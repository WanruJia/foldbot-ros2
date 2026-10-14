"""Pants pipeline tests: contour-based leg split + waist edge (no keypoints).

Covers perception.pants_shape (leg-merging + waist-grab analysis) and its
wiring into bt.board_actions (SideFold skip when legs are already merged,
contour grasp details) and bt.perceive_subtree (yolo pants mode publishes
"pants_shape" on the blackboard).
"""
import sys
import os
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest import mock
import numpy as np
import py_trees
from PIL import Image

from perception.pants_shape import (
    segment_garment, find_leg_split, find_waist_edge,
    analyze_pants, pants_shape_board,
)
from bt.board_actions import (
    create_side_fold_subtree, create_arm_length_fold_subtree,
    create_board_fold_subtree,
)
from bt.perceive_subtree import create_perceive_subtree
from planning.board import plan_board_folds


def _draw_pants(h=200, w=200, bg=200, fg=40,
                waist_top=10, waist_h=20, waist_x1=60, waist_x2=140,
                gap=(95, 105), cuff_bottom=190, merged=False):
    """Synthetic waist-up pants: waist band + two legs with an inseam gap."""
    img = np.full((h, w), bg, dtype=np.uint8)
    img[waist_top:waist_top + waist_h, waist_x1:waist_x2] = fg
    leg_top = waist_top + waist_h
    if merged:
        img[leg_top:cuff_bottom, waist_x1:waist_x2] = fg
    else:
        img[leg_top:cuff_bottom, waist_x1:gap[0]] = fg
        img[leg_top:cuff_bottom, gap[1]:waist_x2] = fg
    return img


def _tick_until_done(root, max_ticks=120):
    tree = py_trees.trees.BehaviourTree(root)
    tree.setup(timeout=5)
    for _ in range(max_ticks):
        tree.tick()
        if root.status != py_trees.common.Status.RUNNING:
            break
    return root.status


def test_segment_garment_finds_pants():
    mask = segment_garment(_draw_pants())
    assert mask is not None and mask.dtype == bool
    # garment area: waist 20x80 + legs 160x(35+35) = 12800 px
    assert abs(int(mask.sum()) - 12800) < 200, mask.sum()
    print("PASS test_segment_garment_finds_pants")


def test_segment_uniform_image_returns_none():
    img = np.full((100, 100), 200, dtype=np.uint8)
    assert segment_garment(img) is None
    assert segment_garment(np.full((5, 5), 40, dtype=np.uint8)) is None
    print("PASS test_segment_uniform_image_returns_none")


def test_leg_split_geometry():
    mask = segment_garment(_draw_pants())
    legs = find_leg_split(mask)
    assert legs is not None
    assert legs["cuff_row"] == 189, legs
    assert legs["crotch_row"] == 29, legs  # first single-run row above legs
    assert legs["leg_cols"] == [(60, 95), (105, 140)], legs
    assert legs["mid_col"] == 100.0, legs
    # grab row: 20% up from the cuff inside the leg block -> row 158
    assert legs["grasp"] == (60.0, 158.0), legs
    # fold target mirrors the grasp across the inseam midline
    assert legs["fold_target"] == (140.0, 158.0), legs
    print("PASS test_leg_split_geometry")


def test_legs_already_merged_returns_none():
    mask = segment_garment(_draw_pants(merged=True))
    assert find_leg_split(mask) is None  # single run all the way down
    shape = analyze_pants(_draw_pants(merged=True))
    assert shape["ok"] is True
    assert shape["legs"] is None       # -> caller skips the side fold
    assert shape["waist"] is not None  # waist still found
    print("PASS test_legs_already_merged_returns_none")


def test_shorts_legs_still_found():
    mask = segment_garment(_draw_pants(waist_top=10, waist_h=20,
                                       cuff_bottom=70))
    legs = find_leg_split(mask)
    assert legs is not None
    assert legs["crotch_row"] == 29, legs
    print("PASS test_shorts_legs_still_found")


def test_waist_edge_endpoints():
    mask = segment_garment(_draw_pants())
    waist = find_waist_edge(mask)
    assert waist is not None
    assert waist["row"] == 10, waist
    assert (waist["x1"], waist["x2"]) == (60, 140), waist
    assert waist["grab"] == (100.0, 10.0), waist
    print("PASS test_waist_edge_endpoints")


def test_analyze_pants_bbox_crop_and_origin():
    big = np.full((400, 400), 200, dtype=np.uint8)
    big[40:240, 50:250] = _draw_pants()
    shape = analyze_pants(big, bbox=(50, 40, 250, 240), pad=0)
    assert shape["ok"] is True
    assert shape["origin"] == (50, 40), shape["origin"]
    assert shape["legs"]["grasp"] == (60.0, 158.0)  # crop pixels
    board = pants_shape_board(shape, px_per_m=1000.0)
    g = board["legs"]["grasp"]
    assert abs(g[0] - 0.110) < 1e-9 and abs(g[2] - 0.198) < 1e-9, g
    assert g[1] == 0.005, g  # board surface + clearance
    x1, x2 = board["waist"]["x1"], board["waist"]["x2"]
    assert abs(x1[0] - 0.110) < 1e-9 and abs(x2[0] - 0.190) < 1e-9
    assert abs(x1[2] - 0.050) < 1e-9, x1  # waist row 10 + origin 40
    print("PASS test_analyze_pants_bbox_crop_and_origin")


def test_analyze_pants_unsegmentable():
    shape = analyze_pants(np.full((100, 100), 200, dtype=np.uint8))
    assert shape == {"ok": False, "origin": (0, 0),
                     "legs": None, "waist": None}, shape
    print("PASS test_analyze_pants_unsegmentable")


def test_pants_shape_board_needs_calibration():
    shape = analyze_pants(_draw_pants())
    try:
        pants_shape_board(shape, px_per_m=None)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for px_per_m=None")
    print("PASS test_pants_shape_board_needs_calibration")


def _board_shape(legs=True):
    shape = analyze_pants(_draw_pants())
    board = pants_shape_board(shape, px_per_m=1000.0)
    if not legs:
        board["legs"] = None
    return board


def test_side_fold_builder_skips_when_merged():
    assert create_side_fold_subtree({"legs": None, "waist": None}) is None
    generic = create_side_fold_subtree(None)
    assert generic.name == "SideFold"
    assert "contour" not in generic.children[0].decorated.children[0]._detail
    shaped = create_side_fold_subtree(_board_shape(legs=True))
    assert shaped.name == "SideFold"
    assert "contour" in shaped.children[0].decorated.children[0]._detail, shaped.children[0].decorated.children[0]._detail
    print("PASS test_side_fold_builder_skips_when_merged")


def test_arm_fold_builder_uses_waist():
    generic = create_arm_length_fold_subtree(None)
    assert "contour" not in generic.children[0].decorated.children[0]._detail
    shaped = create_arm_length_fold_subtree(_board_shape(legs=True))
    d = shaped.children[0].decorated.children[0]._detail
    assert "contour" in d and "0.060" in d and "0.140" in d, d
    print("PASS test_arm_fold_builder_uses_waist")


def _seed_board(pants_shape):
    bb = py_trees.blackboard.Client(name="seed_pants_shape")
    bb.register_key(key="board_plan", access=py_trees.common.Access.WRITE)
    bb.register_key(key="pants_shape", access=py_trees.common.Access.WRITE)
    bb.board_plan = plan_board_folds("pants", "dad", pants_mode="tri")
    bb.pants_shape = pants_shape


def _child_names(it):
    return [c.name for c in it._seq.children]


def test_iterator_skips_side_fold_when_merged():
    _seed_board({"legs": None, "waist": None})
    it = create_board_fold_subtree()
    assert _tick_until_done(it) == py_trees.common.Status.SUCCESS
    names = _child_names(it)
    assert "SideFold" not in names, names
    assert names == ["PlaceOnBoard", "FlipPanel:bottom", "ArmLengthFold"], names
    print("PASS test_iterator_skips_side_fold_when_merged")


def test_iterator_runs_side_fold_when_split():
    _seed_board(_board_shape(legs=True))
    it = create_board_fold_subtree()
    assert _tick_until_done(it) == py_trees.common.Status.SUCCESS
    names = _child_names(it)
    assert names[0] == "SideFold", names
    assert "ArmLengthFold" in names, names
    print("PASS test_iterator_runs_side_fold_when_split")


class _T:
    def __init__(self, v):
        self.v = v

    def __int__(self):
        return int(self.v)

    def __float__(self):
        return float(self.v)


def _fake_pants_result():
    class B:
        cls, conf = _T(1), _T(0.9)
        xyxy = [[60.0, 10.0, 140.0, 190.0]]

    class R:
        names = {0: "shirt", 1: "pants"}
        boxes = [B()]
    return R()


def test_yolo_pants_shape_end_to_end():
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    Image.fromarray(_draw_pants()).save(tmp.name)
    tmp.close()
    mdl = tempfile.NamedTemporaryFile(suffix=".pt")
    patch = mock.patch("perception.yolo_perception._detect",
                       return_value=_fake_pants_result())
    root = create_perceive_subtree(perception="yolo", image_path=tmp.name,
                                   px_per_m=1000.0, model_path=mdl.name,
                                   kind="pants")
    with patch:
        status = _tick_until_done(root)
    os.unlink(tmp.name)
    mdl.close()
    assert status == py_trees.common.Status.SUCCESS, status
    bb = py_trees.blackboard.Client(name="read_pants_shape")
    bb.register_key(key="pants_shape", access=py_trees.common.Access.READ)
    bb.register_key(key="garment_kind", access=py_trees.common.Access.READ)
    assert bb.garment_kind == "pants"
    ps = bb.pants_shape
    assert ps is not None and ps["legs"] is not None, ps
    # bbox (60,10)-(140,190) + pad 8 -> origin (52,2); the garment's true
    # frame pixels are grasp (60,158) -> fold target (140,158), waist
    # edge (60,10)-(140,10).
    g = ps["legs"]["grasp"]
    assert abs(g[0] - 0.060) < 1e-9 and abs(g[2] - 0.158) < 1e-9, g
    assert g[1] == 0.005, g
    t = ps["legs"]["fold_target"]
    assert abs(t[0] - 0.140) < 1e-9 and abs(t[2] - 0.158) < 1e-9, t
    x1, x2 = ps["waist"]["x1"], ps["waist"]["x2"]
    assert abs(x1[0] - 0.060) < 1e-9 and abs(x2[0] - 0.140) < 1e-9, (x1, x2)
    assert abs(x1[2] - 0.010) < 1e-9, x1
    print("PASS test_yolo_pants_shape_end_to_end")


if __name__ == "__main__":
    test_segment_garment_finds_pants()
    test_segment_uniform_image_returns_none()
    test_leg_split_geometry()
    test_legs_already_merged_returns_none()
    test_shorts_legs_still_found()
    test_waist_edge_endpoints()
    test_analyze_pants_bbox_crop_and_origin()
    test_analyze_pants_unsegmentable()
    test_pants_shape_board_needs_calibration()
    test_side_fold_builder_skips_when_merged()
    test_arm_fold_builder_uses_waist()
    test_iterator_skips_side_fold_when_merged()
    test_iterator_runs_side_fold_when_split()
    test_yolo_pants_shape_end_to_end()
    print("\nAll pants-shape tests passed ✅")
