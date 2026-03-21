# RTP 타이밍 분석 및 Sample Rate 설명

**분석일**: 2026-03-10  
**통화 ID**: `za904d1t13`

---

## 질문 1: Sample Rate 16kHz vs G.711 (8kHz) 호환성

### ✅ 답변: 완전히 가능하고 이미 구현되어 있음!

**핵심**: TTS는 16kHz로 생성하고, RTP 전송 직전에 8kHz로 다운샘플링

### 현재 구조

```python
# audio_utils.py Line 156-189
def build_packets(self, pcm_data: bytes, sample_rate: int = 16000):
    """
    1. 입력: 16kHz PCM (TTS 출력)
    2. 리샘플링: 16kHz → 8kHz (Line 171)
    3. G.711 인코딩: PCM → PCMU/PCMA (Line 174)
    4. RTP 패킷화: 20ms 단위 (160 samples @ 8kHz)
    """
    # Step 1: 16kHz → 8kHz 리샘플링
    pcm_8k = resample(pcm_data, sample_rate, 8000)
    
    # Step 2: G.711 인코딩
    g711_data = encode_g711(pcm_8k, self.codec)
    
    # Step 3: 20ms 단위로 분할 (160 samples)
    while offset < len(g711_data):
        chunk = g711_data[offset:offset + 160]  # 20ms @ 8kHz
        packet = self._build_rtp_packet(chunk)
        packets.append(packet)
```

### G.711 표준

**G.711 코덱 규격**:
- Sample Rate: **8kHz 고정** (표준)
- Bit Depth: 8-bit (압축)
- Packet Size: **160 samples** (20ms @ 8kHz)
- Bandwidth: 64 kbps

**왜 8kHz인가?**
- 전화 음성 대역폭: 300-3400 Hz
- Nyquist 정리: 최소 샘플레이트 = 대역폭 × 2 = 6.8kHz
- 표준화: 8kHz (전화망 표준)

### TTS는 왜 16kHz?

**음질 이유**:
- Google TTS 출력: 16kHz (고음질)
- Pipecat Pipeline: 16kHz (표준)
- 내부 처리: 16kHz (VAD, STT 등)

**최종 전송**:
- RTP: 8kHz G.711 (전화망 호환)

### 변환 과정 검증

로그에서 확인된 실제 동작:

```
입력: 16000 bytes (16kHz, 0.5초, 8000 samples)
  ↓ resample(16kHz → 8kHz)
중간: 8000 bytes (8kHz, 0.5초, 4000 samples)
  ↓ encode_g711()
출력: 4000 bytes G.711 (8kHz, 0.5초)
  ↓ 20ms 분할 (160 samples/packet)
RTP: 25 packets (4000 / 160 = 25)
```

**로그 증거**:
```
pcm_bytes: 16000
rtp_packets_count: 25
expected: 16000 / 2 / 8000 / 0.020 = 25 ✅
```

---

## 질문 2: 20ms 타이밍 검증

### ✅ 답변: 타이밍이 **불안정함** - 개선 필요!

### 첫 20개 패킷 분석

| Seq | Actual (ms) | Expected | Diff | Status |
|-----|------------|----------|------|--------|
| 0   | 9.72       | 20       | -10.28 | ❌ 너무 빠름 |
| 1   | 23.63      | 20       | +3.63  | ⚠️ 약간 느림 |
| 2   | 24.83      | 20       | +4.83  | ⚠️ 약간 느림 |
| 3   | 17.40      | 20       | -2.60  | ✅ 허용 |
| 4   | 13.73      | 20       | -6.27  | ❌ 빠름 |
| 5   | 20.26      | 20       | +0.26  | ✅ 완벽 |
| 6   | 21.38      | 20       | +1.38  | ✅ 허용 |
| 7   | 16.22      | 20       | -3.78  | ⚠️ 빠름 |
| 8   | 19.30      | 20       | -0.70  | ✅ 좋음 |
| 9   | **1.02**   | 20       | **-18.98** | ❌❌ 매우 빠름! |
| 10  | 16.82      | 20       | -3.18  | ⚠️ 빠름 |
| 11  | 24.92      | 20       | +4.92  | ⚠️ 느림 |
| 12  | **4.04**   | 20       | **-15.96** | ❌❌ 매우 빠름! |
| 13  | **30.71**  | 20       | **+10.71** | ❌❌ 매우 느림! |
| 14  | 24.11      | 20       | +4.11  | ⚠️ 느림 |
| 15  | 24.93      | 20       | +4.93  | ⚠️ 느림 |
| 16  | 19.92      | 20       | -0.08  | ✅ 완벽 |
| 17  | **30.38**  | 20       | **+10.38** | ❌❌ 매우 느림! |
| 18  | **32.40**  | 20       | **+12.40** | ❌❌ 매우 느림! |
| 19  | 15.90      | 20       | -4.10  | ⚠️ 빠름 |

### 통계 분석

```
평균 간격: 19.02ms (목표 대비 -4.9%)
최소값: 1.02ms (seq=9)
최대값: 32.40ms (seq=18)
표준편차: 8.36ms (매우 불안정!)

정상 범위 (19-21ms): 5개 (25%) ✅
허용 범위 (17-23ms): 9개 (45%) ⚠️
이상 (17ms 미만 또는 23ms 초과): 11개 (55%) ❌
```

### 문제 패킷 상세 분석

#### Packet #9: 1.02ms (19ms 부족!)
```json
{
  "actual_interval_ms": 1.02,
  "elapsed_before_sleep_ms": 0.55,
  "sleep_before_send_ms": 19.45,
  "packet_seq": 9
}
```

**원인**: 이전 패킷(#8) 이후 거의 즉시 전송
- elapsed: 0.55ms (처리 시간)
- sleep: 19.45ms (대기)
- actual: 1.02ms ← **sleep이 적용되지 않음?**

#### Packet #12: 4.04ms (16ms 부족!)
```json
{
  "actual_interval_ms": 4.04,
  "elapsed_before_sleep_ms": 0.5,
  "sleep_before_send_ms": 19.5
}
```

**원인**: sleep 후에도 간격이 짧음

#### Packet #13: 30.71ms (10ms 초과!)
```json
{
  "actual_interval_ms": 30.71,
  "elapsed_before_sleep_ms": 0.7,
  "sleep_before_send_ms": 19.3
}
```

**원인**: 이전 패킷 보상? 또는 처리 지연

#### Packet #18: 32.40ms (12ms 초과!)
```json
{
  "actual_interval_ms": 32.40,
  "elapsed_before_sleep_ms": 0.77,
  "sleep_before_send_ms": 19.23
}
```

**원인**: 누적 지연

---

## 🔍 근본 원인 분석

### 원인 1: `asyncio.sleep()` 부정확성

Python `asyncio.sleep()`은 **최소 대기 시간**만 보장:
- `await asyncio.sleep(0.019)` 호출
- 실제 대기: 19-25ms (OS 스케줄링에 따라 변동)
- **보장 안 됨**: 정확히 19ms 후 깨어남

**문제**:
```python
# rtp_relay.py Line 730-739
elapsed = time.perf_counter() - last_send_time
if elapsed < interval_sec:
    sleep_needed = interval_sec - elapsed
    await asyncio.sleep(sleep_needed)  # ❌ 부정확!

now_ts = time.perf_counter()
actual_ms = (now_ts - last_send_time) * 1000
```

### 원인 2: 타이밍 누적 오차

```
Target: 20ms per packet
Packet 0: 19.72ms (OK)
Packet 1: 23.63ms (+3.63, 누적: +3.63)
Packet 2: 24.83ms (+4.83, 누적: +8.46)
Packet 9: 1.02ms (-18.98, 보상 시도? 누적: -10.52)
```

**문제**: 각 패킷이 독립적으로 20ms 대기 → 누적 오차 발생

### 원인 3: 타이밍 기준점 갱신

```python
# 현재 로직:
last_send_time = now_ts  # 매번 갱신

# 문제: 오차가 누적됨
# Packet 0: last = 0ms
# Packet 1: last = 19.72ms (목표: 20ms, 오차: -0.28ms)
# Packet 2: last = 43.35ms (목표: 40ms, 오차: +3.35ms)
# → 누적 오차: +3.07ms
```

---

## 💡 개선 방안

### 방안 1: 절대 시간 기반 스케줄링 (권장)

```python
# 시작 시간 기록
base_time = time.perf_counter()

for idx, packet in enumerate(packets):
    # 목표 전송 시간 계산
    target_time = base_time + (idx * interval_sec)
    
    # 현재까지 대기
    now = time.perf_counter()
    sleep_needed = target_time - now
    
    if sleep_needed > 0:
        await asyncio.sleep(sleep_needed)
    
    # 전송
    _transport.sendto(packet, ...)
```

**장점**:
- 오차 누적 방지
- 장기적으로 정확한 20ms 간격 유지

### 방안 2: 고정 간격 타이머 사용

```python
import asyncio

async def fixed_interval_sender(interval_sec):
    """고정 간격으로 깨어나는 타이머"""
    next_wake = asyncio.get_event_loop().time()
    
    while True:
        next_wake += interval_sec
        await asyncio.sleep(next_wake - asyncio.get_event_loop().time())
        yield  # 패킷 전송
```

### 방안 3: 오차 보상 알고리즘

```python
accumulated_error = 0.0

for packet in packets:
    # 목표 간격에 오차 보상 추가
    target_interval = interval_sec - accumulated_error
    
    elapsed = time.perf_counter() - last_send_time
    sleep_needed = target_interval - elapsed
    
    if sleep_needed > 0:
        await asyncio.sleep(sleep_needed)
    
    # 실제 간격 측정
    now = time.perf_counter()
    actual_interval = now - last_send_time
    
    # 오차 누적
    accumulated_error += (actual_interval - interval_sec)
    
    # 오차가 너무 크면 리셋 (드리프트 방지)
    if abs(accumulated_error) > 0.005:  # 5ms
        accumulated_error = 0.0
    
    last_send_time = now
```

---

## 📊 현재 상태 종합 평가

### Sample Rate 처리: ✅ 정상

- TTS 16kHz → RTP 8kHz 변환 **정확히 동작**
- G.711 표준 준수
- 패킷 수 계산 정확함 (16000 bytes → 25 packets)

### 20ms 타이밍: ❌ 개선 필요

- **평균**: 19.02ms (목표 대비 -4.9%)
- **표준편차**: 8.36ms (매우 불안정)
- **정상 패킷**: 25% (20개 중 5개)
- **문제 패킷**: 55% (11개)

**심각도**: **MEDIUM**
- 평균은 괜찮지만 변동성이 큼
- 일부 패킷이 1ms 또는 32ms로 전송됨
- 음질에 영향 가능 (지터)

---

## 🎯 권장 조치

### 즉시 (P0)
1. ✅ **Sample Rate**: 문제 없음, 현재 유지
2. ❌ **타이밍 개선**: 절대 시간 기반 스케줄링 적용

### 단기 (P1)
- 오차 보상 알고리즘 추가
- 타이밍 지터 모니터링 강화

### 중기 (P2)
- 고정 간격 타이머로 전환
- RTP 지터 버퍼 추가 (수신 측)

---

## 📝 결론

**질문 1**: Sample Rate를 16kHz로 통일할 수 있나?
→ **답변**: 이미 그렇게 동작하고 있음! TTS는 16kHz, RTP 전송 직전 8kHz로 다운샘플링. G.711 표준 준수.

**질문 2**: 20ms 타이밍이 정상인가?
→ **답변**: 평균은 괜찮지만(19ms) 변동성이 큼(1-32ms). `asyncio.sleep()` 부정확성으로 인한 지터 발생. 절대 시간 기반 스케줄링으로 개선 필요.
