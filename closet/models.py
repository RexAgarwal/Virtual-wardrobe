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
