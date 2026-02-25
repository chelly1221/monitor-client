# USB HID Relay Network Controller

Python 기반 USB HID 릴레이 네트워크 컨트롤러. TCP/UDP로 릴레이를 원격 제어합니다.
같은 VID/PID(16c0:05df) 장치를 여러 개 연결하면 전부 자동 감지하여 동시에 제어합니다.

## 주요 기능

- **다중 장치 지원**: 같은 VID/PID의 USB 릴레이 장치를 모두 자동 감지, 동시 제어
- **핫플러그**: 장치를 꽂으면 3초 내 자동 감지, 빠지면 자동 제거
- **TCP/UDP 동시 지원**: asyncio 기반 비동기 서버
- **간단한 명령어**: `OPEN`, `CLOSE`, `STATUS` 등 평문 프로토콜
- **자동 재연결**: 장치 분리 시 자동 재스캔
- **systemd 서비스**: 부팅 시 자동 시작

## 호환 장치

- Vendor ID: `0x16c0`, Product ID: `0x05df`
- DCTTECH 호환 USB HID 릴레이 (1/2/4/8채널)

## 설치

### 시스템 의존성

```bash
sudo apt-get install libhidapi-dev libhidapi-hidraw0 libusb-1.0-0 libudev-dev
```

### Python 의존성

```bash
pip install -r requirements.txt
```

### udev 규칙 (권한)

```bash
sudo nano /etc/udev/rules.d/90-usb-relay.rules
```

내용:
```
SUBSYSTEM=="usb", ATTRS{idVendor}=="16c0", ATTRS{idProduct}=="05df", MODE="0666"
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="16c0", ATTRS{idProduct}=="05df", MODE="0666"
```

적용:
```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
```

## 설정

`config.yaml` 파일 편집:

```yaml
relay:
  # serial_number는 불필요 (모든 장치 자동 감지)
  # channels를 지정하면 모든 장치에 동일하게 적용 (미지정 시 자동 감지)
  auto_reconnect: true
  reconnect_interval: 5

network:
  tcp:
    enabled: true
    host: "0.0.0.0"
    port: 5000
  udp:
    enabled: true
    host: "0.0.0.0"
    port: 5001

logging:
  level: "INFO"
  file: "relay-controller.log"
  max_size_mb: 10
  backup_count: 3
```

## 명령어

| 명령어 | 설명 | 예시 |
|--------|------|------|
| `OPEN` | 모든 채널 열기 (활성화) | `OPEN` |
| `OPEN <ch>` | 특정 채널 열기 | `OPEN 1` |
| `CLOSE` | 모든 채널 닫기 (비활성화) | `CLOSE` |
| `CLOSE <ch>` | 특정 채널 닫기 | `CLOSE 3` |
| `STATUS` | 전체 상태 조회 | `STATUS` |
| `TOGGLE <ch>` | 특정 채널 토글 | `TOGGLE 2` |
| `HELP` | 도움말 | `HELP` |

### 응답 형식

- **성공**: `OK`
- **에러**: `ERROR: <메시지>`
- **상태** (다중 장치): `STATUS: [959BI] CH1=OPEN,CH2=CLOSED | [ABCDE] CH1=OPEN,CH2=CLOSED`

## 사용 예시

### netcat (TCP)

```bash
# 모든 채널 열기
echo "OPEN" | nc localhost 5000

# 채널 1만 열기
echo "OPEN 1" | nc localhost 5000

# 모든 채널 닫기
echo "CLOSE" | nc localhost 5000

# 상태 확인
echo "STATUS" | nc localhost 5000
```

### netcat (UDP)

```bash
# 열기
echo "OPEN" | nc -u -w1 localhost 5001

# 닫기
echo "CLOSE" | nc -u -w1 localhost 5001

# 상태
echo "STATUS" | nc -u -w1 localhost 5001
```

### Python

```python
import socket

# TCP
def send_tcp(cmd):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect(('localhost', 5000))
        s.sendall(cmd.encode() + b'\n')
        return s.recv(1024).decode().strip()

print(send_tcp("OPEN"))
print(send_tcp("STATUS"))

# UDP
def send_udp(cmd):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.sendto(cmd.encode(), ('localhost', 5001))
        resp, _ = s.recvfrom(1024)
        return resp.decode().strip()

print(send_udp("OPEN"))
```

## 서비스 관리

systemd 서비스로 부팅 시 자동 시작됩니다.

```bash
# 상태 확인
sudo systemctl status relay-controller

# 재시작
sudo systemctl restart relay-controller

# 로그 확인
sudo journalctl -u relay-controller -f

# 서비스 중지
sudo systemctl stop relay-controller

# 서비스 시작
sudo systemctl start relay-controller
```

## 트러블슈팅

### 장치를 못 찾는 경우

```bash
# USB 장치 확인
lsusb | grep 16c0

# HID 장치 확인
ls /dev/hidraw*
```

### 권한 문제

udev 규칙이 적용되었는지 확인:
```bash
cat /etc/udev/rules.d/90-usb-relay.rules
sudo udevadm control --reload-rules
sudo udevadm trigger
```

### 디버그 로그

`config.yaml`에서 로그 레벨 변경:
```yaml
logging:
  level: "DEBUG"
```

재시작:
```bash
sudo systemctl restart relay-controller
```

## 아키텍처

```
  relay_controller.py (메인)
       ├── usb_relay.py (다중 장치 관리)
       │     ├── 장치1 (serial: 959BI)
       │     ├── 장치2 (serial: ABCDE)
       │     └── ... (자동 감지)
       ├── network_server.py (TCP + UDP)
       └── command_parser.py (명령어 파싱)
```

### 파일 구성

| 파일 | 역할 |
|------|------|
| `relay_controller.py` | 메인 앱, 설정 로드, 컴포넌트 조율 |
| `usb_relay.py` | USB HID 다중 장치 관리자 |
| `network_server.py` | TCP/UDP 서버, 명령 실행 |
| `command_parser.py` | 명령어 파싱 및 검증 |
| `config.yaml` | 런타임 설정 |
| `requirements.txt` | Python 의존성 |
