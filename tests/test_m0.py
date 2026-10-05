"""M0 tests: BT main tree runs end-to-end with mock perception; fold math sanity."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import math
import py_trees
from bt.main_tree import create_main_tree
from planning.fold_math import side_of_line, fold_point_vert, ease_in_out_cubic
from perception.mock_perception import mock_perceive


def test_main_tree_completes():
    root = create_main_tree()
    tree = py_trees.trees.BehaviourTree(root)
    tree.setup(timeout=5)
    ticks = 0
    while root.status == py_trees.common.Status.INVALID or \
            root.status == py_trees.common.Status.RUNNING:
        tree.tick()
        ticks += 1
        assert ticks < 100, "tree did not finish"
    assert root.status == py_trees.common.Status.SUCCESS, f"tree failed: {root.status}"
    print(f"PASS test_main_tree_completes ({ticks} ticks)")


def test_mock_perception_owners():
    for kind in ("shirt", "pants"):
        for owner in ("dad", "mom", "daughter", "son"):
            r = mock_perceive(kind, owner)
            assert r.kind == kind and r.owner == owner
    print("PASS test_mock_perception_owners (8 combos)")


def test_fold_math():
    # side_of_line sign
    assert side_of_line(0, 0, 1, 0, 0, 1) > 0
    assert side_of_line(0, 0, 1, 0, 0, -1) < 0
    # fold a point straight up: t=1 should mirror it across the crease plane
    p = fold_point_vert(0, 0, 1, 0, 0.0, 1, 1.0, 0.5, 0.0, 0.3)
    assert abs(p["x"] - 0.5) < 1e-9 and abs(p["z"] + 0.3) < 1e-9, p
    assert abs(ease_in_out_cubic(0.5) - 0.5) < 1e-9
    print("PASS test_fold_math")


if __name__ == "__main__":
    test_fold_math()
    test_mock_perception_owners()
    test_main_tree_completes()
    print("\nAll M0 tests passed ✅")
