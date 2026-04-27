## 메타

- **작성일(로컬)**: 2026-04-21 11:07
- **상태**: 완료
- **관련 경로**: `sip-pbx/src/ai_voicebot/langgraph/nodes/classify_intent.py`, `route_utterance.py`, `generate_response.py`, `sip-pbx/frontend/app/knowledge/page.tsx`

## 개요

Chitchat이 KB 고정문이 아닌 LLM 일반 응대로 이어지는지 코드 경로를 점검했고, 지식베이스(페르소나) 화면에서 잡담(chitchat) 템플릿 입력·표시·저장 필드를 제거했다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|------------|------|------|
| `sip-pbx/frontend/app/knowledge/page.tsx` | 수정 | `chitchat_response_template` 상태·로드·PUT·UI·요약 카드 제거 | 백엔드가 필드를 무시해도 동작에 문제 없음 |

## 주요 결정 사항 (로직 점검)

1. **`classify_intent` (persona_chitchat)**: `intent: chitchat`과 함께 `_chitchat_template: None`만 설정되며, 코드베이스 전역에서 문자열 템플릿을 넣는 경로는 없음 → **템플릿 단축 경로 비활성**.
2. **`route_utterance`**: `chitchat`·`out_of_scope`는 `rag_mode: skip`, `utterance_lane: social_direct`로 RAG 없이 `generate_response`로 진행.
3. **`generate_response`**: `intent in ("chitchat", "greeting")` 또는 social 경로의 `out_of_scope`에 `chitchat_rule`을 주입하고 스트리밍 LLM 호출; 페르소나 `description`은 업무 범위로 system에 주입 가능.

## 잔여 과제 (선택)

- `generate_response.py` 109~139행의 chitchat 템플릿 분기는 현재 미사용이나 레거시/호환용으로 남김. 완전 제거 시 동작 변화 없음(다른 노드가 템플릿을 넣지 않는 한).
