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
DetectKeypoints calls yolo_perceive(frame), garment_yaw_in_bbox() for the
garment's rotation inside the bbox, then bbox_to_placement_kp(det,
yaw_deg=...) and the check_placement() result lands on the blackboard as
"placement";
ClassifyOwnerNode keeps using classify_owner(). Mock stays the default
for tests and hardware-less runs.
garment_torso_width_in_bbox() (2026-10-14) measures a sleeve-insensitive
torso width on the garment contour for the owner classifier, replacing
the bbox-width fallback whenever the crop segments honestly.

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


def _numpy():
    """Lazy numpy import (keeps this module import-light)."""
    try:
        import numpy as np
    except ImportError as e:
        raise ImportError(
            "this function needs numpy; run it where numpy is installed."
        ) from e
    return np


def _otsu_threshold(values):
    """Otsu threshold for a 1-D array of non-negative values (numpy only)."""
    np = _numpy()
    vals = np.asarray(values, dtype=np.float64).ravel()
    if vals.size == 0:
        raise ValueError("otsu: empty values")
    vmin, vmax = float(vals.min()), float(vals.max())
    if vmax <= vmin:
        return vmax
    hist, edges = np.histogram(vals, bins=64, range=(vmin, vmax))
    centers = (edges[:-1] + edges[1:]) / 2.0
    total = hist.sum()
    w = np.cumsum(hist) / total
    mu = np.cumsum(hist * centers) / total
    mu_t = mu[-1]
    denom = w * (1.0 - w)
    with np.errstate(divide="ignore", invalid="ignore"):
        sigma_b2 = np.where(denom > 0, (mu_t * w - mu) ** 2 / denom, 0.0)
    return float(centers[int(np.argmax(sigma_b2))])


def _segment_crop(image, bbox, pad, min_foreground):
    """Shared garment/background segmentation for the bbox contour helpers.

    Samples the padded crop's border as background, thresholds the
    color-distance map with Otsu, and returns the foreground mask.

    Returns (fg, cx1, cy1): fg is a bool array over the padded crop,
    (cx1, cy1) the crop origin in full-image pixels. Returns None when
    the crop cannot be segmented honestly (uniform color, degenerate/tiny
    bbox, too few foreground pixels) — callers must fall back, never
    invent a measurement.

    Raises:
        ImportError: numpy (or Pillow, for a path) not installed.
        OSError / ValueError: unreadable image or malformed bbox.
    """
    np = _numpy()
    if isinstance(image, np.ndarray):
        arr = image
    else:
        try:
            from PIL import Image
        except ImportError as e:
            raise ImportError(
                "contour helpers need a numpy array, or Pillow to read "
                "an image path.") from e
        arr = np.asarray(Image.open(image).convert("RGB"))
    if arr.ndim == 3:
        arr = (arr[..., 0] * 0.299 + arr[..., 1] * 0.587
               + arr[..., 2] * 0.114)  # luma
    arr = np.asarray(arr, dtype=np.float64)
    h, w = arr.shape[:2]
    x1, y1, x2, y2 = (float(v) for v in bbox)
    if not (x2 > x1 and y2 > y1):
        raise ValueError(f"degenerate bbox: {bbox!r}")
    cx1, cy1 = max(0, int(x1) - pad), max(0, int(y1) - pad)
    cx2, cy2 = min(w, int(x2) + pad), min(h, int(y2) + pad)
    if cx2 - cx1 < 8 or cy2 - cy1 < 8:
        return None  # too tiny to segment honestly
    crop = arr[cy1:cy2, cx1:cx2]
    # Background = median color of the crop border (garment is centered).
    border = np.concatenate([crop[0, :], crop[-1, :],
                            crop[:, 0], crop[:, -1]])
    bg = float(np.median(border))
    dist = np.abs(crop - bg)
    thr = _otsu_threshold(dist)
    fg = dist > thr
    if int(fg.sum()) < min_foreground:
        return None  # garment indistinguishable from background
    return fg, cx1, cy1


def _pca_long_axis(fg):
    """Long-axis angle of a bool foreground mask (crop coordinates).

    2x2 PCA via closed form; the long axis is the largest-variance axis.
    Returns (angle_deg, ux, uy): angle in [0, 180), plus the unit vector.
    Returns None when the blob is near-square (long axis unstable) or
    empty — the same honesty gate garment_yaw_in_bbox() uses.
    """
    np = _numpy()
    ys, xs = np.nonzero(fg)
    n = xs.size
    if n == 0:
        return None
    xs = xs.astype(np.float64)
    ys = ys.astype(np.float64)
    x0, y0 = xs.mean(), ys.mean()
    xx = ((xs - x0) ** 2).sum()
    yy = ((ys - y0) ** 2).sum()
    xy = ((xs - x0) * (ys - y0)).sum()
    # 2x2 PCA via closed form; long axis = largest eigenvalue.
    trace, det = xx + yy, xx * yy - xy * xy
    disc = max(trace * trace / 4.0 - det, 0.0) ** 0.5
    l1, l2 = trace / 2.0 + disc, trace / 2.0 - disc
    if l1 + l2 <= 0:
        return None
    if (l1 - l2) / (l1 + l2) < 0.1:
        return None  # near-square blob: long axis is unstable
    vx, vy = xy, l1 - xx  # eigenvector for l1 of [[xx,xy],[xy,yy]]
    if vx == 0 and vy == 0:
        vx, vy = 1.0, 0.0
    norm = (vx * vx + vy * vy) ** 0.5
    angle = (np.degrees(np.arctan2(vy, vx)) + 180.0) % 180.0
    return angle, vx / norm, vy / norm


def garment_yaw_in_bbox(image, bbox, pad=8, min_foreground=20):
    """Estimate the garment's yaw from the image region inside its bbox.

    Segments the garment from the board background by sampling the crop
    border as background, thresholding the color-distance map with Otsu,
    then taking the foreground pixels' principal axis (PCA plays the role
    of minAreaRect's long axis here; numpy-only, no cv2 needed).

    image: numpy array (H,W) or (H,W,3/4), or a file path (needs Pillow).
    bbox: (x1, y1, x2, y2) pixels, the YOLO detection.

    Returns yaw_deg in [-90, 90): the garment's rigid rotation relative to
    upright (shoulders/waist horizontal), matching check_placement()'s yaw
    convention (board x = image x, board z = image y). Assumes the garment
    is taller than it is wide (shirt torso / pants length); the width axis
    follows by symmetry.

    Returns None when the crop cannot be segmented honestly: uniform color,
    degenerate/tiny bbox, too few foreground pixels, or a near-square blob
    whose long axis is unstable. Callers must fall back to yaw=0 rather
    than invent a rotation.

    Raises:
        ImportError: numpy (or Pillow, for a path) not installed.
        OSError / ValueError: unreadable image or malformed bbox.
    """
    seg = _segment_crop(image, bbox, pad, min_foreground)
    if seg is None:
        return None
    fg, _, _ = seg
    axis = _pca_long_axis(fg)
    if axis is None:
        return None
    long_axis_deg = axis[0]
    # Upright garment: long axis vertical (90 deg in image coords);
    # yaw is the rigid rotation away from upright.
    yaw = long_axis_deg - 90.0
    return float(((yaw + 90.0) % 180.0) - 90.0)


def garment_torso_width_in_bbox(image, bbox, band=(0.30, 0.70), pad=8,
                                min_foreground=20, min_band_rows=5):
    """Sleeve-insensitive torso width of a shirt inside its YOLO bbox.

    Segments the garment the same honest way as garment_yaw_in_bbox()
    (border-sampled background + Otsu), rotates the mask so the garment's
    long axis is vertical (PCA, numpy-only), then measures the foreground
    run length along x for each row in the mid-torso band (rows
    band[0]..band[1] of the crop height) and returns the LOWER-QUARTILE
    (0.25) row width in pixels.

    Why this exists: the YOLO bbox includes sleeves, so the bbox width
    systematically overestimates the shoulder width that
    planning.fold_planner.classify_owner()'s thresholds were calibrated on
    (2026-10-05, real tape measurements). The mid-torso band excludes the
    shoulder/sleeve flare at the top and hem curl at the bottom, and the
    0.25-quantile (instead of the median) keeps sleeve flare that reaches
    into the lower part of the band from lifting the reading: on a clean
    torso the row widths are nearly constant so the quartile equals the
    median, but sleeve rows that run wide only shift it once they cover
    more than three quarters of the band — no invented rescale factor.

    Returns None when nothing honest can be measured: segmentation
    failure (same conditions as garment_yaw_in_bbox), an unstable long
    axis (near-square blob), or fewer than min_band_rows band rows with
    foreground. Callers must fall back to the bbox width and keep the
    owner label provisional — never invent a width.

    Raises:
        ImportError: numpy (or Pillow, for a path) not installed.
        OSError / ValueError: unreadable image or malformed bbox.

    Honest limits:
    - Assumes the garment is placed shoulder-up so the band's top end is
      below the shoulder line (PlaceOnBoard places it so). The band is
      measured from the foreground's top along the garment's long axis
      (the PCA vector's y component is always non-negative in image
      coordinates, so for a near-upright garment "top" is the shoulders).
      For a garment lying far off upright, which end is the shoulders is
      ambiguous (same [-90, 90) ambiguity as garment_yaw_in_bbox).
    - Lower-quartile over the band is robust to sleeve stubs poking into
      the edge of a few rows AND to sleeve flare reaching well into the
      band, but sleeves covering more than ~3/4 of the band rows (very
      long sleeves on a short torso) still read wide — the AMBIGUOUS
      margin warning in ClassifyOwnerNode stays the real guard there.
    - The quartile spans holes (neckline): rows where the neckline splits
      the run are mostly above the band, but keep band below the neckline
      on garments with a deep collar.
    """
    # Lower quartile (not median): sleeve rows run WIDE, so a statistic
    # below the median ignores sleeve flare that intrudes into the band
    # while matching the median on a clean torso (constant row widths).
    TORSO_WIDTH_QUANTILE = 0.25
    np = _numpy()
    seg = _segment_crop(image, bbox, pad, min_foreground)
    if seg is None:
        return None
    fg, _, _ = seg
    axis = _pca_long_axis(fg)
    if axis is None:
        return None
    angle_deg = axis[0]
    # Rotate foreground coordinates so the long axis is vertical. Working
    # on coordinates (not a rotated mask) means nothing is clipped.
    th = np.radians(90.0 - angle_deg)
    c, s = np.cos(th), np.sin(th)
    ys, xs = np.nonzero(fg)
    xs = xs.astype(np.float64)
    ys = ys.astype(np.float64)
    dx, dy = xs - xs.mean(), ys - ys.mean()
    xu = dx * c - dy * s  # short-axis coordinate (width direction)
    yu = dx * s + dy * c  # long-axis coordinate ("height" direction)
    ymin, ymax = float(yu.min()), float(yu.max())
    if ymax <= ymin:
        return None
    blo, bhi = ymin + band[0] * (ymax - ymin), ymin + band[1] * (ymax - ymin)
    in_band = (yu >= blo) & (yu <= bhi)
    if not bool(in_band.any()):
        return None
    rows = np.floor(yu[in_band]).astype(np.intp)
    xw = xu[in_band]
    widths = []
    for r in np.unique(rows):
        sel = xw[rows == r]
        if sel.size >= 2:
            widths.append(float(sel.max() - sel.min() + 1))
    if len(widths) < min_band_rows:
        return None
    return float(np.quantile(widths, TORSO_WIDTH_QUANTILE))


def _rotate_about_center(corners, angle_deg):
    """Rotate (x, y) points about their centroid by angle_deg.

    Same (x, y-down) convention as check_placement()'s yaw, so a rotated
    shoulder/waist line reports exactly angle_deg there.
    """
    import math
    th = math.radians(angle_deg)
    c, s = math.cos(th), math.sin(th)
    cx = sum(p[0] for p in corners) / len(corners)
    cy = sum(p[1] for p in corners) / len(corners)
    out = []
    for x, y in corners:
        dx, dy = x - cx, y - cy
        out.append((cx + dx * c - dy * s, cy + dx * s + dy * c))
    return out


def bbox_to_placement_kp(det, kind, px_per_m=None, yaw_deg=None):
    """Derive the keypoints check_placement() needs from a detection bbox.

    check_placement() only needs garment center + yaw, computed from 4
    corner-ish points (shoulders+hems for shirts, waist+cuffs for pants).
    We approximate them from the bbox corners:

        shirt: shoulder_l=(x1,y1) shoulder_r=(x2,y1)
               hem_l=(x1,y2)      hem_r=(x2,y2)
        pants: waist_l=(x1,y1)   waist_r=(x2,y1)
               cuff_l=(x1,y2)    cuff_r=(x2,y2)

    yaw_deg: optional garment yaw from garment_yaw_in_bbox() (degrees,
        check_placement() convention). When given, the 4 corners are
        rotated about the bbox center by yaw_deg, so check_placement()'s
        keypoint-based yaw computation observes the real rotation.
        None (default) keeps the old behavior: yaw 0 by construction.

    Returns {name: (x, y, z)} tuples matching check_placement()'s contract.

    Known limitations (documented, not hidden):
    - Units are PIXELS unless px_per_m is given. check_placement()'s
      tolerances are in meters, so pass px_per_m from camera calibration
      (or the known board size in frame) before comparing against them.
    - The 4 points are the (possibly rotated) bbox rectangle, not measured
      garment landmarks. Fine for board folding (center + yaw only);
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
    if yaw_deg is not None:
        yaw_deg = float(yaw_deg)  # TypeError/ValueError on garbage: loud
        corners = _rotate_about_center(corners, yaw_deg)
    kp = {}
    for name, (ix, iy) in zip(names, corners):
        if px_per_m:
            ix, iy = ix / px_per_m, iy / px_per_m
        kp[name] = (ix, 0.0, iy)
    return kp
