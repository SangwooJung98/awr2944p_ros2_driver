# 문제 해결

| 증상 | 확인·조치 |
|---|---|
| `/dev/ttyACM*` 접근 거부 | 실제 포트, `dialout` 그룹, 재로그인 또는 임시 ACL 확인 |
| `No mmWave CLI prompt` | 12 V, J8, S1=XDS, 실행 점퍼, CLI 포트 번호 확인 |
| `no enetStreamCfg` | UART 앱일 수 있음. AWR2x44P DDM_ENET 펌웨어 확인 |
| `Cannot assign requested address` | 해당 PC의 센서 NIC에 `192.168.1.10/24`가 있는지 확인 |
| TCP 7 바인드 `Permission denied` | `tools/run_ethernet.sh` 사용. 시스템 Python에 전역 capability를 부여하지 않음 |
| `Unit awr2944-ethernet... already exists` | 기존 프로세스가 실행 중. 리셋 후 `/radar/start`를 사용하거나 기존 서비스를 종료 |
| `Reset the board before a new Ethernet session` | SW1/NRST 리셋 후 시작 |
| `No valid point-cloud frames within data_timeout` | 3초 무수신. 케이블·NIC·펌웨어 상태 및 커널 로그 확인 |
| RViz에 점이 안 보임 | `/radar/points`, fixed frame `radar_link`, Best Effort QoS, ROS_DOMAIN_ID 확인 |
| 온도/SNR가 없음 | Ethernet 프로토콜에 없는 항목. UART TLV가 있을 때만 제공 |
| 방향·높이가 이상함 | AWR2944P 안테나 cfg, 설치 자세, ROS/TI 축 변환, 실제 TF 확인 |

## 연결을 먼저 확인

```bash
ip -brief address
nmcli device status
ip -s link show dev YOUR_SENSOR_NIC
ping -c 3 192.168.1.200
ss -tn '( sport = :7 )'
journalctl -k --since '5 minutes ago'
```

통신 설정을 확인한 뒤 센서를 리셋하고 `/radar/start`를 호출합니다. stock Ethernet 펌웨어의 새 연결에는 보드 리셋이 필요합니다.

## 화면 깜박임과 실제 수신 중단 구분

```bash
ros2 topic hz /radar/points
ros2 topic echo /radar/diagnostics diagnostic_msgs/msg/DiagnosticArray
```

위 명령은 별도 터미널에서 실행합니다. 진단의 `state`, `frames`, `invalid_packets`, `publish_queue_drops`와 수신 간격을 확인합니다. 필요하면 센서 NIC와 레이더 IP에 한정해 패킷을 캡처합니다. 실제 포인트 좌표나 환경이 포함될 수 있는 캡처를 이슈에 올리기 전 내용을 검토하세요.

RViz Decay Time 0은 최신 프레임 표시 설정입니다. 화면만으로 패킷 손실을 판정하지 않습니다. TCP와 ROS가 정상이어도 센서 내부 프레임 누락은 Ethernet 데이터의 호스트 순번만으로 확인할 수 없습니다.

## 종료와 복구

`/radar/stop` 또는 정상 프로세스 종료는 드라이버가 시작한 RF의 정지를 요청하고 확인합니다. `stop_confirmed=True`를 확인하세요. 강제 종료, USB 단절, `configure_sensor:=false` 수동 수신에서는 소프트웨어가 RF 정지를 보장할 수 없습니다. `sensorStop`은 RF 측정을 정지하며 보드 전원을 끄는 명령은 아닙니다.
