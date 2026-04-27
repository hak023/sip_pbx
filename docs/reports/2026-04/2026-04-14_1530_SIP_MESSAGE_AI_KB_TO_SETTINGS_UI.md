## 메타

- **작성일**: 2026-04-14
- **상태**: 완료
- **관련**: `frontend/app/knowledge/page.tsx`, `frontend/app/settings/chat-relay/page.tsx`, `frontend/components/AppHeader.tsx`

## 개요

SIP MESSAGE(채팅) AI 자동응답 옵션은 지식베이스(페르소나 폼)보다 **설정(채팅 릴레이 API)** 과 역할이 맞으므로, UI를 **설정 → 채팅·SIP MESSAGE** 로 이전하고 지식베이스에서는 링크만 안내한다. 백엔드는 기존 `GET/PUT /api/chat/relay`의 `message_ai_*` 필드를 그대로 사용한다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|------------|------|------|
| `sip-pbx/frontend/app/knowledge/page.tsx` | 수정 | SIP MESSAGE AI 상태·폼·PUT 필드·카드 요약 제거, 설정 페이지 링크 안내 | 페르소나 저장 시 `sip_message_ai_reply_*` 미전송 |
| `sip-pbx/frontend/app/settings/chat-relay/page.tsx` | 수정 | `message_ai_policy` / `message_ai_reply_enabled` / `message_ai_reply_prefix` 로드·저장·UI(레거시 persona 라디오 포함) | `apiJson`, `getTenantOwner` 사용 |
| `sip-pbx/frontend/components/AppHeader.tsx` | 수정 | 설정 네비 라벨 `채팅·SIP MESSAGE` | 경로 동일 `/settings/chat-relay` |

## 주요 결정 사항

- **정책 소스**: 설정 화면에서 `persona`(레거시 페르소나 필드)와 `settings`(이 페이지 값)를 라디오로 선택 가능하게 두어, 기존 `message_ai_policy=persona` 테넌트도 동작을 유지하면서 UI 이전만 수행한다.
- **지식베이스**: 기능 제거 대신 **설정으로 이동** 문구와 링크만 두어 사용자가 혼선 없이 찾을 수 있게 한다.

## 잔여 과제

- 예전에 페르소나 API에만 값을 넣고 `message_ai_policy`가 `persona`인 경우, 설정에서 **「이 페이지 값 사용」** 으로 저장해야 설정 기반으로 전환된다(화면에 레거시 설명 포함).
