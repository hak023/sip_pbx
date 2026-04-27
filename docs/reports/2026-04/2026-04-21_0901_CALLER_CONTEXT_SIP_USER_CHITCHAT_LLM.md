## 메타

- 작성일: 2026-04-21 (로컬)
- 상태: 구현·점검 반영
- 관련: `app.log` 예약 경고, CID `caller-context`, 페르소나 chitchat·HITL

## 개요

1. **예약 로그** `booking_agent_no_bind_tools_model`: 현재 저장소에는 해당 이벤트명이 없으며, 재시작 전 프로세스가 예전 코드를 실행 중이었을 가능성이 큼. 재시작 후에는 `booking_agent_bind_tools_failed` / `booking_agent_gemini_native_fc` / `booking_agent_gemini_fc_init_failed` 등 현행 로그로 확인할 것.
2. **CID 「첫 통화」**: `caller-context`가 발신 문자열 전체에서 숫자만 모아 끝 8자리로 매칭해, `sip:1004@10.x.x.x` 형태일 때 DB의 `caller_id`(예: `1004`)와 `LIKE`가 어긋날 수 있음 → SIP **user** 구간 숫자를 우선하는 `_caller_match_needle` 도입.
3. **페르소나 밖 chitchat**: `classify_intent`의 persona_chitchat 반환에서 `_chitchat_template`을 비워 `generate_response`의 LLM 경로(짧은 잡담 규칙 포함)를 타도록 변경.
4. **페르소나 관련 질문 + 지식 없음 → 에스컬레이션**: `classify_intent_persona_question`은 `_persona_scope_matched=True`를 내려 `route_utterance.compute_domain_question_signal`이 True가 됨 → RAG 0건 시 `generate_response`가 `needs_follow_up=True` → `suppress_hitl_needs_followup`에서 question+domain 신호이므로 **억제되지 않음** → `hitl_alert`에서 `needs_human=True`(단, 페르소나 `escalation_mode=="none"`이면 억제).

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|------------|------|------|
| `sip-pbx/src/api/routers/call_history.py` | 수정 | SIP user 우선 needle, `needle_src` 로그 | 설계대로 |
| `sip-pbx/src/ai_voicebot/langgraph/nodes/classify_intent.py` | 수정 | persona_chitchat 시 `_chitchat_template=None` | 요청 반영 |

## 주요 결정 사항

- 발신 매칭은 **SIP URI user의 숫자**를 먼저 쓰고, 부족할 때만 기존 tail_digits로 폴백한다.
- chitchat은 KB 고정 템플릿 대신 **동일 턴에서 이미 적용되던** 인바운드 LLM 잡담 지침(`chitchat_rule`)을 사용한다(`route_utterance`의 social_direct + `generate_response`).

## 잔여 과제

- `call_records.caller_id`가 여전히 비어 있거나 owner 필터와 안 맞으면 `has_prior_call`은 false로 남을 수 있음 → 그 경우는 DB upsert·owner 일치를 별도 점검.
