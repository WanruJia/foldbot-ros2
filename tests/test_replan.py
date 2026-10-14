"""Tests for the re-perceive / replan loop (bt/replan.py, item 8 final part)."""
import sys
sys.path.insert(0, ".")

import py_trees

from bt.replan import ReplanOnPreempt, create_replan_on_preempt
from bt.preemption import request_preemption, clear_preemption
from bt.board_actions import create_flip_panel_subtree
from bt.main_tree import create_main_tree

RUNNING = py_trees.common.Status.RUNNING
SUCCESS = py_trees.common.Status.SUCCESS
FAILURE = py_trees.common.Status.FAILURE
INVALID = py_trees.common.Status.INVALID


def _reset_flags():
    clear_preemption()
    bb = py_trees.blackboard.Client(name="replan_reset")
    bb.register_key(key="preempted", access=py_trees.common.Access.WRITE)
    bb.register_key(key="preempt_reason", access=py_trees.common.Access.WRITE)
    bb.preempted = False
    bb.preempt_reason = None


class _Trivial(py_trees.behaviour.Behaviour):
    """One-tick SUCCESS (or FAILURE) behaviour; counts constructions."""

    def __init__(self, name, result, counter):
        super().__init__(name)
        self._result = result
        self._counter = counter
        if counter is not None:
            counter[0] += 1

    def update(self):
        return self._result


class _AbortOnce(py_trees.behaviour.Behaviour):
    """Simulate a preemption abort: write the blackboard record, FAIL."""

    def update(self):
        bb = py_trees.blackboard.Client(name="abort_sim")
        bb.register_key(key="preempted", access=py_trees.common.Access.WRITE)
        bb.register_key(key="preempt_reason",
                        access=py_trees.common.Access.WRITE)
        bb.preempted = True
        bb.preempt_reason = "test abort"
        return FAILURE


def _make(perceive_result=SUCCESS, fold=None, **kw):
    p_count, f_count = [0], [0]

    def _fold_factory():
        f_count[0] += 1
        if callable(fold):
            return fold()
        return _Trivial("F", fold if fold else SUCCESS, None)

    def _perceive_factory():
        p_count[0] += 1
        return _Trivial("P", perceive_result, None)

    node = ReplanOnPreempt(
        name="R",
        perceive_factory=_perceive_factory,
        fold_factory=_fold_factory,
        **kw)
    return node, p_count, f_count


def _tick_until_done(node, cap=200):
    tree = py_trees.trees.BehaviourTree(node)
    tree.setup(timeout=5)
    for _ in range(cap):
        tree.tick()
        if node.status != RUNNING:
            break
    return tree


def test_no_preemption_no_reperceive():
    # No request: the fold runs once on the upstream plan, SUCCESS, and
    # perceive is never re-run (first attempt reuses existing blackboard).
    _reset_flags()
    node, p_count, f_count = _make()
    _tick_until_done(node)
    assert node.status == SUCCESS, node.status
    assert p_count[0] == 0, p_count
    assert f_count[0] == 1, f_count
    assert node.reperceives_started == 0
    print("PASS test_no_preemption_no_reperceive")


def test_genuine_fold_failure_not_retried():
    # FAILURE without a preemption record is a genuine failure: no
    # re-perceive, honest FAILURE straight away.
    _reset_flags()
    node, p_count, f_count = _make(fold=FAILURE)
    _tick_until_done(node)
    assert node.status == FAILURE, node.status
    assert p_count[0] == 0, p_count
    assert f_count[0] == 1, f_count
    print("PASS test_genuine_fold_failure_not_retried")


def test_preemption_triggers_reperceive_then_success():
    # Real preemption of a real fold subtree: the node re-perceives once
    # and re-folds on the fresh plan — SUCCESS.
    _reset_flags()
    p_count = [0]
    node = ReplanOnPreempt(
        name="R",
        perceive_factory=lambda: _Trivial("P", SUCCESS, p_count),
        fold_factory=lambda: create_flip_panel_subtree("left", "adult"))
    tree = py_trees.trees.BehaviourTree(node)
    tree.setup(timeout=5)
    requested = False
    for _ in range(300):
        tree.tick()
        if node.status != RUNNING:
            break
        if not requested and node._fold.status == RUNNING:
            request_preemption("operator stop")
            requested = True
    assert requested, "never saw the fold running"
    assert node.status == SUCCESS, node.status
    assert p_count[0] == 1, p_count
    assert node.folds_started == 2, node.folds_started
    assert node.reperceives_started == 1
    print("PASS test_preemption_triggers_reperceive_then_success")


def test_max_replans_exhausted_gives_up():
    # Two aborts with max_replans=1: re-perceive once, refold once, then
    # FAILURE — the loop is bounded, never infinite.
    _reset_flags()
    p_count = [0]
    node = ReplanOnPreempt(
        name="R", max_replans=1,
        perceive_factory=lambda: _Trivial("P", SUCCESS, p_count),
        fold_factory=lambda: create_flip_panel_subtree("left", "adult"))
    tree = py_trees.trees.BehaviourTree(node)
    tree.setup(timeout=5)
    requested = 0
    for _ in range(400):
        tree.tick()
        if node.status != RUNNING:
            break
        if requested < 2 and node._fold.status == RUNNING:
            request_preemption(f"stop {requested}")
            requested += 1
    assert requested == 2, requested
    assert node.status == FAILURE, node.status
    assert p_count[0] == 1, p_count  # only one recovery allowed
    assert node.folds_started == 2, node.folds_started
    print("PASS test_max_replans_exhausted_gives_up")


def test_reperceive_failure_is_honest():
    # The abort is real, but the re-perceive finds nothing (yolo: no
    # detections after the abort): FAILURE, no phantom refold.
    _reset_flags()
    node, p_count, f_count = _make(
        perceive_result=FAILURE, fold=lambda: _AbortOnce(name="A"))
    _tick_until_done(node)
    assert node.status == FAILURE, node.status
    assert p_count[0] == 1, p_count
    assert f_count[0] == 1, f_count  # fold never rebuilt
    print("PASS test_reperceive_failure_is_honest")


def test_create_factory_defaults():
    n = create_replan_on_preempt(lambda: _Trivial("P", SUCCESS, [0]),
                                 lambda: _Trivial("F", SUCCESS, [0]))
    assert isinstance(n, ReplanOnPreempt)
    assert n._max_replans == 1
    print("PASS test_create_factory_defaults")


def _run_main_recovery(preempt_once):
    _reset_flags()
    root = create_main_tree(kind="shirt", owner="daughter",
                            recovery=True)
    bb = py_trees.blackboard.Client(name="replan_sentinel")
    bb.register_key(key="sorted_owner", access=py_trees.common.Access.WRITE)
    bb.sorted_owner = "SENTINEL-not-sorted"
    tree = py_trees.trees.BehaviourTree(root)
    tree.setup(timeout=5)
    node = root.children[2]
    requested = False
    for _ in range(600):
        tree.tick()
        if root.status != RUNNING:
            break
        if (preempt_once and not requested
                and node._fold is not None
                and node._fold.status == RUNNING):
            request_preemption("operator stop")
            requested = True
    return root, node


def test_main_tree_recovery_wiring():
    root = create_main_tree(recovery=True)
    node = root.children[2]
    assert isinstance(node, ReplanOnPreempt), type(node)
    assert isinstance(node._fold_factory(), py_trees.behaviour.Behaviour)
    print("PASS test_main_tree_recovery_wiring")


def test_main_tree_recovery_integration():
    # Full mock tree: preempt once mid-fold; the recovery loop re-perceives,
    # re-folds, and the cycle still completes — the garment gets sorted.
    root, node = _run_main_recovery(preempt_once=True)
    assert root.status == SUCCESS, root.status
    assert node.reperceives_started == 1, node.reperceives_started
    bb = py_trees.blackboard.Client(name="replan_check")
    bb.register_key(key="sorted_owner", access=py_trees.common.Access.READ)
    try:
        sorted_owner = bb.sorted_owner
    except KeyError:
        sorted_owner = None
    assert sorted_owner != "SENTINEL-not-sorted", sorted_owner
    print("PASS test_main_tree_recovery_integration")


def test_main_tree_recovery_no_preempt():
    # Guard present, no request: cycle completes with zero re-perceives,
    # exactly like the unrecovered tree.
    root, node = _run_main_recovery(preempt_once=False)
    assert root.status == SUCCESS, root.status
    assert node.reperceives_started == 0
    print("PASS test_main_tree_recovery_no_preempt")
