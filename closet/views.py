import random
from datetime import date, timedelta

from django.contrib import messages
from django.db.models import Count, Q
from django.urls import reverse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

import logging
import shutil
import uuid
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from PIL import Image, UnidentifiedImageError

from . import cutout, fitcheck, generator, weather
from .forms import ItemForm, OutfitForm, TripForm
from .models import Item, Outfit, PackItem, PlannedOutfit, Trip, WearLog


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


def outfit_detail(request, pk):
    outfit = get_object_or_404(Outfit.objects.prefetch_related('items', 'wears'), pk=pk, owner=request.user)
    return render(request, 'closet/outfit_detail.html', {'outfit': outfit, 'today': date.today()})


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
    if parts[0] == 'fitcheck':
        allowed = len(parts) == 3 and parts[1] in request.session.get('fitcheck_tokens', [])
    else:
        allowed = request.user.items.filter(Q(photo=path) | Q(other_photo=path)).exists()
    if not allowed:
        raise Http404
    return serve(request, path, document_root=settings.MEDIA_ROOT)
