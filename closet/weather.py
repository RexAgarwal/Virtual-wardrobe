"""Daily forecasts from Open-Meteo (free, no API key). Every call fails soft: no network, no weather."""
import json
import urllib.parse
import urllib.request
from datetime import date

from django.core.cache import cache

GEO = 'https://geocoding-api.open-meteo.com/v1/search'
FORECAST = 'https://api.open-meteo.com/v1/forecast'
HORIZON_DAYS = 16  # how far ahead the API will go

# WMO weather code -> (label, hint for what to wear)
CODES = {
    0: ('Clear', 'sun'), 1: ('Mostly clear', 'sun'), 2: ('Partly cloudy', 'cloud'), 3: ('Overcast', 'cloud'),
    45: ('Fog', 'cloud'), 48: ('Fog', 'cloud'),
    51: ('Drizzle', 'rain'), 53: ('Drizzle', 'rain'), 55: ('Drizzle', 'rain'),
    61: ('Rain', 'rain'), 63: ('Rain', 'rain'), 65: ('Heavy rain', 'rain'),
    71: ('Snow', 'snow'), 73: ('Snow', 'snow'), 75: ('Heavy snow', 'snow'), 77: ('Snow', 'snow'),
    80: ('Showers', 'rain'), 81: ('Showers', 'rain'), 82: ('Heavy showers', 'rain'),
    95: ('Thunderstorm', 'rain'), 96: ('Thunderstorm', 'rain'), 99: ('Thunderstorm', 'rain'),
}
ICONS = {'sun': '☀', 'cloud': '☁', 'rain': '☂', 'snow': '❄'}


def _get(url, params):
    full = f'{url}?{urllib.parse.urlencode(params)}'
    with urllib.request.urlopen(full, timeout=5) as r:
        return json.load(r)


def geocode(place):
    """(latitude, longitude, display name) for a city name, or None."""
    place = (place or '').strip()
    if not place:
        return None
    key = f'geo:{place.lower()}'
    hit = cache.get(key)
    if hit is not None:
        return hit or None
    try:
        res = _get(GEO, {'name': place, 'count': 1}).get('results') or []
    except (OSError, ValueError):
        return None
    found = (res[0]['latitude'], res[0]['longitude'], res[0]['name']) if res else ()
    cache.set(key, found, 60 * 60 * 24 * 30)
    return found or None


def forecast(place, first, last):
    """{date: {lo, hi, rain, label, icon}} for days inside the API's horizon. Empty if unavailable."""
    today = date.today()
    first, last = max(first, today), min(last, today.fromordinal(today.toordinal() + HORIZON_DAYS - 1))
    if first > last:
        return {}
    spot = geocode(place)
    if not spot:
        return {}
    lat, lon, _ = spot
    key = f'fc:{lat:.2f}:{lon:.2f}:{first}:{last}'
    data = cache.get(key)
    if data is None:
        try:
            data = _get(FORECAST, {
                'latitude': lat, 'longitude': lon, 'timezone': 'auto',
                'start_date': first.isoformat(), 'end_date': last.isoformat(),
                'daily': 'weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max',
            }).get('daily') or {}
        except (OSError, ValueError):
            return {}
        cache.set(key, data, 60 * 30)
    out = {}
    for n, day in enumerate(data.get('time', [])):
        label, kind = CODES.get(data['weather_code'][n], ('Mixed', 'cloud'))
        out[date.fromisoformat(day)] = {
            'lo': round(data['temperature_2m_min'][n]), 'hi': round(data['temperature_2m_max'][n]),
            'rain': data['precipitation_probability_max'][n], 'label': label, 'icon': ICONS[kind],
        }
    return out


def packing_tips(days):
    """Short advice from a list of forecast dicts."""
    if not days:
        return []
    tips = []
    lo, hi = min(d['lo'] for d in days), max(d['hi'] for d in days)
    if lo <= 10:
        tips.append('Cold mornings: bring a coat or warm layers.')
    elif lo <= 17:
        tips.append('Cool at times: pack a light jacket.')
    if hi >= 28:
        tips.append('Hot afternoons: breathable fabrics and sunglasses.')
    if any((d['rain'] or 0) >= 50 for d in days):
        tips.append('Rain likely: waterproof layer and shoes you can get wet.')
    return tips or ['Mild and settled: easy layers will do.']
