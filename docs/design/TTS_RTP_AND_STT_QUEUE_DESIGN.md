# TTS→RTP 및 STT 입력 큐 설계

**목적**: TTS 생성 오디오를 RTP로 안정 전송하고, 수신 RTP를 STT에 전달하는 큐 아키텍처 설계.
**최종 수정**: 2026-03-30 (Continuous Silence + Drain 방식 반영)

---

## 1. TTS → RTP (PCM 큐 + 전용 스레드 20ms 격자)

### 1.1 아키텍처 개요

```
Google TTS API  ───►  DebugGoogleTTSService  ───►  SIPPBXOutputTransport
(스트리밍)            (일괄 수집 후 yield)          (send_audio_to_caller)
                                                         │
                                                         ▼
                                                  _pipecat_pcm_queue
                                                  (thread-safe queue.Queue)
                                                  maxsize=1000
                                                         │
                                                         ▼
                                              _pcm_sender_thread_main
                                              (전용 스레드, 20ms 격자)
                                                         │
                                          ┌──────────────┼──────────────┐
                                          ▼              ▼              ▼
                                     pcm_buffer     RTP 패킷 빌드    _tts_udp_out_queue
                                   (20ms 프레임)   (PCM→G.711/PCM)   (asyncio.Queue)
                                                                    maxsize=2048
                                                                         │
                                                                         ▼
                                                              이벤트 루프 sendto
                                                            (Windows Proactor 보호)
                                                                         │
                                                                         ▼
                                                                    Caller RTP
```

### 1.2 핵심 설계: Continuous Silence (연속 무음)

이전 방식(미디어 없으면 전송 중단 → 재개 시 base_time 재설정)은 타이밍 불일치와
오디오 늘어짐 현상을 유발했다. 현재는 **항상 20ms 간격으로 패킷 전송**한다.

```
시간축: ─────────────────────────────────────────────►
        [silence][silence][media][media][media][silence][silence]...
         20ms     20ms    20ms   20ms   20ms   20ms     20ms
```

- **`_rtp_base_time`**: 세션 최초 1회 설정, 이후 **절대 변경 없음**
- **미디어 없을 때**: `_PCM_SILENCE_20MS_16K_MONO` (640 bytes) 전송
- **미디어 있을 때**: pcm_buffer에서 20ms 프레임 pop하여 전송
- **효과**: RTP 스트림이 끊기지 않아 수신측 디코더 안정, 타이밍 drift 없음

### 1.3 TTS 오디오 일괄 수집 (Batch-before-Yield)

`DebugGoogleTTSService`는 Google TTS 스트리밍 API의 청크를 **모두 수집한 후** 일괄 yield한다.

```python
# 스트리밍 → 일괄 변환 (debug_google_tts.py)
collected_frames = []
async for frame in super().run_tts(text):
    collected_frames.append(frame)
for frame in collected_frames:
    yield frame
```

- **이유**: 스트리밍 청크 간 네트워크 지연(100~500ms)이 RTP 20ms 소비 속도보다 느리면
  PCM 큐가 고갈되어 무음이 삽입되고, 오디오가 늘어짐
- **효과**: 한 문장의 모든 오디오가 동시에 PCM 큐에 적재 → 연속 재생 보장

### 1.4 세션 종료 시 Graceful Drain

파이프라인 종료 시 PCM 큐에 남아있는 오디오를 끝까지 전송 후 종료한다.

```
stop_pipecat_mode() → pcm_q.put(None)  [sentinel]
                            │
                    _pcm_sender_thread_main:
                    1. sentinel 수신
                    2. 큐 잔여 청크 모두 pcm_buffer로 이동
                    3. _session_ending = True
                    4. pcm_buffer 소진까지 20ms 격자 전송 계속
                    5. pcm_buffer 비면 → rtp_sender_session_end 로그 후 return
```

- **이전 문제**: TTS 7.48초+2.48초 오디오가 PCM 큐에 적재 후, 파이프라인이 ~4초 만에
  종료되면서 나머지 ~6초 분량이 폐기됨
- **해결**: sentinel 수신 시 잔여 버퍼를 20ms 페이싱으로 완전 소진 후 스레드 종료
- `th.join(timeout=20.0)` — 최대 20초 대기 (긴 TTS 드레인 고려)

### 1.5 주요 파라미터

| 파라미터 | 값 | 설명 |
|---|---|---|
| `_pipecat_pcm_queue` maxsize | 1000 | ~31초 분량 (16kHz 16-bit PCM 기준) |
| `_tts_udp_out_queue` maxsize | 2048 | UDP 전송 대기 패킷 |
| `FIXED_INTERVAL_SEC` | 0.020 | 고정 20ms RTP 패킷 간격 |
| `_PCM_SILENCE_20MS_16K_MONO` | 640 bytes | 20ms 무음 PCM |
| UDP 큐 적체 경고 | depth ≥ 48 | `tts_udp_out_queue_backlog_high` |
| PCM 큐 적체 경고 | qsize ≥ 800 | `rtp_tts_pcm_queue_backlog_high` |
| pcm_chunk_gap_large 경고 | gap > 100ms | TTS 청크 간 갭 (큐 고갈 위험) |
| sender thread join timeout | 20.0초 | 드레인 완료 대기 |

### 1.6 로깅 체계

| 이벤트 | 레벨 | 의미 |
|---|---|---|
| `pcm_chunk_queued` | info | TTS PCM 청크 큐 추가 |
| `pcm_chunk_gap_large` | warning | 청크 간 100ms+ 갭 |
| `rtp_tts_send_window_stats` | info | 최근 50패킷 간격 통계 |
| `rtp_sender_session_end_draining` | info | sentinel 수신, 잔여 버퍼 드레인 시작 |
| `rtp_sender_session_end` | info | 발송 루프 종료 (잔여 버퍼 소진 완료) |
| `rtp_health_snapshot` | info | 주기적 RTP 상태 스냅샷 |
| `rtp_absolute_timing_summary` | info | 세션 종료 시 타이밍 요약 |

---

## 2. STT 입력 (RTP → Pipecat)

### 2.1 아키텍처

```
Caller RTP ─► RTP 수신 콜백 ─► rtp_to_pcm16k ─► _pipecat_audio_queue
                                                  (asyncio.Queue)
                                                  maxsize=1000
                                                       │
                                                       ▼
                                          get_caller_audio_stream()
                                          (async generator)
                                                       │
                                                       ▼
                                          SIPPBXInputTransport
                                          (InputAudioRawFrame push)
                                                       │
                                                       ▼
                                              VAD → STT → Pipeline
```

### 2.2 설계 원칙

- **단일 생산자**: RTP 수신 콜백 (동기 소켓 이벤트)
- **단일 소비자**: `get_caller_audio_stream()` (async generator)
- **비블로킹 적재**: `put_nowait` — 소켓 이벤트 루프 블로킹 방지
- **QueueFull 시 드롭**: 오래된 RTP보다 최신 RTP가 중요

### 2.3 Input Transport 시작 전략

```
StartFrame 수신 → push → _delayed_start_audio_loop(0.05초)
                              ↓
                          오디오 루프 시작
                          
폴백: 2.0초 후 StartFrame 미수신 시 강제 시작
      (pipeline_builder에서 ensure_audio_loop_started 호출)
```

### 2.4 주요 파라미터

| 파라미터 | 값 | 설명 |
|---|---|---|
| `_pipecat_audio_queue` maxsize | 1000 | ~20초 분량 |
| `get_caller_audio_stream` timeout | 5.0초 | 큐 대기 타임아웃 (STT keep-alive) |
| Input Transport 지연 시작 | 0.05초 | StartFrame 후 오디오 루프 시작 |
| 폴백 시작 | 2.0초 | StartFrame 미수신 시 강제 시작 |

---

## 3. AEC (음향 에코 제거)

- TTS 오디오(far-end)를 AEC 프로세서에 참조 등록
- `_aec_lock`으로 PCM sender thread ↔ RTP 수신 콜백 동기화
- `AEC_FRAME_BYTES` 단위로 처리
- **성능 모니터링**: AEC 락 점유 > 12ms 시 `tts_sender_aec_lock_hold_ms` 경고

---

## 4. 관련 코드 위치

| 내용 | 파일 |
|---|---|
| PCM 큐·sender thread·UDP 큐 | `src/media/rtp_relay.py` — `_pcm_sender_thread_main`, `send_audio_to_caller`, `stop_pipecat_mode` |
| TTS 일괄 수집 | `src/ai_voicebot/pipecat/services/debug_google_tts.py` — `run_tts` |
| Output Transport | `src/ai_voicebot/pipecat/rtp_transport.py` — `SIPPBXOutputTransport` |
| Input Transport | `src/ai_voicebot/pipecat/rtp_transport.py` — `SIPPBXInputTransport` |
| STT 입력 큐 | `src/media/rtp_relay.py` — `get_caller_audio_stream`, `_pipecat_audio_queue` |
| 파이프라인 빌드 | `src/ai_voicebot/pipecat/pipeline_builder.py` |
