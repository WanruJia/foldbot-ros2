"""Fold math ported from fold.js — pure geometry, no dependencies.

World coords: Y up. A fold crease is a horizontal line through P=(px, axisH, pz)
with horizontal unit direction (dx, dz).
"""
import math


def side_of_line(px, pz, dx, dz, x, z):
    """Which side of the crease line (with direction dx,dz through px,pz) is (x,z).
    Returns sign of cross = dx*(z-pz) - dz*(x-px)."""
    return dx * (z - pz) - dz * (x - px)


def rot_point(px, py, pz, ax, ay, az, qx, qy, qz, theta):
    """Rotate point q around axis through p with unit direction a by theta (right-hand rule)."""
    c, s = math.cos(theta), math.sin(theta)
    vx, vy, vz = qx - px, qy - py, qz - pz
    # Rodrigues: v' = v*c + (a x v)*s + a*(a.v)*(1-c)
    dot = ax * vx + ay * vy + az * vz
    cx = ay * vz - az * vy
    cy = az * vx - ax * vz
    cz = ax * vy - ay * vx
    k = 1 - c
    return {
        'x': px + vx * c + cx * s + ax * dot * k,
        'y': py + vy * c + cy * s + ay * dot * k,
        'z': pz + vz * c + cz * s + az * dot * k,
    }


def fold_point_vert(px, pz, dx, dz, axis_h, fold_sign, t, x, y, z):
    """Target position of a vertex during one fold step.
    fold_sign +1 folds the cross>0 side, -1 folds cross<0 side.
    t: 0..1 progress (eased)."""
    theta = -fold_sign * math.pi * t
    length = math.hypot(dx, dz) or 1.0
    return rot_point(px, axis_h, pz, dx / length, 0, dz / length, x, y, z, theta)


def ease_in_out_cubic(t):
    return 4 * t * t * t if t < 0.5 else 1 - pow(-2 * t + 2, 3) / 2
