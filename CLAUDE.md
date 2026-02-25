# USB HID Relay Network Controller

## 프로젝트 개요

USB HID 릴레이 장치를 TCP/UDP 네트워크 명령으로 제어하는 Python asyncio 기반 프로그램.
같은 VID/PID(16c0:05df) 장치를 여러 개 꽂으면 전부 자동 감지해서 동시에 동일하게 제어.

## 실행 환경

- **플랫폼**: DietPi (Debian Linux, ARM64)
- **실행 방식**: systemd 서비스 (`relay-controller.service`)
- **Python**: 3.x + asyncio
- **USB 장치**: HID USB Relay (VID:16c0, PID:05df)

## 파일 구조

| 파일 | 역할 |
|------|------|
| `relay_controller.py` | 메인 앱 (설정 로드, 컴포넌트 조율, 시그널 핸들링) |
| `usb_relay.py` | USB HID 다중 장치 관리자 (자동 감지, 브로드캐스트, 핫플러그) |
| `network_server.py` | TCP/UDP 서버 (명령 수신, 실행, 응답) |
| `command_parser.py` | 명령어 파싱/검증 (OPEN, CLOSE, STATUS, TOGGLE, HELP) |
| `config.yaml` | 런타임 설정 (포트, 로깅 등) |
| `requirements.txt` | Python 의존성 (pyyaml, hidapi, aiofiles) |

## 핵심 설계

### 다중 장치 관리 (`usb_relay.py`)
- `_devices: Dict[bytes, hid.device]` — HID path를 key로 열린 장치 관리
- `_device_info: Dict[bytes, dict]` — 장치별 serial, channels, state_cache
- `_monitor_loop()`: 3초마다 health check + 새 장치 스캔
- `_send_relay_command()`: 모든 열린 장치에 명령 브로드캐스트
- `get_status()`: `Dict[serial, Dict[channel, bool]]` 반환
- 실패한 장치는 즉시 제거, 새 장치는 자동 추가

### 명령어 프로토콜 (`command_parser.py`)
- `OPEN` → 모든 채널 열기 (target 생략 시 ALL)
- `CLOSE` → 모든 채널 닫기 (target 생략 시 ALL)
- `OPEN <ch>` / `CLOSE <ch>` → 특정 채널
- `STATUS` → 장치별 상태 (`[serial] CH1=OPEN,...`)
- `TOGGLE <ch>` → 첫 번째 장치 기준으로 토글 방향 결정

### 네트워크 서버 (`network_server.py`)
- TCP (기본 5000) / UDP (기본 5001) 동시 운영
- asyncio 이벤트 루프 하나에서 모두 처리

### HID 프로토콜
- Feature report 9바이트: `[0x00, state, channel, 0x00, ...]`
- ON=0xFF, OFF=0xFD
- 상태 읽기: feature report byte[7] 비트필드

## 서비스 관리

```bash
sudo systemctl restart relay-controller   # 재시작
sudo systemctl status relay-controller    # 상태
sudo journalctl -u relay-controller -f    # 로그
```

## 개발 이력

- 2026-02-16: 초기 구현 (단일 장치, Docker 배포)
- 2026-02-25: 다중 장치 동시 지원, Docker 제거, systemd 전환, 명령어 간소화
