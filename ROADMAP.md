# FoldBot ROS 2 — Roadmap (board-based folding mainline)

Mainline: fold with the 75x72cm board (use_board=True default). ABC direct-fabric
folding kept as use_board=False fallback. Public repo: https://github.com/WanruJia/foldbot-ros2

## Honest status (2026-10-09)

- YOLOv8n trained 2026-10-06 on 500 composites from her 5 real garment photos:
  val mAP50 = 0.995. BUT train and val came from the SAME 5 cutouts, so this is
  memorization, not generalization. Do not trust on hardware until validated on
  fresh photos (perception/eval_real.py).
- perception/yolo_perception.py exists (bbox+kind wrapper).
- 2026-10-10: YOLO wired into bt/perceive_subtree.py behind
  perception="yolo" (DetectKeypoints → yolo_perceive + bbox_to_placement_kp
  → check_placement on blackboard; mock stays default). yolo mode needs
  image_path + px_per_m calibration; ABC fold_plan is skipped in yolo mode
  (bbox has no sleeves/a/b/c/crotch — not invented).
- Code changes since last GitHub push (a429b5a) not yet pushed.

## Priority queue (top = next)

1. [NEEDS HER] Real-photo validation. She photographs 15-20 garments on the real
   board under real light -> run `python3 -m perception.eval_real --imgdir <dir>`.
   Look at zero-detection images first. If bad: photograph MORE source garments
   (esp. mom's + more pants), not hyperparameter tuning.
2. DONE 2026-10-10: YOLO wired into bt/perceive_subtree.py behind
   perception="yolo" (6 new tests in tests/test_yolo_wiring.py, all pass).
   yolo mode requires image_path + px_per_m; mock stays default for tests.
3. Yaw from bbox: minAreaRect on the detected garment contour inside the bbox,
   feed yaw into check_placement() (currently keypoint-based).
4. Owner classification for 4 family members. Decide: real-size thresholds
   (needs camera calibration) vs training owner classes. Do not invent.
5. Push code to GitHub via gh.py. PUSH ALLOWLIST ONLY: bt/, perception/*.py,
   planning/, execution/, msgs/, tests/, docs/, dashboard/, README.md, ROADMAP.md.
   NEVER push: data/, synth/cutouts/, *.pt, __pycache__/, *.pyc, her real
   clothing photos. Repo is public.
6. Board viz (~/workspace/your_files/foldbot-board.html): verify reset()
   restores both posAttr.array and basePos.
7. Pants pipeline: leg-merging + waist-grab via edge/contour (no keypoints,
   per her decision). Adult pants: 3-fold sequence already specified.
8. Later: INT8 quantization for edge deployment; grasp-retry + task-preemption
   ideas (cf. Dyna Robotics Taku, Redwood City).

## Done log

- 2026-10-06: board-based folding mainline (use_board=True default), BoardFoldSimulator, check_placement(), pants tri-fold via arm waist-grab. Pushed a429b5a.
- 2026-10-06: YOLOv8n trained on real-clothing composites (mAP50 0.995, overfit caveat documented).
- 2026-10-07: perception/yolo_perception.py + tests (9/9 pass), perception/eval_real.py. Not yet wired/pushed.
- 2026-10-09: ROADMAP.md created; daily background-iteration cron installed per her request.
- 2026-10-10: M6 — YOLO perception wired into the BT (perception="yolo");
  mock stays default. yolo mode needs image_path + px_per_m calibration.
  All tests pass (incl. 6 new wiring tests).
