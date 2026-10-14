"""Re-perceive / replan loop after a preempted fold (item 8, final part).

When PreemptibleSubtree aborts a fold mid-run the garment is left in an
unknown state: half-folded, possibly shifted, maybe half on the board. The
old plan no longer describes reality, so re-running the same fold plan
would be guessing. ReplanOnPreempt closes that gap:

  fold attempt N (guarded by PreemptibleSubtree)
    → SUCCESS: the garment was folded; the cycle continues to SortToBin.
    → FAILURE with "preempted" on the blackboard: the fold was aborted.
      Re-run the PERCEIVE subtree (CaptureImage → ClassifyGarment →
      DetectKeypoints → ClassifyOwner → PlanFolds) to re-observe the
      garment AS IT IS NOW, then re-run the fold on the fresh plan.
      Concretely, PlanFoldsNode rebuilds the board plan from the new
      observation, and yolo pants mode re-analyses the contour: legs that
      got merged by the interrupted attempt now read legs=None, so the
      SideFold is skipped instead of folding air — the replan is driven
      by observation, never by assumption.
    → FAILURE without a preemption: a genuine fold failure. Grasp-level
      retries are already handled by RetryWithLog inside the fold steps;
      this node does NOT retry it — report it honestly.

The loop is bounded: max_replans (default 1) caps how many re-perceive /
re-fold cycles may follow one abort. Exceeding it reports FAILURE with a
WARNING, not an infinite loop. The first fold attempt reuses the
blackboard state from the perceive pass that already ran upstream in the
main tree; perceive factories are only invoked for recovery.

Honest edges:
  - If the re-perceive itself fails (yolo mode: no detections — there may
    be nothing on the board after the abort), the node returns FAILURE:
    there is nothing re-observed to fold.
  - Each fold attempt gets a FRESH PreemptibleSubtree (and a fresh fold
    child): the aborted child's INVALID status never leaks, and
    initialise() on the new wrapper clears the old preemption record so
    a stale preempted=True cannot trigger a phantom second recovery.
  - In yolo mode the perceive subtree re-reads the camera frame: the
    CaptureImage seam re-triggers the camera on the real robot, so the
    recovery loop re-observes live reality, not the pre-abort frame.
"""
import py_trees

from bt.preemption import PreemptibleSubtree

REPERCEIVE_TICK_CAP = 50


def _get(bb, key, default=None):
    # py_trees raises KeyError (not AttributeError) for keys nobody wrote.
    try:
        return getattr(bb, key)
    except (KeyError, AttributeError):
        return default


class ReplanOnPreempt(py_trees.behaviour.Behaviour):
    """Re-perceive and re-fold a garment whose fold was preempted.

    Args:
        name: node name.
        perceive_factory: callable() -> fresh perceive subtree. Run once
            per recovery cycle.
        fold_factory: callable() -> fresh fold subtree. Run once per
            fold attempt (wrapped in a PreemptibleSubtree).
        max_replans: how many re-perceive / re-fold cycles may follow a
            preemption abort before the node gives up honestly (default 1).
        on_park: forwarded to each PreemptibleSubtree so the arms park
            safely on every abort.
    """

    def __init__(self, name, perceive_factory, fold_factory, max_replans=1,
                 on_park=None):
        super().__init__(name)
        self._perceive_factory = perceive_factory
        self._fold_factory = fold_factory
        self._max_replans = max_replans
        self._on_park = on_park
        self._fold = None       # current PreemptibleSubtree
        self._perceive = None   # perceive subtree being re-run, or None
        self._bb = None
        self.folds_started = 0      # observable for tests
        self.reperceives_started = 0

    def setup(self, **kwargs):
        pass  # children are built per attempt and set up at build time

    def initialise(self):
        self._bb = py_trees.blackboard.Client(name="replan_guard")
        self._bb.register_key(key="preempted",
                              access=py_trees.common.Access.READ)
        self._bb.register_key(key="preempted",
                              access=py_trees.common.Access.READ)
        self._perceive = None
        self.folds_started = 0
        self.reperceives_started = 0
        self._start_fold_attempt()
        self.folds_started = 1  # first attempt, from the upstream plan

    def _start_fold_attempt(self):
        self._fold = PreemptibleSubtree(
            name="PreemptibleFold", child=self._fold_factory(),
            on_park=self._on_park)
        self._fold.setup_with_descendants()
        self._fold.initialise()

    def _start_reperceive(self):
        self.reperceives_started += 1
        self._perceive = self._perceive_factory()
        self._perceive.setup_with_descendants()

    def update(self):
        if self._perceive is not None:
            # Recovery pass: re-observe the garment in its post-abort
            # state. Multi-tick behaviours get several ticks (cap keeps a
            # stuck perceive from hanging the cycle).
            for _ in range(REPERCEIVE_TICK_CAP):
                self._perceive.tick_once()
                if self._perceive.status != py_trees.common.Status.RUNNING:
                    break
            st = self._perceive.status
            if st == py_trees.common.Status.RUNNING:
                self.logger.warning(
                    f"[{self.name}] re-perceive still running after "
                    f"{REPERCEIVE_TICK_CAP} ticks — giving up (FAILURE)")
                return py_trees.common.Status.FAILURE
            if st == py_trees.common.Status.FAILURE:
                self.logger.warning(
                    f"[{self.name}] re-perceive FAILED after preemption — "
                    "nothing re-observed to fold (FAILURE)")
                return py_trees.common.Status.FAILURE
            # Re-observed: the fresh plan on the blackboard replaces the
            # stale pre-abort plan. Fold it.
            self.logger.info(
                f"[{self.name}] re-perceived after preemption — re-folding "
                f"(attempt {self.folds_started + 1})")
            self._perceive = None
            self.folds_started += 1
            self._start_fold_attempt()
            return py_trees.common.Status.RUNNING

        self._fold.tick_once()
        st = self._fold.status
        if st == py_trees.common.Status.SUCCESS:
            return py_trees.common.Status.SUCCESS
        if st == py_trees.common.Status.RUNNING:
            return py_trees.common.Status.RUNNING
        # Fold reported FAILURE. Only a preemption abort earns a
        # re-perceive: a genuine fold failure is reported honestly.
        if _get(self._bb, "preempted", False) \
                and self.reperceives_started < self._max_replans:
            self.logger.warning(
                f"[{self.name}] fold preempted — re-perceiving the garment "
                f"before re-folding "
                f"(recovery {self.reperceives_started + 1}/"
                f"{self._max_replans})")
            self._start_reperceive()
            return py_trees.common.Status.RUNNING
        if _get(self._bb, "preempted", False):
            self.logger.warning(
                f"[{self.name}] fold preempted again — "
                f"{self._max_replans} recoveries exhausted (FAILURE)")
        return py_trees.common.Status.FAILURE

    def terminate(self, new_status):
        if self._fold is not None \
                and self._fold.status == py_trees.common.Status.RUNNING:
            self._fold.stop(py_trees.common.Status.INVALID)


def create_replan_on_preempt(perceive_factory, fold_factory, max_replans=1,
                             on_park=None, name="ReplanOnPreempt"):
    """Guard a fold with a preempt→re-perceive→re-fold recovery loop."""
    return ReplanOnPreempt(
        name=name, perceive_factory=perceive_factory,
        fold_factory=fold_factory, max_replans=max_replans, on_park=on_park)
