## 메타

- 작성일: 2026-04-14 (로컬)
- 상태: 구현 완료
- 관련: 통화이력 발신 컬럼, `GET /api/call-history`

## 개요

프론트 통화이력은 `items[].caller_id` 만 표시한다. DB·`metadata.json` 에 `caller_id` 가 비어 있고 `from_number` / `caller` 등 다른 키만 있는 경우 발신이 "—" 로 보였다. 목록 직렬화 시 대체 키를 통합하는 `_resolve_caller_id_for_list` 를 추가했다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `sip-pbx/src/api/routers/call_history.py` | 수정 | `_resolve_caller_id_for_list` 추가, DB·파일 스캔 경로에서 `caller_id` 보강 | 설계대로 |

## 주요 결정 사항

- 우선순위: `caller_id` → `caller` → `from_number` → `caller_number` → `from` → `caller_uri`(sip:user@ 추출).
- `unknown` / `anonymous` 문자열은 건너뜀.

## 잔여 과제

- 여전히 비면 SIP `From` 에 CLI가 없거나(익명), 녹음 파이프라인이 발신 식별자를 아예 기록하지 않는 경우 — 트렁크·게이트웨이에서 P-Asserted-Identity 수집 등은 별도 과제.
