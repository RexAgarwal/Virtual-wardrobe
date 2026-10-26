import uuid
from io import BytesIO

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import models
from django.urls import reverse
from PIL import Image, ImageOps


class Item(models.Model):
    class Category(models.TextChoices):
        TOP = 'top', 'Top'
        BOTTOM = 'bottom', 'Bottom'
        DRESS = 'dress', 'Dress'
        OUTERWEAR = 'outerwear', 'Outerwear'
        SHOES = 'shoes', 'Shoes'
        ACCESSORY = 'accessory', 'Accessory'

    class Season(models.TextChoices):
        ALL = 'all', 'All year'
        SUMMER = 'summer', 'Summer'
        WINTER = 'winter', 'Winter'
        MONSOON = 'monsoon', 'Monsoon'

    class Status(models.TextChoices):
        ACTIVE = 'active', 'In wardrobe'
        LAUNDRY = 'laundry', 'In laundry'
        STORED = 'stored', 'Stored away'
        GONE = 'gone', 'Donated or sold'

    name = models.CharField(max_length=120)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='items')
    photo = models.ImageField(upload_to='items/%Y/%m/')
    # The other version of the picture (original or cut-out), kept so the owner can switch
    other_photo = models.ImageField(upload_to='items/%Y/%m/', blank=True)
    photo_is_cutout = models.BooleanField(default=False)
    category = models.CharField(max_length=20, choices=Category.choices)
    color = models.CharField(max_length=40, blank=True)
    season = models.CharField(max_length=20, choices=Season.choices, default=Season.ALL)
    formality = models.PositiveSmallIntegerField(
        default=2, help_text='1 = very casual, 5 = formal')
    brand = models.CharField(max_length=80, blank=True)
    price = models.DecimalField(max_digits=9, decimal_places=2, null=True, blank=True)
    tags = models.CharField(max_length=200, blank=True, help_text='Comma separated')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    notes = models.TextField(blank=True)
    added = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-added']

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('closet:item_detail', args=[self.pk])

    @property
    def tag_list(self):
        return [t.strip() for t in self.tags.split(',') if t.strip()]

    @property
    def wear_count(self):
        return WearLog.objects.filter(outfit__items=self).count()

    @property
    def cost_per_wear(self):
        if self.price and self.wear_count:
            return self.price / self.wear_count
        return None

    def save(self, *args, **kwargs):
        for field in ('photo', 'other_photo'):
            f = getattr(self, field)
            if f and not f.name.endswith('.webp'):
                setattr(self, field, self._shrink(f))
        super().save(*args, **kwargs)

    @staticmethod
    def _shrink(uploaded):
        img = ImageOps.exif_transpose(Image.open(uploaded))
        img = img.convert('RGBA' if 'A' in img.getbands() or img.mode == 'P' else 'RGB')  # cut-outs keep transparency
        img.thumbnail((settings.WARDROBE_IMAGE_MAX,) * 2)
        buf = BytesIO()
        img.save(buf, 'WEBP', quality=82)
        stem = uploaded.name.rsplit('.', 1)[0].rsplit('/', 1)[-1]
        return ContentFile(buf.getvalue(), name=f'{stem}.webp')


class Outfit(models.Model):
    class Occasion(models.TextChoices):
        EVERYDAY = 'everyday', 'Everyday'
        WORK = 'work', 'Work'
        EVENING = 'evening', 'Evening'
        OCCASION = 'occasion', 'Special occasion'
        TRAVEL = 'travel', 'Travel'
        SPORT = 'sport', 'Active'

    name = models.CharField(max_length=120)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='outfits')
    items = models.ManyToManyField(Item, related_name='outfits')
    occasion = models.CharField(max_length=20, choices=Occasion.choices, default=Occasion.EVERYDAY)
    notes = models.TextField(blank=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created']

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('closet:outfit_detail', args=[self.pk])

    @property
    def last_worn(self):
        log = self.wears.first()
        return log.date if log else None


class WearLog(models.Model):
    outfit = models.ForeignKey(Outfit, on_delete=models.CASCADE, related_name='wears')
    date = models.DateField()

    class Meta:
        ordering = ['-date']
        unique_together = [('outfit', 'date')]

    def __str__(self):
        return f'{self.outfit} on {self.date}'


class PlannedOutfit(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='plans')
    date = models.DateField()
    outfit = models.ForeignKey(Outfit, on_delete=models.CASCADE, related_name='planned')

    class Meta:
        ordering = ['date']
        unique_together = [('owner', 'date')]

    def __str__(self):
        return f'{self.outfit} planned for {self.date}'


class Trip(models.Model):
    name = models.CharField(max_length=120)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='trips')
    destination = models.CharField(max_length=120, blank=True)
    start = models.DateField()
    end = models.DateField()
    items = models.ManyToManyField(Item, through='PackItem', related_name='trips')

    class Meta:
        ordering = ['-start']

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('closet:trip_detail', args=[self.pk])

    @property
    def nights(self):
        return (self.end - self.start).days

    @property
    def packed_count(self):
        return self.packing.filter(packed=True).count()


class PackItem(models.Model):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='packing')
    item = models.ForeignKey(Item, on_delete=models.CASCADE)
    packed = models.BooleanField(default=False)

    class Meta:
        unique_together = [('trip', 'item')]


class TryOnPhoto(models.Model):
    """The full-body photo a person uses for virtual try-on. One per account."""
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='tryon_photo')
    photo = models.ImageField(upload_to='tryon/people/')
    updated = models.DateTimeField(auto_now=True)


class TryOn(models.Model):
    class Status(models.TextChoices):
        QUEUED = 'queued', 'Waiting'
        RUNNING = 'running', 'Dressing you'
        DONE = 'done', 'Ready'
        FAILED = 'failed', 'Failed'

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='tryons')
    outfit = models.ForeignKey(Outfit, on_delete=models.CASCADE, related_name='tryons')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    result = models.ImageField(upload_to='tryon/results/', blank=True)
    message = models.CharField(max_length=300, blank=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created']

    @property
    def pending(self):
        return self.status in (self.Status.QUEUED, self.Status.RUNNING)

    def get_absolute_url(self):
        return reverse('closet:tryon_job', args=[self.pk])


class Perfume(models.Model):
    class Concentration(models.TextChoices):
        PARFUM = 'parfum', 'Parfum'
        EDP = 'edp', 'Eau de parfum'
        EDT = 'edt', 'Eau de toilette'
        EDC = 'edc', 'Eau de cologne'
        OTHER = 'other', 'Other'

    class Family(models.TextChoices):
        FRESH = 'fresh', 'Fresh'
        CITRUS = 'citrus', 'Citrus'
        FLORAL = 'floral', 'Floral'
        WOODY = 'woody', 'Woody'
        ORIENTAL = 'oriental', 'Oriental and amber'
        GOURMAND = 'gourmand', 'Gourmand'
        AROMATIC = 'aromatic', 'Aromatic'
        SPICY = 'spicy', 'Spicy'
        AQUATIC = 'aquatic', 'Aquatic'
        LEATHER = 'leather', 'Leather and oud'

    class Status(models.TextChoices):
        IN_USE = 'in_use', 'In use'
        WISHLIST = 'wishlist', 'Wishlist'
        FINISHED = 'finished', 'Finished'

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='perfumes')
    name = models.CharField(max_length=120)
    brand = models.CharField(max_length=80, blank=True)
    photo = models.ImageField(upload_to='perfumes/%Y/%m/', blank=True)
    concentration = models.CharField(max_length=10, choices=Concentration.choices, default=Concentration.EDP)
    family = models.CharField(max_length=10, choices=Family.choices, blank=True)
    notes = models.CharField(max_length=200, blank=True, help_text='Scent notes, comma separated, e.g. bergamot, rose, vanilla')
    season = models.CharField(max_length=10, choices=Item.Season.choices, default=Item.Season.ALL)
    occasion = models.CharField(max_length=10, choices=Outfit.Occasion.choices, default=Outfit.Occasion.EVERYDAY)
    size_ml = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name='Size (ml)')
    price = models.DecimalField(max_digits=9, decimal_places=2, null=True, blank=True)
    rating = models.PositiveSmallIntegerField(default=0, help_text='0 = not rated, 5 = favourite')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.IN_USE)
    comments = models.TextField(blank=True)
    added = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['brand', 'name']

    def __str__(self):
        return f'{self.brand} {self.name}'.strip()

    def get_absolute_url(self):
        return reverse('closet:perfume_detail', args=[self.pk])

    @property
    def note_list(self):
        return [n.strip() for n in self.notes.split(',') if n.strip()]

    @property
    def stars(self):
        return '★' * self.rating + '☆' * (5 - self.rating) if self.rating else ''

    def save(self, *args, **kwargs):
        if self.photo and not self.photo.name.endswith('.webp'):
            self.photo = Item._shrink(self.photo)
        super().save(*args, **kwargs)


class WatchItem(models.Model):
    """Something the owner wants to buy later: clothes, shoes, a perfume, anything."""

    class Kind(models.TextChoices):
        TOP = 'top', 'Top'
        BOTTOM = 'bottom', 'Bottom'
        DRESS = 'dress', 'Dress'
        OUTERWEAR = 'outerwear', 'Outerwear'
        SHOES = 'shoes', 'Shoes'
        ACCESSORY = 'accessory', 'Accessory'
        PERFUME = 'perfume', 'Perfume'
        OTHER = 'other', 'Something else'

    class Priority(models.IntegerChoices):
        MUST = 1, 'Must have'
        WANT = 2, 'Want'
        MAYBE = 3, 'Maybe'

    class Status(models.TextChoices):
        WATCHING = 'watching', 'Watching'
        BOUGHT = 'bought', 'Bought'
        DROPPED = 'dropped', 'Dropped'

    SYMBOLS = {'INR': '\u20b9', 'USD': '$', 'EUR': '\u20ac', 'GBP': '\u00a3', 'AED': 'AED ', 'JPY': '\u00a5'}

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='watchlist')
    name = models.CharField(max_length=120)
    url = models.URLField(max_length=1000, blank=True, verbose_name='Link')
    site = models.CharField(max_length=80, blank=True)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.TOP)
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=3, blank=True, help_text='e.g. INR, USD')
    photo = models.ImageField(upload_to='watchlist/%Y/%m/', blank=True)
    priority = models.PositiveSmallIntegerField(choices=Priority.choices, default=Priority.WANT)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.WATCHING)
    notes = models.TextField(blank=True)
    added = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['priority', '-added']

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('closet:watch_detail', args=[self.pk])

    @property
    def price_label(self):
        if self.price is None:
            return ''
        from decimal import Decimal
        price = Decimal(str(self.price))  # may still be text right after being set from a form
        symbol = self.SYMBOLS.get(self.currency, f'{self.currency} ' if self.currency else '')
        return f'{symbol}{price:,.0f}' if price == price.to_integral() else f'{symbol}{price:,.2f}'

    def save(self, *args, **kwargs):
        if self.photo and not self.photo.name.endswith('.webp'):
            self.photo = Item._shrink(self.photo)
        if self.url and not self.site:
            from urllib.parse import urlsplit
            self.site = (urlsplit(self.url).hostname or '').removeprefix('www.')[:80]
        super().save(*args, **kwargs)


class ImportToken(models.Model):
    """A secret that lets a person's "save to watchlist" browser button add drafts to their account (and nothing else)."""
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='import_token')
    token = models.CharField(max_length=64, unique=True)
    created = models.DateTimeField(auto_now_add=True)

    @classmethod
    def reset(cls, user):
        import secrets
        obj, _ = cls.objects.update_or_create(owner=user, defaults={'token': secrets.token_urlsafe(32)})
        return obj


class WatchDraft(models.Model):
    """What the browser button found on a shop page. Nothing is on the watchlist until its owner reviews and saves it."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='watch_drafts')
    url = models.URLField(max_length=1000, blank=True)
    name = models.CharField(max_length=120, blank=True)
    price = models.CharField(max_length=40, blank=True)
    currency = models.CharField(max_length=3, blank=True)
    image_url = models.URLField(max_length=1000, blank=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created']
