# 예약 진행 중 chitchat 이탈(JLkzL4mOUA) 수정

- **작성일(로컬)**: 2026-04-20
- **상태**: 구현 완료
- **참고 로그**: `call_data_record_20260420.log` — 첫 턴 `booking` 후 둘째 턴 `persona_chitchat` → `chitchat` → `generate_response`

## 원인

1. **페르소나 유사도 조기 분기**: `classify_intent` 2차에서 `is_relevant == false`이면 `persona_chitchat`으로 즉시 반환. 인원·성명만 말하는 발화는 업무 키워드와 무관해 **잡담으로 오분류**될 수 있음.
2. **`merge_booking_intent_into_result`의 `booking_active`**: `booking_context.messages` 또는 `collected_slots`만 보던데, **체크포인트 직렬화** 등으로 `messages`가 비어 있으면 `booking_context_active` 승격이 되지 않아 `chitchat`이 그대로 라우팅됨.

## 조치

| 파일 | 요약 |
|------|------|
| `classify_intent.py` | `_booking_active`(messages / collected_slots / **`booking_flow_active`**)일 때 `persona_chitchat` 조기 반환 **생략** → LLM 분류로 진행. 동일 플래그로 `_booking_active` 계산 보강. |
| `booking_agent.py` | 턴 종료 시 `booking_context["booking_flow_active"]`: 예약 **생성/취소 성공 기록 직후** `last_action`이 create/cancel이면 `False`, 그 외 `True`. 폴백 경로에도 `True` 설정. |
| `booking_intent_heuristic.py` | `booking_active` 판정에 **`booking_flow_active is True`** 포함. |
| `agent.py` | `_LANGGRAPH_SCHEMA_VERSION` 7→8 (그래프 캐시 무효화). |

## 잔여 과제 (선택)

- `intent_classify` 타이밍 로그가 merge 전 intent만 남기는 경우 UX 혼동 → merge 후 intent를 별도 필드로 남길지 검토.
