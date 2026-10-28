# ROS 2 Integration

Use ROS 2 at device and process boundaries. Keep `planning/`, contour geometry,
owner classification, and the behaviour-tree decisions as ordinary Python.
They do not need a ROS node or service per function.

## Implemented Boundaries

| Boundary | ROS API | Implementation |
| --- | --- | --- |
| Camera to perception | `sensor_msgs/Image`, sensor-data QoS | `execution/camera.py`, `execution/ros_node.py` |
| BT to robot executor | `foldbot_interfaces/action/ExecutePrimitive` | `execution/actions.py`, `execution/ros_backend.py` |
| Operator to task runner | `std_srvs/Trigger`: `/foldbot/start`, `/foldbot/cancel` | `execution/ros_node.py` |
| Task runner to monitoring | `std_msgs/String`: `/foldbot/status` (JSON, transient local) | `execution/ros_node.py` |

The runtime starts **idle**. Start runs one pick -> perceive/plan -> board fold
-> sort cycle. Repeated starts preserve the in-process bin counts, not counts
across process restarts. Status contains `state`, `active_node`, `detail`, and
`motion_inhibited`. The existing HTML dashboard is not a ROS client.

Each camera capture waits for an image with an exposure timestamp newer than
the capture request and within `max_frame_age`. The camera must publish valid
ROS timestamps using the same clock as the runtime. Missing/stale frames time
out, and image-conversion errors fail perception. RGB frames are stored in a
temporary directory and removed on normal shutdown; no training data is touched.
The existing YOLO and contour functions consume this fresh image unchanged.

All pick, board, sorting, and optional legacy ABC motion primitives use the
injected backend. Mock execution remains the default for non-ROS callers.
Only a SUCCEEDED action result with `success=true` completes a motion. Grasp
verification must be backed by the controller's actual sensor observation.
Bin counts advance only after a successful release, not after an attempted place.

## Robot-Specific Server Contract

**This repository supplies the client boundary, not a configured robot driver.**
Before moving hardware, provide an action server at `/foldbot/execute_primitive`
using `foldbot_interfaces/action/ExecutePrimitive`. It should translate robot
primitives into MoveIt 2 trajectories, `control_msgs/action/FollowJointTrajectory`,
and/or `control_msgs/action/GripperCommand`, as appropriate for the actual robot.
Robot model, controllers, collision geometry, gripper limits, and calibrated
poses are not available in this repository and are not invented here.

Goal fields:

- `command`: primitive name, for example `MoveToBasket`, `CloseGripper`,
  `VerifyGrasp`, `FlipPanelUp`, `ReturnPanel`, or `StackInBin`.
- `frame_id`: configured reference frame for the physical board.
- `context_json`: structured JSON, not the mock action's human-readable log.

Context depends on `stage`:

| Stage | Context fields | Commands |
| --- | --- | --- |
| `pick` | taught basket/fold-zone operations | `MoveToBasket`, `DescendToGarment`, `CloseGripper`, `LiftSlightly`, `VerifyGrasp`, `MoveToFoldZone`, `ReleaseGarment`, `RetractArm` |
| `board` | full `board_plan`, optional `pants_shape`, hierarchical `path` | all primitives defined by `bt/board_actions.py` |
| `fold` | `fold_step`, `step_index`, hierarchical `path` | `MoveToGrab`, `CloseGripper`, `MoveToPress`, `ExecuteFold`, `ReleaseAll`, `RetractArms` |
| `sort` | `owner`, `stack_height_m` | `GraspFoldedGarment`, `MoveToOwnerBin`, `StackInBin`, `ReleaseGarment`, `RetractArm` |

For board actions, `path` disambiguates panel and sleeve sides, for example
`["BoardFoldSteps", "FlipPanel:left", "FlipPanelUp"]`. The same context accompanies
the grasp and release commands, so the server knows which object is held.
`Pause` must wait for the configured physical settling interval, not a BT tick.
Reject unknown commands, missing context, uncalibrated targets, and unsafe goals.
Return `success=false` for an unobserved/failed grasp or failed motion; do not
declare success merely because a trajectory or gripper command was submitted.

### Frames And Calibration

Use ROS TF2 in the robot executor for camera, board, robot-base, gripper, and bin
transforms. No fabricated static transforms are published by this runtime.
The planner's local coordinates use **x/z as the tabletop and y as height**.
They are not ROS xyz coordinates. A right-handed board-frame convention can map
planner `(x, y, z)` to ROS `(x, -z, y)` before the board-to-base TF transform.
Confirm the board axes against the actual installation first.

`pants_shape` contour points are image-origin coordinates scaled to meters;
`px_per_m` alone does not remove that origin or establish a board transform.
The server must apply the calibrated image-to-board mapping before treating
those points as robot targets. `frame_id` does not perform that conversion.
Use a rectified top-down camera view for the current scalar-scale perception
path. A perspective image needs calibration/rectification upstream. The model's
documented generalization and garment-orientation limits still apply.

### Cancellation And Safety

Cancel stops the **entire** BT, including pick and sort, and sends an asynchronous
cancel for its active motion. A goal accepted after cancellation is cancelled as
soon as its acceptance callback runs. The task reports `cancel_requested`, never
claims the arms are parked, and does not continue to sorting.

An uncertain stop or command timeout with an outstanding goal inhibits further
motion. Confirm the robot has stopped before restarting the runtime. Existing
mock parking/replan hooks are deliberately rejected with a hardware backend;
automatic physical recovery requires a controller-specific safety policy.
Cancellation on process shutdown is best effort. ROS cancellation is **not an
emergency stop**: use hardware safety interlocks and a controller watchdog.

## Build And Run

For the selected x86-64 Ubuntu 24.04 mini PC, use the
[automated setup and deployment workflow](mini_pc.md). The manual commands below
remain available for other supported development environments.

Use a supported ROS 2 Linux deployment environment, for example Ubuntu 24.04 with
ROS 2 Jazzy. Keep the whole repository intact: the runtime CMake package installs
the existing Python modules from the repository root.

```bash
source /opt/ros/jazzy/setup.bash
rosdep install --from-paths ros2 --ignore-src -r -y
colcon build --base-paths ros2 --symlink-install
source install/setup.bash
```

Install Ultralytics in the Python environment used by ROS before starting a
cycle, and keep trained weights local. If using a virtual environment, create
it with ROS's system Python and system-site-packages so `rclpy` and `cv_bridge`
remain available. The runtime package does not download weights or install ML
dependencies. Package manifests contain placeholder maintainer/license metadata;
set the actual project metadata before distribution.

Start the calibrated camera driver and your robot primitive server, then:

```bash
ros2 launch foldbot_runtime foldbot.launch.py \
  model_path:=/absolute/path/to/local/best.pt \
  px_per_m:=500.0 image_topic:=/camera/image_raw board_frame:=board

ros2 service call /foldbot/start std_srvs/srv/Trigger '{}'
ros2 topic echo /foldbot/status
ros2 service call /foldbot/cancel std_srvs/srv/Trigger '{}'
```

`500.0` is an example, not a calibration value to use on hardware. Nonpositive
scale, invalid timing parameters, or a missing weights file prevent startup.
YOLO loading is preflighted before accepting tasks, so a missing inference
library or unreadable weights cannot first be discovered after picking.
Preflight includes CPU inference warmup, and the same model stays cached for
later captures. Restart after replacing weights. Start requests also require a
recent camera image and discovery of the primitive action server before picking.
Additional node parameters: `tick_hz` (10), `command_timeout` (60 seconds),
`camera_timeout` (5 seconds), `max_frame_age` (1 second), `primitive_action`
(`execute_primitive`). Use `ros2 run foldbot_runtime foldbot_node --ros-args -p ...`
to set parameters not exposed by the launch file.

## Verification

```bash
python3 -m pytest -q tests/test_ros_actions.py
python3 -m pytest -q
```

The boundary tests run without ROS, including both fold paths, action lifecycle
races, failed sorting release, stale camera frames, and motion inhibition.
One optional middleware smoke test uses real ROS services and a rejecting action
server after a colcon build; it skips without ROS and mocks model preflight, not
robot motion. It does not validate inference or hardware.

Validation on the macOS checkout: 20 boundary tests pass; the middleware test is
skipped. Full-suite collection is blocked by the absent `synth` package; excluding
that file reveals three existing tests blocked by missing private YOLO weights.
The ROS node, launch file, and generated interface still require a sourced ROS 2
installation for a real colcon build and middleware/hardware integration tests.