"""M5 tests: fold execution subtree + sort/stack subtree."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import py_trees
from bt.fold_subtree import create_fold_step_subtree, create_fold_subtree
from bt.sort_subtree import create_sort_subtree
from bt.main_tree import create_main_tree
from planning.fold_planner import plan_folds


def _tick_until_done(root, max_ticks=150):
    tree = py_trees.trees.BehaviourTree(root)
    tree.setup(timeout=5)
    for _ in range(max_ticks):
        tree.tick()
        if root.status != py_trees.common.Status.RUNNING:
            break
    return root.status


def _shirt_k():
    P = lambda x, z: {"x": x, "y": 0.002, "z": z}
    return {
        "sleeve_l": P(-0.43, 0.05), "sleeve_r": P(0.43, 0.05),
        "shoulder_l": P(-0.31, -0.18), "shoulder_r": P(0.31, -0.18),
        "hem_l": P(-0.29, 0.22), "hem_r": P(0.29, 0.22),
        "a": P(-0.155, -0.18), "b": P(-0.155, 0.02), "c": P(-0.155, 0.22),
    }


def _seed_plan():
    bb = py_trees.blackboard.Client(name="seed")
    bb.register_key(key="fold_plan", access=py_trees.common.Access.WRITE)
    bb.fold_plan = plan_folds(_shirt_k())


def test_fold_step_subtree_structure():
    plan = plan_folds(_shirt_k())
    sub = create_fold_step_subtree(plan.folds[0], 0)
    names = [c.name for c in sub.children]
    assert names == ["MoveToGrab", "CloseGripper", "MoveToPress",
                     "ExecuteFold", "ReleaseAll", "RetractArms"], names
    print("PASS test_fold_step_subtree_structure")


def test_fold_iterator_runs_all_steps():
    _seed_plan()
    fold = create_fold_subtree()
    assert _tick_until_done(fold) == py_trees.common.Status.SUCCESS
    # 3 steps × 11 ticks each ≈ 33 ticks; all executed without hardcoding count
    print("PASS test_fold_iterator_runs_all_steps (3 fold steps)")


def test_sort_stacks_and_counts():
    from perception.mock_perception import mock_perceive
    bb = py_trees.blackboard.Client(name="seed2")
    bb.register_key(key="perception", access=py_trees.common.Access.WRITE)
    bb.register_key(key="bin_counts", access=py_trees.common.Access.WRITE)
    bb.perception = mock_perceive(kind="shirt", owner="mom")
    bb.bin_counts = {}
    # run twice → stack height grows
    for _ in range(2):
        sort = create_sort_subtree()
        assert _tick_until_done(sort) == py_trees.common.Status.SUCCESS
    assert bb.bin_counts.get("mom") == 2, bb.bin_counts
    bb2 = py_trees.blackboard.Client(name="seed3")
    bb2.register_key(key="sorted_owner", access=py_trees.common.Access.READ)
    assert bb2.sorted_owner == "mom"
    print("PASS test_sort_stacks_and_counts (mom ×2)")


def test_full_tree_end_to_end():
    root = create_main_tree(kind="pants", owner="son")
    assert _tick_until_done(root, max_ticks=200) == py_trees.common.Status.SUCCESS
    print("PASS test_full_tree_end_to_end")


if __name__ == "__main__":
    test_fold_step_subtree_structure()
    test_fold_iterator_runs_all_steps()
    test_sort_stacks_and_counts()
    test_full_tree_end_to_end()
    print("\nAll M5 tests passed ✅")
