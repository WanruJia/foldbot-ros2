"""FoldBot main behavior tree (M0 skeleton, py_trees).

Mirrors the simulation state machine:
  picking → detecting → fold (per step) → placing → done

M0: all action nodes are stubs that log and succeed; perception is mocked.
Real robot: replace stubs with ROS 2 action clients (MoveIt2, gripper, etc.).
"""
import py_trees
from bt.pick_subtree import create_pick_subtree
from bt.perceive_subtree import create_perceive_subtree


class FoldGarment(py_trees.behaviour.Behaviour):
    """Execute each fold step in the plan (real FoldPlan from M4)."""

    def __init__(self, name="FoldGarment"):
        super().__init__(name)
        self._done = 0

    def initialise(self):
        self._done = 0

    def update(self):
        bb = py_trees.blackboard.Client(name="fold")
        bb.register_key(key="fold_plan", access=py_trees.common.Access.READ)
        plan = getattr(bb, "fold_plan", None)
        steps = plan.folds if plan else []
        if self._done < len(steps):
            s = steps[self._done]
            self.logger.info(f"  [fold] {s.label} ({s.status}) "
                             f"[{self._done + 1}/{len(steps)}] "
                             f"grab={s.grab_arm} press={s.press_arm}")
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


def create_main_tree(succeed_on_attempt=1, kind="random", owner="random"):
    pick, _ = create_pick_subtree(succeed_on_attempt=succeed_on_attempt)
    perceive = create_perceive_subtree(kind=kind, owner=owner)
    root = py_trees.composites.Sequence(name="FoldBotMain", memory=True)
    root.add_children([
        pick,
        perceive,
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
