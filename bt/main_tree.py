"""FoldBot main behavior tree (M0 skeleton, py_trees).

Mirrors the simulation state machine:
  picking → detecting → fold (per step) → placing → done

M0: all action nodes are stubs that log and succeed; perception is mocked.
Real robot: replace stubs with ROS 2 action clients (MoveIt2, gripper, etc.).
"""
import py_trees
from perception.mock_perception import mock_perceive


class PickFromBasket(py_trees.behaviour.Behaviour):
    """Take one garment from the laundry basket to the fold zone."""

    def __init__(self, name="PickFromBasket"):
        super().__init__(name)
        self._steps = ["move_to_basket", "descend", "close_gripper",
                       "lift", "move_to_fold_zone", "release", "retract"]
        self._i = 0

    def initialise(self):
        self._i = 0
        self.logger.info("PickFromBasket: reaching to basket...")

    def update(self):
        if self._i < len(self._steps):
            self.logger.info(f"  [pick] {self._steps[self._i]}")
            self._i += 1
            return py_trees.common.Status.RUNNING
        self.blackboard = py_trees.blackboard.Client(name="pick")
        self.blackboard.register_key(key="garment_ready", access=py_trees.common.Access.WRITE)
        self.blackboard.garment_ready = True
        return py_trees.common.Status.SUCCESS


class PerceiveAndPlan(py_trees.behaviour.Behaviour):
    """Run perception pipeline and fold planning (mocked in M0)."""

    def __init__(self, name="PerceiveAndPlan"):
        super().__init__(name)

    def update(self):
        self.logger.info("PerceiveAndPlan: capturing RGB-D (mock)...")
        result = mock_perceive(kind="random", owner="random")
        bb = py_trees.blackboard.Client(name="perceive")
        bb.register_key(key="perception", access=py_trees.common.Access.WRITE)
        bb.perception = result
        self.logger.info(
            f"  detected: {result.kind} / {result.owner} "
            f"({result.metric_name}={result.metric:.3f})"
        )
        # M0: fake a 2-step fold plan; real planner ports planner.js
        bb.register_key(key="fold_plan", access=py_trees.common.Access.WRITE)
        bb.fold_plan = {"steps": ["fold_1", "fold_2"], "kind": result.kind}
        return py_trees.common.Status.SUCCESS


class FoldGarment(py_trees.behaviour.Behaviour):
    """Execute each fold step in the plan."""

    def __init__(self, name="FoldGarment"):
        super().__init__(name)
        self._done = 0

    def initialise(self):
        self._done = 0

    def update(self):
        bb = py_trees.blackboard.Client(name="fold")
        bb.register_key(key="fold_plan", access=py_trees.common.Access.READ)
        steps = getattr(bb, "fold_plan", {"steps": []})["steps"]
        if self._done < len(steps):
            self.logger.info(f"  [fold] executing {steps[self._done]} "
                             f"({self._done + 1}/{len(steps)})")
            self._done += 1
            return py_trees.common.Status.RUNNING
        self.logger.info("FoldGarment: all steps done")
        return py_trees.common.Status.SUCCESS


class SortToBin(py_trees.behaviour.Behaviour):
    """Pick the folded garment and stack it in the owner's bin."""

    def __init__(self, name="SortToBin"):
        super().__init__(name)

    def update(self):
        bb = py_trees.blackboard.Client(name="sort")
        bb.register_key(key="perception", access=py_trees.common.Access.READ)
        owner = getattr(bb, "perception", None)
        owner = owner.owner if owner else "unknown"
        self.logger.info(f"SortToBin: placing into '{owner}' bin, stacking...")
        bb.register_key(key="sorted_owner", access=py_trees.common.Access.WRITE)
        bb.sorted_owner = owner
        return py_trees.common.Status.SUCCESS


def create_main_tree():
    root = py_trees.composites.Sequence(name="FoldBotMain", memory=True)
    root.add_children([
        PickFromBasket(),
        PerceiveAndPlan(),
        FoldGarment(),
        SortToBin(),
    ])
    return root


def run_once(verbose=True):
    root = create_main_tree()
    tree = py_trees.trees.BehaviourTree(root)
    if verbose:
        print(py_trees.display.ascii_tree(root))
    tree.setup(timeout=5)
    while True:
        tree.tick()
        if root.status != py_trees.common.Status.RUNNING:
            break
    print(f"\nFinal status: {root.status}")
    bb = py_trees.blackboard.Client(name="report")
    bb.register_key(key="sorted_owner", access=py_trees.common.Access.READ)
    print(f"Sorted into: {getattr(bb, 'sorted_owner', '?')} bin")
    return root.status


if __name__ == "__main__":
    run_once()
