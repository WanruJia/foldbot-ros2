#!/usr/bin/env bash
set -eo pipefail

if [[ "${EUID}" != 0 || ! -f /opt/ros/jazzy/setup.bash ]]; then
    printf '%s\n' 'Run this validation script inside a disposable ROS Jazzy container as root.' >&2
    exit 1
fi
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD_ROOT="${FOLDBOT_BUILD_ROOT:-/tmp/foldbot-validation}"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-97}"
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
export PYTHONDONTWRITEBYTECODE=1
apt-get update
apt-get install -y python3-colcon-common-extensions python3-rosdep \
    python3-pytest python3-yaml shellcheck
source /opt/ros/jazzy/setup.bash
if [[ ! -e /etc/ros/rosdep/sources.list.d/20-default.list ]]; then
    rosdep init
fi
rosdep update --rosdistro jazzy
rosdep install --from-paths "$ROOT/ros2" --ignore-src --rosdistro jazzy -y
shellcheck --severity=warning --exclude=SC1090,SC1091 "$ROOT"/deploy/ubuntu24/*.sh
cd "$ROOT"
colcon --log-base "$BUILD_ROOT/log" build --base-paths ros2 \
    --build-base "$BUILD_ROOT/build" --install-base "$BUILD_ROOT/install" \
    --symlink-install
source "$BUILD_ROOT/install/setup.bash"
python3 -c 'from foldbot_interfaces.action import ExecutePrimitive; from cv_bridge import CvBridge'
ros2 launch foldbot_runtime foldbot.launch.py --show-args
python3 -m pytest -q -p no:cacheprovider "$ROOT/tests" \
    --ignore="$ROOT/tests/test_synth.py" \
    -k 'not test_class_schema and not test_yolo_perceive_parses_and_sorts and not test_yolo_perceive_no_ultralytics'