#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
CONFIG="${FOLDBOT_CONFIG:-$HOME/.config/foldbot/runtime.yaml}"
if [[ "$#" -gt 1 || ( "$#" == 1 && "$1" != --check && "$1" != --check-live ) ]]; then
    printf '%s\n' 'Usage: bash deploy/ubuntu24/run.sh [--check|--check-live]' >&2
    exit 1
fi
for required in /opt/ros/jazzy/setup.bash "$ROOT/install/setup.bash" \
                "$ROOT/.venv-jazzy/bin/activate" "$CONFIG"; do
    if [[ ! -f "$required" ]]; then
        printf 'Missing %s; follow docs/mini_pc.md first.\n' "$required" >&2
        exit 1
    fi
done
set +u
source /opt/ros/jazzy/setup.bash
source "$ROOT/install/setup.bash"
source "$ROOT/.venv-jazzy/bin/activate"
set -u
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-42}"
export ROS_AUTOMATIC_DISCOVERY_RANGE="${ROS_AUTOMATIC_DISCOVERY_RANGE:-LOCALHOST}"
export CUDA_VISIBLE_DEVICES=-1
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-4}"
export MKL_NUM_THREADS="${MKL_NUM_THREADS:-4}"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-1}"
export PYTHONUNBUFFERED=1
cd "$ROOT"
if [[ "${1:-}" == --check ]]; then
    exec "$ROOT/.venv-jazzy/bin/python" -m execution.doctor "$CONFIG"
elif [[ "${1:-}" == --check-live ]]; then
    exec "$ROOT/.venv-jazzy/bin/python" -m execution.doctor "$CONFIG" --live
fi
exec "$ROOT/.venv-jazzy/bin/python" -m execution.ros_node \
    --ros-args --params-file "$CONFIG"