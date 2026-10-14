"""PerceiveAndPlan subtree (M4; M6 YOLO wiring).

Expands the M0 stub into the real perception → planning chain:

  PerceiveAndPlan (Sequence, memory=True)
  ├── CaptureImage      (mock RGB-D frame; yolo mode: real frame path)
  ├── ClassifyGarment   (shirt | pants — mocked in M4; overridden by the
  │                       top YOLO detection in yolo mode)
  ├── DetectKeypoints   (mock keypoints via perception.mock_perception in
  │                       mock mode; yolo_perceive + bbox_to_placement_kp in
  │                       yolo mode, with check_placement() on the blackboard)
  ├── ClassifyOwner     (REAL planning.fold_planner.classify_owner)
  └── PlanFolds         (REAL planning.fold_planner.plan_folds/plan_pants_folds
                         + planning.board.plan_board_folds)

M4 wires the M2 planner into the tree: the FoldPlan on the blackboard is now
a real plan (3 folds for shirts, tri/bi/none for pants), not a fake 2-step.
M6 wires the trained YOLOv8n detector behind perception="yolo":
DetectKeypoints calls yolo_perceive(frame), garment_yaw_in_bbox() for the
garment's rotation inside the bbox, then bbox_to_placement_kp(det,
yaw_deg=...), and the check_placement() result lands on the blackboard
as "placement". For pants, perception.pants_shape.analyze_pants() runs
contour-based leg-split + waist-edge analysis on the bbox crop and the
arm-ready board-meter targets land as "pants_shape" (legs=None when no
clean inseam gap is visible, so the fold iterator skips the side fold).
The board mainline only needs placement, so PlanFolds always builds the
board plan; the ABC fold plan is skipped whenever the keypoints are the
4-point bbox set (no sleeves / a-b-c fold line / crotch — the bbox cannot
see them; that needs the future learned keypoint detector, not guessing).

Honest limits (not hidden):
- yolo mode requires px_per_m (camera calibration). Without real scale the
  owner-size thresholds and the check_placement() tolerances are in meters
  and pixel widths would misclassify silently — so construction fails
  loudly instead.
- The detector itself is unverified on fresh photos (train/val came from
  the same 5 garment cutouts; see perception/eval_real.py).
"""
import random
import py_trees
from perception.mock_perception import mock_perceive
from perception.yolo_perception import (
    yolo_perceive, bbox_to_placement_kp, garment_yaw_in_bbox,
    garment_torso_width_in_bbox)
from perception.pants_shape import analyze_pants, pants_shape_board
from planning.fold_planner import (
    classify_owner, owner_margin, classify_owner_candidates,
    OWNER_AMBIGUOUS_MARGIN,
    detect_pants_length, pants_fold_mode,
    plan_folds, plan_pants_folds,
)
from planning.board import plan_board_folds, check_placement
from msgs.interfaces import PerceptionResult


def _bb_write():
    bb = py_trees.blackboard.Client(name="perceive")
    bb.register_key(key="frame_id", access=py_trees.common.Access.WRITE)
    bb.register_key(key="frame_path", access=py_trees.common.Access.WRITE)
    bb.register_key(key="garment_kind", access=py_trees.common.Access.WRITE)
    bb.register_key(key="keypoints", access=py_trees.common.Access.WRITE)
    bb.register_key(key="placement", access=py_trees.common.Access.WRITE)
    bb.register_key(key="perception", access=py_trees.common.Access.WRITE)
    bb.register_key(key="fold_plan", access=py_trees.common.Access.WRITE)
    bb.register_key(key="board_plan", access=py_trees.common.Access.WRITE)
    bb.register_key(key="pants_shape", access=py_trees.common.Access.WRITE)
    bb.register_key(key="torso_width_m", access=py_trees.common.Access.WRITE)
    return bb


class CaptureImage(py_trees.behaviour.Behaviour):
    """Trigger the overhead RGB-D camera.

    mock mode: fake frame_id. yolo mode: put the real frame path on the
    blackboard so DetectKeypoints can run yolo_perceive on it.
    """

    def __init__(self, perception="mock", image_path=None, name="CaptureImage"):
        super().__init__(name)
        self._perception = perception
        self._image_path = image_path

    def update(self):
        bb = _bb_write()
        if self._perception == "yolo":
            bb.frame_path = self._image_path
            self.logger.info(f"[CaptureImage] frame: {self._image_path} (yolo)")
        else:
            bb.frame_id = f"frame_{random.randint(1000, 9999)}"
            self.logger.info(
                f"[CaptureImage] captured {bb.frame_id} (mock RGB-D)")
        return py_trees.common.Status.SUCCESS


class ClassifyGarment(py_trees.behaviour.Behaviour):
    """Classify garment kind: shirt | pants (mocked in M4).

    In yolo mode DetectKeypoints overrides this with the detected kind.
    """

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


def _placement_tup_to_dict(kp):
    """(x, y, z) tuples → {'x','y','z'} dicts the planner reads."""
    return {k: {"x": v[0], "y": v[1], "z": v[2]} for k, v in kp.items()}


class DetectKeypoints(py_trees.behaviour.Behaviour):
    """Detect garment keypoints.

    mock mode (default): canned keypoints via perception.mock_perception.
    yolo mode: yolo_perceive(frame) on the real frame path; the top
    detection sets the garment kind, garment_yaw_in_bbox() estimates the
    garment's rotation inside the bbox (numpy PCA; None when the crop
    cannot be segmented, falling back to yaw=0), bbox_to_placement_kp()
    builds the 4 placement points (shoulders+hems / waist+cuffs, rotated
    by the estimated yaw), and the check_placement() result goes on the
    blackboard as "placement". No detections → FAILURE (nothing to fold).
    """

    def __init__(self, owner="random", perception="mock", kind="random",
                 px_per_m=None, model_path=None, conf=0.25,
                 name="DetectKeypoints"):
        super().__init__(name)
        self._owner = owner
        self._perception = perception
        self._kind = kind
        self._px_per_m = px_per_m
        self._model_path = model_path
        self._conf = conf

    def update(self):
        bb = _bb_write()
        bb.pants_shape = None  # yolo pants mode overwrites with analysis
        bb.torso_width_m = None  # yolo shirt mode overwrites when measured
        if self._perception == "yolo":
            return self._update_yolo(bb)
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

    def _update_yolo(self, bb):
        frame = getattr(bb, "frame_path", None)
        if frame is None:
            self.logger.error(
                "[DetectKeypoints] yolo mode but no frame_path on blackboard")
            return py_trees.common.Status.FAILURE
        dets = yolo_perceive(frame, conf=self._conf,
                             model_path=self._model_path)
        if self._kind != "random":  # explicit kind: only accept matching dets
            dets = [d for d in dets if d["kind"] == self._kind]
        if not dets:
            self.logger.error(
                "[DetectKeypoints] yolo: no detections — nothing to fold")
            return py_trees.common.Status.FAILURE
        det = dets[0]  # highest confidence first
        kind = det["kind"]
        bb.garment_kind = kind  # detection overrides the mock classifier
        try:
            yaw = garment_yaw_in_bbox(frame, det["bbox"])
        except (ImportError, OSError, ValueError) as e:
            # Frame unreadable or numpy/Pillow missing: do not invent a
            # rotation; the bbox path degrades to yaw=0 as before.
            self.logger.warning(
                f"[DetectKeypoints] yaw from bbox unavailable ({e}); yaw=0")
            yaw = None
        kp_tup = bbox_to_placement_kp(det, kind, self._px_per_m, yaw_deg=yaw)
        bb.placement = check_placement(kp_tup, kind)
        bb.keypoints = _placement_tup_to_dict(kp_tup)
        bb.perception = PerceptionResult(kind=kind, owner="")
        if kind == "shirt":
            # Sleeve-insensitive torso width for the owner classifier: the
            # bbox width includes sleeves and overestimates true shoulder
            # width. Any failure degrades to the bbox width (provisional),
            # never an invented measurement.
            try:
                tw = garment_torso_width_in_bbox(frame, det["bbox"])
                if tw is not None:
                    bb.torso_width_m = tw / self._px_per_m
                    self.logger.info(
                        "[DetectKeypoints] shirt torso width "
                        f"{bb.torso_width_m:.3f} m (contour, "
                        f"{tw:.0f}px bbox width "
                        f"{det['bbox'][2]-det['bbox'][0]:.0f}px)")
                else:
                    self.logger.warning(
                        "[DetectKeypoints] shirt torso not measurable "
                        "on the contour — owner label from bbox width "
                        "(provisional)")
            except (ImportError, OSError, ValueError) as e:
                self.logger.warning(
                    f"[DetectKeypoints] torso width unavailable ({e}) — "
                    "owner label from bbox width (provisional)")
        if kind == "pants":
            # Contour-based leg split + waist edge for the board pants
            # pipeline (no keypoints, per her decision). Any failure
            # degrades to generic grasps — never an invented split.
            try:
                raw = analyze_pants(frame, bbox=det["bbox"], pad=8)
                if raw["ok"]:
                    bb.pants_shape = pants_shape_board(raw, self._px_per_m)
                    legs = bb.pants_shape["legs"]
                    self.logger.info(
                        "[DetectKeypoints] pants shape: legs="
                        f"{'split' if legs else 'merged (skip side fold)'}, "
                        f"waist={'found' if bb.pants_shape['waist'] else 'missing'} "
                        "[contour]")
                else:
                    self.logger.warning(
                        "[DetectKeypoints] pants crop not segmentable — "
                        "generic grasps")
            except (ImportError, OSError, ValueError) as e:
                self.logger.warning(
                    f"[DetectKeypoints] pants shape unavailable ({e}) — "
                    "generic grasps")
        self.logger.info(
            f"[DetectKeypoints] yolo: {kind} conf={det['conf']:.2f} "
            f"yaw_deg={yaw} placement_ok={bb.placement['ok']}")
        return py_trees.common.Status.SUCCESS


def _owner_measure_keypoints(kind, kp, torso_width_m=None, pants_shape=None):
    """Choose the width measurement classify_owner() sees.

    Contour-measured widths (genuinely measured on this frame) replace the
    bbox width, which overestimates shirt shoulder width (sleeves
    included) and pants waist width (bbox spans leg spread) relative to
    the calibrated thresholds. Returns (measure_kp, provenance), where
    measure_kp carries only the width pair classify_owner() reads.

    The fallbacks are honest, not hidden: when no contour measurement
    exists (segmentation failed, or mock keypoints with no contour data),
    the perceived keypoints are used as-is and provenance says the label
    is provisional.
    """
    import math
    if kind == "shirt" and torso_width_m:
        half = torso_width_m / 2.0
        return ({"shoulder_l": {"x": -half, "z": 0.0},
                 "shoulder_r": {"x": half, "z": 0.0}},
                "contour torso width (sleeve-insensitive)")
    if kind != "shirt" and isinstance(pants_shape, dict):
        waist = pants_shape.get("waist")
        if waist and "x1" in waist and "x2" in waist:
            x1, x2 = waist["x1"], waist["x2"]
            width = math.hypot(x1[0] - x2[0], x1[2] - x2[2])
            if width > 0:
                half = width / 2.0
                return ({"waist_l": {"x": -half, "z": 0.0},
                         "waist_r": {"x": half, "z": 0.0}},
                        "contour waist width (pants_shape)")
    return kp, "bbox width (provisional)"


class ClassifyOwnerNode(py_trees.behaviour.Behaviour):
    """Classify owner with the REAL planner (not mocked).

    classify_owner only needs the width pair (shoulder_l/r or waist_l/r),
    which exists in both mock keypoints and yolo bbox keypoints. In yolo
    mode the raw kp is replaced by a contour measurement when one exists:
    the sleeve-insensitive torso width for shirts (torso_width_m on the
    blackboard) or the contour waist width for pants (pants_shape); the
    provenance is logged so a bbox-width fallback stays visibly
    provisional.

    The winner is logged with its boundary margin; a margin below
    OWNER_AMBIGUOUS_MARGIN (10 mm — e.g. mom vs daughter shirts, 1 cm
    apart) is logged as AMBIGUOUS rather than trusted silently.
    """

    def __init__(self, name="ClassifyOwner"):
        super().__init__(name)

    def update(self):
        bb = _bb_write()
        kind, kp = bb.garment_kind, bb.keypoints
        mkp, provenance = _owner_measure_keypoints(
            kind, kp,
            torso_width_m=getattr(bb, "torso_width_m", None),
            pants_shape=getattr(bb, "pants_shape", None))
        owner, metric, metric_name = classify_owner(kind, mkp)
        margin = owner_margin(kind, metric)
        # overwrite the mock owner with the real classifier output
        bb.perception.owner = owner
        bb.perception.metric = metric
        bb.perception.metric_name = metric_name
        if margin < OWNER_AMBIGUOUS_MARGIN:
            alt = classify_owner_candidates(kind, mkp)[1][0]
            self.logger.warning(
                f"[ClassifyOwner] {metric_name}={metric:.3f} → owner={owner} "
                f"AMBIGUOUS (margin={margin*1000:.1f}mm < "
                f"{OWNER_AMBIGUOUS_MARGIN*1000:.0f}mm; alt={alt}) "
                f"[{provenance}]")
        else:
            self.logger.info(
                f"[ClassifyOwner] {metric_name}={metric:.3f} → owner={owner} "
                f"(margin={margin*1000:.1f}mm) [{provenance}]")
        return py_trees.common.Status.SUCCESS


def _has_full_keypoints(kind, kp):
    """True when kp carries what the ABC planner needs.

    The yolo bbox set only has the 4 placement points; ABC planning needs
    sleeves + the a/b/c fold line (shirts) or the crotch (pants).
    """
    need = {"sleeve_l", "sleeve_r", "a", "b", "c"} if kind == "shirt" \
        else {"crotch"}
    return need.issubset(kp)


class PlanFoldsNode(py_trees.behaviour.Behaviour):
    """Build the fold plan with the REAL planner (not mocked).

    The board plan is always built (board folding only needs placement).
    The ABC plan is built only when the keypoints are the full set —
    bbox-derived keypoints cannot see sleeves, fold lines, or crotch, so
    fold_plan stays None there rather than being invented.
    """

    def __init__(self, name="PlanFolds"):
        super().__init__(name)

    def update(self):
        bb = _bb_write()
        kind, kp = bb.garment_kind, bb.keypoints
        owner = bb.perception.owner
        full = _has_full_keypoints(kind, kp)
        if kind == "shirt":
            # Board plan: detect sleeve length from keypoints in real system;
            # mock uses 'short' here, real vision provides it.
            bplan = plan_board_folds("shirt", owner, sleeve="short")
            plan = plan_folds(kp) if full else None
        else:
            length = detect_pants_length(kp)
            mode = pants_fold_mode(owner, length)
            bplan = plan_board_folds("pants", owner, pants_mode=mode)
            plan = plan_pants_folds(kp, mode) if full else None
            self.logger.info(f"[PlanFolds] pants length={length} mode={mode}")
        if not full:
            self.logger.warning(
                "[PlanFolds] bbox keypoints: ABC fold_plan skipped "
                "(no sleeves/fold-line/crotch — needs keypoint detector)")
        else:
            self.logger.info(
                f"[PlanFolds] real plan: {len(plan.folds)} folds "
                f"({', '.join(f.label for f in plan.folds)})")
        bb.fold_plan = plan
        bb.board_plan = bplan
        self.logger.info(
            f"[PlanFolds] board plan: slot={bplan['slot']} "
            f"panels={bplan['panels']}")
        return py_trees.common.Status.SUCCESS


def create_perceive_subtree(kind="random", owner="random", perception="mock",
                            image_path=None, px_per_m=None, model_path=None,
                            conf=0.25):
    """Build the PerceiveAndPlan subtree.

    perception="mock" (default): canned keypoints; tests and hardware-less
      runs behave exactly as before.
    perception="yolo": run the trained YOLOv8n on image_path. Requires
      px_per_m (camera calibration): owner-size thresholds and
      check_placement() tolerances are in meters, so without real scale
      the pipeline would misclassify silently — construction raises
      ValueError instead.
    """
    if perception not in ("mock", "yolo"):
        raise ValueError(
            f"perception must be 'mock'|'yolo', got {perception!r}")
    if perception == "yolo":
        if image_path is None:
            raise ValueError("yolo mode needs image_path (real camera frame)")
        if px_per_m is None:
            raise ValueError(
                "yolo mode needs px_per_m (camera calibration): owner "
                "thresholds and placement tolerances are in meters")
    root = py_trees.composites.Sequence(name="PerceiveAndPlan", memory=True)
    root.add_children([
        CaptureImage(perception=perception, image_path=image_path),
        ClassifyGarment(kind=kind),
        DetectKeypoints(owner=owner, perception=perception, kind=kind,
                        px_per_m=px_per_m, model_path=model_path, conf=conf),
        ClassifyOwnerNode(),
        PlanFoldsNode(),
    ])
    return root
