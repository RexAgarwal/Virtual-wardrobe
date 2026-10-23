"""Runs in .venv-ml. Usage: tryon_worker.py OUT.jpg PERSON.jpg GARMENT.jpg:upper|lower|overall [...]

Virtual try-on with CatVTON (Stable Diffusion inpainting + garment attention) run on this computer. The
garments are put on one after another, each stage starting from the previous result.

CatVTON asks for a mask of the body area to repaint. Its own masker needs detectron2, so the mask here comes
from the Segformer clothes parser that the cut-out feature already uses.

Weights live in models/tryon (see README). CatVTON's weights are licensed non-commercial (CC BY-NC-SA 4.0).
"""
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'models' / 'tryon'
CODE = BASE / 'CatVTON-code'
sys.path.insert(0, str(CODE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

WIDTH, HEIGHT = 768, 1024
STEPS = 30
# Segformer labels: 2 hair, 4 upper clothes, 5 skirt, 6 pants, 7 dress, 9/10 shoes, 11 face, 12/13 legs, 14/15 arms, 17 scarf
AREA = {
    'upper': {4, 14, 15, 17},
    'lower': {5, 6, 12, 13},
    'overall': {4, 5, 6, 7, 12, 13, 14, 15, 17},
}
KEEP = {2, 11}  # never repaint hair or face


def install_chunked_attention(chunk=2048):
    """Attention over a 1024 px person plus garment is ~24,000 tokens; done in one go it wants a 38 GB buffer.
    Computing it a slice of queries at a time gives the same answer with a small fraction of the memory."""
    import torch.nn.functional as F
    original = F.scaled_dot_product_attention

    def sliced(q, k, v, attn_mask=None, dropout_p=0.0, is_causal=False, scale=None, **kw):
        if is_causal or q.shape[-2] <= chunk:
            return original(q, k, v, attn_mask=attn_mask, dropout_p=dropout_p, is_causal=is_causal, scale=scale, **kw)
        parts = [original(q[..., i:i + chunk, :], k, v, attn_mask=None if attn_mask is None else attn_mask[..., i:i + chunk, :],
                          dropout_p=dropout_p, scale=scale, **kw) for i in range(0, q.shape[-2], chunk)]
        return torch.cat(parts, dim=-2)

    F.scaled_dot_product_attention = sliced


def pick_device():
    if torch.backends.mps.is_available():
        return 'mps', torch.float16
    return 'cpu', torch.float32


def body_mask(parser, person, kind):
    """White where the model should repaint: the garment area plus the arms/legs it overlaps, grown a little."""
    labels = parser.labels(person)
    area = np.isin(labels, list(AREA[kind])) & ~np.isin(labels, list(KEEP))
    mask = Image.fromarray((area * 255).astype('uint8'))
    grow = max(person.size) // 40 * 2 + 1
    mask = mask.filter(ImageFilter.MaxFilter(grow if grow % 2 else grow + 1))
    return mask, area.mean()


def load_pipeline():
    from diffusers import AutoencoderKL
    original = AutoencoderKL.from_pretrained
    local_vae = str(BASE / 'sd-inpainting' / 'vae')
    # CatVTON asks the internet for stabilityai/sd-vae-ft-mse; use the VAE that came with the base model instead
    AutoencoderKL.from_pretrained = classmethod(
        lambda cls, name, *a, **k: original(local_vae if 'sd-vae-ft-mse' in str(name) else name, *a, **k))
    from model.pipeline import CatVTONPipeline
    device, dtype = pick_device()
    return CatVTONPipeline(
        base_ckpt=str(BASE / 'sd-inpainting'), attn_ckpt=str(BASE / 'CatVTON-weights'), attn_ckpt_version='mix',
        weight_dtype=dtype, device=device, skip_safety_check=True, use_tf32=False)


def main(out_path, person_path, jobs):
    from cutout_worker import Parser
    person = ImageOps.exif_transpose(Image.open(person_path)).convert('RGB')
    install_chunked_attention()
    parser = Parser()
    pipe = load_pipeline()
    generator = torch.Generator(device='cpu').manual_seed(42)
    for job in jobs:
        garment_path, _, kind = job.rpartition(':')
        garment = Image.open(garment_path).convert('RGB')
        mask, share = body_mask(parser, person, kind)
        if share < 0.01:
            sys.exit(f'Could not find where the {kind} garment goes in your photo. Use a clear, full-body, front-facing photo.')
        result = pipe(image=person, condition_image=garment, mask=mask, num_inference_steps=STEPS,
                      guidance_scale=2.5, height=HEIGHT, width=WIDTH, generator=generator)[0]
        person = result
    person.save(out_path, 'JPEG', quality=92)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], sys.argv[3:])
