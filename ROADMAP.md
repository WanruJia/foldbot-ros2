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

1. [NEEDS HER — IN PROGRESS] Real-photo validation + fine-tune. She photographs 15-20
   garments on the real board under real light -> run `python3 -m perception.eval_real --imgdir <dir>`.
   2026-10-13: all 15 real photos received (data/real_photos/, private, never pushed).
   First eval (synthetic-only weights): 15/15 detected, 26 detections, mean conf 0.596 —
   BUT kind classification failed: all 26 predicted "shirt", pants never predicted
   (jeans got "shirt 0.94" full-frame box); mean box area 1.34M px^2 (~69% of frame).
   Synthetic 0.995 mAP50 did NOT transfer.
   Fine-tune (CPU, ultralytics, ~/workspace/venvs/foldbot): built data/yolo_real (12 train /
   3 val, GrabCut tight boxes via synth/make_real_labels.py; 6 boxes hand-corrected after
   montage review — auto-seg fails where the peach foam mat matches the tan board HSV range).
   Recipe that won: from best_synth.pt, 40 epochs mixed (48 synth + 12 real, AUTO optimizer,
   freeze backbone) then 30 epochs real-only. Old weights backed up as
   data/yolo_runs/foldbot_nano/weights/best_synth.pt (local only).
   Final eval_real on all 15: 13/15 top-1 kind accuracy (was 8/15), ZERO missed images,
   per-class pants 20 / shirt 11 (pants now predicted), mean conf 0.501,
   mean box area 0.57M px^2 (57% tighter). Remaining errors, reported honestly:
   (a) daughter_longpants_03 — black pants, HELD-OUT val garment, called shirt 0.554
   (genuine unseen-garment gap); (b) son_shortsleeve_01 — gray heather tee confused as
   pants 0.767 (color confusion). Lesson learned the hard way: one bad auto-label
   (pink shirt boxed at the wrong corner) poisoned 160 epochs of training and resisted
   90 epochs of correction — Ultralytics label .cache files must be deleted after any
   label fix, and every auto box must pass montage review before training.
   real data.
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
   2026-10-13 note: local .git was lost in a VM refresh (dir is no longer a git
   repo); pushes continue via gh.py's GitHub-API tree-push (verified remote tree
   == allowlist, 34 files, before pushing).
6. DONE 2026-10-13: Board viz (~/workspace/your_files/foldbot-board.html):
   verified + fixed reset(): it restored posAttr.array from initPos but NOT
   basePos, which bakeFold() mutates permanently — so reset-then-replay folded
   from stale baked positions (wrong geometry on the 2nd playthrough).
   reset() now copies initPos into both posAttr.array and basePos
   (vertPanel derives from initPos, stays valid). Inline scripts node --check OK;
   fix semantics spot-checked. board.html lives in goal files/, NOT the repo —
   nothing to push for it.
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
  green. Pushed dbfbdee.
- 2026-10-13: board-viz reset() fix — reset now restores basePos as well as
  posAttr.array (bakeFold() mutates basePos; without this, reset+replay folded
  from stale baked positions). board.html is goal-file only, not in the repo.
  Repo tests 66/66 pass. Pushed (local .git lost in VM refresh; push via
  gh.py API).
