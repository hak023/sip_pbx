## 메타

- **작성일(로컬)**: 2026-04-21 16:49
- **상태**: 구현 반영 완료
- **관련**: SMS CallDock 설계(CID CallDock 정렬), `sip_message_received` / `sip_message_sent`, `POST /api/chat/send`

## 개요

전역 플로팅 SMS 도크를 통화 도크와 유사한 패턴(Zustand + Socket.IO 구독 + Provider)으로 추가했다. 백엔드에서는 SIP MESSAGE 송신 후 `sip_message_sent` WS 브로드캐스트와 수신 WS에 `tenant_owner`를 실어 멀티 테넌트 필터링에 쓸 수 있게 했다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----|-----|---|---|
| `sip-pbx/src/websocket/server.py` | 수정 | `emit_sip_message_received`에 `tenant_owner`, `schedule_sip_message_sent` 추가 | 설계대로 |
| `sip-pbx/src/sip_core/sip_endpoint.py` | 수정 | 수신 시 `tenant_owner`로 WS emit, `send_sip_message`·`send_chat_sip_message` 경로에서 송신 WS 스케줄 | 설계대로 |
| `sip-pbx/frontend/lib/smsThread.ts` | 추가 | `threadId` 빌드·파싱·peer/owner 정규화 | 설계대로 |
| `sip-pbx/frontend/store/useActiveSmsDockStore.ts` | 추가 | SMS 도크 상태·줄·설정 persist(본문 제외) | 설계대로 |
| `sip-pbx/frontend/components/ActiveSmsDockProvider.tsx` | 추가 | `sip_message_received` / `sip_message_sent` 구독·테넌트 필터 | 설계대로 |
| `sip-pbx/frontend/components/GlobalSmsDock.tsx` | 추가 | 좌하단 플로팅 UI, `/api/chat/send` 연동 | 설계대로 |
| `sip-pbx/frontend/app/layout.tsx` | 수정 | `ActiveSmsDockProvider` + `GlobalSmsDock` 마운트 | 설계대로 |
| `sip-pbx/frontend/components/GlobalCallDock.tsx` | 수정 | CID 영역「문자」→ `openThreadFromCall` | 설계대로 |
| `sip-pbx/frontend/app/chat/page.tsx` | 수정 | URL `thread` 쿼리로 스레드 선택(도크 딥링크) | 보조 |

## 주요 결정 사항

- **위치**: 통화 도크 `right-4` / SMS 도크 `left-4`, z-index `100` vs `99`로 겹침 완화.
- **발신 확인**: `POST /api/chat/send` 응답으로 pending 줄을 즉시 확정(`completePendingOutbound`). WS `sip_message_sent`의 `kind=chat_relay`는 동일 pending 확정용(중복 줄 방지).
- **`sip_message_sent`의 `kind=server_push`**: 자동 열기가 켜진 경우에만 다른 스레드로 전환하며 줄 추가; 끄면 동일 스레드일 때만 반영.
- **테넌트 필터**: `tenant_owner`와 `getTenantOwner()` 비교; 둘 중 하나가 비면(레거시·미로그인) 수신 이벤트는 통과시키는 보수적 호환.

## 후속 구현 (2026-04-21)

- **이력 REST**: `GET /api/chat/messages` + `GET /api/chat/threads`로 DB `thread_id`를 정규화 매칭(`resolveChatThreadIdForApi`)한 뒤 스레드 열 때 병합 로드(`mergeServerLinesWithEphemeral`).
- **Call Dock 발신**: `openThread` / `openThreadFromCall`에 `activePeerKey` 누락을 보완해 `POST /api/chat/send` 대상이 항상 채워지도록 함.
- **입력 UX**: Enter 전송, Shift+Enter 줄바꿈.
- **발화자 UI**: 통화 도크 STT 피드와 유사하게 `상대 · {peer}` / `나 · {owner}` 라벨 + 좌우 정렬·보더 스타일.

## 잔여 과제

- `server_push`의 `tenant_owner`는 여전히 수신 내선 기준 `resolve_chat_owner_for_inbound`에 의존한다. PBX 푸시 발신 주체가 명확해지면 별도 매핑을 검토할 수 있다.
