"""Batch-generate synthetic garment dataset (images + COCO annotations).

Usage:
    python3 -m synth.generate --out data/synth --n 500 --seed 0

Output:
    data/synth/images/000001.png ...
    data/synth/annotations.json  (COCO: shirt/pants + keypoints)

Keypoint order follows perception/msgs keypoint structs.
"""
import argparse
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from synth.garments import SHIRT_KPS, PANTS_KPS
from synth.render import render_sample, IMG_W, IMG_H

CATS = [
    {"id": 1, "name": "shirt", "keypoints": SHIRT_KPS,
     "skeleton": [["shoulder_l", "shoulder_r"], ["shoulder_l", "sleeve_l"],
                  ["shoulder_r", "sleeve_r"], ["shoulder_l", "hem_l"],
                  ["shoulder_r", "hem_r"], ["hem_l", "hem_r"],
                  ["a", "b"], ["b", "c"]]},
    {"id": 2, "name": "pants", "keypoints": PANTS_KPS,
     "skeleton": [["waist_l", "waist_r"], ["waist_l", "cuff_l"],
                  ["waist_r", "cuff_r"], ["crotch", "cuff_l"],
                  ["crotch", "cuff_r"]]},
]
CAT_BY_NAME = {c["name"]: c for c in CATS}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/synth", help="output dir")
    ap.add_argument("--n", type=int, default=200, help="number of samples")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--kind", default=None, choices=["shirt", "pants"],
                    help="force garment kind")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    img_dir = os.path.join(args.out, "images")
    os.makedirs(img_dir, exist_ok=True)

    images, annotations = [], []
    for i in range(args.n):
        img, kps_2d, meta = render_sample(rng, kind=args.kind)
        fname = f"{i + 1:06d}.png"
        # save
        from PIL import Image
        Image.fromarray(img).save(os.path.join(img_dir, fname))

        cat = CAT_BY_NAME[meta["kind"]]
        kp_list, xs, ys, nvis = [], [], [], 0
        for name in cat["keypoints"]:
            u, v, vis = kps_2d[name]
            kp_list += [round(float(u), 1), round(float(v), 1), vis]
            if vis:
                xs.append(u); ys.append(v); nvis += 1
        if xs:
            x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
            bbox = [round(x0, 1), round(y0, 1),
                    round(x1 - x0, 1), round(y1 - y0, 1)]
            area = round((x1 - x0) * (y1 - y0), 1)
        else:
            bbox, area = [0, 0, 0, 0], 0

        images.append({"id": i + 1, "file_name": f"images/{fname}",
                       "width": IMG_W, "height": IMG_H,
                       "kind": meta["kind"], "owner": meta["owner"]})
        annotations.append({"id": i + 1, "image_id": i + 1,
                            "category_id": cat["id"],
                            "keypoints": kp_list, "num_keypoints": nvis,
                            "bbox": bbox, "area": area,
                            "iscrowd": 0})
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{args.n}", flush=True)

    with open(os.path.join(args.out, "annotations.json"), "w") as f:
        json.dump({"images": images, "annotations": annotations,
                   "categories": CATS}, f)
    print(f"wrote {args.n} samples → {args.out}")


if __name__ == "__main__":
    main()
