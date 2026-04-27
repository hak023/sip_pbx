## 메타

- **작성일**: 2026-04-21
- **상태**: 조사·개선안 (코드 변경 없음)
- **관련**: `frontend/components/GlobalCallDock.tsx`, `src/api/routers/call_history.py` (`GET /api/call-history/caller-context`)

## 개요

CID 영역 제목에 **「재방문」** 이 찍히는 것은 버그라기보다 **UI 폴백 문구**이다. 연락처 표시명이 없을 때 이전 통화가 있으면 동일한 한 단어로만 구분되므로, 정보 가치가 낮고 오해(실제 ‘방문’이 아닌 전화 재인입) 소지가 있다.

## 원인 (현재 동작)

1. **프론트** `GlobalCallDock` 의 `cidTitle` (`useMemo`):

   - `contact_display_name` 있으면 그것을 제목으로 사용.
   - 없고 `has_prior_call === false` 이면 **「첫 통화」**.
   - 그 외(이전 통화 있음 + 표시명 없음) → **「재방문」** 고정.

2. **백엔드** `get_caller_context_for_inbound`:

   - `call_records` 로 직전 종료 통화 1건을 찾으면 `has_prior_call: true`, `prior_call_at`, `prior_summary`, `relationship_label: "returning"` 등을 내려줌.
   - docstring 및 구현상 **연락처 테이블 조인 없음** → **`contact_display_name` 은 항상 `null`** 인 경로가 기본.

3. **결과**: 재인입 고객 대부분이 제목에서 **동일한 「재방문」** 만 보게 됨. (아래 블록에는 직전 통화 시각·요약이 이미 나오므로 제목과 정보가 중복·비대칭.)

## 개선 방향 (난이도·효과)

### A. UI만 조정 (저비용, 즉시 체감)

| 방안 | 내용 | 장단점 |
|------|------|--------|
| A1. 문구·구조 | 「재방문」→「이전 통화 있음」「재인입」 등 중립 표현 + 제목에 **상대 시각** 일부 포함(예: `재인입 · 약 3일 전`) | 구현은 `prior_call_at` 포맷만으로 가능. 법/정책에 따라 ‘재방문’ 용어 자체를 피할 수 있음. |
| A2. 제목을 요약 기반으로 | `prior_summary` 가 있으면 **한 줄만 잘라** 부제 또는 제목 보조(말줄임·tooltip) | 상담원에게 유용할 수 있으나 요약 품질·민감정보 노출 시 주의. |
| A3. 이중 라인 | 제목은 **발신 번호/CLI**(`callerLabel`과 역할 분리), CID 카드 상단은 **관계 태그**만 | 스캔성 향상; 레이아웃만 손보면 됨. |

관련 파일: `frontend/components/GlobalCallDock.tsx` (`cidTitle`, CID `amber` 블록).

### B. 인입 페이로드·표시 로직 보강 (중간)

| 방안 | 내용 |
|------|------|
| B1. SIP Display-Name | `From` 이 `"이름" <sip:...@>` 형이면 **이름을 추출**해 제목 또는 부제에 사용. 현재 `displayCallerFromPayload` 는 `sip:` 일 때 **user 부분 위주**라 표시명이 버려질 수 있음 → `lib/callerDisplay.ts` 또는 dock 전용 파서 확장. |
| B2. `call_started` WS 페이로드 | 백엔드가 이미 넘기는 필드에 `caller_display_name` 등이 있으면 스토어에 넣어 CID 상단에 우선 표시. |

### C. 백엔드·데이터 (고가치, 설계 필요)

| 방안 | 내용 |
|------|------|
| C1. `contact_display_name` 실제 채우기 | 동일 `owner` + 발신 번호(needle)로 **연락처/CRM/예약 고객명** 조회 후 API에 반영. 그러면 제목이 자연스럽게 이름으로 바뀜. |
| C2. 통계 확장 | `prior_call_count`, 최근 N일 통화 수, VIP 플래그 → 「단골」「다회선」 등 **세분 라벨**(남용 주의). |
| C3. 캐리어 CLI | 가능한 인프라에서 **CNAM** 등 외부 CLID 이름을 받으면 그대로 표시(가용성·비용 이슈). |

관련 파일: `src/api/routers/call_history.py` (`get_caller_context_for_inbound`), DB/연락처 모듈.

## 업계 관점 (짧게)

- **CTI 스크린 팝업**은 보통 **CRM 이름 → 최근 인터랙션 요약·시각** 순으로 스캔되게 배치한다.
- 제목 한 줄에 감정·비즈 용어(「재방문」)만 두기보다, **식별자(이름/번호) + 사실(직전 통화 시각)** 조합이 오탐·불만을 줄인다.

## 권장 조합 (실무)

1. **단기**: A1 또는 A3 + 기존 하단 `직전 통화` 블록 유지.  
2. **중기**: B1(SIP 표시명) + C1(연락처 조회로 `contact_display_name` 채움).  
3. **장기**: C2 등은 제품 정책·개인정보 검토 후.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `sip-pbx/docs/reports/2026-04/2026-04-21_1605_CID_REVISIT_LABEL_RESEARCH.md` | 추가 | CID 「재방문」 라벨 원인·개선안 정리 | 구현 없음 |

## 잔여 과제

- 실제 구현 시: 용어 확정(재인입 vs 재방문), `prior_summary` 노출 정책, 연락처 매칭 규칙(국번·해외번호).
