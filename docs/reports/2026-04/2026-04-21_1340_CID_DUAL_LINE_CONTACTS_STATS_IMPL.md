## 메타

- **작성일**: 2026-04-21
- **상태**: 구현 완료
- **관련 계획**: CID 이중 라인(A3) + 연락처·발신 통계(C2)

## 개요

CID 도크에 **발신 식별(1행)** 과 **연락처·관계 라벨(2행)** 을 분리하고, **최근 30일·전체 인입 건수**(현재 통화 제외)를 표시한다. `caller_contacts` 테이블·REST API를 추가하고, 통화 종료 시 **예약 고객명 또는 LLM** 으로 표시명을 `이름_끝4자리` 형태로 자동 저장한다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `src/booking/database.py` | 수정 | `_DDL`에 `caller_contacts` 테이블·인덱스 추가 | `init_db()` 시 생성 |
| `src/common/caller_needle.py` | 추가 | SIP/숫자 needle·끝4자리 접미사 유틸 | `call_history`에서 함수 이전 |
| `src/api/routers/call_history.py` | 수정 | `caller-context` 응답에 연락처명·`inbound_count_30d`·`inbound_count_all` 병합 | needle 공통 |
| `src/common/call_record_db.py` | 수정 | `count_inbound_calls_for_caller`, `_params_inbound_caller_owner` | 직전 통화와 동일 owner/caller WHERE |
| `src/common/caller_contact_db.py` | 추가·수정 | CRUD·자동 upsert·`update` 시 `source=manual`·중복 `canonical_phone` 방지 | |
| `src/services/caller_contact_autofill.py` | 추가 | 예약명 우선·LLM JSON·`schedule_caller_contact_autofill` | |
| `src/ai_voicebot/pipecat/pipeline_builder.py` | 수정 | `upsert_call_record` 직후 자동 연락처 스케줄 | `_llm`·transcript 발췌 |
| `src/ai_voicebot/orchestrator/ai_orchestrator.py` | 수정 | `end_call`에서 동일 스케줄(legacy) | 대화 메시지 발췌 |
| `src/api/routers/caller_contacts.py` | 추가·수정 | `GET/POST/PATCH/DELETE`·PATCH 검증·409 중복 | owner 쿼리/바디 |
| `src/api/main.py` | 수정 | `caller_contacts` 라우터 등록 | |
| `frontend/store/useActiveCallDockStore.ts` | 수정 | `CallerContextPayload`에 건수 필드 | |
| `frontend/components/ActiveCallDockProvider.tsx` | 수정 | `normalizeCallerContext` | |
| `frontend/components/GlobalCallDock.tsx` | 수정 | CID 이중 라인 + 통계 문구, 「재방문」→「재인입」 | |
| `frontend/components/AppHeader.tsx` | 수정 | 메인 내비 «발신 연락처»(후속), 당시는 설정 메뉴 | 현재 `/contacts` — [`2026-04-21_1707_CONTACTS_MAIN_NAV_CALL_DOCK.md`](2026-04-21_1707_CONTACTS_MAIN_NAV_CALL_DOCK.md) |
| `frontend/app/contacts/page.tsx` | 추가·수정 | 목록·수동 추가·삭제·편집(PATCH)·트리 UI(후속) | 당시 `app/settings/contacts/page.tsx` |
## 주요 결정 사항

- **canonical_phone**: `caller_match_needle` 결과와 동일 키로 `call_records` 매칭·연락처 행을 일치시킨다.
- **수동 우선**: `source=manual` 이면 자동 upsert는 스킵한다.
- **예약 힌트**: `bookings.call_id` 또는 `customer_phone LIKE` 로 `customer_name`이 있으면 LLM 없이 `auto_booking_hint` 로 저장한다.
- **통계**: `exclude_call_id`(현재 통화)를 제외한 COUNT; 시각 비교는 `end_time` 없으면 `start_time` 보조(`COALESCE`).

## 잔여 과제

- ~~연락처 설정 화면에서 **인라인 수정(PATCH)** UI~~ → 구현됨: [`frontend/app/contacts/page.tsx`](../../frontend/app/contacts/page.tsx)(구 `settings/contacts`)에서 **수정** / `PATCH /api/caller-contacts/{id}`; 저장 시 DB `source=manual`·`llm_confidence=NULL` ([`caller_contact_db.update_caller_contact`](../../src/common/caller_contact_db.py)).
- 기존 DB는 **서버 `init_db()` 재실행** 또는 수동 `CREATE TABLE` 으로 `caller_contacts` 생성 필요.
