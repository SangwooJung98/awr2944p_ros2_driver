# AWR2944P ROS 2 Driver

[![ROS 2 Jazzy tests](https://github.com/SangwooJung98/awr2944p_ros2_driver/actions/workflows/test.yml/badge.svg)](https://github.com/SangwooJung98/awr2944p_ros2_driver/actions/workflows/test.yml)

TI **AWR2944PEVM / AWR2944P**의 DDM 포인트클라우드를 ROS 2 `PointCloud2`로 발행하는 커뮤니티 드라이버입니다. USB UART, TI DDM_ENET TCP, 저장된 UART 데이터 재생을 지원합니다. **TI 공식 ROS 드라이버가 아닙니다.**

[English quick start](docs/README.en.md) · [cfg 설정](docs/configuration.md) · [펌웨어·배선](docs/firmware.md) · [문제 해결](docs/troubleshooting.md) · [검증 범위](docs/validation.md)

## 지원 범위

| 항목 | 내용 |
|---|---|
| 개발 환경 | Ubuntu 24.04, ROS 2 Jazzy, Python 3.12 |
| 보드 | AWR2944PEVM / AWR2944P |
| Ethernet | SDK 4.7.2.1 AWR2x44P DDM_ENET 앱, 10 Hz 예제 |
| USB | SDK 4.6.2.1 UART DDM 전송 검증. 공개 USB cfg는 안테나 수정 후 실측 재검증 전 |
| RViz | Doppler `velocity` 색상, Decay Time `0` |
| 재생·자동 테스트 | 합성 UART 데이터 80프레임·2,400포인트. 센서 없이 실행 가능 |

Ethernet 포인트 수신은 실물 보드에서 확인했습니다. 각도·거리의 절대 정확도와 개별 보드 보정은 검증 범위에 포함되지 않습니다. AWR2944, AWR2E44P, AWR1843, IWR6843에 이 cfg를 그대로 사용하지 마세요.

## 1. 설치와 빌드

[ROS 2 Jazzy](https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html)가 설치된 **Ubuntu 24.04**에서 실행합니다. ROS 설치는 `ros-jazzy-desktop` 또는 `ros-jazzy-ros-base`를 사용하며, RViz 등 패키지 의존성은 아래 `rosdep install`이 설치합니다. RViz 창을 보려면 GUI 세션이 필요합니다. Ethernet 실행 스크립트는 systemd가 실행 중인 Ubuntu와 sudo를 사용합니다. NIC 설정 예제는 NetworkManager의 `nmcli` 기준입니다.

```bash
sudo apt update
sudo apt install git python3-colcon-common-extensions python3-rosdep
mkdir -p ~/radar_projects
cd ~/radar_projects
git clone https://github.com/SangwooJung98/awr2944p_ros2_driver.git
cd awr2944p_ros2_driver
source /opt/ros/jazzy/setup.bash
```

rosdep을 처음 사용하는 PC는 `sudo rosdep init`을 한 번 실행합니다. 이후:

```bash
rosdep update --rosdistro jazzy
rosdep install --from-paths ros2_ws/src --ignore-src -r -y --rosdistro jazzy
rosdep check --from-paths ros2_ws/src --ignore-src --rosdistro jazzy
cd ros2_ws
colcon build --symlink-install --packages-select awr2944_driver
source install/setup.bash
```

**아래 ROS 명령을 실행할 모든 새 터미널**에 같은 환경을 적용합니다. 복제 위치가 다르면 두 번째 경로를 바꿉니다.

```bash
source /opt/ros/jazzy/setup.bash
source ~/radar_projects/awr2944p_ros2_driver/ros2_ws/install/setup.bash
export ROS_DOMAIN_ID=0 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
```

`LOCALHOST`는 같은 PC에서 노드와 RViz를 실행하는 예제용입니다. 다른 PC와 DDS로 통신하려면 양쪽의 ROS 도메인과 discovery 설정을 맞춥니다.

### 다른 PC에서 사용할 때

소스·launch·cfg·RViz 설정·합성 재생 데이터는 모두 저장소에 포함됩니다. 빌드 산출물은 새 PC에서 생성합니다. 드라이버 실행에는 이 개발 PC의 파일이나 TI SDK 설치 경로가 필요하지 않습니다. TI 펌웨어 바이너리는 포함하지 않으므로, 보드에는 사용할 전송 방식에 맞는 펌웨어가 먼저 있어야 합니다. 같은 보드를 다른 PC로 옮기는 경우 펌웨어를 다시 쓸 필요는 없습니다.

| 새 PC에서 확인할 값 | 설정 방법 |
|---|---|
| 저장소 위치 | 예제의 `~/radar_projects/awr2944p_ros2_driver`를 실제 clone 경로로 변경 |
| CLI·데이터 UART | 실제 `/dev/ttyACM*` 또는 `/dev/serial/by-id/...`를 `cli_port`, `data_port`로 지정 |
| 시리얼 접근 권한 | 새 PC 사용자에게 `dialout` 권한 부여 후 재로그인 |
| 센서용 NIC | 해당 PC의 NIC 이름을 선택하고 `192.168.1.10/24` 설정 |
| 센서 네트워크 | 다른 NIC/VPN과 `192.168.1.0/24`가 겹치지 않는 환경, 센서에서 PC로 들어오는 TCP 7 허용 |
| ROS 터미널 | ROS와 이번 clone의 `install/setup.bash`를 source하고 같은 ROS_DOMAIN_ID 사용 |

`/dev/ttyACM0`, `/dev/ttyACM1`과 IP는 예제 기본값입니다. NIC의 MAC 주소나 보드의 USB 시리얼 번호는 코드에 고정되어 있지 않습니다. 이 안내의 검증 대상은 Ubuntu 24.04 / ROS 2 Jazzy이며 Windows·macOS·다른 ROS 배포판은 검증하지 않았습니다.

## 2. 센서 없이 RViz 확인

```bash
ros2 launch awr2944_driver replay.launch.py replay_loop:=true
```

합성 포인트가 10 Hz로 반복 표시됩니다. 실제 레이더 측정이 아닙니다. 이 예제로 ROS 설치, 메시지, 좌표축, RViz 설정을 먼저 확인할 수 있습니다.

GUI 없이 설치 파일·launch·ROS 포인트 수신을 점검하려면 저장소 루트에서 다음을 실행합니다. 실제 센서와 통신하지 않고 별도 ROS 도메인 174에서 재생 후 자동 종료합니다.

```bash
python3 tools/check_install.py
```

## 3. 보드 연결과 USB 권한

| 연결 | 용도 |
|---|---|
| J12, 보드 규격에 맞는 12 V DC 전원 | 보드 전원 |
| J8 USB → PC | XDS110 CLI. USB 모드에서는 데이터 UART도 사용 |
| J9 Ethernet → PC의 센서 전용 NIC | Ethernet 모드의 포인트 데이터 |

QSPI 실행 모드는 **S1=XDS, J20 연결, J18·J17 미연결**입니다. 점퍼를 바꿀 때는 전원을 끕니다. 펌웨어가 준비되지 않았다면 [펌웨어 안내](docs/firmware.md)를 먼저 확인하세요.

```bash
ls -l /dev/serial/by-id/
```

이름이 `/dev/ttyACM0`, `/dev/ttyACM1`인지 직접 확인합니다. 여러 USB 장치가 있으면 번호가 달라질 수 있습니다. launch의 `cli_port`, `data_port`에 해당 보드의 `/dev/serial/by-id/...`를 지정하는 방법도 있습니다.

```bash
sudo usermod -aG dialout "$USER"
```

그룹 변경은 로그아웃·로그인 후 적용됩니다. 현재 세션에서 임시 접근이 필요하면 실제 장치 경로로 다음을 실행합니다. 재연결하면 ACL은 초기화될 수 있습니다.

```bash
sudo apt install acl
sudo setfacl -m "u:$USER:rw" /dev/ttyACM0 /dev/ttyACM1
```

## 4. Ethernet으로 실행

**J8 USB와 J9 LAN을 모두 연결**합니다. USB가 CLI 설정·시작·정지, LAN이 포인트 전송을 담당합니다.

| 장치 | 기본 주소·역할 |
|---|---|
| PC | `192.168.1.10/24`, TCP 서버 포트 `7` |
| 레이더 | `192.168.1.200`, PC로 접속하는 TCP 클라이언트 |

### 센서용 NIC 설정

```bash
ip -brief address
nmcli device status
```

추가 USB-LAN 등 **센서 전용 NIC 이름**을 골라 아래 값을 바꿉니다. 인터넷용 NIC에 적용하지 않습니다. 같은 이름의 연결이 있으면 새로 만들지 말고 기존 설정을 확인합니다.

```bash
RADAR_IF=enxYOUR_SENSOR_ADAPTER
sudo nmcli connection add type ethernet ifname "$RADAR_IF" \
  con-name awr2944-radar \
  ipv4.method manual ipv4.addresses 192.168.1.10/24 \
  ipv4.never-default yes ipv6.method disabled connection.autoconnect yes
sudo nmcli connection up awr2944-radar
ping -c 3 192.168.1.200
```

방화벽이 활성화된 PC는 센서 NIC에서 레이더가 보내는 TCP 포트 7 연결을 허용해야 합니다. `nmcli`가 없는 PC는 NetworkManager를 설치하거나 해당 PC의 네트워크 관리 도구에서 같은 고정 IP와 기본 경로 없음 설정을 적용합니다.

### 드라이버 시작

보드를 리셋한 다음, 터미널 A에서:

```bash
cd ~/radar_projects/awr2944p_ros2_driver
export ROS_DOMAIN_ID=0 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
bash tools/run_ethernet.sh auto_start:=true max_run_seconds:=0.0 \
  connect_timeout:=20.0 cli_port:=/dev/ttyACM0
```

이 스크립트는 systemd를 사용하며 sudo 인증이 필요할 수 있습니다. 드라이버는 현재 사용자로 실행하고 TCP 7번 바인드에 필요한 `CAP_NET_BIND_SERVICE`만 해당 서비스에 부여합니다. Python 실행 파일 전체의 권한은 바꾸지 않습니다. `max_run_seconds:=0.0`은 시간 제한 없는 측정입니다. 기본값은 60초입니다.

ROS 환경을 적용한 터미널 B에서 RViz를 켭니다.

```bash
rviz2 -d "$(ros2 pkg prefix --share awr2944_driver)/rviz/radar.rviz"
```

터미널 C에서 상태와 주파수를 확인할 수 있습니다.

```bash
ros2 topic echo /radar/diagnostics diagnostic_msgs/msg/DiagnosticArray
# 위 명령을 Ctrl+C로 종료한 다음:
ros2 topic hz /radar/points
```

### 정지와 재시작

```bash
ros2 service call /radar/stop std_srvs/srv/Trigger '{}'
```

`/radar/diagnostics`의 `state=stopped`, `stop_confirmed=True`를 확인합니다. 서비스 응답의 `success=true`는 요청 접수이며 완료를 뜻하지 않습니다.

**현재 TI Ethernet 앱은 연결 종료 후 자동 재접속하지 않습니다.** 다음 측정 전 **SW1/NRST를 한 번 누른 후**:

```bash
ros2 service call /radar/start std_srvs/srv/Trigger '{}'
```

프로세스 자체를 종료하려면 드라이버 터미널에서 Ctrl+C 또는:

```bash
sudo systemctl stop awr2944-ethernet
```

서비스가 이미 실행 중이면 `run_ethernet.sh`를 중복 실행하지 않습니다. 오류로 RF가 정지됐어도 프로세스는 남아 있을 수 있으므로, 리셋 후 `/radar/start`로 재개할 수 있습니다.

## 5. USB UART로 실행

보드에 **UART DDM 펌웨어**가 있어야 합니다. Ethernet 앱에서 USB 선만 연결한다고 UART 포인트가 나오지는 않습니다. 전송 방식에 맞는 펌웨어 전환은 [별도 안내](docs/firmware.md)를 따릅니다.

```bash
ros2 launch awr2944_driver usb.launch.py \
  cli_port:=/dev/ttyACM0 data_port:=/dev/ttyACM1 \
  auto_start:=true max_run_seconds:=0.0
```

CLI 115200 bps, 데이터 UART 3125000 bps를 사용합니다. USB 예제 cfg의 안테나 배열은 AWR2944P에 맞췄지만 이 수정본은 실물 보드에서 아직 재검증하지 않았습니다.

## 6. cfg 변경

기본 Ethernet cfg는 [`ethernet_4_7_2.cfg`](ros2_ws/src/awr2944_driver/config/ethernet_4_7_2.cfg)입니다. 검출 임계값, FoV, 주기와 RF 설정의 관계는 [cfg 안내](docs/configuration.md)에 정리했습니다.

같은 cfg 파일을 수정할 때는 **측정 정지 → 파일 저장 → 보드 리셋 → `/radar/start`** 순서입니다. `--symlink-install`로 빌드한 이 소스 트리에서는 cfg 수정만으로 재빌드할 필요가 없습니다. 다른 cfg 경로를 선택할 때는 드라이버 프로세스를 종료하고, 리셋 후 다음처럼 실행합니다.

```bash
cd ~/radar_projects/awr2944p_ros2_driver
bash tools/run_ethernet.sh config_file:=/absolute/path/my_radar.cfg \
  cli_port:=/dev/ttyACM0 auto_start:=true max_run_seconds:=0.0
```

## 토픽·좌표·RViz

| 토픽 | 타입·내용 |
|---|---|
| `/radar/points` | `sensor_msgs/PointCloud2`, XYZ·Doppler 등 8개 float32 필드 |
| `/radar/frame_info` | `std_msgs/String`, JSON 메타데이터 |
| `/radar/diagnostics` | `diagnostic_msgs/DiagnosticArray`, 상태·오류·정지 확인 |
| `/radar/temperature` | `sensor_msgs/Temperature`, 유효한 UART 온도 TLV가 있을 때만 |

필드 순서는 `x, y, z, velocity, snr, noise, intensity, range`입니다. 거리 m, 속도 m/s, SNR·noise dB이며 `intensity=snr`입니다. QoS는 Best Effort / Volatile / depth 5입니다.

기본 축은 **ROS X=전방, Y=왼쪽, Z=위**입니다. TI 좌표를 `(x_ros, y_ros, z_ros)=(y_ti, -x_ti, z_ti)`로 변환합니다. `coordinates:=ti`로 원본 축을 선택할 수 있습니다. 기본 frame은 `radar_link`이며, 단독 표시용 `radar_origin → radar_link` 항등 TF를 발행합니다. 로봇에 장착하면 `publish_tf:=false`로 두고 실제 장착 위치·자세의 TF를 제공합니다.

RViz 기본값은 **Decay Time 0**, **Color Transformer=Intensity**, **Channel Name=velocity**, 범위 **−2~+2 m/s**입니다. RViz의 Intensity는 숫자 필드를 색으로 바꾸는 표시기 이름입니다. 여기서는 Doppler 필드를 사용합니다.

Ethernet에는 SNR·noise·온도·센서 시간·센서 프레임 번호가 없습니다. 미제공 float 필드는 NaN입니다. 호스트 프레임 순번으로 센서 내부 프레임 누락을 판정할 수 없습니다. 타임스탬프는 완성된 패킷을 받은 호스트 시각이며 PTP 또는 센서 측정 시각이 아닙니다.

## 테스트

```bash
cd ~/radar_projects/awr2944p_ros2_driver
python3 tools/generate_sample.py --check
source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash
export ROS_DOMAIN_ID=173 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
cd ros2_ws
colcon test --packages-select awr2944_driver --event-handlers console_direct+
colcon test-result --verbose
```

테스트는 합성 데이터·PTY·localhost TCP를 사용합니다. 실제 보드 제어는 하지 않습니다. 실제 센서 검증용 `tools/verify_live_ros2.py`는 시작/정지 서비스를 호출하므로 자동 테스트와 구분합니다. [검증 범위와 한계](docs/validation.md)를 확인하세요.

## License

드라이버·도구·문서는 [Apache-2.0](LICENSE)입니다. TI SDK와 펌웨어는 TI 배포처에서 별도로 받습니다. 프로토콜과 cfg의 기준은 [TI mmWave MCU+ SDK](https://www.ti.com/tool/MMWAVE-MCUPLUS-SDK)이며, 보드 자료는 [AWR2944PEVM](https://www.ti.com/tool/AWR2944PEVM)에 있습니다. TI SDK·펌웨어에는 각 배포물의 라이선스가 적용됩니다.
