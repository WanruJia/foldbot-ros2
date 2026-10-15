"""Contour-measured owner widths (2026-10-14).

perception.yolo_perception.garment_torso_width_in_bbox() measures a
sleeve-insensitive torso width on the garment contour, and
bt.perceive_subtree._owner_measure_keypoints() (used by ClassifyOwnerNode)
prefers contour measurements over the bbox width when they exist. The
detector is never loaded here: synthetic crops only (numpy + Pillow).
"""
import os
import sys
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
from unittest import mock
from PIL import Image
import py_trees
from perception.yolo_perception import garment_torso_width_in_bbox
from planning.fold_planner import classify_owner
from bt.perceive_subtree import (
    _owner_measure_keypoints, create_perceive_subtree)

BG, FG = 200, 60


def _shirt(h=500, w=400):
    """Axis-aligned shirt: 90px torso, 50px sleeve flare each side (top)."""
    img = np.full((h, w), BG, dtype=np.uint8)
    img[60:461, 190:280] = FG            # torso: 90 wide, 400 tall
    img[60:161, 140:190] = FG            # left sleeve flare
    img[60:161, 280:330] = FG            # right sleeve flare
    return img


def _shirt_long_sleeves(h=500, w=400):
    """Sleeves reaching deep into the measurement band (rows 60-290 of a
    60-460 torso; the 0.30-0.70 band is rows ~180-340, so the flare covers
    ~69% of the band). The old median read ~190 here; the 0.25-quantile
    must still read the 90px torso."""
    img = np.full((h, w), BG, dtype=np.uint8)
    img[60:461, 190:280] = FG            # torso: 90 wide, 400 tall
    img[60:291, 140:190] = FG            # long sleeve flare, left
    img[60:291, 280:330] = FG            # long sleeve flare, right
    return img


def _shirt_sideways(h=500, w=400):
    """Same shirt lying on its side (long axis horizontal)."""
    img = np.full((h, w), BG, dtype=np.uint8)
    img[205:295, 60:461] = FG            # torso: 400 long, 90 tall
    img[155:205, 60:161] = FG            # sleeve flare at the left end
    img[295:345, 60:161] = FG
    return img


def test_torso_width_ignores_sleeves():
    img = _shirt()
    bbox = (135, 55, 335, 465)           # full bbox: 200px wide (sleeves in)
    tw = garment_torso_width_in_bbox(img, bbox)
    assert tw is not None, "segmentation should succeed"
    assert abs(tw - 90.0) <= 2.0, tw     # torso width, not bbox width
    assert tw < 200.0 * 0.7, tw
    print("PASS test_torso_width_ignores_sleeves")


def test_torso_width_deep_sleeve_flare():
    # Sleeve flare covers ~69% of the band rows (would fool the median).
    img = _shirt_long_sleeves()
    bbox = (135, 55, 335, 465)           # full bbox: 190px wide (sleeves in)
    tw = garment_torso_width_in_bbox(img, bbox)
    assert tw is not None, "segmentation should succeed"
    assert abs(tw - 90.0) <= 3.0, tw     # torso width, not flare width
    assert tw < 120.0, tw                # well below the 190px flare
    print("PASS test_torso_width_deep_sleeve_flare")


def test_torso_width_sideways_garment():
    # PCA + coordinate rotation path (no mask rotation, no clipping).
    img = _shirt_sideways()
    bbox = (55, 150, 465, 350)
    tw = garment_torso_width_in_bbox(img, bbox)
    assert tw is not None, "segmentation should succeed"
    assert abs(tw - 90.0) <= 3.0, tw     # torso height == short-axis width
    print("PASS test_torso_width_sideways_garment")


def test_torso_width_uniform_returns_none():
    img = np.full((120, 120), BG, dtype=np.uint8)
    assert garment_torso_width_in_bbox(img, (10, 10, 110, 110)) is None
    print("PASS test_torso_width_uniform_returns_none")


def test_torso_width_near_square_returns_none():
    img = np.full((120, 120), BG, dtype=np.uint8)
    img[30:90, 30:90] = FG               # near-square blob: axis unstable
    assert garment_torso_width_in_bbox(img, (20, 20, 100, 100)) is None
    print("PASS test_torso_width_near_square_returns_none")


def test_torso_width_degenerate_bbox_raises():
    img = _shirt()
    try:
        garment_torso_width_in_bbox(img, (50, 50, 50, 90))
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for degenerate bbox")
    print("PASS test_torso_width_degenerate_bbox_raises")


def test_owner_measure_shirt_contour():
    mkp, prov = _owner_measure_keypoints("shirt", {"junk": 1},
                                        torso_width_m=0.34)
    assert "contour" in prov, prov
    owner, metric, name = classify_owner("shirt", mkp)
    assert abs(metric - 0.34) < 1e-9, metric
    assert owner == "daughter", owner   # 0.34 in [0.33, 0.345)
    print("PASS test_owner_measure_shirt_contour")


def test_owner_measure_shirt_bbox_fallback():
    kp = {"shoulder_l": {"x": 0.0, "z": 0.0},
          "shoulder_r": {"x": 0.40, "z": 0.0}}
    mkp, prov = _owner_measure_keypoints("shirt", kp, torso_width_m=None)
    assert mkp is kp, "fallback must use the perceived keypoints as-is"
    assert "provisional" in prov, prov
    owner, metric, _ = classify_owner("shirt", mkp)
    assert abs(metric - 0.40) < 1e-9 and owner == "dad", (owner, metric)
    print("PASS test_owner_measure_shirt_bbox_fallback")


def test_owner_measure_pants_contour_waist():
    ps = {"waist": {"grab": (0.3, 0.005, 0.2),
                    "x1": (0.10, 0.005, 0.20),
                    "x2": (0.50, 0.005, 0.20)}}
    mkp, prov = _owner_measure_keypoints("pants", {"junk": 1},
                                        pants_shape=ps)
    assert "contour waist" in prov, prov
    owner, metric, _ = classify_owner("pants", mkp)
    assert abs(metric - 0.40) < 1e-9, metric
    assert owner == "daughter", owner    # pants 0.40 in [0.36, 0.44)
    print("PASS test_owner_measure_pants_contour_waist")


def test_owner_measure_pants_waist_missing_fallback():
    kp = {"waist_l": {"x": 0.0, "z": 0.0},
          "waist_r": {"x": 0.48, "z": 0.0}}
    mkp, prov = _owner_measure_keypoints("pants", kp,
                                        pants_shape={"waist": None,
                                                     "legs": None})
    assert mkp is kp and "provisional" in prov, prov
    print("PASS test_owner_measure_pants_waist_missing_fallback")


class _T:
    def __init__(self, v):
        self.v = v

    def __int__(self):
        return int(self.v)

    def __float__(self):
        return float(self.v)


def _fake_result(box_specs):
    class B:
        def __init__(self, cls, conf, xyxy):
            self.cls = _T(cls)
            self.conf = _T(conf)
            self.xyxy = [[float(v) for v in xyxy]]

    made = [B(*b) for b in box_specs]

    class R:
        names = {0: "shirt", 1: "pants"}
        boxes = made
    return R()


def _run_tree(img_path, fake, px_per_m=500.0, torso_patch=None):
    mdl = tempfile.NamedTemporaryFile(suffix=".pt")
    root = create_perceive_subtree(perception="yolo", image_path=img_path,
                                   px_per_m=px_per_m, model_path=mdl.name,
                                   kind="shirt")
    with mock.patch("perception.yolo_perception._detect",
                    return_value=fake):
        if torso_patch is not None:
            with torso_patch:
                tree = py_trees.trees.BehaviourTree(root)
                tree.setup(timeout=5)
                for _ in range(80):
                    tree.tick()
                    if root.status != py_trees.common.Status.RUNNING:
                        break
        else:
            tree = py_trees.trees.BehaviourTree(root)
            tree.setup(timeout=5)
            for _ in range(80):
                tree.tick()
                if root.status != py_trees.common.Status.RUNNING:
                    break
    mdl.close()
    assert root.status == py_trees.common.Status.SUCCESS, root.status
    bb = py_trees.blackboard.Client(name="owner_width_check")
    for k in ("garment_kind", "perception", "torso_width_m"):
        bb.register_key(key=k, access=py_trees.common.Access.READ)
    return bb


def _shirt_png():
    f = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    Image.fromarray(_shirt()).save(f.name)
    f.close()
    return f.name


def test_yolo_shirt_owner_uses_contour_width():
    # bbox 200px wide @500px/m = 0.40m -> "dad"; contour torso 90px =
    # 0.18m -> "son". The tree must prefer the contour measurement.
    path = _shirt_png()
    try:
        fake = _fake_result([(0, 0.90, (135, 55, 335, 465))])
        bb = _run_tree(path, fake)
        assert bb.garment_kind == "shirt"
        assert bb.torso_width_m is not None, "torso width should be measured"
        assert abs(bb.torso_width_m - 0.18) < 0.01, bb.torso_width_m
        assert bb.perception.owner == "son", bb.perception.owner
        assert abs(bb.perception.metric - 0.18) < 0.01, bb.perception.metric
    finally:
        os.unlink(path)
    print("PASS test_yolo_shirt_owner_uses_contour_width")


def test_yolo_shirt_owner_falls_back_to_bbox():
    # Torso unmeasurable (patched to None) -> bbox width, still honest:
    # owner "dad" from the 0.40m bbox, provisional.
    path = _shirt_png()
    try:
        fake = _fake_result([(0, 0.90, (135, 55, 335, 465))])
        patch = mock.patch("bt.perceive_subtree.garment_torso_width_in_bbox",
                           return_value=None)
        bb = _run_tree(path, fake, torso_patch=patch)
        assert bb.torso_width_m is None
        assert bb.perception.owner == "dad", bb.perception.owner
        assert abs(bb.perception.metric - 0.40) < 1e-9, bb.perception.metric
    finally:
        os.unlink(path)
    print("PASS test_yolo_shirt_owner_falls_back_to_bbox")


if __name__ == "__main__":
    test_torso_width_ignores_sleeves()
    test_torso_width_deep_sleeve_flare()
    test_torso_width_sideways_garment()
    test_torso_width_uniform_returns_none()
    test_torso_width_near_square_returns_none()
    test_torso_width_degenerate_bbox_raises()
    test_owner_measure_shirt_contour()
    test_owner_measure_shirt_bbox_fallback()
    test_owner_measure_pants_contour_waist()
    test_owner_measure_pants_waist_missing_fallback()
    test_yolo_shirt_owner_uses_contour_width()
    test_yolo_shirt_owner_falls_back_to_bbox()
    print("\nAll owner-width contour tests passed ✅")
