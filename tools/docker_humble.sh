#!/usr/bin/env bash
# Linux Docker runner for the Humble branch. No host ROS installation is used.
set -euo pipefail
radar_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
radar_image=${RADAR_DOCKER_IMAGE:-awr2944p:humble}
radar_mode=${1:---help}
if (( $# )); then shift; fi
case "$radar_mode" in
    --help|-h)
        printf '%s\n' \
            'Usage: bash tools/docker_humble.sh MODE [arguments...]' \
            'Modes: build, test, replay, ethernet, usb, rviz, exec, shell, stop' \
            'build: build Ubuntu 22.04 / Humble image; test: hardware-free tests' \
            'ethernet/usb: starts idle; pass auto_start:=true to start RF' \
            'replay/rviz: GUI through the current X11/Xwayland session' \
            'exec COMMAND...: run a ROS command in another container on the same domain' \
            'RADAR_CLI_PORT and RADAR_DATA_PORT select host serial devices.' \
            'Defaults: /dev/ttyACM0, /dev/ttyACM1, ROS_DOMAIN_ID=0, ROS_LOCALHOST_ONLY=1.'
        exit 0 ;;
    build|test|replay|ethernet|usb|rviz|exec|shell|stop) ;;
    *) printf 'Unknown mode: %s\n' "$radar_mode" >&2; exit 2 ;;
esac
if ! command -v docker >/dev/null; then
    printf '%s\n' 'Install Docker Engine first: https://docs.docker.com/engine/install/ubuntu/' >&2
    exit 1
fi
radar_docker=(docker)
if ! docker info >/dev/null 2>&1; then radar_docker=(sudo docker); fi
if [[ $radar_mode == build ]]; then
    "${radar_docker[@]}" build --progress=plain -f "$radar_root/docker/Dockerfile.humble" \
        -t "$radar_image" "$radar_root"
    exit
fi
if [[ $radar_mode == stop ]]; then
    "${radar_docker[@]}" stop --timeout 35 awr2944-humble
    exit
fi
radar_options=(--rm --init --network host --cap-drop ALL \
    --security-opt no-new-privileges --stop-timeout 35 \
    --env "ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-0}" \
    --env "ROS_LOCALHOST_ONLY=${ROS_LOCALHOST_ONLY:-1}")
radar_cookie=''
trap 'if [[ -n $radar_cookie ]]; then rm -f -- "$radar_cookie"; fi' EXIT
if [[ $radar_mode == replay || $radar_mode == rviz ]]; then
    if [[ -z ${DISPLAY:-} ]] || ! command -v xauth >/dev/null; then
        printf '%s\n' 'GUI requires DISPLAY and xauth in an X11/Xwayland desktop session.' >&2
        exit 1
    fi
    radar_cookie=$(mktemp /tmp/awr2944-xauth.XXXXXX)
    xauth nlist "$DISPLAY" | sed 's/^..../ffff/' | xauth -f "$radar_cookie" nmerge -
    if [[ ! -s $radar_cookie ]]; then
        printf '%s\n' 'No Xauthority cookie for DISPLAY; run from your desktop terminal.' >&2
        exit 1
    fi
    radar_options+=(--env "DISPLAY=$DISPLAY" --env XAUTHORITY=/tmp/radar.xauth \
        --env QT_X11_NO_MITSHM=1 --env LIBGL_ALWAYS_SOFTWARE=1 \
        --mount 'type=bind,src=/tmp/.X11-unix,dst=/tmp/.X11-unix,readonly' \
        --mount "type=bind,src=$radar_cookie,dst=/tmp/radar.xauth,readonly")
fi
case "$radar_mode" in
    ethernet|usb)
        radar_cli=$(readlink -f -- "${RADAR_CLI_PORT:-/dev/ttyACM0}")
        if [[ ! -c $radar_cli ]]; then printf 'CLI device missing: %s\n' "$radar_cli" >&2; exit 1; fi
        radar_options+=(--name awr2944-humble --device "$radar_cli:/dev/radar_cli:rw" \
            --mount "type=bind,src=$radar_root/ros2_ws/src/awr2944_driver/config,dst=/radar_config,readonly")
        radar_params=(rviz:=false cli_port:=/dev/radar_cli)
        if [[ $radar_mode == ethernet ]]; then
            radar_options+=(--cap-add NET_BIND_SERVICE)
            radar_params+=(config_file:=/radar_config/ethernet_4_7_2.cfg)
        else
            radar_data=$(readlink -f -- "${RADAR_DATA_PORT:-/dev/ttyACM1}")
            if [[ ! -c $radar_data ]]; then printf 'Data device missing: %s\n' "$radar_data" >&2; exit 1; fi
            radar_options+=(--device "$radar_data:/dev/radar_data:rw")
            radar_params+=(data_port:=/dev/radar_data config_file:=/radar_config/usb_4_6_2.cfg)
        fi
        radar_command=(ros2 launch awr2944_driver "$radar_mode.launch.py" "${radar_params[@]}" "$@") ;;
    test)
        radar_options+=(--env ROS_DOMAIN_ID=173 --env ROS_LOCALHOST_ONLY=1)
        radar_command=(bash -c 'set -e; python3 tools/generate_sample.py --check; cd ros2_ws; colcon test --packages-select awr2944_driver --event-handlers console_direct+; colcon test-result --verbose; cd /tmp; python3 /opt/awr2944/tools/check_install.py') ;;
    replay) radar_command=(ros2 launch awr2944_driver replay.launch.py replay_loop:=true "$@") ;;
    rviz) radar_command=(rviz2 -d /opt/awr2944/ros2_ws/install/awr2944_driver/share/awr2944_driver/rviz/radar.rviz "$@") ;;
    exec)
        if (( ! $# )); then printf '%s\n' 'exec requires a command' >&2; exit 2; fi
        radar_command=("$@") ;;
    shell)
        radar_options+=(-i)
        if [[ -t 0 && -t 1 ]]; then radar_options+=(-t); fi
        radar_command=(bash --noprofile --norc) ;;
esac
"${radar_docker[@]}" run "${radar_options[@]}" "$radar_image" "${radar_command[@]}"
