"""Tests for the synthetic data generator."""
import sys
sys.path.insert(0, ".")

import json
import os
import random
import tempfile

from synth.garments import build_shirt, build_pants, SHIRT_KPS, PANTS_KPS
from synth.render import render_sample, IMG_W, IMG_H


def test_garment_keypoints():
    # Shirt has all 9 keypoints, pants all 5
    for owner in ["dad", "mom", "daughter", "son"]:
        s = build_shirt(owner, rng=random.Random(0))
        assert set(s["keypoints"]) == set(SHIRT_KPS), owner
        p = build_pants(owner, rng=random.Random(0))
        assert set(p["keypoints"]) == set(PANTS_KPS), owner
    print("PASS test_garment_keypoints")


def test_render_keypoints_in_frame():
    # All keypoints should be inside the image (placement keeps garment in view)
    rng = random.Random(42)
    for _ in range(20):
        img, kps_2d, meta = render_sample(rng)
        assert img.shape == (IMG_H, IMG_W, 3), img.shape
        for name, (u, v, vis) in kps_2d.items():
            assert vis == 1, f"{meta['kind']}/{meta['owner']} {name} out of frame"
            assert 0 <= u < IMG_W and 0 <= v < IMG_H
    print("PASS test_render_keypoints_in_frame")


def test_coco_output():
    # End-to-end: generate 4 samples, check COCO JSON structure
    import subprocess
    with tempfile.TemporaryDirectory() as d:
        r = subprocess.run(
            [sys.executable, "-m", "synth.generate", "--out", d,
             "--n", "4", "--seed", "0"],
            capture_output=True, text=True, cwd=".")
        assert r.returncode == 0, r.stderr[-500:]
        with open(os.path.join(d, "annotations.json")) as f:
            coco = json.load(f)
        assert len(coco["images"]) == 4
        assert len(coco["annotations"]) == 4
        assert len(coco["categories"]) == 2
        for ann in coco["annotations"]:
            cat = [c for c in coco["categories"]
                   if c["id"] == ann["category_id"]][0]
            assert len(ann["keypoints"]) == len(cat["keypoints"]) * 3
            assert ann["num_keypoints"] > 0
        assert os.path.exists(os.path.join(d, "images", "000001.png"))
    print("PASS test_coco_output")


if __name__ == "__main__":
    test_garment_keypoints()
    test_render_keypoints_in_frame()
    test_coco_output()
    print("\nAll synth tests passed!")
