## 메타

- 작성일: 2026-04-14 (로컬)
- 상태: 구현 반영
- 관련: `sip-pbx/frontend/components/AppHeader.tsx`, `sip-pbx/frontend/app/settings/call-control/page.tsx`, `sip-pbx/src/call_control/models.py`, `sip-pbx/src/api/routers/call_control_api.py`, `sip-pbx/src/sip_core/sip_endpoint.py`

## 개요

착신 제어 화면을 상단 **설정** 드롭다운 하위로 이동하고, 규칙 동작에 **통화중 시 AI 응대**(`busy_ai`) 및 **무조건/통화중 착신전환**(`forward_always`, `forward_when_busy`)을 선택할 수 있도록 UI·API·SIP 처리와 표시 문구를 정리했다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|------------|------|------|
| `sip-pbx/frontend/components/AppHeader.tsx` | 수정 | 메인 네비에서 착신 제어 단독 링크 제거, **설정** 서브메뉴에 착신 제어·링백 배치 | 소스에 없는 `/settings/integrations` 링크 제거 |
| `sip-pbx/frontend/app/settings/call-control/page.tsx` | 수정 | `busy_ai` 라벨을 사용자 문구 **통화중 시 AI 응대**로 통일 | 규칙 옵션·카드는 기존 구현 유지 |
| `sip-pbx/src/api/routers/call_control_api.py` | 수정 | 상태 API `action_label`의 `busy_ai` 문구 동일 반영 | |
| `sip-pbx/src/call_control/models.py` | 수정(선행) | `RoutingAction`에 `busy_ai`, `forward_always`, `forward_when_busy` 및 `forward` 하위 호환 | |
| `sip-pbx/src/sip_core/sip_endpoint.py` | 수정(선행) | INVITE 시 규칙별 callee 전환·busy 시 AI 경로 분기 | |

## 주요 결정 사항

- **네비게이션**: 설정은 드롭다운으로 두고, 실제 존재하는 설정 라우트만 연결(착신 제어, 링백).
- **착신전환**: 단일 `forward`는 API 호환용으로 유지하되 UI 신규 규칙에서는 `forward_always` / `forward_when_busy`만 노출.
- **표기**: 대시보드 배지·API 설명과 규칙 카드 라벨에서 **통화중 시 AI 응대**로 통일.

## 잔여 과제 (선택)

- 모바일에서 설정 드롭다운 UX(햄버거 메뉴 등) 개선 여부 검토.
- `forward` 레거시 규칙을 저장 시 `forward_always`로 마이그레이션하는 배치 작업은 선택 사항.
