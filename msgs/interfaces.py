"""Interface definitions (M0: Python dataclasses; real robot: ROS 2 .msg/.srv/.action).

These mirror the data structures from planner.js so the existing logic
ports over unchanged.
"""
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Point3D:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


@dataclass
class KeypointsShirt:
    """From vision.findKeypoints — pixel coords converted to world."""
    sleeve_l: Point3D = field(default_factory=Point3D)
    sleeve_r: Point3D = field(default_factory=Point3D)
    shoulder_l: Point3D = field(default_factory=Point3D)
    shoulder_r: Point3D = field(default_factory=Point3D)
    hem_l: Point3D = field(default_factory=Point3D)
    hem_r: Point3D = field(default_factory=Point3D)
    a: Point3D = field(default_factory=Point3D)  # ABC fold points
    b: Point3D = field(default_factory=Point3D)
    c: Point3D = field(default_factory=Point3D)


@dataclass
class KeypointsPants:
    """From vision.findKeypointsPants."""
    waist_l: Point3D = field(default_factory=Point3D)
    waist_r: Point3D = field(default_factory=Point3D)
    crotch: Point3D = field(default_factory=Point3D)
    cuff_l: Point3D = field(default_factory=Point3D)
    cuff_r: Point3D = field(default_factory=Point3D)


@dataclass
class FoldStep:
    """One fold step — mirrors planner.js step."""
    label: str = ""
    status: str = ""
    # crease: point (px, pz), direction (dx, dz), fold_sign, axis_h
    px: float = 0.0
    pz: float = 0.0
    dx: float = 0.0
    dz: float = 0.0
    fold_sign: int = 1
    axis_h: float = 0.008
    duration: float = 1.6
    grab: Point3D = field(default_factory=Point3D)
    grab_arm: str = "L"  # 'L' | 'R'
    press: Point3D = field(default_factory=Point3D)
    press_arm: str = "R"


@dataclass
class FoldPlan:
    """Output of PlanFolds service — mirrors planner.js plan."""
    kind: str = ""  # 'shirt' | 'pants'
    owner: str = ""  # 'dad' | 'mom' | 'daughter' | 'son'
    folds: List[FoldStep] = field(default_factory=list)
    # markers for visualization: [{name, x, y, z, color, label}]
    markers: List[dict] = field(default_factory=list)


@dataclass
class PerceptionResult:
    kind: str = ""  # 'shirt' | 'pants'
    owner: str = ""
    metric: float = 0.0
    metric_name: str = ""
    keypoints_shirt: Optional[KeypointsShirt] = None
    keypoints_pants: Optional[KeypointsPants] = None
    plan: Optional[FoldPlan] = None
