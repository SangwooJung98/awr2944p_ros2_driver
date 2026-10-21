#!/usr/bin/env bash
set -e
radar_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
source /opt/ros/jazzy/setup.bash
source "$radar_root/ros2_ws/install/setup.bash"
exec "$@"
