import colorsys
import random
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO

from django.core.files.base import ContentFile
from PIL import Image, ImageDraw, ImageFont

from .models import Item, Outfit, PackItem, PlannedOutfit, Trip, WearLog

C = Item.Category

# royal and neutral palette; name, category, colour, hex, brand, price, formality, tags
PIECES = [
    ('Nude Bodycon Midi', C.DRESS, 'Nude', '#D9B8A3', 'Skims', 98, 4, 'minimal, glam'),
    ('Rhinestone Corset Top', C.TOP, 'Silver', '#C9CCD6', 'Mugler', 420, 4, 'sparkle, sassy'),
    ('Royal Pleated Skirt', C.BOTTOM, 'Royal blue', '#2B3A8F', 'Zara', 55, 3, 'sassy, bold'),
    ('Leather Moto Jacket', C.OUTERWEAR, 'Black', '#25201F', 'AllSaints', 340, 3, 'edgy'),
    ('Faux Fur Chubby Coat', C.OUTERWEAR, 'Blush', '#F2C6CF', 'Zara', 129, 4, 'drama, winter'),
    ('Sculpted Satin Slip', C.DRESS, 'Champagne', '#E5CFA8', 'Reformation', 210, 4, 'evening'),
    ('Lace-Up Knee Boots', C.SHOES, 'Black', '#1D1A1B', 'Balenciaga', 890, 4, 'statement'),
    ('Strappy Stilettos', C.SHOES, 'Nude', '#CFA68C', 'Amina Muaddi', 650, 5, 'heels'),
    ('Oversized Sunnies', C.ACCESSORY, 'Black', '#2B2224', 'Bottega', 380, 2, 'diva'),
    ('Gold Chain Layers', C.ACCESSORY, 'Gold', '#C9A24B', 'Mejuri', 160, 3, 'bling'),
    ('Mesh Glitter Bodysuit', C.TOP, 'Lilac', '#B79BDB', 'Rotate', 275, 4, 'sparkle, pride'),
    ('Rainbow Sequin Blazer', C.OUTERWEAR, 'Rainbow', '#7C5CD6', 'Custom', 310, 4, 'pride, sassy'),
    ('Baby Tee "Mother"', C.TOP, 'White', '#F3EEEA', 'Cotton On', 25, 1, 'casual, cheeky'),
    ('Low-Rise Cargo Pants', C.BOTTOM, 'Khaki', '#A99977', 'Diesel', 220, 2, 'y2k'),
    ('Velvet Opera Gloves', C.ACCESSORY, 'Burgundy', '#6E1F36', 'Vintage', 70, 5, 'drama'),
]

OUTFITS = [
    ('Sunday Brunch', Outfit.Occasion.EVERYDAY, ['Nude Bodycon Midi', 'Oversized Sunnies', 'Strappy Stilettos'],
     'All nude everything. Whisper, do not shout. Then shout.'),
    ('Gala Evening', Outfit.Occasion.OCCASION,
     ['Mesh Glitter Bodysuit', 'Rainbow Sequin Blazer', 'Royal Pleated Skirt', 'Lace-Up Knee Boots'],
     'Jewel tones, gold on top.'),
    ('Date Night, Be Serious', Outfit.Occasion.EVENING,
     ['Sculpted Satin Slip', 'Gold Chain Layers', 'Strappy Stilettos', 'Velvet Opera Gloves'], 'Dinner is the runway.'),
    ('Errands but Make It Fashion', Outfit.Occasion.EVERYDAY,
     ['Baby Tee "Mother"', 'Low-Rise Cargo Pants', 'Oversized Sunnies', 'Leather Moto Jacket'], 'Paparazzi-ready.'),
]


def tile(name, hexcol):
    w, h = 800, 1000
    r, g, b = (int(hexcol[i:i + 2], 16) for i in (1, 3, 5))
    hh, ll, ss = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    top = tuple(int(c * 255) for c in colorsys.hls_to_rgb(hh, min(ll + .18, .95), ss))
    img = Image.new('RGB', (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        k = y / h
        d.line([(0, y), (w, y)], fill=tuple(int(top[i] * (1 - k) + (r, g, b)[i] * k) for i in range(3)))
    rng = random.Random(name)
    d.rectangle([28, 28, w - 29, h - 29], outline=(176, 141, 76), width=3)  # gold keyline
    d.rectangle([40, 40, w - 41, h - 41], outline=(255, 255, 255), width=1)
    font = ImageFont.truetype('/System/Library/Fonts/Supplemental/Georgia Italic.ttf', 64)
    lum = (.299 * r + .587 * g + .114 * b)
    ink = (40, 24, 28) if lum > 150 else (255, 245, 250)
    words, lines, cur = name.split(), [], ''
    for wd in words:
        if d.textlength(f'{cur} {wd}'.strip(), font=font) > w - 120:
            lines.append(cur)
            cur = wd
        else:
            cur = f'{cur} {wd}'.strip()
    lines.append(cur)
    y = h // 2 - len(lines) * 40
    for ln in lines:
        d.text(((w - d.textlength(ln, font=font)) / 2, y), ln, font=font, fill=ink)
        y += 80
    buf = BytesIO()
    img.save(buf, 'PNG')
    return ContentFile(buf.getvalue())


def load_samples(user):
    """Give a user a few sample pieces and outfits so a brand-new wardrobe isn't empty. Safe to repeat."""
    by_name = {}
    for name, cat, colour, hexcol, brand, price, formality, tags in PIECES:
        item = user.items.filter(name=name).first()
        if not item:
            item = Item(owner=user, name=name, category=cat, color=colour, brand=brand, price=Decimal(price),
                        formality=formality, tags=tags)
            item.photo.save(name.replace(' ', '_').replace('"', '') + '.png', tile(name, hexcol))
        by_name[name] = item
    for i, (name, occ, names, notes) in enumerate(OUTFITS):
        o, made = Outfit.objects.get_or_create(owner=user, name=name, defaults=dict(occasion=occ, notes=notes))
        if made:
            o.items.set([by_name[n] for n in names])
            for k in range(i + 1):
                WearLog.objects.get_or_create(outfit=o, date=date.today() - timedelta(days=7 * (k + 1) + i))
    monday = date.today() - timedelta(days=date.today().weekday())
    for k, o in enumerate(user.outfits.all()[:4]):
        PlannedOutfit.objects.get_or_create(owner=user, date=monday + timedelta(days=k * 2), defaults={'outfit': o})
    if not user.trips.exists():
        trip = Trip.objects.create(owner=user, name='Weekend in Paris', destination='Paris',
                                   start=date.today() + timedelta(days=12), end=date.today() + timedelta(days=15))
        for it in list(by_name.values())[:8]:
            PackItem.objects.create(trip=trip, item=it, packed=it.pk % 3 == 0)
