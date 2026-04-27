## 메타

- 작성일: 2026-04-14 (로컬)
- 상태: 분석·수정 완료
- 관련: `sip-pbx/frontend/lib/tenant.ts`, 채팅 API `owner` 쿼리, `chat_messages` / `resolve_chat_owner_for_inbound`

## 개요

채팅 스레드·메시지 API는 `WHERE owner = ?`로만 조회한다. SIP 수신 저장 시 `owner`는 `resolve_chat_owner_for_inbound(to_user)`(릴레이 매핑 또는 To 내선), HTTP 발신은 요청의 `owner`이다. 프론트 `getTenantOwner()`가 `tenant_id`를 `tenant.owner`보다 우선하면 DB에 쌓인 착신·테넌트 키와 달라 목록이 비어 보일 수 있어, **착신 owner 문자열을 우선**하도록 바꿨다.

## 로직 점검 요약

| 구간 | 동작 | 리스크 |
|------|------|--------|
| SIP 수신 `save_chat_message` | `thread_id=발신자 user`, `owner=resolve_chat_owner_for_inbound(to_user)` | 릴레이 미설정 시 `owner=To` 내선 — 로그인 owner가 내선과 다르면 불일치 |
| `POST /api/chat/send` | `owner=req.owner`, `thread_id=to_phone` | 프론트가 넘기는 owner와 DB 수신 owner가 같아야 한 스레드에 모임 |
| `GET /threads`, `/messages` | `owner` 정확 일치 | **tenant_id vs tenant.owner** 불일치 시 빈 목록 |

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `sip-pbx/frontend/lib/tenant.ts` | 수정 | `getTenantOwner()`에서 `tenant` JSON의 `owner`를 `tenant_id`보다 우선 | 설계대로 |

## 주요 결정 사항

- PBX·채팅 DB는 착신/테넌트 **표시 owner 문자열** 기준이므로, UI에서 동일 문자열을 쓰도록 `getTenantOwner()` 정렬을 맞춘다.
- 대시보드 등 `tenant_id`를 의도적으로 쓰는 코드는 `localStorage.getItem("tenant_id")`를 직접 읽는 경로가 있어 본 변경과 분리된다.

## 잔여 과제 (선택)

- 로그인 시 `tenant_id`만 두고 `tenant.owner`를 비우는 클라이언트는 여전히 `tenant_id`로만 조회됨 — 백엔드에 owner 별칭 테이블이 없으면 동일 한계.
- 스레드 `thread_id`를 항상 숫자만 정규화하는 옵션(UA별 From 차이)은 필요 시 별도 검토.
