# RTP 무출력 / Pipecat StartFrame 레이스 점검

- **작성일**: 2026-03-24
- **상태**: 원인 확정 및 코드 수정 반영
- **관련**: `sip-pbx/src/ai_voicebot/pipecat/processors/rag_processor.py`, Pipecat `FrameProcessor.push_frame`

## 현상

- 특정 통화에서 **RTP(TTS)가 전혀 나가지 않음**.
- 터미널에 `RAGLLMProcessor#1 Trying to process LLMFullResponseStartFrame ... but StartFrame not received yet` 유사 로그.

## 원인

Pipecat `FrameProcessor.push_frame()`은 내부에서 `_check_started`로 **`StartFrame`을 처리해 `__started == True`가 된 뒤에만** 다운스트림으로 프레임을 보냄. 그 전에는 **에러 로그만 남기고 return**한다.

`pipeline_builder`의 `_send_initial_greeting()`은 `asyncio.sleep(0.5)` 후 `RAGLLMProcessor.send_greeting()`에서 `push_frame(LLMFullResponseStartFrame/TextFrame/...)`를 호출한다. 파이프라인이 바쁘거나 Input 쪽 지연 시 **`StartFrame`이 `rag_llm`에 도달하기 전에** 인사말이 먼저 실행되면, 모든 인사 `push_frame`이 **드롭**되어 **TTS·RTP가 없음**.

동일 이슈가 **HITL 응답 → TTS** 경로에서도 발생 가능.

## 조치

1. `RAGLLMProcessor`에 `_pipeline_start_event` 추가.
2. `process_frame`에서 `StartFrame` 처리 직후( `super().process_frame` 이후) 이벤트 set + `rag_llm_pipecat_startframe_received` 로그.
3. `send_greeting`: `push_frame` 전 `_wait_for_pipecat_started`(기본 60s). 타임아웃 시 `greeting_phase2_done` set로 사용자 STT 블로킹 방지, `send_greeting_aborted_no_startframe` 로그.
4. HITL 소비 루프: `push_frame` 전 동일 대기, 실패 시 `hitl_tts_skipped_no_startframe`.
5. STT post-filter 폴백 TTS: `LLMFullResponseStart/End`로 감싸고, `StartFrame` 대기(10s) 후 push.

## 참고

- `call_id`가 로그에 없을 수 있음(워크스페이스 `logs` 미포함 등). 재현 시 `rag_llm_pipecat_startframe_received`와 인사 로그 시각 순서로 확인하면 됨.
