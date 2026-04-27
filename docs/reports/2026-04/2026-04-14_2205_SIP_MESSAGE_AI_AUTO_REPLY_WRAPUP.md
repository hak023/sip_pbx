## 메타

- **작성일(로컬)**: 2026-04-14
- **상태**: 구현 마무리·점검
- **관련**: SIP MESSAGE 인입, 페르소나, LangGraph `ConversationAgent`, 내부 HTTP 채팅 릴레이

## 개요

SIP MESSAGE(채팅) 인입 시 페르소나 설정으로 AI 자동 텍스트 응답을 켤 수 있도록 한 흐름을 완성했다. 대화 요약 이후 남은 항목으로 **API 응답 스키마 보강**, **HTTP 릴레이 시 루프 방지 플래그 전달**, **지식 UI에서 설정 저장**, **DB 저장 시 `error_code` 타입 정합성**, **페르소나 목록 메타 필드**를 반영했다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `sip-pbx/src/api/routers/persona.py` | 수정 | `PersonaResponse`에 `sip_message_ai_reply_*` 추가; PUT 시 `model_fields_set`으로 접두 `null` 초기화 가능 | 설계대로 |
| `sip-pbx/src/services/sip_message_ai_reply.py` | 수정 | `save_chat_message(..., error_code="")` 로 문자열 일관 | 설계대로 |
| `sip-pbx/src/services/chat_sip_delivery.py` | 수정 | 내부 HTTP JSON에 `suppress_ai_loop` 포함 | 분리 프로세스 시 재귀 방지 |
| `sip-pbx/src/sip_core/sip_internal_http.py` | 수정 | `InternalChatMessageBody.suppress_ai_loop` → `send_chat_sip_message` 전달 | 설계대로 |
| `sip-pbx/src/ai_voicebot/knowledge/persona_service.py` | 수정 | `list_personas` dict에 에스컬레이션·SIP AI 메타 포함 | 목록/API 정합 |
| `sip-pbx/frontend/app/knowledge/page.tsx` | 수정 | SIP 채팅 AI 자동응답 토글·접두 입력·저장·요약 카드 | 설계대로 |
| `sip-pbx/docs/reports/2026-04/2026-04-14_2205_SIP_MESSAGE_AI_AUTO_REPLY_WRAPUP.md` | 추가 | 본 리포트 | — |

## 주요 결정 사항

- **내부 릴레이**: API 프로세스만 있을 때 `suppress_ai_loop`를 JSON으로 넘겨 PBX 쪽 `X-PBX-Skip-AI-Reply` 경로와 맞춘다.
- **Persona PUT 접두**: Pydantic `model_fields_set`으로 요청 본문에 `sip_message_ai_reply_prefix` 키가 있을 때만 갱신해, `null`로 비우기가 가능하다.

## 잔여 과제

- 운영 문서에 **SIP MESSAGE AI 자동응답** 켜는 순서(페르소나·RAG·LLM 가용성)를 짧게 적어 두면 좋다.
