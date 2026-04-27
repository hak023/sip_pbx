## 메타

- **작성일(로컬)**: 2026-04-15 10:54
- **상태**: 구현 완료
- **관련 경로**: `sip-pbx/src/ai_voicebot/langgraph/nodes/hitl_alert.py`, `sip-pbx/src/call_control/escalation_transfer.py`, `sip-pbx/src/ai_voicebot/pipecat/processors/hitl_processor.py`, `sip-pbx/src/ai_voicebot/pipecat/processors/rag_processor.py`, `sip-pbx/frontend/app/settings/ai-escalation/page.tsx`

## 개요

AI 에스컬레이션에 `none` 모드를 추가해 AI 판정 기반 HITL/호전환만 억제하고, `transfer` 모드에서는 호전환 대상을 페르소나 고정 내선이 아니라 착신 규칙(call-control) 해석 결과로 결정한다. SIP와 동일한 우선순위(발신자 필터 → 규칙)와 `fwd:`·그룹 해석을 공유 모듈로 맞추었으며, 프론트에서 세 가지 옵션을 저장할 수 있다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `sip-pbx/src/call_control/forward_pick.py` | 추가 | `fwd:` 파싱·그룹 멤버 선택(등록·busy) | SIP와 공유 |
| `sip-pbx/src/call_control/escalation_transfer.py` | 추가 | 필터→규칙→액션별 전환 내선 해석 | busy 미연결 시 보수적 동작 |
| `sip-pbx/src/sip_core/sip_endpoint.py` | 수정 | 전환 파싱/그룹 pick을 `forward_pick` 위임 | 설계대로 |
| `sip-pbx/src/sip_core/sip_runtime.py` | 추가 | 전역 SIPEndpoint 등록·busy 조회용 | 설계대로 |
| `sip-pbx/src/main.py` | 수정 | SIP 엔드포인트 생성 후 `set_sip_endpoint_global` | 설계대로 |
| `sip-pbx/src/config/models.py` | 수정 | `escalation_mode`·`transfer_extension` 설명 | `none` 반영 |
| `sip-pbx/src/api/routers/persona.py` | 수정 | `none` 검증, `transfer` 시 내선 필수 제거 | 설계대로 |
| `sip-pbx/src/ai_voicebot/langgraph/nodes/hitl_alert.py` | 수정 | `none` 억제, 착신 규칙 내선 주입·폴백 | 설계대로 |
| `sip-pbx/src/ai_voicebot/pipecat/processors/hitl_processor.py` | 수정 | `intent==transfer` 시 3-arg 콜백 우선 + TypeError 폴백 | 설계대로 |
| `sip-pbx/src/ai_voicebot/pipecat/processors/rag_processor.py` | 수정 | 연락처 미검색 시 call-control 폴백 호전환 | 설계대로 |
| `sip-pbx/frontend/app/settings/ai-escalation/page.tsx` | 추가 | 3옵션 라디오·저장(`PUT .../escalation`) | 설계대로 |
| `sip-pbx/frontend/app/settings/call-control/page.tsx` | 수정 | AI 에스컬레이션 페이지 링크 | 탐색성 |

## 주요 결정 사항

- **`none`**: `intent != "transfer"`일 때만 `needs_human`/`needs_transfer`를 끈다. 명시적 상담원 요청은 유지.
- **`transfer` 내선**: `resolve_escalation_transfer_extension` 결과를 우선하고, Persona `transfer_extension`은 레거시 폴백. 둘 다 없으면 `needs_transfer=False`로 호전환 생략.
- **busy**: `build_escalation_sip_context`로 SIPEndpoint가 있으면 `_extension_has_active_call` 연동; 없으면 busy 관련 액션은 해석기 내부에서 보수적으로 동작.
- **`busy_ai` 에스컬레이션**: 사람 연결 대상을 착신 owner 내선으로 통일(요구사항 반영).
- **HITL 콜백**: 기존 2-arg 콜백 호환을 위해 `TypeError` 시 2-arg 재시도.

## 잔여 과제

- 애플리케이션 종료 시 `set_sip_endpoint_global(None)` 정리(선택).
- `immediate_ai` 등 «전환 불가»일 때 고객 멘트를 HITL/transfer 경로별로 더 세밀히 통일할 여지 있음.
