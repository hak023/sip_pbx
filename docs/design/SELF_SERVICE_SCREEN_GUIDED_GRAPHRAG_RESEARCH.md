# 셀프서비스 AI 도우미 — 화면 안내형 응대(Screen-Guided Assistance) 리서치 & GraphRAG 적용 Brownfield 검토

**작성일**: 2026-07-16
**상태**: 리서치/검토 완료 — **구현 착수 전** (PRD/Story화 여부는 사용자 결정 대기)
**목적**: 신규 기능 아이디어("매뉴얼 기반 응대 중 IntelliDecision으로 기능설명/설정방법을 화면 설명과 함께 대화로 제공")를 위해 GraphRAG 기술을 리서치하고, 현재 코드베이스(brownfield)에 적용 가능한지 검토한다.
**관련 문서**:
- [self-service-ai-assistant-prd.md](../product/self-service-ai-assistant-prd.md) (FR12 IntelliDecision, Epic 1)
- [1.10.intelli-decision-intent-tier.story.md](../stories/1.10.intelli-decision-intent-tier.story.md)
- [SELF_SERVICE_HELP_DOCS_DESIGN.md](SELF_SERVICE_HELP_DOCS_DESIGN.md)
- [self-service-manual-content.md](../product/self-service-manual-content.md)

---

## 1. 요구사항 재정리

사용자 요청을 아래 두 갈래로 정리했다.

1. **화면 안내형 응대**: 고객이 "1) 기능 설명" 또는 "2) 설정 방법"을 물으면, AI가 단순 텍스트 설명을
   넘어 **실제 프론트엔드 화면을 설명하면서**(예: "설정 > AI 에스컬레이션 화면에서 드롭다운을 열어
   '상담원 직접 연결'을 선택하세요") 대화로 안내한다.
2. **연관관계 인프라**: 이를 위해 (a) 매뉴얼·API·프론트엔드 화면 간 연관관계가 구조화되어야 하고,
   (b) GraphRAG류의 "연계된 설명"이 가능한 검색/조합 방식이 필요하다는 가설.

본 문서는 (b)의 기술적 타당성을 GraphRAG 중심으로 리서치하고, (a)의 현재 상태를 코드 기준으로
진단한 뒤, brownfield에 맞는 구현 방향을 제안한다.

---

## 2. GraphRAG 리서치

출처: [Microsoft Research Blog — GraphRAG](https://www.microsoft.com/en-us/research/blog/graphrag-unlocking-llm-discovery-on-narrative-private-data/),
[GraphRAG 공식 문서](https://microsoft.github.io/graphrag/)

### 2-1. 핵심 아이디어

기존 "Baseline RAG"(벡터 유사도 기반 top-k 청크 검색)는 두 가지 클래스의 질의에서 취약하다.

- **점 연결(connecting the dots) 실패**: 답이 여러 문서/청크에 흩어진 속성을 통해서만 종합 가능한
  질문(예: "Novorossiya가 한 일은?" — 개별 청크 어디에도 "Novorossiya"가 직접 언급되지 않지만,
  엔터티 간 관계를 따라가면 답이 나옴).
- **전체 데이터셋 총체적 이해 실패**: "데이터의 상위 5개 주제는?" 같은 질문은 특정 청크 유사도로는
  답할 수 없고 데이터 전체의 구조적 요약이 필요.

GraphRAG는 LLM으로 **엔터티·관계 지식 그래프**를 코퍼스 전체에서 추출하고, Leiden 알고리즘으로
계층적 커뮤니티(의미적 클러스터)를 만들어 각 커뮤니티를 요약해 둔다. 질의 시점에 그래프 구조와
커뮤니티 요약을 함께 활용해 컨텍스트를 조립한다.

### 2-2. 동작 원리 요약

**색인(Index) 단계**:
1. 코퍼스를 TextUnit(분석 단위)으로 분할
2. 각 TextUnit에서 LLM으로 엔터티·관계·핵심 주장(claim) 추출 → 지식 그래프 구성
3. Leiden 기법으로 그래프를 계층적 클러스터링(커뮤니티 탐지)
4. 각 커뮤니티를 하위→상위 방향으로 요약 생성(사전 요약, 여러 추상화 레벨)

**질의(Query) 단계** — 4가지 모드:
- **Global Search**: 커뮤니티 요약을 활용해 전체 데이터셋에 대한 총체적/주제적 질문에 답변
- **Local Search**: 특정 엔터티에서 시작해 이웃·연관 개념으로 팬아웃(fan-out)하며 답변 — **본
  요청과 가장 유사한 패턴**(특정 설정 항목 → 연관 화면/필드로 확장)
- **DRIFT Search**: Local Search + 커뮤니티 정보를 추가로 활용
- **Basic Search**: 기존 baseline RAG(top-k 벡터 검색)와 동일

### 2-3. 비용·복잡도

- 색인 단계마다 **다수의 LLM 호출**이 필요(엔터티/관계 추출 + 커뮤니티 요약 생성) — 코퍼스가
  커질수록 인덱싱 비용·시간이 크게 증가.
- 그래프 저장·질의를 위한 별도 인프라(그래프 구조체, 임베딩 스토어, 커뮤니티 리포트 스토어)가 필요.
- 프롬프트 튜닝이 필수 권장 사항(공식 문서: "out of the box 결과가 최선이 아닐 수 있음").
- 근본적으로 **"관계를 몰라서 LLM이 문서에서 자동으로 발견해야 하는"** 상황(예: 수천 건의 뉴스
  기사에서 인물·조직 간 숨은 관계 발견)에 최적화된 도구다.

---

## 3. 현재 코드베이스 진단 (brownfield 현황)

### 3-1. 이미 존재하는 "관계 정보"

| 구성 요소         | 현재 상태                                                                                                                                                                                                                                                                                    |
| ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 매뉴얼 Q&A (52건) | `docs/product/self-service-manual-content.md`, ChromaDB에 `doc_type=self_service_manual`로 색인. **각 Q&A에 `related_domain` 메타데이터가 이미 존재**(`manual_indexer.py::_SECTION_TO_DOMAIN` 매핑, 어제 구현)                                                                               |
| 설정 카탈로그     | `settings_catalog.py` — 7개 도메인(persona/ai-escalation/call-control/chat-relay/contacts/general/integrations) 등록. 각 도메인의 `schema`(필수/옵션 필드), `writable_fields`, `field_allowed_values`(어제 추가) 보유                                                                        |
| 프론트엔드 화면   | `frontend/app/settings/*` — **도메인당 정확히 1개 라우트**(단순 구조): `ai-escalation/page.tsx`(라디오 3종), `chat-relay/page.tsx`(토글+텍스트), `call-control/page.tsx`(내부 탭 5개: 규칙/스케줄/전환대상/연결음/필터), `contacts`, `general`, `integrations`, `persona`(레거시 리다이렉트) |
| IntelliDecision   | `self_service/intent_tier.py` + `self_service_agent.py` 규칙 10 — 탐색성/실행성 발화 구분(Story 1.10, 어제 구현·QA 완료)                                                                                                                                                                     |

**핵심 관찰**: 매뉴얼 Q&A → 카탈로그 도메인 연결은 이미 되어 있다(`related_domain`). **빠진 것은
"카탈로그 도메인 → 프론트엔드 화면(라우트 + 화면 내 UI 요소)" 연결 한 단계뿐**이다.

### 3-2. 연결 갭 (Gap)

1. `settings_catalog.py`에 프론트엔드 라우트 정보가 전혀 없다(도메인명과 라우트 경로가 우연히
   같은 경우가 많지만 — `ai-escalation` → `/settings/ai-escalation` — 명시적으로 등록된 매핑이
   아니라 우연의 일치이며, `persona`/`general`/`integrations`처럼 리다이렉트되는 경우 불일치).
2. 화면 내 **UI 요소 수준 설명**(예: "escalation_mode는 라디오 버튼 3개", "call-control은 5개
   내부 탭으로 구성")이 코드 어디에도 구조화되어 있지 않다 — 사람이 읽는 매뉴얼 텍스트에만
   자연어로 녹아 있다.
3. `self_service_agent.py`의 시스템 프롬프트는 매뉴얼 RAG 컨텍스트만 주입하며, "이 설정을 하려면
   실제로 화면의 어디를 클릭해야 하는지"에 대한 구조화된 정보를 조합하지 않는다.

---

## 4. Brownfield 적합성 검토 결론

### 4-1. Full GraphRAG(엔터티 추출 + Leiden 클러스터링 + 커뮤니티 요약)는 **과한 엔지니어링**

이유:

1. **코퍼스 규모가 매우 작다**: 매뉴얼 Q&A 52건, 카탈로그 도메인 7개, 프론트엔드 라우트 8개 —
   GraphRAG가 해결하려는 "수천 건의 비정형 문서에서 숨은 관계를 발견"하는 문제 규모가 아니다.
2. **관계가 이미 알려져 있다**: "이 매뉴얼 항목이 어떤 설정 도메인에 대응하는지"는 매뉴얼 저자가
   이미 알고 있는 정보이며(섹션 구조 자체가 도메인별로 나뉨), LLM이 텍스트에서 "발견"해야 할
   숨은 관계가 아니다. Full GraphRAG의 엔터티 추출 단계는 오히려 **환각된 관계**를 만들어낼
   리스크만 추가한다.
3. **인덱싱 비용/지연**: LLM 다회 호출(엔터티 추출 + 커뮤니티 요약) 파이프라인은 이 정도 규모의
   정적 데이터에 비해 과도한 운영 비용이다. 매뉴얼이 바뀔 때마다 재인덱싱 파이프라인을 다시
   돌려야 한다.
4. **인프라 추가 부담**: 그래프 구조체·커뮤니티 리포트 저장소가 신규로 필요 — 기존 ChromaDB +
   SQLite 스택에 없는 컴포넌트 추가(NFR 위반 소지, `technical-architecture.md`의 기존 스택
   유지 원칙과 충돌).

### 4-2. GraphRAG의 "핵심 정신"만 경량하게 채용하는 것이 적합

GraphRAG가 실제로 잘하는 것은 **"Local Search" 패턴** — 특정 엔터티(여기서는 "설정 도메인")에서
출발해 이웃 노드(연관 매뉴얼 Q&A, 화면 라우트, UI 요소)로 팬아웃해 컨텍스트를 조립하는 것이다.
이 패턴 자체는 **수작업으로 정의한 소규모 명시적 그래프**로도 동일하게 구현 가능하며, LLM 기반
자동 추출·클러스터링·커뮤니티 요약 없이도 목적을 달성한다.

**결론**: "GraphRAG 프레임워크(microsoft/graphrag 패키지)"를 도입하지 않고, "그래프 기반
멀티홉 컨텍스트 조합"이라는 아이디어만 차용한 **경량 명시적 지식 그래프**를 구축하는 것을 권장한다.
이는 이미 이 코드베이스가 쓰고 있는 패턴(`settings_catalog.py`의 정적 레지스트리 + `_register()`)과
설계 철학이 완전히 일치한다.

---

## 5. 권장 아키텍처 — 경량 화면 그래프(Screen Graph)

### 5-1. 데이터 모델

```
Node 종류:
  - manual_qa       : 매뉴얼 Q&A 항목 (기존 ChromaDB self_service_manual, related_domain 보유)
  - catalog_domain  : settings_catalog.py의 7개 도메인 (기존)
  - frontend_screen : 프론트엔드 라우트 (신규) — {route, title, description}
  - ui_field        : 화면 내 UI 요소 (신규) — {screen, field_name, element_type, label, options?}

Edge 종류(모두 기존 related_domain 패턴의 자연스러운 확장):
  - manual_qa --relates_to--> catalog_domain      (이미 존재, manual_indexer.py)
  - catalog_domain --rendered_by--> frontend_screen (신규)
  - frontend_screen --has_field--> ui_field         (신규)
  - ui_field --maps_to--> catalog_domain.field      (신규, settings_catalog의 writable_fields와 연결)
```

### 5-2. 저장 방식

**별도 그래프 DB 불필요.** 노드/엣지 총량이 수십~백여 개 수준이므로 `settings_catalog.py`와
동일한 패턴 — Python 모듈 내 정적 딕셔너리 레지스트리 + `_register()` 함수 — 로 충분하다.
프로세스 재시작 시에만 반영되면 되고(설정 화면 구조가 실시간으로 바뀌지 않음), 조회는 단순
딕셔너리 lookup이라 지연 시간 영향이 없다(NFR1과 동일 원칙).

### 5-3. 신규 컴포넌트 제안: `self_service/screen_graph.py`

```python
# 개념 스케치 (실제 구현 시 settings_catalog.py의 _register() 패턴을 그대로 미러링)

_SCREEN_REGISTRY: Dict[str, ScreenEntry] = {}

def _register_screen(
    domain: str,
    route: str,
    title: str,
    fields: List[UiFieldSpec],  # [{field, element_type, label, options}]
) -> None: ...

def get_screen_for_domain(domain: str) -> Optional[ScreenEntry]:
    """도메인명으로 화면 라우트·UI 요소 설명을 조회한다."""

def describe_field_for_conversation(domain: str, field: str) -> str:
    """대화체 안내 문구 생성. 예:
    "설정 > AI 에스컬레이션 화면에서 라디오 버튼 3개(운영자 알림/상담원 직접 연결/
    에스컬레이션 안 함) 중 하나를 선택하시면 됩니다." """
```

등록 예시(ai-escalation 도메인):

```python
_register_screen(
    domain="ai-escalation",
    route="/settings/ai-escalation",
    title="AI 에스컬레이션 설정",
    fields=[
        UiFieldSpec(
            field="escalation_mode", element_type="radio",
            label="AI가 모를 때 처리 방식",
            options=[("hitl", "운영자 알림"), ("transfer", "상담원 직접 연결"), ("none", "에스컬레이션 안 함")],
        ),
    ],
)
```

### 5-4. `self_service_agent.py` 연계 (멀티홉 컨텍스트 조합)

현재 시스템 프롬프트 조립 순서(매뉴얼 RAG → 온보딩 체크리스트 → IntelliDecision 힌트)에 **한 단계
추가**:

```
1. RAG 검색 → 매뉴얼 Q&A(들) 획득, 각 Q&A의 related_domain 확인 (기존, 이미 있음)
2. related_domain으로 screen_graph.get_screen_for_domain() 조회 (신규 — "1-hop" 확장)
3. 화면 설명을 시스템 프롬프트에 [화면 안내 정보]로 추가 주입 (신규)
```

이것이 바로 GraphRAG의 "Local Search"(엔터티에서 출발해 이웃으로 팬아웃)를 그대로 재현한 것이다 —
다만 그래프가 LLM으로 자동 추출된 것이 아니라 **개발자가 명시적으로 정의**한 것이라는 차이뿐이다.

### 5-5. IntelliDecision(Story 1.10)과의 결합

- **유형 A(탐색성 — 기능 설명/설정 방법 질문)**: 화면 안내 정보를 포함해 "어떻게 생겼고 어디를
  눌러야 하는지"까지 설명 — 사용자 요청의 핵심("AI가 화면을 설명하면서 대화를 통해 제공")을
  정확히 충족.
- **유형 B(실행성 — 즉시 변경 요청)**: 기존처럼 확인 발화 → Tool 실행(화면 설명은 불필요, 대화로
  이미 끝남 — 다만 Tool 실패/거부 시 폴백으로 "화면에서 직접 설정하시려면 [경로]로 가시면 됩니다"
  안내에 재사용 가능).

---

## 6. 대안 비교

| 방식                              | 관계 발견 방법                      | 인프라                                    | 코퍼스 적합 규모             | 이 프로젝트 적합성                                                |
| --------------------------------- | ----------------------------------- | ----------------------------------------- | ---------------------------- | ----------------------------------------------------------------- |
| Full GraphRAG(microsoft/graphrag) | LLM 자동 추출 + Leiden 클러스터링   | 그래프 저장소 + 커뮤니티 요약 스토어 신규 | 대규모 비정형 문서(수천 건+) | ❌ 과함(코퍼스 52건, 관계 이미 known)                              |
| LightRAG 등 경량 GraphRAG 변형    | LLM 자동 추출(간소화)               | 벡터DB + 경량 그래프                      | 중간 규모                    | ⚠️ 여전히 LLM 추출 단계 필요 — 우리 관계는 이미 알려져 있어 불필요 |
| **경량 명시적 그래프(권장)**      | 개발자가 직접 정의(정적 레지스트리) | 없음(Python dict)                         | 소규모, 구조 안정적          | ✅ 적합 — 기존 `settings_catalog.py` 패턴과 일치                   |
| 현재 방식(순수 벡터 RAG만)        | 없음(청크 유사도만)                 | ChromaDB(기존)                            | —                            | 현재 상태 — 화면 안내 불가(갭)                                    |

---

## 7. 단계적 도입 로드맵 제안 (참고용, PRD화 시 Story 분해 근거)

1. **Phase 1**: 쓰기 가능 3개 도메인(persona/ai-escalation/chat-relay)에 대해서만
   `screen_graph.py` 프로토타입 등록 + `self_service_agent.py` 연계. 가장 자주 쓰이는 케이스로
   빠르게 가치 검증.
2. **Phase 2**: 쓰기 불가 4개 도메인(call-control/contacts/general/integrations) 확장 —
   call-control은 내부 탭이 5개라 `ui_field`뿐 아니라 `ui_section`(탭) 레벨 노드 추가 검토 필요.
3. **Phase 3**: booking 도메인(카탈로그 밖) 포함 여부 검토 — 현재 self_service Tool 범위 밖이므로
   별도 설계 필요(booking_tools.py와의 관계 정리).

---

## 8. 리스크 및 주의사항

- **유지보수 부담**: 프론트엔드 화면이 바뀔 때마다(필드 추가/이동) `screen_graph.py`도 함께
  갱신해야 한다 — `settings_catalog.py`가 이미 겪고 있는 "카탈로그 등록 누락" 리스크와 동일한
  패턴(FR11 유지보수 규칙과 동일하게 문서화 필요).
- **환각 방지**: 화면 설명은 반드시 실제 프론트엔드 코드를 조사해 수작업으로 등록해야 한다
  (존재하지 않는 버튼/필드를 안내하면 신뢰도 저하) — 매뉴얼 작성 시 이미 적용한 원칙
  ("실제 프론트엔드 설정 화면을 직접 조사하여 작성")을 그대로 계승.
- **범위**: 본 리서치는 "그래프 자체 구축 방식"에 한정했다. 실제 대화 UX(예: 텍스트로만 안내할지,
  향후 화면 스크린샷/딥링크를 함께 제공할지)는 별도 PRD 논의가 필요하다.

---

## 9. 다음 단계 제안

이 문서는 **리서치·검토 결과물**이며 아직 PRD/Story로 전환되지 않았다. 진행을 원하면:

1. `self-service-ai-assistant-prd.md`에 FR13(화면 안내형 응대) 추가 여부 결정
2. Epic 1에 신규 Story(예: Story 1.11 "Screen Graph 구축 및 화면 안내 연계") 추가 여부 결정
3. Phase 1 범위(3개 쓰기 가능 도메인)로 우선 프로토타입 진행할지 확인

*최종 업데이트: 2026-07-16*
