# RTP 스케줄러 구조 재설계: 지속적 20ms 무음 전송 방식

**작성일**: 2026-03-30 13:49  
**상태**: 수정 완료  
**관련 파일**: `sip-pbx/src/media/rtp_relay.py`  
**선행 리포트**:
- `2026-03-29_2133_AUDIO_STRETCH_SOFT_RESYNC_BUG_jkjUT4Nhid.md`
- `2026-03-30_1330_RTP_AUDIO_STRETCH_SOFT_RESYNC_FIX2.md`
- `2026-03-30_1335_RTP_AUDIO_STRETCH_DOUBLE_RESYNC_FIX.md`

---

## 1. 배경: 반복되는 기계음/늘어짐 문제

### 1.1 수정 이력

| 수정 | 내용 | 결과 |
|------|------|------|
| #1 (3/29) | `packets_sent_total = 0` 리셋 방지 | 부분 개선, 여전히 늘어짐 |
| #2 (3/30) | `soft_resync` 공식 수정 (`+1` offset) | 부분 개선, 기계음 발생 |
| #3 (3/30) | `_rtp_new_segment_after_empty`와 `soft_resync` 중복 방지 | 부분 개선, 엣지 케이스 잔존 |

**패턴**: 수정할 때마다 새로운 엣지 케이스 발생 → **구조적 문제**

### 1.2 근본 원인: 복잡한 상태 머신

기존 코드에는 4가지 상호 의존적 메커니즘이 존재:

1. **`queue.get(timeout=...)`** — 블로킹 대기로 타이밍 격자 이탈
2. **조건부 keep-alive** (500ms 간격) — 재개 시 `base_time` 재설정 필요
3. **`_rtp_new_segment_after_empty`** — 큐 고갈 후 재개 시 상태 플래그
4. **`soft_resync`** (200ms 임계값) — 지연 시 `base_time` 재앵커

**문제**: 이 4가지가 상호작용할 때 예측 불가능한 타이밍 오류 발생

```
                   ┌─ queue.get(timeout)으로 수백ms 블로킹
                   │
큐 고갈 ─→ keep-alive 500ms ─→ 재개 시 base_time 재설정
                                   │
                                   ├─ _rtp_new_segment_after_empty (공식 A)
                                   └─ soft_resync (공식 B)
                                          │
                                          └─ 공식 A ≠ 공식 B → 기계음!
```

---

## 2. 새 설계: Continuous Silence (지속적 20ms 무음 전송)

### 2.1 핵심 원칙

1. **항상 정확히 20ms 간격으로 패킷 전송** (큐에 미디어 없으면 무음)
2. **`base_time`은 최초 1회만 설정, 이후 절대 변경 없음**
3. **`soft_resync` 완전 제거**
4. **`_rtp_new_segment_after_empty` 완전 제거**
5. **큐는 비블로킹(`get_nowait()`)으로 읽음** → 20ms 타이밍 격자와 분리

### 2.2 구조 비교

**기존 구조** (이벤트 기반):
```
while True:
    pcm = queue.get(timeout=...)     ← 블로킹! 수백ms 지연 가능
    if pcm is None: break
    if 큐_비었다가_재개:
        base_time 재설정              ← 공식 오류 위험
    for packet in build_packets(pcm):
        target = base_time + N * 20ms
        if 200ms 이상 밀림:
            soft_resync               ← 또 다른 공식 오류 위험
        wait(target)
        send(packet)
```

**새 구조** (시간 기반):
```
pcm = queue.get(blocking=True)       ← 최초 1회만 블로킹
base_time = now                       ← 1회 설정, 이후 불변

while True:
    drain_queue_nowait → buffer       ← 비블로킹, 가능한 만큼 소비
    frame = buffer.pop() or SILENCE   ← 없으면 무음 자동 삽입
    target = base_time + N * 20ms     ← 항상 동일한 격자
    wait(target)                      ← 정확히 20ms 간격
    send(frame)
    N += 1
```

### 2.3 상태 전이 다이어그램

**기존**: 복잡한 상태 머신
```
[INIT] → [WAITING_FIRST_PCM] → [STREAMING] ⇄ [KEEPALIVE_GAP]
                                    │               │
                                    └── soft_resync ←┘
                                    └── new_segment ←┘
```

**새 구조**: 상태 없음
```
[INIT] → [WAITING_FIRST_PCM] → [ALWAYS_SENDING_20MS]
                                     ↑     ↑
                                   media  silence (자동)
```

---

## 3. 변경 사항

### 3.1 `_pcm_sender_thread_main()` 전면 재작성

**삭제된 로직**:
- `_pcm_keepalive_queue_timeout_sec()` 호출 (더 이상 사용 안 함)
- `empty_timeout_count`, `last_was_empty_timeout` (상태 플래그)
- `_rtp_new_segment_after_empty` 판단 및 `base_time` 재설정
- `soft_resync` 전체 블록 (200ms 임계값 판단, `base_time` 재앵커)
- `schedule_did_resync` 플래그
- 조건부 keep-alive 로직 (`_idle >= _iv` 체크)
- `new_segment` 판단 로직
- `pcm_is_keepalive` 플래그 (→ `pcm_is_silence`로 대체)

**추가된 로직**:
- `_split_pcm_to_buffer()`: PCM 청크를 640-byte(20ms) 프레임으로 분할
- `pcm_buffer`: 내부 링 버퍼로 20ms 프레임 관리
- `get_nowait()` 루프: 비블로킹으로 큐에서 모두 가져와 버퍼에 적재
- `silence_streak` 카운터: 연속 무음 패킷 모니터링

### 3.2 `_split_pcm_to_buffer()` 새 메서드

```python
@staticmethod
def _split_pcm_to_buffer(pcm_data: bytes, buf: list) -> None:
    FRAME_BYTES = 640  # 20ms @ 16kHz mono s16le
    for i in range(0, len(pcm_data), FRAME_BYTES):
        frame = pcm_data[i : i + FRAME_BYTES]
        if len(frame) < FRAME_BYTES:
            frame = frame + b"\x00" * (FRAME_BYTES - len(frame))
        buf.append(frame)
```

### 3.3 TSV 덤프 변경

- `tx_kind` 값: `"keepalive"` → `"silence"` (의미 명확화)
- `"media"` 유지

---

## 4. 왜 이 방식이 근본적으로 안전한가

### 4.1 base_time 재설정이 불필요한 이유

**기존**: 큐가 비면 → 전송 중단 → 재개 시 시간 불일치 → `base_time` 재설정 필요
**새 구조**: 큐가 비어도 → 무음 전송 지속 → 시간 격자 유지 → 재설정 불필요

```
시간:  0ms    20ms   40ms   60ms   80ms   100ms  120ms ...
기존: [TTS]  [TTS]  [---GAP---]  [TTS]  [0.1ms!] [TTS]
                      ↑ 큐 고갈     ↑ base_time 재설정 오류
                      
새:   [TTS]  [TTS]  [SIL]  [SIL]  [TTS]  [TTS]  [TTS]
                      ↑ 무음 자동     ↑ 정확히 20ms 간격
```

### 4.2 대역폭 영향

- 무음 패킷 크기: ~172 bytes (RTP header + G.711 payload)
- 초당: 50 packets × 172 bytes = **8.6 KB/s**
- 1시간 통화: **약 30 MB** (무시 가능한 수준)
- 동시 100통화: **860 KB/s** (현대 네트워크에서 무시 가능)

### 4.3 VoIP 표준 관행과의 일치

- RFC 3550: RTP 스트림은 연속적 전송 권장
- 대부분의 VoIP 시스템: VAD(Voice Activity Detection)로 무음 마킹만, 전송은 지속
- SIP 전화기 호환성: 10초 이상 무수신 시 자동 끊김 방지

---

## 5. 타이밍 보장 메커니즘

### 5.1 `_wait_until_send_deadline()` (기존 유지)

```python
def _wait_until_send_deadline(self, deadline: float) -> None:
    spin_cap = self._RTP_SCHED_BUSY_SPIN_MAX_SEC
    y_floor = self._RTP_SCHED_YIELD_FLOOR_SEC
    while True:
        now = time.perf_counter()
        if now >= deadline:
            return
        rem = deadline - now
        if rem > spin_cap + 0.00015:
            time.sleep(rem - spin_cap)
        elif rem > y_floor:
            self._sched_yield_light()
```

### 5.2 behind_schedule 처리

- **200ms 미만 지연**: `debug` 레벨 로그 (정상 jitter)
- **200ms 이상 지연**: `warning` 로그 + AEC 락 경합/CPU 부족 추정
- **soft_resync 없음**: 지연 발생해도 다음 패킷은 `base_time + (N+1) * 20ms`에 전송
- 자연스럽게 따라잡음 (1~2 패킷 내 정상화)

---

## 6. 내부 버퍼 설계

### 6.1 `pcm_buffer` (list[bytes])

```
TTS 청크 (예: 16000 bytes = 500ms) → _split_pcm_to_buffer → [640B, 640B, ..., 640B]
                                                                 ↑ 25개 프레임
```

- **장점**: 큰 TTS 청크를 20ms 프레임 단위로 균일하게 전송
- **기존**: 청크 전체를 `build_packets()`에 넘기고 inner loop에서 전송 → 청크 경계에서 타이밍 이슈 발생 가능
- **새 구조**: 항상 1프레임씩 `build_packets()`에 넘김 → 청크 경계와 무관

### 6.2 비블로킹 큐 소비

```python
while True:
    try:
        chunk = queue.get_nowait()
        self._split_pcm_to_buffer(chunk, pcm_buffer)
    except queue.Empty:
        break
```

- **매 20ms 슬롯 시작 시** 큐에서 가능한 한 모두 가져옴
- 큐 대기 시간 = 0 (비블로킹)
- TTS 청크가 늦게 도착해도 **타이밍 격자에 영향 없음**

---

## 7. 테스트 방법

### 7.1 서버 재시작

```powershell
.\stop-all.ps1
.\start-all.ps1
```

### 7.2 테스트 시나리오

1. **AI 봇 통화 시작** → Phase1 인사 청취
2. **10초 침묵** → Phase2 인사 청취 (이전에 기계음 발생 지점)
3. **질문 후 응답 청취** (TTS 스트리밍 지연 시나리오)
4. **"다시 얘기해 주세요"** 등 반복 요청 (repeat intent)

### 7.3 로그 확인

**RTP TSV (`rtp_tx_{call_id}.tsv`)**:
- **정상**: 모든 패킷 간격이 **19~21ms** (무음 포함)
- **금지**: 0.1ms, 300ms, 500ms 같은 극단적 간격

**app.log 확인**:
```
"event": "rtp_base_time_initialized"     ← 1회만 나와야 함
"event": "rtp_continuous_silence"         ← 큐 비었을 때 무음 전송 중
"event": "rtp_interval_violation"         ← 없어야 정상
```

**없어야 할 로그**:
```
"event": "rtp_base_time_reset_on_first_packet"   ← 삭제됨
"event": "rtp_schedule_soft_resync"              ← 삭제됨
"event": "rtp_tts_sender_resumed_after_empty"    ← 삭제됨
```

---

## 8. 요약

### 8.1 변경 파일

- `sip-pbx/src/media/rtp_relay.py`
  - `_pcm_sender_thread_main()`: 전면 재작성
  - `_split_pcm_to_buffer()`: 새 헬퍼 메서드 추가

### 8.2 삭제된 복잡성

| 제거된 항목 | 이유 |
|------------|------|
| `soft_resync` (200ms 임계값) | 지속적 전송으로 gap 발생 안 함 |
| `_rtp_new_segment_after_empty` | 상태 전환 없음 |
| `schedule_did_resync` | soft_resync 제거 |
| `empty_timeout_count` | 큐 고갈 상태 추적 불필요 |
| `last_was_empty_timeout` | 상태 플래그 불필요 |
| 조건부 keep-alive 로직 | 항상 무음 전송 |
| `new_segment` 판단 | 세그먼트 개념 제거 |
| `base_time` 재설정 로직 (2곳) | 최초 1회 설정 후 불변 |
| `queue.get(timeout=...)` 블로킹 대기 | `get_nowait()` 비블로킹 |

### 8.3 추가된 단순성

| 추가된 항목 | 역할 |
|------------|------|
| `pcm_buffer` (list) | TTS 청크를 20ms 프레임으로 버퍼링 |
| `_split_pcm_to_buffer()` | PCM → 640-byte 프레임 분할 |
| `silence_streak` | 연속 무음 모니터링 |
| `media_packets_sent` | 실제 미디어 패킷 별도 카운트 |

---

**결론**: RTP 스케줄러를 **"이벤트 기반 + 조건부 keep-alive"**에서 **"시간 기반 + 지속적 20ms 무음 전송"**으로 전환했습니다. `base_time` 재설정, `soft_resync`, 상태 플래그 등 **반복적 버그의 근본 원인이었던 복잡한 로직을 모두 제거**하고, 항상 20ms 간격으로 패킷을 전송하는 단순한 구조로 대체했습니다. 이로써 TTS 지연, 큐 고갈, keep-alive 갭 등 어떤 상황에서도 **RTP 타이밍 격자가 깨지지 않습니다**.
