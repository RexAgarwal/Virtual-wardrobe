# Wardrobe

A personal virtual wardrobe built with Django. Photograph your clothes, tag them, build outfits from them, and log what you wore.

## Run it

    python -m venv .venv
    source .venv/bin/activate        # Windows: .venv\Scripts\activate
    pip install -r requirements.txt
    python manage.py migrate
    python manage.py runserver

Open http://127.0.0.1:8000. To use the admin at /admin, run `python manage.py createsuperuser` first.

To add pieces from your phone, run `python manage.py runserver 0.0.0.0:8000`, add your computer's LAN IP to `ALLOWED_HOSTS` in `wardrobe/settings.py`, and open that address on the phone. The photo field opens the camera directly.

## What's inside

- `closet/models.py` — `Item` (a piece of clothing; photos are resized to 1000px WebP on upload), `Outfit` (a set of items with an occasion), `WearLog` (dates an outfit was worn).
- `closet/views.py` — wardrobe grid with search and filters, add/edit/remove pieces, outfit builder, outfit list by occasion, "wore this" logging, and a random outfit picker.
- `templates/` and `static/closet/style.css` — the UI. Photos are the focus; everything else stays quiet.

## Pages

| URL | What it does |
|---|---|
| `/` | All pieces, filterable. Tick pieces to build an outfit from them. |
| `/items/new/` | Add a piece |
| `/items/<id>/` | One piece, its outfits, cost per wear |
| `/outfits/` | Saved outfits by occasion |
| `/outfits/new/` | Outfit builder |
| `/outfits/<id>/` | One outfit, log a wear |
| `/outfits/surprise/` | Jump to a random outfit (`?occasion=work` to narrow) |

## Ideas for next

Calendar of what you wore, least-worn report, packing lists, background removal on photos, export to JSON.

## Fit check (photo to pieces)

Upload a photo of an outfit and it lifts each garment and accessory into your wardrobe.
It runs on this computer with the OWLv2 model; no API key and no upload.

One-time setup (PyTorch has no build for Python 3.15, so it lives in its own 3.14 environment):

    /opt/homebrew/bin/python3.14 -m venv .venv-ml
    .venv-ml/bin/python -m pip install torch transformers pillow scipy

The model (about 600 MB) downloads on first use. To use the Claude vision API instead, set
`WARDROBE_DETECTOR=claude` and `ANTHROPIC_API_KEY`.
