# Outbound Call RTP PCM Sender Thread TypeError 분석 및 수정

- **작성일**: 2026-04-01 15:30
- **상태**: 수정 완료
- **관련 call_id**: `outbound-ob-627eba51-60219613`
- **관련 파일**: `sip-pbx/src/media/rtp_relay.py`

---

## 1. 증상 (로그)

`10:57:56.538` 시점에 `pcm_sender_thread_error`가 연속 20건 이상 발생하며 RTP 패킷 전송이 중단됨.

```
"event": "pcm_sender_thread_error"
"error": "unsupported operand type(s) for +: 'NoneType' and 'float'"
"error_type": "TypeError"
"send_errors_total": 1 ~ 20+ (연속 발생)
```

## 2. 선행 경고 (에러 전 정황)

| 시각 | 이벤트 | 내용 |
|---|---|---|
| 10:57:34.880 | `tts_rtp_duration_mismatch` | Notifier vs Output 불일치 (19.4%) |
| 10:57:38.750 | `pcm_chunk_gap_large` | TTS 청크 간 gap **3870ms** (큐 고갈 위험) |
| 10:57:39.983 | `rtp_interval_violation` | 패킷 간격 **145.5ms** (예상 20ms) |
| 10:57:40.819 | `pcm_chunk_gap_large` | TTS 청크 간 gap **2064ms** |
| 10:57:44.506 | `pcm_chunk_gap_large` | TTS 청크 간 gap **3686ms** |
| 10:57:55.342 | `stt_input_queue_depth_spike` | STT 입력 큐 임계 초과 |
| 10:57:56.538 | **`pcm_sender_thread_error`** | **TypeError 연속 발생** |

## 3. 근본 원인 분석

### 버그 위치: `rtp_relay.py` — `stop_pipecat_mode()` 함수

#### 수정 전 코드 실행 순서 (잘못됨)
```python
# [1] _rtp_base_time을 None으로 리셋 ← 문제 발생 지점
self._rtp_base_time = None
self._rtp_last_send_time = None

# [2] sentinel을 큐에 투입 → 스레드가 종료 신호를 받음
pcm_q.put_nowait(None)

# [3] 스레드 join 대기 (최대 20초)
th.join(timeout=20.0)
```

#### 스레드 내부 코드 (계속 실행 중)
```python
# _pcm_sender_thread_main() 내부 — 매 루프마다 실행
target_time = self._rtp_base_time + (self._rtp_packets_sent_total * FIXED_INTERVAL_SEC)
#              ^^^^^^^^^^^^^^^^^^^
#              [1]에서 이미 None이 되었으므로: None + float → TypeError!
```

#### 타이밍 경쟁 조건
- `stop_pipecat_mode()`는 메인 스레드(또는 asyncio 태스크)에서 실행
- `_pcm_sender_thread_main()`은 별도 스레드에서 실행
- `_rtp_base_time = None` 이후 sentinel이 큐에 투입되지만, 스레드가 sentinel을 처리하기 **전에** 루프를 1회 이상 돌면서 `None + float` TypeError 발생
- sentinel 도달 전까지 모든 루프 반복에서 에러 → 연속 20건 이상 기록

## 4. 수정 내용

`_rtp_base_time` 리셋을 **스레드 join 완료 이후**로 이동.

```python
# 수정 후: sentinel 투입 → join → 리셋 순서로 변경
pcm_q.put_nowait(None)          # [1] sentinel 투입
th.join(timeout=20.0)           # [2] 스레드 종료 대기

# [3] 스레드 종료 확인 후 안전하게 리셋
self._rtp_base_time = None
self._rtp_last_send_time = None
```

## 5. 영향 범위

- **Outbound call 전용** 버그로 추정: Outbound 통화 종료 시 `stop_pipecat_mode()` 가 호출되는 경로에서 발생
- Inbound call도 동일 코드 경로를 사용하므로 동일한 수정이 적용됨
- `pcm_sender_thread_error` 발생 시 해당 패킷 전송이 누락되어 통화 상대방에게 음성 끊김이 발생할 수 있음

## 6. 추가 관찰: `pcm_chunk_gap_large`

에러 이전에 3회의 대규모 TTS 청크 간격 경고가 발생:
- **3870ms**, **2064ms**, **3686ms** — Google TTS 일괄 수집 방식(`google_tts_api_complete`)으로 인해 TTS 청크가 한꺼번에 투입되기 전 큐가 고갈되는 현상
- 이는 별개 이슈로, TTS 스트리밍 갭 개선이 필요할 수 있음
