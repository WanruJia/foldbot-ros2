"""Fold planner ported from planner.js — pure geometry, no dependencies.

Input: world-coordinate keypoints. Output: FoldPlan (see msgs.interfaces).
Mirrors the simulation's fold policies exactly:
  - T-shirt: flip left side along ABC line, then hem flip (2 folds)
  - Pants: leg-to-leg fold first, then by mode:
      tri  (adult long):   bottom third up, top third back (3 folds total)
      bi   (adult short / child long): flip in half (2 folds total)
      none (child short):  no length fold (1 fold total)
"""
import math
from planning.fold_math import side_of_line, fold_point_vert
from msgs.interfaces import (
    FoldPlan, FoldStep, Point3D,
)


def _norm2(x, z):
    l = math.hypot(x, z) or 1.0
    return x / l, z / l


def _after_fold(f, p):
    """Position of point p after fold f completes (t=1)."""
    if side_of_line(f["px"], f["pz"], f["dx"], f["dz"], p["x"], p["z"]) * f["fold_sign"] > 0:
        q = fold_point_vert(f["px"], f["pz"], f["dx"], f["dz"],
                            f["axis_h"], f["fold_sign"], 1,
                            p["x"], p.get("y", 0.002), p["z"])
        return q
    return dict(p)


def _pt(x, y, z):
    return Point3D(x=x, y=y, z=z)


def classify_owner(kind, k):
    """Classify garment owner from keypoint measurements.
    kind: 'shirt' | 'pants'. k: dict of {'x','z'} keypoints.
    Returns (owner, metric, metric_name)."""
    if kind == "shirt":
        m = math.hypot(k["shoulder_r"]["x"] - k["shoulder_l"]["x"],
                       k["shoulder_r"]["z"] - k["shoulder_l"]["z"])
        name = "肩宽"
        if m >= 0.69:
            return "dad", m, name
        if m >= 0.595:
            return "mom", m, name
        if m >= 0.50:
            return "daughter", m, name
        return "son", m, name
    m = math.hypot(k["waist_r"]["x"] - k["waist_l"]["x"],
                   k["waist_r"]["z"] - k["waist_l"]["z"])
    name = "腰宽"
    if m >= 0.52:
        return "dad", m, name
    if m >= 0.44:
        return "mom", m, name
    if m >= 0.36:
        return "daughter", m, name
    return "son", m, name


def detect_pants_length(k):
    """'long' | 'short' from waist-to-cuff length vs waist width."""
    waist_cx = (k["waist_l"]["x"] + k["waist_r"]["x"]) / 2
    waist_cz = (k["waist_l"]["z"] + k["waist_r"]["z"]) / 2
    cuff_cx = (k["cuff_l"]["x"] + k["cuff_r"]["x"]) / 2
    cuff_cz = (k["cuff_l"]["z"] + k["cuff_r"]["z"]) / 2
    h = math.hypot(cuff_cx - waist_cx, cuff_cz - waist_cz)
    wd = math.hypot(k["waist_r"]["x"] - k["waist_l"]["x"],
                    k["waist_r"]["z"] - k["waist_l"]["z"])
    return "long" if (h / max(1e-6, wd) > 1.4) else "short"


def pants_fold_mode(owner, length):
    """'tri' | 'bi' | 'none' per the requested pants policy."""
    adult = owner in ("dad", "mom")
    if adult:
        return "tri" if length == "long" else "bi"
    return "bi" if length == "long" else "none"


def plan_folds(k):
    """T-shirt: B-step left fold, C-step right fold (mirror), D-step hem flip.
    k: dict with sleeve_l/r, shoulder_l/r, hem_l/r, a, b, c (each {'x','y','z'})."""
    hem_mid = {"x": (k["hem_l"]["x"] + k["hem_r"]["x"]) / 2, "y": 0.002,
               "z": (k["hem_l"]["z"] + k["hem_r"]["z"]) / 2}
    top_mid = {"x": (k["shoulder_l"]["x"] + k["shoulder_r"]["x"]) / 2,
               "z": (k["shoulder_l"]["z"] + k["shoulder_r"]["z"]) / 2}
    up = _norm2(top_mid["x"] - hem_mid["x"], top_mid["z"] - hem_mid["z"])
    right = _norm2(k["sleeve_r"]["x"] - k["sleeve_l"]["x"],
                   k["sleeve_r"]["z"] - k["sleeve_l"]["z"])

    # Fold 1: left side in along left ABC line
    s1 = side_of_line(k["a"]["x"], k["a"]["z"], up[0], up[1],
                      k["sleeve_l"]["x"], k["sleeve_l"]["z"])
    fold1 = {"px": k["a"]["x"], "pz": k["a"]["z"], "dx": up[0], "dz": up[1],
             "fold_sign": 1 if s1 >= 0 else -1, "axis_h": 0.008, "duration": 1.6}
    keep1 = _norm2(k["c"]["x"] - k["sleeve_l"]["x"], k["c"]["z"] - k["sleeve_l"]["z"])

    # Fold 1b: right side in (A mirrored to A2) — right sleeve unaffected by fold1
    a2x = k["shoulder_r"]["x"] - (k["a"]["x"] - k["shoulder_l"]["x"])
    s1b = side_of_line(a2x, k["a"]["z"], up[0], up[1],
                       k["sleeve_r"]["x"], k["sleeve_r"]["z"])
    fold1b = {"px": a2x, "pz": k["a"]["z"], "dx": up[0], "dz": up[1],
              "fold_sign": 1 if s1b >= 0 else -1, "axis_h": 0.008, "duration": 1.6}
    c2x = k["shoulder_r"]["x"] - (k["c"]["x"] - k["shoulder_l"]["x"])
    keep1b = _norm2(c2x - k["sleeve_r"]["x"], k["c"]["z"] - k["sleeve_r"]["z"])

    hem_lf = _after_fold(fold1, k["hem_l"])
    hem_rf = _after_fold(fold1b, k["hem_r"])
    hem_mid_f = {"x": (hem_lf["x"] + hem_rf["x"]) / 2,
                 "y": max(hem_lf["y"], hem_rf["y"]) + 0.015,
                 "z": (hem_lf["z"] + hem_rf["z"]) / 2}
    s2 = side_of_line(k["b"]["x"], k["b"]["z"], right[0], right[1],
                      hem_mid_f["x"], hem_mid_f["z"])
    fold2 = {"px": k["b"]["x"], "pz": k["b"]["z"], "dx": right[0], "dz": right[1],
             "fold_sign": 1 if s2 >= 0 else -1, "axis_h": 0.014, "duration": 1.5}
    keep2 = _norm2(k["b"]["x"] - hem_mid_f["x"], k["b"]["z"] - hem_mid_f["z"])

    folds = [
        FoldStep(
            label="左折", status="B·左折 — 左臂抓左袖口, 沿左ABC线翻折",
            px=fold1["px"], pz=fold1["pz"], dx=fold1["dx"], dz=fold1["dz"],
            fold_sign=fold1["fold_sign"], axis_h=fold1["axis_h"], duration=fold1["duration"],
            grab=_pt(k["sleeve_l"]["x"], 0.002, k["sleeve_l"]["z"]), grab_arm="L",
            press=_pt(k["c"]["x"] + keep1[0] * 0.05, 0.03, k["c"]["z"] + keep1[1] * 0.05),
            press_arm="R",
        ),
        FoldStep(
            label="右折", status="C·右折 — 右臂抓右袖口, 沿右ABC线翻折",
            px=fold1b["px"], pz=fold1b["pz"], dx=fold1b["dx"], dz=fold1b["dz"],
            fold_sign=fold1b["fold_sign"], axis_h=fold1b["axis_h"], duration=fold1b["duration"],
            grab=_pt(k["sleeve_r"]["x"], 0.002, k["sleeve_r"]["z"]), grab_arm="R",
            press=_pt(c2x + keep1b[0] * 0.05, 0.03, k["c"]["z"] + keep1b[1] * 0.05),
            press_arm="L",
        ),
        FoldStep(
            label="对折", status="D·对折 — 右臂抓下摆, 上翻对折",
            px=fold2["px"], pz=fold2["pz"], dx=fold2["dx"], dz=fold2["dz"],
            fold_sign=fold2["fold_sign"], axis_h=fold2["axis_h"], duration=fold2["duration"],
            grab=_pt(hem_mid_f["x"], hem_mid_f["y"], hem_mid_f["z"]), grab_arm="R",
            press=_pt(k["b"]["x"] + keep2[0] * 0.05, 0.04, k["b"]["z"] + keep2[1] * 0.05),
            press_arm="L",
        ),
    ]
    markers = [
        {"name": "A", "x": k["a"]["x"], "y": k["a"]["y"], "z": k["a"]["z"],
         "color": "#ff5252", "label": "A"},
        {"name": "A2", "x": a2x, "y": k["a"]["y"], "z": k["a"]["z"],
         "color": "#ff5252", "label": "A'"},
        {"name": "B", "x": k["b"]["x"], "y": k["b"]["y"], "z": k["b"]["z"],
         "color": "#ff9f1c", "label": "B"},
        {"name": "C", "x": k["c"]["x"], "y": k["c"]["y"], "z": k["c"]["z"],
         "color": "#3a86ff", "label": "C"},
    ]
    return FoldPlan(kind="shirt", folds=folds, markers=markers)


def plan_pants_folds(k, mode):
    """Pants fold plan. k: waist_l/r, crotch, cuff_l/r. mode: tri|bi|none."""
    waist_c = {"x": (k["waist_l"]["x"] + k["waist_r"]["x"]) / 2, "y": 0.002,
               "z": (k["waist_l"]["z"] + k["waist_r"]["z"]) / 2}
    cuff_c = {"x": (k["cuff_l"]["x"] + k["cuff_r"]["x"]) / 2, "y": 0.002,
              "z": (k["cuff_l"]["z"] + k["cuff_r"]["z"]) / 2}
    up = _norm2(waist_c["x"] - cuff_c["x"], waist_c["z"] - cuff_c["z"])
    right = _norm2(k["cuff_r"]["x"] - k["cuff_l"]["x"],
                   k["cuff_r"]["z"] - k["cuff_l"]["z"])

    folds = []
    # B-step: leg-to-leg fold
    s1 = side_of_line(waist_c["x"], waist_c["z"], up[0], up[1],
                      k["cuff_l"]["x"], k["cuff_l"]["z"])
    f1 = {"px": waist_c["x"], "pz": waist_c["z"], "dx": up[0], "dz": up[1],
          "fold_sign": 1 if s1 >= 0 else -1, "axis_h": 0.006, "duration": 1.6}
    keep_side1 = _norm2(k["cuff_r"]["x"] - k["cuff_l"]["x"],
                        k["cuff_r"]["z"] - k["cuff_l"]["z"])
    mid_c = {"x": waist_c["x"] + (cuff_c["x"] - waist_c["x"]) * 0.55, "y": 0.03,
             "z": waist_c["z"] + (cuff_c["z"] - waist_c["z"]) * 0.55}
    folds.append(FoldStep(
        label="对折", status="B·对折 — 左臂抓裤脚, 右臂按住中部, 左右对折",
        px=f1["px"], pz=f1["pz"], dx=f1["dx"], dz=f1["dz"],
        fold_sign=f1["fold_sign"], axis_h=f1["axis_h"], duration=f1["duration"],
        grab=_pt(k["cuff_l"]["x"], 0.002, k["cuff_l"]["z"]), grab_arm="L",
        press=_pt(mid_c["x"] + keep_side1[0] * 0.045, 0.03,
                  mid_c["z"] + keep_side1[1] * 0.045), press_arm="R",
    ))

    cuff_lf = _after_fold(f1, k["cuff_l"])
    waist_lf = _after_fold(f1, k["waist_l"])
    waist_mid_f = {"x": (waist_lf["x"] + k["waist_r"]["x"]) / 2, "y": 0.002,
                   "z": (waist_lf["z"] + k["waist_r"]["z"]) / 2}
    cuff_mid_f = {"x": (cuff_lf["x"] + k["cuff_r"]["x"]) / 2,
                  "y": max(cuff_lf["y"], k["cuff_r"]["y"]) + 0.012,
                  "z": (cuff_lf["z"] + k["cuff_r"]["z"]) / 2}

    markers = [
        {"name": "waist", "x": waist_c["x"], "y": waist_c["y"], "z": waist_c["z"],
         "color": "#ff5252", "label": "腰"},
        {"name": "crotch", "x": k["crotch"]["x"], "y": 0.002, "z": k["crotch"]["z"],
         "color": "#ff9f1c", "label": "裆"},
        {"name": "cuff", "x": k["cuff_l"]["x"], "y": 0.002, "z": k["cuff_l"]["z"],
         "color": "#3a86ff", "label": "裤脚"},
    ]

    if mode != "none":
        frac = 1 / 3 if mode == "tri" else 1 / 2
        cp = {"x": cuff_mid_f["x"] + (waist_mid_f["x"] - cuff_mid_f["x"]) * frac, "y": 0.012,
              "z": cuff_mid_f["z"] + (waist_mid_f["z"] - cuff_mid_f["z"]) * frac}
        s2 = side_of_line(cp["x"], cp["z"], right[0], right[1],
                          cuff_mid_f["x"], cuff_mid_f["z"])
        f2 = {"px": cp["x"], "pz": cp["z"], "dx": right[0], "dz": right[1],
              "fold_sign": 1 if s2 >= 0 else -1, "axis_h": 0.012, "duration": 1.5}
        keep2 = _norm2(waist_mid_f["x"] - cp["x"], waist_mid_f["z"] - cp["z"])
        folded_hw = abs(k["waist_r"]["x"] - k["waist_l"]["x"]) / 2
        folds.append(FoldStep(
            label="三折①" if mode == "tri" else "折叠",
            status=("C·三折 — 右臂抓裤脚, 下三分之一上折"
                    if mode == "tri" else "C·折叠 — 右臂抓裤脚, 上翻对折"),
            px=f2["px"], pz=f2["pz"], dx=f2["dx"], dz=f2["dz"],
            fold_sign=f2["fold_sign"], axis_h=f2["axis_h"], duration=f2["duration"],
            grab=_pt(cuff_mid_f["x"], cuff_mid_f["y"], cuff_mid_f["z"]), grab_arm="R",
            press=_pt(cp["x"] - right[0] * folded_hw * 0.5 + keep2[0] * 0.04, 0.035,
                      cp["z"] - right[1] * folded_hw * 0.5 + keep2[1] * 0.04),
            press_arm="L",
        ))
        if mode == "tri":
            cp_b = {"x": cuff_mid_f["x"] + (waist_mid_f["x"] - cuff_mid_f["x"]) * (2 / 3),
                    "y": 0.018,
                    "z": cuff_mid_f["z"] + (waist_mid_f["z"] - cuff_mid_f["z"]) * (2 / 3)}
            s3 = side_of_line(cp_b["x"], cp_b["z"], right[0], right[1],
                              waist_mid_f["x"], waist_mid_f["z"])
            f3 = {"px": cp_b["x"], "pz": cp_b["z"], "dx": right[0], "dz": right[1],
                  "fold_sign": 1 if s3 >= 0 else -1, "axis_h": 0.018, "duration": 1.5}
            grab_b = {"x": waist_mid_f["x"] + (cp_b["x"] - waist_mid_f["x"]) * 0.5,
                      "z": waist_mid_f["z"] + (cp_b["z"] - waist_mid_f["z"]) * 0.5}
            keep3 = _norm2(cp_b["x"] - waist_mid_f["x"], cp_b["z"] - waist_mid_f["z"])
            folds.append(FoldStep(
                label="三折②", status="D·三折 — 右臂抓腰身, 上三分之一回折",
                px=f3["px"], pz=f3["pz"], dx=f3["dx"], dz=f3["dz"],
                fold_sign=f3["fold_sign"], axis_h=f3["axis_h"], duration=f3["duration"],
                grab=_pt(grab_b["x"], 0.002, grab_b["z"]), grab_arm="R",
                press=_pt(cp_b["x"] - right[0] * 0.18 + keep3[0] * 0.04, 0.04,
                          cp_b["z"] - right[1] * 0.18 + keep3[1] * 0.04),
                press_arm="L",
            ))
    return FoldPlan(kind="pants", folds=folds, markers=markers)
