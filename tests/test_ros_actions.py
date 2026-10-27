"""Action transport lifecycle checks without a ROS installation."""
import unittest
from concurrent.futures import Future
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
from unittest import mock

import py_trees

from execution.actions import ActionBehaviour
from execution.camera import FreshFrameSource
from execution.ros_backend import RosBackend
from bt.main_tree import create_main_tree
from bt.perceive_subtree import CaptureImage, create_perceive_subtree
from bt.sort_subtree import create_sort_subtree
from msgs.interfaces import PerceptionResult

try:
    import rclpy
    from foldbot_interfaces.action import ExecutePrimitive
    from rclpy.action import ActionServer, GoalResponse
    from rclpy.executors import SingleThreadedExecutor
    from std_srvs.srv import Trigger
    from cv_bridge import CvBridge
except ImportError:
    ROS_AVAILABLE = False
else:
    ROS_AVAILABLE = True


class FakeHandle:
    def __init__(self, accepted=True):
        self.accepted = accepted
        self.result = Future()
        self.cancels = 0

    def get_result_async(self):
        return self.result

    def cancel_goal_async(self):
        self.cancels += 1


class FakeClient:
    def __init__(self):
        self.ready = True
        self.sent = []

    def server_is_ready(self):
        return self.ready

    def send_goal_async(self, goal):
        future = Future()
        self.sent.append((goal, future))
        return future


class TestActions(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient()
        self.now = 0.0
        self.commits = []
        self.action = ActionBehaviour(
            "Move", self.client, lambda: "goal", timeout=2,
            clock=lambda: self.now,
            on_success=lambda: self.commits.append(True))

    def accept(self, accepted=True):
        handle = FakeHandle(accepted)
        self.client.sent[-1][1].set_result(handle)
        return handle

    def finish(self, handle, status=4, success=True):
        handle.result.set_result(SimpleNamespace(
            status=status, result=SimpleNamespace(success=success, message="done")))
        self.action.tick_once()

    def test_waits_for_observed_success(self):
        self.action.tick_once()
        handle = self.accept()
        self.action.tick_once()
        self.assertEqual(self.action.status, py_trees.common.Status.RUNNING)
        self.assertEqual(len(self.client.sent), 1)
        self.assertEqual(self.commits, [])
        self.finish(handle)
        self.assertEqual(self.action.status, py_trees.common.Status.SUCCESS)
        self.assertEqual(self.commits, [True])

    def test_rejection(self):
        self.action.tick_once()
        self.accept(False)
        self.action.tick_once()
        self.assertEqual(self.action.status, py_trees.common.Status.FAILURE)
        self.assertEqual(self.commits, [])

    def test_failed_result(self):
        for status, success in [(6, True), (5, True), (4, False)]:
            with self.subTest(status=status, success=success):
                self.action.stop(py_trees.common.Status.INVALID)
                self.action.tick_once()
                handle = self.accept()
                self.finish(handle, status, success)
                self.assertEqual(self.action.status, py_trees.common.Status.FAILURE)
        self.assertEqual(self.commits, [])

    def test_timeout_without_server(self):
        self.client.ready = False
        self.action.tick_once()
        self.now = 3
        self.action.tick_once()
        self.assertEqual(self.action.status, py_trees.common.Status.FAILURE)
        self.assertEqual(self.client.sent, [])

    def test_cancel_pending_goal_after_late_acceptance(self):
        self.action.tick_once()
        self.action.stop(py_trees.common.Status.INVALID)
        handle = self.accept()
        self.assertEqual(handle.cancels, 1)
        self.assertEqual(self.commits, [])

    def test_timeout_cancels_running_goal(self):
        self.action.tick_once()
        handle = self.accept()
        self.now = 3
        self.action.tick_once()
        self.assertEqual(handle.cancels, 1)
        self.assertEqual(self.action.status, py_trees.common.Status.FAILURE)

    def test_late_acceptance_does_not_replace_retry(self):
        self.action.tick_once()
        old_future = self.client.sent[-1][1]
        self.action.stop(py_trees.common.Status.INVALID)
        self.action.tick_once()
        current = self.accept()
        old_handle = FakeHandle()
        old_future.set_result(old_handle)
        self.assertEqual(old_handle.cancels, 1)
        self.finish(current)
        self.assertEqual(self.action.status, py_trees.common.Status.SUCCESS)


class RecordingBackend:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail

    def action(self, name, context, on_success=None):
        backend = self

        class RecordedAction(py_trees.behaviour.Behaviour):
            def update(self):
                payload = context() if callable(context) else context
                backend.calls.append((name, payload))
                if name == backend.fail:
                    return py_trees.common.Status.FAILURE
                if on_success is not None:
                    on_success()
                return py_trees.common.Status.SUCCESS

        return RecordedAction(name)


class TestWiring(unittest.TestCase):
    def setUp(self):
        py_trees.blackboard.Blackboard.clear()

    def run_tree(self, root):
        root.setup_with_descendants()
        for tick in range(100):
            root.tick_once()
            if root.status != py_trees.common.Status.RUNNING:
                return root.status
        self.fail("tree did not finish")

    def test_full_board_and_legacy_cycles_use_backend(self):
        for use_board in (True, False):
            with self.subTest(use_board=use_board):
                py_trees.blackboard.Blackboard.clear()
                backend = RecordingBackend()
                root = create_main_tree(kind="shirt", owner="dad",
                                        use_board=use_board, backend=backend)
                self.assertEqual(self.run_tree(root), py_trees.common.Status.SUCCESS)
                names = [name for name, context in backend.calls]
                self.assertIn("VerifyGrasp", names)
                self.assertIn("FlipPanelUp" if use_board else "ExecuteFold", names)
                self.assertIn("StackInBin", names)
                board_calls = [context for name, context in backend.calls
                               if context["stage"] == "board"]
                if use_board:
                    self.assertTrue(all("board_plan" in item and "path" in item
                                        for item in board_calls))

    def test_failure_does_not_sort(self):
        backend = RecordingBackend(fail="FlipPanelUp")
        root = create_main_tree(kind="shirt", owner="dad", backend=backend)
        self.assertEqual(self.run_tree(root), py_trees.common.Status.FAILURE)
        self.assertNotIn("StackInBin", [name for name, context in backend.calls])

    def test_failed_release_does_not_increment_bin(self):
        py_trees.blackboard.Blackboard.set(
            "perception", PerceptionResult(owner="dad"))
        backend = RecordingBackend(fail="ReleaseGarment")
        self.assertEqual(self.run_tree(create_sort_subtree(backend)),
                         py_trees.common.Status.FAILURE)
        self.assertFalse(py_trees.blackboard.Blackboard.exists("sorted_owner"))
        self.assertFalse(py_trees.blackboard.Blackboard.exists("bin_counts"))

    def test_hardware_mock_park_and_recovery_are_rejected(self):
        for option in ("preemption", "recovery"):
            with self.assertRaises(ValueError):
                create_main_tree(backend=RecordingBackend(), **{option: True})

    def test_capture_waits_for_new_frame(self):
        class Frames:
            def request(self):
                self.frame = None

            def poll(self):
                return self.frame

        frames = Frames()
        create_perceive_subtree(perception="yolo", frame_source=frames,
                                px_per_m=500)
        capture = CaptureImage(perception="yolo", frame_source=frames)
        capture.tick_once()
        self.assertEqual(capture.status, py_trees.common.Status.RUNNING)
        frames.frame = "/camera/new.png"
        capture.tick_once()
        self.assertEqual(capture.status, py_trees.common.Status.SUCCESS)
        self.assertEqual(py_trees.blackboard.Blackboard.get("frame_path"),
                         "/camera/new.png")


class TestRosTransport(unittest.TestCase):
    def test_model_preflight_loads_before_execution(self):
        from execution.ros_node import _preflight_model

        loader = mock.Mock()
        with mock.patch.dict("sys.modules", {"ultralytics": SimpleNamespace(YOLO=loader)}):
            _preflight_model("/private/weights.pt")
        loader.assert_called_once_with("/private/weights.pt")

    def test_result_transport_error_inhibits_motion(self):
        client = FakeClient()
        backend = RosBackend(None, client=client,
                             action_type=SimpleNamespace(Goal=SimpleNamespace))
        action = backend.action("MoveToBasket", {"stage": "pick"})
        action.tick_once()
        handle = FakeHandle()
        client.sent[0][1].set_result(handle)
        handle.result.set_exception(RuntimeError("connection lost"))
        action.tick_once()
        self.assertEqual(action.status, py_trees.common.Status.FAILURE)
        self.assertTrue(backend.fault)

    def test_goal_carries_structured_context_and_frame(self):
        client = FakeClient()
        backend = RosBackend(None, client=client,
                             action_type=SimpleNamespace(Goal=SimpleNamespace))
        action = backend.action("FlipPanelUp", {"path": ["FlipPanel:left"]})
        action.tick_once()
        goal = client.sent[0][0]
        self.assertEqual(goal.command, "FlipPanelUp")
        self.assertEqual(goal.frame_id, "board")
        self.assertIn("FlipPanel:left", goal.context_json)

    def test_uncertain_stop_inhibits_next_motion(self):
        client = FakeClient()
        backend = RosBackend(None, client=client,
                             action_type=SimpleNamespace(Goal=SimpleNamespace))
        first = backend.action("MoveToBasket", {"stage": "pick"})
        first.tick_once()
        first.stop(py_trees.common.Status.INVALID)
        second = backend.action("RetractArm", {"stage": "pick"})
        second.tick_once()
        self.assertTrue(backend.fault)
        self.assertEqual(second.status, py_trees.common.Status.FAILURE)
        self.assertEqual(len(client.sent), 1)


class TestFreshFrames(unittest.TestCase):
    def setUp(self):
        self.now_ns = 10_000_000_000
        self.now = 0.0
        self.saved = []
        self.source = FreshFrameSource(
            self.save, lambda: self.now_ns, timeout=2,
            clock=lambda: self.now)

    def save(self, message):
        self.saved.append(message)
        return "/fresh.png"

    def image(self, stamp_ns):
        return SimpleNamespace(header=SimpleNamespace(stamp=SimpleNamespace(
            sec=stamp_ns // 1_000_000_000, nanosec=stamp_ns % 1_000_000_000)))

    def test_ignores_pre_request_stale_and_future_frames(self):
        self.source.receive(self.image(self.now_ns))
        self.source.request()
        self.now_ns += 2_000_000_000
        for stamp in (10_000_000_000, 10_100_000_000, 13_000_000_000):
            self.source.receive(self.image(stamp))
        self.assertIsNone(self.source.poll())
        self.assertEqual(self.saved, [])
        self.source.receive(self.image(self.now_ns))
        self.assertEqual(self.source.poll(), "/fresh.png")
        self.assertEqual(len(self.saved), 1)

    def test_each_request_needs_another_frame(self):
        self.source.request()
        self.now_ns += 100_000_000
        self.source.receive(self.image(self.now_ns))
        self.source.request()
        self.assertIsNone(self.source.poll())

    def test_capture_timeout_fails_tree_node(self):
        capture = CaptureImage(perception="yolo", frame_source=self.source)
        capture.tick_once()
        self.now = 3
        capture.tick_once()
        self.assertEqual(capture.status, py_trees.common.Status.FAILURE)

    def test_conversion_failure_fails_tree_node(self):
        def broken_save(message):
            raise ValueError("unsupported image")

        self.source.save = broken_save
        capture = CaptureImage(perception="yolo", frame_source=self.source)
        capture.tick_once()
        self.now_ns += 100_000_000
        self.source.receive(self.image(self.now_ns))
        capture.tick_once()
        self.assertEqual(capture.status, py_trees.common.Status.FAILURE)


@unittest.skipUnless(ROS_AVAILABLE, "requires ROS 2 and built foldbot_interfaces")
class TestRosMiddleware(unittest.TestCase):
    def test_start_rejected_motion_and_cancel_service(self):
        from execution.ros_node import create_node

        py_trees.blackboard.Blackboard.clear()
        with tempfile.TemporaryDirectory() as directory:
            weights = Path(directory) / "test.pt"
            weights.touch()
            rclpy.init(args=["--ros-args", "-p", f"model_path:={weights}",
                            "-p", "px_per_m:=500.0"])
            runtime = None
            probe = None
            server = None
            executor = SingleThreadedExecutor()
            try:
                with mock.patch("execution.ros_node._preflight_model"):
                    runtime = create_node()
                probe = rclpy.create_node("runtime_probe", namespace="foldbot")
                server = ActionServer(
                    probe, ExecutePrimitive, "execute_primitive",
                    execute_callback=lambda goal: ExecutePrimitive.Result(),
                    goal_callback=lambda goal: GoalResponse.REJECT)
                executor.add_node(runtime)
                executor.add_node(probe)
                start = probe.create_client(Trigger, "start")
                self.assertTrue(start.wait_for_service(timeout_sec=2))
                pending = start.call_async(Trigger.Request())
                executor.spin_until_future_complete(pending, timeout_sec=3)
                self.assertTrue(pending.done())
                self.assertTrue(pending.result().success)
                deadline = time.monotonic() + 5
                while runtime._state == "running" and time.monotonic() < deadline:
                    executor.spin_once(timeout_sec=0.05)
                self.assertEqual(runtime._state, "failure")
                self.assertFalse(py_trees.blackboard.Blackboard.exists("bin_counts"))
                cancel = probe.create_client(Trigger, "cancel")
                self.assertTrue(cancel.wait_for_service(timeout_sec=2))
                pending = cancel.call_async(Trigger.Request())
                executor.spin_until_future_complete(pending, timeout_sec=3)
                self.assertTrue(pending.done())
                self.assertFalse(pending.result().success)
            finally:
                if server is not None:
                    server.destroy()
                if runtime is not None:
                    runtime.destroy_node()
                if probe is not None:
                    probe.destroy_node()
                executor.shutdown()
                rclpy.try_shutdown()


if __name__ == "__main__":
    unittest.main()