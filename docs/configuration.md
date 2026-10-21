# cfg 설정

이 문서는 `AWR2944P`용 DDM 예제 기준입니다. cfg 텍스트가 승인됐다는 사실만으로 거리·각도 정확도가 검증되는 것은 아닙니다.

## 무엇을 바꿀 수 있나

| 명령 | 역할 | 확인할 조건 |
|---|---|---|
| `cfarCfg` | 거리·Doppler 검출 임계값, 윈도우·그룹화 | 낮은 임계값은 잡음·다중경로 검출도 늘릴 수 있음 |
| `aoaFovCfg` | 방위각·고각 FoV | 모델·설치 방향에 맞게 지정 |
| `frameCfg` | 프레임 구성과 주기 | chirp·처리·전송 시간이 주기 안에 들어와야 함 |
| `profileCfg` | 주파수·slope·ADC·타이밍·RX gain | RF 대역과 샘플 수집 구간, 거리/속도 trade-off |
| `chirpCfg` | chirp 구간·활성 TX | DDM 위상 주기와 함께 변경 |
| `antGeometryCfg` | 가상 안테나 배열 | 실제 AWR2944P 보드 배열에 종속 |
| `ddmPhaseShiftAntOrder` | TX별 DDM 위상 순서 | 현재 AWR2944P 예제는 `0 2 3 1` |
| `antennaCalibParams` | 안테나별 복소 보정 | 기본 `0 1` 16쌍은 중립값. 실측 보정 아님 |

## 공개 Ethernet 기본값

```text
profileCfg 0 77 36 2.5 40.00 0 0 100 1 456 12499 0 0 30
chirpCfg 0 5 0 0 0 0 0 15
frameCfg 0 5 32 0 456 100 1 0
ddmPhaseShiftAntOrder 0 2 3 1
```

- 프레임 주기는 100 ms, 목표 10 Hz입니다. 주기의 `100`을 `200`으로 바꾸면 목표는 5 Hz입니다.
- 4 TX + 2개 빈 DDM 밴드의 6-chirp 주기를 사용합니다. chirp 인덱스 0~5를 32회 반복해 프레임당 192 chirp입니다. TX 수를 바꾸면서 이 구성만 그대로 두면 안 됩니다.
- 시작 77 GHz, slope 100 MHz/µs, ramp 40.00 µs입니다. 명목 ramp 끝은 81 GHz이며, ADC 시작 2.5 µs + 456 / 12.499 MS/s ≈ 38.983 µs로 수집 구간이 ramp 안에 들어갑니다.
- SDK 4.7.2.1의 Doppler `cfarCfg`에는 마지막 `variableThresholdMode` 인수가 필요합니다. 공개 Ethernet 예제는 `0`을 사용합니다. UART 4.6 예제와 인수 수가 다릅니다.

원본 생성기 주석의 최대 거리·속도·분해능을 변경 후 성능으로 그대로 인용하지 않습니다. DDM 구성과 유효 ADC 대역을 기준으로 다시 계산하고 기준 표적으로 검증해야 합니다.

## AWR2944P와 AWR2E44P의 안테나 설정

공개 cfg는 SDK 4.7.2.1의 다음 프로파일에 있는 **안테나 배열·TX 위상 순서**를 기준으로 합니다.

```text
ti/demo/awr2x44P/mmw_ddm/profiles/awr2944P/
profile_3d_3Azim_1ElevTx_DDMA_awr2944P_highRangeRes.cfg
```

```text
antGeometryCfg 1 0 1 1 1 2 1 3 0 2 0 3 0 4 0 5 1 4 1 5 1 6 1 7 1 8 1 9 1 10 1 11 0.5 0.8
```

다른 보드의 `antGeometryCfg`, 위상 순서, 보정값은 복사하지 않습니다. 점이 출력되더라도 각도가 잘못될 수 있습니다. 현재 보정값은 Q=0, I=1이며 보드별 측정을 수행하지 않았습니다. USB 공개 cfg에도 같은 배열을 반영했으나 수정 후 UART 실측은 아직 수행하지 않았습니다.

## 적용 절차

1. `/radar/stop`으로 측정을 정지하고 diagnostics에서 정지 확인.
2. cfg를 저장.
3. USB·Ethernet 모두 SW1/NRST 리셋.
4. `/radar/start` 요청 후 diagnostics가 `running`인지 확인.

리셋된 보드에 설정할 때 현재 cfg 파일을 다시 읽습니다. UART에서 리셋 없이 정지 후 시작하면 보드의 기존 설정을 재사용하므로 수정한 cfg가 적용되지 않습니다. 경로 자체인 `config_file` 파라미터는 실행 중 변경할 수 없으므로, 다른 경로를 선택하려면 노드를 재시작합니다. 일반 설치에서 소스 cfg와 설치 cfg가 복사본이면 재빌드하거나 원하는 파일을 절대 경로로 지정합니다.

드라이버는 cfg의 `sensorStart`, `sensorStop`, `enetStreamCfg`, `configDataPort`를 직접 실행하지 않고 연결 순서에 맞게 제어합니다. Ethernet 목적지 IP는 cfg 대신 `host_ip` launch 파라미터로 지정합니다. stock 펌웨어의 포트는 TCP 7이며 `tcp_port:=7007`만으로 펌웨어 포트를 바꿀 수 없습니다.

`profileCfg`, legacy `frameCfg`, `sensorStart`가 있는 ASCII cfg를 받습니다. Advanced subframe/TDM/ADC 캡처용 설정은 이 드라이버의 지원 범위가 아닙니다.
