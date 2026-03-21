# AI 응대 디버깅 로그 강화 및 폴백 버그 수정

## 1. 로그(1793–1907)에서 확인된 현상

- Pipecat 파이프라인 기동: `✅ [Pipecat] Pipeline task started`, `ai_voicebot_pipecat_activated`
- RTP → STT 큐 투입: `stt_path_rtp_first`, `caller_rtp_to_stt_input` (packet_count·stt_queue_size 증가)
- **Input 소비 미시작**: `pipecat_input_transport_started`, `stt_path_input_first`, `pipecat_input_transport_start_fallback` **전부 없음**
- **STT 큐 백업**: `stt_path_queue_high` (queue_size 800), 이후 1000 도달 시 드롭
- **TTS 미송출**: `rtp_tts_queue_empty_timeout` 에서 `packets_sent: 0` 반복
- **pipecat_not_available**: VAD 래퍼용 pipecat import 실패 (별도 이슈)

→ **원인**: Input Transport의 `_read_audio_loop()`가 시작되지 않아 `get_caller_audio_stream()`이 호출되지 않고, 큐만 쌓임. 인사말(TTS)도 파이프라인 하류로 나가지 못함.

---

## 2. 수정한 버그: 폴백 대상 프로세서 인덱스

- **원인**: Pipecat `Pipeline` 은 `_processors = [source] + processors + [sink]` 로 보관함.  
  우리가 넘긴 첫 프로세서는 `transport.input()` 이지만, 파이프라인 내부에서는 **인덱스 1** (0은 `PipelineSource`).
- **기존 코드**: `procs[0].ensure_audio_loop_started()` 호출 → `procs[0]` 은 PipelineSource 로 `ensure_audio_loop_started` 없음 → 폴백이 사실상 동작 안 함.
- **수정**: `procs[1]` (우리 Input Transport)에 대해 `ensure_audio_loop_started()` 호출하도록 변경.

**파일**: `sip-pbx/src/ai_voicebot/pipecat/pipeline_builder.py`  
- 폴백에서 `procs[1]` 사용, 프로세서 타입·메서드 존재 여부 로그 추가.

---

## 3. 추가한 디버깅 로그

### 3.1 Pipeline Builder (`pipeline_builder.py`)

| 이벤트 | 의미 |
|--------|------|
| `input_fallback_check` | 2초 폴백 시점에 procs[1] 타입·`ensure_audio_loop_started` 존재 여부 |
| `input_fallback_applied` | `ensure_audio_loop_started()` 호출 완료 |
| `input_fallback_skipped` | procs 수 부족 등으로 폴백 미실행 |
| `input_fallback_no_method` | procs[1]에 `ensure_audio_loop_started` 없음 |
| `pipeline_runner_about_to_start` | `runner.run(task)` 진입 직전, processor 수·첫 사용자 프로세서(procs[1]) 타입 |

### 3.2 Input Transport (`rtp_transport.py`)

| 이벤트 | 의미 |
|--------|------|
| `input_transport_first_frame` | Input에 **첫 프레임** 도달 시 (프레임 타입, StartFrame 여부) — StartFrame 수신 여부 확인용 |
| `input_transport_startframe_received` | **StartFrame** 수신 시 (즉시 오디오 루프 시작) |
| `input_audio_loop_task_created` | `_read_audio_loop()` 태스크 생성 시 — 큐 소비 시작 예상 시점 |
| `input_ensure_audio_loop_called` | 외부에서 `ensure_audio_loop_started()` 호출 시 (이미 루프 동작 중 여부 포함) |
| (기존) `pipecat_input_transport_started` | `_read_audio_loop()` 진입 |
| (기존) `pipecat_input_transport_start_fallback` | StartFrame 미수신으로 2초 폴백으로 루프 시작 |

### 3.3 RAG Processor (`rag_processor.py`)

| 이벤트 | 의미 |
|--------|------|
| `send_greeting_started` | RAG `send_greeting()` 진입 — Phase1/2 인사말 생성·전송 시작 |

---

## 4. 점검 시 확인할 로그 순서 (정상 시)

1. `pipeline_runner_about_to_start` (processor_count, first_user_proc=SIPPBXInputTransport)
2. **경로 A**: `input_transport_first_frame` (is_start_frame=true) → `input_transport_startframe_received` → `input_audio_loop_task_created` → `pipecat_input_transport_started`  
   **경로 B**: 2초 후 `input_fallback_check` → `input_fallback_applied` → `input_ensure_audio_loop_called` → `input_audio_loop_task_created` → `pipecat_input_transport_started`
3. `pipecat_audio_stream_started` (RTP의 `get_caller_audio_stream()` 진입)
4. `stt_path_queue_first` 또는 `stt_path_input_first` (큐 소비 시작)
5. `send_greeting_started` → `greeting_phase1_sent` → (Phase2) `greeting_phase2_sent`
6. `rtp_tts_queue_empty_timeout` 에서 `packets_sent` > 0 구간 발생

`input_transport_first_frame` 이 한 번도 없으면 StartFrame이 Input에 오지 않는 것이고, `input_fallback_applied` 도 없으면 폴백이 적용되지 않은 것(이번에 procs[1] 수정으로 해결).

---

## 5. 참고

- STT 큐 백업·전체 흐름: `docs/reports/APP_LOG_PIPECAT_STT_QUEUE_ANALYSIS.md`
- Barge-in·로그: `docs/reports/DEBUG_LOG_VERIFICATION.md`
