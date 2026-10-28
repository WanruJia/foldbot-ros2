# Ubuntu 24.04 Mini-PC Deployment

Target: x86-64 mini PC, Ubuntu 24.04 LTS, ROS 2 Jazzy, Ubuntu's Python 3.12,
and CPU-only inference. The runtime starts idle; a successful start request
runs one cycle. This guide does not configure a particular arm or camera driver.

## 1. Prepare Ubuntu And ROS

Install Ubuntu 24.04 and ROS 2 Jazzy using the
[official Ubuntu deb instructions](https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html).
The setup script assumes the official ROS apt repository is already configured;
it does not change apt signing keys, firewall settings, or device permissions.

Run the following on the mini PC as your normal user. Administrative commands
may ask for your password in your terminal.

```bash
sudo apt-get update
sudo apt-get install -y git python3-rosdep
if [[ ! -e /etc/ros/rosdep/sources.list.d/20-default.list ]]; then
  sudo rosdep init
fi
git clone https://github.com/WanruJia/foldbot-ros2.git "$HOME/foldbot-ros2"
cd "$HOME/foldbot-ros2"
bash deploy/ubuntu24/setup.sh --system
```

Use the existing checkout instead of cloning again if one is already present.
The optional user service assumes this exact `~/foldbot-ros2` checkout location.

Setup installs OS/ROS dependencies, resolves package dependencies with rosdep,
creates `.venv-jazzy` with system-site-packages, installs CPU PyTorch/torchvision
and the ML dependencies, and builds the colcon packages. It checks dependency
consistency and records resolved Python versions in
`.venv-jazzy/requirements.lock`. Python package installation never modifies
Ubuntu's externally managed system Python. Downloading these dependencies can
take substantial disk space and requires internet access.

NumPy is constrained below 2 for the Ubuntu `cv_bridge` ABI. OpenCV is constrained
below 4.12 to retain that NumPy compatibility. PyTorch comes from the CPU wheel
index, not a CUDA bundle. No model weights or datasets are downloaded by setup.
The lock file records the installed environment; it is not a prevalidated,
fully pinned dependency lock. Review and retain it with deployment records.

For subsequent builds, use `bash deploy/ubuntu24/setup.sh` without `--system`.
Rosdep may still need administrative permission if package dependencies changed.
After changing system ROS packages or Python dependencies, rerun diagnostics.

## 2. Configure Local Weights And Calibration

Setup creates `~/.config/foldbot/runtime.yaml` only when it does not already
exist. It never overwrites an existing deployment configuration.

Place your trusted trained weights on the mini PC, for example:

```bash
install -Dm600 /path/to/your/best.pt "$HOME/.local/share/foldbot/best.pt"
```

Set these fields in `~/.config/foldbot/runtime.yaml`:

```yaml
/foldbot/runtime:
  ros__parameters:
    model_path: /home/YOUR_USER/.local/share/foldbot/best.pt
    px_per_m: 0.0
    image_topic: /camera/image_raw
    board_frame: board
    primitive_action: /foldbot/execute_primitive
    tick_hz: 10.0
    command_timeout: 60.0
    camera_timeout: 5.0
    max_frame_age: 1.0
    use_sim_time: false
```

Replace the example path with an absolute path and `0.0` with your **measured**
pixel-per-meter calibration on the rectified board image. Zero deliberately
prevents startup. Do not copy an arbitrary example scale into a real robot.
Topics, frame names, and action names must match your drivers and executor.

The runtime checks configuration and loads and warms up YOLO on CPU before
accepting tasks. One model stays cached for subsequent captures. Restart the
runtime after replacing weights. Calibration still needs image-to-board origin
and board-to-robot transforms; scale alone is not a complete calibration.
See [the coordinate and action contract](ros2.md).

## 3. Verify Dependencies And Drivers

```bash
cd "$HOME/foldbot-ros2"
bash deploy/ubuntu24/run.sh --check
```

This checks the host, Python/ROS packages, CPU dependency choices, parameter
file, local weights, and model inference warmup. It does not send motion goals.

Start your hardware-specific camera driver and primitive action server in their
own terminals. All ROS processes on this deployment must use the same domain:

```bash
source /opt/ros/jazzy/setup.bash
source "$HOME/foldbot-ros2/install/setup.bash"
export ROS_DOMAIN_ID=42
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
```

The launcher defaults to local-only discovery. If camera/executor nodes run on
another computer, configure `ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET` consistently
on both computers and use a trusted robot network. ROS discovery is not an
authentication boundary. For devices connected by USB or a vendor controller
protocol, install the vendor's driver and narrowly scoped udev rules as needed;
do not grant blanket access to all devices.

Check live camera/executor readiness without moving anything:

```bash
bash deploy/ubuntu24/run.sh --check-live
```

The live check waits up to ten seconds for a recent, validly timestamped camera
image and discovery of the configured primitive action server. This does not
validate image quality, calibration, controller safety, or motion correctness.
The real start service also rejects requests until the camera and primitive
server are available. Each later capture still requires a new post-request
frame. These are readiness checks, not safety interlocks.

## 4. Run A Single Cycle

Start the runtime in one terminal:

```bash
bash deploy/ubuntu24/run.sh
```

In another terminal, source ROS and the workspace and set the matching domain
and discovery range as above, then:

```bash
ros2 topic echo /foldbot/status
ros2 service call /foldbot/start std_srvs/srv/Trigger '{}'
ros2 service call /foldbot/cancel std_srvs/srv/Trigger '{}'
```

Run `topic echo` in its own terminal, since it is a continuous command.
Use a hardware emergency stop and a controller watchdog. A cancellation request
does not prove the robot has physically stopped. Uncertain stops inhibit further
motion; verify controller state before manually restarting the runtime.

For another parameter file, set `FOLDBOT_CONFIG` to its absolute path before
running the launcher. Default thread limits are OMP/MKL=4 and OpenBLAS=1; override
these environment variables only after measuring latency on the actual PC.

## 5. Optional User Service

Only install this after manual diagnostics and staged hardware testing pass.
From the `~/foldbot-ros2` checkout:

```bash
install -Dm644 deploy/ubuntu24/foldbot.service \
  "$HOME/.config/systemd/user/foldbot.service"
systemctl --user daemon-reload
systemctl --user enable --now foldbot.service
journalctl --user -u foldbot.service -f
```

The service starts the runtime **idle**, never calls `/foldbot/start`, and has
`Restart=no`: it cannot automatically resume an interrupted task. It runs under
your normal account, not root. Disable it with
`systemctl --user disable --now foldbot.service`.

Optional environment overrides belong in `~/.config/foldbot/runtime.env`, one
literal `KEY=value` per line. Examples are `ROS_DOMAIN_ID=42` and
`ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET`. Systemd environment files do not expand
`$HOME`; use absolute paths for `FOLDBOT_CONFIG`. Keep the same network settings
for drivers and operator terminals. User services normally start on login;
unattended boot requires separately enabling user lingering with an administrator.

## Remaining Hardware Work

- Install and configure drivers for the actual arm, gripper, and camera.
- Implement `/foldbot/execute_primitive` against those controllers.
- Calibrate board/camera/base/bin transforms, collision geometry, panel grasp
  poses, and measured stack heights; provide sensor-backed grasp verification.
- Validate perception on fresh real photos and test cancellation and hardware
  emergency stop before attempting complete folding cycles.

No vendor robot model, fabricated calibration, or success-only motion server is
included. Those depend on the hardware selection, not on the mini PC.

## Tests And CI

The ROS Jazzy GitHub workflow builds the real packages and runs the middleware
smoke test in a ROS container. It excludes the existing unavailable synth module
and three tests requiring private weights. It does not need your photos or
weights and does not test physical hardware. Local deployment tests run with:

```bash
python3 -m pytest -q tests/test_deployment.py tests/test_ros_actions.py
```

The Ubuntu installer, colcon build, and systemd service cannot be executed
natively on macOS. Their actual deployment must be verified on the mini PC or
in the Linux CI job; shell/configuration and ROS-independent tests run locally.