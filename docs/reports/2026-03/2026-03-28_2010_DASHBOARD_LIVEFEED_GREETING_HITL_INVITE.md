# 대시보드 실시간 대화창 점검 (greeting / HITL / INVITE 시점)

- **작성일**: 2026-03-28 (로컬)
- **상태**: 조치 반영 완료
- **관련 경로**: `sip-pbx/frontend/app/dashboard/page.tsx`, `sip-pbx/src/ai_voicebot/pipecat/processors/rag_processor.py`, `sip-pbx/src/sip_core/sip_endpoint.py`

## 점검 요약

### 1. INVITE(통화 시도) 시점 표시

- 백엔드 `sip_endpoint._handle_invite_b2bua`에서 이미 `emit_call_started(..., sip_phase: "inviting")`를 송출하고, 프론트 `call_started` 핸들러에서 해당 단계일 때 실시간 피드에 시그널링 안내를 넣도록 되어 있음.
- **문제**: `liveFeedByCall[call_id]`에는 줄이 쌓이지만, `selectedFeedCallId`는 `activeCalls` 변경 후 `useEffect`에서만 채워져 **같은 렌더 사이클**에서는 선택 통화가 비어 있어 패널이 “빈 상태”로 보일 수 있음. STT 등은 그 이후 이벤트라 선택이 이미 잡힌 뒤라 “연결 후부터만 보인다”처럼 느껴질 수 있음.

**조치**: `call_started` 수신 시 `setSelectedFeedCallId((prev) => prev || id)`를 즉시 호출해 INVITE 직후 피드와 선택 통화를 한 틱에 맞춤. `stt_transcript`, `tts_started`, `ai_greeting`, `hitl_requested`에도 동일 패턴으로 보강.

### 2. greeting 1·2 미표시

- 프론트는 `ai_greeting` 이벤트로 `appendLiveFeed` 처리 중이었음.
- 백엔드는 `asyncio.create_task(emit_ai_greeting(...))`로 발송. 루프/예외 상황에서 유실·무시 가능성을 줄이기 위해 **`await emit_ai_greeting`** 으로 변경 (Phase1·Phase2-only·Phase2 after gap 세 경로).

### 3. HITL 요청/답변 미표시

- `hitl_requested`는 목록 상태(`hitlRequests`)만 갱신하고 실시간 대화 피드에는 넣지 않았음.
- `hitl_resolved`는 목록에서 제거만 함. 서버는 `response` 필드를 함께 보냄.

**조치**: `hitl_requested` 시 질문을 `hitl_request` 종류로 피드에 추가, `hitl_resolved` 시 운영자 답변을 `hitl_response`로 추가. UI는 장미색(rose) 테두리로 구분.

## 참고

- B2BUA 200 OK 시점에는 기존과 같이 `emit_call_started(..., sip_phase: "answered")`가 송출되며, 프론트에서 추가 시그널링 줄을 넣음.
