"""Fit Check: lift the individual pieces (tee, watch, shoes...) out of a photo of someone wearing them.

A vision model names each visible garment or accessory and boxes it; Pillow does the cropping.
"""
import base64
import json
import subprocess
import tempfile
from io import BytesIO

from django.conf import settings
from PIL import Image, ImageOps

from .models import Item

MAX_SIDE = 2000  # only very large photos are shrunk; boxes are relative so nothing is lost
PAD = 0.06       # breathing room around each box, as a share of the box size

PIECES_TOOL = {
    'name': 'report_pieces',
    'description': 'Report every separate garment, shoe or accessory the person in the photo is wearing or carrying.',
    'input_schema': {
        'type': 'object',
        'properties': {'pieces': {'type': 'array', 'items': {
            'type': 'object',
            'properties': {
                'name': {'type': 'string', 'description': 'Short product-style name, e.g. "White Logo Tee". Include a brand only if legible.'},
                'category': {'type': 'string', 'enum': Item.Category.values},
                'color': {'type': 'string', 'description': 'Main colour, one or two words'},
                'brand': {'type': 'string', 'description': 'Only if the brand is readable on the piece, else empty'},
                'formality': {'type': 'integer', 'minimum': 1, 'maximum': 5},
                'tags': {'type': 'string', 'description': 'Up to four comma separated style words'},
                'box': {'type': 'array', 'items': {'type': 'number'}, 'minItems': 4, 'maxItems': 4,
                        'description': 'Tight bounding box [left, top, right, bottom] as fractions 0 to 1 of image width and height'},
            },
            'required': ['name', 'category', 'color', 'formality', 'box'],
        }}},
        'required': ['pieces'],
    },
}

PROMPT = ('List each separate piece of clothing, footwear and accessory (watch, glasses, belt, bag, jewellery, hat) '
          'visible in this photo. Skip skin, hair and anything that is not worn or carried. Give each piece a tight '
          'bounding box that covers only that piece and never the wearer\'s face. If a piece is partly hidden, box '
          'the visible part.')


class NotConfigured(Exception):
    pass


def _prepare(image):
    img = ImageOps.exif_transpose(image).convert('RGB')
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    return img


def ml_ready():
    return settings.WARDROBE_ML_PYTHON.is_file()


def detect(image, client=None):
    """Pieces found in a PIL image: with the Claude API if a key is set (or a client is passed), else on this machine."""
    if client is not None or (settings.ANTHROPIC_API_KEY and settings.WARDROBE_DETECTOR == 'claude'):
        found = _detect_claude(image, client)
    else:
        found = _detect_local(image)
    return [p for p in found if _valid_box(p.get('box'))]


def _detect_local(image):
    """Zero-shot detection with OWLv2, run in the .venv-ml environment (PyTorch lives there)."""
    if not ml_ready():
        raise NotConfigured('The local model environment (.venv-ml) is missing. See the README to set it up.')
    with tempfile.NamedTemporaryFile(suffix='.jpg') as tmp:
        _prepare(image).save(tmp.name, 'JPEG', quality=92)
        run = subprocess.run([str(settings.WARDROBE_ML_PYTHON), str(settings.WARDROBE_ML_WORKER), tmp.name],
                             capture_output=True, text=True, timeout=300)
    if run.returncode != 0:
        raise RuntimeError(run.stderr[-800:])
    return json.loads(run.stdout.strip().splitlines()[-1])


def _detect_claude(image, client=None):
    if client is None:
        import anthropic
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    buf = BytesIO()
    _prepare(image).save(buf, 'JPEG', quality=88)
    reply = client.messages.create(
        model=settings.WARDROBE_VISION_MODEL, max_tokens=2000,
        tools=[PIECES_TOOL], tool_choice={'type': 'tool', 'name': 'report_pieces'},
        messages=[{'role': 'user', 'content': [
            {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/jpeg',
                                         'data': base64.b64encode(buf.getvalue()).decode()}},
            {'type': 'text', 'text': PROMPT}]}])
    found = next((b.input for b in reply.content if b.type == 'tool_use'), {})
    return found.get('pieces', [])


def _valid_box(box):
    try:
        l, t, r, b = (float(v) for v in box)
    except (TypeError, ValueError):
        return False
    return 0 <= l < r <= 1.001 and 0 <= t < b <= 1.001 and (r - l) * (b - t) > 0.0005


def crop(image, box):
    """Cut a box (fractions of width/height) out of the image, with a little padding."""
    img = ImageOps.exif_transpose(image).convert('RGB')
    w, h = img.size
    l, t, r, b = (min(max(float(v), 0), 1) for v in box)
    pw, ph = (r - l) * PAD, (b - t) * PAD
    px = (max(l - pw, 0) * w, max(t - ph, 0) * h, min(r + pw, 1) * w, min(b + ph, 1) * h)
    return img.crop(tuple(round(v) for v in px))


def clean(piece):
    """Coerce one detected piece into safe Item field values."""
    cat = piece.get('category')
    return {
        'name': (piece.get('name') or 'Untitled piece').strip()[:120],
        'category': cat if cat in Item.Category.values else Item.Category.ACCESSORY,
        'color': (piece.get('color') or '').strip()[:40],
        'brand': (piece.get('brand') or '').strip()[:80],
        'formality': min(max(int(piece.get('formality') or 2), 1), 5),
        'tags': (piece.get('tags') or '').strip()[:200],
    }
