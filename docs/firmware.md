# 펌웨어와 배선

대상은 **AWR2944PEVM / AWR2944P GP EVM**입니다. 제품명에 P가 없는 AWR2944나 AWR2E44P의 보드·펌웨어·안테나 설정을 혼용하지 않습니다.

## 연결

| 단자 | 연결 |
|---|---|
| J12 | 보드 규격의 12 V DC 전원. 전원 정격·극성은 보드 가이드 확인 |
| J8 | PC USB, XDS110 CLI 및 UART 데이터 |
| J9 | PC의 센서 전용 Ethernet NIC |
| SW1/NRST | 리셋 |

Ethernet 모드도 USB CLI가 필요합니다. USB-LAN 어댑터로 추가 NIC를 사용할 수 있습니다. 실제 시험에서는 어댑터 분리·USB 프로토콜 오류가 있었으므로 허브, 전원, 포트, 케이블 접촉 상태를 확인합니다.

## 펌웨어 선택

| 모드 | 사용한 앱 |
|---|---|
| UART | SDK 4.6.2.1 AWR2x44P DDM UART 앱으로 전송 확인 |
| Ethernet | SDK 4.7.2.1 `awr2x44P_mmw_demoDDMEnet.appimage` |

[TI mmWave MCU+ SDK](https://www.ti.com/tool/MMWAVE-MCUPLUS-SDK)에서 SDK를 내려받고 해당 버전의 설치 가이드를 따릅니다. 이 저장소에는 TI SDK·펌웨어 바이너리가 포함되지 않습니다. 참고 보드 자료는 [AWR2944PEVM 제품 페이지](https://www.ti.com/tool/AWR2944PEVM)에 있습니다.

Ethernet 앱 위치:

```text
ti/demo/awr2x44P/mmw_ddm/awr2x44P_mmw_demoDDMEnet.appimage
```

## GP EVM 부팅 모드

점퍼 변경은 전원을 끈 상태에서 수행합니다. S1은 XDS 쪽입니다.

| 목적 | J20 / SOP0 | J18 / SOP1 | J17 / SOP2 |
|---|---|---|---|
| 정상 QSPI 실행 | 연결 | 미연결 | 미연결 |
| UART 플래시 모드 | 연결 | 미연결 | 연결 |

SDK의 AWR2x44P용 `uart_uniflash.py` 절차를 사용합니다. GP 보드에서 사용한 파일·위치는 다음과 같습니다. HS 등 다른 보안 변형에는 이 표를 그대로 적용하지 않습니다.

| 이미지 | 용도·위치 |
|---|---|
| `sbl_uart_uniflash.release.tiimage` | UART flash writer, RAM에서 실행 |
| `sbl_qspi.release.tiimage` | QSPI bootloader, `0x0` |
| `awr2x44P_mmw_demoDDMEnet.appimage` | DDM_ENET 앱, `0xA0000` |

부트로더 이미지는 SDK의 `tools/awr2x44P/`에서 찾을 수 있습니다. 설치된 MCU+ SDK의 `tools/boot/uart_uniflash.py --help`와 mmWave SDK 사용자 가이드 §4.2.4/§4.5에 따라 이미지 쓰기와 검증을 완료합니다. ROS 드라이버는 플래시를 수행하지 않습니다.

쓰기 완료 후 J8 USB 분리 → 12 V 전원 끄기 → J17 제거(J20만 연결) → 12 V 켜기 → SW1/NRST → J8 재연결 순서로 실행 모드로 돌아갑니다.

## 변경 시 필요한 작업

- **cfg 변경:** 재플래시 불필요. 정지·설정 저장·리셋·시작.
- **다른 PC 연결:** 보드의 실행 모드 유지. 새 PC의 ROS, 시리얼 권한, 센서 NIC를 설정.
- **Ethernet ↔ UART 포인트 전송 전환:** 전송 경로가 빌드 시 선택되는 앱이므로 호환 앱을 다시 써야 함. `enetStreamCfg 0`만으로 UART 출력으로 전환되지 않음.
- **Ethernet 측정 재시작:** stock TCP 클라이언트가 재접속하지 않으므로 세션 종료 후 보드 리셋 필요.

`version`, `help`, `queryDemoStatus`, `queryLocalIp`로 펌웨어와 상태를 확인할 수 있습니다. CLI를 여러 프로그램에서 동시에 열지 않습니다. 드라이버는 Ethernet 시작 시 `enetStreamCfg` 지원 여부를 확인하고, 포인트 연결을 받은 후 RF를 시작합니다.
