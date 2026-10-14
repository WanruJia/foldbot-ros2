"""M3 tests: PickFromBasket subtree with 3-attempt grasp retry."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import py_trees
from bt.pick_subtree import create_pick_subtree
from bt.main_tree import create_main_tree
from bt.retry_decorator import RetryWithLog


def _tick_until_done(root, max_ticks=50):
    tree = py_trees.trees.BehaviourTree(root)
    tree.setup(timeout=5)
    for _ in range(max_ticks):
        tree.tick()
        if root.status != py_trees.common.Status.RUNNING:
            break
    return root.status


def test_pick_subtree_structure():
    pick, verify = create_pick_subtree()
    names = [c.name for c in pick.children]
    assert names == ["MoveToBasket", "DescendToGarment", "GraspWithRetry",
                     "MoveToFoldZone", "ReleaseGarment", "RetractArm"], names
    retry = pick.children[2]
    # Item 8 cleanup (2026-10-14): the silent py_trees.decorators.Retry is
    # retired — GraspWithRetry is now the honest, attempt-counted decorator
    # shared with the board grasp pairs.
    assert isinstance(retry, RetryWithLog)
    assert retry.max_attempts == 3
    seq_names = [c.name for c in retry.children[0].children]
    assert seq_names == ["CloseGripper", "LiftSlightly", "VerifyGrasp"], seq_names
    print("PASS test_pick_subtree_structure")


def test_grasp_retry():
    # Fail first attempt, succeed on second → subtree still succeeds
    pick, verify = create_pick_subtree(succeed_on_attempt=2)
    status = _tick_until_done(pick)
    assert status == py_trees.common.Status.SUCCESS, status
    assert verify.attempts == 2, f"expected 2 attempts, got {verify.attempts}"
    bb = py_trees.blackboard.Client(name="t")
    bb.register_key(key="grasp_attempts", access=py_trees.common.Access.READ)
    assert bb.grasp_attempts == 2
    print("PASS test_grasp_retry (failed 1st, ok 2nd)")


def test_grasp_gives_up_after_3():
    # Never succeeds → Retry exhausts 3 attempts → subtree fails
    pick, verify = create_pick_subtree(succeed_on_attempt=99)
    status = _tick_until_done(pick)
    assert status == py_trees.common.Status.FAILURE, status
    assert verify.attempts == 3, f"expected 3 attempts, got {verify.attempts}"
    print("PASS test_grasp_gives_up_after_3")


def test_grasp_retry_attempts_honest():
    # Unification: GraspWithRetry counts attempts the same way the board
    # grasp pairs do — attempts_used matches the VerifyGrasp attempt counter
    # both on recovery and on give-up.
    pick, verify = create_pick_subtree(succeed_on_attempt=2)
    assert _tick_until_done(pick) == py_trees.common.Status.SUCCESS
    retry = pick.children[2]
    assert retry.attempts_used == 2 == verify.attempts

    pick2, verify2 = create_pick_subtree(succeed_on_attempt=99)
    assert _tick_until_done(pick2) == py_trees.common.Status.FAILURE
    retry2 = pick2.children[2]
    assert retry2.attempts_used == 3 == verify2.attempts
    print("PASS test_grasp_retry_attempts_honest")


def test_grasp_on_retry_hook():
    # The unified decorator exposes the on_retry hook on the pick path too:
    # a hook that re-observes (mock: just records) runs before each re-attempt.
    from bt.pick_subtree import create_pick_subtree  # local for clarity
    pick, verify = create_pick_subtree(succeed_on_attempt=2)
    retry = pick.children[2]
    calls = []
    retry.on_retry = lambda failures_so_far: calls.append(failures_so_far)
    assert _tick_until_done(pick) == py_trees.common.Status.SUCCESS
    assert calls == [1], f"on_retry should fire once before attempt 2, got {calls}"
    print("PASS test_grasp_on_retry_hook")


def test_full_tree_with_new_pick():
    root = create_main_tree()
    status = _tick_until_done(root, max_ticks=80)
    assert status == py_trees.common.Status.SUCCESS, status
    print("PASS test_full_tree_with_new_pick")


if __name__ == "__main__":
    test_pick_subtree_structure()
    test_grasp_retry()
    test_grasp_gives_up_after_3()
    test_grasp_retry_attempts_honest()
    test_grasp_on_retry_hook()
    test_full_tree_with_new_pick()
    print("\nAll M3 tests passed ✅")
