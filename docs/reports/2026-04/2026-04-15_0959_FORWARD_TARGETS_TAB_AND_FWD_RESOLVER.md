## 개요

Call Control에 **착신 전환 대상**을 별도 탭으로 관리하고, 착신 규칙의 `forward_to`에서 **`fwd:<uuid>`** 참조로 연동한다. 단일 내선과 그룹(멤버 목록·링 모드)을 저장하며, B2BUA는 그룹에서 등록·비통화중 내선을 우선해 1명만 선택해 INVITE 한다. 대표번호·헌트그룹의 동시/순차/순환 개념은 UI 설명과 향후 확장 주석으로 반영했다.

**작성일:** 2026-04-15 (로컬)  
**관련 경로:** `sip-pbx/src/call_control/db.py`, `models.py`, `sip-pbx/src/api/routers/call_control_api.py`, `sip-pbx/src/sip_core/sip_endpoint.py`, `sip-pbx/frontend/app/settings/call-control/page.tsx`

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|------------|------|------|
| `sip-pbx/src/call_control/db.py` | 수정 | `call_forward_targets` 테이블 DDL 및 CRUD | 설계대로 |
| `sip-pbx/src/call_control/models.py` | 수정 | `ForwardTargetKind`, `ForwardRingMode`, `ForwardTarget*` 모델 | 설계대로 |
| `sip-pbx/src/api/routers/call_control_api.py` | 수정 | `GET/POST/PUT/DELETE /forward-targets` 및 검증 헬퍼 | 설계대로 |
| `sip-pbx/src/sip_core/sip_endpoint.py` | 수정 | `_call_control_resolve_forward_target(..., rule_owner=)` 에 `fwd:` 해석·그룹 멤버 선택 | 설계대로 |
| `sip-pbx/frontend/app/settings/call-control/page.tsx` | 수정 | «착신 전환» 탭·모달, 규칙 모달에서 등록 대상/직접 입력 | 설계대로 |

## 주요 결정 사항

- **참조 형식:** `forward_to = fwd:<forward_target_id>` 규칙 owner(착신 내선)와 DB 행 `owner`가 일치할 때만 해석한다.
- **그룹 선택:** 동시/순차/순환 모두 현재는 동일 알고리즘(목록 순, 유휴·등록 우선). 실제 동시 링(다중 INVITE)은 B2BUA 범위 밖이므로 문서·UI에 명시.
- **API:** 수정 시 `owner`는 쿼리로만 전달하고, body는 `ForwardTargetUpdate` 필드만 사용해 Pydantic extra 필드 오류를 피한다.

## 잔여 과제

- 순환(circular) 링: 마지막 응답 내선 등 상태를 DB/메모리에 두고 공정 분배하는 로직.
- 그룹 **진짜** 동시 링(여러 INVITE): 미디어/B2BUA 설계 확장 필요.
