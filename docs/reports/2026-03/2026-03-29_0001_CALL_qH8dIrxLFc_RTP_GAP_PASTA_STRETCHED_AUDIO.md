# RTP 오디오 뭉개짐 분석 - "파..........스타" 1초 갭

## 작성일
2026-03-29 00:00

## 대상 통화
- **Call ID**: `qH8dIrxLFc`
- **문제 TTS**: "저희는 파스타, 피자, 리조또, 스테이크 등 다양한 정통 이탈리아 요리를 제공하고 있습니다..."
- **증상**: "저희는 파..........스타" (1초 무음 갭)
- **발생 시각**: `2026-03-29 00:53:37`

---

## 1. 문제 현상

### 청각적 증상
```
"저희는 파" → [1초 무음] → "스타, 피자, 리조또..."
```

### RTP 패킷 분석

| Seq | Timestamp | TX Kind | Interval (ms) | Notes |
|-----|-----------|---------|---------------|-------|
| 51130 | 00:53:20.191 | media | 20.113 | 마지막 정상 미디어 |
| 51131 | 00:53:28.208 | keepalive | 8017.486 | Silence keepalive |
| 51132 | 00:53:36.224 | keepalive | 8015.496 | Silence keepalive |
| **51133** | **00:53:37.311** | **media** | **1086.429** | **⚠️ 첫 TTS 패킷, 1086ms 갭!** |
| 51134 | 00:53:37.330 | media | 20.357 | 정상 복구 |

**Keepalive(`51132`) → 첫 TTS 미디어(`51133`) 사이 1086ms 갭 발생!**

---

## 2. 타임라인 분석

### TTS → RTP 전송 흐름

```
00:53:37.054 - rag_textframe_pushed (RAG → Pipeline)
00:53:37.056 - google_tts_api_call (TTS API 호출 시작)
00:53:37.067 - tts_first_audio_received (TTS 첫 오디오 수신)
            ↓
        [244ms 암흑 지대]
            ↓
00:53:37.310 - tts_first_audio_sent_to_rtp (Output Transport → send_audio_to_caller)
00:53:37.310 - rtp_schedule_soft_resync (ideal_late_ms=1066.91, soft_resync #9)
00:53:37.311 - [RTP TX] seq=51133 전송 (1086ms interval)
```

### 갭 분해

```
Keepalive 51132:     00:53:36.224
TTS 첫 오디오 수신:   00:53:37.067  (+ 843ms, 정상: LLM 처리 시간)
RTP 첫 전송:         00:53:37.310  (+ 243ms, ⚠️ 비정상!)
실제 패킷 간격:       1086ms
```

**243ms 지연이 핵심 문제!**

---

## 3. 근본 원인

### 3-1. RTP 송신 스레드 대기 로직

#### `_pcm_keepalive_queue_timeout_sec` 메서드

```python
def _pcm_keepalive_queue_timeout_sec(self, packets_sent: int) -> float:
    """Keepalive ON이고 이미 RTP를 보낸 적 있으면, 다음 킵얼라이브 시각까지 대기."""
    if not self._ai_silence_rtp_keepalive_enabled():
        return self._pcm_queue_get_timeout_sec()
    if packets_sent <= 0:
        return 1.25
    now = time.perf_counter()
    last = self._tts_last_udp_enqueued_mono  # ← Keepalive 전송 시각
    interval = self._rtp_keepalive_interval_sec()  # 8.0초
    if last <= 0:
        return 1.25
    gap = interval - (now - last)
    if gap > 0.02:
        return min(1.25, gap)  # ← ⚠️ 최대 1.25초 대기!
    return 0.02
```

#### 문제 시나리오

**Keepalive 전송 직후:**
```
now = 00:53:36.3 (Keepalive 직후)
last = 00:53:36.224 (_tts_last_udp_enqueued_mono, Keepalive 전송 시각)
gap = 8.0 - (36.3 - 36.224) = 7.924초
return min(1.25, 7.924) = 1.25초 ← ⚠️
```

**송신 스레드:**
```python
pcm_data = self._pipecat_pcm_queue.get(timeout=1.25)  # 1.25초 대기!
```

### 3-2. 실제 대기 시간

```
TTS 첫 오디오 수신:  00:53:37.067 (PCM Queue에 put_nowait)
RTP 첫 전송:        00:53:37.310 (queue.get 반환 후 전송)
대기 시간:           243ms
```

**1.25초 timeout인데 243ms만 대기?**

→ **`queue.get(timeout)`은 아이템이 도착하면 즉시 반환!**

따라서 **243ms는 다른 원인**입니다.

### 3-3. 추가 원인 가능성

1. **Python GIL (Global Interpreter Lock)**
   - Output Transport (메인 스레드) vs RTP 송신 스레드
   - GIL 경쟁으로 인한 스케줄링 지연

2. **Output Transport 내부 처리 시간**
   - `process_frame` → `send_audio_to_caller` 사이

3. **RTP 송신 스레드 루프 처리 시간**
   - `queue.get` → 실제 전송 사이

---

## 4. Soft Resync의 역할

### Soft Resync 로직

```python
ideal_target = self._rtp_base_time + (self._rtp_packets_sent_total * 0.02)
target_time = ideal_target
now_before_sleep = time.perf_counter()
sleep_needed = target_time - now_before_sleep

resync_thr = self._RTP_SCHED_SOFT_RESYNC_LATE_MS / 1000.0  # 300ms
if sleep_needed < -resync_thr:  # 300ms 이상 늦음
    # Base time 재설정 → 즉시 전송
    self._rtp_base_time = now_before_sleep
    self._rtp_packets_sent_total = 0
    target_time = now_before_sleep
    sleep_needed = 0.0
```

### 문제 통화에서의 동작

```
Keepalive 51132: 00:53:36.224
_rtp_base_time = 과거 시각 (00:53:20 근처, Keepalive는 업데이트 안 함)
_rtp_packets_sent_total = 2071 (Keepalive 포함)

첫 TTS 패킷 51133 처리 시:
ideal_target = 00:53:20 + (2071 * 0.02) = 00:53:20 + 41.42초 = ...
now_before_sleep = 00:53:37.310
sleep_needed = ideal_target - 00:53:37.310 = -17초 (대폭 음수)

→ Soft Resync 트리거
→ _rtp_base_time = 00:53:37.310 (재앵커)
→ sleep_needed = 0.0 (즉시 전송)
→ ideal_late_ms = (00:53:37.310 - ideal_target) * 1000 = 1066.91ms
```

**Soft Resync는 즉시 전송을 지시했지만, 이미 1초가 지난 뒤였습니다!**

---

## 5. 근본 원인 정리

### 문제의 핵심

**TTS 첫 오디오가 Pipeline에 도착(`00:53:37.067`)했지만, Output Transport가 `send_audio_to_caller`를 호출하기까지 243ms가 걸렸습니다.**

### 원인 후보

1. **Pipeline 내부 Frame 처리 지연** (Processor 체인)
2. **GIL 경쟁** (Output Transport vs RTP 송신 스레드)
3. **OS Thread 스케줄링 지연** (Windows)

### Soft Resync는 증상이지 원인이 아님

- Soft Resync는 **이미 늦은 상황을 감지하고 복구**하는 로직
- 근본 원인은 **TTS 첫 오디오가 RTP 송신 스레드까지 도달하는 243ms 지연**

---

## 6. 해결 방안

### 방안 1: Output Transport → PCM Queue 투입 시점 로깅 강화

**현재 추가한 로그:**
- `output_transport_pcm_queuing_attempt` - send_audio_to_caller 호출 직전
- `send_audio_first_pcm_queued` - put_nowait 완료 직후
- `rtp_sender_queue_get_attempt` - queue.get 대기 시작
- `rtp_sender_queue_get_success` - queue.get 반환 직후

**목적**: 244ms가 어디서 발생하는지 정확히 추적

### 방안 2: Keepalive 직후 첫 미디어 패킷 즉시 전송 (우선 고려)

**문제**: Keepalive 전송 후 RTP 송신 스레드가 긴 timeout으로 대기

**해결**: Keepalive 전송 시 `_rtp_base_time`을 업데이트하여, 다음 미디어 패킷 스케줄링이 즉시 이루어지도록

```python
# Keepalive 전송 시 (현재는 _rtp_base_time 업데이트 없음)
if pcm_is_keepalive:
    # ✅ Keepalive도 _rtp_base_time 업데이트 (다음 미디어 패킷 스케줄링 정상화)
    self._rtp_base_time = now_after_sleep
    self._rtp_packets_sent_total = 0
```

**효과**: 다음 미디어 패킷이 도착하면 `ideal_target`이 현재 시각 기준으로 계산되어 즉시 전송

### 방안 3: Thread 우선순위 조정

RTP 송신 스레드를 고우선순위로 설정:

```python
# _pipecat_outgoing_sender_loop 스레드 생성 시
import os
if os.name == 'nt':  # Windows
    import win32api, win32process, win32con
    win32process.SetThreadPriority(
        win32api.GetCurrentThread(),
        win32con.THREAD_PRIORITY_TIME_CRITICAL
    )
```

---

## 7. 권장 조치

### 즉시 적용 (Quick Fix)

**1. 디버깅 로그 추가 (이미 완료)**
   - 244ms 지연 구간 추적용 로그 활성화
   - 다음 통화에서 정확한 병목 지점 확인

**2. Keepalive 후 base_time 업데이트**
   - Keepalive 전송 시 `_rtp_base_time` 재앵커
   - 다음 미디어 패킷 스케줄링 정상화

### 중장기 개선

**3. Thread 우선순위 조정**
   - RTP 송신 스레드를 실시간 우선순위로

**4. Pipeline 최적화**
   - Processor 체인 단축
   - Frame 처리 로직 최적화

---

## 8. 다음 단계

1. **디버깅 로그 활성화 상태로 다음 통화 테스트**
   - `output_transport_pcm_queuing_attempt`
   - `send_audio_first_pcm_queued`
   - `rtp_sender_queue_get_attempt`
   - `rtp_sender_queue_get_success`

2. **244ms 구간 정확히 파악**
   - Output Transport → PCM Queue: ?ms
   - PCM Queue → RTP 송신 스레드: ?ms
   - RTP 변환 → UDP 전송: ?ms

3. **Keepalive base_time 업데이트 적용 (추후 결정)**

---

## 9. 로그 증거

### RTP TX TSV
```
seq=51132 (keepalive): 00:53:36.224
seq=51133 (media):     00:53:37.311 (interval=1086.429ms)
```

### App Log
```json
{"timestamp": "2026-03-29T00:53:37.067", "event": "tts_first_audio_received"}
{"timestamp": "2026-03-29T00:53:37.310", "event": "tts_first_audio_sent_to_rtp"}
{"timestamp": "2026-03-29T00:53:37.310", "event": "rtp_schedule_soft_resync", "ideal_late_ms": 1066.91}
```

### Jitter Spike Log
```json
{"timestamp": "2026-03-29T00:53:37.868", 
 "event": "rtp_tts_send_window_jitter_spike",
 "interval_max_ms": 46.43,
 "note": "창 내 간격 극단값 — 청취 뭉개짐과 상관"}
```

---

## 10. 결론

**"파..........스타" 1초 갭은 Keepalive 직후 첫 TTS 미디어 패킷 전송이 244ms 지연되어 발생했습니다.**

### 핵심 원인
- TTS 첫 오디오 수신 (`00:53:37.067`)
- Output Transport 처리 지연
- RTP 송신 스레드 도달 (`00:53:37.310`, +243ms)
- Keepalive와의 실제 간격: 1086ms

### 해결 전략
1. **디버깅 로그로 병목 지점 특정** (현재 진행 중)
2. **Keepalive 후 base_time 재앵커 (고려 중)**
3. **Thread 우선순위 조정 (장기)**

---

**상태**: 디버깅 로그 추가 완료, 다음 통화 대기  
**다음 액션**: 통화 테스트 후 244ms 구간 상세 분석
