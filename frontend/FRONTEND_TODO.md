# Frontend 미구현/보완 사항

필요한 기능이지만 아직 구현되지 않았거나 목업/하드코딩된 항목입니다.

---

## 1. 대시보드 – 실시간 통화 목록 ✅ 완료

- **위치**: `app/dashboard/page.tsx`
- **구현 내용**:
  - `GET /api/calls/active` 연동 (JWT 인증, callee == 로그인 extension만 반환)
  - 15초 주기 폴링으로 목록 동기화
  - WebSocket `call_started` / `call_ended` 구독으로 실시간 추가/제거 (callee가 본인 extension인 경우만 목록에 반영)
  - `ActiveCall` 타입을 백엔드 스키마에 맞게 수정 (`call_id`, `caller`/`callee` as `CallerInfo`, `is_ai_handled`, `duration` 등)

---

## 2. 운영자 상태 – 부재중 메시지 수정 ✅ 완료

- **위치**: `components/OperatorStatusToggle.tsx`
- **구현 내용**:
  - 부재중일 때 "✏️ 메시지 수정" 클릭 시 Dialog 오픈 (제목/설명, Textarea, 취소/저장)
  - 초기값은 store의 `awayMessage`, 저장 시 `updateStatus(OperatorStatus.AWAY, draftAwayMessage)` 호출하여 API 반영

---

## 3. 지식 베이스 – 작성자/수정자 ✅ 완료

- **위치**: `app/knowledge/add/page.tsx`, `app/knowledge/[id]/edit/page.tsx`
- **구현 내용**:
  - `lib/auth.ts`에 `getCurrentUserId()` 추가: localStorage `user.id` → `tenant.owner` → `'operator'` 순으로 반환
  - 지식 추가 시 `metadata.addedBy`, 수정 시 `metadata.updatedBy`에 `getCurrentUserId()` 사용

---

## 4. 기타 ✅ 반영

- **placeholder**: Capability 추가 페이지 API URL placeholder를 `예: https://your-api.example.com/data` 로 수정.
- **타입 정리**: `ActiveCall`은 이미 백엔드 스키마에 맞게 `CallerInfo` 객체로 정의됨 (항목 1에서 완료).
