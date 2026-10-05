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
      panels: ordered list of panels to flip (each 'left' | 'right' | 'bottom')
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
    if pants_mode == "tri":
        panels = [PANEL_BOTTOM, "top"]  # bottom third up, top third down
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
    """Arm push pose for flipping a panel (underneath, pushing up).

    Returns {'x', 'z', 'y'} — position under the panel where the
    arm makes contact, plus push direction (always +y).
    Board center = origin, board top surface at y=0.
    Middle-top fixed panel spans z in [-0.36, 0]; hinge at z=0.
    """
    if panel == PANEL_LEFT:
        return {"x": -(COL_W / 2 + COL_W / 2), "z": 0.0, "y": -0.05}
    if panel == PANEL_RIGHT:
        return {"x": COL_W / 2 + COL_W / 2, "z": 0.0, "y": -0.05}
    if panel == PANEL_BOTTOM:
        return {"x": 0.0, "z": MID_H / 2, "y": -0.05}
    if panel == "top":
        # Top fold for pants tri-fold: arm presses from above
        return {"x": 0.0, "z": -(MID_H / 2 + 0.10), "y": 0.10}
    raise ValueError(f"unknown panel: {panel}")
