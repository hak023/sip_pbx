## 메타

- 작성일: 2026-04-20
- 목적: SIP MESSAGE/RCS 텍스트 수신 시 AI 자동응답 스위치를 **설정(채팅 릴레이)** 으로 이전·통합

## 개요

`chat_relay_settings`에 **`message_ai_policy`**, **`message_ai_reply_enabled`**, **`message_ai_reply_prefix`** 를 추가하고, `GET/PUT /api/chat/relay` 로 조회·저장한다. `sip_message_ai_reply`는 `policy=settings`이면 페르소나의 `sip_message_ai_reply_*` 대신 이 컬럼만으로 ON/OFF·접두어를 결정한다. `policy=persona`(기본)는 기존 지식베이스·페르소나 플래그와 동일 동작이다. 에이전트는 계속 **`ConversationAgent.process_utterance`**(음성과 동일 LangGraph 경로)를 사용한다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 |
|-----------|-----------|------|
| `sip-pbx/src/booking/database.py` | 수정 | `chat_relay_settings`용 `ALTER` 마이그레이션 3건 |
| `sip-pbx/src/services/chat_relay_service.py` | 수정 | `get_chat_relay_settings` SELECT * + message_ai 필드, `upsert_chat_relay_settings` 병합 저장 |
| `sip-pbx/src/api/routers/chat.py` | 수정 | 응답/요청 모델·PUT 부분 갱신(`exclude_unset`) |
| `sip-pbx/src/services/sip_message_ai_reply.py` | 수정 | 정책별 게이트·접두어, `kb_owner` 정규화 단일화 |
| `sip-pbx/src/api/routers/persona.py` | 수정 | 페르소나 SIP 메시지 필드 레거시 안내 문구 |

## 주요 결정 사항

- **이중 경로**: `persona`(기본) = 레거시; `settings` = 운영자가 설정 화면만 보면 되도록 분리.
- **페르소나 `enabled`**: 여전히 필요(음성과 동일하게 조직 AI가 켜져 있어야 메시지 AI도 동작).
- **프론트**: `PUT /api/chat/relay` body에 `message_ai_policy`, `message_ai_reply_enabled`, `message_ai_reply_prefix` 추가. 기존 클라이언트는 `sip_username`만내도 동작(선택 필드).

## 잔여 과제

- 프론트 **설정** 페이지에서 지식베이스의 SIP/RCS 토글을 제거하고 위 API 필드로 연결.
