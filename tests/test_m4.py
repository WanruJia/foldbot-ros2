"""M4 tests: PerceiveAndPlan subtree with the real M2 planner wired in."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import py_trees
from bt.perceive_subtree import create_perceive_subtree
from bt.main_tree import create_main_tree


def _tick_until_done(root, max_ticks=80):
    tree = py_trees.trees.BehaviourTree(root)
    tree.setup(timeout=5)
    for _ in range(max_ticks):
        tree.tick()
        if root.status != py_trees.common.Status.RUNNING:
            break
    return root.status


def test_perceive_subtree_structure():
    root = create_perceive_subtree()
    names = [c.name for c in root.children]
    assert names == ["CaptureImage", "ClassifyGarment", "DetectKeypoints",
                     "ClassifyOwner", "PlanFolds"], names
    print("PASS test_perceive_subtree_structure")


def test_shirt_gets_3_fold_plan():
    root = create_perceive_subtree(kind="shirt", owner="mom")
    assert _tick_until_done(root) == py_trees.common.Status.SUCCESS
    bb = py_trees.blackboard.Client(name="t")
    for k in ("garment_kind", "keypoints", "perception", "fold_plan"):
        bb.register_key(key=k, access=py_trees.common.Access.READ)
    assert bb.garment_kind == "shirt"
    assert bb.perception.owner == "mom"  # real classifier on mock keypoints
    plan = bb.fold_plan
    assert len(plan.folds) == 3, f"shirt plan should have 3 folds, got {len(plan.folds)}"
    assert [f.label for f in plan.folds] == ["左折", "右折", "对折"]
    print("PASS test_shirt_gets_3_fold_plan")


def test_pants_dad_long_gets_tri():
    root = create_perceive_subtree(kind="pants", owner="dad")
    assert _tick_until_done(root) == py_trees.common.Status.SUCCESS
    bb = py_trees.blackboard.Client(name="t2")
    for k in ("perception", "fold_plan"):
        bb.register_key(key=k, access=py_trees.common.Access.READ)
    plan = bb.fold_plan
    assert len(plan.folds) == 3, f"dad long pants should be tri (3 folds), got {len(plan.folds)}"
    print("PASS test_pants_dad_long_gets_tri")


def test_full_tree_end_to_end():
    root = create_main_tree(kind="shirt", owner="daughter")
    assert _tick_until_done(root, max_ticks=120) == py_trees.common.Status.SUCCESS
    bb = py_trees.blackboard.Client(name="t3")
    bb.register_key(key="sorted_owner", access=py_trees.common.Access.READ)
    assert bb.sorted_owner == "daughter", bb.sorted_owner
    print("PASS test_full_tree_end_to_end")


if __name__ == "__main__":
    test_perceive_subtree_structure()
    test_shirt_gets_3_fold_plan()
    test_pants_dad_long_gets_tri()
    test_full_tree_end_to_end()
    print("\nAll M4 tests passed ✅")
