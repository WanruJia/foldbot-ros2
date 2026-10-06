"""Parametric garment meshes for synthetic data generation.

Uses Wanru's real family measurements (2026-10-05):
  Shirts (shoulder / body width, cm):
    dad 43/50, mom 35/43, daughter 34/36, son 27/33
  Pants (length, cm): daughter 71, son 58
    (adult lengths not yet measured; waist widths from mock_perception)

Each builder returns:
  verts: list of (x, y, z) — y is height above table
  faces: list of (i, j, k) triangle indices
  keypoints: dict name -> (x, y, z) matching perception/msgs keypoint names
  outline: list of (x, z) polygon points for 2D rendering
"""
import math
import random

# Real measurements (meters)
SHIRT_DIMS = {
    # owner: (shoulder_width, body_width, body_length)
    "dad":      (0.43, 0.50, 0.72),
    "mom":      (0.35, 0.43, 0.66),
    "daughter": (0.34, 0.36, 0.58),
    "son":      (0.27, 0.33, 0.52),
}
PANTS_DIMS = {
    # owner: (waist_width, length)
    "dad":      (0.56, 1.00),   # length estimated, not yet measured
    "mom":      (0.48, 0.92),   # length estimated, not yet measured
    "daughter": (0.40, 0.71),
    "son":      (0.32, 0.58),
}

SHIRT_KPS = ["sleeve_l", "sleeve_r", "shoulder_l", "shoulder_r",
             "hem_l", "hem_r", "a", "b", "c"]
PANTS_KPS = ["waist_l", "waist_r", "crotch", "cuff_l", "cuff_r"]


def build_shirt(owner, sleeve="short", rng=None):
    """Build a T-shirt mesh lying flat, centered at origin.

    Body: rectangle body_width x body_length.
    Sleeves: short stubs sticking out at shoulder height.
    Keypoints match perception KeypointsShirt.
    """
    rng = rng or random.Random()
    sh_w, body_w, body_l = SHIRT_DIMS[owner]
    hw, hl = body_w / 2, body_l / 2
    sh_hw = sh_w / 2

    # Sleeve stub extends beyond body
    sleeve_len = 0.14 if sleeve == "short" else 0.30
    sleeve_w = 0.10  # vertical extent of sleeve

    # Outline polygon (x, z), going clockwise from top-left
    # z+ = down (toward hem), z- = up (toward neck)
    z_neck, z_hem = -hl, hl
    z_sl_top, z_sl_bot = -hl + 0.06, -hl + 0.06 + sleeve_w
    outline = [
        (-sh_hw, z_neck),            # left neck
        (-hw - sleeve_len, z_sl_top),  # left sleeve tip top
        (-hw - sleeve_len, z_sl_bot),  # left sleeve tip bottom
        (-hw, z_sl_bot),             # left armpit
        (-hw, z_hem),                # left hem
        (hw, z_hem),                 # right hem
        (hw, z_sl_bot),              # right armpit
        (hw + sleeve_len, z_sl_bot),   # right sleeve tip bottom
        (hw + sleeve_len, z_sl_top),   # right sleeve tip top
        (sh_hw, z_neck),             # right neck
    ]

    # Triangulate as a fan from centroid (convex-ish, good enough for flat shirt)
    cx = sum(p[0] for p in outline) / len(outline)
    cz = sum(p[1] for p in outline) / len(outline)
    verts = [(cx, 0.002, cz)] + [(x, 0.002, z) for x, z in outline]
    faces = [(0, i + 1, (i + 1) % len(outline) + 1) for i in range(len(outline))]

    kp = {
        "sleeve_l": (-hw - sleeve_len + 0.02, 0.002, (z_sl_top + z_sl_bot) / 2),
        "sleeve_r": (hw + sleeve_len - 0.02, 0.002, (z_sl_top + z_sl_bot) / 2),
        "shoulder_l": (-sh_hw, 0.002, z_neck + 0.02),
        "shoulder_r": (sh_hw, 0.002, z_neck + 0.02),
        "hem_l": (-hw + 0.02, 0.002, z_hem - 0.01),
        "hem_r": (hw - 0.02, 0.002, z_hem - 0.01),
        # ABC fold points (left third line)
        "a": (-hw / 2, 0.002, z_neck + 0.02),
        "b": (-hw / 2, 0.002, 0.0),
        "c": (-hw / 2, 0.002, z_hem - 0.01),
    }
    return {"verts": verts, "faces": faces, "keypoints": kp, "outline": outline,
            "kind": "shirt", "owner": owner}


def build_pants(owner, rng=None):
    """Build pants mesh lying flat, waist at top (z-), cuffs at bottom (z+).

    Two legs side by side. Keypoints match perception KeypointsPants.
    """
    rng = rng or random.Random()
    waist_w, length = PANTS_DIMS[owner]
    hw = waist_w / 2
    z_waist, z_cuff = -length / 2, length / 2
    # Crotch: inseam starts ~35% down from waist
    z_crotch = z_waist + length * 0.35
    gap = 0.015  # small gap between legs at crotch
    # Slight taper: legs narrower at cuff
    taper = 0.92
    cuff_hw = hw * taper

    # Simple polygon around the full silhouette (clockwise from waist left):
    # down left outer → across left cuff → up to crotch → across → down to
    # right cuff → across → up right outer → across waist back to start
    outline = [
        (-hw, z_waist),            # waist left
        (-cuff_hw, z_cuff),        # left cuff outer
        (-gap, z_cuff),            # left cuff inner
        (-gap, z_crotch),          # up to crotch
        (gap, z_crotch),           # across crotch
        (gap, z_cuff),             # down to right cuff inner
        (cuff_hw, z_cuff),         # right cuff outer
        (hw, z_waist),             # up right outer to waist right
    ]

    cx = sum(p[0] for p in outline) / len(outline)
    cz = sum(p[1] for p in outline) / len(outline)
    verts = [(cx, 0.002, cz)] + [(x, 0.002, z) for x, z in outline]
    faces = [(0, i + 1, (i + 1) % len(outline) + 1) for i in range(len(outline))]

    kp = {
        "waist_l": (-hw + 0.01, 0.002, z_waist + 0.01),
        "waist_r": (hw - 0.01, 0.002, z_waist + 0.01),
        "crotch": (0.0, 0.002, z_crotch),
        "cuff_l": (-(cuff_hw + gap) / 2, 0.002, z_cuff - 0.01),
        "cuff_r": ((cuff_hw + gap) / 2, 0.002, z_cuff - 0.01),
    }
    return {"verts": verts, "faces": faces, "keypoints": kp, "outline": outline,
            "kind": "pants", "owner": owner}


def add_wrinkles(mesh, rng, amplitude=0.008, freq=25.0):
    """Add wrinkle noise to vertex heights (y). Returns new mesh dict."""
    verts = []
    for i, (x, y, z) in enumerate(mesh["verts"]):
        if i == 0:  # centroid stays
            verts.append((x, y, z))
            continue
        n = (math.sin(x * freq + rng.random() * 6.28) *
             math.cos(z * freq * 1.3 + rng.random() * 6.28))
        verts.append((x, y + abs(n) * amplitude * rng.uniform(0.5, 1.0), z))
    m = dict(mesh)
    m["verts"] = verts
    # keypoints ride at base height (detection target is 2D anyway)
    return m


def transform_mesh(mesh, dx, dz, yaw):
    """Translate + rotate mesh around Y. Returns new mesh dict."""
    cy, sy = math.cos(yaw), math.sin(yaw)

    def xf(x, z):
        return (x * cy - z * sy + dx, x * sy + z * cy + dz)

    verts = [(xf(x, z)[0], y, xf(x, z)[1]) for x, y, z in mesh["verts"]]
    kp = {k: (xf(x, z)[0], y, xf(x, z)[1]) for k, (x, y, z) in mesh["keypoints"].items()}
    outline = [xf(x, z) for x, z in mesh["outline"]]
    m = dict(mesh)
    m["verts"], m["keypoints"], m["outline"] = verts, kp, outline
    return m
