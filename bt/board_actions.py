"""Board-based fold actions (M5 extension).

Replaces fabric-manipulation FoldSteps with rigid board operations:
  PlaceOnBoard: pick garment, place centered on board, align, release
  FlipPanel:    arm goes UNDER the panel, pushes UP, gravity finishes the flip
  TuckSleeve:  (long sleeves) arm nudges sleeve onto the body — no precision needed
  SideFold:    (pants) arm folds one leg over the other by the cuffs

Each FlipPanel is 3 primitives vs 6 for a fabric FoldStep, and all motions
are rigid (no deformable grasping).
"""
import py_trees

from planning.board import panel_push_pose


class MockBoardAction(py_trees.behaviour.Behaviour):
    """Base mock board primitive: RUNNING for `ticks` ticks, then SUCCESS."""

    def __init__(self, name, ticks=2, detail=""):
        super().__init__(name)
        self._ticks = ticks
        self._t = 0
        self._detail = detail

    def initialise(self):
        self._t = 0

    def update(self):
        self._t += 1
        if self._t < self._ticks:
            return py_trees.common.Status.RUNNING
        if self._detail:
            self.logger.info(f"[{self.name}] {self._detail}")
        return py_trees.common.Status.SUCCESS


def create_place_on_board_subtree(place):
    """Build the PlaceOnBoard sequence."""
    root = py_trees.composites.Sequence(name="PlaceOnBoard", memory=True)
    root.add_children([
        MockBoardAction("MoveToPick", ticks=2,
                        detail="arm → garment pick pose"),
        MockBoardAction("CloseGripper", ticks=1,
                        detail="gripper closed"),
        MockBoardAction("MoveToBoard", ticks=2,
                        detail=f"arm → board ({place['x']:.2f},{place['z']:.2f})"),
        MockBoardAction("PlaceAndAlign", ticks=2,
                        detail="place garment, align to board center"),
        MockBoardAction("OpenGripper", ticks=1,
                        detail="gripper open"),
        MockBoardAction("RetractArm", ticks=2,
                        detail="arm to home"),
    ])
    return root


def create_flip_panel_subtree(panel, slot="adult"):
    """Build the FlipPanel sequence: grab edge, flip up, pause, return down.

    v1.2: Changed from push-from-below to grab-edge (Wanru's suggestion).
    Grabbing gives full control: flip up AND return down.
    Sequence: grab edge → flip up (garment folds) → pause → return panel → release.
    """
    pose = panel_push_pose(panel, slot)
    root = py_trees.composites.Sequence(
        name=f"FlipPanel:{panel}", memory=True)
    root.add_children([
        MockBoardAction("MoveToPanelEdge", ticks=2,
                        detail=f"arm → {panel} panel edge ({pose['x']:.2f},{pose['z']:.2f})"),
        MockBoardAction("CloseGripper", ticks=1,
                        detail=f"gripper grabs {panel} panel edge"),
        MockBoardAction("FlipPanelUp", ticks=3,
                        detail=f"lift {panel} panel up and over (garment folds)"),
        MockBoardAction("Pause", ticks=1,
                        detail="let garment settle"),
        MockBoardAction("ReturnPanel", ticks=3,
                        detail=f"lower {panel} panel back down"),
        MockBoardAction("OpenGripper", ticks=1,
                        detail="gripper releases panel"),
        MockBoardAction("RetractArm", ticks=2,
                        detail="arm to home"),
    ])
    return root


def create_arm_length_fold_subtree():
    """Build the ArmLengthFold sequence (pants tri-fold second step).

    v1.3: The middle-top board panel is FIXED (video design) — there is no
    physical top panel to flip. After the bottom panel folds the lower 36cm
    up, the arm grabs the waist edge and folds the top down directly.
    Sequence: move to waist → grab → fold down → release → retract.
    """
    root = py_trees.composites.Sequence(
        name="ArmLengthFold", memory=True)
    root.add_children([
        MockBoardAction("MoveToWaistEdge", ticks=2,
                        detail="arm → garment waist edge (top)"),
        MockBoardAction("CloseGripper", ticks=1,
                        detail="gripper grabs waist edge"),
        MockBoardAction("FoldTopDown", ticks=3,
                        detail="fold top down over the folded lower part"),
        MockBoardAction("OpenGripper", ticks=1,
                        detail="gripper releases garment"),
        MockBoardAction("RetractArm", ticks=2,
                        detail="arm to home"),
    ])
    return root


def create_tuck_sleeve_subtree(side):
    """Build the TuckSleeve sequence (long sleeves): nudge sleeve inward."""
    root = py_trees.composites.Sequence(
        name=f"TuckSleeve:{side}", memory=True)
    root.add_children([
        MockBoardAction("MoveToSleeve", ticks=2,
                        detail=f"arm → {side} sleeve"),
        MockBoardAction("NudgeSleeve", ticks=2,
                        detail=f"nudge {side} sleeve onto body (no precision needed)"),
        MockBoardAction("RetractArm", ticks=2,
                        detail="arm to home"),
    ])
    return root


def create_side_fold_subtree():
    """Build the pants SideFold sequence: cuff-to-cuff leg fold."""
    root = py_trees.composites.Sequence(name="SideFold", memory=True)
    root.add_children([
        MockBoardAction("MoveToCuff", ticks=2,
                        detail="arm → left cuff"),
        MockBoardAction("CloseGripper", ticks=1,
                        detail="gripper closed on cuff"),
        MockBoardAction("FoldLegOver", ticks=3,
                        detail="fold left leg over right leg"),
        MockBoardAction("Release", ticks=1,
                        detail="gripper open"),
        MockBoardAction("RetractArm", ticks=2,
                        detail="arm to home"),
    ])
    return root


class BoardFoldIterator(py_trees.behaviour.Behaviour):
    """Read the board plan from the blackboard and run the full sequence.

    Expected blackboard keys:
      board_plan: dict from planning.board.plan_board_folds()
    """

    def __init__(self, name="BoardFoldGarment"):
        super().__init__(name)
        self._seq = None

    def initialise(self):
        bb = py_trees.blackboard.Client(name="board_fold_iter")
        bb.register_key(key="board_plan", access=py_trees.common.Access.READ)
        plan = getattr(bb, "board_plan", None)
        self._seq = py_trees.composites.Sequence(
            name="BoardFoldSteps", memory=True)
        if not plan:
            self.logger.warning("[BoardFoldGarment] no board_plan on blackboard")
            return
        slot = plan.get("slot", "adult")
        children = [create_place_on_board_subtree(plan["place"])]
        if plan.get("side_fold_first"):
            children.insert(0, create_side_fold_subtree())
        if plan.get("tuck_sleeves"):
            children.append(create_tuck_sleeve_subtree("left"))
            children.append(create_tuck_sleeve_subtree("right"))
        for panel in plan.get("panels", []):
            if panel == "arm_fold":
                children.append(create_arm_length_fold_subtree())
            else:
                children.append(create_flip_panel_subtree(panel, slot))
        for c in children:
            self._seq.add_child(c)
        self.logger.info(
            f"[BoardFoldGarment] {len(children)} steps "
            f"(slot={slot}, panels={plan.get('panels', [])})")
        self._seq.setup_with_descendants()

    def update(self):
        if self._seq is None:
            return py_trees.common.Status.FAILURE
        self._seq.tick_once()
        st = self._seq.status
        if st == py_trees.common.Status.SUCCESS:
            self.logger.info("[BoardFoldGarment] all steps done")
        return st

    def terminate(self, new_status):
        if self._seq:
            self._seq.stop(py_trees.common.Status.INVALID)


def create_board_fold_subtree():
    """Entry point: board-based fold subtree (use_board=True)."""
    return BoardFoldIterator()
