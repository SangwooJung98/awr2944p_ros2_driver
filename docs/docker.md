# Humble Docker 사용법

Linux 호스트에서 공식 `ros:humble-ros-base-jammy` 이미지를 기반으로 Ubuntu 22.04 / ROS 2 Humble / Python 3.10 환경을 만듭니다. 호스트 ROS 환경과 컨테이너 ROS 환경은 분리됩니다. Ubuntu 24.04 호스트에서도 이 방법을 사용합니다.

## 준비와 빌드

[Docker Engine 공식 설치 안내](https://docs.docker.com/engine/install/ubuntu/)에 따라 Docker를 설치합니다. 실행 스크립트는 현재 계정으로 Docker에 접근할 수 없으면 sudo를 사용합니다. RViz 창에는 Linux의 X11 또는 Xwayland 세션과 호스트의 `xauth`가 필요합니다. 없다면 `sudo apt install xauth`로 설치합니다.

```bash
git clone --branch humble https://github.com/SangwooJung98/awr2944p_ros2_driver.git
cd awr2944p_ros2_driver
bash tools/docker_humble.sh build
bash tools/docker_humble.sh test
```

기본 이미지 이름은 `awr2944p:humble`입니다. 의존성 설치와 colcon 빌드는 이미지 안에서 수행됩니다. `test`는 UART·Ethernet 에뮬레이터 테스트와 설치된 launch의 합성 포인트 재생을 실행하며 실제 센서에 접근하지 않습니다.

## 센서 없이 RViz

```bash
bash tools/docker_humble.sh replay
```

합성 데이터가 10 Hz로 반복 표시됩니다. GUI 없이 실행하려면:

```bash
bash tools/docker_humble.sh exec python3 /opt/awr2944/tools/check_install.py
```

## Ethernet 측정

[배선과 펌웨어](firmware.md)를 준비하고, 호스트 센서 NIC를 `192.168.1.10/24`로 설정합니다. 보드 IP는 `192.168.1.200`입니다. NIC 설정은 [README](../README.md)의 명령을 호스트에서 실행합니다. Docker 컨테이너는 Linux host network를 사용하므로 별도 포트 매핑이나 컨테이너 IP 설정은 필요하지 않습니다.

J8 USB와 J9 Ethernet을 연결하고 보드를 리셋한 뒤, 저장소 루트에서:

```bash
export ROS_DOMAIN_ID=0 ROS_LOCALHOST_ONLY=1
RADAR_CLI_PORT=/dev/ttyACM0 bash tools/docker_humble.sh ethernet \
  auto_start:=true max_run_seconds:=0.0 connect_timeout:=20.0
```

다른 데스크톱 터미널에서도 같은 저장소로 이동한 뒤:

```bash
export ROS_DOMAIN_ID=0 ROS_LOCALHOST_ONLY=1
bash tools/docker_humble.sh rviz
```

RViz는 Humble 컨테이너 안에서 실행하며 Doppler `velocity` 색상과 Decay Time 0을 사용합니다. 현재 데스크톱의 Xauthority 쿠키를 임시 파일로 전달하고 종료 시 삭제합니다. `xhost +` 설정은 필요하지 않습니다. 기본 렌더링은 소프트웨어 OpenGL입니다.

## USB UART 측정

보드에 UART DDM 펌웨어가 있어야 합니다. Ethernet 펌웨어에서는 USB 연결만으로 UART 포인트를 받을 수 없습니다.

```bash
RADAR_CLI_PORT=/dev/ttyACM0 RADAR_DATA_PORT=/dev/ttyACM1 \
  bash tools/docker_humble.sh usb auto_start:=true max_run_seconds:=0.0
# 다른 데스크톱 터미널:
bash tools/docker_humble.sh rviz
```

호스트의 `/dev/serial/by-id/...` 경로도 `RADAR_CLI_PORT`, `RADAR_DATA_PORT`에 지정할 수 있습니다. 스크립트가 컨테이너 안의 `/dev/radar_cli`, `/dev/radar_data`로 연결합니다. 직접 `cli_port:=/dev/ttyACM0`을 전달하는 대신 호스트 장치는 위 환경변수로 선택합니다. 장치가 재연결되면 드라이버 컨테이너를 다시 실행합니다.

## 상태 확인과 정지

```bash
bash tools/docker_humble.sh exec ros2 topic hz /radar/points
bash tools/docker_humble.sh exec ros2 topic echo /radar/diagnostics
bash tools/docker_humble.sh exec ros2 service call /radar/stop std_srvs/srv/Trigger '{}'
```

서비스 응답은 요청 접수이며 diagnostics의 `state=stopped`, `stop_confirmed=True`로 RF 정지를 확인합니다. Ethernet 측정을 다시 시작할 때는 보드를 리셋한 뒤:

```bash
bash tools/docker_humble.sh exec ros2 service call /radar/start std_srvs/srv/Trigger '{}'
```

드라이버 컨테이너까지 종료하려면 실행 터미널에서 Ctrl+C 또는:

```bash
bash tools/docker_humble.sh stop
```

컨테이너 이름은 `awr2944-humble`이며 중복 실행하지 않습니다. 정상 종료는 SIGINT를 전달하고 RF 정지·시리얼 정리에 최대 35초를 줍니다. 기본 측정 제한은 60초이고 `max_run_seconds:=0.0`은 시간 제한을 해제합니다.

## cfg와 코드 수정

호스트의 `ros2_ws/src/awr2944_driver/config/`는 하드웨어 실행 컨테이너의 `/radar_config/`에 읽기 전용으로 연결됩니다. 기본 cfg 수정은 이미지 재빌드가 필요하지 않습니다. 측정을 정지하고 파일을 저장한 뒤, 보드를 리셋하고 시작합니다.

새 cfg는 해당 디렉터리에 넣고 드라이버 컨테이너를 다시 실행하며 경로를 지정합니다.

```bash
bash tools/docker_humble.sh ethernet config_file:=/radar_config/my_radar.cfg \
  auto_start:=true max_run_seconds:=0.0
```

Python 코드·launch·Docker 파일을 수정했다면 `bash tools/docker_humble.sh build`로 이미지를 다시 빌드합니다. 이미지 안의 경로는 `/opt/awr2944`이며 호스트 사용자 이름이나 clone 경로에 의존하지 않습니다.

## DDS와 권한

- Docker 환경의 기본 RMW는 `rmw_cyclonedds_cpp`입니다. 서로 다른 컨테이너 사이에서 공유 메모리를 요구하지 않으며 `/dev/shm`을 호스트와 공유하지 않습니다.
- 기본 `ROS_LOCALHOST_ONLY=1`은 같은 PC 내 통신입니다. 여러 PC 간 DDS가 필요하면 모든 참여 프로세스에 `ROS_LOCALHOST_ONLY=0`, 같은 `ROS_DOMAIN_ID`와 적절한 네트워크 설정을 적용합니다.
- 하드웨어 컨테이너는 전달한 USB 장치만 접근하며 privileged 모드는 사용하지 않습니다. 모든 Linux capability를 제거하고 Ethernet 모드에 TCP 7 바인드용 `NET_BIND_SERVICE`만 추가합니다.
- 컨테이너에는 호스트 Docker 소켓이나 홈 디렉터리를 연결하지 않습니다. 설정 디렉터리는 읽기 전용이고 로그는 컨테이너의 `/tmp/ros/log`에 있습니다. 필요하면 종료 전에 `sudo docker cp awr2944-humble:/tmp/ros/log ./radar_logs`로 가져옵니다.
