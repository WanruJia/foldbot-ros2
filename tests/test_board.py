"""Tests for the folding board design (M5 extension)."""
import sys
sys.path.insert(0, ".")

from planning.board import (
    plan_board_folds, panel_push_pose, hinge_slot_for_owner,
    PANEL_LEFT, PANEL_RIGHT, PANEL_BOTTOM, BoardFoldSimulator,
)
from bt.board_actions import (
    create_place_on_board_subtree, create_flip_panel_subtree,
    create_tuck_sleeve_subtree, create_side_fold_subtree,
    create_arm_length_fold_subtree,
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
    # Tri-fold: side fold first, bottom panel, then ARM folds top down
    # (v1.3: middle-top panel is fixed, no physical top panel — arm does it)
    p = plan_board_folds("pants", "dad", pants_mode="tri")
    assert p["side_fold_first"]
    assert p["panels"] == [PANEL_BOTTOM, "arm_fold"]
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
    # Grab poses are at the panel edge (y >= 0, above board surface)
    # v1.2: changed from push-from-below to grab-edge
    for panel in [PANEL_LEFT, PANEL_RIGHT, PANEL_BOTTOM]:
        pose = panel_push_pose(panel, "adult")
        assert pose["y"] >= 0, f"{panel} grab should be at/above board"
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
    assert len(flip.children) == 7  # grab edge, flip up, pause, return, release, retract

    tuck = create_tuck_sleeve_subtree("left")
    assert tuck.name == "TuckSleeve:left"
    assert len(tuck.children) == 3

    side = create_side_fold_subtree()
    assert side.name == "SideFold"
    assert len(side.children) == 5

    armfold = create_arm_length_fold_subtree()
    assert armfold.name == "ArmLengthFold"
    assert len(armfold.children) == 5  # move, grab, fold down, release, retract
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


def test_fold_simulator():
    """BoardFoldSimulator: vertex-level fold math matches viz behavior.

    Simulates a mom-size tee (scaled to board) with sleeves sticking out.
    After left+right+bottom flips, garment should fit the center column.
    """
    # Simplified garment: body + sleeves, in board coords (meters)
    # Body: x in [-0.216, 0.216], z in [-0.14, 0.14]
    # Sleeves stick out to x=±0.32
    verts = []
    # body corners
    for x in (-0.216, 0.216):
        for z in (-0.14, 0.14):
            verts.append({"x": x, "y": 0.002, "z": z})
    # sleeve tips (the parts that stick out)
    for x in (-0.32, 0.32):
        verts.append({"x": x, "y": 0.002, "z": -0.05})
    # center points
    verts.append({"x": 0.0, "y": 0.002, "z": -0.14})
    verts.append({"x": 0.0, "y": 0.002, "z": 0.14})

    sim = BoardFoldSimulator(verts)
    # Check panel assignment
    # x=-0.32 → left, x=0.32 → right, x=0,z=0.14 → bottom, x=0,z=-0.14 → center
    assert sim.panel_of[4] == PANEL_LEFT, f"sleeve L: {sim.panel_of[4]}"
    assert sim.panel_of[5] == PANEL_RIGHT, f"sleeve R: {sim.panel_of[5]}"
    assert sim.panel_of[7] == PANEL_BOTTOM, f"hem: {sim.panel_of[7]}"
    assert sim.panel_of[6] == "center", f"shoulder: {sim.panel_of[6]}"

    # Flip left: sleeve L folds to center
    sim.apply_panel_fold(PANEL_LEFT)
    # sleeve tip at x=-0.32, d=-(-0.32+0.125)=0.195, new x=-0.125+0.195=0.07
    assert abs(sim.pos[4]["x"] - 0.07) < 0.01, f"sleeve L x: {sim.pos[4]['x']}"

    # Flip right: sleeve R folds to center
    sim.apply_panel_fold(PANEL_RIGHT)
    assert abs(sim.pos[5]["x"] - (-0.07)) < 0.01, f"sleeve R x: {sim.pos[5]['x']}"

    # Flip bottom: hem + folded sleeves (now at z>0) fold up
    # Before: put a sleeve vertex at z>0 to simulate side-folded sleeve on bottom panel
    sim2 = BoardFoldSimulator(verts)
    sim2.apply_panel_fold(PANEL_LEFT)
    sim2.apply_panel_fold(PANEL_RIGHT)
    # Manually move a folded sleeve to z>0 (as the viz does after side folds)
    # Actually the test verts have sleeves at z=-0.05, so let's just check hem
    sim2.apply_panel_fold(PANEL_BOTTOM)
    # hem at z=0.14 → z=-0.14
    assert abs(sim2.pos[7]["z"] - (-0.14)) < 0.01, f"hem z: {sim2.pos[7]['z']}"

    # Full sequence: should fit center column
    sim3 = BoardFoldSimulator(verts)
    sim3.apply_sequence([PANEL_LEFT, PANEL_RIGHT, PANEL_BOTTOM])
    assert sim3.is_folded_clean(), f"bbox: {sim3.bounding_box()}"
    print("PASS test_fold_simulator")


if __name__ == "__main__":
    test_hinge_slots()
    test_plan_board_shirt()
    test_plan_board_pants()
    test_panel_push_pose()
    test_board_subtrees()
    test_board_tree_e2e()
    test_fold_simulator()
    print("\nAll board tests passed!")


