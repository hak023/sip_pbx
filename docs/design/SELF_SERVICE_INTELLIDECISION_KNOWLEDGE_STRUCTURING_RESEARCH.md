# 셀프서비스 AI 도우미 — IntelliDecision·지식 구조화·시각화 개선 리서치 (2026-07-27)

**작성일**: 2026-07-27
**작업 유형**: 리서치·기술 검토(코드 변경 없음, 방향 승인 시 후속 Brief/PRD/Story로 진행)
**관련 문서**:
- [SELF_SERVICE_SCREEN_GUIDED_GRAPHRAG_RESEARCH.md](../design/SELF_SERVICE_SCREEN_GUIDED_GRAPHRAG_RESEARCH.md) — 2026-07-16, 화면 안내형 응대 리서치(경량 Screen Graph 채택 근거)
- [2026-07-23_intellidecision_enhancement_research.md](../reports/2026-07/2026-07-23_intellidecision_enhancement_research.md) — IntelliDecision D~I 유형·능력 레지스트리 리서치
- [self-service-ai-assistant-prd.md](../product/self-service-ai-assistant-prd.md), [self-service-ai-assistant-architecture.md](../architecture/self-service-ai-assistant-architecture.md)
- 코드: `src/ai_voicebot/langgraph/nodes/self_service_agent.py`, `src/ai_voicebot/self_service/screen_graph.py`, `settings_catalog.py`, `tools.py`

---

## 1. 요청 배경 (사용자 5개 관찰)

1. 정적인 사항이 너무 많다.
2. AI가 어떻게 IntelliDecision을 해서 지식베이스·화면안내·변경가능 설정을 안내하게 되는지
   "지식의 정리"가 제대로 안 되어 보인다(정적 코딩 때문 아닌지).
3. 가시적으로 잘 정리된 정보를 보여주는 게 중요하다.
4. 상황에 따라 연계된 정보를 보여주도록 GraphRAG 등 기술이 있다면 활용을 고려해야 한다.
5. 위 방안에 대해 기술 검토·리서치로 방향을 잡아달라.

## 2. 현재 상태 진단 (코드 직접 확인 기준)

### 2.1 이미 구현된 것 (과거 세션에서 이미 상당 부분 진행됨)

| 구성 요소                                | 파일                                                                     | 상태                                                                                              |
| ---------------------------------------- | ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------- |
| 설정 카탈로그(도메인·필드·writable 여부) | `settings_catalog.py`                                                    | DB 우선 + 정적 폴백, 핫 리로드(Epic 2, 2026-07-20/21)                                             |
| Screen Graph(도메인↔화면↔UI요소)         | `screen_graph.py`                                                        | 정적 레지스트리, DB 우선 + 정적 폴백(Epic 2 Story 2.3)                                            |
| 매뉴얼 Q&A → 도메인 연결                 | `manual_indexer.py`(`related_domain` 메타데이터)                         | ChromaDB 색인 시 태깅                                                                             |
| RAG 검색 결과 → Screen Graph 1-hop 확장  | `self_service_agent.py::_screen_guidance_from_rag_hits()`(L323~)         | `related_domain` 메타데이터로 1-hop 팬아웃 — **이미 GraphRAG "Local Search" 정신을 일부 구현 중** |
| 능력 목록 동적 생성(유형 C)              | `self_service_agent.py::_format_capability_section()`(L385~, Story 1.17) | 카탈로그 실시간 조회 + Tool 능력 정적 매핑 조합                                                   |

**결론**: 사용자가 우려하는 "정적"의 실체는 카탈로그·화면·매뉴얼 데이터 자체가 아니다 —
이들은 이미 상당히 동적화되어 있다(Epic 2). **진짜 정적인 것은 "IntelliDecision 정책
(유형 A~I가 언제·어떻게 적용되는가)" 그 자체가 하나의 거대한 자연어 프롬프트 문자열로
하드코딩되어 있다는 점**이다.

### 2.2 핵심 문제 — "정책이 데이터가 아니라 프롬프트 산문(prose)"

`self_service_agent.py`의 `_SELF_SERVICE_SYSTEM_PROMPT_TEMPLATE`(기본, 10개 규칙) +
`_TOOL_USAGE_INSTRUCTION`(Tool 바인딩 시 추가, 4개 규칙 + 유형 A/B 상세)을 직접 읽어보면:

- 유형 A/B/C/F/I(총 5종)의 판단 기준과 응대 방식이 **번호 붙은 자연어 문단**으로 한 프롬프트에
  이어 붙어 있다. 유형 D/E/G/H(리서치에서 제안된 나머지 4종)는 아직 반영되지 않았다(리서치
  문서 §4의 "우선순위 D/F/I만 즉시 구현" 결정이 그대로 유지된 상태).
- 새 유형을 추가할 때마다 **프롬프트 텍스트를 직접 편집**해야 하고, 그때마다 다른 번호(11~14
  등)와 상호 참조("시스템 프롬프트의 유형 F 규칙을 따르세요")를 손으로 맞춰야 한다 — 실제로
  과거 세션 메모에 "프롬프트 번호 재조정 함정(2회째 반복 확인)"이라는 기록이 남아 있을 만큼
  이미 유지보수 비용으로 드러난 문제다.
- 이 구조에서는 **"지금 이 발화가 왜 유형 B로 판단됐는지"를 코드로 추적할 방법이 없다** — 전부
  LLM의 자유 판단에 위임되어 있어, 로그에도 "판단 근거"가 남지 않는다(현재 로그는 결과만
  남긴다: `self_service_tool_start`/`self_service_agent_response`). 이것이 사용자가 느낀
  "지식의 정리가 안 되어 보인다"는 감각의 실체라고 판단한다 — **정책 자체가 코드에서 조회 가능한
  구조가 아니라, 사람만 읽을 수 있는 프롬프트 산문에 녹아 있기 때문**이다.

## 3. 외부 기술 리서치

### 3.1 GraphRAG(Microsoft) — 기존 리서치 재확인, 결론 불변

공식 문서(microsoft.github.io/graphrag) 재확인 결과, Full GraphRAG(엔터티 자동 추출 + Leiden
커뮤니티 클러스터링 + 커뮤니티 요약)는 "코퍼스에 **숨어 있는** 관계를 LLM이 자동으로 발견해야
하는" 대규모 비정형 데이터에 최적화된 도구라는 점이 재확인됐다. 이 도메인(카탈로그 7개 도메인,
화면 8개, 매뉴얼 Q&A 52건, IntelliDecision 유형 9종)은:

- 규모가 작다(노드 총합 100개 미만).
- 관계가 **이미 알려져 있다**(어떤 매뉴얼 Q&A가 어떤 도메인에 속하는지는 저작 시점에 이미 안다).

→ **Full GraphRAG 프레임워크 도입 결론은 여전히 기각**(2026-07-16 리서치와 동일 결론, 재검토
결과도 동일). 다만 GraphRAG의 **"Local Search"(엔터티 → 이웃 팬아웃)** 아이디어는 여전히 유효한
차용 대상이며, 이미 §2.1의 1-hop 확장으로 일부 구현되어 있다 — 이를 **명시적 다중 홉 그래프
순회 함수**로 승격시키는 것이 3.3의 제안이다.

### 3.2 "Workflows vs Agents" 원칙 (Anthropic, 2024-12) — 이번에 추가로 참고

Anthropic의 "Building Effective Agents"(engineering blog)는 실전에서 성공한 LLM 시스템 대부분이
복잡한 프레임워크가 아니라 **단순하고 조합 가능한 패턴**을 썼다는 점을 핵심으로 제시한다. 특히
관련성이 높은 두 패턴:

- **Routing(라우팅) 워크플로**: 입력을 분류해 서로 다른 전용 처리 경로로 보내는 패턴 — "서로
  다른 유형의 고객 문의(일반 질문/환불/기술지원)를 각각 다른 프롬프트·툴로 라우팅"하는 예시가
  공식 문서에 직접 언급된다. 지금 IntelliDecision(유형 A~I)이 하려는 일과 정확히 같은 문제
  범주다.
- **투명성(transparency) 원칙**: "에이전트의 계획 단계를 명시적으로 드러내라"를 3대 핵심
  원칙 중 하나로 꼽는다 — 이는 사용자의 관찰 ③(가시적으로 잘 정리된 정보를 보여주는 게
  중요하다)과 정확히 일치한다.

**시사점**: 지금의 구조(하나의 거대 프롬프트가 9종 유형을 전부 판단)는 Anthropic이 권장하는
"라우팅으로 관심사를 분리하라"는 원칙과 반대 방향으로 진화해 왔다(유형이 늘 때마다 같은
프롬프트에 계속 이어붙임). 유형별로 **최소한 데이터 차원에서라도 분리된 정의**를 갖는 것이
바람직하다.

### 3.3 결론 — 무엇을 채택할지

| 후보                                                                    | 채택 여부           | 이유                                                             |
| ----------------------------------------------------------------------- | ------------------- | ---------------------------------------------------------------- |
| Full GraphRAG(microsoft/graphrag 패키지, 엔터티 자동추출+커뮤니티 요약) | **기각**(재확인)    | 코퍼스 규모·관계 기지성 문제로 과설계, 2026-07-16 결론과 동일    |
| GraphRAG의 "Local Search" 정신(엔터티→이웃 팬아웃)                      | **채택(확장)**      | 이미 1-hop 구현됨 — 명시적 다중 홉 순회로 승격                   |
| "정책을 데이터로" — IntelliDecision 유형을 구조화된 레지스트리로 분리   | **채택(핵심 제안)** | Anthropic 라우팅 원칙과 부합, 유지보수·추적성 문제의 근본 해결책 |
| 정책/그래프 시각화(운영자용)                                            | **채택**            | 사용자 관찰 ③ 직접 대응, 디버깅·신뢰성 향상                      |

---

## 4. 권장 방향 (3개 축, 상호 독립적으로 단계 진행 가능)

### 축 A — IntelliDecision "정책을 데이터로" 구조화 (가장 중요, 근본 원인 해결)

**현재**: 유형 A~I가 프롬프트 문자열 안에 번호로 나열됨.

**제안**: `self_service/intellidecision_policy.py`(가칭) 신설 — `settings_catalog.py`와 동일한
"정적 레지스트리 + `_register()`" 패턴을 그대로 재사용한다(이 코드베이스가 이미 검증한 패턴,
신규 개념 도입 아님).

```python
@dataclass
class IntentTypeSpec:
    code: str                  # "A", "B", "C", ... "I"
    name: str                  # "탐색성", "실행성", "도움 요청", ...
    trigger_examples: List[str]
    requires_tool: bool        # Tool 호출이 필요한 유형인지 (base prompt vs TOOL_USAGE_INSTRUCTION 배치 결정에 사용)
    guidance: str              # 응대 방식 서술(현재 프롬프트 산문에 있던 것과 동일 텍스트, 이 레지스트리로 이관)
    related_types: List[str]   # 예: F는 A/B 판단 이전에 선행, D는 B 확인 중에만 트리거

_INTENT_TYPE_REGISTRY: Dict[str, IntentTypeSpec] = {}
def _register_intent_type(...): ...

def render_prompt_section() -> str:
    """레지스트리에서 번호·순서를 자동 생성 — 번호 재조정 함정을 구조적으로 제거."""

def get_intent_type(code: str) -> Optional[IntentTypeSpec]: ...
def list_intent_types() -> List[IntentTypeSpec]: ...
```

**효과**:
1. 새 유형(D/E/G/H 등 아직 미구현분) 추가가 "레지스트리에 항목 추가"가 되어, 번호 재조정
   함정이 구조적으로 사라진다(`render_prompt_section()`이 순서를 자동 계산).
2. `list_intent_types()`가 존재하므로 **로그·시각화 양쪽에서 재사용 가능**(축 C와 직결).
3. 프롬프트 텍스트 자체는 legacy와 동일하게 유지 가능(레지스트리 → 문자열 렌더링이므로 회귀
   위험 최소 — CR 원칙 준수, "기존 응대 품질 무변경"을 시험으로 검증 가능).
4. 향후 유형별 A/B 테스트, 유형별 온/오프 feature flag도 자연스럽게 가능해진다(현재는
   프롬프트 문자열 편집 없이는 불가능).

**주의**: 이건 "LLM이 결정 트리로 판단하게 강제"하는 것이 아니다 — 최종 판단은 지금처럼 LLM이
자연어 맥락으로 내린다(이 저장소의 확립된 원칙: "키워드 매칭이 아니라 LLM 판단 우선"). 바뀌는
것은 **그 판단 기준을 사람과 코드 양쪽이 조회 가능한 데이터로 관리하느냐**일 뿐이다.

### 축 B — Screen Graph를 "명시적 다중 홉 그래프"로 확장

**현재**: `manual_qa --relates_to--> catalog_domain --rendered_by--> frontend_screen` 3종
노드, 1-hop 팬아웃만 명시적으로 구현(`_screen_guidance_from_rag_hits`).

**제안**: 동일한 정적 레지스트리 철학을 유지한 채 노드 타입을 확장한다.

```
기존: manual_qa → catalog_domain → frontend_screen → ui_field
신규 추가: catalog_domain → tool (settings_catalog의 get_fn/update_fn ↔ tools.py의 SELF_SERVICE_TOOLS)
신규 추가: intellidecision_type → catalog_domain (예: 유형 E "실행취소"는 catalog_domain의
           writable 필드가 있는 도메인에만 적용 가능하다는 관계)
```

`self_service/knowledge_graph.py`(가칭)에 `traverse(start_node, max_hops=2)` 형태의 범용
순회 함수를 두면, 지금처럼 함수마다 개별적으로 "related_domain 꺼내서 screen_graph 조회"를
반복 구현하지 않고 하나의 조회 인터페이스로 수렴한다. **여전히 그래프 DB나 GraphRAG 패키지는
불필요** — 파이썬 dict 기반 인접 리스트로 충분한 규모다(§3.3의 결론과 일치).

### 축 C — 가시화(Visualization) — 운영자/개발자용 지식 그래프 뷰어

**현재**: `settings/ai-assistant/docs` 페이지에 Screen Graph 열람 탭이 있지만(Story 1.12),
정적 표 형태다.

**제안**: 축 A/B가 데이터 구조로 정리되면, 프론트엔드에 **그래프 시각화 뷰**를 추가하는 비용이
크게 낮아진다(이미 구조화된 JSON을 그대로 그리기만 하면 됨). 두 단계로 나눠 제안한다.

1. **1단계(저비용)**: 기존 `settings/ai-assistant/docs` 페이지에 신규 탭 "AI 의사결정 로직"을
   추가해, 축 A 레지스트리를 표/카드 형태로 나열(유형별 트리거 예시·Tool 필요 여부·설명) —
   그래프 렌더링 없이 데이터만 노출해도 사용자 관찰 ③(가시적으로 잘 정리된 정보)을 상당 부분
   충족한다.
2. **2단계(중비용, 선택)**: mermaid.js 또는 경량 force-directed 그래프 라이브러리(예:
   `react-force-graph`, 신규 의존성 추가 필요 — 도입 여부는 별도 승인)로 축 B의 그래프를
   시각적으로 렌더링. **실통화 경로에는 영향 없는 순수 운영자 대시보드 기능**이라 리스크가
   낮다.

## 5. 하지 않을 것 (Non-Goals, 명시적으로 배제)

- **microsoft/graphrag 패키지 도입**: §3.3 근거로 기각.
- **LLM 자동 엔터티/관계 추출 파이프라인**: 관계가 이미 알려져 있어 불필요, 환각 리스크만 추가.
- **IntelliDecision을 결정 트리/상태 머신으로 강제 전환**: 최종 판단은 LLM의 맥락 이해에 맡기는
  현재 원칙을 유지한다(레지스트리는 "판단 기준 데이터"이지 "판단 로직 대체"가 아님).
- **별도 그래프 데이터베이스(Neo4j 등) 도입**: 노드/엣지 규모가 수백 개 미만이라 불필요.

## 6. 제안 우선순위 및 다음 단계

| 순위 | 항목                                    | 예상 난이도                                 | 비고                                  |
| ---- | --------------------------------------- | ------------------------------------------- | ------------------------------------- |
| 1    | 축 A(IntelliDecision 정책 레지스트리화) | 중간(리팩터링, 기존 프롬프트 텍스트는 유지) | 근본 원인 해결, 나머지 축의 선행 조건 |
| 2    | 축 B(Screen Graph 다중 홉 확장)         | 낮음(축 A와 유사 패턴 재사용)               | 축 A 완료 후 자연스럽게 이어짐        |
| 3    | 축 C-1(정적 표 형태 가시화)             | 낮음(기존 페이지에 탭 추가)                 | 축 A만 있어도 착수 가능               |
| 4    | 축 C-2(그래프 시각화)                   | 중간(신규 프론트엔드 의존성 검토 필요)      | 선택 사항, 사용자 가치 확인 후 진행   |

**다음 단계**: 사용자가 위 방향(특히 축 A 착수 여부)을 승인하면, BMAD 절차(PRD FR 추가 →
architecture 갱신 → Story 분할)로 착수한다. 이번 문서는 리서치·방향 제시로 범위를 한정하며
코드·프롬프트는 변경하지 않았다.

*최종 업데이트: 2026-07-27*
