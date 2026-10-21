#!/usr/bin/env bash
# Start an idle ROS node with only the capability needed to bind TI TCP port 7.
# This does not change NIC addresses, flash firmware, or start RF automatically.
set -euo pipefail
radar_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
if [[ ${1:-} == --help ]]; then
    printf '%s\n' 'Usage: bash tools/run_ethernet.sh [ROS launch name:=value ...]' \
        'Requires the sensor-facing NIC to have 192.168.1.10/24 and Ethernet firmware.' \
        'Uses a transient systemd service as the current user with CAP_NET_BIND_SERVICE.' \
        'Starts idle; call /radar/start separately. RViz runs separately in your desktop.'
    exit 0
fi
if [[ ! -f "$radar_root/ros2_ws/install/setup.bash" ]]; then
    printf '%s\n' 'Build ros2_ws with colcon first.' >&2
    exit 1
fi
if [[ $(id -u) == 0 ]]; then
    printf '%s\n' 'Run this script as your normal desktop user; it invokes sudo for systemd only.' >&2
    exit 1
fi
exec sudo systemd-run --unit=awr2944-ethernet --collect --pty --wait \
    --uid="$(id -u)" --gid="$(id -g)" \
    --property=AmbientCapabilities=CAP_NET_BIND_SERVICE \
    --property=CapabilityBoundingSet=CAP_NET_BIND_SERVICE \
    --property=NoNewPrivileges=yes --property=KillSignal=SIGINT \
    --property=TimeoutStopSec=35 \
    --setenv="HOME=$HOME" --setenv="ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-0}" \
    --setenv="ROS_AUTOMATIC_DISCOVERY_RANGE=${ROS_AUTOMATIC_DISCOVERY_RANGE:-SUBNET}" \
    --working-directory="$radar_root" \
    /bin/bash "$radar_root/tools/ros_env_exec.sh" \
    ros2 launch awr2944_driver ethernet.launch.py rviz:=false "$@"
