"""M4b tests: owner-classification margins and candidate ranking.

Item 4 decision: real-size thresholds (already in classify_owner), NOT
owner-class training (only 5 real garments exist — mom has none, dad-pants
and son-pants are absent; training would memorize identities).
These tests pin the honest-ambiguity layer added on top of the thresholds:
owner_margin() and classify_owner_candidates().
"""
import math
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from planning.fold_planner import (
    classify_owner, owner_margin, classify_owner_candidates,
    OWNER_AMBIGUOUS_MARGIN, OWNER_BOUNDARIES,
)


def _shirt_k(shoulder_w):
    hw = shoulder_w / 2
    P = lambda x, z: {"x": x, "y": 0.002, "z": z}
    return {"shoulder_l": P(-hw, -0.18), "shoulder_r": P(hw, -0.18)}


def _pants_k(waist_w):
    hw = waist_w / 2
    P = lambda x, z: {"x": x, "y": 0.002, "z": z}
    return {"waist_l": P(-hw, -0.25), "waist_r": P(hw, -0.25)}


def test_margin_values():
    # shirt boundaries: 0.33 / 0.345 / 0.39
    assert math.isclose(owner_margin("shirt", 0.43), 0.04, abs_tol=1e-9)
    assert owner_margin("shirt", 0.345) == 0.0          # exactly on boundary
    assert math.isclose(owner_margin("shirt", 0.34), 0.005, abs_tol=1e-9)
    assert math.isclose(owner_margin("shirt", 0.35), 0.005, abs_tol=1e-9)
    assert math.isclose(owner_margin("shirt", 0.27), 0.06, abs_tol=1e-9)
    assert math.isclose(owner_margin("shirt", 0.32), 0.01, abs_tol=1e-9)
    # pants boundaries: 0.36 / 0.44 / 0.52
    assert math.isclose(owner_margin("pants", 0.48), 0.04, abs_tol=1e-9)
    assert math.isclose(owner_margin("pants", 0.40), 0.04, abs_tol=1e-9)
    assert math.isclose(owner_margin("pants", 0.32), 0.04, abs_tol=1e-9)
    assert owner_margin("pants", 0.44) == 0.0
    assert math.isclose(owner_margin("pants", 0.50), 0.02, abs_tol=1e-9)
    print("PASS test_margin_values")


def test_candidates_agree_with_classify():
    # Sweep: candidates[0][0] must ALWAYS equal classify_owner()[0]
    # (by construction), including exact boundary ties (thresholds use >=),
    # and the list must stay distance-ranked.
    n = 0
    for kind, lo, hi in (("shirt", 0.20, 0.60), ("pants", 0.20, 0.70)):
        w = lo
        while w <= hi + 1e-12:
            k = _shirt_k(w) if kind == "shirt" else _pants_k(w)
            want = classify_owner(kind, k)[0]
            cands = classify_owner_candidates(kind, k)
            assert cands[0][0] == want, \
                f"{kind} w={w:.3f}: classify={want}, candidates={cands}"
            dists = [d for _, d in cands]
            assert dists == sorted(dists), f"{kind} w={w}: not ranked"
            assert len(cands) == 4
            n += 1
            w += 0.005
    # exact boundaries included in the sweep above; double-check a few
    for kind in ("shirt", "pants"):
        for b in OWNER_BOUNDARIES[kind]:
            k = _shirt_k(b) if kind == "shirt" else _pants_k(b)
            assert classify_owner_candidates(kind, k)[0][0] == \
                classify_owner(kind, k)[0], f"{kind} boundary {b}"
    print(f"PASS test_candidates_agree_with_classify ({n} widths, 2 kinds)")


def test_ambiguous_mom_daughter_shirt():
    # mom 0.35 vs daughter 0.34: the real 1 cm gap. A 0.34 measurement is
    # labeled daughter with margin 5 mm < 10 mm -> ambiguous, honest
    # alternative is mom.
    k = _shirt_k(0.34)
    owner, m, _ = classify_owner(kind="shirt", k=k)
    assert owner == "daughter"
    margin = owner_margin("shirt", m)
    assert margin < OWNER_AMBIGUOUS_MARGIN, f"margin={margin}"
    cands = classify_owner_candidates("shirt", k)
    assert cands[0] == ("daughter", 0.0)
    assert cands[1][0] == "mom", f"alt should be mom, got {cands}"
    print("PASS test_ambiguous_mom_daughter_shirt")


def test_son_shirt_range():
    # son's real shirts span 0.27-0.32: inside the interval distance is 0
    # and the label stays son across the whole range.
    for w in (0.27, 0.30, 0.32):
        k = _shirt_k(w)
        assert classify_owner("shirt", k)[0] == "son", w
        assert classify_owner_candidates("shirt", k)[0] == ("son", 0.0), w
    print("PASS test_son_shirt_range")


def test_lenient_kind_contract():
    # Established contract: non-"shirt" kinds (e.g. the board test's
    # "tee") are measured like pants — in ALL THREE functions, consistently.
    k = _pants_k(0.48)
    assert classify_owner("tee", k)[0] == classify_owner("pants", k)[0] == "mom"
    assert owner_margin("tee", 0.48) == owner_margin("pants", 0.48)
    assert [o for o, _ in classify_owner_candidates("tee", k)] == \
           [o for o, _ in classify_owner_candidates("pants", k)]
    print("PASS test_lenient_kind_contract")


if __name__ == "__main__":
    test_margin_values()
    test_candidates_agree_with_classify()
    test_ambiguous_mom_daughter_shirt()
    test_son_shirt_range()
    test_lenient_kind_contract()
    print("\nAll owner-margin tests passed ✅")
