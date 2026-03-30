# 오디오 늘어짐 분석 - call_id: 7biV~fDq3c

**작성일**: 2026-03-29 18:30 KST  
**문제**: "기상 감정서는 기상청 홈페이지에서 온라인으로 신청하실 수 있습니다. 신청 후 발급까지는 약 7~14일 정도 소요됩니다." 후반부가 늘어지고 안 들림  
**사용자 보고**: "온라인.........................................(으로 신청하실 수 있습니다. 신청 후 발급까지는 약 7~14일 정도 소요됩니다.) << 괄호부분은 늘어지더니 아예 안들렸어."  
**call_id**: `7biV~fDq3c`

---

## 1. 타임라인 분석

### 1.1 8번째 응답 (문제 발생)

| 시각 (UTC+9) | 이벤트 | 상세 |
|-------------|--------|------|
| 18:31:25.904 | **LLM 응답 생성** | "기상 감정서는 기상청 홈페이지에서..." (88자, repeat) |
| 18:31:25.906 | **Google TTS API 호출** | api_call_num: 8, text_len: 88 |
| 18:31:25.917 | **TTS 첫 오디오 수신** | 11ms 후 첫 청크 |
| 18:31:26.226 | **첫 오디오 RTP 투입** | chunk_seq: 99, queue_size: 1 |
| 18:31:26.228 | **⚠️ 새 구간 시작** | `rtp_tts_sender_resumed_after_empty` |
| 18:31:26.228 | **⚠️ base_time 리셋** | `rtp_base_time_reset_on_first_packet` |
| 18:31:26.710 | **첫 청크 전송 완료** | 25 packets (seq: 15264~15288) |
| 18:31:27.210 | **2번째 청크 완료** | 25 packets |
| 18:31:27.710 | **3번째 청크 완료** | 25 packets, **queue: 19** |
| 18:31:28.092 | **TTS API 완료** | 14.12초 소요, 29 frames, 451,852 bytes |
| 18:31:28.094 | **EndFrame 처리** | thread_packets_queued: **2494** |
| 18:31:28.214 | **4번째 청크 완료** | queue: **25** |

### 1.2 7번째 응답 종료 → 8번째 시작 사이 Gap

| 시각 | 이벤트 | 패킷 | Gap |
|------|--------|------|-----|
| 18:31:14.508 | 7번째 응답 마지막 청크 완료 | 2397 | - |
| 18:31:17.510 | **Keepalive** | 2398 (1개) | **3.0초** |
| 18:31:20.523 | **Keepalive** | 2399 (1개) | **3.0초** |
| 18:31:23.540 | **Keepalive** | 2400 (1개) | **3.0초** |
| 18:31:26.228 | **8번째 응답 첫 청크** | 2401~ (25개) | **2.7초** |

**총 Keepalive 구간**: 11.7초 (3초 간격 × 4회)

---

## 2. 문제 진단

### 2.1 RTP Timing 로그 부족

**문제**: 
- `pcm_chunk_queued` 로그: **127개**
- `rtp_packet_timing_absolute` 로그: **30개만**
- `rtp_tts_send_window_stats`: 정상 출력

**원인 추정**:
- `rtp_packet_timing_absolute`는 **첫 N개 패킷만 로깅**하고 이후 생략됨
- 코드에 로깅 조건(예: `packet_seq < 30`)이 있을 가능성

**영향**:
- 8번째 응답(18:31:26~28)의 **개별 패킷 타이밍 추적 불가**
- 문제 구간의 `interval_from_prev_ms`, `sleep_requested_ms` 확인 불가

### 2.2 Keepalive Gap의 영향

**구조**:
```
7번째 응답 완료 (18:31:14.508)
  ↓ PCM 큐 비어짐
  ↓ 3초마다 Keepalive (18:31:17, 20, 23)
8번째 응답 시작 (18:31:26.228)
  ↓ base_time 리셋 (새 구간)
  ↓ 첫 청크 전송 (482ms, 0.96배속)
```

**문제 가능성**:
1. **Base_time 리셋 후 재동기화 지연**: 새 구간 시작 시 타이밍 안정화까지 일부 패킷 지연 가능
2. **PCM 큐 부족**: 8번째 응답이 **2.1초 만에 완료** (TTS API 호출 18:31:25.906 → 완료 18:31:28.092)되었으나, **TTS 첫 청크가 26.226초에야 RTP 투입**됨 (지연: **0.3초**)
3. **대량 PCM 동시 투입**: 18:31:26.8~28.1 구간에 **29개 프레임 (451KB)** 이 **1.2초 만에 집중 투입**

### 2.3 PCM 큐 투입 패턴

**chunk_seq 99~127 (29개)**:

| chunk_seq | 시각 | queue_size_after | 간격 |
|-----------|------|------------------|------|
| 99 | 18:31:26.228 | 1 | - |
| 100 | 18:31:26.286 | 1 | 58ms |
| 101 | 18:31:26.347 | 2 | 61ms |
| 102 | 18:31:26.406 | 3 | 59ms |
| ... | ... | 증가 | ... |
| 120 | 18:31:27.700 | 18 | - |
| 121 | 18:31:27.766 | 19 | 66ms |
| 122 | 18:31:27.826 | 20 | 60ms |
| 123 | 18:31:27.890 | 21 | 64ms |
| 124 | 18:31:27.947 | 22 | 57ms |
| 125 | 18:31:28.014 | 23 | 67ms |
| 126 | 18:31:28.068 | 24 | 54ms |
| 127 | 18:31:28.094 | **25** | 26ms |

**관찰**:
- TTS API가 **초당 약 15~17개 청크**를 생성 (16KB @ 16kHz = 500ms/chunk)
- RTP 송신은 **초당 2개 청크** 소비 (1초 = 500ms × 2)
- **PCM 큐가 1초 만에 1 → 25로 증가** (18:31:27~28)

### 2.4 RTP 송신 속도

**chunk_sent_complete 타이밍**:

| 시각 | 청크 seq | 패킷 수 | 소요 시간 | 계산 |
|------|----------|---------|----------|------|
| 18:31:26.710 | 99 (15264~15288) | 25 | 482ms | 500ms 예상 |
| 18:31:27.210 | 100 (15289~15313) | 25 | 500ms | ✓ 정상 |
| 18:31:27.710 | 101 (15314~15338) | 25 | 500ms | ✓ 정상 |
| 18:31:28.214 | 102 (15339~15363) | 25 | 504ms | ✓ 정상 |
| 18:31:28.712 | 103 | 25 | 498ms | ✓ 정상 |

**평균**: **498~504ms per chunk** (25 packets × 20ms = 500ms 이론값)

**결론**: RTP 송신은 **정상 속도** (20ms 간격 유지)

---

## 3. 근본 원인 추정

### 3.1 TTS API 응답 속도 vs RTP 소비 속도

**TTS 생성 속도**:
- 451,852 bytes ÷ 2.186초 (26.226~28.092) = **206 KB/s**
- 청크 기준: **29개 ÷ 2.186초 = 13.3 chunks/s**

**RTP 소비 속도**:
- 16,000 bytes/chunk × 2 chunks/s = **32 KB/s**
- 이론값: 16kHz × 2 bytes = **32 KB/s**

**비교**:
- **TTS 생성이 RTP 소비보다 6.4배 빠름** (206 ÷ 32)
- 이것은 **정상** (Google TTS는 실시간보다 빠르게 스트리밍)

### 3.2 실제 문제

**사용자 경험**:
- "온라인으로" 까지는 정상
- 이후 "........................................" (무음 또는 늘어짐)
- 괄호 부분 "으로 신청하실 수 있습니다. 신청 후 발급까지는 약 7~14일 정도 소요됩니다." 안 들림

**가설 1: 특정 구간 패킷 손실**
- **증거 부족**: `window_stats`에서 `pipeline_lag_packets: 1` (정상 범위)
- `udp_packets_sent_stat: 2500` vs `thread_packets_queued: 2500` (일치)

**가설 2: RTP Timestamp 점프**
- **Base_time 리셋** (line 9547) 후 timestamp가 불연속적으로 증가했을 가능성
- 수신측(단말)이 timestamp 불연속을 감지하고 **jitter buffer** 재초기화 → 일부 패킷 버림

**가설 3: 초반 패킷 지연 누적**
- 첫 청크 전송이 **482ms** (기대: 500ms) → **18ms 빠름**
- 이후 청크는 정상 (500ms)
- **초반 18ms 앞서감**이 누적되어 일부 패킷이 jitter buffer 범위 초과?

---

## 4. 로그 증거

### 4.1 Base_time 리셋 (Line 9547)

```json
{
  "timestamp": "2026-03-29T18:31:26.228",
  "event": "rtp_base_time_reset_on_first_packet",
  "call_id": "7biV~fDq3c",
  "note": "새 구간 첫 패킷 전송 직전 base_time 재설정 (처리 지연 흡수)"
}
```

### 4.2 Keepalive Gap (Line 1505)

```json
{
  "timestamp": "2026-03-29T18:29:07.334",
  "event": "rtp_tts_sender_resumed_after_empty",
  "call_id": "7biV~fDq3c",
  "empty_timeouts": 0,
  "packets_sent_so_far": 726,
  "was_keepalive_gap": true
}
```

### 4.3 RTP Timestamp (Line 9584)

**8번째 응답 첫 청크**:
- `last_ts: 1735702531` (seq: 15288)

**7번째 응답 마지막 청크** (line 8897):
- `last_ts: 1735698051` (seq: 15260)

**Timestamp 점프**:
- Δ = 1735702531 - 1735698051 = **4480 timestamp units**
- 시간: 4480 ÷ 16000 Hz = **280ms**

**실제 시간 Gap**:
- 18:31:26.228 - 18:31:14.508 = **11.72초**

**⚠️ 불일치**:
- **RTP Timestamp는 280ms 증가**
- **실제 시간은 11.72초 경과**
- **Keepalive 패킷 3개 (18:31:17, 20, 23)**는 timestamp 증가 없이 전송됨

---

## 5. RTP Timestamp 불연속 문제

### 5.1 Keepalive 패킷의 Timestamp

**코드 확인 필요**:
- Keepalive 패킷의 timestamp가 **마지막 데이터 패킷과 동일**한지?
- 아니면 **무음 640 bytes (40ms)만큼 증가**하는지?

**예상 동작** (Line 1509, 1673, 1832, 1918, 1923):
```
18:31:17.510: seq=13591, ts=1735431011 (keepalive)
18:31:20.523: seq=13592, ts=1735431171 (keepalive)
18:31:23.540: seq=13593, ts=1735431331 (keepalive)
```

**Timestamp 증가**:
- 13591 → 13592: 160 units = **10ms**
- 13592 → 13593: 160 units = **10ms**

**⚠️ 문제**:
- Keepalive는 **640 bytes (40ms = 640 units)**여야 하는데
- 로그에는 **160 units (10ms)만 증가**

### 5.2 Base_time 리셋의 영향

**시나리오**:
```
18:31:14.508: 마지막 데이터 청크 (seq: 15260, ts: 1735698051)
18:31:17.510: Keepalive (seq: 13591, ts: 1735431011) ← 이전 구간 timestamp 사용?
  ...
18:31:26.228: 새 구간 시작, base_time 리셋
18:31:26.710: 첫 데이터 청크 (seq: 15264, ts: 1735702531)
```

**Timestamp 점프**:
- 1735698051 (15260) → 1735702531 (15264) = **4480 units (280ms)**
- **예상**: 4 packets × 160 = **640 units (40ms)**
- **실제**: **280ms** (7배 큼)

**⚠️ 수신측 영향**:
- **Jitter buffer가 280ms timestamp 점프 감지**
- **Packet loss로 판단** → 일부 패킷 버림 또는 무음 삽입
- **늘어지는 듯한 재생**

---

## 6. Window Stats 분석

### 6.1 18:31:27.658 (Line 2727)

```json
{
  "timestamp": "2026-03-29T18:31:27.658",
  "event": "rtp_tts_send_window_stats",
  "call_id": "7biV~fDq3c",
  "behind_schedule_cumulative": 8,
  "interval_avg_ms": 20.01,
  "interval_max_ms": 28.82,
  "interval_min_ms": 17.41,
  "interval_violations_cumulative": 13,
  "last_rtp_seq": 13713,
  "pcm_queue_size": 3,
  "thread_packets_queued": 850,
  "timing_error_ms": 0.63,
  "udp_packets_sent_stat": 850,
  "window_size": 50
}
```

**분석**:
- `interval_max_ms: 28.82` (허용: 23ms) → **5.82ms 초과**
- `interval_violations_cumulative: 13` (이전: 12, +1)
- **일부 패킷이 28.82ms 간격으로 전송됨** (20ms 기대)

**영향**:
- 28.82ms 간격 = **143% 속도** → 늘어진 재생
- 이것이 사용자가 들은 "........................................" 구간일 가능성

### 6.2 18:31:28.214 이후 (Line 9753)

```
chunk_sent_complete: 18:31:28.214 (seq: 15339~15363, 25 packets)
queue_size: 25 (최대)
```

**분석**:
- PCM 큐가 **25개로 가득 참** (maxsize: 500이지만 청크 단위)
- 이후 RTP 송신은 정상 (500ms/chunk)

**⚠️ 문제**:
- **사용자는 28.214 이후 내용("신청 후 발급까지는 약 7~14일 정도 소요됩니다")을 못 들음**
- **RTP는 정상 전송**했는데 왜?

---

## 7. RTP Dump 실제 분석 (✅ 정확한 데이터)

### 7.1 app.log의 오해

**app.log의 `first_packet_seq` 로그 (keepalive)**:
```
18:31:17.510: seq=13590 (keepalive)
18:31:20.523: seq=13591 (keepalive)  
18:31:23.540: seq=13592 (keepalive)
```

**⚠️ 오인**: app.log 만으로는 Seq가 15260 → 13590으로 **역행**한 것처럼 보임

### 7.2 RTP Dump (TSV) 실제 데이터

**파일**: `logs/rtp_tx_7biV_fDq3c.tsv` (실제 전송된 RTP 패킷)

| 시각 | tx_kind | Seq | Timestamp | Interval (ms) |
|------|---------|-----|-----------|---------------|
| 18:31:14.507 | media | 15260 | 1735698051 | 20.255 |
| 18:31:17.511 | **keepalive** | **15261** | **1735698211** | **3002.636** |
| 18:31:20.522 | **keepalive** | **15262** | **1735698371** | **3012.307** |
| 18:31:23.539 | **keepalive** | **15263** | **1735698531** | **3016.686** |
| 18:31:26.230 | media | **15264** | **1735698691** | **2691.134** |
| 18:31:26.250 | media | 15265 | 1735698851 | 19.476 |
| 18:31:26.272 | media | 15266 | 1735699011 | 22.357 |

**✅ 실제 상황**:
- **Seq는 연속**: 15260 → 15261 → 15262 → 15263 → 15264 (역행 없음)
- **Timestamp도 연속**: +160씩 정확히 증가
- **Keepalive 간격**: 정확히 3초 (3002ms, 3012ms, 3016ms)

**⚠️ 실제 문제**: 
- 마지막 keepalive(18:31:23.539) → 첫 미디어(18:31:26.230) = **2.691초 gap**
- 이론적으로는 **20ms** 간격이어야 하는데, **2.7초 지연** 발생

### 7.3 app.log vs RTP Dump 차이 원인

**app.log의 `first_packet_seq`**:
- `build_packets()` 직후 `rtp_packets[0]`를 파싱하여 로깅
- **Keepalive 패킷의 경우 파싱이 잘못**되었거나, 다른 데이터를 읽었을 가능성

**RTP Dump (TSV)**:
- `_sync_sendto_and_stats()` 내부에서 **실제 전송 직전** 패킷 파싱
- **훨씬 정확**한 데이터 (UDP sendto 직전)

**결론**: **RTP Dump를 신뢰**해야 하며, app.log의 keepalive seq는 무시

---

## 8. 실제 근본 원인

### 8.1 문제 1: Keepalive → Media 간 긴 Gap (2.691초)

**정상 시나리오**:
```
미디어 패킷: 20ms 간격
Keepalive: 500ms 간격 (권장)
다음 미디어: 500ms 이내 도착
```

**현재 시나리오**:
```
마지막 미디어 (18:31:14.507)
  ↓ 3.0초 후
Keepalive 1 (18:31:17.511)
  ↓ 3.0초 후
Keepalive 2 (18:31:20.522)
  ↓ 3.0초 후  
Keepalive 3 (18:31:23.539)
  ↓ 2.7초 후 ← ⚠️ 문제
첫 미디어 (18:31:26.230)
```

**영향**:
- 클라이언트 Jitter Buffer는 **20ms 기준으로 설계**됨
- **2.7초 gap**은 Jitter Buffer 범위를 **135배 초과**
- 클라이언트가 **세션 끊김으로 오인** → 버퍼 리셋 → **일부 패킷 버림/재생 불안정**

### 8.2 문제 2: Base_time 리셋

**코드 동작** (Line 1513, 1725):
```python
# Keepalive 전송 후
last_was_empty_timeout = True

# 다음 미디어 패킷 전송 시
if last_was_empty_timeout:
    self._rtp_base_time = time.time()  # ← 리셋
    self._rtp_new_segment_after_empty = False
```

**영향**:
- Base_time 리셋 후 **패킷 타이밍이 재조정**됨
- 초기 불안정 (첫 수십 패킷 간격 오차 증가)
- `interval_max_ms: 28.82` (정상: 20ms) → 사용자가 "늘어짐" 감지

### 8.3 사용자 증상과의 매칭

| 사용자 보고 | 실제 원인 |
|------------|-----------|
| "온라인........................................" | 2.7초 gap → 클라이언트 재생 중단/버퍼 리셋 |
| "(으로 신청하실 수 있습니다... 안 들림)" | Gap 후 재생 복구 지연, 일부 패킷 버림 |
| "늘어지더니" | Base_time 리셋 후 interval 불안정 (28.82ms) |

---

## 9. 종합 진단 (RTP Dump 기반)

### 9.1 주요 문제

1. **Keepalive 간격이 너무 김** (3초)
   - 마지막 keepalive → 첫 미디어 = **2.691초 gap**
   - Jitter Buffer 설계 범위(20ms 기준) **135배 초과**
   - 클라이언트가 **세션 끊김으로 오인** → 재생 불안정

2. **Base_time 리셋**
   - Keepalive 후 첫 미디어에서 `base_time` 재설정
   - 초기 타이밍 불안정 (일부 패킷 간격 28.82ms까지 증가)
   - 누적되어 **재생 속도 불일치** 발생 가능

3. **RTP Timestamp 연속성은 정상**
   - Seq: 15260 → 15261~15263 → 15264 (연속)
   - Timestamp: +160씩 정확히 증가
   - **프로토콜 위반 없음** (초기 가설 부정)

### 9.2 사용자 증상과의 매칭

| 증상 | 원인 |
|------|------|
| "온라인........................................" | 2.7초 gap → 클라이언트 재생 중단/무음 |
| 괄호 부분 "안 들림" | Gap 후 Jitter Buffer 리셋, 초기 패킷 버림 |
| "늘어지더니" | Base_time 리셋 후 interval 불안정 (최대 28.82ms) |

---

## 10. 해결 방안

### Option 1: Keepalive 간격 단축 (★★★ 권장, 즉시 적용)

**현재**:
```python
ai_rtp_keepalive_interval_sec: float = 8.0  # 기본값
최소값 제한: 3.0초
```

**수정 (✅ 적용 완료)**:
```python
ai_rtp_keepalive_interval_sec: float = 0.5  # 500ms
최소값 제한: 0.5초
```

**효과**:
- Keepalive → 다음 미디어 최대 gap: **0.5초** (현재: 2.7초)
- Jitter Buffer 범위 내 (**25배 개선**)
- 클라이언트 재생 안정성 **대폭 향상**

**수정 파일**: `rtp_relay.py`
- Line 102: `ai_rtp_keepalive_interval_sec: float = 0.5`
- Line 175: fallback `= 0.5`
- Line 176: `max(0.5, min(...))`
- Line 1279: `v = float(os.environ.get(env_key, "0.5"))`
- Line 1284: `return max(0.5, min(v, 60.0))`

### Option 2: Base_time 리셋 제거 (보류)

**현재**:
- Keepalive 후 첫 미디어에서 `base_time` 재설정
- 타이밍 기준점 변경 → 초기 불안정

**수정안**:
```python
# Line 1513 제거 또는 조건 추가
# last_was_empty_timeout = True  # 제거
```

**단점**:
- Keepalive 간격이 0.5초로 단축되면 **base_time 리셋 필요성 감소**
- Option 1만으로도 충분할 가능성

### Option 3: PCM 큐 사이즈 증가 (선택)

**현재**: `maxsize=500` (청크 단위, 실제 ~250초 분량)

**효과**: 큐 부족 문제는 관찰되지 않음 (유지)

---

## 11. 코드 수정 상세

### 11.1 Keepalive 간격 단축 (✅ 적용 완료)

**파일**: `rtp_relay.py`

**수정 1: 기본값 (Line 102)**
```python
# Before
ai_rtp_keepalive_interval_sec: float = 8.0,

# After
ai_rtp_keepalive_interval_sec: float = 0.5,
```

**수정 2: Fallback (Line 175)**
```python
# Before
self._media_ai_rtp_keepalive_interval_sec = 8.0

# After
self._media_ai_rtp_keepalive_interval_sec = 0.5
```

**수정 3: 최소값 제한 (Line 176)**
```python
# Before
self._media_ai_rtp_keepalive_interval_sec = max(
    3.0, min(self._media_ai_rtp_keepalive_interval_sec, 60.0)
)

# After  
self._media_ai_rtp_keepalive_interval_sec = max(
    0.5, min(self._media_ai_rtp_keepalive_interval_sec, 60.0)
)
```

**수정 4: 환경변수 (Line 1279, 1284)**
```python
# Before (Line 1279)
v = float(os.environ.get(env_key, "8.0"))

# After
v = float(os.environ.get(env_key, "0.5"))

# Before (Line 1284)
return max(3.0, min(v, 60.0))

# After
return max(0.5, min(v, 60.0))
```

---

## 12. 즉시 확인 사항

### 12.1 수정 완료 항목 (✅)

1. **Keepalive 간격 단축**: 8.0초 → **0.5초** (5개 위치)
2. **최소값 제한 완화**: 3.0초 → **0.5초**
3. **환경변수 기본값**: "8.0" → **"0.5"**

### 12.2 테스트 시나리오

**시나리오 1: Repeat 응답 (Gap 재현)**
```
1. 질문: "기상 감정서는 어떻게 발급받나요?"
2. 응답 완료 대기
3. "다시 말해주세요" (repeat)
   → Gap 발생 (응답 7 → 8)
4. 오디오 품질 확인
```

**예상 결과**:
- **Before**: Gap 9초 + 미디어 재개 2.7초 = 늘어짐
- **After**: Gap 최대 0.5초 + 미디어 재개 0.5초 = **정상 재생**

### 12.3 로그 확인

**확인 항목**:
```bash
grep "rtp_ai_silence_keepalive_inject" app.log
# interval_sec: 0.5 확인

grep "rtp_base_time_reset_on_first_packet" app.log
# 빈도 감소 확인 (0.5초마다 keepalive → gap 짧아짐)
```

---

## 13. 권장 조치

### 즉시 (✅ 완료)

1. **Keepalive 간격 단축**: 8초 → **0.5초** (5개 위치 수정 완료)
   - 파일: `rtp_relay.py` Line 102, 175, 176, 1279, 1284

### 단기 (테스트 후 결정)

2. **테스트 실행**:
   - "다시 말해주세요" repeat 시나리오
   - Gap 후 오디오 품질 확인
   - RTP Dump 분석 (interval 0.5초 확인)

3. **추가 개선 검토** (필요 시):
   - Base_time 리셋 제거 (keepalive 후 타이밍 안정화)
   - PCM 큐 사이즈 조정 (현재는 정상)

### 중장기 (선택)

4. **TTS 미리 생성** (Gap 자체 제거)
5. **Adaptive interval 재검토** (현재는 고정 20ms 사용 중)

---

## 14. 예상 효과

### Before (수정 전)

```
Gap 11.7초
  ↓ Keepalive 3초마다 (3회)
  ↓ 마지막 keepalive → 첫 미디어: 2.7초
새 응답 시작
  ↓ Base_time 리셋
  ↓ 클라이언트 Jitter Buffer 혼란
  ↓ 재생 중단/불안정
사용자: "........................................" (늘어짐/안 들림)
```

### After (수정 후 - 0.5초 간격)

```
Gap 11.7초
  ↓ Keepalive 0.5초마다 (23회) ← 연속적 유지
  ↓ 마지막 keepalive → 첫 미디어: 최대 0.5초
새 응답 시작
  ↓ Base_time 리셋 (여전히 발생하지만 gap 짧아 영향 최소)
  ↓ 클라이언트 Jitter Buffer 정상 처리
사용자: 전체 문장 명료하게 청취 ✓
```

**개선폭**:
- Gap 감소: **2.7초 → 0.5초** (81% 감소)
- Keepalive 패킷 증가: 3개 → 23개 (대역폭 영향 무시 가능, 172 bytes × 20회 = 3.4KB)
- **재생 안정성 대폭 개선** 예상

---

## 15. 다음 단계

### 테스트 (필수)

1. **서버 재시작**: `python start_all.py` (수정 반영)
2. **통화 시작**: 1004번 호출
3. **Repeat 시나리오**:
   - 질문: "기상 감정서는 어떻게 발급받나요?"
   - 응답 완료 후 **10초 대기**
   - "다시 말해주세요"
4. **확인**:
   - 오디오 품질 (늘어짐/끊김 없음)
   - RTP Dump: keepalive interval 0.5초
   - app.log: `rtp_ai_silence_keepalive_inject` interval_sec: 0.5

### 추가 개선 (선택)

- Base_time 리셋 로직 검토 (keepalive 후 리셋 제거)
- 환경변수 설정 가이드 추가 (`SIPPBX_AI_RTP_KEEPALIVE_INTERVAL_SEC`)

---

**작성자**: AI Assistant  
**긴급도**: 높음 (사용자 경험 치명적)  
**상태**: ✅ **수정 완료** (Keepalive 0.5초), 테스트 대기  
**우선순위**: ★★★ 즉시 테스트 필요
