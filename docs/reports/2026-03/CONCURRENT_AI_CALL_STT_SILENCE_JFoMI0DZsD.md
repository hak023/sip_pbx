# 동시 AI 통화 시 두 번째 호 무음 (STT Singleton)

- **작성일**: 2026-03-26 (로컬)
- **상태**: 수정 반영됨
- **관련 로그**: `sip-pbx/logs/app.log` — `call_id` `JFoMI0DZsD`
- **관련 코드**: `sip-pbx/src/ai_voicebot/factory.py`, `sip-pbx/src/sip_core/call_manager.py`

## 증상

- 첫 통화에서 상담원 연결 후, 두 번째 통화(`JFoMI0DZsD`)에서 **발화·TTS가 들리지 않음**.
- 로그: `rtp_tts_queue_empty_timeout` 에 `packets_sent: 0` 지속, `caller_rtp_to_stt_input` / `input_audio_frame_to_pipeline` 은 정상 증가 가능.
- 동일 시각대 `ai_enabled_calls: 2` 등 **두 Pipecat 파이프라인이 겹친 상태**가 관측됨.

## 원인 (가설 → 코드 정합)

1. Pipecat 파이프 순서: `… → STT → RAG → TTS → …`. RAG의 `send_greeting()` 등은 **RAG 프로세서가 `StartFrame`을 받은 뒤**에만 안전하게 동작.
2. `GoogleSTTService.start(StartFrame)` 은 내부에서 `await self._connect()` 를 호출하며, `_connect()` 는 **`_request_queue`·`_streaming_task` 를 매번 새로 할당**한다 (Pipecat `google/stt.py`).
3. **동일 `GoogleSTTService` 인스턴스를 두 파이프라인이 공유**하면, 나중에 시작한 파이프라인의 `start()` 가 앞선 통화의 스트림 상태를 덮어쓰거나, 한쪽 파이프라인에서 프레임 처리 순서가 깨질 수 있다.
4. 기존 `get_or_create_google_stt_service()` 싱글톤이 `call_manager` 의 Pipecat 경로에서 사용되어, **동시 통화 시 STT 공유**가 발생.

## 조치

- `create_google_stt_service_per_pipeline()` 추가: **통화(파이프라인)마다 새 `GoogleSTTService`** 생성.
- `call_manager` Pipecat 분기에서 STT만 위 함수로 교체. TTS는 기존처럼 Singleton 유지 (충돌 시 별도 이슈로 per-pipeline 분리 검토).

## 재현·검증

- 재현: AI 모드 통화 1건 유지(또는 긴 처리) 상태에서 두 번째 번호로 AI 인입 → 이전 빌드에서는 무음·인사 타임아웃 가능.
- 검증: 두 통화 동시에 `stt_path_input_first`, `initial_greeting` / TTS RTP 송신 로그가 각 `call_id` 에서 기대대로 나오는지 확인.

## 트레이드오프

- 통화마다 STT 인스턴스 생성으로 **첫 연결 비용**이 호당 발생할 수 있음 (기존 Singleton은 이를 피했으나 동시성 안전과 상충).
