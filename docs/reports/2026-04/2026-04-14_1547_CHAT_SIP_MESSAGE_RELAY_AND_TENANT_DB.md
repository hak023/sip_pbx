## 메타

- 작성일: 2026-04-14 (로컬)
- 상태: 구현 반영
- 선행 점검: `2026-04-14_1538_CHAT_MANAGEMENT_IMPLEMENTATION_AUDIT.md`

## 개요

유저 간 SIP MESSAGE를 PBX가 REGISTER 맵으로 **릴레이**하고, 발신 성공은 **원격 UA의 최종 SIP 응답(2xx만 성공)** 을 기준으로 판정한다. 대시보드 **테넌트(owner)** 와 SIP **REGISTER 사용자명**이 다를 수 있어 `chat_relay_settings`로 매핑·관리하며, 수신 MESSAGE는 **To / Request-URI** 내선으로 테넌트를 역매핑해 `chat_messages.owner`에 저장한다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 |
|-----------|------------|------|
| `sip-pbx/src/booking/database.py` | 수정 | `chat_relay_settings` 테이블·인덱스 DDL |
| `sip-pbx/src/services/chat_relay_service.py` | 추가 | 조회/저장, 발신 sip_from 해석, 수신 owner 역매핑 |
| `sip-pbx/src/sip_core/sip_endpoint.py` | 수정 | MESSAGE 클라이언트 트랜잭션(Call-ID·threading.Event·8s), 수신 DB owner 정합 |
| `sip-pbx/src/api/routers/chat.py` | 수정 | `GET/PUT /api/chat/relay`, 발신·재전송 시 `resolve_sip_from_for_outbound` |
| `sip-pbx/frontend/app/settings/chat-relay/page.tsx` | 추가 | 릴레이 내선 설정 UI |
| `sip-pbx/frontend/app/chat/page.tsx` | 수정 | 릴레이 설정 링크·안내 문구 |
| `sip-pbx/docs/reports/2026-04/2026-04-14_1538_CHAT_MANAGEMENT_IMPLEMENTATION_AUDIT.md` | 수정 | 잔여 과제 1~2 완료 표기 |

## 주요 결정 사항

- **2xx만 전송 성공**: `_handle_sip_response` 초입에서 `CSeq`에 `MESSAGE` 포함·상태코드 ≥200 인 응답으로 대기 중 `Call-ID`를 완료; 100–199는 무시(프로비저널).
- **발신 From**: `chat_relay_settings.sip_username`이 있으면 그 값으로 REGISTER 조회·SIP From; 없으면 `owner` 문자열 그대로.
- **수신 owner**: `sip_username == To(R-URI) user` 인 테넌트 row가 있으면 그 `owner`; 없으면 내선 문자열을 owner로 저장(단일 테넌트·레거시). **로그인 owner와 수신 스레드가 맞으려면 릴레이 매핑 설정 권장.**
- **타임아웃**: 8초(`_chat_message_txn_timeout_sec`), 실패 코드 `sip_timeout`.

## 잔여 과제 (선택)

- ~~HTTP API만 별도 프로세스인 경우 `deliver_chat_sip_message` 경로를 IPC/내부 API로 통일~~ → `2026-04-14_1555_CHAT_SIP_INTERNAL_RELAY_VIA_BRANCH.md`
- ~~다중 Via/프록시 환경에서 응답 매칭 강화(branch 등)~~ → 동일 리포트.
