"""PickFromBasket subtree (M3).

Expands the M0 stub into individual arm/gripper action nodes with a
3-attempt retry on the grasp sequence:

  PickFromBasket (Sequence, memory=True)
  ├── MoveToBasket
  ├── DescendToGarment
  ├── GraspWithRetry (Retry, 3 attempts)
  │   └── GraspSequence (Sequence)
  │       ├── CloseGripper
  │       ├── LiftSlightly
  │       └── VerifyGrasp   ← may fail → triggers retry
  ├── MoveToFoldZone
  ├── ReleaseGarment
  └── RetractArm

M3: nodes are still mocks (log + succeed after N ticks). Real robot:
replace each MockArmAction with a ROS 2 action client (MoveIt2 /
gripper_command). VerifyGrasp would read a force/torque or vacuum sensor.
"""
import py_trees


class MockArmAction(py_trees.behaviour.Behaviour):
    """Base mock: RUNNING for `ticks` ticks, then SUCCESS."""

    def __init__(self, name, ticks=2):
        super().__init__(name)
        self._ticks = ticks
        self._t = 0

    def initialise(self):
        self._t = 0
        self.logger.info(f"[{self.name}] start")

    def update(self):
        self._t += 1
        if self._t < self._ticks:
            return py_trees.common.Status.RUNNING
        self.logger.info(f"[{self.name}] done")
        return py_trees.common.Status.SUCCESS


class MoveToBasket(MockArmAction):
    """Move arm to pre-grasp pose above the laundry basket."""

    def __init__(self):
        super().__init__("MoveToBasket", ticks=3)


class DescendToGarment(MockArmAction):
    """Lower to the garment pile in the basket."""

    def __init__(self):
        super().__init__("DescendToGarment", ticks=2)


class CloseGripper(MockArmAction):
    """Close the gripper on the garment."""

    def __init__(self):
        super().__init__("CloseGripper", ticks=2)


class LiftSlightly(MockArmAction):
    """Lift a few cm to test the grasp."""

    def __init__(self):
        super().__init__("LiftSlightly", ticks=2)


class VerifyGrasp(py_trees.behaviour.Behaviour):
    """Check grasp success. Fails until `succeed_on_attempt` to exercise retry.

    Real robot: read gripper force / vacuum / finger position sensor.
    """

    def __init__(self, succeed_on_attempt=1):
        super().__init__("VerifyGrasp")
        self._succeed_on = succeed_on_attempt
        self.attempts = 0

    def initialise(self):
        self.attempts += 1

    def update(self):
        if self.attempts < self._succeed_on:
            self.logger.warning(
                f"[VerifyGrasp] grasp failed (attempt {self.attempts}), retrying...")
            return py_trees.common.Status.FAILURE
        self.logger.info(f"[VerifyGrasp] grasp OK (attempt {self.attempts})")
        bb = py_trees.blackboard.Client(name="grasp")
        bb.register_key(key="grasp_attempts", access=py_trees.common.Access.WRITE)
        bb.grasp_attempts = self.attempts
        return py_trees.common.Status.SUCCESS


class MoveToFoldZone(MockArmAction):
    """Carry the garment to the central fold zone."""

    def __init__(self):
        super().__init__("MoveToFoldZone", ticks=3)


class ReleaseGarment(MockArmAction):
    """Open gripper to lay the garment flat."""

    def __init__(self):
        super().__init__("ReleaseGarment", ticks=2)

    def update(self):
        s = super().update()
        if s == py_trees.common.Status.SUCCESS:
            bb = py_trees.blackboard.Client(name="pick_done")
            bb.register_key(key="garment_ready", access=py_trees.common.Access.WRITE)
            bb.garment_ready = True
        return s


class RetractArm(MockArmAction):
    """Retract to home pose, clear of the camera view."""

    def __init__(self):
        super().__init__("RetractArm", ticks=2)


def create_pick_subtree(succeed_on_attempt=1):
    """Build the PickFromBasket subtree.

    succeed_on_attempt: VerifyGrasp succeeds on this attempt (1 = first try).
    Use 2 or 3 in tests to exercise the retry path.
    """
    grasp_seq = py_trees.composites.Sequence(name="GraspSequence", memory=True)
    verify = VerifyGrasp(succeed_on_attempt=succeed_on_attempt)
    grasp_seq.add_children([CloseGripper(), LiftSlightly(), verify])

    # Retry the whole grasp sequence up to 3 times.
    # Sequence memory=True: progresses normally; on FAILURE initialise() resets
    # it so the next retry starts from CloseGripper again.
    grasp_retry = py_trees.decorators.Retry(
        name="GraspWithRetry", child=grasp_seq, num_failures=3)

    pick = py_trees.composites.Sequence(name="PickFromBasket", memory=True)
    pick.add_children([
        MoveToBasket(),
        DescendToGarment(),
        grasp_retry,
        MoveToFoldZone(),
        ReleaseGarment(),
        RetractArm(),
    ])
    return pick, verify
