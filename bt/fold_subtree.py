"""FoldGarment subtree (M5).

Expands fold execution into per-step arm primitives. Each FoldStep from the
planner becomes:

  FoldStep:<label> (Sequence, memory=True)
  ├── MoveToGrab   (grab_arm → grab pose)
  ├── CloseGripper
  ├── MoveToPress  (press_arm → press pose)
  ├── ExecuteFold  (arc motion along the crease line)
  ├── ReleaseAll
  └── RetractArms

FoldStepsIterator reads the FoldPlan from the blackboard at initialise() and
builds one such subtree per step, so 3-fold shirts and tri/bi/none pants all
work without hardcoding the count.

M5: still mocks (log + succeed). Real robot: each primitive becomes a
MoveIt2 Cartesian path / gripper action; ExecuteFold streams the fold arc
from planning.fold_math.fold_point_vert.
"""
import py_trees


class MockFoldAction(py_trees.behaviour.Behaviour):
    """Base mock fold primitive: RUNNING for `ticks` ticks, then SUCCESS."""

    def __init__(self, name, ticks=2, detail=""):
        super().__init__(name)
        self._ticks = ticks
        self._t = 0
        self._detail = detail

    def initialise(self):
        self._t = 0

    def update(self):
        self._t += 1
        if self._t < self._ticks:
            return py_trees.common.Status.RUNNING
        if self._detail:
            self.logger.info(f"[{self.name}] {self._detail}")
        return py_trees.common.Status.SUCCESS


def create_fold_step_subtree(step, idx):
    """Build the primitive sequence for one FoldStep."""
    g = step.grab
    p = step.press
    root = py_trees.composites.Sequence(
        name=f"FoldStep:{step.label}", memory=True)
    root.add_children([
        MockFoldAction("MoveToGrab", ticks=2,
                       detail=f"{step.grab_arm} arm → grab ({g.x:.2f},{g.z:.2f})"),
        MockFoldAction("CloseGripper", ticks=1,
                       detail=f"{step.grab_arm} gripper closed"),
        MockFoldAction("MoveToPress", ticks=2,
                       detail=f"{step.press_arm} arm → press ({p.x:.2f},{p.z:.2f})"),
        MockFoldAction("ExecuteFold", ticks=3,
                       detail=f"fold arc: sign={step.fold_sign} h={step.axis_h}"),
        MockFoldAction("ReleaseAll", ticks=1, detail="both grippers open"),
        MockFoldAction("RetractArms", ticks=2, detail="arms to home"),
    ])
    return root


class FoldStepsIterator(py_trees.behaviour.Behaviour):
    """Read the FoldPlan from the blackboard and run each step's subtree."""

    def __init__(self, name="FoldGarment"):
        super().__init__(name)
        self._seq = None
        self._n = 0

    def initialise(self):
        bb = py_trees.blackboard.Client(name="fold_iter")
        bb.register_key(key="fold_plan", access=py_trees.common.Access.READ)
        plan = getattr(bb, "fold_plan", None)
        steps = plan.folds if plan else []
        self._n = len(steps)
        self._seq = py_trees.composites.Sequence(
            name="FoldSteps", memory=True)
        for i, s in enumerate(steps):
            self._seq.add_children([create_fold_step_subtree(s, i)])
        self.logger.info(f"[FoldGarment] executing {self._n} fold steps")
        # setup the dynamically built subtree
        self._seq.setup_with_descendants()

    def update(self):
        if self._n == 0:
            return py_trees.common.Status.SUCCESS
        self._seq.tick_once()
        st = self._seq.status
        if st == py_trees.common.Status.SUCCESS:
            self.logger.info("[FoldGarment] all steps done")
        return st

    def terminate(self, new_status):
        if self._seq:
            self._seq.stop(py_trees.common.Status.INVALID)


def create_fold_subtree():
    return FoldStepsIterator()
