#!/usr/bin/env bash
set -e
source /opt/ros/humble/setup.bash
source /opt/awr2944/ros2_ws/install/setup.bash
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp/radar-runtime-$(id -u)}"
mkdir -p "$ROS_HOME" "$ROS_LOG_DIR" "$XDG_RUNTIME_DIR" "$XDG_CACHE_HOME" "$XDG_CONFIG_HOME"
chmod 700 "$XDG_RUNTIME_DIR"
exec "$@"
