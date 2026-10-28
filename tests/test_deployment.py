"""Mini-PC deployment configuration and fail-closed startup checks."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import yaml

from execution.doctor import load_config
from execution.ros_node import start_readiness_error, validate_config
from perception.yolo_perception import _detect, _load_model


ROOT = Path(__file__).resolve().parents[1]


class TestDeployment(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.weights = Path(self.directory.name) / "local.pt"
        self.weights.touch()
        self.config = {"model_path": str(self.weights), "px_per_m": 500.0}

    def test_valid_config_preserves_defaults_and_overrides(self):
        settings = validate_config({**self.config, "tick_hz": 5.0})
        self.assertEqual(settings["tick_hz"], 5.0)
        self.assertEqual(settings["camera_timeout"], 5.0)

    def test_invalid_numeric_values_are_rejected(self):
        for name in ("px_per_m", "tick_hz", "command_timeout", "camera_timeout",
                     "max_frame_age"):
            for value in (0, -1, float("nan"), float("inf"), True, "500"):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    validate_config({**self.config, name: value})

    def test_missing_model_and_empty_device_names_are_rejected(self):
        for name in ("model_path", "image_topic", "board_frame", "primitive_action"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_config({**self.config, name: " "})
        with self.assertRaises(ValueError):
            validate_config({**self.config, "model_path": "/not/a/model.pt"})

    def test_parameter_typos_and_nonboolean_clock_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown parameters"):
            validate_config({**self.config, "pixel_per_meter": 500})
        with self.assertRaises(ValueError):
            validate_config({**self.config, "use_sim_time": "false"})

    def test_loads_ros_parameter_file(self):
        path = Path(self.directory.name) / "runtime.yaml"
        path.write_text(yaml.safe_dump({
            "/foldbot/runtime": {"ros__parameters": self.config}}))
        self.assertEqual(load_config(path)["model_path"], str(self.weights))

    def test_wrong_ros_node_scope_is_rejected(self):
        path = Path(self.directory.name) / "runtime.yaml"
        for document in ([], {"wrong_node": {"ros__parameters": self.config}}):
            path.write_text(yaml.safe_dump(document))
            with self.assertRaises(ValueError):
                load_config(path)

    def test_shipped_config_cannot_enable_unconfigured_motion(self):
        with self.assertRaises(ValueError):
            load_config(ROOT / "ros2/foldbot_runtime/config/mini_pc.yaml")

    def test_start_requires_server_and_current_camera(self):
        now = 10_000_000_000
        self.assertIsNotNone(start_readiness_error(False, now, now, 1))
        for stamp in (None, 0, now - 2_000_000_000, now + 1):
            with self.subTest(stamp=stamp):
                self.assertIsNotNone(start_readiness_error(True, stamp, now, 1))
        self.assertIsNone(start_readiness_error(True, now - 100_000_000, now, 1))

    def test_setup_and_launcher_have_valid_shell_syntax(self):
        subprocess.run([
            "bash", "-n", str(ROOT / "deploy/ubuntu24/setup.sh"),
            str(ROOT / "deploy/ubuntu24/run.sh"),
        ], check=True)

    def test_cpu_inference_reuses_loaded_model(self):
        _load_model.cache_clear()
        self.addCleanup(_load_model.cache_clear)
        model = mock.Mock()
        model.predict.return_value = ["detection"]
        loader = mock.Mock(return_value=model)
        with mock.patch.dict("sys.modules", {"ultralytics": SimpleNamespace(YOLO=loader)}):
            self.assertEqual(_detect(str(self.weights), "first.png", 0.25, 416), "detection")
            self.assertEqual(_detect(str(self.weights), "next.png", 0.25, 416), "detection")
        loader.assert_called_once_with(str(self.weights.resolve()))
        model.predict.assert_called_with("next.png", conf=0.25, imgsz=416,
                                         device="cpu", verbose=False)


if __name__ == "__main__":
    unittest.main()