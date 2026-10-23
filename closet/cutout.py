"""Cut-outs: the garment with its background removed (see ml/cutout_worker.py for how)."""
import json
import logging
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings
from PIL import Image, ImageOps

log = logging.getLogger(__name__)
MODEL = settings.BASE_DIR / 'models' / 'u2net.onnx'
WORKER = settings.BASE_DIR / 'closet' / 'ml' / 'cutout_worker.py'


def available():
    return settings.WARDROBE_ML_PYTHON.is_file() and MODEL.is_file()


def cut_out(jobs):
    """jobs: [(PIL image, category)]. Returns a list of RGBA PIL images, None where it did not work."""
    if not jobs or not available():
        return [None] * len(jobs)
    with tempfile.TemporaryDirectory() as tmp:
        args = []
        for n, (image, category) in enumerate(jobs):
            src = Path(tmp) / f'in{n}.jpg'
            ImageOps.exif_transpose(image).convert('RGB').save(src, 'JPEG', quality=92)
            args.append(f'{src}:{category}')
        try:
            run = subprocess.run([str(settings.WARDROBE_ML_PYTHON), str(WORKER), tmp, *args],
                                 capture_output=True, text=True, timeout=300)
            if run.returncode:
                raise RuntimeError(run.stderr[-600:])
            report = json.loads(run.stdout.strip().splitlines()[-1])
        except Exception:
            log.exception('Cut-out failed')
            return [None] * len(jobs)
        out = []
        for row in report:
            path = Path(tmp) / f"{row['n']}.png"
            if row['mode'] and path.is_file():
                img = Image.open(path)
                img.load()
                out.append(img)
            else:
                out.append(None)
        return out
