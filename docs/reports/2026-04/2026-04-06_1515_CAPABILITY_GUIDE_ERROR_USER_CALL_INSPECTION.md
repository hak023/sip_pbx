# capability_guide_generation_error 점검 (유저 간 통화 / Qlq5z5UFp5)

- **작성일**: 2026-04-06 (로컬)
- **상태**: 원인 확정, 코드 수정 반영
- **관련 로그**: `sip-pbx/logs/app.log` (동일 일자)
- **관련 코드**: `src/ai_voicebot/orchestrator/ai_orchestrator.py`, `src/services/knowledge_service.py`, `src/api/routers/capabilities.py`

## 1. 결론 (요약)

- **에러 직접 원인**: Phase 1 인사 문구(`greeting_message`)가 아니라, **Phase 2**에서 호출하는 `KnowledgeService.get_all_capabilities()`가 **구현되어 있지 않아** 발생한 `AttributeError`이다.
- **로그 증거**: `capability_guide_generation_error`의 `error` 필드가 **`'KnowledgeService' object has no attribute 'get_all_capabilities'`** 로 동일하게 반복됨 (예: 13:14:48, **13:15:24**, 13:18:21).
- **통화 성격**: INVITE는 1004→1003 유저 간 호이나, 착신(1003) **자리비움(away)** 으로 `callee_is_away_activating_ai` / `no_answer_timeout_activating_ai` 가 먼저 걸렸고, 이후 B2BUA로 실제 착신이 응답해 **bypass RTP 릴레이 + 실시간 STT**까지 진행됨. 동시에 `pipecat_no_rtp_worker` → **Legacy 오케스트레이터**가 떠서 AI 인사·가이드 파이프라인이 **겹쳐서** 돌아간 흐름으로 해석됨.

## 2. 타임라인 (app.log 기준, call_id `Qlq5z5UFp5`)

| 시각(대략) | 이벤트 |
|------------|--------|
| 13:15:09 | `callee_is_away_activating_ai`, `no_answer_timeout_activating_ai`, Pipecat 시도 후 `pipecat_no_rtp_worker` → legacy 폴백 |
| 13:15:14 | 착신 200 OK, `bypass_realtime_stt_feed_started` (유저 간 릴레이) |
| 13:15:24 | `call_established_wait_timeout_starting_greeting` → Legacy `play_greeting` (Phase 1 TTS) 직전/직후 |
| 13:15:24 | `capability_guide_generation_error` — **내용은 항상 `get_all_capabilities` 미구현** |

`call_established_wait_timeout_starting_greeting`은 `ai_orchestrator.handle_call`에서 `_call_established_event`가 15초 내에 set 되지 않으면 찍히는 경고로, 인사 시작과 **시간상 인접**할 뿐 capability 에러의 **논리적 원인**은 아님.

## 3. 코드 관계

- `play_greeting()`은 Phase 1 고정 인사 후 `asyncio.create_task(self._generate_capability_guide())`로 Phase 2를 병렬 생성한다.
- `_generate_capability_guide()`는 `get_knowledge_service().get_all_capabilities(owner=..., active_only=True)`를 호출한다.
- `src/api/routers/capabilities.py` 역시 동일 메서드를 전제로 하지만, **`KnowledgeService` 클래스에 메서드가 없었음** (API/시드 설계와 구현 불일치).

## 4. 조치

- `src/services/knowledge_service.py`에 **`get_all_capabilities`**, **`count_capabilities`**, **`add_capability`**, **`update_capability`**, **`toggle_capability`**, **`reorder_capabilities`** 를 추가하여 API·오케스트레이터·시드 경로와 맞췄다.
- Chroma 메타데이터 스키마는 설계서 `doc_type=capability` 및 `display_name`, `priority`, `is_active`, `owner` 등을 따른다.

## 5. 후속 확인 권장

- 동일 시나리오 재통화 후 `capability_guide_generation_error` 소멸 및 Phase 2 TTS(또는 capability 없을 때 `None` 처리) 확인.
- `TTS RTP callback not set` 등 **별도 이슈**는 이 점검 범위 밖이나, Legacy 경로에서 발화가 실제 RTP로 안 나갈 수 있으므로 로그가 남으면 RTP/콜백 설정을 추가 점검할 것.
