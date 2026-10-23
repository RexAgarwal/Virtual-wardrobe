"""Virtual try-on: dress a person's full-body photo in an outfit's pieces, using a model that runs on this computer.

Jobs run one at a time in a background thread (a try-on takes a while and the model needs most of the memory),
so people queue behind each other. The model itself runs in .venv-ml through ml/tryon_worker.py.
"""
import logging
import subprocess
import tempfile
import threading
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import close_old_connections
from django.utils import timezone
from PIL import Image

log = logging.getLogger(__name__)
READY = settings.BASE_DIR / 'models' / 'tryon' / 'READY'
WORKER = settings.BASE_DIR / 'closet' / 'ml' / 'tryon_worker.py'
TIMEOUT = 30 * 60
_one_at_a_time = threading.Lock()


def available():
    return settings.WARDROBE_ML_PYTHON.is_file() and READY.is_file()


def garments_for(outfit):
    """[(item, cloth_type)]: the dress, or the top and the bottom. The model dresses one body area at a time."""
    items = list(outfit.items.all())
    pick = lambda *cats: next((i for i in items if i.category in cats), None)
    dress, top, bottom = pick('dress'), pick('top'), pick('bottom')
    if dress:
        return [(dress, 'overall')]
    upper = top or pick('outerwear')
    return [(i, kind) for i, kind in ((upper, 'upper'), (bottom, 'lower')) if i]


def _on_white(item, path):
    """Garment picture as a plain JPEG on white, the way try-on models expect a product photo."""
    img = Image.open(item.photo)
    img = img.convert('RGBA')
    flat = Image.new('RGB', img.size, (255, 255, 255))
    flat.paste(img, mask=img.split()[3])
    flat.save(path, 'JPEG', quality=94)


def start(job):
    threading.Thread(target=_run, args=(job.pk,), daemon=True).start()


def _run(job_id):
    from .models import TryOn
    close_old_connections()
    try:
        with _one_at_a_time:
            job = TryOn.objects.select_related('owner', 'outfit').get(pk=job_id)
            job.status = TryOn.Status.RUNNING
            job.save(update_fields=['status'])
            try:
                _generate(job)
                job.status = TryOn.Status.DONE
            except Exception as e:
                log.exception('Try-on %s failed', job_id)
                job.status, job.message = TryOn.Status.FAILED, (str(e) or 'Something went wrong.')[:300]
            job.save()
    finally:
        close_old_connections()


def _generate(job):
    if not available():
        raise RuntimeError('The try-on model is not installed on this computer yet.')
    garments = garments_for(job.outfit)
    if not garments:
        raise RuntimeError('This outfit needs a top, a bottom or a dress to try on.')
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        args = []
        for n, (item, kind) in enumerate(garments):
            path = tmp / f'garment{n}.jpg'
            _on_white(item, path)
            args.append(f'{path}:{kind}')
        out = tmp / 'result.jpg'
        run = subprocess.run([str(settings.WARDROBE_ML_PYTHON), str(WORKER), str(out), job.owner.tryon_photo.photo.path, *args],
                             capture_output=True, text=True, timeout=TIMEOUT)
        if run.returncode or not out.is_file():
            raise RuntimeError((run.stderr or 'The try-on model produced no picture.').strip().splitlines()[-1][:280])
        job.result.save(f'{job.pk}.jpg', ContentFile(out.read_bytes()), save=False)
        job.message = ''
