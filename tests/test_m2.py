"""M2 tests: fold planner ported from planner.js."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from planning.fold_planner import (
    classify_owner, detect_pants_length, pants_fold_mode,
    plan_folds, plan_pants_folds,
)


def _shirt_k(shoulder_w=0.62):
    cx, cz = 0.0, 0.0
    hw = shoulder_w / 2
    P = lambda x, z: {"x": cx + x, "y": 0.002, "z": cz + z}
    return {
        "sleeve_l": P(-hw - 0.12, 0.05), "sleeve_r": P(hw + 0.12, 0.05),
        "shoulder_l": P(-hw, -0.18), "shoulder_r": P(hw, -0.18),
        "hem_l": P(-hw + 0.02, 0.22), "hem_r": P(hw - 0.02, 0.22),
        "a": P(-hw / 2, -0.18), "b": P(-hw / 2, 0.02), "c": P(-hw / 2, 0.22),
    }


def _pants_k(waist_w=0.48, long=True):
    cx, cz = 0.0, 0.0
    hw = waist_w / 2
    leg = 0.95 if long else 0.38  # realistic leg lengths (dad long=0.95)
    P = lambda x, z: {"x": cx + x, "y": 0.002, "z": cz + z}
    return {
        "waist_l": P(-hw, -0.25), "waist_r": P(hw, -0.25),
        "crotch": P(0, -0.05),
        "cuff_l": P(-hw + 0.03, -0.25 + leg), "cuff_r": P(hw - 0.03, -0.25 + leg),
    }


def test_classify_owner():
    # 真实数据校准 (2026-10-05): dad 0.43 / mom 0.35 / daughter 0.32 / son 0.27-0.32
    cases = [
        ("shirt", 0.43, "dad"), ("shirt", 0.35, "mom"),
        ("shirt", 0.32, "daughter"), ("shirt", 0.27, "son"),
        ("pants", 0.56, "dad"), ("pants", 0.48, "mom"),
        ("pants", 0.40, "daughter"), ("pants", 0.32, "son"),
    ]
    for kind, w, want in cases:
        k = _shirt_k(w) if kind == "shirt" else _pants_k(w)
        owner, m, name = classify_owner(kind, k)
        assert owner == want, f"{kind} w={w}: got {owner}, want {want}"
    print("PASS test_classify_owner (8 cases, real-data thresholds)")


def test_pants_length_and_mode():
    assert detect_pants_length(_pants_k(0.48, True)) == "long"
    assert detect_pants_length(_pants_k(0.48, False)) == "short"
    assert pants_fold_mode("dad", "long") == "tri"
    assert pants_fold_mode("dad", "short") == "bi"
    assert pants_fold_mode("mom", "long") == "tri"
    assert pants_fold_mode("daughter", "long") == "bi"
    assert pants_fold_mode("daughter", "short") == "none"
    assert pants_fold_mode("son", "short") == "none"
    print("PASS test_pants_length_and_mode")


def test_plan_folds_shirt():
    plan = plan_folds(_shirt_k(0.62))
    assert len(plan.folds) == 3, f"shirt should have 3 folds (left+right+hem), got {len(plan.folds)}"
    assert plan.folds[0].grab_arm == "L" and plan.folds[1].grab_arm == "R"
    assert plan.folds[0].label == "左折" and plan.folds[1].label == "右折"
    assert len(plan.markers) == 4  # A, A', B, C
    print("PASS test_plan_folds_shirt (3 folds: left+right+hem)")


def test_plan_pants_modes():
    k = _pants_k(0.48, True)
    assert len(plan_pants_folds(k, "tri").folds) == 3, "tri should have 3 folds"
    assert len(plan_pants_folds(k, "bi").folds) == 2, "bi should have 2 folds"
    assert len(plan_pants_folds(k, "none").folds) == 1, "none should have 1 fold"
    print("PASS test_plan_pants_modes (tri=3, bi=2, none=1)")


if __name__ == "__main__":
    test_classify_owner()
    test_pants_length_and_mode()
    test_plan_folds_shirt()
    test_plan_pants_modes()
    print("\nAll M2 tests passed ✅")
