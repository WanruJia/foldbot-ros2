"""PerceiveAndPlan subtree (M4).

Expands the M0 stub into the real perception → planning chain:

  PerceiveAndPlan (Sequence, memory=True)
  ├── CaptureImage      (mock RGB-D frame)
  ├── ClassifyGarment   (shirt | pants — mocked in M4)
  ├── DetectKeypoints   (mock keypoints via perception.mock_perception)
  ├── ClassifyOwner     (REAL planning.fold_planner.classify_owner)
  └── PlanFolds         (REAL planning.fold_planner.plan_folds/plan_pants_folds)

M4 wires the M2 planner into the tree: the FoldPlan on the blackboard is now
a real plan (3 folds for shirts, tri/bi/none for pants), not a fake 2-step.
Real robot: replace CaptureImage/ClassifyGarment/DetectKeypoints with the
learned vision pipeline; ClassifyOwner/PlanFolds stay as-is.
"""
import random
import py_trees
from perception.mock_perception import mock_perceive
from planning.fold_planner import (
    classify_owner, detect_pants_length, pants_fold_mode,
    plan_folds, plan_pants_folds,
)
from planning.board import plan_board_folds


def _bb_write():
    bb = py_trees.blackboard.Client(name="perceive")
    bb.register_key(key="frame_id", access=py_trees.common.Access.WRITE)
    bb.register_key(key="garment_kind", access=py_trees.common.Access.WRITE)
    bb.register_key(key="keypoints", access=py_trees.common.Access.WRITE)
    bb.register_key(key="perception", access=py_trees.common.Access.WRITE)
    bb.register_key(key="fold_plan", access=py_trees.common.Access.WRITE)
    bb.register_key(key="board_plan", access=py_trees.common.Access.WRITE)
    return bb


class CaptureImage(py_trees.behaviour.Behaviour):
    """Trigger the overhead RGB-D camera (mocked)."""

    def __init__(self, name="CaptureImage"):
        super().__init__(name)

    def update(self):
        bb = _bb_write()
        bb.frame_id = f"frame_{random.randint(1000, 9999)}"
        self.logger.info(f"[CaptureImage] captured {bb.frame_id} (mock RGB-D)")
        return py_trees.common.Status.SUCCESS


class ClassifyGarment(py_trees.behaviour.Behaviour):
    """Classify garment kind: shirt | pants (mocked in M4)."""

    def __init__(self, kind="random", name="ClassifyGarment"):
        super().__init__(name)
        self._kind = kind

    def update(self):
        kind = self._kind
        if kind == "random":
            kind = random.choice(["shirt", "pants"])
        bb = _bb_write()
        bb.garment_kind = kind
        self.logger.info(f"[ClassifyGarment] kind={kind}")
        return py_trees.common.Status.SUCCESS


def _kp_to_dict(kp):
    """Convert Keypoints dataclass to the plain dicts the planner expects."""
    if hasattr(kp, "sleeve_l"):  # shirt
        d = lambda p: {"x": p.x, "y": p.y, "z": p.z}
        return {
            "sleeve_l": d(kp.sleeve_l), "sleeve_r": d(kp.sleeve_r),
            "shoulder_l": d(kp.shoulder_l), "shoulder_r": d(kp.shoulder_r),
            "hem_l": d(kp.hem_l), "hem_r": d(kp.hem_r),
            "a": d(kp.a), "b": d(kp.b), "c": d(kp.c),
        }
    d = lambda p: {"x": p.x, "y": p.y, "z": p.z}
    return {
        "waist_l": d(kp.waist_l), "waist_r": d(kp.waist_r),
        "crotch": d(kp.crotch),
        "cuff_l": d(kp.cuff_l), "cuff_r": d(kp.cuff_r),
    }


class DetectKeypoints(py_trees.behaviour.Behaviour):
    """Detect garment keypoints (mocked in M4 via mock_perceive)."""

    def __init__(self, owner="random", name="DetectKeypoints"):
        super().__init__(name)
        self._owner = owner

    def update(self):
        bb = _bb_write()
        kind = bb.garment_kind
        owner = self._owner
        if owner == "random":
            owner = random.choice(["dad", "mom", "daughter", "son"])
        result = mock_perceive(kind=kind, owner=owner)
        kp = result.keypoints_shirt if kind == "shirt" else result.keypoints_pants
        bb.keypoints = _kp_to_dict(kp)
        bb.perception = result  # keep full mock result for SortToBin
        n = len(bb.keypoints)
        self.logger.info(f"[DetectKeypoints] {n} keypoints for {kind} (mock)")
        return py_trees.common.Status.SUCCESS


class ClassifyOwnerNode(py_trees.behaviour.Behaviour):
    """Classify owner with the REAL planner (not mocked)."""

    def __init__(self, name="ClassifyOwner"):
        super().__init__(name)

    def update(self):
        bb = _bb_write()
        kind, kp = bb.garment_kind, bb.keypoints
        owner, metric, metric_name = classify_owner(kind, kp)
        # overwrite the mock owner with the real classifier output
        bb.perception.owner = owner
        bb.perception.metric = metric
        bb.perception.metric_name = metric_name
        self.logger.info(
            f"[ClassifyOwner] {metric_name}={metric:.3f} → owner={owner} (real)")
        return py_trees.common.Status.SUCCESS


class PlanFoldsNode(py_trees.behaviour.Behaviour):
    """Build the fold plan with the REAL planner (not mocked)."""

    def __init__(self, name="PlanFolds"):
        super().__init__(name)

    def update(self):
        bb = _bb_write()
        kind, kp = bb.garment_kind, bb.keypoints
        owner = bb.perception.owner
        if kind == "shirt":
            plan = plan_folds(kp)
            # Board plan: detect sleeve length from keypoints in real system;
            # mock uses 'short' here, real vision provides it.
            bplan = plan_board_folds("shirt", owner, sleeve="short")
        else:
            length = detect_pants_length(kp)
            mode = pants_fold_mode(owner, length)
            plan = plan_pants_folds(kp, mode)
            self.logger.info(f"[PlanFolds] pants length={length} mode={mode}")
            bplan = plan_board_folds("pants", owner, pants_mode=mode)
        bb.fold_plan = plan
        bb.board_plan = bplan
        self.logger.info(
            f"[PlanFolds] real plan: {len(plan.folds)} folds "
            f"({', '.join(f.label for f in plan.folds)})")
        self.logger.info(
            f"[PlanFolds] board plan: slot={bplan['slot']} "
            f"panels={bplan['panels']}")
        return py_trees.common.Status.SUCCESS


def create_perceive_subtree(kind="random", owner="random"):
    """Build the PerceiveAndPlan subtree."""
    root = py_trees.composites.Sequence(name="PerceiveAndPlan", memory=True)
    root.add_children([
        CaptureImage(),
        ClassifyGarment(kind=kind),
        DetectKeypoints(owner=owner),
        ClassifyOwnerNode(),
        PlanFoldsNode(),
    ])
    return root
