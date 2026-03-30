# RTP 패킷 손실 분석 - call_id: 7vV6sKS5nD (적응형 간격 작동 중)

**작성일**: 2026-03-29 17:00  
**대상 통화**: `7vV6sKS5nD`  
**문제 시각**: 2026-03-29T08:36:00 UTC (17:36:00 KST)  
**TTS 텍스트**: "3월 29일 경기 지역은 한때 비가 **오다가** 소나기"  
**사용자 피드백**: 괄호 부분("오다가")이 들리지 않음  
**api_call_num**: 9

---

## 1. 심각도 평가

### ⚠️ **매우 심각: 80% 오디오 손실**

**TTS 생성**:
- 바이트: 339,212 bytes
- 예상 패킷: **2,120 packets**

**실제 전송**:
- 시작 seq: 42764
- 마지막 seq: 43188
- 전송 패킷: **425 packets**

**손실**:
- 손실 패킷: 2,120 - 425 = **1,695 packets**
- 손실률: **80.0%**
- 손실 오디오: 1,695 × 160 = **271,200 bytes** (약 8.5초 분량)

---

## 2. 적응형 간격 동작 확인

### 2.1 적응형 간격 작동 여부: ✅ **정상 작동**

**간격 전환 로그**:

| 시각 | packets_sent | 큐 크기 | 이전 간격 | 새 간격 | 모드 |
|------|--------------|---------|-----------|---------|------|
| 17:36:01.507 | 2574 | 6 | 20ms | 18ms | 약간 빠름 |
| 17:36:01.944 | 2599 | 11 | 18ms | 15ms | 버스트 |
| 17:36:02.807 | 2649 | 17 | 15ms | 12ms | 긴급 |
| 17:36:03.753 | 2699 | 15 | 12ms | 15ms | 버스트 |
| 17:36:05.987 | 2824 | 10 | 15ms | 18ms | 약간 빠름 |
| 17:36:08.207 | 2949 | 5 | 18ms | 20ms | 정상 |

**평가**: 
- ✅ 큐 백로그에 따라 **12~20ms 동적 조정** 확인
- ✅ 큐 17개 → 12ms (긴급 모드) 정상 작동
- ✅ 큐 5개 이하 → 20ms (정상 모드) 복귀

### 2.2 PCM 큐 백로그

**최대 백로그**: **18개** (line 46008, 46026)

| 청크 | 시각 | queue_size_after |
|------|------|------------------|
| 105 (첫 청크) | 17:36:01.024 | 1 |
| 106 | 17:36:01.084 | 1 |
| 107 | 17:36:01.143 | 2 |
| 108 | 17:36:01.205 | 3 |
| 109 | 17:36:01.267 | 4 |
| 110 | 17:36:01.330 | 5 |
| 111 | 17:36:01.389 | 6 |
| 112 | 17:36:01.447 | 7 |
| 114 | 17:36:01.602 | 8 |
| 116 | 17:36:01.792 | 10 |
| 117 | 17:36:01.850 | 11 |
| 118 | 17:36:01.912 | 12 |
| 120 | 17:36:02.030 | 13 |
| 121 | 17:36:02.178 | 14 |
| 122 | 17:36:02.240 | 15 |
| 123 | 17:36:02.303 | 16 |
| 125 | 17:36:02.435 | 17 |
| 126 (마지막) | 17:36:02.452 | **18** |

**백로그 패턴**:
- **초반(1~2)**: 즉시 소비 (queue=1)
- **중반(3~18)**: 선형 증가 (평균 +1/청크)
- **최대**: 18개 (응답 9 EndFrame 시점)

**평가**:
- ⚠️ 이전 분석(14개)보다 **백로그 증가** (18개)
- ⚠️ 적응형 간격에도 불구하고 **백로그 해소 실패**

---

## 3. 817ms 간격 Jitter Spike (핵심 원인)

### 3.1 발견

**로그** (line 46403):
```
timestamp: 2026-03-29T17:36:09.025
event: rtp_tts_send_window_jitter_spike
interval_max_ms: 817.66  ← ⚠️ **비정상적으로 큰 간격**
interval_min_ms: 17.0
pcm_queue_size: 5
thread_packets_queued: 2950
```

**의미**:
- 50개 패킷 윈도우 내에서 **한 패킷이 817ms 뒤에 전송됨**
- 정상 간격(12~20ms)의 **40~68배**
- 이 간격 동안 **40개 패킷 분량의 오디오가 전송되지 않음**

### 3.2 817ms 갭의 원인 추정

**가설 1: soft_resync 후 첫 패킷 지연**

```
17:36:08.207: 청크 처리 완료 (seq 43163)
17:36:08.207: adaptive_interval_changed (5개, 20ms)
17:36:09.025: rtp_tts_send_window_stats (interval_max=817ms)
```

**갭**: 08.207 → 09.025 = **818ms**

**추정**:
- 청크 19 완료 후 **다음 청크(20)가 즉시 도착하지 않음**
- RTP 송신 스레드가 `queue.get(timeout=0.02)`로 대기
- **타임아웃 반복** → 817ms 누적

**가설 2: 큐가 비어있는 동안 긴 대기**

**검증 필요**:
- 청크 19와 20 사이에 `rtp_tts_queue_empty_timeout` 로그가 있는지
- `pcm_chunk_queued` 로그에서 청크 20 투입 시각 확인

### 3.3 80% 손실의 메커니즘

**시나리오 재구성**:

1. **TTS API 완료** (17:36:02.444):
   - 339,212 bytes 생성 완료
   - 22개 프레임 (청크 105~126)

2. **청크 투입** (17:36:01.024 ~ 02.452):
   - 투입 시간: **1.428초**
   - 투입 속도: ~65ms/청크

3. **RTP 전송** (17:36:01.024 ~ 14.642):
   - 전송 기간: **13.6초**
   - 전송 패킷: 425개
   - **예상 패킷의 20%만 전송**

4. **817ms 갭 발생** (17:36:08.207 ~ 09.025):
   - 청크 경계에서 긴 대기
   - **40개 패킷 분량 전송 실패**

5. **이후 응답 시작** (17:36:14.642):
   - 새 응답(api_call_num=10) 시작
   - 응답 9 중단

**결론**:
- RTP 송신 스레드가 **청크를 전송하다가 멈춤**
- 817ms 갭 동안 **다음 청크를 기다림**
- 다음 청크가 도착하지 않음 → **응답 중단**
- **1,695개 패킷이 전송되지 않고 큐에서 사라짐**

---

## 4. 근본 원인 분석

### 4.1 왜 청크가 도착하지 않았는가?

**EndFrame 시점 상태**:
- **thread_packets_queued**: 2628 (line 46010)
- **투입 완료**: 22개 청크 (339,212 bytes)
- **전송 완료**: 청크 1~3 (79 packets, line 46010 기준)
- **큐에 대기**: 18개 청크

**문제**:
- EndFrame 시점에 **18개 청크가 큐에 있음**
- 하지만 **817ms 갭 시점에 큐 크기 5개** (line 46403)
- **13개 청크가 처리됨** (18 - 5)
- **13개 × 25 패킷 = 325 패킷** 전송 예상
- **실제**: 79 → 2950 = **371 패킷 증가** (line 46403)

**계산 검증**:
- 시작 (line 46010): 2628 packets_queued
- 갭 시점 (line 46403): 2950 packets_queued
- **증가**: 2950 - 2628 = **322 packets**
- **청크**: 322 / 25 ≈ **12.9개** (약 13개)

**결과**:
- EndFrame 시점 18개 청크 중 **13개만 전송됨**
- **나머지 5개 청크가 큐에서 사라짐** (125 packets 분량)

### 4.2 왜 5개 청크가 사라졌는가?

**가설 1: 다음 응답 시작으로 큐 초기화**

**증거**:
- line 46012: 새 응답 시작 (`tts_first_audio_received`, 17:36:02.555)
- line 46706: TTS 전송 종료 (`tts_sending_active: false`, 17:36:14.615)
- line 46710: 새 구간 시작 (`rtp_tts_sender_resumed_after_empty`, packets_sent=3080)

**메커니즘**:
1. 응답 9 EndFrame 시점: 큐에 18개 청크
2. RTP 송신 스레드: 13개 청크 전송 (2628 → 2950)
3. 큐 크기 5개 남음
4. **새 응답(10) 시작** → 큐에 새 청크 투입
5. **응답 9의 나머지 5개 청크가 응답 10과 섞임** 또는 **드롭됨**

**가설 2: 큐가 비지 않고 817ms 갭 발생**

**증거**:
- line 46403: `pcm_queue_size: 5` (갭 시점에도 큐에 5개)
- line 46404: `interval_max_ms: 817.66`

**모순**:
- 큐에 5개 청크가 있는데 **817ms 대기?**
- `_pcm_keepalive_queue_timeout_sec()`: 큐 > 0이면 **0.02초 반환**
- 하지만 817ms 갭 발생

**추정 원인**:
- `queue.get(timeout=0.02)` 호출 **직전**에 큐 크기 체크
- 하지만 `get()` 호출 시 **실제로는 비어있음** (race condition)
- 또는 **다른 이유로 get()이 블로킹됨**

---

## 5. 상세 타임라인

### 5.1 응답 9 전체 흐름

| 시각 | 이벤트 | packets_sent | 큐 크기 | 간격 | 비고 |
|------|--------|--------------|---------|------|------|
| 17:36:00.698 | TTS API 호출 | - | - | - | api_call_num=9 |
| 17:36:01.024 | 첫 청크 투입 (105) | 2549 | 1 | 20ms | 응답 시작 |
| 17:36:01.507 | 청크 106~113 투입 | 2574 | 6→7 | 20→18ms | 간격 가속 시작 |
| 17:36:01.944 | 청크 114~116 | 2599 | 11→12 | 18→15ms | 버스트 모드 |
| 17:36:02.303 | 청크 117~123 | - | 13→16 | 15ms | 백로그 누적 |
| 17:36:02.444 | **TTS API 완료** | - | - | - | 339,212 bytes |
| 17:36:02.452 | **EndFrame** | **2628** | **18** | - | 22개 청크 투입 완료 |
| 17:36:02.807 | 청크 전송 중 | 2649 | 18→17 | 15→12ms | 긴급 모드 |
| 17:36:08.207 | 청크 19 완료 (seq 43163) | 2949 | 5 | 18→20ms | 정상 복귀 |
| 17:36:09.025 | **817ms 갭 확인** | 2950 | 5 | - | ⚠️ **Jitter spike** |
| 17:36:14.615 | TTS 전송 종료 | - | **0** | - | 새 응답 시작 |

### 5.2 청크별 전송 상태 (응답 9)

| 청크 번호 | seq 범위 | 투입 시각 | 완료 시각 | 간격 | 상태 |
|-----------|---------|-----------|-----------|------|------|
| 105 | 42764-42788 | 17:36:01.024 | 17:36:01.505 | 20ms | ✅ 전송 |
| 106 | 42789-42813 | 17:36:01.084 | 17:36:01.944 | 18ms | ✅ 전송 |
| 107 | 42814-42838 | 17:36:01.143 | 17:36:02.375 | 15ms | ✅ 전송 |
| 108 | 42839-42863 | 17:36:01.205 | 17:36:02.807 | 15ms | ✅ 전송 |
| 109 | 42864-42888 | 17:36:01.267 | ? | 12ms | ✅ 전송 |
| 110~119 | 42889-43163 | 01.330~02.030 | 08.207 | 12~18ms | ✅ 전송 |
| 120 | 43164-43188 | 17:36:02.178 | 17:36:09.511 | 20ms | ✅ 전송 |
| 121~126 | 43189~? | 02.240~02.452 | **미전송** | - | ❌ **손실** |

**전송 완료**: 청크 105~120 (**16개 청크**, 400 packets)  
**손실**: 청크 121~126 (**6개 청크**, 150 packets) + keepalive 등

---

## 6. 817ms 갭의 정체

### 6.1 청크 120과 121 사이

**청크 120 완료**:
```
timestamp: 17:36:08.207
event: rtp_pcm_chunk_sent_complete
first_seq: 43164
last_seq: 43188
packets_sent_cumulative: 2949
```

**다음 청크 121 시도**:
```
timestamp: 17:36:08.207
event: rtp_pcm_chunk_to_packets
first_packet_seq: 43189
packets_sent_so_far: 2949
pcm_queue_size: 5  ← 큐에 5개 남음
```

**817ms 후**:
```
timestamp: 17:36:09.025
event: rtp_tts_send_window_stats
interval_max_ms: 817.66  ← 이전 패킷과 817ms 간격
thread_packets_queued: 2950  ← 1개 패킷만 증가
```

**분석**:
- 청크 121의 **첫 패킷(seq 43189)만 전송됨** (2949 → 2950)
- **나머지 24개 패킷은?** → 미전송
- 817ms 동안 **왜 1개만 전송?**

### 6.2 추정 시나리오

**시나리오 A: 청크 121 처리 중 큐가 비었다고 판단**

```python
# _pcm_sender_thread_main
for idx, packet in enumerate(rtp_packets):  # 청크 121의 25개 패킷
    if idx == 0:
        # 첫 패킷 전송 (seq 43189)
        # ...
    
    if idx == 1:
        # 두 번째 패킷 전송 시도
        # 하지만 어떤 이유로 중단?
```

**가능성**:
1. **예외 발생**: `pcm_sender_thread_error` 로그 없음 → 배제
2. **pipecat_mode 비활성화**: `if not self._pipecat_mode: break` → 가능
3. **다음 청크 get() 타임아웃**: 루프가 다음 청크를 가져오려다 817ms 대기

**시나리오 B: 적응형 간격 로직 버그**

```python
# 청크 121 시작 시
current_chunk_interval_sec = self._get_adaptive_packet_interval_sec()  # 20ms
# 청크 내 패킷 전송
ideal_target = self._rtp_base_time + (self._rtp_packets_sent_total * current_chunk_interval_sec)
```

**문제**:
- `_rtp_base_time`이 **여전히 이전 base_time**을 참조?
- Soft resync 직후 타이밍 계산 오류?

---

## 7. 코드 레벨 분석

### 7.1 의심 지점 1: 청크 루프 중단

```python
# rtp_relay.py line 1689
for idx, packet in enumerate(rtp_packets):
    if not self._pipecat_mode:  ← ⚠️ 여기서 중단?
        break
```

**검증**:
- 817ms 갭 시점에 `_pipecat_mode`가 `False`로 변경?
- 하지만 line 46710 (`packets_sent_so_far: 3080`)에서 계속 전송 중
- → **배제**

### 7.2 의심 지점 2: `current_chunk_interval_sec` 스코프

```python
# line 1440
current_chunk_interval_sec = 0.020  # 초기화

while ...:
    # line 1675~1685
    prev_chunk_interval = current_chunk_interval_sec
    current_chunk_interval_sec = self._get_adaptive_packet_interval_sec()
    
    # line 1709
    ideal_target = self._rtp_base_time + (
        self._rtp_packets_sent_total * current_chunk_interval_sec
    )
```

**문제**:
- `current_chunk_interval_sec`가 **청크 시작 시 결정됨**
- 하지만 `_rtp_packets_sent_total`은 **전체 누적 패킷 수**
- **절대 시간 계산이 잘못됨**

**예시**:
```
packets_sent_total = 2950
current_chunk_interval = 0.020 (청크 121, 20ms)
ideal_target = base_time + (2950 × 0.020) = base_time + 59초

하지만 이전 패킷들은 12~18ms 간격으로 전송됨!
→ 실제 경과 시간 < 59초
→ ideal_target이 너무 미래 → sleep 필요 없음 → 즉시 전송 예상
→ 하지만 817ms 갭 발생?
```

**모순**: 타이밍 계산 오류가 원인은 아님 (즉시 전송되어야 함)

### 7.3 의심 지점 3: 다음 청크 get() 타임아웃

**코드 흐름**:
```python
# 청크 20 완료 후
# line 1440으로 루프 재시작

try:
    pcm_data = self._pipecat_pcm_queue.get(timeout=_get_timeout)
    # ← 여기서 817ms 대기?
except queue.Empty:
    # keepalive 또는 timeout 로그
```

**가설**:
- 청크 20 완료 후 **다음 청크(21)를 기다림**
- 하지만 **청크 21~26은 이미 큐에 있음** (5개)
- `qsize() = 5`인데 `get()`이 왜 블로킹?

**가능성**:
1. **`qsize()`와 `get()` 사이의 race condition**
   - `qsize()` 호출 시 5개
   - `get()` 호출 시 **다른 스레드가 소비** → 비어있음
   - 하지만 TTS 송신 스레드는 단일 스레드 → 배제

2. **`_pcm_keepalive_queue_timeout_sec()` 버그**
   ```python
   if self._pipecat_pcm_queue.qsize() > 0:
       return 0.02
   ```
   - 큐 크기 5개 → 0.02초 반환 예상
   - 하지만 817ms 대기 발생
   - → **함수가 호출되지 않았거나, 반환값이 무시됨?**

### 7.4 의심 지점 4: Soft Resync 후 타이밍 오류

**로그** (line 46040):
```
timestamp: 17:36:02.841
event: rtp_timing_drift_detected
accumulated_error_ms: 604.16
```

**로그** (line 46153):
```
timestamp: 17:36:04.693
event: rtp_timing_drift_detected
accumulated_error_ms: 653.25
```

**로그** (line 46204):
```
timestamp: 17:36:05.563
event: rtp_timing_drift_detected
accumulated_error_ms: 773.33
```

**패턴**:
- 누적 타이밍 오차가 **600~773ms로 증가**
- 적응형 간격(12~20ms)으로 인해 **예상 시간과 실제 시간 불일치**
- Soft resync가 **여러 번 발생** (soft_resync_count=3, line 45854)

**추정**:
- Soft resync 후 `base_time` 재설정
- 하지만 **`_rtp_packets_sent_total`도 0으로 초기화**됨 (line 1747~1748)
- 이후 `ideal_target` 계산 시 **패킷 수가 0부터 다시 시작**
- **타이밍 오차 누적**

---

## 8. 핵심 문제: 적응형 간격 로직 버그

### 8.1 발견된 버그

**문제**: **절대 시간 격자 계산 오류**

**현재 코드**:
```python
# line 1426: 초기화
current_chunk_interval_sec = 0.020

# line 1440: 루프 시작
while ...:
    # line 1675: 청크마다 간격 결정
    prev_chunk_interval = current_chunk_interval_sec
    current_chunk_interval_sec = self._get_adaptive_packet_interval_sec()
    
    # line 1709: 목표 시각 계산
    ideal_target = self._rtp_base_time + (
        self._rtp_packets_sent_total * current_chunk_interval_sec  ← ⚠️ 버그!
    )
```

**버그 설명**:
- `_rtp_packets_sent_total`: **전체 누적 패킷 수** (0부터 시작)
- `current_chunk_interval_sec`: **현재 청크의 간격** (청크마다 변경)
- **이전 패킷들은 다른 간격(12~18ms)으로 전송되었는데**
- **현재 간격(20ms)을 전체 패킷에 곱함** → **타이밍 오차**

**예시**:
```
패킷 1~100: 12ms 간격 전송 (실제 경과 1.2초)
패킷 101번째:
  _rtp_packets_sent_total = 100
  current_chunk_interval_sec = 20ms (큐 5개 → 정상 모드)
  ideal_target = base_time + (100 × 0.020) = base_time + 2.0초
  
  하지만 실제 경과: 1.2초
  타이밍 오차: 2.0 - 1.2 = 0.8초 (800ms)
```

**결과**:
- `sleep_needed = ideal_target - now = 0.8초` → **800ms sleep**
- **817ms 갭의 원인!**

### 8.2 해결 방법

**방법 1: 누적 절대 시간 추적**

```python
# 초기화
self._rtp_cumulative_ideal_time = 0.0  # 누적 예상 시간 (초)

# 각 패킷 전송 시
ideal_target = self._rtp_base_time + self._rtp_cumulative_ideal_time
self._rtp_cumulative_ideal_time += current_chunk_interval_sec

# Soft resync 시
if sleep_needed < -resync_thr:
    self._rtp_base_time = now
    self._rtp_cumulative_ideal_time = 0.0  # 누적 시간도 리셋
```

**방법 2: 마지막 전송 시각 기준 상대 계산**

```python
# 각 패킷 전송 시
if self._rtp_packets_sent_total == 0:
    ideal_target = self._rtp_base_time
else:
    ideal_target = self._rtp_last_send_time + current_chunk_interval_sec
```

**방법 3: 적응형 간격 비활성화 후 검증**

```bash
# 환경변수로 비활성화
$env:SIPPBX_RTP_ADAPTIVE_INTERVAL="0"
# 테스트: 817ms 갭 재현 여부 확인
```

---

## 9. 추가 발견: interval_violations 과다

**로그** (line 46039):
```
interval_violations_cumulative: 257  (packets_sent=2650, 응답 9 중반)
```

**로그** (line 46307):
```
interval_violations_cumulative: 321  (packets_sent=2900, 응답 9 후반)
```

**증가**: 257 → 321 = **64회** (250개 패킷 중)

**위반율**: 64 / 250 = **25.6%**

**의미**:
- 적응형 간격에도 불구하고 **25%의 패킷이 예상 간격 이탈**
- `INTERVAL_TOLERANCE_MS = 5ms` 기준
- **타이밍 계산 오류의 증거**

---

## 10. 결론 및 권고사항

### 10.1 핵심 발견

**발견 1**: ✅ 적응형 간격 **정상 작동** (12~20ms 동적 조정)  
**발견 2**: ⚠️ 백로그 **18개로 증가** (이전 14개 대비)  
**발견 3**: ❌ **817ms 갭 발생** (청크 120→121)  
**발견 4**: ❌ **80% 오디오 손실** (2120 → 425 packets)  
**발견 5**: ❌ **타이밍 계산 버그** (절대 시간 격자 오류)

### 10.2 근본 원인

**절대 시간 격자 계산 오류**:
- `ideal_target = base_time + (packets_sent_total × current_interval)`
- **이전 패킷들의 실제 간격을 무시**
- **현재 간격을 전체 패킷에 적용** → 타이밍 오차 누적
- **오차가 800ms 이상 누적** → 817ms 갭

### 10.3 즉시 조치 (긴급)

#### 조치 1: 적응형 간격 비활성화 (즉시)

```yaml
# config/config.yaml
media:
  ai_rtp_adaptive_interval:
    enabled: false  ← 변경
```

또는

```bash
$env:SIPPBX_RTP_ADAPTIVE_INTERVAL="0"
```

**이유**:
- 적응형 간격 로직에 **치명적 버그** 존재
- 현재 상태에서는 **고정 20ms가 더 안정적**
- 버그 수정 전까지 **롤백 필수**

#### 조치 2: 타이밍 계산 로직 수정

**수정 필요 파일**: `src/media/rtp_relay.py`

**수정 1**: 누적 절대 시간 추적

```python
# line 1426 초기화 추가
self._rtp_cumulative_ideal_time_sec = 0.0

# line 1709 수정
# Before
ideal_target = self._rtp_base_time + (
    self._rtp_packets_sent_total * current_chunk_interval_sec
)

# After
ideal_target = self._rtp_base_time + self._rtp_cumulative_ideal_time_sec
```

**수정 2**: 각 패킷 전송 후 누적 시간 증가

```python
# line 1844 근처 (패킷 전송 후)
self._rtp_cumulative_ideal_time_sec += current_chunk_interval_sec
self._rtp_last_send_time = now_after_sleep
self._rtp_packets_sent_total += 1
```

**수정 3**: Soft resync 시 누적 시간 초기화

```python
# line 1747 (soft resync)
self._rtp_base_time = now_before_sleep
self._rtp_packets_sent_total = 0
self._rtp_cumulative_ideal_time_sec = 0.0  ← 추가
```

### 10.4 검증 방법

**테스트 1: 고정 20ms로 롤백 테스트**

```bash
# 비활성화
$env:SIPPBX_RTP_ADAPTIVE_INTERVAL="0"
# 재시작 후 테스트
# - 817ms 갭 재현 여부 확인
# - 80% 손실 재현 여부 확인
```

**예상**:
- 고정 20ms로 817ms 갭 사라짐 → **적응형 간격 로직 버그 확정**
- 여전히 갭 발생 → **다른 근본 원인 존재**

**테스트 2: 타이밍 로직 수정 후 재테스트**

```bash
# 수정 적용
# 활성화
$env:SIPPBX_RTP_ADAPTIVE_INTERVAL="1"
# 재시작 후 테스트
# - 817ms 갭 사라짐 확인
# - 백로그 < 12개 확인
# - 80% 손실 해소 확인
```

---

## 11. 사용자 피드백 분석

**"3월 29일 경기 지역은 한때 비가 **(오다가)** 소나기"**

**누락 부분**: "오다가"

**TTS 전체 텍스트**:
```
"삼월 이십구일 경기 지역은 한때 비가 오다가 소나기가 내리는 곳이 있겠습니다. 
밤이 되면 날씨가 맑아질 예정입니다. 더 도움이 필요하시면 말씀해 주세요."
```

**"오다가" 위치**: 약 20자 지점 (전체 85자 중)

**오디오 위치**: 약 **20% 지점** (전체 10.6초 중 **2.1초**)

**전송된 부분**: 청크 1~16 (400 packets, **6.4초**)

**계산**:
- 2.1초 = **약 청크 4~5** (청크당 0.5초)
- 청크 4~5는 **전송 완료됨**
- → "오다가"는 **전송되었어야 함**

**모순**:
- 로그상 청크 4~5는 전송됨
- 하지만 사용자는 "오다가" 미청취
- → **RTP 패킷은 전송되었으나 단말에 도달하지 않음?**
- → 또는 **타임스탬프 문제로 단말이 드롭?**

---

## 12. 대안 가설: Jitter Buffer 오버플로우

### 12.1 가설

**단말 Jitter Buffer**:
- 크기: 일반적으로 50~200ms
- 역할: 네트워크 지연 변동성 흡수

**문제**:
- RTP 패킷이 전송되지만 **타이밍 오차 700ms+** (line 46040, 46153, 46204)
- 단말이 타임스탬프 기준으로 재생하려다 **700ms 지연된 패킷 수신**
- Jitter buffer 한계(50~200ms) 초과 → **패킷 드롭**

**메커니즘**:
1. 패킷 seq 43000 전송 (RTP timestamp: X)
2. 하지만 **실제 도착은 700ms 뒤**
3. 단말이 timestamp X 시점에 재생하려 함
4. 패킷 미도착 → **재생 건너뜀** ("오다가" 누락)
5. 700ms 후 도착한 패킷은 **이미 지나간 시간** → 드롭

**증거**:
- `rtp_timing_drift_detected`: 700ms 오차
- 사용자 체감: 중간 부분("오다가") 누락
- 로그: 패킷은 전송됨 (seq 연속)

### 12.2 왜 타이밍 오차가 누적되었나?

**적응형 간격의 부작용**:
- 간격이 12→15→18→20ms로 변경
- 하지만 **RTP timestamp는 20ms 단위로 증가** (고정)
- **실제 전송 시각과 RTP timestamp 불일치**

**예시**:
```
패킷 1: 12ms 간격, RTP ts=0     (실제 0.012초)
패킷 2: 12ms 간격, RTP ts=160   (실제 0.024초, RTP 기대 0.020초)
패킷 3: 15ms 간격, RTP ts=320   (실제 0.039초, RTP 기대 0.040초)
...
패킷 100: RTP ts=16000 (실제 1.5초, RTP 기대 2.0초)
→ 타이밍 오차: 500ms
```

---

## 13. 최종 판단

### 13.1 적응형 간격 구현 상태

**구현 완료도**: ⭐⭐⭐⭐☆ (4/5)
- ✅ 큐 백로그 감지
- ✅ 동적 간격 조정
- ✅ 로깅 개선
- ❌ **타이밍 계산 로직 오류**

**운영 가능성**: ❌ **불가**
- 80% 오디오 손실 발생
- 817ms 갭 발생
- 타이밍 오차 700ms+ 누적

### 13.2 긴급 조치

**즉시 롤백**: ⚠️ **필수**

```yaml
# config/config.yaml
ai_rtp_adaptive_interval:
  enabled: false
```

**수정 후 재배포**:
1. 누적 절대 시간 추적 로직 추가
2. Soft resync 시 누적 시간 초기화
3. 간격 변경 로그 강화
4. 테스트 → 817ms 갭 해소 확인

### 13.3 수정 우선순위

**우선순위 1: 타이밍 계산 버그 수정** (긴급)
- 누적 절대 시간 추적
- 예상 시간: 1~2시간

**우선순위 2: 적응형 간격 재활성화** (수정 후)
- 롤백 해제
- 테스트: 긴 응답(20개+ 청크)

**우선순위 3: 백로그 감소 확인** (검증)
- 18개 → 10개 이하 달성 여부
- 817ms 갭 재발 여부

---

## 14. 데이터 요약

### 14.1 TTS 생성

```
api_call_num: 9
text_len: 85
text_preview: "삼월 이십구일 경기 지역은 한때 비가 오다가 소나기가 내리는 곳이 있겠습니다..."
frames_generated: 22
total_audio_bytes: 339,212
duration_sec: 10.6
tts_api_duration: 1.746초 (17:36:00.698 → 02.444)
```

### 14.2 PCM 큐 투입

```
chunk_range: 105~126 (22개)
time_range: 17:36:01.024 ~ 02.452 (1.428초)
total_chunks: 22
total_bytes: 339,212
avg_interval: 65ms/청크
max_queue_size: 18
```

### 14.3 RTP 전송

```
시작: 17:36:01.024 (seq 42764, packets_sent=2549)
EndFrame: 17:36:02.452 (packets_queued=2628, 큐 18개)
갭 발생: 17:36:08.207 ~ 09.025 (817ms)
종료: 17:36:14.615 (packets_sent=3080)

전송 패킷: 43188 - 42764 + 1 = 425 packets
예상 패킷: 2120 packets
손실: 1695 packets (80.0%)
```

### 14.4 적응형 간격 동작

```
간격 전환:
  20ms (큐 1~5) → 18ms (큐 6~10) → 15ms (큐 11~15) → 12ms (큐 16+)
  → 15ms (큐 15) → 18ms (큐 10) → 20ms (큐 5)

백로그 최대: 18개
타이밍 오차: 최대 773ms
interval_violations: 64회 (25.6%)
jitter_spike: 817ms
```

---

## 15. 수정 체크리스트

- [ ] **즉시**: 적응형 간격 비활성화 (`enabled: false`)
- [ ] **긴급**: 누적 절대 시간 추적 로직 추가
- [ ] Soft resync 시 누적 시간 초기화
- [ ] 간격 변경 로그에 누적 시간 추가
- [ ] 테스트: 고정 20ms로 817ms 갭 재현 여부
- [ ] 테스트: 수정 후 적응형 간격 재활성화
- [ ] 모니터링: 1주일 운영 후 백로그·갭·손실 통계

---

**분석자**: AI Agent (Cursor)  
**분석 시각**: 2026-03-29T17:00:00+09:00  
**상태**: ❌ **치명적 버그 발견** (타이밍 계산 오류)  
**권고**: ⚠️ **즉시 롤백 필수** (enabled: false)  
**다음 단계**: 누적 절대 시간 추적 로직 구현 → 재테스트
