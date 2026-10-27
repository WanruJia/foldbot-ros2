"""ROS 2 task runner; importing this module does not require ROS."""
import json
import math
from pathlib import Path
import tempfile

import py_trees

from bt.main_tree import create_main_tree
from execution.camera import FreshFrameSource
from execution.ros_backend import RosBackend


def _preflight_model(model_path):
    from ultralytics import YOLO

    YOLO(model_path)


def create_node():
    """Construct the ROS runtime only in a sourced ROS 2 environment."""
    from cv_bridge import CvBridge
    from PIL import Image
    from rclpy.node import Node
    from rclpy.qos import DurabilityPolicy, QoSProfile, qos_profile_sensor_data
    from sensor_msgs.msg import Image as ImageMessage
    from std_msgs.msg import String
    from std_srvs.srv import Trigger

    class FoldBotNode(Node):
        def __init__(self):
            super().__init__("runtime", namespace="foldbot")
            defaults = {
                "model_path": "", "px_per_m": 0.0,
                "image_topic": "/camera/image_raw", "board_frame": "board",
                "primitive_action": "execute_primitive", "tick_hz": 10.0,
                "command_timeout": 60.0, "camera_timeout": 5.0,
                "max_frame_age": 1.0,
            }
            for name, value in defaults.items():
                self.declare_parameter(name, value)
            self.config = {name: self.get_parameter(name).value for name in defaults}
            for name in ("px_per_m", "tick_hz", "command_timeout",
                         "camera_timeout", "max_frame_age"):
                if not math.isfinite(self.config[name]) or self.config[name] <= 0:
                    raise ValueError(f"{name} must be finite and positive")
            if not self.config["model_path"] or not Path(self.config["model_path"]).is_file():
                raise ValueError("model_path must name your local YOLO weights")
            if not self.config["board_frame"]:
                raise ValueError("board_frame must identify a calibrated board frame")
            _preflight_model(self.config["model_path"])
            self._temporary = tempfile.TemporaryDirectory(prefix="foldbot-camera-")
            self._bridge = CvBridge()
            self.frames = FreshFrameSource(
                self._save_image, lambda: self.get_clock().now().nanoseconds,
                timeout=self.config["camera_timeout"],
                max_age=self.config["max_frame_age"])
            self.backend = RosBackend(
                self, action_name=self.config["primitive_action"],
                frame_id=self.config["board_frame"],
                timeout=self.config["command_timeout"])
            self._tree = None
            self._state = "idle"
            self._detail = ""
            self._images = self.create_subscription(
                ImageMessage, self.config["image_topic"], self.frames.receive,
                qos_profile_sensor_data)
            self._status = self.create_publisher(
                String, "status", QoSProfile(
                    depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))
            self._start_service = self.create_service(Trigger, "start", self._start)
            self._cancel_service = self.create_service(Trigger, "cancel", self._cancel)
            self._timer = self.create_timer(1.0 / self.config["tick_hz"], self._tick)
            self._publish()

        def _save_image(self, message):
            pixels = self._bridge.imgmsg_to_cv2(message, desired_encoding="rgb8")
            path = Path(self._temporary.name) / "frame.png"
            Image.fromarray(pixels).save(path)
            return str(path)

        def _start(self, request, response):
            if self._state == "running" or self.backend.fault:
                response.success = False
                response.message = ("task already running" if self._state == "running"
                                    else "motion inhibited; verify controller stop before restart")
                return response
            try:
                root = create_main_tree(
                    backend=self.backend, perception="yolo", frame_source=self.frames,
                    px_per_m=self.config["px_per_m"], model_path=self.config["model_path"])
                self._tree = py_trees.trees.BehaviourTree(root)
                self._tree.setup(timeout=5)
                py_trees.blackboard.Blackboard.set("garment_ready", False)
                py_trees.blackboard.Blackboard.set("sorted_owner", None)
                self._state, self._detail = "running", ""
                response.success, response.message = True, "task started"
            except Exception as error:
                self._state, self._detail = "failure", str(error)
                response.success, response.message = False, self._detail
            self._publish()
            return response

        def stop_task(self):
            if self._state != "running":
                return False
            self._tree.root.stop(py_trees.common.Status.INVALID)
            self._state = "cancel_requested"
            self._detail = "cancel sent; controller stop and safe parking are not confirmed"
            return True

        def _cancel(self, request, response):
            response.success = self.stop_task()
            response.message = self._detail if response.success else "no running task"
            self._publish()
            return response

        def _tick(self):
            if self._state == "running":
                try:
                    self._tree.tick()
                    status = self._tree.root.status
                    if status != py_trees.common.Status.RUNNING:
                        self._state = status.name.lower()
                except Exception as error:
                    self._tree.root.stop(py_trees.common.Status.INVALID)
                    self._state, self._detail = "failure", str(error)
            self._publish()

        def _publish(self):
            tip = self._tree.root.tip() if self._tree is not None else None
            self._status.publish(String(data=json.dumps({
                "state": self._state,
                "active_node": tip.name if tip is not None else None,
                "detail": self._detail or (tip.feedback_message if tip is not None else ""),
                "motion_inhibited": self.backend.fault,
            })))

        def destroy_node(self):
            self.stop_task()
            self.backend.client.destroy()
            self._temporary.cleanup()
            return super().destroy_node()

    return FoldBotNode()


def main(args=None):
    """Run task services and camera/action callbacks in a single executor."""
    import rclpy

    rclpy.init(args=args)
    node = None
    try:
        node = create_node()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node is not None:
            node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()