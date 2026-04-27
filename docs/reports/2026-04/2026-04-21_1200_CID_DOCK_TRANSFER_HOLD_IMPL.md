## 메타

- 작성일: 2026-04-21 (로컬)
- 상태: 구현 반영
- 관련: CID `caller-context`, GlobalCallDock, `dock_transfer_request` / `dock_hold_request`, RTP `DOCK_HOLD`, Transfer preclear

## 개요

Call Dock에서 **이전 통화(CID)** 조회 실패·owner 누락을 UI·로그로 구분하고, callee SIP user로 owner를 보강한다. **「돌려주기」**는 WebSocket으로 `TransferManager.initiate_dock_transfer` 경로를 타며, 전환 전 **착신 레그 정리**(AI: `cancel_pipeline`, 인간: 서버 발 BYE + `skip_full_cleanup_on_callee_bye_200`)를 수행한다. **「통화대기」**는 RTP `RelayMode.DOCK_HOLD`에서 양측에 로컬 생성 PCMU 톤을 송신한다. 발신 단말 **REINVITE**는 동일 RTP 앵커 전제로 생략 가능함을 로그(`dock_transfer_caller_leg_media_anchor`)로 남긴다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|------------|------|------|
| `sip-pbx/frontend/lib/sipUri.ts` | 추가 | SIP URI user 추출 | CID owner 보강 |
| `sip-pbx/frontend/store/useActiveCallDockStore.ts` | 수정 | `CallerContextPayload.fetch_error` | 설계대로 |
| `sip-pbx/frontend/components/ActiveCallDockProvider.tsx` | 수정 | owner=callee user 폴백, 실패 시 `emptyCallerContext`, 스킵 시 명시 오류 | 설계대로 |
| `sip-pbx/frontend/components/GlobalCallDock.tsx` | 수정 | 대시보드 버튼 제거, 돌려주기·통화대기·모달, CID 오류 표시 | 설계대로 |
| `sip-pbx/frontend/lib/websocket.ts` | 수정 | `emitWithAck` | Dock 액션용 |
| `sip-pbx/src/sip_core/models/transfer.py` | 수정 | `TransferRecord.skip_announcement` | Dock용 |
| `sip-pbx/src/sip_core/transfer_manager.py` | 수정 | `initiate_dock_transfer`, `preclear_callee` 콜백, `skip_announcement` | 설계대로 |
| `sip-pbx/src/call_transfer/manager.py` | 수정 | `initiate_dock_transfer` | 설계대로 |
| `sip-pbx/src/sip_core/sip_endpoint.py` | 수정 | `_preclear_callee_for_dock_transfer`, callee BYE 부분 정리 플래그, `set_dock_hold`, `switch_to_bridge_mode` 내 hold 정지·REINVITE 메모 로그 | REINVITE는 옵션 문서화 |
| `sip-pbx/src/media/rtp_relay.py` | 수정 | `DOCK_HOLD`, `start_dock_hold_moh` / `stop_dock_hold_moh`, 릴레이 차단 | 설계대로 |
| `sip-pbx/src/websocket/server.py` | 수정 | `dock_transfer_request`, `dock_hold_request`, `dock_hold_state` | 설계대로 |

## 주요 결정 사항

- **CID owner**: `tenant.owner` 없으면 `call_started.callee` SIP user로 `caller-context` API owner 보강.
- **돌려주기 From CLI**: `dock_transfer_request.owner_cli`(프론트는 `getTenantOwner()` 또는 callee user) → `TransferRecord.caller_display` → 기존 `send_transfer_invite`의 `effective_caller` 우선 사용.
- **착신 정리**: AI는 파이프라인 취소만; 인간 착신은 B2BUA 발 BYE 후 200 OK에서 **전체 cleanup 생략** 플래그.
- **통화대기**: SIP hold 대신 RTP 계층 양측 MOH(440/480Hz 혼합, PCMU 20ms).
- **REINVITE**: 브릿지 전환 시 발신↔B2BUA 미디어 앵커 유지 시 생략 가능 — 엄격 REINVITE는 후속 과제.

## 잔여 과제

- 짧은 SIP user·비숫자 user에 대한 `caller-context` needle 정책 추가 점검.
- Dock 전환 실패 시 callee 복구·롤백 정책.
- 표준 SIP REINVITE/SDP 갱신이 필요한 단말에 대한 옵션 구현.
