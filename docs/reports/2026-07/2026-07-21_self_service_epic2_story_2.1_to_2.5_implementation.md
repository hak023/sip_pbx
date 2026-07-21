# 셀프서비스 AI 도우미 Epic 2 — Story 2.1~2.5 구현 완료 리포트

- 작성일: 2026-07-21
- 버전: 1.0
- 상태: Story 2.1~2.4 Done, Story 2.5 Review(IV2 실서버 검증만 보류)
- 관련 문서:
  - [PRD Epic 2](../../product/self-service-ai-assistant-prd.md)
  - [Architecture §Epic 2](../../architecture/self-service-ai-assistant-architecture.md)
  - [Story 2.1](../../stories/2.1.catalog-config-storage.story.md)
  - [Story 2.2](../../stories/2.2.catalog-loader-dynamic.story.md)
  - [Story 2.3](../../stories/2.3.screen-graph-dynamic.story.md)
  - [Story 2.4](../../stories/2.4.frontend-catalog-export.story.md)
  - [Story 2.5](../../stories/2.5.frontend-catalog-import.story.md)
  - [Epic 2 기획 리포트](2026-07-20_self_service_epic2_dynamic_catalog_planning.md)

## 1. 요약

사용자가 "셀프서비스 AI 도우미 기능이 너무 하드코딩되어 있다"고 지적한 문제(설정 카탈로그·
Screen Graph가 순수 Python dict라 신규 설정/화면 추가 시 코드 배포가 필요함)를 해결하기 위해
기획했던 Epic 2를 BMAD 원칙(문서→구현→테스트→QA)에 따라 story 단위로 순차 구현했다.

이번 세션에서 **Story 2.1~2.4를 완전히 완료(Done)**했고, **Story 2.5는 코드 구현·단위 테스트까지
완료했으나 IV2(실서버 재시작 없이 즉시 반영되는지 실증)만 사용자 승인을 받은 서버 재시작 이후로
보류**했다(프로젝트 규칙상 서버 재시작은 사용자 승인 필수).

## 2. Story별 구현 내용

### Story 2.1 — 카탈로그/Screen Graph 설정 저장소 설계 및 구현
- `self_service_catalog_config` 신규 SQLite 테이블(`config_kind`/`version_no`/`config_json`/
  `is_active`/`uploaded_by`/`note`/`created_at`) — `src/booking/database.py` `_DDL`에 추가.
- `src/common/self_service_catalog_config_db.py` 신규 — CRUD + 버전 관리
  (`get_active_config`/`save_new_version`/`activate_version`/`list_versions`).
- `settings_catalog.py`에 함수 화이트리스트 레지스트리(`_GET_FN_REGISTRY`/`_UPDATE_FN_REGISTRY`) 신설
  — DB 설정은 실제 Python 콜러블이 아니라 **이름 문자열**만 참조 가능(RCE 방지 핵심 설계).
- `scripts/self_service_catalog_migrate_seed.py` — 하드코딩 값을 1회성으로 DB에 시드하는 멱등 스크립트.

### Story 2.2 — 카탈로그 로더 동적화
- `src/ai_voicebot/self_service/catalog_config_loader.py` 신규 — `get_cached_config()`(버전 변경
  감지 시에만 재조회), `invalidate_cache()`.
- `settings_catalog.py`의 `list_domains()`/`get_domain_schema()`/`get_domain_value()`/
  `domain_writable_fields()`/`get_field_allowed_values()`/`call_update_fn()` 내부 구현을
  `_get_effective_catalog()`(DB 우선, 없으면 하드코딩 폴백) 경유로 교체 — **외부 시그니처 불변**(CR5).
- **회귀 함정 발견 및 해결**: 마이그레이션 스크립트를 실제 개발 DB에 실행해둔 상태였기 때문에
  `monkeypatch.setitem(catalog._CATALOG, ...)`로 정적 dict를 직접 조작하던 기존 단위 테스트 2건이
  DB 우선 동작으로 인해 실패 — `tests_new/unit/conftest.py` 오토유즈 픽스처를 추가해
  `catalog_config_loader.get_cached_config`를 기본 None 고정(하드코딩 폴백 강제)함으로써 해결.

### Story 2.3 — Screen Graph 동적화
- `screen_graph.py`도 동일 패턴(`_get_effective_screens()`, `id()` 기반 캐시)으로 전환.
- Screen Graph는 실행 가능한 콜러블이 없는 순수 데이터라 화이트리스트 불필요.
- 실제 시드된 DB에서 역직렬화한 결과가 정적 레지스트리와 route/title/description/**nav_hint**/
  fields 전부 1바이트도 다르지 않음을 스크립트로 직접 검증(2026-07-20 결함 개선분인 nav_hint가
  DB 이관 후에도 정확히 보존됨을 확인).

### Story 2.4 — 프론트엔드 설정 다운로드(내보내기)
- `GET /api/settings/ai-assistant/catalog-config/export` 신설 — DB 활성 버전이 있으면 그대로,
  없으면 정적 스냅샷을 즉석 직렬화해 반환(다운로드는 항상 성공).
- DRY: `settings_catalog.export_static_snapshot()`/`screen_graph.export_static_snapshot()`를
  새로 추출해 마이그레이션 스크립트와 export API가 공유하도록 리팩터링.
- 프론트엔드 `settings/ai-assistant/docs` 페이지에 "설정 관리" 탭 신설 + "설정 다운로드" 버튼
  (Blob + `<a download>`로 파일 다운로드, 별도 백엔드 Content-Disposition 불필요).

### Story 2.5 — 프론트엔드 설정 업로드(검증·적용·롤백)
- `POST /catalog-config/import` — 카탈로그+Screen Graph를 함께 검증 후 **둘 다 통과해야만** 비활성
  버전으로 저장, 현재 활성 버전과의 diff(added/removed/changed) 미리보기 반환.
- `POST /catalog-config/activate` — 신규 업로드 확정 적용과 과거 버전 롤백을 모두 처리(동일 함수 재사용).
- `GET /catalog-config/versions` — 버전 이력 조회.
- 감사 로그: 별도 테이블 없이 `self_service_catalog_config`에 `activated_at`/`activated_by` 컬럼만
  마이그레이션 추가 — 버전 이력 테이블 자체가 "누가/언제 업로드"(`created_at`/`uploaded_by`)와
  "누가/언제 활성화·롤백"(`activated_at`/`activated_by`)을 모두 겸하는 감사 로그 역할.
- `catalog_config_loader.py::validate_config()`를 이번에 처음 실전 통합(Story 2.1/2.2에서는 정의만
  하고 미사용)하며 구조 검증 강화(get_fn_ref 필수화, screen_graph 필수 키 검사).
- 프론트엔드: 파일 업로드 → 검증 오류/diff 미리보기 → "확정 적용" 버튼, 버전 이력 표 + 롤백 버튼
  (카탈로그/Screen Graph 각각 독립).

## 3. 테스트 결과

| 항목                                                         | 결과                                                                                          |
| ------------------------------------------------------------ | --------------------------------------------------------------------------------------------- |
| 신규 단위 테스트                                             | Story 2.1: 27개, Story 2.2: 11개, Story 2.3: 9개, Story 2.4: 4개, Story 2.5: 30개             |
| 전체 회귀(`tests_new/unit/test_ai_voicebot` + `test_events`) | **327개 전체 통과**(회귀 0건)                                                                 |
| 실제 개발 DB 마이그레이션                                    | 성공 확인(카탈로그/Screen Graph 각 v1 시드 → 값 왕복 일치 확인 → 재실행 시 멱등 skip 확인)    |
| 프론트엔드                                                   | TS 언어서버 진단(get_errors) 오류 없음. 실제 브라우저 동작은 미확인(서버 재시작 후 확인 필요) |

## 4. 알려진 제한사항 / 후속 조치 필요

1. **Story 2.5 IV2 미검증**: "설정 업로드 → 확정 적용 → 서버 재시작 없이 다음 대화부터 즉시
   반영"을 실제 운영 서버로 실증하지 못했다. 이번에 수정한 백엔드 코드가 아직 실행 중인 서버
   프로세스에 반영되지 않았기 때문(코드 변경 후 재시작 필요) — 프로젝트 규칙상 서버 재시작은
   사용자 승인이 필요해 사용자 승인 후 다음 세션에서 검증 예정.
2. **Story 2.6(intent_tier.py 키워드 힌트 제거)**: 착수 전. "베이스라인 확보 → 제거 → 재검증 →
   저하 시 롤백" 절차가 실서버(`/api/self-service/test/converse`) 접근을 요구해 역시 재시작 승인
   대기 중.
3. **Story 2.7(통합 QA, master-qa.md Branch L)**: 위 두 Story 완료 후 진행 예정.
4. **Story 2.8(매뉴얼 도메인 매핑 동적화)**: 우선순위 낮음, 선택 사항.

## 5. 다음 단계

사용자가 서버 재시작을 승인하면:
1. Story 2.5 IV2 시나리오 실행(업로드→적용→재시작 없이 대화 테스트로 라벨/화면 안내 변경 확인,
   화이트리스트 미등록 함수명 업로드 시 거부되는지 등).
2. Story 2.6 베이스라인 확보 → intent_tier 힌트 제거 → 재검증.
3. Story 2.7 통합 QA 전체 실행 및 Epic 2 최종 완료 리포트 작성.

*최종 업데이트: 2026-07-21*
