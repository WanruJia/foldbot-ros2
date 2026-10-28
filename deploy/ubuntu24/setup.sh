#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
if [[ "$(uname -s)" != Linux || "$(uname -m)" != x86_64 ]]; then
    printf '%s\n' 'This setup requires Ubuntu 24.04 on x86-64.' >&2
    exit 1
fi
source /etc/os-release
if [[ "$ID" != ubuntu || "$VERSION_ID" != 24.04 ]]; then
    printf '%s\n' 'This setup requires Ubuntu 24.04.' >&2
    exit 1
fi
if [[ "${EUID}" == 0 ]]; then
    printf '%s\n' 'Run as your normal user, not with sudo.' >&2
    exit 1
fi
if [[ "$#" -gt 1 || ( "$#" == 1 && "$1" != --system ) ]]; then
    printf '%s\n' 'Usage: bash deploy/ubuntu24/setup.sh [--system]' >&2
    exit 1
fi
if [[ "${1:-}" == --system ]]; then
    sudo -v
    sudo apt-get update
    sudo apt-get install -y \
        build-essential cmake python3-venv python3-pip python3-rosdep \
        python3-colcon-common-extensions python3-numpy python3-pil \
        ros-jazzy-ros-base ros-jazzy-cv-bridge ros-jazzy-py-trees
fi
if [[ ! -f /opt/ros/jazzy/setup.bash ]]; then
    printf '%s\n' 'Install ROS 2 Jazzy using its official Ubuntu deb instructions first.' >&2
    printf '%s\n' 'https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html' >&2
    exit 1
fi
if [[ ! -e /etc/ros/rosdep/sources.list.d/20-default.list ]]; then
    printf '%s\n' 'Initialize rosdep once: sudo rosdep init' >&2
    exit 1
fi
set +u
source /opt/ros/jazzy/setup.bash
set -u
rosdep update --rosdistro jazzy
rosdep install --from-paths "$ROOT/ros2" --ignore-src --rosdistro jazzy -y

/usr/bin/python3 -m venv --system-site-packages "$ROOT/.venv-jazzy"
touch "$ROOT/.venv-jazzy/COLCON_IGNORE"
"$ROOT/.venv-jazzy/bin/python" -m pip install --upgrade pip
"$ROOT/.venv-jazzy/bin/python" -m pip install \
    --index-url https://download.pytorch.org/whl/cpu torch torchvision
"$ROOT/.venv-jazzy/bin/python" -m pip install -r "$ROOT/deploy/ubuntu24/requirements.txt"
"$ROOT/.venv-jazzy/bin/python" -m pip check
"$ROOT/.venv-jazzy/bin/python" -m pip freeze > "$ROOT/.venv-jazzy/requirements.lock"

cd "$ROOT"
colcon build --base-paths ros2 --symlink-install \
    --cmake-args -DPython3_EXECUTABLE=/usr/bin/python3
mkdir -p "$HOME/.config/foldbot"
if [[ ! -e "$HOME/.config/foldbot/runtime.yaml" ]]; then
    install -m 600 "$ROOT/ros2/foldbot_runtime/config/mini_pc.yaml" \
        "$HOME/.config/foldbot/runtime.yaml"
fi
printf '%s\n' 'Build complete. Set model_path and measured px_per_m in ~/.config/foldbot/runtime.yaml.'
printf '%s\n' 'Then run: bash deploy/ubuntu24/run.sh --check'