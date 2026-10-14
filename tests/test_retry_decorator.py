"""Tests for bt/retry_decorator.RetryWithLog (item 8: grasp-retry)."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import py_trees
from bt.retry_decorator import RetryWithLog
from bt.board_actions import (
    create_flip_panel_subtree, create_side_fold_subtree,
    create_arm_length_fold_subtree, create_place_on_board_subtree,
)
from planning.board import PANEL_LEFT


class FlakyChild(py_trees.behaviour.Behaviour):
    """Succeeds on the `succeed_on_attempt`-th attempt (1-based), fails before.

    attempts: how many times initialise() ran = attempts actually started.
    """

    def __init__(self, succeed_on_attempt=1, name="FlakyChild"):
        super().__init__(name)
        self._succeed_on = succeed_on_attempt
        self.attempts = 0

    def initialise(self):
        self.attempts += 1

    def update(self):
        if self.attempts < self._succeed_on:
            return py_trees.common.Status.FAILURE
        return py_trees.common.Status.SUCCESS


def _tick_until_done(root, max_ticks=60):
    tree = py_trees.trees.BehaviourTree(root)
    tree.setup(timeout=5)
    for _ in range(max_ticks):
        tree.tick()
        if root.status != py_trees.common.Status.RUNNING:
            break
    return root.status


def test_success_first_try():
    node = RetryWithLog("R", FlakyChild(succeed_on_attempt=1), max_attempts=3)
    assert _tick_until_done(node) == py_trees.common.Status.SUCCESS
    assert node.attempts_used == 1
    assert node.decorated.attempts == 1
    print("PASS test_success_first_try (1 attempt)")


def test_retry_then_success():
    calls = []
    node = RetryWithLog("R", FlakyChild(succeed_on_attempt=3), max_attempts=3,
                        on_retry=lambda n: calls.append(n))
    assert _tick_until_done(node) == py_trees.common.Status.SUCCESS
    assert node.attempts_used == 3
    assert node.decorated.attempts == 3
    assert calls == [1, 2], calls  # hook fired before attempts 2 and 3
    print("PASS test_retry_then_success (failed twice, ok on 3rd)")


def test_give_up_after_max_attempts():
    node = RetryWithLog("R", FlakyChild(succeed_on_attempt=99), max_attempts=3)
    assert _tick_until_done(node) == py_trees.common.Status.FAILURE
    assert node.attempts_used == 3
    assert node.decorated.attempts == 3  # exactly 3 child attempts, no more
    assert "gave up" in node.feedback_message
    print("PASS test_give_up_after_max_attempts (FAILURE after 3)")


def test_single_attempt_no_retry():
    node = RetryWithLog("R", FlakyChild(succeed_on_attempt=99), max_attempts=1)
    assert _tick_until_done(node) == py_trees.common.Status.FAILURE
    assert node.attempts_used == 1
    print("PASS test_single_attempt_no_retry")


def test_invalid_max_attempts():
    with pytest.raises(ValueError):
        RetryWithLog("R", FlakyChild(), max_attempts=0)
    print("PASS test_invalid_max_attempts")


def test_retry_resets_between_tree_runs():
    # attempts_used must not leak from one run into the next.
    node = RetryWithLog("R", FlakyChild(succeed_on_attempt=2), max_attempts=3)
    assert _tick_until_done(node) == py_trees.common.Status.SUCCESS
    assert node.attempts_used == 2
    node.stop(py_trees.common.Status.INVALID)
    # New garment on the real robot: the child's world state is fresh, but the
    # SAME decorator node is re-ticked — its count must start over, not add up.
    node.decorated.attempts = 0
    assert _tick_until_done(node) == py_trees.common.Status.SUCCESS
    assert node.attempts_used == 2  # fresh count, not 4
    print("PASS test_retry_resets_between_tree_runs")


def test_board_grasp_steps_wrapped():
    # Each board grasp pair is now (RetryWithLog -> Sequence[move, close]).
    for builder, kwargs, retry_name in [
        (create_flip_panel_subtree, (PANEL_LEFT, "adult"), "RetryPanelGrasp"),
        (create_side_fold_subtree, (), "RetryLegGrasp"),
        (create_arm_length_fold_subtree, (), "RetryWaistGrasp"),
    ]:
        sub = builder(*kwargs) if kwargs else builder()
        first = sub.children[0]
        assert isinstance(first, RetryWithLog), f"{sub.name}: {type(first)}"
        assert first.name == retry_name, first.name
        inner = first.children[0]
        assert [c.name for c in inner.children] == [
            inner.children[0].name, "CloseGripper"]
    place = create_place_on_board_subtree({"x": 0, "z": 0, "yaw": 0})
    first = place.children[0]
    assert isinstance(first, RetryWithLog) and first.name == "RetryPickGrasp"
    print("PASS test_board_grasp_steps_wrapped")


def test_board_subtree_still_runs_end_to_end():
    # Mock path: grasp succeeds on attempt 1, decorator passes through.
    flip = create_flip_panel_subtree(PANEL_LEFT, "adult")
    assert _tick_until_done(flip) == py_trees.common.Status.SUCCESS
    retry = flip.children[0]
    assert retry.attempts_used == 1
    print("PASS test_board_subtree_still_runs_end_to_end")


if __name__ == "__main__":
    test_success_first_try()
    test_retry_then_success()
    test_give_up_after_max_attempts()
    test_single_attempt_no_retry()
    test_invalid_max_attempts()
    test_retry_resets_between_tree_runs()
    test_board_grasp_steps_wrapped()
    test_board_subtree_still_runs_end_to_end()
    print("\nAll retry tests passed!")
