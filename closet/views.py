import random
import re
from datetime import date, timedelta

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.urls import reverse
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth.decorators import login_not_required
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

import logging
import shutil
import uuid
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from PIL import Image, UnidentifiedImageError

from . import bookmarklet, cutout, fitcheck, generator, linkpreview, tryon, weather
from .features import enabled, feature_required
from .forms import ItemForm, OutfitForm, PerfumeForm, TripForm, WatchItemForm
from .models import ImportToken, Item, Outfit, PackItem, Perfume, WatchDraft, WatchItem, PlannedOutfit, Trip, TryOn, TryOnPhoto, WearLog


def _offer_cutout(item):
    """Make (or remake) the background-free version of an item's picture. True if made.

    It is always cut from the original picture. A first cut-out is kept as the alternative; remaking one that is
    currently in use replaces it in place.
    """
    if not cutout.available():
        return False
    using_cutout = item.photo_is_cutout and bool(item.other_photo)
    try:
        image = Image.open(item.other_photo if using_cutout else item.photo)
        image.load()
    except OSError:
        return False
    result = cutout.cut_out([(image, item.category)])[0]
    if result is None:
        return False
    buf = BytesIO()
    result.save(buf, 'WEBP', quality=88)
    target = item.photo if using_cutout else item.other_photo
    stem = Path((item.other_photo if using_cutout else item.photo).name).stem
    if target:
        target.delete(save=False)
    target.save(f'{stem}-cut.webp', ContentFile(buf.getvalue()))
    return True


def item_photo(request, pk):
    """Choose between the original picture and its cut-out."""
    item = get_object_or_404(Item, pk=pk, owner=request.user)
    if not item.other_photo:
        return redirect(item)
    if request.method == 'POST':
        if request.POST.get('use') == 'other':
            Item.objects.filter(pk=item.pk).update(
                photo=item.other_photo.name, other_photo=item.photo.name, photo_is_cutout=not item.photo_is_cutout)
            messages.success(request, 'Picture updated.')
        return redirect(item)
    return render(request, 'closet/item_photo.html', {'item': item, 'nav': 'items'})


@require_POST
def item_make_cutout(request, pk):
    item = get_object_or_404(Item, pk=pk, owner=request.user)
    if _offer_cutout(item):
        return redirect('closet:item_photo', pk=item.pk)
    messages.error(request, 'Could not make a cut-out for this picture.')
    return redirect(item)


def item_list(request):
    qs = request.user.items.exclude(status=Item.Status.GONE)
    f = {k: request.GET.get(k, '') for k in ('category', 'season', 'status', 'q')}
    if f['category']:
        qs = qs.filter(category=f['category'])
    if f['season']:
        qs = qs.filter(Q(season=f['season']) | Q(season=Item.Season.ALL))
    if f['status']:
        qs = qs.filter(status=f['status'])
    if f['q']:
        qs = qs.filter(Q(name__icontains=f['q']) | Q(color__icontains=f['q']) |
                       Q(tags__icontains=f['q']) | Q(brand__icontains=f['q']))
    return render(request, 'closet/item_list.html', {
        'items': qs, 'filters': f, 'nav': 'items',
        'categories': Item.Category.choices,
        'seasons': Item.Season.choices,
        'statuses': Item.Status.choices,
        'total': request.user.items.exclude(status=Item.Status.GONE).count(),
    })


def item_detail(request, pk):
    item = get_object_or_404(Item, pk=pk, owner=request.user)
    return render(request, 'closet/item_detail.html', {'item': item})


def item_create(request):
    form = ItemForm(request.POST or None, request.FILES or None)
    if form.is_valid():
        item = form.save(commit=False)
        item.owner = request.user
        item.save()
        if _offer_cutout(item):
            messages.success(request, f'Added {item.name}. Choose which picture to keep.')
            return redirect('closet:item_photo', pk=item.pk)
        messages.success(request, f'Added {item.name}.')
        return redirect(item)
    return render(request, 'closet/item_form.html', {'form': form, 'title': 'Add an item'})


def item_edit(request, pk):
    item = get_object_or_404(Item, pk=pk, owner=request.user)
    form = ItemForm(request.POST or None, request.FILES or None, instance=item)
    if form.is_valid():
        form.save()
        if 'photo' in form.changed_data:  # a new picture makes the old alternative stale
            if item.other_photo:
                item.other_photo.delete(save=False)
            item.other_photo = ''
            item.photo_is_cutout = False
            item.save()
            if _offer_cutout(item):
                messages.success(request, 'Saved. Choose which picture to keep.')
                return redirect('closet:item_photo', pk=item.pk)
        messages.success(request, 'Saved.')
        return redirect(item)
    return render(request, 'closet/item_form.html', {'form': form, 'item': item, 'title': item.name})


@require_POST
def item_delete(request, pk):
    item = get_object_or_404(Item, pk=pk, owner=request.user)
    item.photo.delete(save=False)
    if item.other_photo:
        item.other_photo.delete(save=False)
    item.delete()
    messages.success(request, f'Removed {item.name}.')
    return redirect('closet:item_list')


def outfit_list(request):
    occasion = request.GET.get('occasion', '')
    qs = request.user.outfits.prefetch_related('items').annotate(wear_total=Count('wears'))
    if occasion:
        qs = qs.filter(occasion=occasion)
    return render(request, 'closet/outfit_list.html', {
        'outfits': qs, 'nav': 'outfits', 'occasion': occasion, 'occasions': Outfit.Occasion.choices,
    })


BOARD_ORDER = {'top': 0, 'dress': 0, 'bottom': 1, 'shoes': 2}


def _board(items):
    """Arrange an outfit's cut-outs like a figure: top, bottom and shoes down the middle, layers and extras beside.

    Only pieces whose picture is a cut-out go on the board (a photo with a background would show as a box);
    the rest are returned separately so the page can offer to make cut-outs for them.
    """
    cut = [i for i in items if i.photo_is_cutout]
    centre = sorted((i for i in cut if i.category in BOARD_ORDER), key=lambda i: BOARD_ORDER[i.category])
    seen, trimmed = set(), []
    for i in centre:  # one piece per slot: a dress takes the top slot, so it replaces a top
        slot = BOARD_ORDER[i.category]
        if slot not in seen:
            seen.add(slot)
            trimmed.append(i)
    return {
        'centre': trimmed,
        'left': [i for i in cut if i.category == 'outerwear'],
        'right': [i for i in cut if i.category == 'accessory'],
        'left_out': [i for i in items if not i.photo_is_cutout],
    }


def outfit_detail(request, pk):
    outfit = get_object_or_404(Outfit.objects.prefetch_related('items', 'wears'), pk=pk, owner=request.user)
    board = _board(list(outfit.items.all()))
    has_board = bool(board['centre'] or board['left'] or board['right'])
    return render(request, 'closet/outfit_detail.html', {
        'outfit': outfit, 'today': date.today(), 'board': board, 'has_board': has_board})


def outfit_create(request):
    initial = {}
    if 'items' in request.GET:
        initial['items'] = request.GET.getlist('items')
    form = OutfitForm(request.POST or None, initial=initial, user=request.user)
    if form.is_valid():
        outfit = form.save(commit=False)
        outfit.owner = request.user
        outfit.save()
        form.save_m2m()
        messages.success(request, f'Saved outfit {outfit.name}.')
        return redirect(outfit)
    return render(request, 'closet/outfit_form.html', _picker_context(request, form, title='Build an outfit'))


def outfit_edit(request, pk):
    outfit = get_object_or_404(Outfit, pk=pk, owner=request.user)
    form = OutfitForm(request.POST or None, instance=outfit, user=request.user)
    if form.is_valid():
        form.save()
        messages.success(request, 'Saved.')
        return redirect(outfit)
    return render(request, 'closet/outfit_form.html', _picker_context(request, form, outfit=outfit, title=outfit.name))


def _picker_context(request, form, **extra):
    selected = form['items'].value() or []
    selected = {int(v) for v in selected}
    pieces = request.user.items.exclude(status=Item.Status.GONE).order_by('category', 'name')
    return {'form': form, 'pieces': pieces, 'selected': selected, **extra}


@require_POST
def outfit_delete(request, pk):
    outfit = get_object_or_404(Outfit, pk=pk, owner=request.user)
    outfit.delete()
    messages.success(request, f'Deleted {outfit.name}.')
    return redirect('closet:outfit_list')


@require_POST
def outfit_wore(request, pk):
    outfit = get_object_or_404(Outfit, pk=pk, owner=request.user)
    when = request.POST.get('date') or date.today()
    _, created = WearLog.objects.get_or_create(outfit=outfit, date=when)
    messages.success(request, 'Logged.' if created else 'Already logged for that day.')
    return redirect(outfit)


def outfit_surprise(request):
    """Pick a random saved outfit, optionally by occasion."""
    qs = request.user.outfits.all()
    occasion = request.GET.get('occasion')
    if occasion:
        qs = qs.filter(occasion=occasion)
    pks = list(qs.values_list('pk', flat=True))
    if not pks:
        messages.info(request, 'No outfits saved yet. Build one first.')
        return redirect('closet:outfit_create')
    return redirect('closet:outfit_detail', pk=random.choice(pks))


def outfit_generate(request):
    season = request.GET.get('season', '')
    formality = int(request.GET['formality']) if request.GET.get('formality', '').isdigit() else None
    combos, missing = generator.suggest(request.user, 6, season=season, occasion_formality=formality)
    return render(request, 'closet/generate.html', {
        'combos': combos, 'missing': missing, 'season': season, 'formality': formality,
        'seasons': Item.Season.choices, 'nav': 'generate',
        'occasions': Outfit.Occasion.choices,
    })


@require_POST
def outfit_generate_save(request):
    items = request.user.items.filter(pk__in=request.POST.getlist('items'))
    if not items:
        return redirect('closet:outfit_generate')
    outfit = Outfit.objects.create(owner=request.user, name=request.POST.get('name') or 'Fresh combination',
                                   occasion=request.POST.get('occasion') or Outfit.Occasion.EVERYDAY)
    outfit.items.set(items)
    messages.success(request, f'Saved {outfit.name}.')
    return redirect(outfit)


def _monday(d):
    return d - timedelta(days=d.weekday())


def planner(request):
    try:
        anchor = date.fromisoformat(request.GET['start'])
    except (KeyError, ValueError):
        anchor = date.today()
    start = _monday(anchor)
    days = [start + timedelta(days=n) for n in range(7)]
    if 'city' in request.GET:
        request.session['city'] = request.GET['city'].strip()[:80]
    city = request.session.get('city', '')
    spot = weather.geocode(city) if city else None
    forecast = weather.forecast(city, days[0], days[-1]) if spot else {}
    planned = {p.date: p for p in PlannedOutfit.objects.filter(owner=request.user, date__in=days)
               .select_related('outfit').prefetch_related('outfit__items')}
    return render(request, 'closet/planner.html', {
        'nav': 'plan', 'start': start, 'end': days[-1],
        'prev': start - timedelta(days=7), 'next': start + timedelta(days=7),
        'rows': [(d, planned.get(d), forecast.get(d)) for d in days], 'today': date.today(),
        'city': city, 'place': spot[2] if spot else '', 'city_unknown': bool(city) and not spot,
        'out_of_range': bool(spot) and not forecast,
        'outfits': request.user.outfits.all(),
    })


@require_POST
def planner_set(request):
    try:
        day = date.fromisoformat(request.POST['date'])
    except (KeyError, ValueError):
        return redirect('closet:planner')
    outfit_id = request.POST.get('outfit')
    if outfit_id:
        PlannedOutfit.objects.update_or_create(
            owner=request.user, date=day,
            defaults={'outfit': get_object_or_404(Outfit, pk=outfit_id, owner=request.user)})
    else:
        PlannedOutfit.objects.filter(owner=request.user, date=day).delete()
    return redirect(f"{reverse('closet:planner')}?start={_monday(day).isoformat()}")


def trip_list(request):
    return render(request, 'closet/trip_list.html', {
        'nav': 'trips', 'trips': request.user.trips.prefetch_related('packing')})


def _trip_context(request, form, **extra):
    selected = {int(v) for v in (form['items'].value() or [])}
    pieces = request.user.items.exclude(status=Item.Status.GONE).order_by('category', 'name')
    return {'form': form, 'pieces': pieces, 'selected': selected, 'nav': 'trips', **extra}


def _sync_trip(trip, items):
    keep = {i.pk for i in items}
    trip.packing.exclude(item_id__in=keep).delete()
    for i in items:
        PackItem.objects.get_or_create(trip=trip, item=i)


def trip_create(request):
    form = TripForm(request.POST or None, user=request.user)
    if form.is_valid():
        trip = form.save(commit=False)
        trip.owner = request.user
        trip.save()
        _sync_trip(trip, form.cleaned_data['items'])
        messages.success(request, f'Trip to {trip.destination or trip.name} created.')
        return redirect(trip)
    return render(request, 'closet/trip_form.html', _trip_context(request, form, title='Plan a trip'))


def trip_edit(request, pk):
    trip = get_object_or_404(Trip, pk=pk, owner=request.user)
    initial = {'items': trip.items.values_list('pk', flat=True)}
    form = TripForm(request.POST or None, instance=trip, initial=initial, user=request.user)
    if form.is_valid():
        form.save()
        _sync_trip(trip, form.cleaned_data['items'])
        messages.success(request, 'Saved.')
        return redirect(trip)
    return render(request, 'closet/trip_form.html', _trip_context(request, form, trip=trip, title=trip.name))


def trip_detail(request, pk):
    trip = get_object_or_404(Trip, pk=pk, owner=request.user)
    rows = list(trip.packing.select_related('item').order_by('item__category', 'item__name'))
    groups = {}
    for r in rows:
        groups.setdefault(r.item.get_category_display(), []).append(r)
    days = [trip.start + timedelta(days=n) for n in range(trip.nights + 1)]
    forecast = weather.forecast(trip.destination, trip.start, trip.end) if trip.destination else {}
    return render(request, 'closet/trip_detail.html', {
        'forecast': [(d, forecast[d]) for d in days if d in forecast],
        'tips': weather.packing_tips(list(forecast.values())),
        'nav': 'trips', 'trip': trip, 'groups': groups, 'total': len(rows),
        'packed': sum(r.packed for r in rows)})


@require_POST
def trip_toggle(request, pk, item_pk):
    row = get_object_or_404(PackItem, trip_id=pk, trip__owner=request.user, item_id=item_pk)
    row.packed = not row.packed
    row.save(update_fields=['packed'])
    return redirect('closet:trip_detail', pk=pk)


@require_POST
def trip_delete(request, pk):
    get_object_or_404(Trip, pk=pk, owner=request.user).delete()
    return redirect('closet:trip_list')


MAX_UPLOAD = 15 * 1024 * 1024


def _fitcheck_dir(token):
    return Path(settings.MEDIA_ROOT) / 'fitcheck' / token


def fitcheck_start(request):
    context = {'nav': 'fitcheck', 'ready': fitcheck.ml_ready() or bool(settings.ANTHROPIC_API_KEY)}
    if request.method == 'POST':
        upload = request.FILES.get('photo')
        if not upload:
            messages.error(request, 'Choose a photo first.')
        elif upload.size > MAX_UPLOAD:
            messages.error(request, 'That photo is over 15 MB. Try a smaller one.')
        else:
            try:
                image = Image.open(upload)
                image.load()
                found = fitcheck.detect(image)
            except (UnidentifiedImageError, OSError):
                messages.error(request, 'That file is not an image I can read.')
            except fitcheck.NotConfigured as e:
                messages.error(request, str(e))
            except Exception:
                logging.getLogger(__name__).exception('Fit Check detection failed')
                messages.error(request, 'Fit Check could not reach the vision service. Try again in a moment.')
            else:
                if not found:
                    messages.info(request, 'No separate pieces found. Try a photo where the outfit is clearly visible.')
                else:
                    return _fitcheck_review(request, image, found)
    return render(request, 'closet/fitcheck_start.html', context)


def _fitcheck_review(request, image, found):
    token = uuid.uuid4().hex
    folder = _fitcheck_dir(token)
    folder.mkdir(parents=True)
    request.session['fitcheck_tokens'] = (request.session.get('fitcheck_tokens', []) + [token])[-5:]
    pieces = []
    for n, raw in enumerate(found):
        crop = fitcheck.crop(image, raw['box'])
        crop.save(folder / f'{n}.jpg', 'JPEG', quality=90)
        pieces.append({'n': n, **fitcheck.clean(raw), 'url': f'{settings.MEDIA_URL}fitcheck/{token}/{n}.jpg'})
    crops = [Image.open(folder / f'{p["n"]}.jpg') for p in pieces]
    for piece, result in zip(pieces, cutout.cut_out([(c, p['category']) for c, p in zip(crops, pieces)])):
        if result is not None:
            result.save(folder / f'{piece["n"]}_cut.png')
            piece['cut_url'] = f'{settings.MEDIA_URL}fitcheck/{token}/{piece["n"]}_cut.png'
    return render(request, 'closet/fitcheck_review.html', {
        'nav': 'fitcheck', 'token': token, 'pieces': pieces, 'categories': Item.Category.choices})


@require_POST
def fitcheck_add(request):
    token = request.POST.get('token', '')
    mine = token in request.session.get('fitcheck_tokens', [])
    folder = _fitcheck_dir(token) if mine and token.isalnum() and len(token) == 32 else None
    if not folder or not folder.is_dir():
        messages.error(request, 'That Fit Check expired. Upload the photo again.')
        return redirect('closet:fitcheck')
    added = []
    for key in request.POST.getlist('keep'):
        if not key.isdigit() or not (folder / f'{key}.jpg').is_file():
            continue
        fields = fitcheck.clean({
            'name': request.POST.get(f'name_{key}'), 'category': request.POST.get(f'category_{key}'),
            'color': request.POST.get(f'color_{key}'), 'brand': request.POST.get(f'brand_{key}'),
            'formality': request.POST.get(f'formality_{key}'), 'tags': request.POST.get(f'tags_{key}')})
        orig, cut = folder / f'{key}.jpg', folder / f'{key}_cut.png'
        use_cut = cut.is_file() and request.POST.get(f'pick_{key}', 'cut') == 'cut'
        main, other = (cut, orig) if use_cut else (orig, cut if cut.is_file() else None)
        item = Item(owner=request.user, photo_is_cutout=use_cut, **fields)
        item.photo.save(f'{token[:8]}-{key}{main.suffix}', ContentFile(main.read_bytes()))
        if other:
            item.other_photo.save(f'{token[:8]}-{key}-alt{other.suffix}', ContentFile(other.read_bytes()))
        added.append(item)
    shutil.rmtree(folder, ignore_errors=True)
    request.session['fitcheck_tokens'] = [t for t in request.session.get('fitcheck_tokens', []) if t != token]
    if not added:
        messages.info(request, 'Nothing added.')
        return redirect('closet:fitcheck')
    messages.success(request, f"Added {len(added)} piece{'s' if len(added) != 1 else ''} to your wardrobe.")
    return redirect('closet:item_list')


def about(request):
    return render(request, 'closet/about.html', {'nav': 'about'})


@require_POST
def load_sample_pieces(request):
    from .samples import load_samples
    load_samples(request.user)
    messages.success(request, 'Added a few sample pieces and outfits to try things out. Delete them any time.')
    return redirect('closet:item_list')


def media(request, path):
    """Photos are private: a piece's picture only goes to its owner, a pending Fit check crop to the session that made it."""
    from django.http import Http404
    from django.views.static import serve
    parts = path.split('/')
    if parts[0] == 'perfumes':
        allowed = request.user.perfumes.filter(photo=path).exists()
    elif parts[0] == 'watchlist':
        allowed = request.user.watchlist.filter(photo=path).exists()
    elif parts[0] == 'tryon':
        allowed = (TryOnPhoto.objects.filter(owner=request.user, photo=path).exists()
                   or TryOn.objects.filter(owner=request.user, result=path).exists())
    elif parts[0] == 'fitcheck':
        allowed = len(parts) == 3 and parts[1] in request.session.get('fitcheck_tokens', [])
    else:
        allowed = request.user.items.filter(Q(photo=path) | Q(other_photo=path)).exists()
    if not allowed:
        raise Http404
    return serve(request, path, document_root=settings.MEDIA_ROOT)


# --- Try on (beta) -------------------------------------------------------------------------------------------

@feature_required('tryon')
def tryon_home(request):
    photo = TryOnPhoto.objects.filter(owner=request.user).first()
    if request.method == 'POST':
        if request.POST.get('remove') and photo:
            photo.photo.delete(save=False)
            photo.delete()
            messages.success(request, 'Your photo was removed.')
            return redirect('closet:tryon')
        upload = request.FILES.get('photo')
        if not upload or upload.size > MAX_UPLOAD:
            messages.error(request, 'Choose a photo under 15 MB.')
        else:
            try:
                img = Image.open(upload)
                img.load()
                from PIL import ImageOps
                img = ImageOps.exif_transpose(img).convert('RGB')
            except (UnidentifiedImageError, OSError):
                messages.error(request, 'That file is not an image I can read.')
            else:
                img.thumbnail((1024, 1024))
                buf = BytesIO()
                img.save(buf, 'JPEG', quality=92)
                photo = photo or TryOnPhoto(owner=request.user)
                if photo.photo:
                    photo.photo.delete(save=False)
                photo.photo.save(f'{request.user.pk}.jpg', ContentFile(buf.getvalue()))
                messages.success(request, 'Saved your photo.')
                return redirect('closet:tryon')
    return render(request, 'closet/tryon_home.html', {
        'nav': 'tryon', 'photo': photo, 'jobs': request.user.tryons.select_related('outfit')[:12],
        'ready': tryon.available()})


@feature_required('tryon')
@require_POST
def tryon_start(request, pk):
    outfit = get_object_or_404(Outfit, pk=pk, owner=request.user)
    if not TryOnPhoto.objects.filter(owner=request.user).exists():
        messages.info(request, 'Add a full-body photo of yourself first.')
        return redirect('closet:tryon')
    if not tryon.garments_for(outfit):
        messages.error(request, 'This outfit needs a top, a bottom or a dress to try on.')
        return redirect(outfit)
    if not tryon.available():
        messages.error(request, 'The try-on model is not installed on this computer yet.')
        return redirect(outfit)
    job = TryOn.objects.create(owner=request.user, outfit=outfit)
    tryon.start(job)
    return redirect(job)


@feature_required('tryon')
def tryon_job(request, pk):
    job = get_object_or_404(TryOn.objects.select_related('outfit'), pk=pk, owner=request.user)
    return render(request, 'closet/tryon_job.html', {'nav': 'tryon', 'job': job})


@feature_required('tryon')
@require_POST
def tryon_delete(request, pk):
    job = get_object_or_404(TryOn, pk=pk, owner=request.user)
    if job.result:
        job.result.delete(save=False)
    job.delete()
    return redirect('closet:tryon')


# --- Perfumes (beta) -----------------------------------------------------------------------------------------

@feature_required('perfumes')
def perfume_list(request):
    qs = request.user.perfumes.all()
    f = {k: request.GET.get(k, '') for k in ('family', 'season', 'status', 'q')}
    if f['family']:
        qs = qs.filter(family=f['family'])
    if f['season']:
        qs = qs.filter(Q(season=f['season']) | Q(season=Item.Season.ALL))
    if f['status']:
        qs = qs.filter(status=f['status'])
    if f['q']:
        qs = qs.filter(Q(name__icontains=f['q']) | Q(brand__icontains=f['q']) | Q(notes__icontains=f['q']))
    return render(request, 'closet/perfume_list.html', {
        'perfumes': qs, 'filters': f, 'nav': 'perfumes', 'total': request.user.perfumes.count(),
        'families': Perfume.Family.choices, 'seasons': Item.Season.choices, 'statuses': Perfume.Status.choices})


@feature_required('perfumes')
def perfume_detail(request, pk):
    perfume = get_object_or_404(Perfume, pk=pk, owner=request.user)
    return render(request, 'closet/perfume_detail.html', {'perfume': perfume, 'nav': 'perfumes'})


@feature_required('perfumes')
def perfume_create(request):
    form = PerfumeForm(request.POST or None, request.FILES or None)
    if form.is_valid():
        perfume = form.save(commit=False)
        perfume.owner = request.user
        perfume.save()
        messages.success(request, f'Added {perfume}.')
        return redirect(perfume)
    return render(request, 'closet/perfume_form.html', {'form': form, 'title': 'Add a perfume', 'nav': 'perfumes'})


@feature_required('perfumes')
def perfume_edit(request, pk):
    perfume = get_object_or_404(Perfume, pk=pk, owner=request.user)
    form = PerfumeForm(request.POST or None, request.FILES or None, instance=perfume)
    if form.is_valid():
        form.save()
        messages.success(request, 'Saved.')
        return redirect(perfume)
    return render(request, 'closet/perfume_form.html', {
        'form': form, 'perfume': perfume, 'title': perfume.name, 'nav': 'perfumes'})


@feature_required('perfumes')
@require_POST
def perfume_delete(request, pk):
    perfume = get_object_or_404(Perfume, pk=pk, owner=request.user)
    if perfume.photo:
        perfume.photo.delete(save=False)
    name = str(perfume)
    perfume.delete()
    messages.success(request, f'Removed {name}.')
    return redirect('closet:perfume_list')


# --- Watchlist (beta) ----------------------------------------------------------------------------------------

@feature_required('watchlist')
def watch_list(request):
    status = request.GET.get('status', 'watching')
    qs = request.user.watchlist.all()
    if status in WatchItem.Status.values:
        qs = qs.filter(status=status)
    kind = request.GET.get('kind', '')
    if kind:
        qs = qs.filter(kind=kind)
    totals = {}  # what it would cost to buy everything shown, per currency (mixing currencies would be wrong)
    for w in qs:
        if w.price is not None and w.status == WatchItem.Status.WATCHING:
            totals[w.currency or '-'] = totals.get(w.currency or '-', 0) + w.price
    symbol = WatchItem.SYMBOLS
    totals = [f"{symbol.get(c, c + ' ' if c != '-' else '')}{t:,.0f}" for c, t in totals.items()]
    return render(request, 'closet/watch_list.html', {
        'items': qs, 'status': status, 'kind': kind, 'nav': 'watchlist', 'totals': totals,
        'statuses': WatchItem.Status.choices, 'kinds': WatchItem.Kind.choices,
        'total': request.user.watchlist.count(), 'drafts': request.user.watch_drafts.all()})


@feature_required('watchlist')
def watch_add(request):
    """Step 1 is an optional link box that fills in what it can; step 2 is the form, always editable."""
    initial, shown_image = {}, ''
    if request.method == 'POST' and 'fetch_url' in request.POST:
        url = request.POST['fetch_url'].strip()
        initial = {'url': url}
        try:
            info = linkpreview.fetch(url)
        except linkpreview.LinkError as e:
            messages.info(request, f'{e} Fill in the details below instead; the link is kept.')
        else:
            initial.update(name=info['name'], price=info['price'] or None, currency=info['currency'],
                           image_url=info['image_url'])
            shown_image = info['image_url']
            got = [x for x, ok in (('name', info['name']), ('price', info['price']), ('picture', info['image_url'])) if ok]
            missing = [x for x in ('name', 'price', 'picture') if x not in got]
            messages.success(request, 'Found: ' + ', '.join(got) + '.' + (f' Not found: {", ".join(missing)}. Add them below.' if missing else ''))
        return render(request, 'closet/watch_form.html', {
            'form': WatchItemForm(initial=initial), 'title': 'Add to your watchlist', 'nav': 'watchlist',
            'shown_image': shown_image})
    form = WatchItemForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        item = form.save(commit=False)
        item.owner = request.user
        wanted_image = form.cleaned_data.get('image_url')
        if wanted_image and not request.FILES.get('photo'):
            try:
                data = linkpreview.fetch_image(wanted_image)
                Image.open(BytesIO(data)).verify()  # a shop 'picture' can be an SVG or an error page; refuse those here
                item.photo.save('link.img', ContentFile(data), save=False)
            except (linkpreview.LinkError, OSError, ValueError, SyntaxError):
                messages.info(request, 'Saved without the shop picture. You can add your own.')
        item.save()
        try:
            WatchDraft.objects.filter(pk=request.POST.get('draft'), owner=request.user).delete()
        except (ValueError, ValidationError):
            pass
        messages.success(request, f'Added {item.name} to your watchlist.')
        return redirect(item)
    return render(request, 'closet/watch_start.html' if request.method == 'GET' else 'closet/watch_form.html', {
        'form': form, 'title': 'Add to your watchlist', 'nav': 'watchlist'})


@feature_required('watchlist')
def watch_manual(request):
    return render(request, 'closet/watch_form.html', {
        'form': WatchItemForm(), 'title': 'Add to your watchlist', 'nav': 'watchlist'})


@feature_required('watchlist')
def watch_detail(request, pk):
    item = get_object_or_404(WatchItem, pk=pk, owner=request.user)
    return render(request, 'closet/watch_detail.html', {'item': item, 'nav': 'watchlist'})


@feature_required('watchlist')
def watch_edit(request, pk):
    item = get_object_or_404(WatchItem, pk=pk, owner=request.user)
    form = WatchItemForm(request.POST or None, request.FILES or None, instance=item)
    if form.is_valid():
        form.save()
        messages.success(request, 'Saved.')
        return redirect(item)
    return render(request, 'closet/watch_form.html', {'form': form, 'item': item, 'title': item.name, 'nav': 'watchlist'})


@feature_required('watchlist')
@require_POST
def watch_delete(request, pk):
    item = get_object_or_404(WatchItem, pk=pk, owner=request.user)
    if item.photo:
        item.photo.delete(save=False)
    item.delete()
    messages.success(request, f'Removed {item.name}.')
    return redirect('closet:watch_list')


@feature_required('watchlist')
@require_POST
def watch_bought(request, pk):
    """Mark it bought and, for clothes and perfume, start the real entry so the photo and price carry over."""
    watch = get_object_or_404(WatchItem, pk=pk, owner=request.user)
    watch.status = WatchItem.Status.BOUGHT
    watch.save(update_fields=['status'])
    clothing = {c for c in Item.Category.values}
    if watch.kind in clothing and watch.photo:
        item = Item(owner=request.user, name=watch.name, category=watch.kind, price=watch.price, notes=watch.notes)
        item.photo.save('watch.img', ContentFile(watch.photo.read()))
        messages.success(request, 'Marked as bought and added to your wardrobe. Check the details.')
        return redirect('closet:item_edit', pk=item.pk)
    if watch.kind == 'perfume':
        perfume = Perfume(owner=request.user, name=watch.name, price=watch.price, comments=watch.notes)
        if watch.photo:
            perfume.photo.save('watch.img', ContentFile(watch.photo.read()), save=False)
        perfume.save()
        messages.success(request, 'Marked as bought and added to your perfumes. Check the details.')
        return redirect('closet:perfume_edit', pk=perfume.pk)
    messages.success(request, 'Marked as bought.')
    return redirect(watch)


_SYMBOLS = {'\u20b9': 'INR', 'Rs': 'INR', 'INR': 'INR', '$': 'USD', '\u20ac': 'EUR', '\u00a3': 'GBP'}
MAX_DRAFTS = 30


@csrf_exempt
@login_not_required
@require_POST
def watch_import(request):
    """Receives what the browser button read off a shop page. Identified by the person's button token, not their
    login (the post comes from another website, so their login cookie isn't sent). It only ever creates a draft."""
    from django.http import HttpResponseForbidden
    token = ImportToken.objects.select_related('owner').filter(token=request.POST.get('token', '')[:64]).first()
    if not token or not enabled('watchlist', token.owner):
        return HttpResponseForbidden('This save button is not valid. Make a new one from your Watchlist.')
    user, post = token.owner, request.POST
    raw_price = post.get('price', '')[:40]
    currency = post.get('currency', '').strip().upper()[:3]
    if not currency:
        currency = next((code for sym, code in _SYMBOLS.items() if sym in raw_price), '')
    image = post.get('image', '').strip()
    url = post.get('url', '').strip()
    clean = lambda u: u if u.lower().startswith(('http://', 'https://')) else ''
    name = re.sub(r'\s*[:|]\s*Amazon\.[a-z.]+.*$', '', re.sub(r'\s+', ' ', post.get('name', '')).strip(), flags=re.I)
    draft = WatchDraft.objects.create(
        owner=user, url=clean(url)[:1000], name=name[:120], price=linkpreview._number(raw_price),
        currency=currency, image_url=clean(image)[:1000])
    old = user.watch_drafts.all()[MAX_DRAFTS:]  # keep the newest few; drafts are throw-away
    WatchDraft.objects.filter(pk__in=[d.pk for d in old]).delete()
    return redirect('closet:watch_draft', pk=draft.pk)


@feature_required('watchlist')
@require_POST
def watch_draft_discard(request, pk):
    get_object_or_404(WatchDraft, pk=pk, owner=request.user).delete()
    return redirect('closet:watch_list')


@feature_required('watchlist')
def watch_draft(request, pk):
    draft = get_object_or_404(WatchDraft, pk=pk, owner=request.user)
    initial = {'url': draft.url, 'name': draft.name, 'price': draft.price or None, 'currency': draft.currency,
               'image_url': draft.image_url}
    got = [x for x, ok in (('name', draft.name), ('price', draft.price), ('picture', draft.image_url)) if ok]
    if got:
        messages.success(request, 'Read from the shop page: ' + ', '.join(got) + '. Check it, then save.')
    else:
        messages.info(request, 'Nothing could be read from that page. Fill in the details below.')
    return render(request, 'closet/watch_form.html', {
        'form': WatchItemForm(initial=initial), 'title': 'Save to your watchlist', 'nav': 'watchlist',
        'shown_image': draft.image_url, 'draft': draft})


@feature_required('watchlist')
def watch_button(request):
    """Setup page for the browser button, with this person's own secret built in."""
    if request.method == 'POST':
        ImportToken.reset(request.user)
        messages.success(request, 'Made a new button. The old one has stopped working, so replace it in your browser.')
        return redirect('closet:watch_button')
    token = getattr(request.user, 'import_token', None) or ImportToken.reset(request.user)
    origin = f'{request.scheme}://{request.get_host()}'
    return render(request, 'closet/watch_button.html', {
        'nav': 'watchlist', 'origin': origin, 'link': bookmarklet.as_link(origin, token.token),
        'raw': bookmarklet.code(origin, token.token), 'local': request.get_host().startswith(('127.', 'localhost'))})
