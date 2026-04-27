# 음성 예약 자동화 — 구현 리포트

- **작성일(로컬)**: 2026-04-20 15:38
- **상태**: 구현 반영
- **관련 설계**: `2026-04-20_1730_VOICE_BOOKING_AUTO_API_DESIGN.md`

## 개요

`intent=booking`으로 라우팅되지 않아 예약 레인에 못 들어가던 경우를 줄이기 위해 `classify_intent` 이후 휴리스틱(`booking_intent_heuristic`)을 두었고, 예약 도구 루프·DB 커밋 구간에 `call_data_record` 이벤트를 추가해 통화별 사후 분석이 가능하도록 했다. LangGraph 캐시 무효화를 위해 스키마 버전을 올렸다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|------------|------|------|
| `sip-pbx/src/ai_voicebot/langgraph/booking_intent_heuristic.py` | 추가 | `BOOKING_VOICE_ENABLED` / `STRICT`, 패턴·컨텍스트 기반 `booking` 승격, `booking_intent_routed` 로그 | 설계 §3.1 정렬 |
| `sip-pbx/src/ai_voicebot/langgraph/nodes/classify_intent.py` | 수정 | 반환 경로에 휴리스틱 머지, `_BOOKING_ACTION_PATTERNS` 소량 보강 | 설계대로 |
| `sip-pbx/src/ai_voicebot/langgraph/nodes/booking_agent.py` | 수정 | 도구 호출 전후 `booking_tool_start` / `booking_tool_done`, max rounds 시 `booking_rejected` | 설계대로 |
| `sip-pbx/src/ai_voicebot/langgraph/tools/booking_tools.py` | 수정 | `_create_booking` 성공 `booking_committed`, 실패 `booking_rejected` | 전화번호 전체 비노출 |
| `sip-pbx/src/ai_voicebot/langgraph/agent.py` | 수정 | `_LANGGRAPH_SCHEMA_VERSION` 7 | 의도·로깅 변경 반영 |
| `sip-pbx/docs/reports/2026-04/2026-04-20_1730_VOICE_BOOKING_AUTO_API_DESIGN.md` | 수정 | 상단 상태·구현 리포트 링크 | — |
| 본 문서 | 추가 | 구현 요약·검증 메모 | — |

## 주요 결정 사항

- `booking_tool_done`의 `ok`는 JSON 파싱 후 `error` 키 부재로 판단하고, 파싱 실패 시 문자열 앞부분에 `"error"` 부분 문자열이 없으면 성공으로 간주하는 보수적 폴백을 둠.
- `booking_committed`에는 PII를 넣지 않고 `booking_id`, 슬롯, 인원, `owner`만 기록.
- `route_utterance`는 `intent == booking`이면 기존대로 `utterance_lane=booking`이므로 변경 없음.

## 잔여 과제 (선택)

- 설계 비목표: HITL 큐, 외부 POS 단일 진실원, 프론트 `booking_confirmed` WebSocket.

## 검증

- `python -m py_compile` 대상: `booking_intent_heuristic.py`, `classify_intent.py`, `booking_agent.py`, `booking_tools.py`, `agent.py`.
- 수동: “예약하려고 하는데요” 등 → `call_data_record`에 `category=booking`, `booking_intent_routed` 또는 LLM 분류 `booking` 확인.
