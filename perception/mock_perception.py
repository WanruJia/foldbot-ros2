"""Mock perception node (M0).

Returns canned keypoints so the BT main tree runs end-to-end without hardware.
Real robot: replace with learned segmentation + HRNet keypoint detector.
"""
import random
from msgs.interfaces import (
    PerceptionResult, KeypointsShirt, KeypointsPants, Point3D,
)


def _pt(x, y, z):
    return Point3D(x=x, y=y, z=z)


def mock_perceive(kind="shirt", owner="mom"):
    """Simulate a perception pipeline result.

    kind: 'shirt' | 'pants' | 'random'
    owner: 'dad' | 'mom' | 'daughter' | 'son' | 'random'
    """
    if kind == "random":
        kind = random.choice(["shirt", "pants"])
    if owner == "random":
        owner = random.choice(["dad", "mom", "daughter", "son"])

    result = PerceptionResult(kind=kind, owner=owner)

    if kind == "shirt":
        # 真实数据 (2026-10-05): dad 0.43 / mom 0.35 / daughter 0.32 / son 0.27
        widths = {"dad": 0.43, "mom": 0.35, "daughter": 0.32, "son": 0.27}
        w = widths[owner]
        cx, cz = (random.random() - 0.5) * 0.2, (random.random() - 0.5) * 0.15
        k = KeypointsShirt(
            sleeve_l=_pt(cx - w / 2 - 0.12, 0.002, cz + 0.05),
            sleeve_r=_pt(cx + w / 2 + 0.12, 0.002, cz + 0.05),
            shoulder_l=_pt(cx - w / 2, 0.002, cz - 0.18),
            shoulder_r=_pt(cx + w / 2, 0.002, cz - 0.18),
            hem_l=_pt(cx - w / 2 + 0.02, 0.002, cz + 0.22),
            hem_r=_pt(cx + w / 2 - 0.02, 0.002, cz + 0.22),
            a=_pt(cx - w / 4, 0.002, cz - 0.18),
            b=_pt(cx - w / 4, 0.002, cz + 0.02),
            c=_pt(cx - w / 4, 0.002, cz + 0.22),
        )
        result.keypoints_shirt = k
        result.metric, result.metric_name = w, "肩宽"
    else:
        widths = {"dad": 0.56, "mom": 0.48, "daughter": 0.40, "son": 0.32}
        w = widths[owner]
        cx, cz = (random.random() - 0.5) * 0.2, (random.random() - 0.5) * 0.15
        # 长裤: 腿长 ~1.7x 腰宽 (dad 0.95/0.56)，保证 detect_pants_length 判为 long
        leg = w * 1.7
        k = KeypointsPants(
            waist_l=_pt(cx - w / 2, 0.002, cz - 0.25),
            waist_r=_pt(cx + w / 2, 0.002, cz - 0.25),
            crotch=_pt(cx, 0.002, cz - 0.05),
            cuff_l=_pt(cx - w / 2 + 0.03, 0.002, cz - 0.25 + leg),
            cuff_r=_pt(cx + w / 2 - 0.03, 0.002, cz - 0.25 + leg),
        )
        result.keypoints_pants = k
        result.metric, result.metric_name = w, "腰宽"

    return result


if __name__ == "__main__":
    r = mock_perceive("shirt", "mom")
    print(f"kind={r.kind} owner={r.owner} {r.metric_name}={r.metric:.3f}")
    r = mock_perceive("pants", "dad")
    print(f"kind={r.kind} owner={r.owner} {r.metric_name}={r.metric:.3f}")
