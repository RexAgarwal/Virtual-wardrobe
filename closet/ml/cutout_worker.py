"""Runs in .venv-ml. Usage: cutout_worker.py OUT_DIR PATH:CATEGORY [PATH:CATEGORY ...]

For each image writes OUT_DIR/<n>.png, the garment with the background removed, trimmed and centred on a
transparent 3:4 canvas, and prints a JSON list [{"n": 0, "mode": "worn"|"object"} or {"n": 1, "mode": null}].

- Photo with a person in it: the Segformer clothes model keeps only the garment for the given category.
  Skin, hair and background go. Parts hidden behind an arm stay hidden; nothing is invented.
- Photo of a lone item (or an accessory): the U2-Net background remover keeps the main object.
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parents[2]
U2NET = ROOT / 'models' / 'u2net.onnx'
SEGFORMER = 'mattmdjaga/segformer_b2_clothes'

# Segformer clothes labels
SKIN_HAIR = {2, 11, 12, 13, 14, 15}
KEEP = {'top': {4}, 'outerwear': {4}, 'bottom': {5, 6}, 'dress': {7, 4}, 'shoes': {9, 10}}
MAX_SIDE = 1000
MARGIN = 0.08


def load_u2net():
    import onnxruntime as ort
    return ort.InferenceSession(str(U2NET), providers=['CPUExecutionProvider'])


def object_mask(session, image):
    small = np.asarray(image.resize((320, 320), Image.LANCZOS), dtype=np.float32)
    small = small / max(small.max(), 1e-6)
    small = (small - (0.485, 0.456, 0.406)) / (0.229, 0.224, 0.225)
    pred = session.run(None, {session.get_inputs()[0].name: small.transpose(2, 0, 1)[None].astype(np.float32)})[0][0, 0]
    pred = (pred - pred.min()) / max(pred.max() - pred.min(), 1e-6)
    return Image.fromarray((pred * 255).astype('uint8')).resize(image.size, Image.LANCZOS)


class Parser:
    def __init__(self):
        import torch
        from transformers import SegformerForSemanticSegmentation
        self.torch = torch
        self.model = SegformerForSemanticSegmentation.from_pretrained(SEGFORMER).eval()

    def labels(self, image):
        torch = self.torch
        # the model's own preprocessing: 512x512, ImageNet mean and deviation
        x = np.asarray(image.resize((512, 512), Image.BILINEAR), dtype=np.float32) / 255
        x = (x - (0.485, 0.456, 0.406)) / (0.229, 0.224, 0.225)
        with torch.no_grad():
            logits = self.model(pixel_values=torch.from_numpy(x.transpose(2, 0, 1)[None].astype(np.float32))).logits
        up = torch.nn.functional.interpolate(logits, size=image.size[::-1], mode='bilinear', align_corners=False)
        return up.argmax(dim=1)[0].numpy()


def tidy(keep):
    """Bridge hairline gaps, then drop stray specks: keep only blobs at least a fifth the size of the biggest."""
    from scipy import ndimage
    keep = ndimage.binary_closing(keep, structure=np.ones((9, 9)))
    blobs, count = ndimage.label(keep)
    if count > 1:
        sizes = ndimage.sum(keep, blobs, range(1, count + 1))
        good = [i + 1 for i, size in enumerate(sizes) if size >= 0.2 * sizes.max()]
        keep = np.isin(blobs, good)
    return ndimage.binary_fill_holes(keep)


def finish(image, mask):
    """Apply the mask, trim to the garment and centre it on a 3:4 transparent canvas."""
    mask = mask.filter(ImageFilter.MedianFilter(5)).filter(ImageFilter.GaussianBlur(0.8))
    rgba = image.convert('RGBA')
    rgba.putalpha(mask)
    box = mask.point(lambda v: 255 if v > 24 else 0).getbbox()
    if not box:
        return None
    rgba = rgba.crop(box)
    w, h = rgba.size
    height = max(h * (1 + 2 * MARGIN), w * (1 + 2 * MARGIN) * 4 / 3)
    canvas = Image.new('RGBA', (round(height * 3 / 4), round(height)), (0, 0, 0, 0))
    canvas.paste(rgba, ((canvas.width - w) // 2, (canvas.height - h) // 2))
    canvas.thumbnail((MAX_SIDE, MAX_SIDE))
    return canvas


def main(out_dir, jobs):
    out = Path(out_dir)
    parser = u2 = None
    report = []
    for n, job in enumerate(jobs):
        path, _, category = job.rpartition(':')
        image = ImageOps.exif_transpose(Image.open(path)).convert('RGB')
        image.thumbnail((1600, 1600))
        mode, mask = None, None
        if category in KEEP:
            parser = parser or Parser()
            labels = parser.labels(image)
            person = np.isin(labels, list(SKIN_HAIR)).mean()
            keep = np.isin(labels, list(KEEP[category]))
            if person > 0.02 and keep.mean() > 0.02:
                mode, mask = 'worn', Image.fromarray((tidy(keep) * 255).astype('uint8'))
        if mask is None and U2NET.is_file():
            u2 = u2 or load_u2net()
            mode, mask = 'object', object_mask(u2, image)
        result = finish(image, mask) if mask is not None else None
        if result is None:
            mode = None
        else:
            result.save(out / f'{n}.png')
        report.append({'n': n, 'mode': mode})
    print(json.dumps(report))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2:])
