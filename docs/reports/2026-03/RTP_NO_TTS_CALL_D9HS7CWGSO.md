# call_id d9hs7CWgSO — TTS·RTP 미송신 원인 분석

- **작성일**: 2026-03-26 (로컬)
- **상태**: 로그 기반 원인 정리
- **근거 로그**: `sip-pbx/logs/app.log` (2026-03-27 19:27–19:28 구간)

## 결론 요약

**RTP가 안 나간 이유는 “UDP/코덱 문제”가 아니라, TTS 경로에서 PCM이 송신 큐에 한 번도 쌓이지 않았기 때문이다.**  
로그상 `rtp_tts_queue_empty_timeout`의 `packets_sent`가 통화 내내 **0**이며, 인사 Phase1 직후 **`on_tts_complete`가 25.5초 안에 오지 않아** `greeting_phase_gap_tts_complete_timeout`으로 빠졌다. 즉 **Google TTS(또는 Pipecat TTS 처리)가 이 통화에서 완료 이벤트·오디오 프레임을 만들지 못한 상태**로 해석하는 것이 타당하다.

## 로그로 확인된 사실

1. **수신·파이프라인 앞단은 정상**  
   `pipecat_mode_enabled`, `pipeline_built`, `rag_llm_pipecat_startframe_received`, `caller_rtp_to_stt_input`, `input_audio_frame_to_pipeline` 등이 지속적으로 찍힘.

2. **인사 텍스트는 RAG에서 TTS로 push 됨**  
   `send_greeting_started` → `greeting_phase1_sent` → `greeting_phase_waiting_tts_complete` → `rag_greeting_blocking_start` (Phase1 후 `event.wait()`).

3. **정상 호(AZIriupMq-)와의 대비**  
   동일 로그 파일에서 `AZIriupMq-`는 `rag_greeting_blocking_start` 후 약 1.2초 만에 `rag_greeting_blocking_end`가 찍힘.  
   **`d9hs7CWgSO`는 `rag_greeting_blocking_end`가 타임아웃 처리 전까지 없음** → TTS 완료/notifier가 동작하지 않음.

4. **RTP 송신 스레드는 “큐 공허”만 반복**  
   `tts_queue_size: 0`, `tts_sending_active: false`, `rtp_tts_queue_empty_timeout`의 `packets_sent: 0` 지속.

5. **`ai_mode_activated` 시 `ai_enabled_calls`: 2**  
   직전 통화 `AZIriupMq-`는 BYE·cleanup 이후에도 `ai_enabled_calls`에서 제거되지 않은 것으로 보인다(`cleanup_terminated_call`은 코드베이스에서 호출부가 없고, `sip_endpoint._cleanup_call`에는 `discard` 없음).  
   이것이 TTS를 직접 막는다고 단정할 수는 없으나, **“이전 AI 통화가 완전히 정리되지 않은 채 다음 통화가 올라온”** 신호로 남는다.

## 기술적 원인 가설 (우선순위)

1. **`GoogleTTSService` Singleton + 이전 파이프라인 취소 후 내부 상태**  
   `factory.py`는 STT에 대해 “동시 파이프라인에서 Singleton 공유 시 스트림 꼬임”을 명시하고 **통화별 STT**로 분리해 두었으나, **TTS는 여전히 Singleton**이다.  
   직전 호가 `pipecat_pipeline_cancelled` 등으로 끊긴 뒤, **TTS 쪽 내부 태스크/큐가 다음 호에서 합성을 진행하지 못하는** 패턴과 부합한다.

2. **(보조) 인사 `send_greeting`이 `PipelineRunner.run()`과 별도 Task에서 돌아가는 설계**  
   `pipeline_builder.py`에서 `asyncio.create_task(_send_initial_greeting())` 후 `await runner.run(task)`.  
   대부분 정상 동작하지만, Pipecat/Google TTS 구현에 따라 **동시성·컨텍스트 이슈**가 있을 수 있어, 재현 시 **통화별 TTS** 또는 **runner와 동일 스케줄링으로 인사 전송**이 검증 가치가 있다.

## 권장 후속 조치

- **TTS를 STT와 동일하게 통화(파이프라인)별 인스턴스로 분리**하거나, Singleton 사용 시 **파이프라인 종료 시 TTS `stop`/리셋**을 명시적으로 호출하는지 Pipecat/GoogleTTSService 문서·소스로 확인.
- **`sip_endpoint._cleanup_call`(또는 AI 종료 공통 경로)에서 `CallManager.ai_enabled_calls.discard(original_call_id)` 및 필요 시 `ai_orchestrator.end_call()` 정리** — 집합 누수 제거.
- 재현 시 **TTS API 오류·취소 예외**를 위해 `call_id` 단위로 Google TTS 진입/종료·첫 오디오 프레임 로그를 추가.

## 코드 반영 (2026-03-26)

- **`create_google_tts_service_per_pipeline`**: `factory.py` — Pipecat는 `get_or_create_google_tts_service` 대신 통화마다 새 `GoogleTTSService` 인스턴스 사용.
- **`call_manager.py`**: 부재중 AI 터크오버 시 위 per-pipeline TTS 사용, 로그 이벤트 `google_tts_service_per_pipeline_for_call`.
- **`CallManager.discard_ai_enabled_call`**: `sip_endpoint._cleanup_call`에서 BYE 정리 시 호출 — `ai_enabled_calls` 집합 누수 제거.
- **`ai_orchestrator.end_call()`**: Pipecat 경로는 `handle_call`을 타지 않아 레거시 STT/버퍼와 섞일 수 있어 **BYE 정리에서 호출하지 않음** (기존과 동일).
- **인사 Task·runner 동시성**: 이번 변경 범위에서 수정하지 않음. 통화별 TTS로 재현 여부 확인 후 필요 시 후속.
