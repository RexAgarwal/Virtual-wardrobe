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
    .venv-ml/bin/python -m pip install torch transformers pillow scipy onnxruntime numpy

The model (about 600 MB) downloads on first use. To use the Claude vision API instead, set
`WARDROBE_DETECTOR=claude` and `ANTHROPIC_API_KEY`.

### Cut-outs (background removal)

When someone adds a piece, the app also makes a version with the background removed and lets them choose
between the original and the cut-out. It needs two free models, both used locally:

- Clothes model for photos of a person wearing the piece (about 110 MB). It downloads from Hugging Face the first time it runs.
- U2-Net background remover for photos of a single item (about 176 MB). Download it once into `models/`:

      mkdir -p models
      curl -L -o models/u2net.onnx https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx

Without these, adding pieces still works; the cut-out choice just doesn't appear.

### Try on (beta)

Shows an outfit on a person's own full-body photo, using CatVTON (Stable Diffusion inpainting) on this computer.
It is switched on only for admins and the users in `WARDROBE_BETA_USERS` (see `WARDROBE_FEATURES` in settings).
It takes about 5 minutes per garment on an Apple M-series Mac, one job at a time. One-time setup, about 4.5 GB:

    .venv-ml/bin/python -m pip install diffusers accelerate safetensors huggingface_hub
    git clone --depth 1 https://github.com/Zheng-Chong/CatVTON.git models/tryon/CatVTON-code
    .venv-ml/bin/python - <<'PY'
    from huggingface_hub import snapshot_download
    snapshot_download('zhengchong/CatVTON', local_dir='models/tryon/CatVTON-weights', allow_patterns=['mix-48k-1024/*'])
    snapshot_download('booksforcharlie/stable-diffusion-inpainting', local_dir='models/tryon/sd-inpainting',
                      ignore_patterns=['safety_checker/*', '*.ckpt', '*.fp16.*', '*.onnx', '*.msgpack', '*.h5'])
    PY
    touch models/tryon/READY

CatVTON's weights are licensed CC BY-NC-SA 4.0 (non-commercial). The body mask comes from the same Segformer clothes
parser the cut-outs use, since CatVTON's own masker needs detectron2.
