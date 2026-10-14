"""FoldBot main behavior tree (M0 skeleton, py_trees).

Mirrors the simulation state machine:
  picking → detecting → fold (per step) → placing → done

M0: all action nodes are stubs that log and succeed; perception is mocked.
Real robot: replace stubs with ROS 2 action clients (MoveIt2, gripper, etc.).
"""
import py_trees
from bt.pick_subtree import create_pick_subtree
from bt.perceive_subtree import create_perceive_subtree
from bt.fold_subtree import create_fold_subtree
from bt.board_actions import create_board_fold_subtree
from bt.sort_subtree import create_sort_subtree
from bt.preemption import PreemptibleSubtree
from bt.replan import ReplanOnPreempt


def create_main_tree(succeed_on_attempt=1, kind="random", owner="random",
                     use_board=True, perception="mock", image_path=None,
                     px_per_m=None, model_path=None, conf=0.25,
                     preemption=False, recovery=False):
    """FoldBot main tree. Board-based folding is the primary method (v2.0):
    the arm grabs panel edges and flips — no precise fabric manipulation.
    use_board=False selects the legacy ABC direct-fold (high dexterity).
    perception="yolo" wires the trained YOLOv8n into the perceive subtree
    (needs image_path + px_per_m camera calibration); default "mock" keeps
    the canned-keypoint behavior.
    preemption=True guards the fold with PreemptibleSubtree (abort on
    request, arms park, cycle FAILS instead of sorting a half-folded
    garment). recovery=True additionally adds a bounded re-perceive /
    re-plan loop after a preempted fold (bt/replan.py): the garment is
    re-observed in its post-abort state and re-folded on the fresh plan.
    Default off: mock runs keep the exact pre-item-8 behaviour."""
    pick, _ = create_pick_subtree(succeed_on_attempt=succeed_on_attempt)
    perceive = create_perceive_subtree(kind=kind, owner=owner,
                                       perception=perception,
                                       image_path=image_path, px_per_m=px_per_m,
                                       model_path=model_path, conf=conf)
    fold = create_board_fold_subtree() if use_board else create_fold_subtree()
    sort = create_sort_subtree()
    if recovery:
        # A preempted fold earns one re-perceive + re-fold: the factories
        # rebuild fresh subtrees each attempt, so no aborted state leaks.
        # The recovery perceive re-runs with the same camera config as the
        # initial pass.
        fold = ReplanOnPreempt(
            name="ReplanOnPreempt",
            perceive_factory=lambda: create_perceive_subtree(
                kind=kind, owner=owner, perception=perception,
                image_path=image_path, px_per_m=px_per_m,
                model_path=model_path, conf=conf),
            fold_factory=(create_board_fold_subtree
                          if use_board else create_fold_subtree))
    elif preemption:
        # Guard the long fold sequence: a "preempt_request" on the blackboard
        # (operator stop / new garment) aborts it on the next tick — arms
        # park, the abort is recorded, and the tree reports FAILURE instead
        # of sorting a half-folded garment. Default off: mock runs keep the
        # exact pre-item-8 behaviour.
        fold = PreemptibleSubtree(name="PreemptibleFold", child=fold)
    root = py_trees.composites.Sequence(name="FoldBotMain", memory=True)
    root.add_children([pick, perceive, fold, sort])
    return root


def run_once(verbose=True):
    root = create_main_tree()
    tree = py_trees.trees.BehaviourTree(root)
    if verbose:
        print(py_trees.display.ascii_tree(root))
    tree.setup(timeout=5)
    while True:
        tree.tick()
        if root.status != py_trees.common.Status.RUNNING:
            break
    print(f"\nFinal status: {root.status}")
    bb = py_trees.blackboard.Client(name="report")
    bb.register_key(key="sorted_owner", access=py_trees.common.Access.READ)
    print(f"Sorted into: {getattr(bb, 'sorted_owner', '?')} bin")
    return root.status


if __name__ == "__main__":
    run_once()
