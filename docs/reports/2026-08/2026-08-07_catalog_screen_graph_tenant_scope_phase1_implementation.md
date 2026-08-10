# NFR11 계획 실행 완료 — 설정 카탈로그/Screen Graph owner 스코프 구현

- 작성일: 2026-08-07
- 상태: Phase 1~4 전체 완료(호출부 owner 전달 포함, 아래 §추가 구현 참고)
- 관련 문서: [2026-08-07_catalog_screen_graph_tenant_scope_gap_and_plan.md](2026-08-07_catalog_screen_graph_tenant_scope_gap_and_plan.md)

## 수행 내역

### Phase 1 — 문서 갱신
- `docs/product/self-service-ai-assistant-prd.md`: NFR11 신설(기술 부채 명시, 방향 전환 기록).
- `docs/architecture/self-service-ai-assistant-architecture.md`: Epic 2/3 사이에 "알려진 기술
  부채" 절 추가.

### Phase 2 — DB/캐시 레이어 owner 스코프 (구현 완료)
- `src/booking/database.py`: `self_service_catalog_config`에 `owner TEXT NOT NULL DEFAULT ''`
  컬럼 추가(신규 설치 DDL + 기존 DB `ALTER TABLE` 마이그레이션), `UNIQUE(config_kind, version_no)`
  → `UNIQUE(config_kind, owner, version_no)`로 확장(새 유니크 인덱스로 대체 — SQLite는 기존
  제약을 ALTER로 못 바꾸므로).
- `src/common/self_service_catalog_config_db.py`: `get_active_config`/`save_new_version`/
  `activate_version`/`list_versions` 모두 `owner: str = ""` 파라미터 추가 — **owner 지정 시
  테넌트 커스텀 버전 우선 조회, 없으면 `owner=''`(전역 기본값)로 자동 폴백**. 신규
  `purge_owner_versions(owner)` 추가(`owner=''` 호출은 항상 무시 — 전역 기본값 보호).
- `src/ai_voicebot/self_service/catalog_config_loader.py`: 캐시 키를 `config_kind` →
  `(config_kind, owner)`로 확장, `invalidate_cache()`도 owner 단위 무효화 지원.
- `src/ai_voicebot/self_service/knowledge_documents.py`: `reset_knowledge_base()`가 이제
  `purge_owner_versions()`도 호출해 테넌트 커스텀 카탈로그/screen_graph 버전을 함께 초기화.
- API/프론트: `KnowledgeBaseResetResponse`에 `deleted_catalog_versions` 필드 추가(백엔드 Pydantic
  + 프론트 TS interface).

**실서버 검증(마이그레이션 적용 확인)**: `init_db()`를 실제 `data/booking.db`에 대해 실행 —
기존 12개 행(catalog/screen_graph v1~v6) 모두 `owner=''`로 데이터 손실 없이 보존됨을 직접
쿼리로 확인. `get_active_config('catalog')`/`get_active_config('catalog', owner='1001')` 둘 다
동일하게 활성 v2를 반환함을 확인(커스텀 버전이 없는 테넌트는 기존과 동일하게 전역값 사용 —
회귀 없음).

**✅ (2026-08-07 같은 세션 후속) 호출부 owner 전달도 완료**: 처음엔 범위가 넓어 보류했으나,
실제로 확인해보니 `settings_catalog.py`/`screen_graph.py`의 소비 함수들은 이미 owner 인자
없는 전역 API였을 뿐 다른 구조적 장벽은 없어, 각 함수에 `owner: str = ""` 파라미터를 추가하고
실제 호출부(`self_service_agent.py`, `hybrid_rag.py`, `tools.py`, API 라우터)에 이미 있던
`owner` 지역 변수를 그대로 전달하는 것으로 마무리했다. 상세는 아래 "다음 단계" 절 참고.

### Phase 3 — 잔여물 정기 점검 스크립트
- `scripts/check_ownerless_residue.py` 신규: `knowledge_documents`/`tool_execution_log`/
  `self_service_decision_log`(SQLite)와 ChromaDB 전 컬렉션의 owner 누락 여부를 점검. 실행
  결과 현재 잔여물 없음(`[OK] ownerless 잔여 데이터 없음`).

### Phase 4 — QA 계획 문서화
- `docs/qa/self-service-ai-assistant-e2e-manual-driven-qa-plan.md`에 "갭 D" 추가 — 카탈로그/
  screen_graph가 아직 owner-scoped가 아니므로, 테넌트 간 격리 교차 검증 QA 케이스는 Phase 2의
  호출부 전달 Story 완료 후에만 의미가 있음을 명시(지금 만들면 항상 전역 공유라 무의미).

## 검증

- `pytest tests_new/unit -k "catalog_config or screen_graph or settings_catalog or
  knowledge_document or knowledge_base or self_service"` — 기존 무관 사전 결함 1건
  (`test_register_markdown_document_uses_manual_adapter`) 제외 전부 통과.
- `test_self_service_catalog_config_db.py`의 temp DB fixture 스키마도 신규 `owner` 컬럼 반영
  (누락 시 `no such column: owner`로 실패하는 것을 직접 확인 후 수정).
- 실제 `data/booking.db`에 마이그레이션 적용 + 기존 데이터 무손실 확인(위 §Phase 2).
- `npx tsc --noEmit` — 프론트 타입 에러 없음.

## 다음 단계 — ✅ (2026-08-07 같은 날 후속 세션) 호출부 전달까지 완료

사용자가 "보류한 다음 단계 진행해줘"라고 요청해 아래를 모두 구현했다(당초 별도 Story로 미루려
했던 부분):

1. **읽기 경로 owner 전달 완료**: `settings_catalog.py`의 `list_domains()`/`get_domain_schema()`/
   `domain_writable_fields()`/`get_field_allowed_values()`와 `screen_graph.py`의
   `get_screen_for_domain()`/`list_all_screens()`/`describe_screen_for_conversation()`가 전부
   `owner: str = ""` 파라미터를 받아 `_get_effective_catalog(owner)`/`_get_effective_screens(owner)`로
   전달한다(각각 owner별 캐시 딕셔너리로 분리 — 기존 단일 캐시 변수를 `Dict[owner, ...]`로 확장).
   `knowledge_graph.py`의 hop 리졸버(`_resolve_rendered_by`/`_resolve_writable`)도 이미 받고 있던
   `owner` 인자를 실제로 전달하도록 수정(기존엔 `_owner` 파라미터를 무시하고 있었음).
2. **실제 호출부 연결**: `self_service_agent.py::_format_capability_section()`/
   `_format_screen_guidance()`(세션의 실제 `owner`를 전달), `hybrid_rag.py::search_hybrid_multi_domain()`
   (이미 받은 `owner` 인자를 `list_domains()`에도 전달), `tools.py::_get_self_service_settings()`,
   API 라우터 `GET /api/settings/ai-assistant/catalog`(신규 `owner` 쿼리 파라미터, 기본값 빈
   문자열이라 프론트 기존 호출은 그대로 전역값 조회 — 하위 호환 유지).
3. **의도적으로 남겨둔 예외**: `tools.py::_build_writable_fields_hint()`는 LangChain Tool의
   docstring/description에 **모듈 로드 시 1회만 정적으로 굽는(bake) 문자열**이라, 이 함수 자체를
   테넌트별로 다르게 만들려면 Tool 바인딩을 세션(owner)마다 다시 만드는 더 큰 구조 변경이
   필요하다 — 이번 범위에서는 여전히 전역(owner='') 힌트를 사용한다(현재 실제 배포 상태와 동일,
   회귀 아님). 필요해지면 별도 Story로 분리.

**테스트 중 발견·수정한 테스트 인프라 이슈**: 시그니처 변경으로 25개 이상의 기존 유닛테스트가
한꺼번에 깨졌는데, 원인은 크게 두 갈래였다 — (a) `tests_new/unit/conftest.py`의 autouse
픽스처가 `get_cached_config`를 1-인자 lambda로 monkeypatch하고 있어 2-인자 호출과 충돌(모든
tests_new/unit 테스트에 영향), (b) 개별 dynamic-loader 테스트 파일들이 캐시 리셋 픽스처에서
전역 캐시를 `None`으로 되돌리고 있어 새 `Dict` 기반 캐시와 타입 불일치. 둘 다 수정 후 전체
재실행 결과 이 작업과 무관한 `test_sip_core/test_call_session.py`(12건, `Leg`/`CallSession`
생성자 시그니처 불일치 — 이번 변경과 전혀 무관, 사전 존재하던 결함)와 기존에 알려진
`test_register_markdown_document_uses_manual_adapter` 1건을 제외한 전부 통과.

## 검증(추가)

- `pytest tests_new/unit`(전체, `test_ai_pipeline` 제외) — 위 13건(사전 결함 1 + 무관 12건)
  제외 전부 통과.
- `npx tsc --noEmit` — 프론트 타입 에러 없음(이번 라운드는 백엔드만 수정).

## 남은 후속 과제(진짜 마지막 단계)

1. 프론트엔드에 테넌트별 카탈로그/screen_graph 버전 업로드·활성화 UI 추가(기존 Epic 2 export/
   import 흐름을 owner 파라미터만 추가해 재사용 가능할 것으로 예상 — 실제 설계는 후속 Story에서).
2. `tools.py::_build_writable_fields_hint()`를 테넌트별로 동적화하려면 Tool 바인딩 자체를
   세션(owner)마다 재생성하는 구조 변경 필요(현재는 전역 힌트, 기존과 동일).
3. 후속 Story 완료 후 QA 갭 D의 "테넌트 간 커스터마이즈 격리" 교차 검증 케이스를 실제로 추가.

*최종 업데이트: 2026-08-07*
