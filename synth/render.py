"""Top-down renderer with domain randomization for synthetic garment data.

Camera: orthographic top-down (like a robot overhead camera).
Output: RGB image + projected 2D keypoints.

Domain randomization:
  - garment position / rotation on table
  - wrinkle amplitude
  - fabric hue / brightness
  - table background color / texture noise
  - lighting gradient direction
  - slight camera offset (translation only — keeps keypoints valid)
"""
import math
import random

import numpy as np

from .garments import build_shirt, build_pants, add_wrinkles, transform_mesh

# Image / camera
IMG_W, IMG_H = 640, 480
# Camera covers 1.4m x 1.05m on the table (fits dad's 1.0m pants)
CAM_W, CAM_H = 1.4, 1.05

# Fabric hues per owner (matches viz: dad blue, mom purple, daughter pink, son green)
OWNER_HUE = {"dad": 210, "mom": 280, "daughter": 330, "son": 120}


def _hsl_to_rgb(h, s, l):
    h = h % 360 / 360.0
    if s == 0:
        return (l, l, l)
    q = l * (1 + s) if l < 0.5 else l + s - l * s
    p = 2 * l - q
    def tc(t):
        t = t % 1.0
        if t < 1 / 6: return p + (q - p) * 6 * t
        if t < 1 / 2: return q
        if t < 2 / 3: return p + (q - p) * (2 / 3 - t) * 6
        return p
    return (tc(h + 1 / 3), tc(h), tc(h - 1 / 3))


def world_to_px(x, z, cam_cx=0.0, cam_cz=0.0):
    """Orthographic top-down: world (x,z) -> pixel (u,v)."""
    u = (x - cam_cx + CAM_W / 2) / CAM_W * IMG_W
    v = (z - cam_cz + CAM_H / 2) / CAM_H * IMG_H
    return u, v


def render_sample(rng, kind=None, owner=None):
    """Render one randomized sample.

    Returns (image_np_HWC_uint8, keypoints_2d_dict, meta_dict).
    """
    kind = kind or rng.choice(["shirt", "pants"])
    owner = owner or rng.choice(["dad", "mom", "daughter", "son"])
    sleeve = rng.choice(["short", "long"]) if kind == "shirt" else None
    np_rng = np.random.default_rng(rng.randrange(2**31))

    # Build garment
    if kind == "shirt":
        mesh = build_shirt(owner, sleeve=sleeve, rng=rng)
    else:
        mesh = build_pants(owner, rng=rng)

    # Randomize wrinkles
    mesh = add_wrinkles(mesh, rng, amplitude=rng.uniform(0.003, 0.012))

    # Randomize rotation: try up to 20 yaws, keep one whose rotated bbox fits
    # (large garments only fit when axis-aligned)
    cam_margin = 0.06
    placed = False
    for _ in range(20):
        yaw = rng.uniform(-math.pi, math.pi)
        cy, sy = math.cos(yaw), math.sin(yaw)
        rx = [x * cy - z * sy for x, z in mesh["outline"]]
        rz = [x * sy + z * cy for x, z in mesh["outline"]]
        for x, y, z in mesh["keypoints"].values():
            rx.append(x * cy - z * sy)
            rz.append(x * sy + z * cy)
        hx = (max(rx) - min(rx)) / 2
        hz = (max(rz) - min(rz)) / 2
        x_range = CAM_W / 2 - hx - cam_margin
        z_range = CAM_H / 2 - hz - cam_margin
        if x_range > 0 and z_range > 0:
            placed = True
            break
    if not placed:
        yaw = 0.0  # fallback: axis-aligned (fits by construction for our sizes)
        cy, sy = 1.0, 0.0
        rx = [x for x, z in mesh["outline"]]
        rz = [z for x, z in mesh["outline"]]
        hx = (max(rx) - min(rx)) / 2
        hz = (max(rz) - min(rz)) / 2
        x_range = max(CAM_W / 2 - hx - cam_margin, 0)
        z_range = max(CAM_H / 2 - hz - cam_margin, 0)
    dx = rng.uniform(-x_range, x_range) if x_range > 0 else 0.0
    dz = rng.uniform(-z_range, z_range) if z_range > 0 else 0.0
    mesh = transform_mesh(mesh, dx, dz, yaw)

    # Slight camera offset (accounted for in placement margin above)
    cam_cx = rng.uniform(-0.05, 0.05)
    cam_cz = rng.uniform(-0.05, 0.05)

    # --- rasterize with matplotlib ---
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon
    from matplotlib.collections import PolyCollection

    fig = plt.figure(figsize=(IMG_W / 100, IMG_H / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, IMG_W)
    ax.set_ylim(IMG_H, 0)  # v grows downward
    ax.axis("off")

    # Table background with noise
    bg_base = rng.uniform(0.55, 0.75)
    bg = np.full((IMG_H, IMG_W, 3), bg_base, dtype=np.float32)
    bg += np_rng.normal(0, 0.02, bg.shape)
    # subtle wood-grain-ish streaks
    for _ in range(rng.randint(3, 8)):
        y0 = rng.randint(0, IMG_H)
        bg[y0:y0 + rng.randint(2, 6), :, :] *= rng.uniform(0.92, 1.0)
    bg = np.clip(bg, 0, 1)
    ax.imshow(bg, extent=(0, IMG_W, IMG_H, 0), zorder=0)

    # Fabric color
    hue = OWNER_HUE[owner] + rng.uniform(-15, 15)
    sat = rng.uniform(0.35, 0.6)
    light = rng.uniform(0.62, 0.78)
    base_rgb = _hsl_to_rgb(hue, sat, light)

    # Triangulate outline as fan (same as mesh) for wrinkle shading
    outline_px = [world_to_px(x, z, cam_cx, cam_cz) for x, z in mesh["outline"]]

    # Soft drop shadow (offset dark polygon under garment)
    sh_off = (rng.uniform(4, 10), rng.uniform(4, 10))
    shadow_poly = [(u + sh_off[0], v + sh_off[1]) for u, v in outline_px]
    ax.add_patch(Polygon(shadow_poly, closed=True, facecolor=(0, 0, 0),
                         alpha=rng.uniform(0.12, 0.22), zorder=1,
                         edgecolor="none"))

    # Garment body: single filled polygon (fan triangulation overlaps on
    # concave outlines, so fill flat and add wrinkles as a clipped overlay)
    garment_patch = Polygon(outline_px, closed=True, facecolor=base_rgb,
                            edgecolor=(0.25, 0.25, 0.3), linewidth=1.2,
                            alpha=1.0, zorder=2)
    ax.add_patch(garment_patch)

    # Wrinkle shading: sinusoidal bands clipped to the garment polygon
    wr_amp = rng.uniform(0.04, 0.10)
    wr_freq = rng.uniform(0.02, 0.05)
    wr_ang = rng.uniform(0, math.pi)
    yy, xx = np.mgrid[0:IMG_H, 0:IMG_W]
    wr = np.sin((xx * math.cos(wr_ang) + yy * math.sin(wr_ang)) * wr_freq * 6.28
                + np_rng.uniform(0, 6.28))
    wr = 1.0 + wr * wr_amp
    wr = np.clip(wr, 0.85, 1.15)
    wr_rgb = np.stack([wr] * 3, axis=-1)
    ax.imshow(wr_rgb, extent=(0, IMG_W, IMG_H, 0), alpha=0.55, zorder=3,
              clip_path=garment_patch, clip_on=True)

    # Lighting gradient overlay
    grad = np.linspace(rng.uniform(0.92, 1.0), rng.uniform(1.0, 1.08), IMG_W)
    grad = np.clip(np.tile(grad, (IMG_H, 1)), 0, 1)
    ax.imshow(np.stack([grad] * 3, axis=-1), extent=(0, IMG_W, IMG_H, 0),
              alpha=0.12, zorder=4)

    fig.canvas.draw()
    buf = np.asarray(fig.canvas.buffer_rgba())
    plt.close(fig)
    img = (buf[:, :, :3]).astype(np.uint8)

    # Project keypoints
    kps_2d = {}
    for name, (x, y, z) in mesh["keypoints"].items():
        u, v = world_to_px(x, z, cam_cx, cam_cz)
        # visibility: 1 if inside image
        vis = 1 if (0 <= u < IMG_W and 0 <= v < IMG_H) else 0
        kps_2d[name] = (u, v, vis)

    meta = {"kind": kind, "owner": owner, "sleeve": sleeve,
            "dx": dx, "dz": dz, "yaw": yaw}
    return img, kps_2d, meta
