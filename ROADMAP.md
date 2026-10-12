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
- 2026-10-11: Yaw from bbox landed. perception.garment_yaw_in_bbox()
  segments the garment inside the YOLO bbox (border-sampled background,
  Otsu, numpy PCA as the minAreaRect long axis — no cv2 needed) and returns
  yaw in [-90, 90) matching check_placement()'s convention; bbox_to_
  placement_kp(..., yaw_deg=...) rotates the 4 placement keypoints so
  check_placement()'s keypoint-based yaw observes the real rotation.
  Returns None (falls back to yaw=0) when the crop can't be segmented
  honestly: uniform color, tiny bbox, or near-square blob. 15 new tests in
  tests/test_yolo_yaw.py, all pass; full suite green.
- 2026-10-11: pushed f65a9e5 (yaw-from-bbox + all prior code since a429b5a).
- 2026-10-12: owner-classification DECISION: real-size thresholds, NOT
  training owner classes. Rationale: only 5 real garments exist
  (dad_tee, son_tee, daughter_longsleeve, son_hoodie, daughter_pants) —
  mom has zero garments, dad-pants/son-pants are absent, so owner labels
  would memorize 5 garment identities, not generalize. Thresholds use her
  real 2026-10-05 measurements; the "needs camera calibration" side is
  already covered (yolo mode requires px_per_m, fails loudly without it).
  Owner-class training is deferred until she photographs several distinct
  garments per owner per kind (pairs with item 1's ask for more source
  garments, esp. mom's + more pants).
- 2026-10-12: threshold classifier made ambiguity-honest.
  planning/fold_planner.py: OWNER_WIDTHS prototype table (real data; son
  shirts observed 0.27-0.32 range) + OWNER_BOUNDARIES (0.33/0.345/0.39
  shirt, 0.36/0.44/0.52 pants) as the single threshold source;
  owner_margin(kind, metric) = distance to nearest decision boundary;
  classify_owner_candidates() = ranked owner list, head always equals the
  classify_owner() winner by construction. ClassifyOwnerNode now logs the
  margin and warns AMBIGUOUS below 10 mm (mom vs daughter shirts are 1 cm
  apart). KNOWN LIMIT (documented, not silently fixed): yolo-mode "shoulder
  width" is the bbox width (sleeves included) — systematically wider than
  the calibrated true shoulder width, so yolo-path owner labels are
  provisional until a sleeve-insensitive width or bbox-calibrated
  thresholds exist. 5 new tests in tests/test_owner_margin.py
  (182-width agreement sweep included); full suite green.

## Priority queue (top = next)

1. [NEEDS HER] Real-photo validation. She photographs 15-20 garments on the real
   board under real light -> run `python3 -m perception.eval_real --imgdir <dir>`.
   Look at zero-detection images first. If bad: photograph MORE source garments
   (esp. mom's + more pants), not hyperparameter tuning.
2. DONE 2026-10-10: YOLO wired into bt/perceive_subtree.py behind
   perception="yolo" (6 new tests in tests/test_yolo_wiring.py, all pass).
   yolo mode requires image_path + px_per_m; mock stays default for tests.
3. DONE 2026-10-11: Yaw from bbox. perception.garment_yaw_in_bbox()
   segments the garment contour inside the bbox (border-sampled background
   + Otsu + numpy PCA for the long axis; numpy-only, no cv2) and returns
   yaw in [-90, 90) in check_placement()'s convention. bbox_to_placement_
   kp(..., yaw_deg=...) rotates the 4 placement keypoints about the bbox
   center, feeding the real yaw into check_placement() (still keypoint-
   based). Returns None → yaw=0 fallback when segmentation is impossible
   (uniform crop, tiny bbox, near-square blob). 15 tests, all pass.
4. DONE 2026-10-12: Owner classification = real-size thresholds
   (DECISION: not owner-class training — only 5 real garments exist, mom
   has none; training would memorize identities). classify_owner() kept
   its contract (boundaries now live in OWNER_BOUNDARIES, one source);
   added owner_margin() + classify_owner_candidates() (head == winner by
   construction); ClassifyOwnerNode logs margin, warns AMBIGUOUS < 10 mm.
   Known limit: yolo-mode bbox width overestimates shoulder width
   (sleeves) — labels there are provisional, not silently rescaled.
   5 new tests in tests/test_owner_margin.py, full suite green.
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
- 2026-10-11: yaw-from-bbox (garment_yaw_in_bbox + yaw_deg on
  bbox_to_placement_kp); check_placement() now observes real garment
  rotation from the contour inside the bbox. 15 new tests, full suite
  green.
- 2026-10-12: owner-classification decision (thresholds, not owner-class
  training — 5 garments can't train owners); margin/ambiguity layer
  (owner_margin, classify_owner_candidates, OWNER_WIDTHS/OWNER_BOUNDARIES);
  ClassifyOwnerNode warns AMBIGUOUS < 10 mm. 5 new tests, full suite
  green.
