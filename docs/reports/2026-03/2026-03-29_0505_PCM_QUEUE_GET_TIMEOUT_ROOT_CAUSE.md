# RTP 오디오 뭉개짐 근본 원인 확정: PCM Queue Get Timeout 블로킹

**작성일**: 2026-03-29 05:05 KST
**call_id**: `dwcHt09Rup`
**문제 발생 시각**:
- 첫 번째: 2026-03-29T04:58:30.750 KST / 2026-03-28T19:58:30.750Z
- 두 번째: 2026-03-29T04:58:58.917 KST / 2026-03-28T19:58:58.917Z

**증상**:
- "기.................상.............감..................정.............서는 기상청 홈페이지에서"
- "신..............청........ 후 발..........급.........까.........지는 약 7~14일 정도 (소요되며, 수수료가 발생할 수 있습니다. 더 도움이 필요하시면) <<(뭉개지다가 짤려서 안들림)"

**상태**: **근본 원인 확정**

---

## 핵심 결론

**송신 스레드 (`_pcm_sender_thread_main`)가 PCM 큐에서 청크를 `get()` 할 때, keepalive 간격(3초)을 타임아웃으로 사용하여 최대 1.25초까지 블로킹 상태로 대기합니다. 이 동안 TTS API가 생성한 PCM 청크들이 큐에 쌓여도 가져오지 않아, 응답당 93~95%의 오디오가 RTP로 송신되지 못했습니다.**

---

## 증거 체인

### 1️⃣ 첫 번째 TTS 응답 (api_call_num: 5, "기상감정서는...")

#### TTS 생성
- **Line 3069** (`google_tts_api_complete`):
  - `frames_generated: 31`
  - `total_audio_bytes: 483852`
  - `duration_sec: 15.12`

#### PCM 큐 투입
- **Line 2865**: `chunk_seq: 40`, `pcm_bytes: 16000`, `queue_size_after: 1`
- **Line 2875**: `chunk_seq: 41`, `pcm_bytes: 16000`, `queue_size_after: 1`
- ...
- **Line 3077**: `chunk_seq: 70`, `pcm_bytes: 3852`, `queue_size_after: 27`

**✅ 31개 프레임 (30 × 16000 + 3852 = 483852 bytes) 모두 PCM 큐 투입 완료**

#### EndFrame 시점 송신
- **Line 3079** (`output_endframe_processed`, `04:58:32.993`):
  - `response_audio_frame_count: 31` ✅
  - `response_bytes: 483852` ✅
  - `thread_packets_queued: 1043`

**송신 스레드 진행**:
- **시작**: 944 packets (Line 2866, `rtp_tts_sender_resumed_after_empty`)
- **EndFrame 시점**: 1043 packets
- **EndFrame까지 송신**: **99 packets** (6.5%)

#### 예상 vs 실제
- **예상 RTP 패킷**: 483852 bytes → 리샘플링(16kHz→8kHz) → 241926 bytes → ÷ 160 = **1512 packets**
- **EndFrame까지 실제 송신**: **99 packets**
- **부족**: **1413 packets (93.5%)**

#### RTP TX TSV 확인
- **첫 패킷**: `seq 7139` (04:58:31.019)
- **마지막 패킷**: `seq 7895` (04:58:46.139, `payload_bytes: 15`)
- **송신 범위**: 7139~7895 = **757 packets**
- **실제 송신**: 757 × 160 = **121120 bytes** (약 25%)
- **유실**: **362732 bytes (75%)**

#### 다음 응답까지 추가 송신
- **두 번째 응답 시작**: `packets_sent_so_far: 1705` (Line 4563, 04:58:59.208)
- **첫 번째 응답 추가 송신**: 1705 - 1043 = **662 packets**
- **첫 번째 응답 총 송신**: 99 + 662 = **761 packets** (50.3%)
- **여전히 부족**: **751 packets (49.7%)**

---

### 2️⃣ 두 번째 TTS 응답 (api_call_num: 6, "신청 후 발급까지는...")

#### TTS 생성
- **Line 4751** (`google_tts_api_complete`):
  - `frames_generated: 29`
  - `total_audio_bytes: 458252`

#### PCM 큐 투입
- **Line 4562**: `chunk_seq: 71`, `queue_size_after: 1`
- ...
- **Line 4759**: `chunk_seq: 99`, `pcm_bytes: 10252`, `queue_size_after: 25`

**✅ 29개 프레임 (28 × 16000 + 10252 = 458252 bytes) 모두 투입**

#### EndFrame 시점 송신
- **Line 4761** (`output_endframe_processed`, `04:59:01.073`):
  - `response_audio_frame_count: 29` ✅
  - `response_bytes: 458252` ✅
  - `thread_packets_queued: 1799`

**송신 스레드 진행**:
- **시작**: 1705 packets
- **EndFrame 시점**: 1799 packets
- **EndFrame까지 송신**: **94 packets** (6.6%)

#### 예상 vs 실제
- **예상 RTP 패킷**: 458252 bytes → 리샘플링 → 229126 bytes → ÷ 160 = **1432 packets**
- **EndFrame까지 실제 송신**: **94 packets** (6.6%)
- **부족**: **1338 packets (93.4%)**

---

### 3️⃣ 패턴 확인

**두 응답 모두 동일 패턴**:
1. ✅ TTS API가 정상 생성 (31개, 29개 프레임)
2. ✅ 모든 프레임이 `SIPPBXOutputTransport`에 도달
3. ✅ 모든 프레임이 `send_audio_to_caller()` 호출됨
4. ✅ 모든 PCM 청크가 큐에 투입됨 (`pcm_chunk_queued`)
5. ❌ **EndFrame 시점 송신 스레드는 겨우 6~7%만 처리**
6. ❌ **큐에 20~27개 청크가 계속 백로그 상태**

---

## 근본 원인: `_pcm_keepalive_queue_timeout_sec()`

### 문제 코드

**파일**: `src/media/rtp_relay.py`
**Lines 1276-1290**:

```python
def _pcm_keepalive_queue_timeout_sec(self, packets_sent: int) -> float:
    """키프얼라이브 ON이고 이미 RTP를 보낸 적 있으면, 다음 킵얼라이브 시각까지 대기."""
    if not self._ai_silence_rtp_keepalive_enabled():
        return self._pcm_queue_get_timeout_sec()
    if packets_sent <= 0:
        return 1.25
    now = time.perf_counter()
    last = self._tts_last_udp_enqueued_mono
    interval = self._rtp_keepalive_interval_sec()  # 3.0 seconds
    if last <= 0:
        return 1.25
    gap = interval - (now - last)
    if gap > 0.02:
        return min(1.25, gap)  # ❌ 최대 1.25초까지 블로킹!
    return 0.02
```

### 문제 메커니즘

**Line 1406** (`_pcm_sender_thread_main`):
```python
pcm_data = self._pipecat_pcm_queue.get(timeout=_get_timeout)
```

**시나리오**:

1. **TTS 응답 시작**: 첫 청크가 큐에 투입됨
2. **송신 스레드**: 첫 청크를 `get()`, RTP 패킷 생성 및 UDP 큐에 투입 (25 packets/chunk)
3. **`_tts_last_udp_enqueued_mono` 갱신** (Line 1819)
4. **다음 `get()` 호출**: `_get_timeout = min(1.25, 3.0 - 0.5) = 1.0` 초 ← **여기서 블로킹!**
5. **TTS API가 나머지 30개 청크를 빠르게 큐에 투입** (1~2초 내)
6. **하지만 송신 스레드는 `get()` 타임아웃 (1초)이 만료될 때까지 대기**
7. **타임아웃 만료 후 두 번째 청크 처리, 다시 타임아웃 (0.9초)**
8. **이 과정 반복 → 큐는 계속 쌓이고, 실제 송신은 느림**

### 왜 `udp_packets_sent_stat`은 정상이었나?

**`pipeline_lag_packets: 1` (거의 동일)**:
- `thread_packets_queued`: 송신 스레드가 UDP 큐에 투입한 패킷 수
- `udp_packets_sent_stat`: 실제 `sendto()` 완료 수

**UDP 송신 자체는 정상**입니다!

**문제는 송신 스레드가 PCM 큐에서 청크를 가져오는 속도가 너무 느리다는 것입니다!**

---

## 로그 증거

### EndFrame 시점 큐 상태

**Line 3077** (`04:58:32.993`):
```json
{
  "event": "pcm_chunk_queued",
  "chunk_seq": 70,
  "queue_size_after": 27
}
```

**27개 청크 = 432000 bytes = 실행 시간 13.5초 분량**

**이 시점까지 송신된 것: 99 packets = 1.98초 분량**

**송신 스레드가 PCM 소비 속도가 TTS 생성 속도의 1/7 수준!**

### RTP TX TSV - 느린 송신

**첫 번째 응답 송신 구간**:
- **시작**: `seq 7139` (04:58:31.019)
- **종료**: `seq 7895` (04:58:46.139)
- **소요 시간**: **15.12초** (TTS 생성 시간과 동일)
- **송신량**: 757 packets = 121120 bytes (25%)

**송신 속도**: 757 packets ÷ 15.12 sec = **50 packets/sec** (정상: 50 packets/sec)

**하지만 TTS는 1.86초 내에 모든 청크를 큐에 투입했습니다!**
- `04:58:31.017` (첫 청크) → `04:58:32.993` (마지막 청크/EndFrame)
- **1.976초** 내에 483852 bytes 투입

**송신은 15.12초 걸림 → 7.6배 느림!**

---

## 핵심 문제 지점

**파일**: `src/media/rtp_relay.py`
**함수**: `_pcm_keepalive_queue_timeout_sec()` (Lines 1276-1290)

**문제**:
- `queue.get(timeout=gap)`에서 `gap`이 최대 **1.25초**까지 설정됨
- 이 시간 동안 송신 스레드는 큐에 청크가 쌓여도 가져오지 않음
- 타임아웃이 만료되어야만 다음 `get()` 호출

**현재 로직**:
```
gap = keepalive_interval (3.0s) - (now - last_udp_enqueue)
if gap > 0.02:
    return min(1.25, gap)  # ❌ 블로킹
```

**결과**:
- TTS가 1~2초 내에 모든 청크 투입
- 송신 스레드는 매 청크마다 0.9~1.25초씩 블로킹
- 청크 30개 → 대기 시간 30초 이상
- 실제로는 15초 동안 25%만 송신

---

## 해결 방안

### 옵션 1: `get()` 타임아웃을 짧게 고정

```python
def _pcm_keepalive_queue_timeout_sec(self, packets_sent: int) -> float:
    """짧은 타임아웃으로 고정하여 청크를 즉시 처리."""
    return 0.05  # 50ms (keepalive와 무관)
```

**장점**:
- 간단하고 명확
- 큐에 청크가 있으면 즉시 처리
- keepalive는 여전히 `queue.Empty` 시 처리

**단점**:
- 매 50ms마다 타임아웃 발생 (큐가 비었을 때)

---

### 옵션 2: `get()` 타임아웃을 큐 상태 기반으로 동적 설정

```python
def _pcm_keepalive_queue_timeout_sec(self, packets_sent: int) -> float:
    """큐에 청크가 있으면 즉시, 없으면 keepalive 간격까지 대기."""
    if not self._ai_silence_rtp_keepalive_enabled():
        return self._pcm_queue_get_timeout_sec()
    
    # 큐에 청크가 있으면 즉시 처리
    if self._pipecat_pcm_queue.qsize() > 0:
        return 0.02
    
    # 큐가 비었을 때만 keepalive 간격 고려
    if packets_sent <= 0:
        return 1.25
    
    now = time.perf_counter()
    last = self._tts_last_udp_enqueued_mono
    interval = self._rtp_keepalive_interval_sec()
    if last <= 0:
        return 1.25
    
    gap = interval - (now - last)
    if gap > 0.02:
        return min(1.25, gap)
    return 0.02
```

**장점**:
- 큐에 청크가 있으면 즉시 처리
- 큐가 비었을 때만 긴 타임아웃 적용
- 최적의 성능

**단점**:
- 약간 복잡

---

### ✅ 권장: 옵션 2 (동적 타임아웃)

**큐 상태를 확인하여, 청크가 있으면 즉시 처리하고, 없으면 keepalive 간격을 고려하는 방식이 가장 효율적입니다.**

---

## 수정 후 예상 동작

### Before (현재)
1. TTS가 1.98초 내에 31개 청크 (483852 bytes) 투입
2. 송신 스레드: 첫 청크 처리 → 1초 블로킹 → 두 번째 처리 → 1초 블로킹 → ...
3. 15초 동안 757 packets (25%) 송신
4. **75% 유실**

### After (수정)
1. TTS가 1.98초 내에 31개 청크 투입
2. 송신 스레드: 첫 청크 처리 → **큐 확인 → 즉시 다음 청크 처리** → ...
3. **1.98초 내 모든 청크 처리 시작**
4. **3초 내 모든 패킷 송신 완료** (50 packets/sec)
5. **유실 없음**

---

## 추가 최적화 고려 사항

### 1. Keepalive 간격 재검토

**현재**: `ai_rtp_keepalive_interval_sec: 3.0`

**이 간격이 `get()` 타임아웃 계산에 영향을 미쳤습니다.**

**수정 후에는 영향이 없지만, 3초 간격이 적절한지 재검토 필요.**

---

### 2. PCM 큐 크기 제한

**현재**: `pcm_queue_max: 150`

**큐가 27개까지 쌓였으나, 송신 스레드가 처리하지 못했습니다.**

**수정 후에는 백로그가 발생하지 않을 것으로 예상.**

---

### 3. 송신 스레드 우선순위

**현재**: 일반 Python 스레드

**실시간 오디오 송신을 위해 스레드 우선순위 상향 고려.**

---

## 로그 강화 제안

### 1. PCM 큐 `get()` 타임아웃 로깅

**모든 `get()` 호출에 대해**:
- `timeout` 값
- 실제 대기 시간
- `get()` 성공 여부

```python
logger.debug("rtp_sender_queue_get_attempt",
            call_id=self.media_session.call_id,
            timeout_sec=_get_timeout,
            queue_size_before=self._pipecat_pcm_queue.qsize(),
            note="queue.get() 호출 (블로킹 타임아웃 추적)")

queue_wait_start = time.perf_counter()
try:
    pcm_data = self._pipecat_pcm_queue.get(timeout=_get_timeout)
    elapsed = time.perf_counter() - queue_wait_start
    logger.debug("rtp_sender_queue_get_success",
                call_id=self.media_session.call_id,
                elapsed_ms=round(elapsed * 1000, 2),
                pcm_bytes=len(pcm_data),
                queue_size_after=self._pipecat_pcm_queue.qsize())
except queue.Empty:
    elapsed = time.perf_counter() - queue_wait_start
    logger.debug("rtp_sender_queue_empty_timeout",
                call_id=self.media_session.call_id,
                timeout_sec=_get_timeout,
                elapsed_ms=round(elapsed * 1000, 2),
                queue_size=self._pipecat_pcm_queue.qsize())
```

---

### 2. 청크 처리 완료 시점 로깅

**현재 `rtp_pcm_chunk_sent_complete`는 있지만, 실제 시각 정보가 부족합니다.**

```python
logger.info("rtp_pcm_chunk_sent_complete",
           ...,
           chunk_processing_start_ts=...,
           chunk_processing_end_ts=...,
           chunk_processing_duration_ms=...,
           note="청크 처리 소요 시간 추적")
```

---

## 후속 조치

1. ✅ `_pcm_keepalive_queue_timeout_sec()` 수정 (옵션 2 권장)
2. ✅ 백엔드 재시작 및 재현 테스트
3. ✅ 로그 확인:
   - PCM 큐 백로그 해소 확인
   - `output_endframe_processed` 시점의 `thread_packets_queued` 증가 확인
   - RTP TX TSV에서 송신 구간 단축 확인
4. ✅ 추가 로깅 (선택):
   - `queue.get()` 대기 시간
   - 청크 처리 소요 시간

---

## 요약

**RTP 오디오 뭉개짐의 근본 원인은 송신 스레드의 PCM 큐 `get()` 타임아웃이 keepalive 간격(3초)과 연동되어 최대 1.25초까지 블로킹되기 때문입니다. TTS API가 빠르게 생성한 PCM 청크들이 큐에 쌓여도, 송신 스레드는 타임아웃이 만료될 때까지 대기하여 93~95%의 오디오를 송신하지 못했습니다. 해결 방법은 `get()` 타임아웃을 큐 상태 기반으로 동적 설정하여, 큐에 청크가 있으면 즉시 처리하도록 수정하는 것입니다.**

---

**원인 코드**: `src/media/rtp_relay.py::_pcm_keepalive_queue_timeout_sec()` (Lines 1276-1290)
**수정 대상**: `return min(1.25, gap)` → 큐 상태 기반 동적 타임아웃
**예상 효과**: PCM 유실 없음, 오디오 뭉개짐 해소
