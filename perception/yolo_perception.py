"""Real perception via the trained YOLOv8n detector (M5 wiring).

Trained 2026-10-06: data/yolo_runs/foldbot_nano/weights/best.pt (6.2 MB)
- 500 composited images (400 train / 100 val) from 5 real garment photos
- 30/30 epochs, val mAP50 = 0.995 (data/yolo_runs/foldbot_nano/results.csv)
- classes: 0=shirt, 1=pants  (data/yolo/foldbot.yaml)

What the model gives you: bbox + kind + confidence per garment.
What it does NOT give: owner (use planning.fold_planner.classify_owner on
real keypoints), keypoints, or metric scale.

Honest caveat: train and val were composited from the SAME 5 GrabCut
cutouts, so 0.995 is near-duplicate memorization, not real-world
generalization. Before trusting this on hardware, point it at fresh photos
with perception/eval_real.py and look at the zero-detection images first.

Pipeline wiring (done 2026-10-10, M6): bt/perceive_subtree.py
create_perceive_subtree(perception="yolo", image_path=..., px_per_m=...)
wires this in: CaptureImage puts the real frame path on the blackboard,
DetectKeypoints calls yolo_perceive(frame) then bbox_to_placement_kp(det)
and the check_placement() result lands on the blackboard as "placement";
ClassifyOwnerNode keeps using classify_owner(). Mock stays the default
for tests and hardware-less runs.

This module has zero third-party imports at load time; ultralytics is
imported lazily inside yolo_perceive() so unit tests run anywhere.
"""
import os

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DEFAULT_MODEL = os.path.join(
    REPO_ROOT, "data", "yolo_runs", "foldbot_nano", "weights", "best.pt")

CLASSES = {0: "shirt", 1: "pants"}


def _detect(model_path, image_path, conf, imgsz):
    """Run the model. Separated so tests can monkeypatch it."""
    from ultralytics import YOLO  # lazy: keeps this module import-light
    model = YOLO(model_path)
    return model.predict(image_path, conf=conf, imgsz=imgsz, verbose=False)[0]


def yolo_perceive(image_path, conf=0.25, imgsz=416, model_path=None):
    """Detect garments in an image with the trained YOLOv8n model.

    Returns a list of dicts, highest confidence first:
        {"kind": "shirt" | "pants", "conf": float,
         "bbox": (x1, y1, x2, y2)}   # pixels, x1<x2, y1<y2

    Raises:
        FileNotFoundError: image or model file missing.
        ImportError: ultralytics not installed in this environment.
    """
    model_path = model_path or DEFAULT_MODEL
    if not os.path.isfile(image_path):
        raise FileNotFoundError(f"image not found: {image_path}")
    if not os.path.isfile(model_path):
        raise FileNotFoundError(f"model not found: {model_path}")
    try:
        result = _detect(model_path, image_path, conf, imgsz)
    except ImportError as e:
        raise ImportError(
            "ultralytics is not installed in this environment. "
            "Run yolo_perceive() where the training env lives "
            "(pip install ultralytics), or use perception/eval_real.py "
            "there.") from e

    dets = []
    names = result.names or {}
    for b in result.boxes:
        cls_id = int(b.cls)
        kind = CLASSES.get(cls_id, names.get(cls_id))
        if kind not in ("shirt", "pants"):
            continue  # unknown class id: skip rather than guess
        x1, y1, x2, y2 = (float(v) for v in b.xyxy[0])
        dets.append({"kind": kind, "conf": float(b.conf),
                     "bbox": (x1, y1, x2, y2)})
    dets.sort(key=lambda d: d["conf"], reverse=True)
    return dets


def bbox_to_placement_kp(det, kind, px_per_m=None):
    """Derive the keypoints check_placement() needs from a detection bbox.

    check_placement() only needs garment center + yaw, computed from 4
    corner-ish points (shoulders+hems for shirts, waist+cuffs for pants).
    We approximate them from the bbox corners:

        shirt: shoulder_l=(x1,y1) shoulder_r=(x2,y1)
               hem_l=(x1,y2)      hem_r=(x2,y2)
        pants: waist_l=(x1,y1)   waist_r=(x2,y1)
               cuff_l=(x1,y2)    cuff_r=(x2,y2)

    Returns {name: (x, y, z)} tuples matching check_placement()'s contract.

    Known limitations (documented, not hidden):
    - Units are PIXELS unless px_per_m is given. check_placement()'s
      tolerances are in meters, so pass px_per_m from camera calibration
      (or the known board size in frame) before comparing against them.
    - Yaw is 0 by construction: an axis-aligned bbox cannot observe
      garment rotation. Fine for roughly-squared placements on the board;
      do not use this for the ABC fold-line path, which needs real
      keypoints.
    """
    if kind not in ("shirt", "pants"):
        raise ValueError(f"kind must be 'shirt'|'pants', got {kind!r}")
    (x1, y1, x2, y2) = det["bbox"]
    if kind == "shirt":
        names = ("shoulder_l", "shoulder_r", "hem_l", "hem_r")
    else:
        names = ("waist_l", "waist_r", "cuff_l", "cuff_r")
    corners = [(x1, y1), (x2, y1), (x1, y2), (x2, y2)]  # image x->board x, y->board z
    kp = {}
    for name, (ix, iy) in zip(names, corners):
        if px_per_m:
            ix, iy = ix / px_per_m, iy / px_per_m
        kp[name] = (ix, 0.0, iy)
    return kp
