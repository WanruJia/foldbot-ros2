"""Yaw from bbox (roadmap item 3): contour yaw -> check_placement().

perception.yolo_perception.garment_yaw_in_bbox() estimates the garment's
rotation inside a YOLO bbox (border-sampled background, Otsu, numpy PCA
standing in for minAreaRect's long axis), and bbox_to_placement_kp() now
takes yaw_deg to rotate the 4 placement keypoints so check_placement()'s
keypoint-based yaw computation observes the real rotation.

The real detector is NOT loaded: ultralytics stays monkeypatched away in
the BT integration tests, and the yaw unit tests use synthetic PIL images.
"""
import math
import os
import sys
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest import mock
import py_trees
from perception.yolo_perception import (
    garment_yaw_in_bbox, bbox_to_placement_kp)
from planning.board import check_placement
from bt.perceive_subtree import create_perceive_subtree


def _rotated_rect_image(w, h, angle_deg, img_size=400, bg=235, fg=60):
    """Synthetic garment: dark rotated rectangle on a light board.

    Returns (numpy array, bbox) with the bbox covering the whole image.
    """
    from PIL import Image, ImageDraw
    import numpy as np
    cx = cy = img_size / 2.0
    th = math.radians(angle_deg)
    c, s = math.cos(th), math.sin(th)
    pts = []
    for dx, dy in [(-w / 2, -h / 2), (w / 2, -h / 2),
                   (w / 2, h / 2), (-w / 2, h / 2)]:
        pts.append((cx + dx * c - dy * s, cy + dx * s + dy * c))
    img = Image.new("L", (img_size, img_size), bg)
    ImageDraw.Draw(img).polygon(pts, fill=fg)
    return np.asarray(img), (0, 0, img_size, img_size)


def test_yaw_upright():
    img, bbox = _rotated_rect_image(120, 220, 0)
    yaw = garment_yaw_in_bbox(img, bbox)
    assert yaw is not None, "upright garment should segment"
    assert abs(yaw) < 3.0, yaw
    print("PASS test_yaw_upright")


def test_yaw_rotated_30():
    img, bbox = _rotated_rect_image(120, 220, 30)
    yaw = garment_yaw_in_bbox(img, bbox)
    assert yaw is not None, "rotated garment should segment"
    assert abs(yaw - 30.0) < 4.0, yaw
    print("PASS test_yaw_rotated_30")


def test_yaw_rotated_negative():
    img, bbox = _rotated_rect_image(120, 220, -25)
    yaw = garment_yaw_in_bbox(img, bbox)
    assert yaw is not None
    assert abs(yaw + 25.0) < 4.0, yaw
    print("PASS test_yaw_rotated_negative")


def test_yaw_pants_tall():
    # pants-like aspect ratio, rotated
    img, bbox = _rotated_rect_image(90, 260, -15)
    yaw = garment_yaw_in_bbox(img, bbox)
    assert yaw is not None
    assert abs(yaw + 15.0) < 4.0, yaw
    print("PASS test_yaw_pants_tall")


def test_yaw_uniform_returns_none():
    import numpy as np
    img = np.full((200, 200), 235, dtype=np.uint8)
    assert garment_yaw_in_bbox(img, (10, 10, 190, 190)) is None
    print("PASS test_yaw_uniform_returns_none")


def test_yaw_tiny_bbox_returns_none():
    img, bbox = _rotated_rect_image(120, 220, 0)
    assert garment_yaw_in_bbox(img, (10, 10, 14, 14)) is None
    print("PASS test_yaw_tiny_bbox_returns_none")


def test_yaw_near_square_returns_none():
    # Near-square blob: long axis is unstable -> honest None, not a guess.
    img, bbox = _rotated_rect_image(200, 200, 20)
    assert garment_yaw_in_bbox(img, bbox) is None
    print("PASS test_yaw_near_square_returns_none")


def test_yaw_degenerate_bbox_raises():
    import numpy as np
    img = np.full((200, 200), 235, dtype=np.uint8)
    try:
        garment_yaw_in_bbox(img, (50, 50, 50, 90))
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for degenerate bbox")
    print("PASS test_yaw_degenerate_bbox_raises")


def test_yaw_path_input():
    from PIL import Image
    import numpy as np
    arr, _ = _rotated_rect_image(120, 220, 10)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        Image.fromarray(arr.astype(np.uint8)).save(f.name)
        path = f.name
    try:
        yaw = garment_yaw_in_bbox(path, (0, 0, 400, 400))
    finally:
        os.unlink(path)
    assert yaw is not None
    assert abs(yaw - 10.0) < 4.0, yaw
    print("PASS test_yaw_path_input")


def test_bbox_to_placement_kp_yaw_none_is_legacy():
    det = {"bbox": (100, 200, 450, 600)}
    kp = bbox_to_placement_kp(det, "shirt")
    assert kp["shoulder_l"] == (100, 0.0, 200), kp["shoulder_l"]
    assert kp["shoulder_r"] == (450, 0.0, 200)
    assert kp["hem_l"] == (100, 0.0, 600)
    assert kp["hem_r"] == (450, 0.0, 600)
    print("PASS test_bbox_to_placement_kp_yaw_none_is_legacy")


def test_bbox_to_placement_kp_yaw_feeds_check_placement():
    det = {"bbox": (100, 200, 450, 600)}
    legacy = check_placement(bbox_to_placement_kp(det, "shirt"), "shirt")
    kp = bbox_to_placement_kp(det, "shirt", yaw_deg=25.0)
    pl = check_placement(kp, "shirt")
    # yaw is observed by the keypoint-based computation ...
    assert abs(pl["dyaw_deg"] - 25.0) < 0.5, pl
    # ... while the center (and its corrections) is unchanged
    assert pl["dx"] == legacy["dx"] and pl["dz"] == legacy["dz"], pl
    assert pl["ok"] is False
    print("PASS test_bbox_to_placement_kp_yaw_feeds_check_placement")


def test_bbox_to_placement_kp_yaw_pants():
    det = {"bbox": (50, 100, 530, 900)}
    kp = bbox_to_placement_kp(det, "pants", yaw_deg=-20.0)
    pl = check_placement(kp, "pants")
    assert abs(pl["dyaw_deg"] + 20.0) < 0.5, pl
    print("PASS test_bbox_to_placement_kp_yaw_pants")


def test_bbox_to_placement_kp_yaw_garbage_raises():
    det = {"bbox": (100, 200, 450, 600)}
    try:
        bbox_to_placement_kp(det, "shirt", yaw_deg="clockwise-ish")
    except (TypeError, ValueError):
        pass
    else:
        raise AssertionError("expected an error for garbage yaw_deg")
    print("PASS test_bbox_to_placement_kp_yaw_garbage_raises")


# --- BT integration: _update_yolo feeds yaw into placement ---

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


def _tick_until_done(root, max_ticks=80):
    tree = py_trees.trees.BehaviourTree(root)
    tree.setup(timeout=5)
    for _ in range(max_ticks):
        tree.tick()
        if root.status != py_trees.common.Status.RUNNING:
            break
    return root.status


def _read(keys):
    bb = py_trees.blackboard.Client(name="yolo_yaw")
    for k in keys:
        bb.register_key(key=k, access=py_trees.common.Access.READ)
    return bb


def _run_yolo_with_yaw(yaw_stub):
    fake = _fake_result([(0, 0.90, (100, 200, 450, 600))])
    img = tempfile.NamedTemporaryFile(suffix=".jpg")
    mdl = tempfile.NamedTemporaryFile(suffix=".pt")
    root = create_perceive_subtree(perception="yolo", image_path=img.name,
                                   px_per_m=1000.0, model_path=mdl.name)
    detect = mock.patch("perception.yolo_perception._detect",
                        return_value=fake)
    yawp = mock.patch("bt.perceive_subtree.garment_yaw_in_bbox", yaw_stub)
    with detect, yawp:
        status = _tick_until_done(root)
    img.close()
    mdl.close()
    assert status == py_trees.common.Status.SUCCESS, status
    return _read(("placement",))


def test_yolo_yaw_reaches_placement():
    bb = _run_yolo_with_yaw(lambda frame, bbox: 25.0)
    assert abs(bb.placement["dyaw_deg"] - 25.0) < 0.5, bb.placement
    # center correction identical to the no-yaw run
    assert abs(bb.placement["dx"] - (-0.275)) < 1e-9, bb.placement
    print("PASS test_yolo_yaw_reaches_placement")


def test_yolo_yaw_unavailable_falls_back_to_zero():
    def boom(frame, bbox):
        raise OSError("unreadable frame")
    bb = _run_yolo_with_yaw(boom)
    assert bb.placement["dyaw_deg"] == 0.0, bb.placement
    print("PASS test_yolo_yaw_unavailable_falls_back_to_zero")


if __name__ == "__main__":
    test_yaw_upright()
    test_yaw_rotated_30()
    test_yaw_rotated_negative()
    test_yaw_pants_tall()
    test_yaw_uniform_returns_none()
    test_yaw_tiny_bbox_returns_none()
    test_yaw_near_square_returns_none()
    test_yaw_degenerate_bbox_raises()
    test_yaw_path_input()
    test_bbox_to_placement_kp_yaw_none_is_legacy()
    test_bbox_to_placement_kp_yaw_feeds_check_placement()
    test_bbox_to_placement_kp_yaw_pants()
    test_bbox_to_placement_kp_yaw_garbage_raises()
    test_yolo_yaw_reaches_placement()
    test_yolo_yaw_unavailable_falls_back_to_zero()
    print("\nAll YOLO yaw tests passed ✅")
