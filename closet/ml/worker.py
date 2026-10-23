"""Runs in .venv-ml (PyTorch). Usage: worker.py IMAGE_PATH  -> JSON list of pieces on stdout.

Zero-shot detection with OWLv2: we describe garments in words and the model boxes them.
Colour is read from the pixels; there is no brand reading without OCR, so brand stays empty.
"""
import json
import os
import sys

import torch
from PIL import Image, ImageOps
from transformers import Owlv2ForObjectDetection, Owlv2Processor

MODEL = 'google/owlv2-base-patch16-ensemble'
THRESHOLD = float(os.environ.get('WARDROBE_THRESHOLD', 0.08))  # floor for the model; real cut-offs are per group
CLOTHING = ('top', 'outerwear', 'bottom', 'dress')
MIN_SCORE = {g: 0.10 for g in CLOTHING} | {'shoes': 0.15}  # everything else needs 0.25 (small things, more false alarms)
DEFAULT_MIN = 0.25

# group -> (category, formality, text queries)
GROUPS = {
    'top': ('top', 2, ['a t-shirt', 'a shirt', 'a sweater', 'a hoodie', 'a polo shirt', 'a tank top', 'a blouse']),
    'outerwear': ('outerwear', 3, ['a jacket', 'a coat', 'a blazer', 'a cardigan']),
    'bottom': ('bottom', 2, ['a pair of pants', 'a pair of jeans', 'a pair of shorts', 'a skirt']),
    'dress': ('dress', 3, ['a dress']),
    'shoes': ('shoes', 2, ['a pair of sneakers', 'a pair of shoes', 'a pair of boots']),
    'watch': ('accessory', 3, ['a wrist watch']),
    'glasses': ('accessory', 2, ['a pair of sunglasses', 'a pair of glasses']),
    'hat': ('accessory', 2, ['a hat', 'a baseball cap']),
    'bag': ('accessory', 2, ['a handbag', 'a backpack']),
    'belt': ('accessory', 3, ['a belt']),
    'scarf': ('accessory', 3, ['a scarf']),
    'necklace': ('accessory', 3, ['a necklace', 'a chain necklace']),
    'bracelet': ('accessory', 2, ['a bracelet']),
}
LABELS = {  # first query word(s) -> display name
    'a t-shirt': 'Tee', 'a shirt': 'Shirt', 'a sweater': 'Sweater', 'a hoodie': 'Hoodie', 'a polo shirt': 'Polo',
    'a tank top': 'Tank Top', 'a blouse': 'Blouse', 'a jacket': 'Jacket', 'a coat': 'Coat', 'a blazer': 'Blazer',
    'a cardigan': 'Cardigan', 'a pair of pants': 'Trousers', 'a pair of jeans': 'Jeans', 'a pair of shorts': 'Shorts',
    'a skirt': 'Skirt', 'a dress': 'Dress', 'a pair of sneakers': 'Sneakers', 'a pair of shoes': 'Shoes',
    'a pair of boots': 'Boots', 'a wrist watch': 'Watch', 'a pair of sunglasses': 'Sunglasses',
    'a pair of glasses': 'Glasses', 'a hat': 'Hat', 'a baseball cap': 'Cap', 'a handbag': 'Handbag',
    'a backpack': 'Backpack', 'a belt': 'Belt', 'a scarf': 'Scarf', 'a necklace': 'Necklace',
    'a chain necklace': 'Chain', 'a bracelet': 'Bracelet',
}
PALETTE = {
    'Black': (25, 25, 28), 'White': (240, 240, 238), 'Grey': (128, 128, 132), 'Silver': (190, 192, 198),
    'Beige': (214, 196, 168), 'Cream': (240, 230, 206), 'Brown': (110, 75, 50), 'Tan': (176, 138, 92),
    'Navy': (28, 38, 84), 'Blue': (50, 90, 190), 'Light blue': (150, 190, 230), 'Green': (50, 120, 70),
    'Olive': (110, 110, 60), 'Red': (190, 40, 45), 'Burgundy': (110, 28, 48), 'Pink': (235, 150, 180),
    'Orange': (230, 130, 45), 'Yellow': (235, 200, 60), 'Gold': (190, 150, 60), 'Purple': (120, 70, 160),
}


def colour_name(crop):
    """Most common palette colour in the middle of the crop (ignores edges, where the background sits)."""
    w, h = crop.size
    mid = crop.crop((w // 4, h // 4, w - w // 4, h - h // 4)).resize((24, 24))
    votes = {}
    raw = mid.tobytes()
    for px in (tuple(raw[i:i + 3]) for i in range(0, len(raw), 3)):
        best = min(PALETTE, key=lambda n: sum((a - b) ** 2 for a, b in zip(px, PALETTE[n])))
        votes[best] = votes.get(best, 0) + 1
    return max(votes, key=votes.get)


def _inter(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(w, 0) * max(h, 0)


def main(path):
    image = ImageOps.exif_transpose(Image.open(path)).convert('RGB')
    w, h = image.size
    queries = [q for _, _, qs in GROUPS.values() for q in qs]
    processor = Owlv2Processor.from_pretrained(MODEL)
    model = Owlv2ForObjectDetection.from_pretrained(MODEL).eval()
    inputs = processor(text=[queries], images=image, return_tensors='pt')
    with torch.no_grad():
        out = model(**inputs)
    side = max(w, h)  # OWLv2 pads to a square, so boxes are relative to the padded image
    res = processor.post_process_grounded_object_detection(
        out, threshold=THRESHOLD, target_sizes=torch.tensor([(side, side)]), text_labels=[queries])[0]

    best = {}  # group -> (score, box, query)
    owner = {q: g for g, (_, _, qs) in GROUPS.items() for q in qs}
    for score, box, query in zip(res['scores'], res['boxes'], res['text_labels']):
        g = owner[query]
        if g not in best or score > best[g][0]:
            best[g] = (float(score), [float(v) for v in box], query)
        generic = GROUPS[g][2][0]  # the plain wording ("a t-shirt") wins over a fancier one when nearly as sure
        if query == generic and g in best and score >= 0.8 * best[g][0]:
            best[g] = (float(score), [float(v) for v in box], query)

    pieces, clothing_boxes = [], []
    for g, (score, (x0, y0, x1, y1), query) in sorted(best.items(), key=lambda kv: -kv[1][0]):
        x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, w), min(y1, h)
        if x1 - x0 < 8 or y1 - y0 < 8 or score < MIN_SCORE.get(g, DEFAULT_MIN):
            continue
        if g in CLOTHING:  # a weaker garment guess sitting inside a stronger one is the same garment
            area = (x1 - x0) * (y1 - y0)
            if any(_inter(b, (x0, y0, x1, y1)) > 0.5 * area for b in clothing_boxes):
                continue
            clothing_boxes.append((x0, y0, x1, y1))
        cat, formality, _ = GROUPS[g]
        colour = colour_name(image.crop((int(x0), int(y0), int(x1), int(y1))))
        label = LABELS[query]
        pieces.append({
            'name': f'{colour} {label}', 'category': cat, 'color': colour, 'brand': '',
            'formality': formality, 'tags': label.lower(), 'score': round(score, 3),
            'box': [x0 / w, y0 / h, x1 / w, y1 / h]})
    pieces.sort(key=lambda p: -p['score'])
    print(json.dumps(pieces))


if __name__ == '__main__':
    main(sys.argv[1])
