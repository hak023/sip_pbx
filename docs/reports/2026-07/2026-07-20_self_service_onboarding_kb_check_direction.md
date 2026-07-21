# 셀프서비스 AI 도우미 — 온보딩 체크리스트 "지식베이스 업로드" 항목 누락 구현 방향 리포트

**작성일**: 2026-07-20
**요청 배경**: 2026-07-20 점검 리포트에서 FR4/[self-service-ai-assistant-brief.md](../../product/self-service-ai-assistant-brief.md)가
온보딩 체크리스트 예시로 "페르소나 등록, **지식베이스 업로드**, 알림 설정"을 명시했으나, 실제
[onboarding.py](../../../src/ai_voicebot/self_service/onboarding.py)의 `_CHECKS`에는 `persona`/`ai-escalation`/`call-control`
3개만 있고 지식베이스(KB) 업로드 여부 체크가 없음을 확인함. 문서에 명시된 기능이 구현되지 않은
**진짜 누락**이 맞다. 본 리포트는 이를 어떻게 구현할지 방향을 정리한다(코드 변경은 미실시, 방향
검토만).

---

## 1. 왜 빠졌는지 (원인 추정)

[Story 1.5 완료 리포트](../2026-07/2026-07-15_self_service_story_1.5_onboarding_checklist.md)를 보면,
`_CHECKS` 대상은 "설정 카탈로그(Story 1.4)에 이미 등록된 도메인"으로만 국한해서 선정했다
(persona/ai-escalation/call-control). **지식베이스는애초에 `settings_catalog.py`에 도메인으로
등록되어 있지 않다** — KB는 "설정값"이 아니라 ChromaDB에 저장되는 문서 집합이라 카탈로그의
"도메인=값 하나" 모델과 성격이 다르기 때문으로 보인다. Story 1.5는 "카탈로그에 있는 것만
쓴다"는 IV1 원칙을 지키다 보니, 카탈로그 밖에 있는 KB 항목이 조사 대상에서 자연스럽게 누락된
것으로 판단된다(의도적 제외 근거가 리포트에 별도로 없는 것으로 보아 **인지하지 못하고 빠뜨린
쪽에 가깝다**).

## 2. 실제 KB 업로드 여부를 확인할 수 있는 기존 데이터 소스

코드 조사 결과, 신규 파이프라인 없이 기존 벡터 DB 조회만으로 판정 가능하다.

- `src/ai_voicebot/knowledge/chromadb_client.py::get_vector_db()` — 이미 초기화된 ChromaDB 래퍼 싱글턴을 반환.
  `.get(where={...}, limit=...)` 지원(예: `persona_service.py`가 `where={"owner": owner}`로 이미 사용 중인
  것과 동일 패턴).
- 문서 메타데이터의 `doc_type` 값 중 **일반 고객 응대용 지식베이스**는 `doc_type="knowledge"`로 색인됨
  (`extraction_pipeline.py`에서 확인). 셀프서비스 매뉴얼(`self_service_manual`, Story 1.3)과는 다른
  `doc_type`이므로 혼동 없이 구분 가능하다.
- 따라서 `get_vector_db().get(where={"owner": owner, "doc_type": "knowledge"}, limit=1)`의 결과 건수가
  0이면 "아직 지식베이스를 업로드하지 않음"으로 판정할 수 있다(신규 집계 파이프라인 불필요, Story 1.5의
  기존 설계 원칙 NFR3/IV1과 동일하게 "기존 소스 재사용"을 그대로 따를 수 있음).

## 3. 구현 방향(제안)

### 3.1 온보딩 체크(가장 낮은 리스크, 권장 우선순위 1)

`onboarding.py`에 신규 판정 함수만 추가하면 된다(카탈로그 확장 불필요, 온보딩 모듈 내부에 국한):

```python
async def _knowledge_base_incomplete(owner: str) -> bool:
    """지식베이스에 owner 소유 문서가 1건도 없으면 미완료."""
    from src.ai_voicebot.knowledge.chromadb_client import get_vector_db
    vdb = get_vector_db()
    if vdb is None:
        return False  # 조회 실패는 미완료로 오판하지 않음(기존 원칙과 동일)
    try:
        docs = vdb.get(where={"owner": owner, "doc_type": "knowledge"}, limit=1)
        ids = (docs or {}).get("ids") or []
        return len(ids) == 0
    except Exception:
        return False
```

이는 `_CHECKS` 구조가 `(domain, check_fn, message)` 튜플 리스트라 **카탈로그 도메인이 아닌 것도
이미 수용 가능**하다 — `check_fn`이 `settings_catalog.get_domain_value()`가 아니라 별도 조회를 하도록
살짝 예외를 두면 된다. 다만 현재 `get_onboarding_checklist()` 루프는 무조건
`settings_catalog.get_domain_value(domain, owner)`를 호출하는 구조라, "카탈로그를 거치지 않는 체크"를
추가하려면 다음 중 하나가 필요하다:

- **(A) 권장**: `_CHECKS` 튜플에 "값 조회 방식"을 다형적으로 만들어(예: `domain=None`이면 카탈로그를
  건너뛰고 `check_fn(owner)`를 직접 호출), KB 체크만 카탈로그 우회 경로로 추가.
- (B) 대안: `settings_catalog.py`에 `knowledge_base`라는 "가짜 도메인"을 등록해 `get_fn`이 위 벡터 DB
  조회를 감싸도록 만든다 — 다만 KB는 "설정값"이 아니므로 카탈로그의 의미론(도메인=설정)과 맞지 않아
  **비권장**(향후 FR5/FR6 "설정 조회/자동설정" 문맥에 KB가 섞이면 오히려 혼란).

**권장: (A)** — 온보딩 전용 관심사로 좁게 유지하고, 카탈로그는 "설정"만 다루는 순수성을 지킨다.

### 3.2 안내 문구(재사용 가능한 기존 텍스트)

매뉴얼([self-service-manual-content.md](../../product/self-service-manual-content.md)) §2에 이미
"지식베이스 업로드"가 초기 설정 항목으로 언급되어 있으므로, 안내 문구는 그 톤을 재사용:

```
"아직 지식베이스에 등록된 문서가 없어요. 자주 묻는 질문이나 서비스 안내 자료를 업로드하면
AI가 더 정확하게 답변할 수 있어요."
```

### 3.3 자동설정 연계는 없음(읽기 전용 안내에 그침)

KB 업로드 자체(파일 첨부)는 전화/문자 대화로 처리할 수 있는 액션이 아니므로(파일 업로드 UI 필요),
이 체크는 **"미완료 안내"까지만** 하고 Story 1.8류의 자동설정 Tool로 연결하지 않는다 — Screen Graph
(Story 1.11)가 이미 있으니, 안내 시 "지식베이스 화면"으로 연결되는 라우트가 있다면 화면 안내를
함께 제공하는 것도 고려할 수 있다(단, 현재 Screen Graph 레지스트리에 지식베이스 화면이 등록되어
있는지는 별도 확인 필요).

## 4. 예상 작업 규모 및 테스트

- 변경 파일: `onboarding.py` 1개 (함수 1개 추가 + `_CHECKS` 순회 로직에 분기 1곳 추가)
- 신규 테스트: `test_self_service_onboarding.py`에 3~4건 추가(KB 없음/있음/조회 실패/기존 3개 항목과의
  통합 순서) — 기존 18건 회귀 영향 없음(신규 분기만 추가하는 구조라 하위 호환).
- Story 1.5는 이미 "Done"으로 종료되었으므로, 이 보완은 신규 소규모 Story(가칭 "Story 1.5b" 또는
  Story 1.5 Change Log에 추가 항목으로 기록) 형태로 진행하는 것을 권장.

*본 리포트는 방향 제시 목적이며, 이번 세션에서는 코드 변경을 수행하지 않았다(사용자 확인 후 착수 권장).*

*최종 업데이트: 2026-07-20*
