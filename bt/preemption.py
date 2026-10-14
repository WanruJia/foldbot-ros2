"""Task preemption for the fold subtree (item 8, second half).

On the real robot the fold sequence is long (place + panel flips + retracts)
and things change mid-fold: the operator hits stop, or a new garment lands on
the board. py_trees' composite semantics will not abort a running fold child
for you — a Sequence with memory=True keeps ticking the RUNNING child until
it finishes. So a stop request issued mid-fold would be honoured only after
the arm finished folding the wrong garment. (Cf. the preemption behaviour
Dyna's Taku demos: an interrupt must take effect on the next tick.)

PreemptibleSubtree wraps the fold subtree (BoardFoldIterator, or the legacy
ABC FoldStepsIterator) and checks a blackboard flag every tick:

  "preempt_request" — None or a reason string. None = no request.
  Raised by the operator UI / dashboard / a ROS topic callback on the real
  robot. In tests and the mock sim, raise it directly with
  request_preemption(reason).

When the flag is observed while the fold child is RUNNING, the wrapper:
  1. stops the running child (terminate(INVALID) — the retry decorators and
     the iterators underneath already implement terminate());
  2. parks the arms safely via the on_park hook (mock: logs "arms to safe
     park"; real robot: command a safe park pose — the hook is the seam);
  3. clears the request and records "preempted" = True plus
     "preempt_reason" on the blackboard — a preemption is observable,
     never silent;
  4. returns FAILURE so the main Sequence does NOT proceed to SortToBin.
     Sorting an interrupted, half-folded garment into a family bin would be
     a lie the tree must not tell. A bounded re-perceive / replan loop
     after a preemption lives in bt/replan.py (ReplanOnPreempt), wired via
     create_main_tree(recovery=True).

Honesty contract:
  - The wrapper never reports a fold as done when it was aborted.
  - A request that arrives after the child already reached SUCCESS is moot:
    the fold genuinely completed, so the real outcome is reported and the
    stale request is cleared (it must not leak into the next garment).
  - A request before the fold starts (child INVALID): the fold never ran,
    so FAILURE is the honest outcome — the garment was not folded.
  - attempts_used on the RetryWithLog decorators below stays truthful: an
    interrupted RUNNING child is stopped, not counted as a completed attempt.
"""
import py_trees


def request_preemption(reason="operator stop"):
    """Raise a preemption request that PreemptibleSubtree will honour."""
    bb = py_trees.blackboard.Client(name="preempt_requester")
    bb.register_key(key="preempt_request",
                    access=py_trees.common.Access.WRITE)
    bb.preempt_request = reason or "operator stop"


def clear_preemption():
    """Withdraw a pending request (operator stand-down)."""
    bb = py_trees.blackboard.Client(name="preempt_requester")
    bb.register_key(key="preempt_request",
                    access=py_trees.common.Access.WRITE)
    bb.preempt_request = None


class PreemptibleSubtree(py_trees.behaviour.Behaviour):
    """Wrap a long-running subtree so a preemption request aborts it cleanly.

    Args:
        name: node name.
        child: the fold subtree to guard.
        on_park: optional callable() run when arms must park safely after an
            abort. Real robot: command the safe park pose here. Mock default:
            logs. Kept as a hook (not a node) so tests can observe it.
    """

    def __init__(self, name, child, on_park=None):
        super().__init__(name)
        self._child = child
        self._on_park = on_park
        self._bb = None
        self.parked = False  # observable for tests: arms were parked

    def setup(self, **kwargs):
        self._child.setup_with_descendants()

    def initialise(self):
        self._bb = py_trees.blackboard.Client(name="preempt_guard")
        self._bb.register_key(key="preempt_request",
                              access=py_trees.common.Access.WRITE)
        self._bb.register_key(key="preempted",
                              access=py_trees.common.Access.WRITE)
        self._bb.register_key(key="preempt_reason",
                              access=py_trees.common.Access.WRITE)
        # Each fold starts with a clean preemption record; a stale True
        # from a previous garment must not be mistaken for this one.
        self._bb.preempted = False
        self._bb.preempt_reason = None
        self.parked = False

    def _park_arms(self):
        self.parked = True
        if self._on_park is not None:
            self._on_park()
        else:
            self.logger.info(f"[{self.name}] arms to safe park")

    def _record_abort(self, reason):
        self._bb.preempt_request = None
        self._bb.preempted = True
        self._bb.preempt_reason = reason

    def update(self):
        # NOTE: py_trees blackboard __getattr__ raises KeyError (not
        # AttributeError) for a key nobody ever wrote, so getattr() with a
        # default does NOT catch it — read defensively.
        try:
            req = self._bb.preempt_request
        except (KeyError, AttributeError):
            req = None
        child_st = self._child.status
        running = child_st == py_trees.common.Status.RUNNING
        if req and running:
            self._child.stop(py_trees.common.Status.INVALID)
            self._park_arms()
            self._record_abort(req)
            self.logger.warning(
                f"[{self.name}] fold preempted mid-run ({req}) — arms "
                f"parked, fold aborted (FAILURE)")
            return py_trees.common.Status.FAILURE
        if req and child_st == py_trees.common.Status.INVALID:
            # Requested before the fold ever started: nothing ran, so the
            # honest outcome is FAILURE — this garment was not folded.
            self._park_arms()
            self._record_abort(req)
            self.logger.warning(
                f"[{self.name}] preemption before fold start ({req}) — "
                f"fold aborted (FAILURE)")
            return py_trees.common.Status.FAILURE
        if req:
            # Child already terminal (SUCCESS/FAILURE): the fold genuinely
            # finished before the request arrived. Report the real outcome
            # and clear the stale request so it cannot leak into the next
            # garment.
            self.logger.info(
                f"[{self.name}] preemption arrived after fold "
                f"{child_st} ({req}) — reporting real outcome")
            self._bb.preempt_request = None
            return child_st
        if child_st in (py_trees.common.Status.SUCCESS,
                        py_trees.common.Status.FAILURE):
            return child_st  # terminal: do not re-tick a finished child
        self._child.tick_once()
        return self._child.status

    def terminate(self, new_status):
        if self._child.status == py_trees.common.Status.RUNNING:
            self._child.stop(py_trees.common.Status.INVALID)


def create_preemptible(fold_child, name="PreemptibleFold", on_park=None):
    """Guard a fold subtree (or factory producing one) with preemption."""
    child = fold_child() if callable(fold_child) else fold_child
    return PreemptibleSubtree(name=name, child=child, on_park=on_park)
