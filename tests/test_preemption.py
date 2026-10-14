"""Tests for task preemption (bt/preemption.py, item 8 second half)."""
import sys
sys.path.insert(0, ".")

import py_trees

from bt.preemption import (
    PreemptibleSubtree, create_preemptible, request_preemption,
    clear_preemption,
)
from bt.board_actions import create_flip_panel_subtree
from bt.main_tree import create_main_tree

RUNNING = py_trees.common.Status.RUNNING
SUCCESS = py_trees.common.Status.SUCCESS
FAILURE = py_trees.common.Status.FAILURE
INVALID = py_trees.common.Status.INVALID


def _get(bb, key, default=None):
    # py_trees blackboard raises KeyError (not AttributeError) for a key
    # nobody ever wrote — getattr()'s default does not catch it.
    try:
        return getattr(bb, key)
    except (KeyError, AttributeError):
        return default


def _bb():
    bb = py_trees.blackboard.Client(name="preempt_test")
    bb.register_key(key="preempt_request",
                    access=py_trees.common.Access.WRITE)
    bb.register_key(key="preempted", access=py_trees.common.Access.WRITE)
    bb.register_key(key="preempt_reason",
                    access=py_trees.common.Access.WRITE)
    bb.register_key(key="sorted_owner", access=py_trees.common.Access.READ)
    return bb


def _tick_until(wrapper, predicate, cap=200):
    tree = py_trees.trees.BehaviourTree(wrapper)
    tree.setup(timeout=5)
    for _ in range(cap):
        tree.tick()
        if predicate(wrapper):
            break
    return tree


def test_no_preemption_transparent():
    # No request: the fold runs to completion exactly as before, and the
    # preemption record stays clean.
    clear_preemption()
    parked = []
    w = PreemptibleSubtree(name="P", child=create_flip_panel_subtree(
        "left", "adult"), on_park=lambda: parked.append(1))
    _tick_until(w, lambda n: n.status != RUNNING)
    assert w.status == SUCCESS, w.status
    assert w.parked is False and parked == []
    bb = _bb()
    assert _get(bb, "preempted", None) is False
    assert _get(bb, "preempt_request", None) is None
    print("PASS test_no_preemption_transparent")


def test_preempt_mid_fold():
    # Request mid-fold: the running child is stopped, arms park, the abort
    # is recorded honestly, and the wrapper reports FAILURE (not success).
    clear_preemption()
    parked = []
    w = PreemptibleSubtree(name="P", child=create_flip_panel_subtree(
        "left", "adult"), on_park=lambda: parked.append(1))
    tree = py_trees.trees.BehaviourTree(w)
    tree.setup(timeout=5)
    for _ in range(200):
        tree.tick()
        if w.status == RUNNING:
            break
    assert w.status == RUNNING, "fold should still be running"
    request_preemption("new garment placed")
    tree.tick()
    assert w.status == FAILURE, w.status
    assert w.parked is True and parked == [1]
    bb = _bb()
    assert bb.preempted is True
    assert bb.preempt_reason == "new garment placed"
    assert bb.preempt_request is None  # request consumed, not leaked
    assert w._child.status == INVALID  # running child was stopped
    print("PASS test_preempt_mid_fold")


def test_preempt_before_start():
    # Requested before the fold ever started: nothing ran, so FAILURE is the
    # honest outcome — the garment was not folded.
    clear_preemption()
    request_preemption("operator stop")
    w = PreemptibleSubtree(name="P",
                           child=create_flip_panel_subtree("left", "adult"))
    _tick_until(w, lambda n: n.status != RUNNING)
    assert w.status == FAILURE, w.status
    assert w.parked is True
    assert w._child.status == INVALID  # child never ticked
    bb = _bb()
    assert bb.preempted is True
    print("PASS test_preempt_before_start")


def test_late_preemption_reports_real_outcome():
    # A request that arrives after the fold genuinely completed is moot:
    # the real SUCCESS is reported, the stale request is cleared, and no
    # phantom abort is recorded.
    clear_preemption()
    w = PreemptibleSubtree(name="P",
                           child=create_flip_panel_subtree("left", "adult"))
    _tick_until(w, lambda n: n.status != RUNNING)
    assert w.status == SUCCESS
    request_preemption("too late")
    tree = py_trees.trees.BehaviourTree(w)
    tree.setup(timeout=5)
    tree.tick()
    assert w.status == SUCCESS, w.status
    bb = _bb()
    assert _get(bb, "preempted", None) is False
    assert _get(bb, "preempt_request", None) is None
    assert w.parked is False
    print("PASS test_late_preemption_reports_real_outcome")


def test_main_tree_preemption_wiring():
    from bt.board_actions import BoardFoldIterator
    clear_preemption()
    default = create_main_tree()
    assert isinstance(default.children[2], BoardFoldIterator)
    guarded = create_main_tree(preemption=True)
    fold = guarded.children[2]
    assert isinstance(fold, PreemptibleSubtree), type(fold)
    assert isinstance(fold._child, BoardFoldIterator)
    print("PASS test_main_tree_preemption_wiring")


def _run_main(preempt_at_running):
    """Run the full mock main tree; optionally preempt once the fold runs."""
    clear_preemption()
    root = create_main_tree(preemption=True)
    # Sentinel: the blackboard is process-global and earlier test files run
    # full main trees, so "sort never ran" can only be proved by a value
    # that survives this run unchanged.
    bb = py_trees.blackboard.Client(name="preempt_sentinel")
    bb.register_key(key="sorted_owner", access=py_trees.common.Access.WRITE)
    bb.sorted_owner = "SENTINEL-not-sorted"
    tree = py_trees.trees.BehaviourTree(root)
    tree.setup(timeout=5)
    fold = root.children[2]
    preempted = False
    for _ in range(500):
        tree.tick()
        if root.status != RUNNING:
            break
        if preempt_at_running and not preempted and fold.status == RUNNING:
            request_preemption("operator stop")
            preempted = True
    return root


def test_main_tree_preempt_integration():
    # Full tree, preempted mid-fold: the cycle FAILS and SortToBin never
    # runs — a half-folded garment must not be sorted into a family bin.
    root = _run_main(preempt_at_running=True)
    assert root.status == FAILURE, root.status
    bb = _bb()
    assert _get(bb, "sorted_owner", None) == "SENTINEL-not-sorted"
    assert _get(bb, "preempted", None) is True
    print("PASS test_main_tree_preempt_integration")


def test_main_tree_no_preempt_full_run():
    # Guard present but no request: the whole cycle still completes and the
    # garment is sorted, exactly like the unguarded tree.
    root = _run_main(preempt_at_running=False)
    assert root.status == SUCCESS, root.status
    bb = _bb()
    # SortToBin ran and overwrote the sentinel with a real owner.
    assert _get(bb, "sorted_owner", None) != "SENTINEL-not-sorted"
    assert _get(bb, "preempted", None) is False
    print("PASS test_main_tree_no_preempt_full_run")
