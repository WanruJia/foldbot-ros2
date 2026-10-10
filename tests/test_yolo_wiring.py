"""M6 tests: YOLO wired into bt/perceive_subtree.py (DetectKeypoints).

The real ultralytics model is NOT loaded: perception.yolo_perception._detect
is monkeypatched with a fake detector (same pattern as test_yolo_perception).
Mock mode (default) behavior is covered by test_m4.py and must not change.
"""
import sys
import os
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest import mock
import py_trees
from bt.perceive_subtree import create_perceive_subtree


class _T:
    """Mimics a 0-d torch tensor for int()/float() conversion."""

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
    bb = py_trees.blackboard.Client(name="yolo_wiring")
    for k in keys:
        bb.register_key(key=k, access=py_trees.common.Access.READ)
    return bb


def _yolo_subtree(fake, px_per_m=1000.0, kind="random"):
    """Create a yolo-mode subtree with _detect monkeypatched."""
    img = tempfile.NamedTemporaryFile(suffix=".jpg")
    mdl = tempfile.NamedTemporaryFile(suffix=".pt")
    patch = mock.patch("perception.yolo_perception._detect",
                       return_value=fake)
    root = create_perceive_subtree(perception="yolo", image_path=img.name,
                                   px_per_m=px_per_m, model_path=mdl.name,
                                   kind=kind)
    return root, patch, img, mdl


def test_yolo_requires_image_and_calibration():
    for kwargs in ({"perception": "yolo"},
                   {"perception": "yolo", "image_path": "/tmp/x.jpg"},
                   {"perception": "laser"}):
        try:
            create_perceive_subtree(**kwargs)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected ValueError for {kwargs}")
    print("PASS test_yolo_requires_image_and_calibration")


def test_yolo_end_to_end_shirt():
    # bbox (100,200)-(450,600) px at 1000 px/m -> 0.35m wide -> mom (0.345+)
    fake = _fake_result([(0, 0.90, (100, 200, 450, 600))])
    root, patch, img, mdl = _yolo_subtree(fake)
    with patch:
        status = _tick_until_done(root)
    img.close()
    mdl.close()
    assert status == py_trees.common.Status.SUCCESS, status
    bb = _read(("garment_kind", "keypoints", "placement", "perception",
                "board_plan", "fold_plan", "frame_path"))
    assert bb.garment_kind == "shirt", bb.garment_kind
    assert bb.frame_path == img.name
    # detection overrode any mock kind; placement ran on bbox keypoints
    assert set(bb.keypoints) == {"shoulder_l", "shoulder_r",
                                 "hem_l", "hem_r"}, set(bb.keypoints)
    pl = bb.placement
    assert set(pl) == {"ok", "dx", "dz", "dyaw_deg"}, pl
    # center (0.275, 0.40) vs shirt target (0.0, -0.02): clearly off-board
    assert pl["ok"] is False
    assert abs(pl["dx"] - (-0.275)) < 1e-9, pl
    assert abs(pl["dz"] - (-0.42)) < 1e-9, pl
    # real owner classifier on the 0.35m bbox width -> mom
    assert bb.perception.owner == "mom", bb.perception.owner
    assert bb.perception.kind == "shirt"
    # board plan built; ABC plan skipped (bbox has no sleeves/a/b/c)
    assert bb.board_plan["slot"] and bb.board_plan["panels"]
    assert bb.fold_plan is None, bb.fold_plan
    print("PASS test_yolo_end_to_end_shirt")


def test_yolo_pants_kind_and_owner():
    # bbox (50,100)-(530,900): width 0.48m -> mom pants; length 0.8m long
    fake = _fake_result([(1, 0.88, (50, 100, 530, 900))])
    root, patch, img, mdl = _yolo_subtree(fake)
    with patch:
        status = _tick_until_done(root)
    img.close()
    mdl.close()
    assert status == py_trees.common.Status.SUCCESS, status
    bb = _read(("garment_kind", "perception", "board_plan", "fold_plan"))
    assert bb.garment_kind == "pants"
    assert bb.perception.owner == "mom", bb.perception.owner
    assert bb.fold_plan is None  # no crotch point from bbox
    assert bb.board_plan["panels"]
    print("PASS test_yolo_pants_kind_and_owner")


def test_yolo_no_detections_fails():
    fake = _fake_result([])  # empty frame: nothing to fold
    root, patch, img, mdl = _yolo_subtree(fake)
    with patch:
        status = _tick_until_done(root)
    img.close()
    mdl.close()
    assert status == py_trees.common.Status.FAILURE, status
    print("PASS test_yolo_no_detections_fails")


def test_yolo_kind_filter_rejects_mismatch():
    # explicit kind="shirt" but detector only sees pants -> FAILURE
    fake = _fake_result([(1, 0.88, (50, 100, 530, 900))])
    root, patch, img, mdl = _yolo_subtree(fake, kind="shirt")
    with patch:
        status = _tick_until_done(root)
    img.close()
    mdl.close()
    assert status == py_trees.common.Status.FAILURE, status
    print("PASS test_yolo_kind_filter_rejects_mismatch")


def test_yolo_prefers_highest_confidence():
    # pants lower conf, shirt higher conf -> shirt wins
    fake = _fake_result([
        (1, 0.60, (50, 100, 530, 900)),
        (0, 0.95, (100, 200, 450, 600)),
    ])
    root, patch, img, mdl = _yolo_subtree(fake)
    with patch:
        status = _tick_until_done(root)
    img.close()
    mdl.close()
    assert status == py_trees.common.Status.SUCCESS, status
    bb = _read(("garment_kind",))
    assert bb.garment_kind == "shirt", bb.garment_kind
    print("PASS test_yolo_prefers_highest_confidence")


if __name__ == "__main__":
    test_yolo_requires_image_and_calibration()
    test_yolo_end_to_end_shirt()
    test_yolo_pants_kind_and_owner()
    test_yolo_no_detections_fails()
    test_yolo_kind_filter_rejects_mismatch()
    test_yolo_prefers_highest_confidence()
    print("\nAll YOLO wiring tests passed ✅")
