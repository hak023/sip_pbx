# 셀프서비스 카탈로그/N홉 데이터의 테넌트(owner) 스코프 부재 — 실사례 확인 + 계획

- 작성일: 2026-08-07
- 버전: v1.0
- 상태: 조사 완료(DB 직접 쿼리로 사실 확인) · 구현은 계획 단계
- 관련 문서: [2026-08-07_full_reset_hard_delete_fix.md](2026-08-07_full_reset_hard_delete_fix.md),
  [2026-08-07_list_tab_document_count_final_fix.md](2026-08-07_list_tab_document_count_final_fix.md)

## 1. 사용자 지적 요약

지난 리포트에서 "설정/화면 안내는 시스템 공통 정의라 삭제 대상이 아니다"라고 설명했는데,
사용자가 이를 "그렇다고 버그가 아닌 건 아니다"라고 재반박했다. 요지:

1. 이 시스템은 **원래 특정 도메인(로컬호스트 대상)에 종속적으로 개발**되어 owner 개념 없이
   시작했다. 이후 **도메인 비종속·원격(remote) REST-API를 테넌트별로 실행/안내**하는 것이
   목적으로 방향이 바뀌었다("REST-API를 이용하는 어떤 시스템이라도 이 시스템을 통해서 정보
   데이터만 업로드하면 REST-API 조작과 안내를 할 수 있음"). 이 방향 전환을 문서에 명시적으로
   남겨달라고 요청.
2. 따라서 **owner가 없는 데이터는 모두 구 방향(로컬호스트 시절)의 잔여물**이며, 진짜로
   정리 대상이 맞다.
3. **screen_graph를 포함한 N홉(hop) 관련 모든 데이터가 테넌트 지향적(owner-scoped)이어야
   하는데, 실제로 그렇게 되어 있는지 확인이 안 되어 있다.**
4. "전체 삭제"는 테넌트 소유 데이터만 지우는 것으로 범위가 맞다(이 부분은 기존 설명에 동의).
5. QA 시 테넌트별로 N홉 전체(카탈로그+화면 안내 포함)를 점검할 수 있도록 테스트 데이터가
   필요하다.

## 2. 아키텍처 방향 전환 기록 (요청사항 — 이 문서에 명시)

> **이 시스템(셀프서비스 AI 도우미)은 처음엔 로컬 도메인/로컬호스트 전용으로 개발되었으나,
> 현재는 "테넌트가 업로드한 정보(매뉴얼·설정 카탈로그·화면 안내·OpenAPI 스펙)만으로 임의의
> 원격(remote) REST-API 시스템을 조작·안내할 수 있는" 도메인 비종속 플랫폼으로 방향이
> 전환되었다.** 이 전환 이후로는:
> - 모든 지식베이스 데이터(Q&A, 설정 카탈로그, 화면 안내, OpenAPI 엔드포인트 메타)는
>   **테넌트(owner) 단위로 격리**되어야 한다 — 한 테넌트의 데이터가 다른 테넌트의 RAG 검색·
>   설정 화면·REST-API 실행에 노출되면 안 된다.
> - owner가 비어있거나 없는 상태로 남아있는 데이터는 **구 방향(로컬호스트 종속 개발) 시절의
>   잔여물**로 간주하고, 발견 즉시 정리 대상으로 삼는다(신규 기능이 의도적으로 owner-less로
>   설계된 경우가 아닌 한).

## 3. 조사 결과 (실제 DB/ChromaDB 직접 쿼리 — 추측 없음)

### 3.1 `knowledge_documents`(문서 CRUD 테이블)
```
owner='9001'      16건
owner='9999test'   1건
owner IS NULL/빈값  0건   ← 현재 시점엔 ownerless 잔여물 없음
```
→ 이 테이블 자체는 이미 처음부터 `owner` 컬럼 필수(NOT NULL 가능성 높음)로 설계되어 있고,
현재 DB에는 ownerless 잔여 행이 없다. **3.3의 catalog_config와는 상황이 다르다.**

### 3.2 ChromaDB(`knowledge`/`persona` 컬렉션)
```
knowledge: total=203, no_owner=0, owners={1003:78, 1004:21, 9003:52, 9099:52}
persona:   total=4,   no_owner=0, owners={1004:1, 1003:1, 9001:1, 9003:1}
```
→ 벡터 청크 레벨에서도 현재 owner 누락 잔여물은 없음(이전 세션에서 이미 정리된 것으로 보임).

### 3.3 `self_service_catalog_config`(설정 카탈로그 + screen_graph) — **여기가 진짜 문제**
테이블 스키마를 직접 확인한 결과:
```sql
CREATE TABLE self_service_catalog_config (
    id INTEGER PRIMARY KEY,
    config_kind TEXT NOT NULL,     -- 'catalog' | 'screen_graph'
    version_no INTEGER NOT NULL,
    config_json TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 0,
    uploaded_by TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    activated_at TEXT,
    activated_by TEXT NOT NULL DEFAULT ''
)
```
**`owner` 컬럼이 아예 없다.** `config_kind`(catalog/screen_graph)별로 **"현재 활성 버전
(`is_active=1`) 딱 1개"**만 존재하고, 이 활성 버전이 **모든 테넌트에게 공통으로** 적용된다
(`catalog_config_loader.get_active_config()` → `settings_catalog.py`/`screen_graph.py`가
owner 인자 없이 그대로 소비). 실제 저장된 버전들:
```
catalog:      v1(migration_script) v2(migration_script, active) v3(iv2-test-script)
              v4(qa27-script) v5(qa27-chatrelay-test) v6('')
screen_graph: v1~v6 동일 패턴, v2가 active
```
→ **사용자 지적이 정확히 맞다.** 지금 활성화된 catalog v2/screen_graph v2는 초기 마이그레이션
스크립트가 만든 **단일 전역(global) 설정**이며, 테넌트별로 다른 설정 도메인/화면 구성을 가질
수 없다. "AI 에스컬레이션" 클러스터가 모든 owner에서 항상 똑같이 보이는 이유가 바로 이것 —
owner 개념이 아예 코드에 없기 때문에 "그 owner 것"이 아니라 "시스템 전체의 유일한 것"이다.

이것은 단순 잔여물 정리로 끝날 문제가 아니라, **애초에 이 테이블이 도메인 종속(단일 로컬
배포) 시절 설계 그대로 남아있어 테넌트별 격리가 구조적으로 불가능한 상태**라는 뜻이다.

### 3.4 N홉(hop) 그래프 — screen_graph가 owner-scoped 인지
`knowledge_graph.py`/`screen_graph.py`가 hop 간선을 만들 때 사용하는 3개 노드 타입:
- `manual_qa`(Q&A) — ChromaDB `related_domain` 메타, **owner 필터 있음**(RAG 검색 시
  `owner_filter` 적용, 확인됨).
- `settings_catalog`(설정 카탈로그) — **owner 개념 없음**(3.3).
- `frontend_screen`(화면 안내) — **owner 개념 없음**(3.3, screen_graph도 동일 테이블).

→ N홉 경로 중 "Q&A ↔ 카탈로그"·"카탈로그 ↔ 화면" 간선은 존재하지만, 그 **간선의 절반
(카탈로그·화면 쪽 노드)이 테넌트별로 다르게 구성될 수 없다.** 사용자가 요청한 "screen_graph를
포함한 N홉의 모든 데이터가 테넌트 지향적이어야 한다"는 요구사항은 **현재 구현되어 있지 않음**을
확인했다.

## 4. 왜 "버그가 아니다"라고 잘못 답했는가 (자기 진단)

지난 리포트에서 "카탈로그/화면 안내는 시스템 공통 정의라 삭제 대상이 아니다"라고 설명한 것은
**현재 코드가 실제로 그렇게 동작한다는 사실 설명으로는 맞았지만**, 그 설계 자체가 이 시스템의
"테넌트별 원격 REST-API 조작" 목적에 부합하는지는 검증하지 않고 기존 설계를 그대로 정당화하는
답변이었다. 사용자가 지적한 것은 "현재 코드가 이렇게 동작한다"가 아니라 **"이 동작 자체가
목적에 안 맞는 설계 결함"**이라는 것이었고, 이 지적이 맞다.

## 5. 계획(구현 전 — 순서대로 진행)

### Phase 1 — 문서·PRD 갱신 (지금 이 리포트로 1차 완료, 후속 필요)
- [ ] `docs/product/self-service-ai-assistant-prd.md`(또는 마스터 `docs/product/prd.md`)에
  "카탈로그·screen_graph의 테넌트 스코프 부재"를 기술 부채(Known Gap)로 명시.
- [ ] `docs/architecture/`의 관련 아키텍처 문서에 위 §2 방향 전환 문구를 반영(BMAD 하네스
  원칙대로 코드 변경 전에 설계 문서 먼저 갱신).

### Phase 2 — `self_service_catalog_config`에 owner 스코프 추가 (스키마 변경, 영향 큼)
- [ ] `self_service_catalog_config` 테이블에 `owner TEXT NOT NULL DEFAULT ''` 컬럼 추가
      (마이그레이션, 기존 행은 `owner=''`로 "전역 기본값(fallback)"으로 유지).
- [ ] `get_active_config(config_kind, owner)` — **owner별 활성 버전 우선 조회, 없으면
      owner=''(전역 기본값)로 폴백** — 테넌트가 커스터마이즈하지 않았으면 기존처럼 공통
      기본 설정을 쓰게 하여 하위 호환 유지.
- [ ] `save_new_version()`/`activate_version()`에 owner 인자 추가.
- [ ] `catalog_config_loader.py`의 캐시 키를 `(config_kind)` → `(config_kind, owner)`로 확장.
- [ ] `settings_catalog.py`/`screen_graph.py`가 owner를 받아 전달하도록 호출부 수정(이미 대부분
      owner를 인자로 받고 있으므로 전달 경로만 연결하면 됨 — 재작성 범위 아님).
- [ ] "전체 삭제"(`reset_knowledge_base`)에 **owner 커스텀 카탈로그/screen_graph 버전 삭제**
      단계 추가(단, `owner=''` 전역 기본값은 절대 삭제하지 않음 — 다른 테넌트에 영향).

### Phase 3 — 잔여물 정리 정책
- [ ] `owner` 컬럼이 있는 모든 테이블(`knowledge_documents`, ChromaDB 등)은 이미 확인한 대로
      현재 ownerless 잔여물이 없음 — **정기 점검 스크립트**(`scripts/`)로 향후 재발 여부만
      감시(1회성 정리가 아니라 회귀 방지).
- [ ] Phase 2 완료 후에는 `self_service_catalog_config`에서도 "실질적으로 특정 owner만 쓰고
      전역 기본값과 동일한 낡은 버전"을 주기적으로 정리할 수 있는 관리 커맨드 추가 검토.

### Phase 4 — QA 테스트 데이터: 테넌트별 N홉 전수 점검용 데이터셋
- [ ] `docs/qa/fixtures/`에 clothing-store 매뉴얼(Q&A)뿐 아니라, **해당 테넌트 전용
      catalog/screen_graph 버전 fixture**를 추가(Phase 2 완료 후에만 의미 있음 — 지금은
      전역 공통이라 테넌트별 fixture를 만들어도 다른 테넌트와 구분되지 않음).
- [ ] `scripts/qa_clothing_store_admin_simulator.py`(기존 QA 시뮬레이터)에 "이 테넌트의 N홉
      전체 그래프(Q&A→카탈로그→화면)가 owner로 정확히 격리되는지" 검증 스텝 추가:
      테넌트 A의 catalog/screen 커스터마이즈가 테넌트 B에 보이지 않는지 교차 확인.

## 6. 즉시 조치가 필요한지 여부

Phase 2(스키마 변경)는 `settings_catalog.py`/`screen_graph.py`/`catalog_config_loader.py`/
프론트 여러 화면에 걸친 변경이라 **바로 구현하지 않고 계획만 세운다**(사용자 요청 그대로
"리포트해서 계획세워봐"). 구현 착수 여부·우선순위는 사용자 확인 후 진행한다.

*최종 업데이트: 2026-08-07*
