# FoldBot ROS 2 — Roadmap (board-based folding mainline)

Mainline: fold with the 75x72cm board (use_board=True default). ABC direct-fabric
folding kept as use_board=False fallback. Public repo: https://github.com/WanruJia/foldbot-ros2

## Honest status (2026-10-09)

- 2026-10-27: ROS 2 boundary adapters added: optional primitive action backend
  for pick, board/ABC folding, and sorting; fresh stamped camera frames;
  start/cancel services and JSON status topic; colcon interface/runtime packages.
  Mock execution remains the default. See docs/ros2.md. Hardware deployment
  still requires a robot-specific primitive server, calibrated camera/TF frames,
  and real ROS middleware validation; no real motion or safe parking is claimed.

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

- 2026-10-14: the sleeve-width KNOWN LIMIT (10-12) is now FIXED by
  contour measurement instead of the provisional bbox fallback:
  perception.garment_torso_width_in_bbox() (new; shares
  _segment_crop/_pca_long_axis with the refactored garment_yaw_in_bbox —
  same honesty gates, all 15 yaw tests still green) rotates foreground
  coordinates (not a mask, so nothing is clipped) to upright and returns
  the lower-quartile (0.25) row width over the mid-torso band (0.30–0.70 of the
  long-axis extent; symmetric band, so the PCA reference-end ambiguity
  does not matter) — 2026-10-14 evening run: quartile instead of median so
  sleeve flare reaching into the band no longer lifts the reading until it
  covers >3/4 of the band rows (synthetic check: old median 190px vs new
  90px on deep-flare fixture). bt ClassifyOwnerNode now prefers contour
  measurements via _owner_measure_keypoints(): shirts use torso_width_m
  from the blackboard, pants use the contour waist from pants_shape when
  present; either falls back to the bbox width and stays visibly
  provisional in the logs. 12 new tests in
  tests/test_owner_width_contour.py (synthetic sleeve-flare shirt reads
  the 90px torso, not the 200px bbox; deep-flare fixture: sleeve flare over
  ~69% of the band reads 90px, not 190px; sideways garment exercises the
  coordinate-rotation path; full yolo-tree integration: contour →
  "son" 0.18m vs bbox-fallback "dad" 0.40m). Full suite green except the
  3 pytest-only files, which need pytest installed (pre-existing env
  gap; those files were untouched). Remaining honest limits: the band
  assumes shoulder-up placement; sleeves covering more than ~3/4 of the band rows still
  read wide — the <10mm AMBIGUOUS warning stays the guard.
- 2026-10-14: pants leg-merging + waist-grab landed (perception/pants_
  shape.py, numpy-only edge/contour, no keypoints per her decision):
  inseam-gap leg split -> outer-edge grasp + midline-mirrored fold target;
  top-band waist edge -> grab endpoints. Legs=None (already folded /
  no clean gap) makes the iterator SKIP the side fold instead of folding
  air; failures degrade to generic grasps with a warning. 14 new tests;
  full suite 80/80 green.

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
7. DONE 2026-10-14: Pants pipeline — leg-merging + waist-grab via
   edge/contour (no keypoints, per her decision). New module
   perception/pants_shape.py (numpy-only): segment_garment() (border-
   sampled background + Otsu, same honest approach as garment_yaw_in_
   bbox), find_leg_split() (two-run rows from the bottom = legs; crotch
   row above; grasp = outer edge of left leg near cuffs, fold target =
   mirror across the inseam midline), find_waist_edge() (top wide band;
   endpoints = arm grab targets), analyze_pants() (bbox-crop entry point),
   pants_shape_board() (crop px -> board meters via px_per_m; frame->board
   origin offset stays with the arm's camera calibration, never invented).
   Honest skips: legs=None when no clean inseam gap is visible (already
   side-folded pants, pressed-flat blobs) — BoardFoldIterator then SKIPS
   the SideFold instead of folding air; segmentation failure degrades to
   generic grasps with a warning, never an invented split. Wired:
   DetectKeypoints (yolo pants mode) publishes "pants_shape" on the
   blackboard; create_side_fold_subtree()/create_arm_length_fold_subtree()
   take it for contour-accurate grasp details. 14 new tests in
   tests/test_pants_shape.py; full suite 80/80 green. KNOWN LIMITS
   (documented in module): assumes waist-up crop (PlaceOnBoard places it
   so); a 180-degree-rotated garment would mislabel cuffs as waist —
   garment_yaw_in_bbox() only resolves [-90, 90), so this ambiguity is
   real and left to the camera setup. Adult pants tri-fold (side fold +
   bottom panel + arm length fold) was already specified; this item
   supplied the perception behind the two arm grasps.
8. Later: INT8 quantization for edge deployment (DEFERRED while the model is
   provisional — it still memorizes her board/background; quantizing now would
   lock in a bad artifact). Grasp-retry DONE 2026-10-14 for the board
   mainline (see done log); the pick subtree's silent py_trees Retry was
   unified into RetryWithLog on 2026-10-14 (see done log).
   Task preemption DONE 2026-10-14 for the board mainline (second half, see
   done log); a re-perceive / replan loop after a preemption is still open
   (see the 2026-10-14 done-log entry — now implemented and pushed).

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
- 2026-10-13: YOLO fine-tune on her 15 real board photos (she shot them
  ~11:45–12:02 PDT, approved with '好', 12 train / 3 val, 30 epochs,
  ft → ft11 series, best = runs/detect/data/yolo_runs/foldbot_real_ft11).
  Kind classification on real photos: BEFORE — all 26 boxes 'shirt', 0/7 pants,
  avg conf 0.6; AFTER — 13/15 top-1 correct, 6/7 pants (pants conf 0.65–0.80),
  val mAP50 0.912 (P 0.615 / R 1.0, noisy on 3 val images). Remaining errors:
  daughter_longpants_03 → shirt (0.554), son_shortsleeve_01 → pants (0.767).
  HONEST CAVEAT: 15 photos still tiny; model memorizes her board/background.
  More photos with varied positions/backgrounds needed to generalize.
  Weights + data NEVER pushed (public-repo allowlist: no *.pt, no data/,
  no real clothing photos).
- 2026-10-14: pants leg-merging + waist-grab via edge/contour (item 7):
  new perception/pants_shape.py (numpy-only; leg split from two-run rows,
  waist edge from top band; honest legs=None skip + generic-grasp
  degradation), wired into DetectKeypoints (yolo pants -> "pants_shape" on
  blackboard) and BoardFoldIterator (skips SideFold when legs not visible;
  contour grasp details). 14 new tests, full suite 80/80 green. Pushed
  8d229a6 (remote tree 36 files, allowlist-clean).
- 2026-10-14: grasp-retry for the board mainline (item 8, first half): new
  bt/retry_decorator.py — RetryWithLog (honest attempt counting via
  attempts_used, per-attempt INFO logs, WARNING on give-up, optional
  on_retry hook so the real robot can re-observe between attempts; returns
  FAILURE only after max_attempts — never reports unobserved success).
  All four board grasp steps wrap their (move → close gripper) pair:
  RetryPickGrasp / RetryPanelGrasp / RetryLegGrasp / RetryWaistGrasp,
  3 attempts each. Mock path passes through on attempt 1. 8 new tests in
  tests/test_retry_decorator.py; test_board.py + test_pants_shape.py structure
  assertions updated for the new wrappers; full suite 88/88 green.
  INT8 quantization deferred until the model generalizes (provisional now);
  task preemption still open. Pushed 21fc2d3 (remote tree 38 files,
  allowlist-clean: 36 retained + retry_decorator.py + test_retry_decorator.py).
- 2026-10-14: task preemption for the board mainline (item 8, second half):
  new bt/preemption.py — PreemptibleSubtree wraps the fold subtree (opt-in
  via create_main_tree(preemption=True); default off so mock runs keep the
  exact pre-item-8 behaviour) and honours a blackboard "preempt_request"
  on the next tick: stops the running fold child, parks the arms via the
  on_park hook (mock logs; real robot commands the safe park pose), records
  preempted=True + preempt_reason (an abort is never silent), and returns
  FAILURE so the main Sequence does NOT sort a half-folded garment into a
  family bin. Honest edges: a request arriving after the fold already
  reached SUCCESS reports the real outcome and clears the stale flag (no
  leak into the next garment); a pre-start request aborts with FAILURE
  (nothing ran); initialise() resets the preemption record per garment.
  7 new tests in tests/test_preemption.py (mid-fold abort, pre-start abort,
  late-request honesty, no-preemption transparency, main-tree wiring +
  integration: preempted cycle FAILS and SortToBin never runs); full suite
  95/95 green. Pushed 601715d (remote tree 40 files, allowlist-clean).
  Still open: re-perceive / replan loop after a preemption; INT8 deferred
  until the model generalizes. (This push also syncs the 11:49 run's
  grasp-retry done-log line, whose single-file ROADMAP update had failed.)

- 2026-10-14: re-perceive / replan loop after preemption (item 8 CLOSED):
  new bt/replan.py — ReplanOnPreempt wraps each fold attempt in
  PreemptibleSubtree; on a preemption abort it re-runs the perceive
  subtree to re-observe the garment in its post-abort state and re-folds
  on the fresh plan (legs merged by the interrupted attempt read
  legs=None → SideFold skipped, never folds air). Bounded: max_replans=1
  default; genuine non-preemption fold failures are NOT retried; a failed
  re-perceive reports FAILURE honestly. Wired via
  create_main_tree(recovery=True) (preemption=True path unchanged).
  9 new tests in tests/test_replan.py incl. integration: a preempted mock
  cycle recovers and still sorts. Full suite 104/104 green. Pushed
  e590630 (remote tree 42 files, allowlist-clean, verified).
  Still open: INT8 quantization deferred until the model generalizes.

- 2026-10-14: contour-measured owner widths (item 4 follow-up, closes the
  2026-10-12 sleeve-width KNOWN LIMIT): perception.garment_torso_width_in_
  bbox() — numpy-only sleeve-insensitive torso width from the contour;
  bt _owner_measure_keypoints() prefers it (shirts) and the pants_shape
  contour waist (pants) over the bbox width, with the fallback still
  visibly provisional. 11 new tests; full suite green (13 script-runnable
  files; the 3 pytest-only files fail on missing pytest — pre-existing
  env gap, untouched). Pushed 64f5a26 (remote tree 43 files,
  allowlist-clean, verified).

- 2026-10-14: torso-width sleeve-flare robustness (item 4 follow-up):
  perception.garment_torso_width_in_bbox() now takes the 0.25-quantile
  (not the median) of the per-row band widths. On a clean torso the
  quartile equals the median (constant row widths), but sleeve flare
  reaching deep into the band no longer lifts the reading until it
  covers >3/4 of the band rows — verified on a synthetic fixture with
  flare over ~69% of the band (old median read 190px, new quartile reads
  90px). 1 new test (test_torso_width_deep_sleeve_flare); full suite
  118/118 green via the foldbot venv's pytest. Remaining honest limit:
  flare over >3/4 of the band still reads wide; the <10mm AMBIGUOUS
  margin warning in ClassifyOwnerNode stays the guard. Pushed (remote
  tree 43 files, allowlist-clean, verified).

- 2026-10-14: dashboard refresh: dashboard/progress.json was stale at
  2026-10-05 (5 log entries, all bt_nodes "stub") — brought current:
  14 daily-log entries through 10-14, 16 milestones (M0–M13 done; M14 more
  real photos [NEEDS HER]; M15 INT8 deferred), bt_nodes all ✅ 实现,
  tests 117/117. dashboard/inline.py re-embedded into index.html
  (verified JSON parses). Pushed 8e81800 (remote tree 43 files,
  allowlist-clean).

- 2026-10-15 (02:49 PDT hourly run): dashboard refresh — dashboard/progress.json
  was stale at tests 117/117 (last_run 2026-10-14) and missing the 10-14
  evening quartile-fix daily-log entry; now tests 118/118 (last_run
  2026-10-15), 15 daily_log entries, M0–M13 done / M14 photos [NEEDS HER]
  / M15 INT8 deferred, updated 2026-10-15. dashboard/inline.py re-embedded
  into index.html (verified JSON parses). Pushed 6bd107e (remote tree 43
  files, allowlist-clean, verified). Top queue item #1 still [NEEDS HER]:
  no new garment photos since 10-13; INT8 stays deferred.

- 2026-10-14: retry-decorator unification (closes the item-8 "future
  cleanup"): bt/pick_subtree.py's GraspWithRetry now uses
  bt.retry_decorator.RetryWithLog instead of the silent
  py_trees.decorators.Retry — same 3-attempt semantics, but retries are
  now attempt-counted (attempts_used), logged per attempt at INFO / on
  give-up at WARNING, and expose the on_retry re-observe hook. Both retry
  paths in the tree (pick grasp + the four board grasp pairs) are now one
  decorator. docstrings updated; tests/test_m3.py structure assertion
  updated to RetryWithLog, plus 2 new unification tests
  (test_grasp_retry_attempts_honest — attempts_used matches VerifyGrasp
  on both recovery and give-up; test_grasp_on_retry_hook — hook fires
  once before the re-attempt). Full suite 117/117 green via the foldbot
  venv's pytest. Pushed 5e57df1 (remote tree 43 files, allowlist-clean,
  verified).
