"""Tests for the folding board design (M5 extension)."""
import sys
sys.path.insert(0, ".")

from planning.board import (
    plan_board_folds, panel_push_pose, hinge_slot_for_owner,
    PANEL_LEFT, PANEL_RIGHT, PANEL_BOTTOM,
)
from bt.board_actions import (
    create_place_on_board_subtree, create_flip_panel_subtree,
    create_tuck_sleeve_subtree, create_side_fold_subtree,
)


def test_hinge_slots():
    assert hinge_slot_for_owner("dad") == "adult"
    assert hinge_slot_for_owner("mom") == "adult"
    assert hinge_slot_for_owner("daughter") == "child"
    assert hinge_slot_for_owner("son") == "child"
    print("PASS test_hinge_slots")


def test_plan_board_shirt():
    # Short sleeve: 3 panels, no tuck, no side fold
    p = plan_board_folds("shirt", "dad", sleeve="short")
    assert p["slot"] == "adult"
    assert p["panels"] == [PANEL_LEFT, PANEL_RIGHT, PANEL_BOTTOM]
    assert not p["tuck_sleeves"] and not p["side_fold_first"]
    # Long sleeve: tuck sleeves first
    p = plan_board_folds("shirt", "mom", sleeve="long")
    assert p["tuck_sleeves"]
    assert p["panels"] == [PANEL_LEFT, PANEL_RIGHT, PANEL_BOTTOM]
    # Child slot
    p = plan_board_folds("shirt", "son", sleeve="short")
    assert p["slot"] == "child"
    print("PASS test_plan_board_shirt")


def test_plan_board_pants():
    # Tri-fold: side fold first, then bottom + top panels
    p = plan_board_folds("pants", "dad", pants_mode="tri")
    assert p["side_fold_first"]
    assert p["panels"] == [PANEL_BOTTOM, "top"]
    # Bi-fold: side fold + bottom only
    p = plan_board_folds("pants", "daughter", pants_mode="bi")
    assert p["side_fold_first"]
    assert p["panels"] == [PANEL_BOTTOM]
    # None: side fold only, no board needed
    p = plan_board_folds("pants", "son", pants_mode="none")
    assert p["side_fold_first"]
    assert p["panels"] == []
    print("PASS test_plan_board_pants")


def test_panel_push_pose():
    # Push poses are underneath the board (y < 0)
    for panel in [PANEL_LEFT, PANEL_RIGHT, PANEL_BOTTOM]:
        pose = panel_push_pose(panel, "adult")
        assert pose["y"] < 0, f"{panel} push should be from below"
    # Left/right are mirrored
    pl = panel_push_pose(PANEL_LEFT, "adult")
    pr = panel_push_pose(PANEL_RIGHT, "adult")
    assert abs(pl["x"] + pr["x"]) < 1e-9
    print("PASS test_panel_push_pose")


def test_board_subtrees():
    # Each builder returns a py_trees Sequence with the right children
    place = create_place_on_board_subtree({"x": 0, "z": 0, "yaw": 0})
    assert place.name == "PlaceOnBoard"
    assert len(place.children) == 6  # pick, close, move, place, open, retract

    flip = create_flip_panel_subtree(PANEL_LEFT, "adult")
    assert flip.name == "FlipPanel:left"
    assert len(flip.children) == 3  # under, push, retract

    tuck = create_tuck_sleeve_subtree("left")
    assert tuck.name == "TuckSleeve:left"
    assert len(tuck.children) == 3

    side = create_side_fold_subtree()
    assert side.name == "SideFold"
    assert len(side.children) == 5
    print("PASS test_board_subtrees")


def test_board_tree_e2e():
    """Full BT run with use_board=True."""
    import py_trees
    from bt.main_tree import create_main_tree
    root = create_main_tree(kind="tee", owner="mom", use_board=True)
    tree = py_trees.trees.BehaviourTree(root)
    tree.setup(timeout=5)
    for _ in range(500):
        tree.tick()
        if root.status != py_trees.common.Status.RUNNING:
            break
    assert root.status == py_trees.common.Status.SUCCESS, \
        f"board tree failed: {root.status}"
    print("PASS test_board_tree_e2e (use_board=True)")


if __name__ == "__main__":
    test_hinge_slots()
    test_plan_board_shirt()
    test_plan_board_pants()
    test_panel_push_pose()
    test_board_subtrees()
    test_board_tree_e2e()
    print("\nAll board tests passed!")
