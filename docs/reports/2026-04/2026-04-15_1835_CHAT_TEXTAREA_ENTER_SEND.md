## 메타

- 작성일: 2026-04-15
- 상태: 구현 완료
- 관련: `sip-pbx/frontend/app/chat/page.tsx`

## 개요

채팅 관리 화면에서 메시지 입력란에 포커스가 있을 때 **Enter** 로 **전송** 버튼과 동일하게 `sendChat()` 이 호출되도록 했다. **Shift+Enter** 는 줄바꿈으로 두었고, 한글 IME 조합 중(`isComposing`)에는 Enter 로 전송하지 않는다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----|-----|---|---|
| `sip-pbx/frontend/app/chat/page.tsx` | 수정 | textarea `onKeyDown`: Enter → `sendChat()`, Shift+Enter 유지 | 설계대로 |
| `sip-pbx/frontend/app/chat/page.tsx` | 수정 | placeholder 에 단축키 안내 한 줄 | UX |

## 주요 결정 사항

- 전송 버튼과 동일한 가드는 기존 `sendChat()` 내부(`owner`, `selectedThreadId`, `trim`, `sending`)에 맡김.
- 다줄 입력은 Shift+Enter 로 유지하는 것이 일반적인 채팅 UX 이다.
