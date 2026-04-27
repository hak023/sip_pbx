---
작성일: 2026-04-23
상태: 완료
---

## 개요

채팅·SIP MESSAGE 설정 화면에서 **SIP 릴레이 내선**·**응답 정책 소스(페르소나/이 페이지)** UI를 제거하고, **「SIP MESSAGE 수신 시 AI 자동응답 사용」** 과 접두어만으로 동작하도록 맞췄다. 서버는 더 이상 페르소나·`message_ai_policy` 분기로 AI를 켜지 않으며, `chat_relay_settings.message_ai_reply_enabled` 만 본다. 이로써 예전에 **페르소나만 켜 두고 설정 스위치는 꺼져 있던** 경우에 발생하던 «자동응답 안 됨»과, **`policy=settings`인데 페르소나 disabled라 조기 return** 하던 문제를 정리한다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 |
|-----------|-----------|------|
| `sip-pbx/frontend/app/settings/chat-relay/page.tsx` | 수정 | 릴레이·정책 라디오 삭제; 저장 시 `sip_username: ""` 로 별칭 비움 |
| `sip-pbx/src/services/sip_message_ai_reply.py` | 수정 | 페르소나 게이트·`persona`/`settings` 정책 분기 제거; DB 스위치·접두어만 사용 |
| `sip-pbx/src/services/chat_relay_service.py` | 수정 | 기본 정책 문자열 `settings`; upsert 시 `message_ai_policy` 생략 → `settings` 저장 |
| `sip-pbx/src/api/routers/chat.py` | 수정 | 응답 기본 `message_ai_policy` 문서·모델 정리 |
| `sip-pbx/src/api/routers/persona.py` | 수정 | `CreatePersonaRequest` doc — SIP MESSAGE AI는 채팅 설정만 |

## 주요 결정 사항

- **레거시 페르소나 `sip_message_ai_reply_*`**: API/DB 필드는 유지하나 **SIP 수신 AI 경로에서는 미사용**.
- **저장 시 `sip_username` 빈 문자열**: UI 제거에 맞춰 별칭 매핑을 비움(이미 없으면 착신 To user = owner 동작과 동일).
- **기존 테넌트**: 예전에 **페르소나만**으로 AI가 돌던 경우, **이 설정 화면에서 자동응답 체크 후 저장**해야 한다.

## 잔여 과제 (선택)

- DB에 `message_ai_policy` 컬럼은 남아 있으나 의미가 축소됨. 향후 마이그레이션으로 제거·단일화 가능.
