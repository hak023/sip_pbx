# 도메인 비종속 지식베이스 & IntelliDecision 플랫폼 설계 (초안 v2)

**작성일**: 2026-08-04 (2026-07-30 리서치를 대체 재작성, 같은 날 IntelliDecision 레퍼런스 보강 + 핵심 기술 시장 동향 확장 + 유형 검증·hop 전략·대화 이론 심화)
**버전**: 2.3 (§3.10~3.12 신설 — IntelliDecision 유형을 Alexa 표준 내장 인턴트와 1:1 대조, GraphRAG Local/Global Search로 hop 전략 근거 보강, 혼합 주도권 대화·Rasa Forms로 대화 주도 목표 이론 근거 보강)
**상태**: 초안 — PRD FR32/Story 1.26~1.29 착수 전 설계

<!-- 아래는 2026-07-30 원본 리서치 헤더(참고용, 부록 A에서 요약) -->
**원본 작성일**: 2026-07-30
**작업 유형**: 외부 리서치(시장 동향·학술자료·산업 사례, 코드 변경 없음)
**관련 문서**:
- [SELF_SERVICE_INTELLIDECISION_KNOWLEDGE_STRUCTURING_RESEARCH.md](SELF_SERVICE_INTELLIDECISION_KNOWLEDGE_STRUCTURING_RESEARCH.md) — 2026-07-27 선행 리서치(정책 레지스트리 방향, 이미 Story 1.18/1.19로 구현됨)
- [SELF_SERVICE_CORE_FEATURES_EXTERNAL_RESEARCH.md](SELF_SERVICE_CORE_FEATURES_EXTERNAL_RESEARCH.md) — 2026-07-29 Story별 학술·산업 매핑(§2 매뉴얼 RAG 부분과 직접 연결)
- [SELF_SERVICE_SCREEN_GUIDED_GRAPHRAG_RESEARCH.md](SELF_SERVICE_SCREEN_GUIDED_GRAPHRAG_RESEARCH.md) — GraphRAG Brownfield 기각 이력(규모 근거)
- `self-service-ai-assistant-architecture.md` §IntelliDecision 정책 레지스트리/Screen Graph 2-hop(현재 구현)

> **범위 전환 안내**: 2026-07-30 리서치는 "현재 매뉴얼 Q&A 52건 규모"를 전제로 한 벤더 비종속·투명성
> 리서치였고, Story 1.23~1.25로 그 일부(인벤토리 조회 API, RAG 매칭 메타데이터, SourceAdapter
> 프로토콜 골격)가 이미 구현되었다. 이번 문서는 사용자가 제시한 **더 큰 목표 전환**을 반영한다 —
> "특정 도메인(셀프서비스 매뉴얼)에 묶인 RAG"가 아니라 **웹 화면에서 임의의 데이터를 업로드하면
> 지식베이스가 되고, 그 지식이 어떻게·어떤 질문에 쓰일지 화면에서 미리 확인 가능한 범용 지식베이스
> 플랫폼**으로 방향을 넓힌다.

---

## 1. 목표 재정의

사용자가 제시한 10개 요구사항을 6대 목표로 정리한다.

| #   | 목표                                                                         | 대응 요구사항(원문 번호) |
| --- | ---------------------------------------------------------------------------- | ------------------------ |
| ①   | 도메인 비종속 — 특정 기능(셀프서비스)에 묶이지 않는 범용 지식베이스          | 1                        |
| ②   | 웹 업로드로 데이터(API 문서·매뉴얼 등) 투입, 업로드 포맷 정의                | 2                        |
| ③   | 업로드된 지식의 조회·수정·삭제(CRUD)를 웹에서 수행                           | 3                        |
| ④   | IntelliDecision 분류와 연계된 관계형 지식 구조, hop 확장 가능 설계           | 4, 5                     |
| ⑤⑥  | 어떤 질문에 KB가 어떻게 매칭·응답될지 실행 전에도 화면에서 확인 가능(투명성) | 6, 7                     |
| ⑦⑧  | 실사용 사례·연구자료 레퍼런스(링크+발췌) 조사 및 시스템 적용 방향 수립       | 8, 9                     |

---

## 2. 현황 진단 — 무엇이 이미 있고 무엇이 없는가

코드베이스를 직접 추적해 확인한 사실만 기술한다(추정 아님).

### 2.1 있는 것

| 컴포넌트                                    | 경로                                                       | 현재 상태                                                                                                                                                                               |
| ------------------------------------------- | ---------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `SourceAdapter` 프로토콜                    | `src/ai_voicebot/self_service/manual_indexer.py`           | `load_pairs`/`load_pairs_with_meta` 인터페이스 정의됨(Story 1.25). 구현체는 `MarkdownManualAdapter` **하나뿐**                                                                          |
| `knowledge_graph.py::traverse()`            | `src/ai_voicebot/self_service/knowledge_graph.py`          | `max_hops` 파라미터를 받지만 실제로는 `manual_qa→catalog_domain→frontend_screen→intent_type` **고정 3단 체인 하나만** 순회 — 신규 노드/엣지 타입을 등록해 그래프를 확장하는 구조가 아님 |
| `intellidecision_policy.py::IntentTypeSpec` | `src/ai_voicebot/self_service/intellidecision_policy.py`   | 유형 A~I 9종에 `rag_enabled`/`rag_source_scope`/`rag_strategy_hint` 메타데이터 보유(Story 1.24)                                                                                         |
| `knowledge_base_inventory.py`               | `src/ai_voicebot/self_service/knowledge_base_inventory.py` | 색인 현황(총 청크 수·도메인 분포·최근 색인 시각) 읽기 전용 집계(Story 1.23)                                                                                                             |
| REST API 8종                                | `src/api/routers/settings_ai_assistant.py`                 | `docs`/`catalog`/`screen-graph`/`intellidecision-policy`/`knowledge-base/inventory`/`catalog-config/*` — **전부 읽기 전용 조회 또는 설정값(카탈로그) 관리**                             |
| 프론트 5개 탭                               | `frontend/app/settings/ai-assistant/docs/page.tsx`         | Q&A/카탈로그/화면안내/IntelliDecision정책/지식베이스현황 — **전부 뷰어, 편집 불가**                                                                                                     |

### 2.2 없는 것 (핵심 격차)

1. **지식 콘텐츠 자체의 업로드/수정/삭제 API가 없다.** 매뉴얼은 `docs/product/self-service-manual-content.md` 파일을 직접 편집한 뒤 `POST /docs/index?force=true`로 재색인해야 하며, 이는 코드/문서 저장소 접근 권한이 있는 개발자만 가능하다. "웹페이지에서 업로드"라는 요구사항을 전혀 충족하지 못한다.
2. **PDF/OpenAPI 등 비-마크다운 소스 어댑터 구현체가 없다.** 프로토콜만 있고 실제 구현이 하나뿐이라 벤더 비종속이라 부르기 이르다.
3. **그래프가 진짜 n-hop 구조가 아니다.** 노드/엣지 타입이 하드코딩되어 있어 새 지식 유형(예: API 엔드포인트, 절차 단계)을 추가하려면 `knowledge_graph.py` 자체를 다시 고쳐야 한다.
4. **"이 질문에 KB가 어떻게 응답할지" 실행 전에 확인할 방법이 없다.** 현재는 실제 대화(`POST /api/self-service/test/converse`)를 태워봐야만 알 수 있다 — 사용자가 명시적으로 금지한 "시험해봐야 아는" 상태 그대로다.
5. **도메인이 `self_service`에 강하게 결합되어 있다.** `owner`(테넌트) 스코프는 있지만 "이 지식이 어느 업무 도메인/제품 영역에 속하는지"는 `settings_catalog.py`의 고정 7개 도메인에 종속된다.

---

## 3. 시장 동향 — 핵심 기술별 선행 서비스 사례 (원문·번역·상세 설명·실사용 방식)

> **총론**: 이 설계가 의존하는 핵심 기술은 크게 두 갈래다 — **(A) 지식베이스 표현·검색**
> (RAG·청킹·지식 그래프)과 **(B) 발화 의도 분류·라우팅**(우리의 IntelliDecision에 해당).
> 두 갈래 모두 이미 다수의 선행 서비스가 프로덕션에서 검증한 성숙한 시장이며, 어느 한 벤더의
> 특이한 주장이 아니라 **여러 회사가 독립적으로 수렴한 공통 패턴**이라는 점이 중요하다. 아래는
> **§3.1~3.3(지식베이스 계열)**, **§3.4~3.8(IntelliDecision·라우팅 계열)** 순으로 정리하며,
> 각 항목은 원문 인용 → 한국어 번역 → 상세 설명 → 실제 사용 방식 → 우리 시스템 적용 방향
> 순으로 기술한다.

### 3.1 Anthropic — Contextual Retrieval (지식베이스 청킹 품질)

**출처**: https://www.anthropic.com/news/contextual-retrieval (2024-09-19, Anthropic 엔지니어링 블로그)

**원문**:
> "Contextual Embeddings reduced the top-20-chunk retrieval failure rate by 35% (5.7% → 3.7%).
> Combining Contextual Embeddings and Contextual BM25 reduced the top-20-chunk retrieval failure
> rate by 49% (5.7% → 2.9%)... Reranked Contextual Embedding and Contextual BM25 reduces the
> top-20-chunk retrieval failure rate by 67% (5.7% → 1.9%)."

**번역**: "맥락 임베딩(Contextual Embeddings)만 적용해도 상위 20개 청크 검색 실패율이 35%
감소했다(5.7%→3.7%). 맥락 임베딩과 맥락 BM25를 함께 적용하면 실패율이 49% 감소한다
(5.7%→2.9%)... 재순위화(rerank)까지 더한 맥락 임베딩+맥락 BM25는 실패율을 67% 감소시킨다
(5.7%→1.9%)."

**상세 설명**: 문서를 청크(작은 조각)로 쪼개 임베딩하면, 개별 청크가 "이게 어느 문서·어느
맥락의 내용인지"를 잃어버리는 문제가 생긴다. 예를 들어 "매출이 전분기 대비 3% 늘었다"라는
청크만 남으면 어느 회사·어느 분기 얘기인지 알 수 없다. Anthropic의 해법은 청크를 색인하기
**전에** LLM(Claude Haiku)으로 "이 청크가 전체 문서에서 어떤 맥락인지"를 50~100 토큰짜리
문장으로 자동 요약해 청크 앞에 붙이는 것이다(사람이 수작업으로 태그를 다는 게 아니라 전량
자동화). Anthropic은 코드베이스·소설·논문 등 다양한 데이터셋에서 이 실험을 반복해 위 수치를
얻었다.

**실제 사용 방식**: Anthropic은 이 기법을 자사 API 고객(엔터프라이즈 RAG 시스템을 구축하는
개발자)에게 [쿡북](https://platform.claude.com/cookbook/capabilities-contextual-embeddings-guide)
형태로 공개해, 프롬프트 캐싱(Prompt Caching)과 결합하면 청크 100만 토큰당 약 1.02달러의
저비용으로 전체 지식베이스에 이 전처리를 적용할 수 있다고 안내한다.

**적용 방향**: 현재 우리 저장소의 수작업 `{domain: xxx}` 태그(§9 매뉴얼 파싱)는 이미 좋은
실천이지만 사람이 태그를 달아야 한다. Contextual Retrieval은 이를 자동화해 신규 소스(API 문서,
PDF 등)를 업로드할 때 사람이 태그를 안 달아도 LLM이 청크-문서 관계를 자동 주석하게 만드는
방향이다 — Story 1.29(스파이크) 채택 여부 판단의 근거.

### 3.2 Intercom **Fin** — 실제 상용 AI 고객 에이전트(12,000개 이상 기업 고객)

**출처**: https://fin.ai/ (Intercom의 AI 고객 에이전트 제품 공식 페이지)

**원문 (§01, 실적)**:
> "Fin has industry leading resolution rates, averaging 76% across 12,000+ customers, with many
> seeing over 85%... Currently at 2 million weekly resolutions and growing fast."

**번역**: "Fin은 업계 최고 수준의 문제 해결률을 보유하고 있으며, 12,000개 이상의 고객사에서
평균 76%, 다수는 85% 이상을 달성하고 있다... 현재 주간 200만 건의 문제를 해결하고 있으며
빠르게 성장 중이다."

**원문 (§10, 노코드 지식 구성)**:
> "Fin is the only Agent you can fully manage yourself, configuring tone, behaviour, knowledge
> and more, all without needing any engineering resources... you never need to contact us to
> make changes to any part of the system."

**번역**: "Fin은 톤·행동·지식 등 모든 것을 엔지니어링 리소스 없이 완전히 스스로 관리할 수 있는
유일한 에이전트다... 시스템의 어떤 부분을 변경하든 우리(Intercom)에게 연락할 필요가 없다."

**원문 (§14, 라이브 반영 전 테스트)**:
> "Fin has a full testing suite to run simulations, regression testing, and manual inspection.
> This gives you the confidence to set changes live, knowing they will improve the customer
> experience."

**번역**: "Fin은 시뮬레이션·회귀 테스트·수동 점검을 실행할 수 있는 완전한 테스트 스위트를
갖추고 있다. 이는 변경사항을 라이브로 반영하기 전에 그것이 고객 경험을 개선할 것이라는 확신을
운영자에게 준다."

**원문 (§13, 절차 기반 지식)**:
> "Fin is trained to understand your business goals, all your policies, rules, guidelines, and
> operating procedures... reason about problems, and resolve very complex, multi-step workflows
> via Procedures."

**번역**: "Fin은 비즈니스 목표, 모든 정책·규칙·가이드라인·운영 절차를 이해하도록 학습되어
있다... 문제에 대해 추론하고, 'Procedures'(절차)를 통해 매우 복잡한 다단계 워크플로를
해결한다."

**상세 설명**: Fin은 Intercom(2018년부터 고객 응대 플랫폼을 운영해온 회사)이 2023년 출시한
AI 고객 서비스 에이전트로, "문제 해결 성공 건에 대해서만 과금"하는 성과 기반 가격 모델을
업계 최초로 도입했다(Kyle Poyar, Growth Unhinged 발행인 인용 — "Intercom이 2023년 초 파괴적인
성과 기반 가격 모델로 [Fin을] 출시했으며, 이는 대부분의 경쟁사보다 1년 앞선 것"). 이는 벤더가
"우리 AI가 실제로 정확히 응답한다"는 확신이 있어야만 가능한 가격 모델이며, 그 확신의 근거가
바로 §14의 테스트 스위트(시뮬레이션)와 §10의 노코드 지식 구성이다.

**실제 사용 방식**: Anthropic 자신도 고객사로서 Fin을 도입해 "직접 만드는 대신 Fin을
선택했다"고 밝혔으며(§01 각주), Matterport·WHOOP·Personio 등의 실사용 후기가 공식 페이지에
인용되어 있다 — 예: WHOOP의 Emily Shirley(Growth Product 담당)는 "몇몇 벤더는 화려한 데모를
보여줬지만 모든 변경에 엔지니어가 필요했다. 나는 통제권이 필요했고, Fin이 그것을 줬다"고
언급했다.

**적용 방향**:
- §10은 요구사항 ②③(엔지니어링 없이 웹에서 지식을 구성)의 실제 상용 선례 — 코드 배포 없는
  지식 CRUD가 12,000개 이상 기업에서 검증된 표준 관행임을 뒷받침. **Story 1.26**의 직접 근거.
- §14는 요구사항 ⑤⑥(사전 예측 투명성)과 정확히 일치하는 기능 — "라이브 반영 전 시뮬레이션"이
  실제 업계 표준 관행임을 확인. 본 설계의 **응답 시뮬레이터**(§5.2)가 이 사례를 직접 채택한
  것이다. **Story 1.27**의 직접 근거.
- §13의 "Procedures"(다단계 절차)는 단일 Q&A를 넘어서는 구조화된 지식 표현 사례 — §4의 n-hop
  그래프 확장에서 `procedure_step` 노드 타입을 예약하는 근거. **Story 1.28**과 연결.

### 3.3 Glean — 엔터프라이즈 "지식 그래프 + 벡터DB" 하이브리드 아키텍처

**출처**: https://www.glean.com/blog/knowledge-graph-vs-vector-database (2026-03-20 최신 갱신,
Emrecan Dogan, Glean Head of Product 작성)

**원문**:
> "Explainability and reasoning: Because the graph is explicit, you can trace why a result
> emerged. When an AI agent surfaces a document or recommends a next step, it can show its work:
> 'This incident is linked to that service, which is owned by this team, whose runbook is here.'
> That kind of traceability is essential for trust, debugging, anomaly detection, and regulatory
> compliance."

**번역**: "설명 가능성과 추론: 그래프는 명시적이므로 왜 그 결과가 나왔는지 추적할 수 있다.
AI 에이전트가 문서를 제시하거나 다음 행동을 추천할 때, '이 장애는 저 서비스와 연결되어 있고,
그 서비스는 이 팀이 소유하며, 그 팀의 운영 매뉴얼은 여기 있다'는 식으로 자신의 근거를 보여줄
수 있다. 이런 추적 가능성은 신뢰·디버깅·이상 탐지·규제 준수에 필수적이다."

**상세 설명**: Glean은 "지식 그래프냐 벡터DB냐"라는 이분법 자체가 잘못된 질문이라고 주장한다.
지식 그래프(Enterprise Graph)는 조직의 사람·팀·문서·티켓 같은 **엔터티와 관계**(누가 무엇을
소유하는지, 누가 누구와 협업하는지)를 다루는 데 강하고, 벡터DB는 **비정형 텍스트의 의미적
유사도**(문서 내용이 서로 비슷한지)를 다루는 데 강하다고 구분한다. Glean은 두 계층을 결합해
"그래프로 범위를 좁힌 뒤 그 안에서 벡터 유사도 검색"(Graph-scoped search)이나 "그래프 신호로
벡터 검색 결과를 재순위화"(Graph-informed ranking) 같은 하이브리드 패턴을 실제 프로덕션에
적용하고 있다고 설명한다.

**실제 사용 방식**: Glean은 이 아키텍처("시스템 오브 컨텍스트")를 자사 엔터프라이즈 AI
검색·에이전트 제품에 실제로 구현해 판매 중이며, 별도 벤치마크 블로그
([2026-02-12](https://www.glean.com/blog/search-benchmark))에서 "Glean의 검색 결과가
ChatGPT의 기업 지식 모드보다 1.9배, Claude 엔터프라이즈 검색보다 1.6배 더 선호되었다"는
평가 결과를 공개했다(자사 벤치마크이므로 마케팅 편향 가능성을 감안해 참고자료로만 활용).

**적용 방향**: 현재 `knowledge_graph.py`의 "고정 3단 체인"을 **범용 노드/엣지 등록 테이블**로
일반화해야 한다는 방향(§5.1)이 개별 회사의 주장이 아니라 업계 공통 트렌드임을 뒷받침한다.
특히 "그래프로 범위를 좁힌 뒤 벡터 검색"(Graph-scoped search) 패턴은 향후 IntelliDecision
유형별 `rag_source_scope`(Story 1.24에서 이미 필드만 존재)를 실제 검색 필터로 연결할 때
참고할 구체적 구현 패턴이다.

### 3.4 IntelliDecision 핵심 레퍼런스 ① — Anthropic "Building Effective Agents": Routing 워크플로

> **왜 이 레퍼런스가 IntelliDecision과 가장 밀접한가**: 우리의 IntelliDecision(발화를 유형
> A~I로 분류한 뒤 유형별로 다른 전략을 적용하는 것)은 Anthropic이 정의한 "Routing"이라는
> 명명된 워크플로 패턴과 구조적으로 동일하다. 이 문서는 Anthropic이 다수의 실제 고객사와
> 함께 프로덕션에 배포한 경험을 바탕으로 작성한 것이라 추상적 이론이 아니라 실전 근거다.

**출처**: https://www.anthropic.com/research/building-effective-agents (2024-12-19, Erik S.,
Barry Zhang 작성, Anthropic 엔지니어링)

**원문**:
> "Routing classifies an input and directs it to a specialized followup task. This workflow
> allows for separation of concerns, and building more specialized prompts. Without this
> workflow, optimizing for one kind of input can hurt performance on other inputs."

**번역**: "라우팅은 입력을 분류하여 전문화된 후속 작업으로 보낸다. 이 워크플로는 관심사의
분리와 더 전문화된 프롬프트 설계를 가능하게 한다. 이 워크플로가 없으면, 한 종류의 입력에
맞춰 최적화하는 것이 다른 종류의 입력에 대한 성능을 해칠 수 있다."

**원문(적용 예시)**:
> "Directing different types of customer service queries (general questions, refund requests,
> technical support) into different downstream processes, prompts, and tools. Routing easy/common
> questions to smaller, cost-efficient models like Claude Haiku 4.5 and hard/unusual questions to
> more capable models like Claude Sonnet 4.5 to optimize for best performance."

**번역**: "고객 서비스 문의의 여러 유형(일반 질문, 환불 요청, 기술 지원)을 서로 다른 후속
프로세스·프롬프트·도구로 나누어 보낸다. 쉽고 흔한 질문은 Claude Haiku 4.5처럼 더 작고
비용 효율적인 모델로, 어렵고 드문 질문은 Claude Sonnet 4.5처럼 더 유능한 모델로 라우팅해
성능을 최적화한다."

**상세 설명**: Anthropic은 이 문서에서 "가장 성공적인 LLM 에이전트 구현은 복잡한 프레임워크가
아니라 단순하고 조합 가능한 패턴을 사용했다"고 결론짓는다(다수 고객사와의 협업 경험 기반).
그중 "Routing"은 6가지 핵심 워크플로(프롬프트 체이닝, **라우팅**, 병렬화, 오케스트레이터-워커,
평가자-최적화자, 자율 에이전트) 중 하나로 명시적으로 분류되며, "고객 서비스 문의 분류"가
1순위 실사용 예시로 제시된다. 우리의 IntelliDecision 유형 A~I는 바로 이 "Routing" 패턴의
구체적 구현이며, 각 유형이 서로 다른 프롬프트 규칙(FR12/25/26)과 Tool 필요 여부를 갖는 것이
"분리된 관심사"에 해당한다.

**실제 사용 방식**: Anthropic 자신이 Claude API 문서·쿡북에서 이 패턴을 코드 예제로
제공하며(고객 지원, 콘텐츠 검토, 데이터 파이프라인 라우팅 등), 다수의 SaaS 고객 지원
챗봇(Zendesk AI Agents, Intercom Fin 등)이 "문의 유형 분류 → 전용 처리 경로"의 내부 구조를
공개적으로 언급하고 있다(각 벤더가 세부 구현은 비공개).

**적용 방향**: Anthropic의 "핵심 원칙 3가지"(①에이전트 설계의 단순성 유지 ②에이전트의 계획
단계를 명시적으로 드러내는 투명성 우선 ③도구 문서화를 통한 에이전트-컴퓨터 인터페이스 정교화)
중 **②투명성 원칙**이 사용자가 이번에 요구한 목표 ⑤⑥⑦(사전 예측 가능한 투명성)의 학술적
근거다 — "에이전트가 무엇을 할지 미리 보여줘야 한다"는 원칙이 IntelliDecision 정책
레지스트리(Story 1.18/1.24)와 응답 시뮬레이터(§5.2, Story 1.27) 설계의 이론적 기반이다.

### 3.5 IntelliDecision 핵심 레퍼런스 ② — Semantic Router (오픈소스, 실제 프로덕션 채택 640+건)

**출처**: https://github.com/aurelio-labs/semantic-router (Aurelio AI, MIT 라이선스,
2026-08 기준 GitHub 스타 3.8k, 640개 이상 프로젝트가 의존성으로 사용 중)

**원문**:
> "Semantic Router is a superfast decision-making layer for your LLMs and agents. Rather than
> waiting for slow LLM generations to make tool-use decisions, we use the magic of semantic
> vector space to make those decisions — routing our requests using semantic meaning."

**번역**: "Semantic Router는 LLM과 에이전트를 위한 초고속 의사결정 계층이다. 도구 사용
결정을 내리기 위해 느린 LLM 생성을 기다리는 대신, 의미 벡터 공간을 이용해 그 결정을 내린다
— 요청을 의미론적 의미로 라우팅하는 것이다."

**상세 설명**: 이 라이브러리는 사용자 발화를 미리 정의된 `Route`(예: "정치 얘기", "잡담")
각각의 대표 예시 발화들과 임베딩 유사도로 비교해 어느 라우트에 해당하는지 판정한다 — LLM
호출 없이 임베딩 유사도만으로 판정하므로 매우 빠르다(수 ms 수준). 특정 라우트에도 매칭되지
않으면 `None`을 반환해 "분류 불가"임을 명시적으로 드러낸다(우리 유형 F "모호성 해소"와
개념적으로 대응).

**실제 사용 방식(학술·산업 근거)**:
- **학술 논문**: Dimitrios Manias 외, ["Semantic Routing for Enhanced Performance of
  LLM-Assisted Intent-Based 5G Core Network Management and
  Orchestration"](https://arxiv.org/abs/2404.15869)(IEEE GlobeCom 2024) — 통신사가 5G
  코어망 운영에서 자연어 명령을 의도(intent)별로 분류해 자동화 오케스트레이션에 연결하는 데
  이 기법을 실제로 적용한 연구다. IntelliDecision처럼 "발화 유형에 따라 다른 자동화 경로로
  분기"하는 것이 통신 인프라 운영에도 실사용되고 있음을 보여준다.
- **실사용 후기**: Adrien Sales(개발자)는 자신의 블로그에서 ["Semantic Router로 로컬
  LLM(ollama/gemma2)을 이용해 10ms 이내에 응답해야 하는 실제 콜센터(hotline) 문제를
  해결한 사례"](https://dev.to/adriens/semantic-router-w-ollamagemma2-real-life-10ms-hotline-challenge-1i3f)를
  공개했다 — **콜센터(전화 응대) 시나리오에서 발화를 초저지연으로 분류해야 하는 문제**라는
  점에서 우리 SIP PBX의 실시간 음성 파이프라인과 도메인이 정확히 일치한다.
- GitHub의 "Used by" 탭에 640개 이상의 공개 프로젝트가 의존성으로 등록되어 있어, 단발성
  실험이 아니라 여러 프로덕션 시스템에서 반복 채택되고 있음을 시사한다.

**적용 방향**: 우리 IntelliDecision은 현재 전량 LLM 호출(메인 LLM의 프롬프트 규칙)로 유형을
판정하는데, Semantic Router의 접근은 "LLM 호출 전에 임베딩 유사도로 1차 필터링"하는 **저지연
사전 라우팅 계층**을 추가할 수 있음을 보여준다. 다만 2026-07-20 Story 2.6에서 우리는 이미
"키워드/임베딩 기반 힌트"(`intent_tier.py`)를 회귀 검증 후 **의도적으로 제거**한 이력이
있으므로(§6 Non-Goal 재확인 항목에 추가), 이 방향을 재도입하려면 반드시 Story 2.6과 동일한
"베이스라인 확보 → 도입 → A/B 재검증 → 저하 시 롤백" 절차를 다시 밟아야 한다 — 근거 없이
재도입하지 않는다.

### 3.6 Google **Dialogflow CX** — 흐름(Flow)·페이지(Page)·라우트(Route) 기반 대화 상태 머신

**출처**: https://docs.cloud.google.com/dialogflow/cx/docs/basics (Google Cloud 공식 문서,
한국어 현지화 버전 직접 확인)

**원문(한국어 공식 문서)**:
> "복잡한 대화상자에는 여러 가지 대화 주제가 포함되는 경우가 많습니다. 예를 들어 피자 배달
> 에이전트는 음식 주문, 고객 정보, 확인을 별도의 주제로 가질 수 있습니다... 흐름은 이러한
> 주제와 연결된 대화 경로를 정의하는 데 사용됩니다."
>
> "인텐트는 대화 차례 1회에서 최종 사용자의 의도를 분류합니다... 경로는 최종 사용자 입력이
> 인텐트 또는 세션 상태의 일부 조건과 일치하면 호출됩니다. 인텐트 요구사항이 있는 경로를
> 인텐트 경로라고도 합니다. 조건 요구사항만 있는 경로를 조건 경로라고도 합니다."

**상세 설명**: Dialogflow CX는 구글 클라우드의 엔터프라이즈급 대화형 에이전트 빌더로,
**흐름(Flow)** 안에 여러 **페이지(Page)** 를 상태 머신처럼 정의하고, 각 페이지에서 사용자
발화가 **인텐트**(의도, 예: "주문하기")나 **조건**(세션 상태값)과 일치하면 **라우트(Route)**
를 통해 다른 페이지로 전환하는 구조다. 이는 우리 IntelliDecision의 "유형 A~I 판정 → 유형별
처리 경로"와 개념적으로 동일하다 — 차이는 Dialogflow CX가 **명시적 상태 머신**으로 라우팅
규칙을 그래픽 콘솔에서 시각적으로 설계하게 해준다는 점이다. 아래는 공식 문서가 제공한 실제
아키텍처 다이어그램이다.

![Dialogflow CX 다중 흐름 다이어그램](https://docs.cloud.google.com/static/dialogflow/cx/docs/images/cx-flow.svg)

![Dialogflow CX 페이지·라우트 전환 다이어그램](https://docs.cloud.google.com/static/dialogflow/cx/docs/images/cx-page.svg)

**실제 사용 방식**: Dialogflow CX는 구글 클라우드 고객사(항공사·통신사·금융사 등)의 콜센터
IVR·챗봇에 실제로 배포되는 상용 제품이며, 최근에는 **생성형 플레이북**(자연어 지시문 기반 LLM
에이전트)과 결정론적 흐름을 하나의 콘솔에서 함께 쓸 수 있도록 통합되었다(공식 문서에 "생성형과
결정론적 비교" 페이지가 별도로 존재할 정도로 두 방식의 병존이 업계 표준 관행임을 보여준다).

**적용 방향**: 우리 `knowledge_graph.py`의 n-hop 일반화(§5.1, Story 1.28)를 설계할 때,
Dialogflow CX의 "페이지=상태, 라우트=상태 전이 규칙, 인텐트/조건=전이 트리거"라는 명시적
상태 머신 모델을 참고할 수 있다 — 특히 "인텐트 경로"와 "조건 경로"를 구분하는 방식은 향후
우리 `intellidecision_policy.py`에 "발화 의도 기반 분기"와 "세션 상태 기반 분기"(예: 이미
확인 발화 중인지)를 구조적으로 분리하는 데 참고할 수 있다.

### 3.7 Amazon **Lex V2** — 인텐트·슬롯·폴백 인텐트 기반 대화형 봇

**출처**: https://docs.aws.amazon.com/lexv2/latest/dg/how-it-works.html (AWS 공식 문서)

**원문**:
> "An intent represents an action that the user wants to perform... Amazon Lex always includes
> a fallback intent for each bot. The fallback intent is used whenever Amazon Lex can't deduce
> the user's intent."

**번역**: "인텐트는 사용자가 수행하려는 행동을 나타낸다... Amazon Lex는 모든 봇에 항상 폴백
인텐트를 포함한다. 폴백 인텐트는 Amazon Lex가 사용자의 의도를 추론할 수 없을 때 사용된다."

**원문(고급 기능)**:
> "Assisted NLU – Uses Large Language Models (LLMs) to improve intent classification and slot
> resolution... Context Switching – Advanced bots can handle topic changes within a conversation.
> For example, a user might start asking about account information, then switch to placing an
> order, and return to the original topic."

**번역**: "Assisted NLU(보조 자연어이해) — 대규모 언어 모델(LLM)을 사용해 인텐트 분류와
슬롯(파라미터) 추출 정확도를 높인다... 맥락 전환 — 고급 봇은 대화 중 주제 전환을 처리할 수
있다. 예를 들어 사용자가 계좌 정보를 묻다가 주문으로 전환한 뒤 다시 원래 주제로 돌아갈 수
있다."

**상세 설명**: Amazon Lex V2는 아마존이 자사 Alexa에도 쓰이는 NLU 엔진을 상용화한 것으로,
"인텐트(의도) + 슬롯(파라미터) + 폴백 인텐트(분류 실패 시 기본 경로)" 3요소가 핵심이다.
특히 **폴백 인텐트**는 우리 유형 F(모호성 해소)와 정확히 대응하는 개념 — "분류가 안 되면
무조건 되묻는다"는 설계가 아마존 규모의 상용 제품에도 이미 표준 컴포넌트로 내장되어 있음을
보여준다. 최근 추가된 **Assisted NLU**는 순수 규칙 기반 매칭에 LLM을 보조로 결합한 것으로,
우리의 "LLM 우선 + 발화 패턴은 참고 신호"(FR12) 원칙과 반대 방향(규칙 우선 + LLM 보조)이지만
같은 문제(정확도와 설명 가능성의 균형)를 다른 축에서 풀고 있다.

**실제 사용 방식**: Amazon Lex V2는 AWS 콘솔의 사전 구축 템플릿(고객 지원 FAQ, 예약 봇, 주문
상태 조회 등)으로 약 50분 내 작동하는 챗봇을 만들 수 있도록 문서화되어 있으며, Slack·웹·모바일
앱 등에 실제 배포 가능한 완제품 형태로 제공된다.

**적용 방향**: "폴백 인텐트"는 우리 유형 F가 이미 커버하고 있음을 재확인시켜주는 근거다.
"슬롯(파라미터) 개념"은 우리 자동설정 Tool의 "필수/옵션 필드"(FR6)와 대응하며, 향후 문서
업로드(Story 1.26)에서 OpenAPI 파라미터를 다룰 때도 유사한 슬롯 채우기(slot filling) 패턴을
참고할 수 있다.

### 3.8 Zendesk **AI 에이전트**(Forethought 기반) — 에이전틱 AI 실사용 지표

**출처**: https://www.zendesk.kr/service/ai/ai-agents/ (Zendesk 한국어 공식 페이지, 2026년
8월 기준 최신)

**원문(한국어 원문, 실사용 고객 인용)**:
> "저희는 현재 81개의 살롱을 운영 중이고, 올해 160개 지점으로 확장 예정입니다. 리셉션
> 스태프 충원 없이 진행할 계획입니다." — Austin Towns, Hello Sugar 최고기술책임자
> (자동화율 66%, 월 14,000달러 절감)
>
> "Zendesk의 AI 상담사는 사용자의 의도를 자동으로 파악하고 자주 묻는 이메일 질문에
> 답변합니다." — Davide Donini, TeamSystem IT 연동 부문장 (자동화율 80%, 반복 이메일 99%
> 감소)
>
> "AI 상담사가 Zendesk AI와 당사의 백엔드 시스템을 연동하여, 사용자가 구독을 전적으로 직접
> 관리할 수 있도록 해줍니다." — Chris Boyd, Babbel 툴링 및 자동화 수석 관리자(문제 해결률
> 50%+, 인바운드 메시지량 45% 감소)

**상세 설명**: Zendesk는 2007년 창립한 고객 서비스 플랫폼 회사로, Forethought를 인수해 만든
"에이전틱 AI" 상담사를 자사 제품에 통합했다. Zendesk가 스스로 설명하는 핵심 차별점은
"미리 정의된 스크립트를 따르는 작업 기반 봇과 달리, 에이전틱 AI는 문제 해결을 위해 AI
상담사가 전반적인 추론, 결정, 대화 진행에 따른 조정을 할 수 있게 만든다"는 것이다 — 이는
Anthropic의 "Workflow(고정 경로) vs Agent(자율 판단)" 구분(§3.4)에서 후자에 해당하며,
우리 IntelliDecision이 "유형 분류는 고정 스키마(A~I)로 하되, 각 유형 내 실제 응대는 LLM이
자율적으로 판단"하는 **하이브리드 방식**을 취하고 있는 것과 비교할 만한 지점이다.

**실제 사용 방식**: 공식 페이지에 4개 실고객사의 정량 지표가 공개되어 있다 — Hello Sugar
(뷰티 살롱 체인, 자동화율 66%·월 14,000달러 절감), TeamSystem(자동화율 80%·반복 이메일 99%
감소), Babbel(어학 서비스, 문제 해결률 50%+·인바운드 메시지량 45% 감소), Action Property
Management(부동산 관리, 자동 문제 해결률 80%·최초 응답 대기시간 81% 단축). 또한 "통합형
지식에 기반으로 답변을 제공"(헬프센터·Google Drive·PDF 등 외부 소스 연동), "내장된 QA
기능으로 완벽한 투명성 확보"(모든 상호작용을 자동 평가해 92% 품질 점수 예시 제공)를 제품
화면 스크린샷과 함께 공개하고 있다 — 이는 우리 목표 ⑤⑥⑦(투명성)의 실제 상용 구현 사례다.

**적용 방향**: Zendesk가 강조하는 "내장된 QA로 완벽한 투명성"은 §5.2 응답 시뮬레이터와 §2.1
지식베이스 인벤토리(Story 1.23)를 결합한 우리의 목표와 정확히 같은 방향이다. "통합형 지식
(헬프센터+Drive+PDF)"은 Story 1.26이 목표하는 다중 소스 어댑터(마크다운+PDF+OpenAPI)와
동일한 패턴이며, 실제로 PDF 연동이 상용 서비스에서 이미 표준 기능임을 재확인해준다.

### 3.9 LangChain `DocumentLoader` / LlamaIndex `IngestionPipeline` / Haystack `Pipeline`
2026-07-30 선행 리서치에서 이미 확인(부록 A 참고) — 소스 어댑터 플러그인화의 표준 패턴이며,
`SourceAdapter` 프로토콜(Story 1.25)이 이미 이 방향의 1보를 뗀 상태다. 이번 설계는 이 프로토콜을
실제 다중 구현체로 확장하는 것이 핵심 과제임을 재확인한다.

### 3.10 IntelliDecision 유형(A~I) 자체의 실사용 검증 — Amazon Alexa 표준 내장 인텐트와의 1:1 대조

> **왜 이 대조가 필요한가**: 사용자가 "우리 유형 분류가 다른 시스템에서도 쓰이는 검증된 개념인지"를
> 질문했다. 가장 직접적인 증거는 **Amazon Alexa의 "표준 내장 인텐트"(Standard Built-in
> Intents)** 다 — 이는 수억 대의 Echo 기기에 실제 배포된 음성 어시스턴트 플랫폼이 "어떤 발화
> 유형을 표준으로 분류해야 하는가"를 공식 문서로 명세한 것이라, 우리 유형 A~I가 임의로 만든
> 분류가 아니라 **업계 표준 패턴과 대응**됨을 검증할 수 있다.

**출처**: https://developer.amazon.com/en-US/docs/alexa/custom-skills/standard-built-in-intents.html
(Amazon 공식 개발자 문서, 최종 갱신 2025-10-07)

**원문(발췌)**:
> "AMAZON.HelpIntent — Provides help about how to use the skill... AMAZON.FallbackIntent —
> Provides a fallback for user utterances that do not match any of your skill's intents...
> AMAZON.RepeatIntent — Lets the user request to repeat the last action... AMAZON.CancelIntent —
> Lets the user cancel a transaction or task (but remain in the skill)."

**번역**: "AMAZON.HelpIntent — 스킬 사용법에 대한 도움말을 제공한다... AMAZON.FallbackIntent —
사용자 발화가 스킬의 어떤 인텐트와도 일치하지 않을 때의 폴백을 제공한다... AMAZON.RepeatIntent —
사용자가 마지막 동작을 반복 요청할 수 있게 한다... AMAZON.CancelIntent — 사용자가 거래나 작업을
취소하되 스킬 안에는 남아있게 한다(스킬을 완전히 종료하지 않고)."

**대조표 — 우리 유형 A~I ↔ Alexa 표준 내장 인텐트**:

| 우리 유형           | 개념              | 대응하는 Alexa 표준 내장 인텐트      | 공식 설명(번역)                                                                         |
| ------------------- | ----------------- | ------------------------------------ | --------------------------------------------------------------------------------------- |
| C(포괄적 도움 요청) | "뭘 할 수 있어?"  | `AMAZON.HelpIntent`                  | "스킬 사용법에 대한 도움말 제공"                                                        |
| F(모호성 해소)      | 분류 불가·되묻기  | `AMAZON.FallbackIntent`              | "어떤 인텐트와도 일치하지 않는 발화에 대한 폴백"                                        |
| I(반복 요청)        | "다시 말해줘"     | `AMAZON.RepeatIntent`                | "마지막 동작을 반복 요청"                                                               |
| D(정정)/E(실행취소) | 진행 중 취소·정정 | `AMAZON.CancelIntent`                | "거래·작업을 취소하되 스킬 안에는 남아있음"(완전 종료와 구분되는 "취소 후 재시도" 개념) |
| (확인 발화 응답)    | Yes/No 확인       | `AMAZON.YesIntent`/`AMAZON.NoIntent` | "확인 질문에 대한 긍정/부정 응답"                                                       |

**상세 설명**: 특히 주목할 점은 Alexa 공식 문서가 `AMAZON.CancelIntent`를 "거래를 취소하되 스킬
안에는 남아있는 것"과 "스킬을 완전히 종료하는 것" 두 가지로 명시적으로 구분한다는 것 — 이는
우리 유형 D(정정, 세션 유지하며 다른 값으로 재시도)와 유형 E(실행취소, 이미 반영된 값을
되돌림)를 나누는 설계와 **개념적으로 동일한 분기**다. 또한 `AMAZON.FallbackIntent`는 "통계
모델(statistical model)로 판정되며, 사용자 발화가 자체 인텐트에 확신을 갖고 매칭되지 않을
때"라고 설명하는데, 이는 우리 FR12의 "LLM 우선 판단, 키워드/패턴은 참고 신호"라는 원칙과 정확히
같은 접근이다.

**실제 사용 방식**: 이 표준 인텐트들은 Alexa Skills Kit으로 만드는 **모든** 상용 스킬이 공통으로
구현해야 하는 필수/권장 구성요소이며, Amazon은 스킬 인증(certification) 요구사항에 `AMAZON.
StopIntent`/`CancelIntent` 처리를 **필수 항목**으로 명시하고 있다(공식 문서 "cert-stop-and-
cancel" 섹션). 즉 "도움 요청/폴백/반복/취소" 유형 분류는 하나의 특정 서비스가 실험적으로
도입한 것이 아니라, **음성 어시스턴트 플랫폼 표준 자체에 내장된 필수 요구사항**이다.

**적용 방향**: 이 대조는 우리 IntelliDecision 유형 C/D/E/F/I가 "임의로 만든 분류"가 아니라
**업계에서 이미 오랫동안 검증된 대화 제어 패턴을 재사용한 것**임을 뒷받침하는 1차 근거다.
향후 매뉴얼/설명자료에서 "왜 이렇게 유형을 나눴는가"를 설명할 때 이 대조표를 그대로 인용할 수
있다. 다만 유형 G(일괄 처리)와 H(범위 외 설명)는 Alexa 표준 인텐트에 직접 대응이 없다 —
이는 우리 도메인(자동설정 다중 필드 변경, 정책 기반 제한 사유 설명)이 음성 비서 범용
플랫폼보다 더 구체적인 업무 도메인(테넌트 설정 관리)에 특화되어 있기 때문으로 해석하며,
향후 유사 검증이 필요하면 엔터프라이즈 워크플로 자동화 플랫폼(예: ServiceNow Virtual Agent)
쪽 사례를 추가 조사할 후보로 남긴다.

### 3.11 Hop 기반 연계 매칭의 실사용 검증 — Microsoft Research **GraphRAG**의 Local Search

> **왜 이 레퍼런스가 필요한가**: 사용자가 "어떤 유형의 질문일 때 hop으로 연결된 정보를 매칭해
> 응대하는지"에 대한 연구 근거를 요청했다. Microsoft Research의 GraphRAG는 정확히 이
> "질문 유형에 따라 그래프 순회 전략을 다르게 선택"하는 설계를 공개 연구로 발표했다.

**출처**: https://microsoft.github.io/graphrag/ (Microsoft Research 공식 프로젝트 문서),
논문: https://arxiv.org/pdf/2404.16130

**원문**:
> "Baseline RAG struggles to connect the dots. This happens when answering a question requires
> traversing disparate pieces of information through their shared attributes in order to provide
> new synthesized insights... Local Search for reasoning about specific entities by fanning-out to
> their neighbors and associated concepts. Global Search for reasoning about holistic questions
> about the corpus by leveraging the community summaries."

**번역**: "기본(Baseline) RAG는 '점을 잇는 것'을 잘 못한다. 이는 질문에 답하기 위해 서로
흩어진 정보 조각들을 공유 속성을 통해 가로질러야 새로운 통합적 통찰을 제공할 수 있는 경우에
발생한다... Local Search는 특정 엔터티에 대해 추론할 때 **그 이웃 노드와 연관 개념으로
팬아웃(fanning-out, 확산)** 하는 방식이다. Global Search는 커뮤니티 요약을 활용해 말뭉치
전체에 대한 총체적 질문을 추론하는 방식이다."

**상세 설명**: GraphRAG는 질문 유형에 따라 **서로 다른 그래프 순회 전략**을 명시적으로
구분한다 — ① Local Search(특정 엔터티 중심 질문 → 그 엔터티의 인접 노드로 hop 확장), ②
Global Search(말뭉치 전체에 대한 총체적 질문 → 커뮤니티 요약 활용, hop 없이 상위 요약 계층
조회), ③ DRIFT Search(Local Search + 커뮤니티 맥락 결합), ④ Basic Search(hop 불필요, 단순
벡터 검색). 이는 사용자가 요청한 "어떤 유형의 질문일 때 어떤 hop 전략을 매칭할지"라는 질문에
대한 **가장 직접적인 학술·산업 근거**다 — GraphRAG는 이를 "질문 유형별 검색 모드 선택"으로
공식화했다.

**실제 사용 방식**: GraphRAG는 Microsoft Research가 오픈소스로 공개(GitHub 3.7만 스타)했으며,
Microsoft 자체 제품(Copilot 계열)뿐 아니라 다수의 엔터프라이즈 RAG 도입 사례에서 참조
아키텍처로 채택되고 있다. 우리 저장소의 과거 리서치(`SELF_SERVICE_SCREEN_GUIDED_GRAPHRAG_
RESEARCH.md`, 2026-07-16/27)가 "Full GraphRAG(엔터티 자동추출+Leiden 클러스터링)는 우리
규모엔 과설계"라고 결론지은 것은 **색인 파이프라인의 복잡도**(엔터티 자동 추출, 커뮤니티
클러스터링)에 대한 판단이었지, "질문 유형별로 다른 hop 전략을 매칭한다"는 **개념 자체**를
기각한 것이 아니다.

**적용 방향**: 우리는 GraphRAG의 4가지 검색 모드 구분 개념을 **경량화해서 재사용**한다 —
Full GraphRAG의 자동 커뮤니티 클러스터링 없이도, `intellidecision_policy.py`의
`rag_strategy_hint`(Story 1.24에 이미 존재)를 "vector"(Basic Search에 대응)/"hybrid"(BM25
결합)/향후 "graph_local"(Local Search에 대응, `knowledge_graph.traverse()` 사용)로 확장하면
동일한 개념을 우리 규모에 맞게 구현할 수 있다. 이는 Story 1.28(n-hop 일반화)의 구체적 설계
근거로 직접 채택한다 — "유형 A(탐색성)는 특정 도메인 질문이 많으므로 Local Search(2~3-hop)를,
유형 C(포괄적 도움)는 여러 카테고리를 총괄해야 하므로 Global Search류(카탈로그 전체 요약)를
매칭"하는 식으로 유형별 hop 전략을 `rag_strategy_hint`에 구체적으로 명시할 수 있다.

### 3.12 대화로 사용자 목표를 이끌어내는 방식의 연구 근거 — Mixed-Initiative Dialogue와 Slot Filling

> **왜 이 레퍼런스가 필요한가**: 사용자가 "IntelliDecision이 대화를 통해 똑똑하게 사용자가
> 원하는 것을 이끌어내 수행한다"는 개념의 학술·산업 근거를 요청했다. 이는 대화 시스템 연구
> 분야에서 "혼합 주도권(Mixed-Initiative) 대화"와 "슬롯 채우기(Slot Filling)"로 이미 수십 년간
> 연구되어 온 확립된 개념이다.

**출처 ①(학술)**: Wikipedia "Dialogue system" 문서가 인용하는 Jurafsky & Martin,
*Speech and Language Processing*(Pearson, 2009/2025 3판 초안), Chapter 24("Dialogue Systems
and Chatbots") — 대화 시스템 교과서의 표준 레퍼런스

**원문(주도권 유형 분류, Wikipedia 발췌)**:
> "by initiative: system initiative, user initiative, mixed initiative"

**번역**: "주도권 방식에 따른 분류: 시스템 주도, 사용자 주도, **혼합 주도(mixed initiative)**"

**상세 설명**: 대화 시스템 연구는 오래전부터 "누가 대화의 주도권을 쥐는가"를 3가지로 분류해왔다
— 시스템이 정해진 순서로만 질문하는 시스템 주도(예: "이름을 말씀하세요", "전화번호를
말씀하세요" 순서 고정), 사용자가 원하는 대로 말하고 시스템이 그때그때 대응하는 사용자 주도,
그리고 **두 방식을 상황에 따라 전환하는 혼합 주도**(사용자가 여러 정보를 한 번에 말하면
시스템이 그만큼 받아들이고, 부족한 부분만 골라서 되묻는 방식)다. 우리 IntelliDecision이
"단일 발화에서 여러 설정 변경을 한 번에 파악"(유형 G, 일괄 처리)하면서도 "모호하면 되묻는다"
(유형 F)는 것은 정확히 혼합 주도 대화의 정의와 일치한다.

**출처 ②(산업, 실제 오픈소스 구현체)**: https://legacy-docs-oss.rasa.com/docs/rasa/forms
(Rasa Open Source 공식 문서 — 수만 개 기업이 실사용 중인 오픈소스 대화형 AI 프레임워크)

**원문**:
> "One of the most common conversation patterns is to collect a few pieces of information from a
> user in order to do something (book a restaurant, call an API, search a database, etc.). This
> is also called slot filling... Users will not always respond with the information you ask of
> them. Typically, users will ask questions, make chitchat, change their mind, or otherwise stray
> from the happy path."

**번역**: "가장 흔한 대화 패턴 중 하나는 무언가를 하기 위해(레스토랑 예약, API 호출, 데이터베이스
검색 등) 사용자로부터 몇 가지 정보를 수집하는 것이다. 이를 **슬롯 채우기(slot filling)**라고도
부른다... 사용자는 항상 요청받은 정보로만 응답하지 않는다. 일반적으로 사용자는 질문을 하거나,
잡담을 하거나, 마음을 바꾸거나, 그 외에 정해진 경로(happy path)를 벗어난다."

**상세 설명**: Rasa의 "Form"(슬롯 채우기 메커니즘)은 필수 정보(슬롯)를 순서대로 채워나가되,
사용자가 도중에 잡담(chitchat)하거나 마음을 바꾸면(change their mind) 이를 "Unhappy Path"로
명시적으로 정의해 별도 처리 규칙(`action_deactivate_loop`로 폼 중단, 또는 되돌아가서 계속
진행)을 두도록 문서화하고 있다. 이는 우리 유형 D(정정)·E(실행취소)·F(모호성 해소)가 다루는
"대화가 예상 경로를 벗어났을 때의 복구"와 **정확히 동일한 문제의식**이며, Rasa는 이를 실제
프로덕션 봇 수만 개에서 검증된 패턴으로 문서화하고 있다.

**실제 사용 방식**: Rasa Open Source는 GitHub 스타 1.9만+ 규모의 오픈소스 프로젝트로, Rasa
Pro(상용 버전)는 다수의 엔터프라이즈 콜센터·챗봇에 실제 배포되어 있다. "Form"(슬롯 채우기)과
"Unhappy Path"(대화 이탈 처리) 개념은 Rasa 문서에서 "가장 흔한 대화 패턴"이라고 명시할 만큼
업계 표준 관행이다.

**적용 방향**: 이 연구 근거는 IntelliDecision의 핵심 설계 철학 — "정해진 스크립트가 아니라
사용자가 무엇을 원하는지 대화로 이끌어내되, 예상 경로를 벗어나면 복구한다" — 이 학술적으로는
"혼합 주도 대화"(Jurafsky & Martin), 산업적으로는 "슬롯 채우기 + Unhappy Path"(Rasa)라는
확립된 개념의 우리 도메인(셀프서비스 설정 관리) 적용임을 뒷받침한다. 향후 매뉴얼/설명자료에서
"IntelliDecision이 왜 이렇게 설계되었는가"를 설명할 때, "이미 검증된 혼합 주도 대화·슬롯 채우기
이론을 채용했다"는 근거로 이 절을 인용할 수 있다.

### 3.13 레퍼런스 → 시스템 적용 비교표

| 실사용 근거                                               | 우리 시스템 현재 상태                                             | 적용 방향                                                                          |
| --------------------------------------------------------- | ----------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| Fin §10(노코드 지식 구성, 12,000+ 고객)                   | 매뉴얼 .md 파일 직접 편집만 가능                                  | Story 1.26: 지식 문서 CRUD API + 업로드 프론트 화면                                |
| Fin §14(라이브 전 테스트 스위트)                          | 실제 대화를 태워야만 결과 확인 가능                               | Story 1.27: 응답 시뮬레이터(실제 LLM 호출로 최종 응답까지 생성하는 dry-run 테스트) |
| Fin §13(다단계 Procedures)                                | Q&A 페어 단위 지식만 존재                                         | Story 1.28: 그래프에 `procedure_step` 노드 타입 예약                               |
| Glean(지식 그래프+벡터DB 하이브리드, Graph-scoped search) | 그래프가 하드코딩된 3단 체인                                      | Story 1.28: 노드/엣지 등록 테이블화, hop 수 가변화                                 |
| Anthropic Contextual Retrieval(청크 문맥 보강)            | 수작업 도메인 태그만 존재                                         | Story 1.29: 비용/품질 실측 스파이크 후 채택 여부 결정                              |
| **Anthropic Routing 워크플로(고객 문의 유형 분류)**       | IntelliDecision 유형 A~I가 이미 이 패턴의 구현체(Story 1.18/1.19) | 투명성 원칙(②)을 §5.2 응답 시뮬레이터로 완전히 실현                                |
| **Semantic Router(5G 통신망 실사례·콜센터 10ms 사례)**    | 전량 LLM 호출 기반 분류, 임베딩 사전 필터링 없음                  | 재도입 검토 시 Story 2.6과 동일한 베이스라인·A/B 롤백 절차 필수(§6 Non-Goal 참고)  |
| **Dialogflow CX(흐름/페이지/라우트 상태 머신)**           | IntelliDecision이 유사 개념을 프롬프트 규칙으로만 구현            | 인텐트 경로 vs 조건 경로 구분을 `intellidecision_policy.py` 설계에 참고            |
| **Amazon Lex V2(폴백 인텐트, Assisted NLU)**              | 유형 F(모호성 해소)가 폴백 인텐트와 동일 개념을 이미 구현         | 슬롯(파라미터) 채우기 패턴을 Story 1.26 OpenAPI 어댑터 설계에 참고                 |
| **Zendesk AI 에이전트(실고객 4건, 정량 지표 공개)**       | 지식베이스 인벤토리(Story 1.23)만 있고 QA 자동 평가는 없음        | 통합형 지식(헬프센터+Drive+PDF)·QA 자동 평가는 Story 1.26/1.27의 실사용 근거       |
| **Alexa 표준 내장 인텐트(유형 C/D/E/F/I 1:1 대조)**       | 유형 A~I가 이미 이 표준 패턴과 대응(§3.10 대조표)                 | 매뉴얼/설명자료에 "업계 표준 패턴 채용" 근거로 §3.10 대조표 직접 인용              |
| **GraphRAG Local/Global Search(질문 유형별 hop 전략)**    | `rag_strategy_hint`가 "vector"/"hybrid"뿐, "graph_local" 없음     | Story 1.28: `rag_strategy_hint`에 "graph_local"(Local Search 대응) 추가            |
| **혼합 주도 대화·Rasa Forms(슬롯 채우기+Unhappy Path)**   | 유형 D/E/F/G가 이미 Unhappy Path 개념을 프롬프트로 구현           | 매뉴얼/설명자료에 "혼합 주도 대화 이론 채용" 근거로 §3.12 인용                     |

---

## 4. 목표 ①②③ — 도메인 비종속 업로드 · CRUD 설계

### 4.1 업로드 지원 데이터 유형 (사용자 결정: 1단계부터 PDF/OpenAPI 포함)

| 소스 유형          | 어댑터(신규)                       | 파싱 방식                                                                              | 필수 메타데이터                                                 |
| ------------------ | ---------------------------------- | -------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| 마크다운 Q&A(기존) | `MarkdownManualAdapter`(기존 유지) | 섹션+`{domain: xxx}` 태그                                                              | title, domain_tags, owner                                       |
| 일반 텍스트/PDF    | `PdfDocumentAdapter`(신규)         | PDF 텍스트 추출 후 문단 단위 청킹                                                      | title, domain_tags, owner, source_type=`pdf`, page_range        |
| API 문서(OpenAPI)  | `OpenApiSpecAdapter`(신규)         | OpenAPI JSON/YAML의 각 endpoint(path+method+summary+parameters)를 Q&A 유사 페어로 변환 | title, domain_tags, owner, source_type=`openapi`, endpoint_path |
| (예약) CSV FAQ     | 미착수, 수요 확인 후               | —                                                                                      | —                                                               |

모든 업로드 문서는 공통 메타데이터(`document_id`, `owner`, `domain_tags: List[str]`, `source_type`,
`version`, `uploaded_at`, `uploaded_by`)를 갖는다 — 기존 `knowledge_service.add_knowledge()`의
`owner`/`category`/`doc_type` 파라미터를 그대로 재사용하고 확장한다(신규 벡터 스토어 도입 없음).

### 4.2 CRUD API 초안

```
POST   /api/knowledge-base/documents            # 업로드(파일 또는 텍스트 본문 + 메타데이터)
GET    /api/knowledge-base/documents?owner=&domain_tag=&source_type=   # 목록 조회
GET    /api/knowledge-base/documents/{document_id}                     # 단건 조회(청크 목록 포함)
PUT    /api/knowledge-base/documents/{document_id}                     # 메타데이터/본문 수정 → 재색인
DELETE /api/knowledge-base/documents/{document_id}                     # 삭제(색인에서도 제거)
```

기존 `knowledge_service.list_knowledge()`/`get_all_knowledge()`(조회)와
`knowledge_base_inventory.summarize_inventory()`(집계)를 그대로 재사용하고, 신규로 필요한 것은
**문서 단위 lifecycle(생성/수정/삭제)** 뿐이다 — 벡터 스토어(ChromaDB) 자체를 교체하지 않는다.

### 4.3 프론트엔드 — "지식 업로드" 신규 탭

기존 `settings/ai-assistant/docs` 페이지의 5개 탭에 6번째 탭을 추가한다: 파일 업로드(드래그 앤
드롭) + 메타데이터 폼(도메인 태그, source_type 자동 감지) + 업로드된 문서 목록(수정/삭제 버튼) —
기존 탭들의 카드/표 UI 패턴(Story 1.18/1.23)을 재사용해 신규 npm 의존성 없이 구현 가능.

### 4.4 도메인 비종속화(목표 ①)

`domain_tags`를 `settings_catalog.py`의 고정 7개 도메인에서 분리해 **자유 텍스트 태그 배열**로
전환한다 — 기존 self_service 도메인은 `domain_tags=["persona"]`처럼 하위 호환되게 매핑하되, 신규
업로드 문서는 임의의 태그(`["api-docs", "billing"]` 등)를 가질 수 있다. 이는 향후 셀프서비스 외
다른 기능 영역(예약, 통화 이력 등)의 지식도 동일 플랫폼에 얹을 수 있게 하는 전제 조건이다.

---

## 5. 목표 ④⑤⑥ — 관계형 구조 확장과 투명성

### 5.1 지식 그래프 n-hop 일반화

`knowledge_graph.py`를 다음과 같이 일반화한다(방향, 상세 스키마는 Story 1.28 설계 스파이크에서
확정):

- **노드 타입 레지스트리**: 현재 4종(`manual_qa`/`catalog_domain`/`frontend_screen`/`intent_type`)에
  신규 타입을 **미리 예약**한다 — `document`(§4의 업로드 문서), `api_endpoint`(OpenAPI 엔드포인트),
  `procedure_step`(다단계 절차 단위, Fin Procedures 사례 참고).
- **엣지 타입 레지스트리**: `relates_to`/`rendered_by`/`writable` 외에 `depends_on`(절차 단계 간
  순서), `documents`(API 문서 ↔ 실제 Tool/엔드포인트 매핑)를 예약.
- **`traverse(start_node, *, max_hops)`**: 고정 3단 체인 함수 호출이 아니라, 노드/엣지 등록
  테이블을 실제로 순회하는 그래프 탐색 함수로 재작성 — `max_hops`를 3~4단계로 늘려도 코드 수정
  없이 동작해야 한다(현재는 `max_hops` 파라미터가 사실상 무시됨).

### 5.2 응답 시뮬레이터 (사용자 결정: 실제 LLM 응답까지 생성)

**신규 기능**: 운영자가 지식베이스 화면에서 예시 질문을 입력하면, 실제 통화/채팅 세션에는 영향을
주지 않는 **격리된 테스트 엔드포인트**로 다음을 함께 반환한다.

1. 매칭된 지식 문서/청크(문서 ID, 관련 도메인 태그, 유사도 점수)
2. 판정된 IntelliDecision 유형(A~I)과 판단 근거(Story 1.20~1.22의 판단 근거 캡처 재사용)
3. **실제 LLM 호출로 생성된 최종 응답 텍스트**(Fin Testing suite와 동등 수준)

기존 `POST /api/self-service/test/converse`(Story 1.15~1.19에서 QA용으로 이미 사용 중인
격리 엔드포인트)를 확장하는 방향을 우선 검토한다 — 신규 엔드포인트를 만들더라도 동일한 실행
경로(LangGraph 그래프, 실제 owner 데이터)를 재사용해 "시뮬레이터에서 본 것과 실제 응답이 다르다"는
불일치를 원천 차단해야 한다. 실 LLM 호출이므로 지연·비용이 발생함을 화면에 명시한다(로딩 상태
UI 필요).

### 5.3 IntelliDecision 유형별 연결 투명성(목표 ⑦)

기존 Story 1.24의 `rag_enabled`/`rag_source_scope`/`rag_strategy_hint`와 §5.2 시뮬레이터를
연결한다: 정책 표/그래프 탭(기존)에서 특정 유형을 클릭하면 "이 유형에 매칭되는 예시 질문으로
시뮬레이터를 즉시 실행"하는 바로가기를 제공 — 유형별 매칭 구조를 표로 읽는 것에서 나아가 실제
동작으로 확인하는 것까지 한 화면에서 완결시킨다.

---

## 6. Non-Goal (범위 밖, 재확인)

과거 리서치(2026-07-16/27/30)와 일관되게 아래는 이번에도 범위 밖으로 유지한다.

- Full GraphRAG(엔터티 자동 추출 + Leiden 클러스터링 등) — 노드/엣지를 여전히 명시적 스키마로
  등록하는 방식(§5.1)을 채택하며, 자동 추출 파이프라인은 도입하지 않는다.
- ChromaDB 이외 벡터DB로의 마이그레이션 — 소스 어댑터 계층(§4.1)만 벤더 비종속으로 설계하고,
  저장소 자체 교체는 별도 트랙.
- 독립 벡터DB 네임스페이스 물리 격리 — 기존 `owner` 필터 기반 논리적 격리를 유지.- **임베딩 기반 사전 라우팅(keyword/embedding pre-routing) 재도입은 근거 없이 바로 하지 않는다** — 저장소는 2026-07-20/21 Story 2.6에서 동일한 방향(`intent_tier.py`)을 베이스라인 확보→제거→재검증 절차로 이미 검증해 제거한 이력이 있다(§3.5 Semantic Router 적용 방향 참고). 재도입을 검토하려면 동일한 절차를 다시 밟아야 한다.
---

## 7. 로드맵 (Epic/Story)

| Story    | 내용                                                                                                                    | 우선순위 |
| -------- | ----------------------------------------------------------------------------------------------------------------------- | -------- |
| **1.26** | 지식 문서 CRUD API + 업로드 프론트 탭. `SourceAdapter` 신규 구현체 2종(`PdfDocumentAdapter`, `OpenApiSpecAdapter`) 포함 | 1        |
| **1.27** | 응답 시뮬레이터 — 실제 LLM 호출 기반 dry-run 테스트 엔드포인트 + 프론트 화면                                            | 2        |
| **1.28** | `knowledge_graph.py` n-hop 일반화(노드/엣지 등록 테이블화, 신규 노드 타입 예약분 실제 등록)                             | 3        |
| **1.29** | Contextual Retrieval 도입 스파이크(비용/품질 실측 후 채택 여부 결정)                                                    | 4        |

우선순위는 사용자 요구사항의 실질 가치(코드 배포 없는 지식 구성 → 신뢰 가능한 사전 확인 → 구조
확장 → 품질 고도화) 순으로 배치했다. 각 Story는 독립적으로 완료 가능하도록 설계한다.

---

## 부록 A: 2026-07-30 리서치 요약 (본 문서로 대체됨)

2026-07-30 리서치는 Modular RAG 3단계(Naive→Advanced→Modular), Anthropic Contextual Retrieval
실증치, LangChain/LlamaIndex/Haystack 소스 어댑터 패턴, RAGAS/Langfuse류 observability 관행을
다뤘으며, 그 결과로 Story 1.23(지식베이스 인벤토리 API)·1.24(RAG 매칭 정책 메타데이터)·1.25
(SourceAdapter 프로토콜 골격)가 구현 완료되었다. 이번 문서는 그 성과 위에서 범위를 "셀프서비스
매뉴얼"에서 "도메인 비종속 지식베이스 플랫폼"으로 확장한 것이며, 세부 시장 리서치 내용(Modular
RAG 3단계 표, BM25 원리 등)은 중복을 피하기 위해 이 문서에 재수록하지 않는다 — 필요 시 Git 이력의
2026-07-30 버전을 참고할 것.

---

## 부록 B: 관련 문서

- [self-service-ai-assistant-prd.md](../product/self-service-ai-assistant-prd.md) — FR32
- [self-service-ai-assistant-architecture.md](../architecture/self-service-ai-assistant-architecture.md) — §RAG·IntelliDecision 고도화
- [docs/stories/1.26.*](../stories/) ~ 1.29(로드맵 §7)

---

*최종 업데이트: 2026-08-04*
