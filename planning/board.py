"""Folding board geometry and board-based fold planning.

Board design (v1.1, 2026-10-05 — per Wanru's video reference):
  - 75cm x 72cm board, three columns x 25cm wide.
  - Side columns: single 72cm panels (hinged inner edge, flip in).
  - Middle column: top 36cm FIXED (pedestal underneath),
                   bottom 36cm hinged (flips up for hem fold).
  - Robot arm reaches UNDER the panels and pushes UP to flip them.
  - Gravity assists once the panel passes vertical.

Layout (top view, meters):
  ┌─────────┬─────────┬─────────┐
  │         │  0.36   │         │
  │         │ (fixed) │         │
  │  0.25   ├─────────┤  0.25   │  0.72
  │         │  0.36   │         │
  │         │ (flips) │         │
  └─────────┴─────────┴─────────┘
     0.25      0.25      0.25
"""

# Board dimensions (meters)
BOARD_W = 0.75
BOARD_L = 0.72
COL_W = 0.25
SIDE_H = 0.72
MID_H = 0.36

# Pedestal (under middle-top fixed panel)
PEDESTAL_W = 0.20
PEDESTAL_H = 0.18   # clearance for arm underneath

# Panel names
PANEL_LEFT = "left"
PANEL_RIGHT = "right"
PANEL_BOTTOM = "bottom"  # middle-bottom flip panel


def hinge_slot_for_owner(owner):
    """Pick hinge slot from owner size class (v1.1: fixed 25cm, kept for API)."""
    return "adult" if owner in ("dad", "mom") else "child"


def center_width(slot="adult"):
    """Center column width (fixed 25cm in v1.1)."""
    return COL_W


def plan_board_folds(kind, owner, sleeve="short", pants_mode=None):
    """Plan board-based folding.

    kind: 'shirt' | 'pants'
    owner: 'dad' | 'mom' | 'daughter' | 'son'
    sleeve: 'short' | 'long' (shirts only)
    pants_mode: 'tri' | 'bi' | 'none' (pants only)

    Returns dict:
      slot: hinge slot ('adult' | 'child')
      place: {'x', 'z', 'yaw'} garment placement on board (board center = origin)
      panels: ordered list of steps — panel names ('left'|'right'|'bottom')
              or 'arm_fold' (arm does a direct length fold, no panel)
      side_fold_first: bool (pants only — arm does leg-to-leg fold before boarding)
      tuck_sleeves: bool (long sleeves — arm tucks before flipping)
    """
    slot = hinge_slot_for_owner(owner)

    if kind == "shirt":
        # Shirt centered on the center panel
        plan = {
            "slot": slot,
            "place": {"x": 0.0, "z": -0.02, "yaw": 0.0},
            "panels": [PANEL_LEFT, PANEL_RIGHT, PANEL_BOTTOM],
            "side_fold_first": False,
            "tuck_sleeves": sleeve == "long",
        }
        return plan

    # Pants: arm does side fold first, then board does length folds.
    # Folded pants placed vertically, waist at top.
    # v1.3: tri-fold second step is "arm_fold" (arm folds top down directly).
    # The middle-top panel is FIXED (video design) — no physical top panel
    # exists, so the arm does the second length fold instead of a panel.
    if pants_mode == "tri":
        panels = [PANEL_BOTTOM, "arm_fold"]  # bottom panel up, arm folds top down
    elif pants_mode == "bi":
        panels = [PANEL_BOTTOM]          # flip in half
    else:  # none — side fold only, no board needed
        panels = []

    return {
        "slot": slot,
        "place": {"x": 0.0, "z": 0.10, "yaw": 0.0},  # shifted for length
        "panels": panels,
        "side_fold_first": True,
        "tuck_sleeves": False,
    }


def panel_push_pose(panel, slot="adult"):
    """Arm grasp pose for flipping a panel (grab edge, flip, return).

    Returns {'x', 'z', 'y'} — position at the panel edge where the
    gripper grabs. Board center = origin, board top surface at y=0.
    Middle-top fixed panel spans z in [-0.36, 0]; hinge at z=0.

    v1.2: Changed from push-from-below to grab-edge (Wanru's suggestion).
    Grabbing gives full control for both flip-up and return-down.
    """
    if panel == PANEL_LEFT:
        return {"x": -(COL_W / 2 + COL_W / 2), "z": 0.0, "y": 0.02}
    if panel == PANEL_RIGHT:
        return {"x": COL_W / 2 + COL_W / 2, "z": 0.0, "y": 0.02}
    if panel == PANEL_BOTTOM:
        return {"x": 0.0, "z": MID_H / 2, "y": 0.02}
    raise ValueError(f"unknown panel: {panel}")


class BoardFoldSimulator:
    """Vertex-level board fold simulator (Python port of the viz math).

    Validates that a panel flip sequence produces the expected folded garment.
    Used for planning verification and vision-based fold checking.

    Vertices: list of {'x', 'y', 'z'}. Panel assignment is based on INITIAL
    positions and never changes (a vertex folded by the left panel is still
    'left' even after moving to the center).

    Key insight (validated in viz): side panels use ORIGINAL assignment,
    but the bottom panel folds EVERYTHING currently at z>0 (including
    side-folded sleeves now lying on the bottom panel area).
    """

    def __init__(self, vertices):
        """vertices: list of {'x','y','z'} in board coordinates (meters)."""
        self.init_pos = [dict(v) for v in vertices]
        self.pos = [dict(v) for v in vertices]
        self.hx = COL_W / 2  # 0.125
        # Assign panels by initial position
        self.panel_of = []
        for v in self.init_pos:
            ox, oz = v["x"], v["z"]
            if ox < -self.hx:
                self.panel_of.append(PANEL_LEFT)
            elif ox > self.hx:
                self.panel_of.append(PANEL_RIGHT)
            elif oz > 0:
                self.panel_of.append(PANEL_BOTTOM)
            else:
                self.panel_of.append("center")
        self.folded = {PANEL_LEFT: False, PANEL_RIGHT: False, PANEL_BOTTOM: False}

    def apply_panel_fold(self, panel):
        """Permanently apply a panel fold (panel flips 180° and returns).

        Side panels: fold vertices originally assigned to that panel.
        Bottom panel: fold ALL vertices currently at z>0 (includes side-folded parts).
        """
        if self.folded[panel]:
            return  # already folded
        hx = self.hx
        for i, v in enumerate(self.pos):
            bx, bz = v["x"], v["z"]
            wy = v.get("y", 0.002)
            should_fold = False
            if panel in (PANEL_LEFT, PANEL_RIGHT):
                should_fold = (self.panel_of[i] == panel)
            elif panel == PANEL_BOTTOM:
                # Bottom folds everything currently at z>0
                should_fold = (bz > 0.005)
            if not should_fold:
                continue
            if panel == PANEL_LEFT:
                d = -(bx + hx)
                v["x"] = -hx + d
                v["y"] = max(wy, 0.004)
            elif panel == PANEL_RIGHT:
                d = bx - hx
                v["x"] = hx - d
                v["y"] = max(wy, 0.004)
            elif panel == PANEL_BOTTOM:
                d = bz
                v["z"] = -d
                v["y"] = max(wy, 0.006)
        self.folded[panel] = True

    def apply_sequence(self, panels):
        """Apply a sequence of panel flips. Returns final vertex positions."""
        for p in panels:
            self.apply_panel_fold(p)
        return self.pos

    def bounding_box(self):
        """Current (x_min, x_max, z_min, z_max) of vertices."""
        xs = [v["x"] for v in self.pos]
        zs = [v["z"] for v in self.pos]
        return min(xs), max(xs), min(zs), max(zs)

    def is_folded_clean(self, tol=0.02):
        """Check if garment is folded to roughly the center panel size.

        After left+right+bottom folds, garment should fit within
        center column (0.25m wide) and top-middle (0.36m tall).
        """
        x_min, x_max, z_min, z_max = self.bounding_box()
        w, h = x_max - x_min, z_max - z_min
        return (w <= COL_W + tol) and (h <= MID_H + tol)
