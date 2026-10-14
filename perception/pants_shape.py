"""Pants shape analysis via edge/contour — no learned keypoints.

Board-mainline pants need two arm targets before folding starts:

  1. LEG MERGE (side fold): find the two legs and the inseam gap between
     them. The arm grabs the OUTER edge of one leg (no cuff keypoint) and
     folds it over to the mirrored point across the pants midline.
  2. WAIST GRAB (arm length fold): find the waist edge — its left/right
     endpoints — so the arm can grab the top and fold it down.

Wanru's decision (2026-10-06): board-mainline perception uses bbox + kind
+ owner only; keypoint labels were dropped. Pants therefore get
edge/contour analysis, never invented keypoints. (The ABC fallback keeps
its own 5-keypoint pants plan — this module is not used there.)

Method (numpy-only, no cv2, no ultralytics):
  - Segment the garment inside its crop with border-sampled background +
    Otsu on the color-distance map (the same honest approach as
    perception.yolo_perception.garment_yaw_in_bbox).
  - Legs: scan rows from the bottom; rows with exactly two foreground
    runs (gaps < min_gap merged) are the legs. The first row above that
    block is the crotch. When no clean two-leg block exists — e.g. the
    legs are already stacked from a previous side fold, or the legs are
    too short to see — legs is reported as None so the caller SKIPS the
    side fold instead of folding air.
  - Waist: scan down from the top; the first row whose longest run spans
    at least half of the garment's widest row is the waist edge; its
    endpoints are the arm's grab targets.

Coordinates are crop pixels unless converted. image x -> board x,
image y -> board z (the same convention as bbox_to_placement_kp). Meters
need px_per_m; the frame->board origin offset belongs to the arm's camera
calibration — this module reports crop/frame-relative coordinates and
never invents a board origin.

Known limits (documented, not hidden):
  - Assumes the crop is waist-up, as placed by PlaceOnBoard. A garment
    rotated 180 deg would mislabel the cuffs as the waist edge.
    garment_yaw_in_bbox() only resolves yaw in [-90, 90), so this
    ambiguity is real and left to the operator/camera setup.
  - The leg split needs a visible inseam gap; pressed-flat or
    dark-on-dark pants that segment as one blob report legs=None
    (skip the side fold) rather than guessing a split.

This module has zero third-party imports at load time; numpy (and Pillow,
only for file paths) is imported lazily so unit tests run anywhere.
"""


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
    """Otsu threshold for a 1-D array of non-negative values (numpy only).

    Compact copy of the approach in perception.yolo_perception
    (kept local so this module has no cross-module private imports).
    """
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


def _to_luma(image):
    """Image (ndarray or path) -> 2-D float64 luma array."""
    np = _numpy()
    if isinstance(image, np.ndarray):
        arr = image
    else:
        try:
            from PIL import Image
        except ImportError as e:
            raise ImportError(
                "pants_shape needs a numpy array, or Pillow to read an "
                "image path.") from e
        arr = np.asarray(Image.open(image).convert("RGB"))
    if arr.ndim == 3:
        arr = (arr[..., 0] * 0.299 + arr[..., 1] * 0.587
               + arr[..., 2] * 0.114)
    return np.asarray(arr, dtype=np.float64)


def segment_garment(image, min_foreground=20):
    """Segment the garment inside its crop.

    image: numpy array (H,W) or (H,W,3/4), or a file path (needs Pillow).
    The crop is expected to be garment-centered (e.g. a YOLO bbox with a
    small pad) so the crop border samples the background.

    Returns a bool foreground mask, or None when the crop cannot be
    segmented honestly (uniform color, tiny crop, too few foreground
    pixels).
    """
    np = _numpy()
    arr = _to_luma(image)
    h, w = arr.shape[:2]
    if h < 8 or w < 8:
        return None  # too tiny to segment honestly
    border = np.concatenate([arr[0, :], arr[-1, :],
                             arr[:, 0], arr[:, -1]])
    bg = float(np.median(border))
    dist = np.abs(arr - bg)
    thr = _otsu_threshold(dist)
    fg = dist > thr
    if int(fg.sum()) < min_foreground:
        return None  # garment indistinguishable from background
    return fg


def _foreground_runs(row, min_gap=2):
    """(x1, x2) runs of True in a bool row; gaps < min_gap are merged.

    x2 is exclusive (Python-slice style).
    """
    runs = []
    start = None
    for x, v in enumerate(row):
        if v and start is None:
            start = x
        elif not v and start is not None:
            runs.append((start, x))
            start = None
    if start is not None:
        runs.append((start, len(row)))
    if len(runs) < 2:
        return runs
    merged = [runs[0]]
    for x1, x2 in runs[1:]:
        px1, px2 = merged[-1]
        if x1 - px2 < min_gap:
            merged[-1] = (px1, x2)
        else:
            merged.append((x1, x2))
    return merged


def find_leg_split(mask, min_gap=2, min_leg_frac=0.10):
    """Find the two pant legs and the inseam gap between them.

    mask: bool foreground mask of the garment crop (waist-up assumed).

    Returns a dict, or None when no clean two-leg split is visible
    (legs already merged/stacked, or the leg block is too short):
        cuff_row:   bottom-most foreground row (crop px)
        crotch_row: first non-two-run row above the leg block (crop px),
                    None when the block reaches the top of the garment
        leg_cols:   [(x1, x2), (x1, x2)] leg column spans at the
                    representative row (crop px)
        mid_col:    inseam gap center at the representative row (crop px)
        grasp:      (x, y) outer edge of the left leg near the cuffs
        fold_target:(x, y) grasp mirrored across the pants midline
        block_height: rows in the two-leg block (diagnostic)
    """
    np = _numpy()
    mask = np.asarray(mask, dtype=bool)
    h, _w = mask.shape
    rows_with_fg = np.nonzero(mask.any(axis=1))[0]
    if rows_with_fg.size == 0:
        return None
    top, bottom = int(rows_with_fg[0]), int(rows_with_fg[-1])
    garment_h = bottom - top + 1

    # Collect the two-run block from the bottom up.
    block = []  # (row, runs) bottom-up
    r = bottom
    while r >= top:
        runs = _foreground_runs(mask[r], min_gap)
        if len(runs) == 2:
            block.append((r, runs))
            r -= 1
        else:
            break
    min_height = max(6, int(min_leg_frac * garment_h))
    if len(block) < min_height:
        return None  # no reliable two-leg region: skip the side fold
    crotch_row = r if r >= top else None

    n = len(block)
    rep_row, rep_runs = block[n // 2]          # mid-block: the midline
    grab_row, grab_runs = block[int(0.2 * (n - 1))]  # near the cuffs
    (lx1, lx2), (rx1, rx2) = rep_runs
    mid_col = (lx2 + rx1) / 2.0
    grasp_x = grab_runs[0][0]                  # outer edge of the left leg
    return {
        "cuff_row": bottom,
        "crotch_row": crotch_row,
        "leg_cols": [(lx1, lx2), (rx1, rx2)],
        "mid_col": mid_col,
        "grasp": (float(grasp_x), float(grab_row)),
        "fold_target": (float(2.0 * mid_col - grasp_x), float(grab_row)),
        "block_height": n,
    }


def find_waist_edge(mask, top_band_frac=0.15, min_width_frac=0.5, min_gap=2):
    """Find the waist edge: the top wide band of the garment.

    Returns {"row", "x1", "x2", "grab"} (crop px; grab is the waist
    midpoint) or None when no wide top band is found.
    """
    np = _numpy()
    mask = np.asarray(mask, dtype=bool)
    rows_with_fg = np.nonzero(mask.any(axis=1))[0]
    if rows_with_fg.size == 0:
        return None
    top, bottom = int(rows_with_fg[0]), int(rows_with_fg[-1])
    garment_h = bottom - top + 1
    widths = [0] * (bottom + 1)
    for r in range(top, bottom + 1):
        runs = _foreground_runs(mask[r], min_gap)
        if runs:
            widths[r] = max(x2 - x1 for x1, x2 in runs)
    max_w = max(widths)
    if max_w <= 0:
        return None
    band_bottom = top + int(top_band_frac * garment_h)
    for r in range(top, min(band_bottom, bottom) + 1):
        runs = _foreground_runs(mask[r], min_gap)
        if not runs:
            continue
        x1, x2 = max(runs, key=lambda q: q[1] - q[0])
        if x2 - x1 >= min_width_frac * max_w:
            return {"row": r, "x1": x1, "x2": x2,
                    "grab": (float(x1 + x2) / 2.0, float(r))}
    return None


def analyze_pants(image, bbox=None, pad=8, min_gap=2):
    """Full contour analysis of a pants crop.

    image: numpy array or file path (Pillow). bbox: optional
        (x1, y1, x2, y2) frame-pixel box to crop first (e.g. the YOLO
        detection); the crop is padded by `pad` px for background
        sampling.

    Returns:
        {"ok": True, "origin": (x0, y0), "legs": {...}|None,
         "waist": {...}|None}
        origin = crop top-left in frame pixels ((0,0) without bbox).
        legs=None means "no clean two-leg split — skip the side fold".
        waist=None means "no waist edge found — generic waist grab".

    On segmentation failure returns {"ok": False, "origin": ...,
    "legs": None, "waist": None}.
    """
    np = _numpy()
    origin = (0, 0)
    crop = image
    if bbox is not None:
        arr = _to_luma(image)
        h, w = arr.shape[:2]
        x1, y1, x2, y2 = (float(v) for v in bbox)
        if not (x2 > x1 and y2 > y1):
            raise ValueError(f"degenerate bbox: {bbox!r}")
        cx1, cy1 = max(0, int(x1) - pad), max(0, int(y1) - pad)
        cx2, cy2 = min(w, int(x2) + pad), min(h, int(y2) + pad)
        origin = (cx1, cy1)
        crop = arr[cy1:cy2, cx1:cx2]
    mask = segment_garment(crop)
    if mask is None:
        return {"ok": False, "origin": origin,
                "legs": None, "waist": None}
    return {"ok": True, "origin": origin,
            "legs": find_leg_split(mask, min_gap=min_gap),
            "waist": find_waist_edge(mask, min_gap=min_gap)}


def _crop_to_frame(p, origin):
    ox, oy = origin
    return (p[0] + ox, p[1] + oy)


def pants_shape_board(shape, px_per_m):
    """Convert an analyze_pants() result to arm-ready board coordinates.

    px_per_m: camera calibration (pixels per meter). Convention: image x
    -> board x, image y -> board z, following bbox_to_placement_kp (frame
    pixels divided by px_per_m; the frame->board origin offset is the
    arm's camera extrinsic, applied downstream — never invented here).
    Grasp height y is the board surface plus a small clearance (0.005 m).

    Returns {"legs": {"grasp": (x,y,z), "fold_target": (x,y,z)} | None,
             "waist": {"grab": (x,y,z), "x1": (x,y,z), "x2": (x,y,z)} | None}.
    """
    if px_per_m is None or px_per_m <= 0:
        raise ValueError(f"px_per_m must be positive, got {px_per_m!r}")
    origin = shape.get("origin", (0, 0))

    def to_board(p):
        fx, fy = _crop_to_frame(p, origin)
        return (fx / px_per_m, 0.005, fy / px_per_m)

    legs = shape.get("legs")
    waist = shape.get("waist")
    return {
        "legs": ({"grasp": to_board(legs["grasp"]),
                  "fold_target": to_board(legs["fold_target"])}
                 if legs else None),
        "waist": ({"grab": to_board(waist["grab"]),
                   "x1": to_board((waist["x1"], waist["row"])),
                   "x2": to_board((waist["x2"], waist["row"]))}
                  if waist else None),
    }
