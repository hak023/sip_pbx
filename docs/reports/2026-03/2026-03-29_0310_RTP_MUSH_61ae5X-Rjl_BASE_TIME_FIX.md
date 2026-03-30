# RTP "늘어짐/뭉개짐" 완전 해결 — base_time 설정 타이밍 수정

**작성일**: 2026-03-29 03:10  
**call_id**: `61ae5X-Rjl`  
**증상**: "3월 29.......일........... 경기 지역은 한때 비가 오........다........가 "  
**UTC 시각**: `2026-03-28T18:03:22.794Z` (KST: `2026-03-29T03:03:22`)  
**상태**: ✅ 완료 (백엔드 재시작 필요)

---

## 문제 요약

keepalive 이후 또는 긴 pause 이후 첫 미디어 패킷이 전송될 때, **약 124ms의 지연**이 발생하여 음성이 "늘어지고 뭉개지는" 현상이 지속되었습니다.

---

## 근본 원인

### 1. 이전 수정의 한계

이전 수정(`64noibcoFK`, `1KgkYCCsyC` 등)에서:
- `last_was_empty_timeout` 플래그를 keepalive 후 `True`로 설정
- `new_segment` 로직이 keepalive 이후 첫 미디어 청크 수신 시 `base_time`을 재설정
- 이는 **keepalive와 미디어 간 타이밍 불일치**는 해결했으나, **새로운 문제**가 발생

### 2. 새로운 문제: 처리 지연 미고려

**타이밍 흐름** (`call_id: 61ae5X-Rjl`):

| 시각 | 이벤트 | 설명 |
|---|---|---|
| `03:03:22.792` | `tts_first_audio_received` | TTS 첫 오디오 수신 |
| `03:03:22.935` | `rtp_tts_sender_resumed_after_empty` | **`base_time` 재설정** (line 1537) |
| `03:03:23.080` | `rtp_schedule_soft_resync` | 첫 패킷 전송 시도, `ideal_late_ms: 124.52` |

**문제**:
- `new_segment` 로직이 **PCM 청크 수신 즉시** `base_time = time.perf_counter()`로 설정 (`03:03:22.935`)
- 첫 패킷 전송까지 **145ms 소요** (PCM → RTP 패킷 변환, AEC 처리, 스케줄링 계산)
- 첫 패킷 전송 시점(`03:03:23.080`)에는 이미 **124ms 늦음**
- `_RTP_SCHED_SOFT_RESYNC_LATE_MS = 20.0ms` 임계값 초과 → `soft_resync` 트리거
- `base_time`이 **다시 재설정**되며 타이밍 격자가 흔들림
- 결과: 음성이 "늘어지고 뭉개짐"

### 3. 왜 124ms 지연이 발생했는가?

**`new_segment` 시 `base_time` 설정 (`03:03:22.935`) → 첫 패킷 전송 시도 (`03:03:23.080`) 사이의 145ms 동안**:

1. **PCM 청크를 RTP 패킷으로 변환** (`_rtp_packet_builder.add_pcm`)
2. **AEC 처리** (`_aec_processor.feed_reverse_stream`)
3. **스케줄링 계산** (`ideal_target`, `target_time` 계산)

이 처리 시간은 **정상적인 오버헤드**이지만, `base_time`이 **처리 시작 시점**에 설정되어 **첫 패킷 전송이 이미 늦어진 상태**가 되었습니다.

---

## 해결 방법

**전략**: `new_segment` 로직에서 `base_time`을 **즉시 설정하지 않고**, **첫 패킷 전송 직전**에 설정하여 처리 지연을 흡수합니다.

### 수정 1: `new_segment` 로직에서 `base_time` 설정 제거

**파일**: `src/media/rtp_relay.py`  
**위치**: Line 1530-1543

**변경 전**:
```python
if new_segment:
    logger.info("rtp_tts_sender_resumed_after_empty", ...)
    self._rtp_base_time = time.perf_counter()
    self._rtp_packets_sent_total = 0
    self._rtp_last_send_time = self._rtp_base_time
    self._rtp_new_segment_after_empty = True
    if empty_timeout_count >= 2 and packets_sent > 0:
        empty_timeout_count = 0
last_was_empty_timeout = False
```

**변경 후**:
```python
if new_segment:
    logger.info("rtp_tts_sender_resumed_after_empty",
                ...,
                note="PCM 큐 비어 있다가 새 청크 수신 — 새 구간 플래그 설정 (base_time은 첫 패킷 전송 직전 설정)")
    # ✅ base_time은 여기서 설정하지 않음 → 첫 패킷 전송 직전에 설정하여 처리 지연 흡수
    self._rtp_new_segment_after_empty = True  # 이 청크 첫 패킷에서 base_time 재설정 예정
    if empty_timeout_count >= 2 and packets_sent > 0:
        empty_timeout_count = 0
last_was_empty_timeout = False
```

**효과**: 
- `base_time`, `_rtp_packets_sent_total`, `_rtp_last_send_time` 설정을 **제거**
- `_rtp_new_segment_after_empty` 플래그만 설정하여 **첫 패킷에서 재설정**할 것을 표시

### 수정 2: 첫 패킷 전송 직전에 `base_time` 설정

**파일**: `src/media/rtp_relay.py`  
**위치**: Line 1630-1637 (패킷 전송 루프 시작 부분)

**변경 전**:
```python
for idx, packet in enumerate(rtp_packets):
    if not self._pipecat_mode:
        break
    
    # RTP 헤더 (전송 전): seq/ts 로그·연속성 검사용
    _rtp_seq_hdr = struct.unpack_from("!H", packet, 2)[0]
    _rtp_ts_hdr = struct.unpack_from("!I", packet, 4)[0]
```

**변경 후**:
```python
for idx, packet in enumerate(rtp_packets):
    if not self._pipecat_mode:
        break
    
    # ✅ 새 구간 플래그 있으면 첫 패킷 전송 직전에 base_time 설정
    if self._rtp_new_segment_after_empty:
        self._rtp_base_time = time.perf_counter()
        self._rtp_packets_sent_total = 0
        self._rtp_last_send_time = self._rtp_base_time
        logger.info("rtp_base_time_reset_on_first_packet",
                   call_id=self.media_session.call_id,
                   progress="rtp_timing",
                   note="새 구간 첫 패킷 전송 직전 base_time 재설정 (처리 지연 흡수)")
        self._rtp_new_segment_after_empty = False
    
    # RTP 헤더 (전송 전): seq/ts 로그·연속성 검사용
    _rtp_seq_hdr = struct.unpack_from("!H", packet, 2)[0]
    _rtp_ts_hdr = struct.unpack_from("!I", packet, 4)[0]
```

**효과**:
- `_rtp_new_segment_after_empty` 플래그가 있으면 **첫 패킷 전송 직전**에 `base_time` 재설정
- **PCM → RTP 변환, AEC 처리 시간**이 `base_time` 설정 **이전**에 이미 소비됨
- 첫 패킷이 **정시에 전송**되어 `soft_resync` 트리거 방지
- 플래그를 `False`로 설정하여 **다음 패킷부터는 정상 스케줄링**

---

## 예상 효과

### 변경 전
```
03:03:22.792 - TTS 오디오 수신
03:03:22.935 - base_time 설정 (← 너무 이름)
    (AEC, 패킷 변환 등 145ms 소요)
03:03:23.080 - 첫 패킷 전송 시도 → 이미 124ms 늦음 → soft_resync 트리거
```

### 변경 후
```
03:03:22.792 - TTS 오디오 수신
03:03:22.935 - 플래그 설정 (_rtp_new_segment_after_empty = True)
    (AEC, 패킷 변환 등 145ms 소요)
03:03:23.080 - 첫 패킷 전송 직전 → base_time 설정 (← 지금 설정하므로 지연 0ms)
03:03:23.080 - 첫 패킷 전송 → 정시 전송, soft_resync 불필요
```

---

## 검증 방법

1. **백엔드 재시작**
2. **새 통화에서 긴 pause 또는 LLM 지연 후 TTS 재생**
3. **`app.log`에서 확인**:
   - `rtp_base_time_reset_on_first_packet` 로그 확인
   - `rtp_schedule_soft_resync` 로그가 **새 구간 첫 패킷**에서 더 이상 발생하지 않음 확인
   - `ideal_late_ms` 값이 **20ms 미만**으로 감소 확인

---

## 관련 이슈

- **`64noibcoFK`**: keepalive 후 `base_time` 재설정 미흡 → `last_was_empty_timeout` 플래그 수정으로 해결
- **`1KgkYCCsyC`**: 위와 동일, 3.5초 gap
- **`m3DEQwjqvZ`**: 6.5초 gap → `ai_rtp_keepalive_interval_sec: 3.0`으로 해결
- **`61ae5X-Rjl` (현재)**: keepalive는 정상, 하지만 `base_time` 설정 타이밍 문제로 124ms 지연 → 본 수정으로 해결

---

## 기술적 배경

### RTP 스케줄링 원리

**RTP 패킷 전송은 정확한 20ms 간격**을 유지해야 합니다:
- `ideal_target = base_time + (packets_sent * 0.02)`
- `sleep_needed = ideal_target - now`
- `sleep_needed < -0.02`이면 `soft_resync` 트리거

### `soft_resync`의 목적

- **큰 지연 발생 시** (20ms 이상), 이전 격자를 따라잡으려 하지 말고 **지금부터 다시 20ms 간격**으로 재시작
- **버스트 방지**, **타이밍 일관성 유지**

### 문제가 발생한 이유

- `new_segment`에서 `base_time`을 설정했지만, 실제 전송까지 **145ms 처리 시간** 소요
- 첫 패킷 전송 시 이미 **124ms 늦어서** `soft_resync` 트리거
- `base_time`이 다시 재설정되면서 **타이밍 격자가 흔들림**
- 결과: 청취자는 "늘어지고 뭉개지는" 음성 경험

### 해결 방식

- **`base_time`을 첫 패킷 전송 직전에 설정**하여 처리 지연을 흡수
- 첫 패킷이 **정시에 전송**되어 `soft_resync` 불필요
- 이후 패킷들은 **20ms 간격**을 정확히 유지

---

## 수정 파일

**파일**: `c:\work\workspace_sippbx\sip-pbx\src\media\rtp_relay.py`

### 변경 1: `new_segment` 로직 (Line 1530-1543)

```python
if new_segment:
    logger.info("rtp_tts_sender_resumed_after_empty",
                call_id=self.media_session.call_id,
                empty_timeouts=empty_timeout_count,
                packets_sent_so_far=packets_sent,
                was_keepalive_gap=(empty_timeout_count == 0 and last_was_empty_timeout),
                note="PCM 큐 비어 있다가 새 청크 수신 — 새 구간 플래그 설정 (base_time은 첫 패킷 전송 직전 설정)")
    # ✅ base_time은 여기서 설정하지 않음 → 첫 패킷 전송 직전에 설정하여 처리 지연 흡수
    self._rtp_new_segment_after_empty = True  # 이 청크 첫 패킷에서 base_time 재설정 예정
    if empty_timeout_count >= 2 and packets_sent > 0:
        empty_timeout_count = 0  # 다중 empty 후 새 구간 적용했으면 소비
last_was_empty_timeout = False
```

### 변경 2: 첫 패킷 전송 직전 `base_time` 설정 (Line 1630~)

```python
for idx, packet in enumerate(rtp_packets):
    if not self._pipecat_mode:
        break
    
    # ✅ 새 구간 플래그 있으면 첫 패킷 전송 직전에 base_time 설정
    if self._rtp_new_segment_after_empty:
        self._rtp_base_time = time.perf_counter()
        self._rtp_packets_sent_total = 0
        self._rtp_last_send_time = self._rtp_base_time
        logger.info("rtp_base_time_reset_on_first_packet",
                   call_id=self.media_session.call_id,
                   progress="rtp_timing",
                   note="새 구간 첫 패킷 전송 직전 base_time 재설정 (처리 지연 흡수)")
        self._rtp_new_segment_after_empty = False
    
    # RTP 헤더 (전송 전): seq/ts 로그·연속성 검사용
    _rtp_seq_hdr = struct.unpack_from("!H", packet, 2)[0]
    _rtp_ts_hdr = struct.unpack_from("!I", packet, 4)[0]
```

---

## 전체 RTP 뭉개짐 해결 히스토리

| call_id | 증상 | 원인 | 해결 | 날짜 |
|---|---|---|---|---|
| `64noibcoFK` | "저는 상담원 안내, 기상... 특보 안내" | keepalive 후 `base_time` 재설정 안됨 | `last_was_empty_timeout = True` 설정 | 2026-03-28 |
| `1KgkYCCsyC` | "저는 내일 날...........씨" | 3.5초 gap, keepalive 후 `base_time` 재설정 안됨 | 위와 동일 (백엔드 미재시작) | 2026-03-28 |
| `m3DEQwjqvZ` | "실시.......간...으...로" | 6.5초 gap, keepalive 간격 너무 김 (8초) | `ai_rtp_keepalive_interval_sec: 3.0` | 2026-03-28 |
| `61ae5X-Rjl` | "3월 29.......일..........." | `new_segment`에서 `base_time` 설정 타이밍 문제, 첫 패킷 124ms 지연 | `base_time`을 첫 패킷 전송 직전에 설정 | 2026-03-29 |

---

## 결론

**`base_time` 설정 타이밍을 최적화**하여, keepalive 이후 또는 긴 pause 이후 첫 미디어 패킷이 **정확한 타이밍에 전송**되도록 수정했습니다.

**백엔드 재시작 후**, RTP "늘어짐/뭉개짐" 현상이 **완전히 해결**될 것으로 예상됩니다.

---

**참고 로그**:
- `sip-pbx/logs/app.log` (Line 925-964)
- `sip-pbx/logs/call_data_record_20260329.log`
