"""Tests for perception.yolo_perception — no ultralytics/torch needed.

The model-loading path is exercised via monkeypatched _detect();
the ImportError path is exercised by hiding ultralytics from sys.modules.
"""
import os
import sys
import tempfile
import unittest.mock as mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from perception.yolo_perception import (
    yolo_perceive, bbox_to_placement_kp, DEFAULT_MODEL, CLASSES,
)


def test_class_schema():
    # Must match data/yolo/foldbot.yaml (verified 2026-10-08)
    assert CLASSES == {0: "shirt", 1: "pants"}, CLASSES
    assert os.path.isfile(DEFAULT_MODEL), f"model missing: {DEFAULT_MODEL}"
    print("PASS test_class_schema")


def test_bbox_to_placement_kp_shirt():
    det = {"kind": "shirt", "conf": 0.9, "bbox": (10.0, 20.0, 110.0, 220.0)}
    kp = bbox_to_placement_kp(det, "shirt")
    assert set(kp) == {"shoulder_l", "shoulder_r", "hem_l", "hem_r"}, kp
    assert kp["shoulder_l"] == (10.0, 0.0, 20.0), kp["shoulder_l"]
    assert kp["shoulder_r"] == (110.0, 0.0, 20.0), kp["shoulder_r"]
    assert kp["hem_l"] == (10.0, 0.0, 220.0), kp["hem_l"]
    assert kp["hem_r"] == (110.0, 0.0, 220.0), kp["hem_r"]
    print("PASS test_bbox_to_placement_kp_shirt")


def test_bbox_to_placement_kp_pants():
    det = {"kind": "pants", "conf": 0.8, "bbox": (5.0, 15.0, 55.0, 215.0)}
    kp = bbox_to_placement_kp(det, "pants")
    assert set(kp) == {"waist_l", "waist_r", "cuff_l", "cuff_r"}, kp
    assert kp["waist_l"] == (5.0, 0.0, 15.0)
    assert kp["cuff_r"] == (55.0, 0.0, 215.0)
    print("PASS test_bbox_to_placement_kp_pants")


def test_bbox_to_placement_kp_scaling():
    det = {"kind": "shirt", "conf": 0.9, "bbox": (0.0, 0.0, 200.0, 400.0)}
    kp = bbox_to_placement_kp(det, "shirt", px_per_m=1000.0)
    assert kp["shoulder_r"] == (0.2, 0.0, 0.0), kp["shoulder_r"]
    assert kp["hem_r"] == (0.2, 0.0, 0.4), kp["hem_r"]
    print("PASS test_bbox_to_placement_kp_scaling")


def test_bbox_to_placement_kp_bad_kind():
    try:
        bbox_to_placement_kp({"bbox": (0, 0, 1, 1)}, "dress")
    except ValueError:
        print("PASS test_bbox_to_placement_kp_bad_kind")
        return
    raise AssertionError("expected ValueError for bad kind")


class _T:
    """Mimics a 0-d torch tensor for int()/float() conversion."""
    def __init__(self, v):
        self.v = v
    def __int__(self):
        return int(self.v)
    def __float__(self):
        return float(self.v)


def _fake_result(box_specs):
    class B:
        def __init__(self, cls, conf, xyxy):
            self.cls = _T(cls)
            self.conf = _T(conf)
            self.xyxy = [[float(v) for v in xyxy]]
    made = [B(*b) for b in box_specs]

    class R:
        names = {0: "shirt", 1: "pants"}
        boxes = made
    return R()


def test_yolo_perceive_parses_and_sorts():
    fake = _fake_result([
        (1, 0.60, (0, 0, 50, 50)),     # pants, lower conf
        (0, 0.95, (10, 20, 110, 220)),  # shirt, higher conf
        (7, 0.99, (0, 0, 9, 9)),       # unknown class id -> skipped
    ])
    with tempfile.NamedTemporaryFile(suffix=".jpg") as img, \
            mock.patch("perception.yolo_perception._detect", return_value=fake):
        dets = yolo_perceive(img.name)
    assert len(dets) == 2, dets
    assert dets[0]["kind"] == "shirt" and abs(dets[0]["conf"] - 0.95) < 1e-9
    assert dets[0]["bbox"] == (10.0, 20.0, 110.0, 220.0), dets[0]["bbox"]
    assert dets[1]["kind"] == "pants"
    print("PASS test_yolo_perceive_parses_and_sorts")


def test_yolo_perceive_missing_image():
    try:
        yolo_perceive("/nonexistent/photo.jpg")
    except FileNotFoundError:
        print("PASS test_yolo_perceive_missing_image")
        return
    raise AssertionError("expected FileNotFoundError")


def test_yolo_perceive_missing_model():
    with tempfile.NamedTemporaryFile(suffix=".jpg") as img:
        try:
            yolo_perceive(img.name, model_path="/nonexistent/best.pt")
        except FileNotFoundError as e:
            assert "model not found" in str(e)
            print("PASS test_yolo_perceive_missing_model")
            return
    raise AssertionError("expected FileNotFoundError")


def test_yolo_perceive_no_ultralytics():
    # ultralytics is not installed here; make sure the error is helpful.
    with tempfile.NamedTemporaryFile(suffix=".jpg") as img, \
            mock.patch.dict(sys.modules, {"ultralytics": None}):
        try:
            yolo_perceive(img.name)
        except ImportError as e:
            assert "pip install ultralytics" in str(e), str(e)
            print("PASS test_yolo_perceive_no_ultralytics")
            return
    raise AssertionError("expected ImportError")


if __name__ == "__main__":
    test_class_schema()
    test_bbox_to_placement_kp_shirt()
    test_bbox_to_placement_kp_pants()
    test_bbox_to_placement_kp_scaling()
    test_bbox_to_placement_kp_bad_kind()
    test_yolo_perceive_parses_and_sorts()
    test_yolo_perceive_missing_image()
    test_yolo_perceive_missing_model()
    test_yolo_perceive_no_ultralytics()
    print("ALL YOLO PERCEPTION TESTS PASS")
