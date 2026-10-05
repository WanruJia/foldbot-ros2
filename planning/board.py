"""Folding board geometry and board-based fold planning.

Board design (v1.0, 2026-10-05):
  - 55cm x 75cm board on a 20cm-wide center pedestal, 15-20cm tall.
  - Robot arm reaches UNDER the side panels and pushes UP to flip them.
  - Gravity assists once the panel passes vertical.
  - Side hinges have 2 slots: adult (center 25cm) / child (center 17cm).

Layout (top view, meters):
  ┌─────────────────────────────────────────┐
  │  ┌──────┬──────────────────┬──────┐     │
  │  │ left │      center      │right │ 40cm
  │  │panel │      panel       │panel │     │
  │  ├──────┴──────────────────┴──────┤     │
  │  │        bottom panel             │ 35cm
  │  └───────────────────────────────┘     │
  └─────────────────────────────────────────┘
"""

# Board dimensions (meters)
BOARD_W = 0.55
BOARD_L = 0.75
CENTER_H = 0.40          # center panel height
BOTTOM_H = 0.35          # bottom panel height
SIDE_W = 0.15            # side panel width (fixed outer)

# Hinge slots: center panel width per size class
HINGE_SLOTS = {
    "adult": 0.25,   # dad (50cm) / mom (43cm)
    "child": 0.17,   # daughter (36cm) / son (33cm)
}

# Pedestal
PEDESTAL_W = 0.20
PEDESTAL_H = 0.18   # clearance for arm underneath

# Panel names
PANEL_LEFT = "left"
PANEL_RIGHT = "right"
PANEL_BOTTOM = "bottom"


def hinge_slot_for_owner(owner):
    """Pick hinge slot from owner size class."""
    return "adult" if owner in ("dad", "mom") else "child"


def center_width(slot):
    """Center panel width for a hinge slot."""
    return HINGE_SLOTS[slot]


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

    Returns {'x', 'z', 'y'} — position under the panel edge where the
    arm makes contact, plus push direction (always +y).
    Board center = origin, board top surface at y=0.
    """
    cw = center_width(slot)
    if panel == PANEL_LEFT:
        return {"x": -(cw / 2 + SIDE_W / 2), "z": 0.0, "y": -0.05}
    if panel == PANEL_RIGHT:
        return {"x": cw / 2 + SIDE_W / 2, "z": 0.0, "y": -0.05}
    if panel == PANEL_BOTTOM:
        return {"x": 0.0, "z": CENTER_H / 2 + BOTTOM_H / 2, "y": -0.05}
    if panel == "top":
        # Top fold for pants tri-fold: arm presses from above
        return {"x": 0.0, "z": -(CENTER_H / 2 + 0.10), "y": 0.10}
    raise ValueError(f"unknown panel: {panel}")
