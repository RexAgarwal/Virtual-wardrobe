"""Rule-based outfit suggestions: no AI service, just colour, season and formality sense."""
import random

from .models import Item

NEUTRALS = {'black', 'white', 'beige', 'nude', 'grey', 'gray', 'khaki', 'cream',
            'champagne', 'navy', 'brown', 'tan', 'camel', 'ivory', 'silver', 'gold'}
C = Item.Category


def _tone(item):
    return item.color.strip().lower()


def _chromatic(items):
    """Distinct non-neutral colours in a candidate outfit."""
    return {_tone(i) for i in items if _tone(i) and _tone(i) not in NEUTRALS}


def _near(pool, formality):
    close = [i for i in pool if abs(i.formality - formality) <= 1]
    return close or pool


def suggest(user, count=6, season='', occasion_formality=None):
    pool = list(user.items.filter(status=Item.Status.ACTIVE))
    if season:
        pool = [i for i in pool if i.season in (season, Item.Season.ALL)]
    by = {c: [i for i in pool if i.category == c] for c in C.values}
    one_piece = by[C.DRESS]
    tops, bottoms = by[C.TOP], by[C.BOTTOM]
    if not one_piece and not (tops and bottoms):
        return []

    results, seen = [], set()
    for _ in range(300):
        if len(results) >= count:
            break
        f = occasion_formality or random.choice([i.formality for i in pool])
        if one_piece and (not (tops and bottoms) or random.random() < .35):
            base = [random.choice(_near(one_piece, f))]
        else:
            base = [random.choice(_near(tops, f)), random.choice(_near(bottoms, f))]
        extras = []
        for cat, odds in ((C.SHOES, .95), (C.OUTERWEAR, .45), (C.ACCESSORY, .6)):
            if by[cat] and random.random() < odds:
                extras.append(random.choice(_near(by[cat], f)))
        combo = base + extras
        if len(_chromatic(combo)) > 2:
            continue
        key = frozenset(i.pk for i in combo)
        if key in seen:
            continue
        seen.add(key)
        results.append(combo)
    return results
