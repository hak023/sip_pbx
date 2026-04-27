## 메타

- 작성일: 2026-04-14 (로컬)
- 상태: 검증 완료 (자동 스크립트 + 코드 추적)
- DB: 검증 전용 `data/_api_verify_call_control.db` (스크립트가 매 실행 시 삭제 후 재생성)

## 개요

`/api/call-control` REST가 **설정한 대로 SQLite에 반영되고**, `routing_engine.resolve_rule` / `resolve_caller_filter` 결과와 **status·preview** 응답이 일치하는지 검증했다. SIP INVITE 경로에서의 실제 통화 동작은 **코드 추적**으로 한정(본 문서 §4).

## 검증 방법

1. **자동 스크립트**: `scripts/verify_call_control_api.py`  
   - `CALL_CONTROL_DB_PATH` 를 전용 파일로 고정 후 `httpx.AsyncClient` + `ASGITransport` 로 FastAPI 앱 인메모리 호출 (httpx 0.28 호환).  
   - 규칙·스케줄·안내멘트·링그룹·발신필터·오버플로 정책 CRUD, `DELETE` 204, `routing_engine.resolve_rule` 고정 시각(2026-04-13 12:00 KST = UTC 03:00)으로 스케줄 매칭 확인.  
   - **우선순위**: `schedule_id=None` 인 항상 규칙이 숫자 priority 가 더 작으면 스케줄 규칙보다 먼저 매칭됨 → 검증 시 항상 규칙은 `priority=200` 으로 뒤로 보냄.
2. **코드 추적**: `sip_endpoint.py` INVITE 처리 구간에서 call-control 호출 순서·액션 분기.

## 검증 결과 요약

| 구분 | 결과 | 비고 |
|------|------|------|
| GET/POST/PUT/PATCH/DELETE rules | 통과 | priority·이름 갱신 확인 |
| POST schedules + time_ranges | 통과 | JSON days/time_ranges 저장 |
| resolve_rule (스케줄 + priority) | 통과 | `immediate_ai` 규칙이 평일 09–18 창에서 선택 |
| GET /status/{owner}, /preview/{owner} | 통과 | 엔진과 동일 규칙 id |
| announcements + ringback-greeting | 통과 | `use_as_ringback_greeting` 반영 |
| ring-groups CRUD | 통과 | POST/DELETE |
| caller-filters + PUT JSON | 통과 | **수정**: `PUT /caller-filters/{id}` 가 본문을 받도록 `Body(...)` 명시 (`call_control_api.py`) |
| overflow GET/PUT | 통과 | DB 저장·조회 |
| SIP 실통화 E2E | 미실시 | REGISTER·RTP 필요 |

## SIP 연동 (설정 → 동작) 코드 추적

- **평가 순서** (`sip_endpoint.py`): `resolve_caller_filter(callee, caller)` → 없으면 `resolve_rule(callee)`.
- **적용 액션**: `busy_ai` + 착신 통화 중 → `immediate_ai`로 치환, `forward_always`/`forward` → `forward_to` REGISTER 해석 성공 시 callee 교체, `forward_when_busy` + 통화 중일 때만 동일, 규칙 없음 → `operator_status` away 시 `immediate_ai`.
- **안내멘트**: 규칙의 `announcement_id` 가 있으면 `get_announcement` 로 텍스트 로드 후 `call_info` 에 반영.

## 설정 대비 갭 (리스크)

| 항목 | API·DB | SIP/런타임 |
|------|--------|------------|
| `ring_group` 액션 | 저장·조회 가능 | `sip_endpoint` 에 **RING_GROUP 문자열 분기 없음** — 적용 시 `direct` 에 가깝게 처리될 수 있음 |
| `overflow_policy` | GET/PUT 정상 | INVITE·CallManager 경로에서 **조회/적용 코드 없음** (정책만 저장) |
| 공휴일 스케줄 | `holidays` 패키지 없으면 `_is_holiday` 항상 False | 검증 환경에서 `holidays_lib_not_installed` 경고 확인 |

## 부수 수정 (검증 중 발견)

| 파일 | 내용 |
|------|------|
| `sip-pbx/src/api/routers/chat.py` | `Body` 미 import 로 앱 기동 실패 → `from fastapi import … Body` 추가 |
| `sip-pbx/src/api/routers/call_control_api.py` | `PUT /caller-filters/{id}` 요청 본문이 무시되던 문제 → `updates: Dict = Body(...)` |

## 재실행 방법

```powershell
cd sip-pbx
$env:PYTHONPATH = (Resolve-Path .).Path
.\venv\Scripts\python.exe scripts\verify_call_control_api.py
```

성공 시 `PASS:` 줄 다수 후 `All checks passed` 출력.

## 잔여 과제 (선택)

- `ring_group`·`overflow` 의 SIP/CallManager 연동 및 E2E 시나리오 테스트.
- `holidays` 설치 환경에서 공휴일 스케줄 단위 테스트.
