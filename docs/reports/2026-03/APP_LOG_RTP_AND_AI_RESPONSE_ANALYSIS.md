# 로그 분석 리포트: RTP 미전송 및 AI 응대 (BZlthevU1Q)

**대상**
- `app.log` 2831–2989 (통화 BZlthevU1Q, 2026-03-13 13:31:59–13:32:15)
- 콘솔 로그: StartFrame not received yet, 서버 종료 시 `ValueError: I/O operation on closed file`

**요약**
- 인사말(Phase1/2) 생성·파이프라인 전송까지는 정상이나 **RTP로 한 건도 전송되지 않음** (packets_sent: 0).
- 콘솔에는 **BargeInSuppressProcessor#0**, **RAGLLMProcessor#0** 의 “StartFrame not received yet” 에러가 계속 기록됨.
- 서버 종료 시 로그 파일이 먼저 닫힌 뒤 백그라운드 태스크가 로깅을 시도해 **ValueError: I/O operation on closed file** 발생.

---

## 1. RTP 미전송 (packets_sent: 0)

### 1.1 로그에서 보이는 흐름

| 시각(대략) | 이벤트 | 의미 |
|------------|--------|------|
| 13:32:09.548 | input_transport_first_frame (StartFrame), input_transport_startframe_received | Input까지 StartFrame 도달·오디오 루프 시작 |
| 13:32:09.551 | barge_in_suppress_passed (OutputTransportMessageUrgentFrame) | 바지인 쪽으로 1프레임 통과 |
| 13:32:09.980–10.050 | stt_path_rtp_first, send_greeting_started, greeting_phase1_sent, rag_greeting_blocking_start | RTP→STT 경로 가동, 인사말 Phase1 전송·RAG 블로킹 진입 |
| 13:32:10.503 | rtp_tts_queue_empty_timeout, **packets_sent: 0** | TTS→RTP 구간에서 1초 동안 전송된 패킷 0개 |
| 13:32:11.512, 12.523 | rtp_tts_queue_empty_timeout 반복, **packets_sent: 0** | 계속 0건 전송 |
| 13:32:15.895 | BYE 수신, bye_cleanup_triggered | 통화 종료 시점까지도 RTP 전송 없음 |

즉, **인사말 텍스트는 RAG에서 생성되어 파이프라인으로 넘어갔지만, TTS→Output Transport→RTP Relay 구간을 타고 caller 쪽으로 나간 패킷이 없음.**

### 1.2 콘솔 에러와의 연결

콘솔에는 동일 통화 구간에 다음이 반복 기록됨.

- `BargeInSuppressProcessor#0 Trying to process InputAudioRawFrame#N ... but StartFrame not received yet`
- `RAGLLMProcessor#0 Trying to process LLMFullResponseStartFrame#1 / TextFrame#1 / LLMFullResponseEndFrame#1 but StartFrame not received yet`

Pipecat `FrameProcessor` 는 **StartFrame을 먼저 받아야** `_check_started` 를 통과하고, 그렇지 않으면 위와 같이 ERROR 로그를 남기며 동작이 제한될 수 있음.  
그 결과:

- **입력 경로**: StartFrame이 BargeInSuppressProcessor에 “정식” 전달되지 않아, 하류(STT, RAG)로의 프레임 흐름이 꼬이거나 지연될 수 있음.
- **출력 경로**: RAGLLMProcessor가 StartFrame을 받지 못한 상태에서 인사말(TextFrame 등)을 처리하게 되면, Pipecat 내부에서 해당 프레임을 버리거나 TTS로 넘기지 않을 수 있음.

따라서 **RTP가 0인 현상은 “StartFrame이 하류 프로세서들에 제대로 전달되지 않아, TTS→Output→RTP 경로가 활성화되지 않은 것”과 일치**함.

### 1.3 이미 적용된 수정 (StartFrame)

- `BargeInSuppressProcessor.process_frame()` 에 **`await super().process_frame(frame, direction)`** 가 추가되어 있음 (ERROR_REPORT_STARTFRAME_AND_TTS.md 반영).
- 이 수정이 적용된 상태에서 **서버를 재시작**하면, 같은 시나리오에서 “StartFrame not received yet” 가 사라지고 RTP가 나가기 시작할 가능성이 높음.
- 분석에 사용한 로그(13:32)가 **수정 반영 전 빌드**에서 나온 것이라면, 재기동 후 동일 통화를 다시 테스트해 보는 것이 좋음.

### 1.4 RTP 미전송 정리

- **현상**: `rtp_tts_queue_empty_timeout` 이며 `packets_sent` 가 항상 0.
- **원인**: StartFrame 미전달로 인한 Pipecat 프로세서 동작 제한 → TTS 출력이 RTP까지 전달되지 않음.
- **대응**: BargeInSuppressProcessor 의 `super().process_frame()` 적용 후 **서버 재시작**으로 확인. 문제가 남으면 TTS→Output Transport→RTP Relay 구간 로그 추가로 경로별 전달 여부 확인 권장.

---

## 2. AI 응대 동작 요약

### 2.1 정상으로 보이는 부분

- AI Takeover(no_answer_timeout_activating_ai) 후 Pipecat 기동, pipeline_built, input_transport_first_frame(StartFrame), pipecat_input_transport_started.
- RTP→STT: caller_rtp_to_stt_input, stt_path_rtp_first, stt_path_queue_first, input_audio_frame_to_pipeline (frame_count 1~200) → **입력 오디오는 파이프라인까지 유입됨.**
- RAG 인사말: send_greeting_started, rag_llm_greeting_phase1/phase2, greeting_phase1_sent, rag_greeting_blocking_start → **Phase1/2 텍스트 생성 및 “전송” 로그까지는 찍힘.**

### 2.2 문제가 되는 부분

- **TTS → RTP**: greeting_phase1_sent 이후에도 `tts_sending_active: false`, `packets_sent: 0` 이 계속됨.  
  → 인사말이 TTS를 거쳐 Output Transport → RTP Relay로 나가지 못함.
- 콘솔의 **RAGLLMProcessor “StartFrame not received yet”** 와 맞물려, **인사말 프레임이 Pipecat 내부에서 정상 처리되지 않았을 가능성**이 큼.

### 2.3 AI 응대 정리

- **인사말 생성·파이프라인 상 “전송” 로그**까지는 정상.
- **실제 음성(caller에게 RTP로 전달)** 은 되지 않음 → 위 1절의 StartFrame/TTS→RTP 경로 원인과 동일 이슈로 보는 것이 타당함.

---

## 3. 서버 종료 시 ValueError: I/O operation on closed file

### 3.1 현상

- `asyncio.run()` 종료 과정에서 **“Log file closed successfully”** 로그 직후, 다음 태스크들에서 예외 발생:
  - `SIPPBXInputTransport._read_audio_loop()` (rtp_transport.py 205행): `pipecat_input_transport_stopped` 로깅 시
  - `PipelineBuilder.build_and_run()` (pipeline_builder.py 372행): `stop_pipecat()` → rtp_relay.py 1282행 `pipecat_mode_stopped` 로깅 시
  - 동일 `build_and_run` 374행: `stop_pipecat_mode_failed` 로깅 시
- 공통: **structlog가 이미 닫힌 파일(또는 스트림)에 쓰려다 `ValueError: I/O operation on closed file`** 발생.

### 3.2 원인

- 서버 종료 시 **메인 프로세스에서 로깅 파일/핸들을 먼저 닫음**.
- 그 뒤에도 **백그라운드 태스크**(Input Transport 오디오 루프, Pipecat build_and_run 의 finally → stop_pipecat 등)가 정리 과정에서 `logger.info()` / `logger.warning()` 를 호출함.
- 이때 structlog가 닫힌 file 객체에 print → **ValueError** 발생.

### 3.3 권장 대응

- **정리/종료 경로에서의 로깅**을 try/except 로 한 번 감싸서, “I/O operation on closed file” 등은 무시하거나 별도 처리:
  - `rtp_transport.py`: `_read_audio_loop()` 의 `finally` 블록 안 `logger.info(...)` 두 곳.
  - `rtp_relay.py`: `stop_pipecat_mode()` 내 `logger.info("pipecat_mode_stopped", ...)`.
  - `pipeline_builder.py`: `build_and_run()` 의 `logger.warning("stop_pipecat_mode_failed", ...)`.
- 또는 **공통 유틸**을 두고, “shutdown 중일 때는 로깅 스킵/안전 로깅” 하도록 할 수 있음.
- 목적: **종료 순서에 따른 예외를 막고**, 실제 오류는 그대로 로그에 남기기.

**적용**: rtp_transport.py (`_read_audio_loop` finally), rtp_relay.py (`stop_pipecat_mode`), pipeline_builder.py (`stop_pipecat_mode_failed` 로깅) 에서 해당 로깅을 `try/except (ValueError, OSError)` 로 감싸 두었음.

---

## 4. 체크리스트 (재현·검증용)

| 항목 | 확인 방법 |
|------|-----------|
| BargeInSuppressProcessor 수정 반영 | 서버 재시작 후 동일 통화에서 콘솔에 “StartFrame not received yet” 없음 |
| RTP 전송 | 동일 통화에서 `packets_sent` > 0, `rtp_tts_queue_empty_timeout` 없거나 감소 |
| 인사말 청취 | caller 측에서 “안녕하세요. 기상청 AI 상담원입니다…” 음성 수신 |
| 종료 시 예외 | 서버 정상 종료 후 콘솔에 “I/O operation on closed file” 없음 |

---

**작성일**: 2026-03-13  
**대상 통화**: BZlthevU1Q (callee 1004, 기상청)  
**참고**: ERROR_REPORT_STARTFRAME_AND_TTS.md (StartFrame 원인 및 BargeInSuppressProcessor 수정 내용)
