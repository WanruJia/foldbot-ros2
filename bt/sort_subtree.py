"""SortToBin subtree (M5).

Expands sorting into arm primitives with per-bin stacking:

  SortToBin (Sequence, memory=True)
  ├── GraspFoldedGarment
  ├── MoveToOwnerBin     (reads owner from blackboard)
  ├── StackInBin         (places at stack height = count * layer_h)
  ├── ReleaseGarment
  └── RetractArm

Bin stack counts live on the blackboard (key: bin_counts dict) so repeated
cycles stack higher. M5: mocks. Real robot: MoveToOwnerBin uses TF frames
per bin; StackInBin adds the measured garment thickness.
"""
import py_trees

LAYER_H = 0.035  # stacked garment thickness (m), mirrors the simulation


class MockSortAction(py_trees.behaviour.Behaviour):
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


class GraspFoldedGarment(MockSortAction):
    def __init__(self):
        super().__init__("GraspFoldedGarment", ticks=2,
                         detail="grasp folded garment in fold zone")


class MoveToOwnerBin(MockSortAction):
    def __init__(self):
        super().__init__("MoveToOwnerBin", ticks=3)

    def initialise(self):
        super().initialise()
        bb = py_trees.blackboard.Client(name="sort_nav")
        bb.register_key(key="perception", access=py_trees.common.Access.READ)
        owner = getattr(bb, "perception", None)
        self._owner = owner.owner if owner else "unknown"
        self._detail = f"move to '{self._owner}' bin"


class StackInBin(py_trees.behaviour.Behaviour):
    """Place at stack height; increments the bin's count on the blackboard."""

    def __init__(self, name="StackInBin"):
        super().__init__(name)
        self._t = 0

    def initialise(self):
        self._t = 0

    def update(self):
        self._t += 1
        if self._t < 2:
            return py_trees.common.Status.RUNNING
        bb = py_trees.blackboard.Client(name="sort_stack")
        bb.register_key(key="perception", access=py_trees.common.Access.READ)
        bb.register_key(key="bin_counts", access=py_trees.common.Access.WRITE)
        owner = getattr(bb, "perception", None)
        owner = owner.owner if owner else "unknown"
        try:
            counts = bb.bin_counts
        except KeyError:
            counts = {}
        n = counts.get(owner, 0)
        h = 0.055 + n * LAYER_H
        counts[owner] = n + 1
        bb.bin_counts = counts
        bb.register_key(key="sorted_owner", access=py_trees.common.Access.WRITE)
        bb.sorted_owner = owner
        self.logger.info(
            f"[StackInBin] '{owner}' bin: #{n + 1} at h={h:.3f}m")
        return py_trees.common.Status.SUCCESS


def create_sort_subtree():
    root = py_trees.composites.Sequence(name="SortToBin", memory=True)
    root.add_children([
        GraspFoldedGarment(),
        MoveToOwnerBin(),
        StackInBin(),
        MockSortAction("ReleaseGarment", ticks=1, detail="open gripper"),
        MockSortAction("RetractArm", ticks=2, detail="arm to home"),
    ])
    return root
