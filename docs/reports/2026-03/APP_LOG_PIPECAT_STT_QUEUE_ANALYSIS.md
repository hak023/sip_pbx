# app.log Pipecat / AI 응대 로직 점검 (STT 큐 백업)

## 1. 로그 구간 요약 (예: 782–1053)

- **통화**: call_id `ORCetBDwVO`, callee `1004`, Pipecat 경로 사용.
- **타임라인**: 11:59:03.405 ~ 11:59:28.xxx (약 25초).

## 2. 정상 동작 구간

| 시점 | 이벤트 | 의미 |
|------|--------|------|
| 11:59:03.405 | `call_session_marked_as_ai`, `ai_call_started_event_emitted` | AI 통화로 전환 |
| 11:59:03.405 | `🚀 [Pipecat] Starting Pipecat pipeline for AI call` | Pipecat 파이프라인 시작 |
| 11:59:03.407 | `pipecat_mode_enabled`, `pipecat_pipeline_args` | RTP가 Pipecat 모드, STT/TTS/VAD/RAG 등 모두 있음 |
| 11:59:03.419 | `✅ [Pipecat] Pipeline task started`, `ai_voicebot_pipecat_activated` | 파이프라인 태스크 생성·실행 |
| 11:59:03.873 | `stt_path_rtp_first` | RTP → STT 경로에 첫 패킷 투입 |
| 11:59:03.875 | `call_established` (caller 1003, callee AI) | 통화 연결 완료 |

즉, **파이프라인은 시작되었고**, **RTP는 caller 오디오를 STT 입력 큐에 계속 넣고 있음**.

## 3. 발견된 이슈

### 3.1 `pipecat_not_available` (VAD 래퍼)

```
"event": "pipecat_not_available", "note": "Pipecat 패키지가 없어 VAD 래퍼를 사용할 수 없습니다"
```

- **위치**: `vad_wrapper.py` — `pipecat.processors.frame_processor` / `pipecat.frames.frames` import 실패 시 `_PIPECAT_AVAILABLE = False`.
- **영향**: VAD 래퍼(로깅·Interruption 흡수)만 스킵되고, 원본 VAD는 그대로 사용. 파이프라인 자체는 동작.
- **권장**: 동일 환경에서 `import pipecat.processors.frame_processor` 등이 되는지 확인. 필요 시 `pip install pipecat-ai[google,silero]` 재설치.

### 3.2 Input Transport 미기동 — STT 큐 백업 (핵심)

- **증상**
  - `caller_rtp_to_stt_input`로 **RTP → 큐**는 계속 증가 (packet_count 1 → 1100+).
  - `stt_queue_size`가 0 → 999 → **1000**에서 멈춤 후 `stt_input_queue_full_dropping`, `stt_path_queue_full_drop` 다량 발생.
  - **한 번도 나오지 않는 로그**:
    - `pipecat_input_transport_started`
    - `stt_path_input_first`
    - `pipecat_audio_stream_started`
    - `stt_path_queue_first`
- **해석**
  - RTP는 `_pipecat_audio_queue`에 넣고 있음 (생산자 정상).
  - **Input Transport의 `_read_audio_loop()`가 시작되지 않아** `get_caller_audio_stream()`이 호출되지 않고, 큐를 소비하는 쪽이 없음.
  - `_read_audio_loop()`는 **StartFrame**을 받을 때만 `asyncio.create_task(self._read_audio_loop())`로 기동됨.
- **결론**: 이 구간에서는 **StartFrame이 Input Transport(파이프라인 첫 프로세서)에 도달하지 않았거나, 도달 전에 이미 큐가 백업**된 상태로 보는 것이 타당함.  
  → Pipecat 라이브러리 초기화 순서/타이밍 이슈 가능성 있음.

### 3.3 TTS 미송출

- `rtp_tts_queue_empty_timeout`이 **packets_sent: 0**으로 반복.
- 인사말(greeting)이 RTP로 나가지 않음.  
  → 파이프라인에서 인사말이 출력 단까지 도달하지 않았거나, Output 쪽으로 전달되지 않은 상태로 추정 (Input이 막혀 있어서 전체 파이프라인이 진행되지 않았을 가능성 있음).

### 3.4 487 CANCEL

- 11:59:03.466에 CANCEL / INVITE 487 수신 후 ACK 전송.
- 한쪽에서 통화를 취소한 것으로 보이며, 그 후에도 RTP/STT 경로 로그는 계속 찍힘 (다른 leg 또는 정리 지연).

## 4. 데이터 흐름 요약

```
[정상 기대]
RTP(caller) → _pipecat_audio_queue.put
                    ↓
Input Transport: get_caller_audio_stream() → _read_audio_loop() → push_frame(InputAudioRawFrame)
                    ↓
VAD → STT → RAG → TTS → Output → send_audio_to_caller()

[해당 로그에서 실제]
RTP → 큐 put 만 반복 → 큐 1000 찼음 → 드롭
Input Transport _read_audio_loop() 미기동 → get_caller_audio_stream() 미호출 → 큐 소비 없음
```

## 5. 적용한 코드 측 대응

### 5.1 Input Transport 폴백 (StartFrame 미수신 대비)

- **파일**: `rtp_transport.py` (SIPPBXInputTransport)
  - **ensure_audio_loop_started()**: 외부에서 호출 시 `_read_audio_loop()`를 강제로 한 번 시작 (이미 돌고 있으면 무시).
  - **process_frame()** 에서 첫 프레임 수신 시 **2초 후** `_read_audio_loop()`를 시작하는 **폴백 타이머** 예약.
  - StartFrame을 수신하면 폴백 타이머는 취소하고, 기존대로 즉시 `_read_audio_loop()` 시작.
- **파일**: `pipeline_builder.py` (build_and_run)
  - 파이프라인·태스크 생성 직후, **2초 뒤** 첫 프로세서(Input)의 `ensure_audio_loop_started()`를 호출하는 태스크를 `asyncio.create_task`로 예약.
- **효과**: 라이브러리가 StartFrame을 늦게 보내거나 아예 안 보내는 경우에도, 최대 약 2초 후에는 **큐 소비가 시작**되어 STT 큐가 1000으로 꽉 찬 뒤 계속 드롭되는 상황을 완화.

### 5.2 확인용 로그

- 폴백으로 루프가 시작되면 `pipecat_input_transport_start_fallback` (StartFrame 미수신 — 폴백으로 오디오 루프 시작) 로그가 남음.
- 정상적으로 StartFrame으로 기동되면 기존처럼 `pipecat_input_transport_started`, `stt_path_input_first` 등이 찍힘.

## 6. 점검 체크리스트 (AI 응대 / Pipecat)

1. **Pipecat 기동**
   - `✅ [Pipecat] Pipeline task started`, `ai_voicebot_pipecat_activated` 있는지.
2. **Input 소비 시작**
   - `pipecat_input_transport_started` 또는 `pipecat_input_transport_start_fallback` 중 하나가 나오는지.
   - `stt_path_queue_first` 또는 `stt_path_input_first` 가 나오는지 (큐 소비 시작).
3. **STT 큐 백업**
   - `stt_path_queue_high`, `stt_input_queue_full_dropping`, `stt_path_queue_full_drop` 이 반복되지 않는지.
4. **TTS 송출**
   - `rtp_tts_queue_empty_timeout` 의 `packets_sent` 가 0만 반복되지 않는지 (인사말 등 일부라도 전송되는지).
5. **VAD 래퍼**
   - `pipecat_not_available` 가 나오면, 해당 환경에서 pipecat import 가능 여부 확인.

## 7. 참고

- STT 경로·로그 의미: `docs/reports/DEBUG_LOG_VERIFICATION.md`, `docs/reports/STT_STREAMING_NOT_RECOGNIZING_USER_SPEECH.md`
- Orchestrator vs Pipecat 구조: `docs/design/ORCHESTRATOR_VS_PIPECAT_STRUCTURE.md`
