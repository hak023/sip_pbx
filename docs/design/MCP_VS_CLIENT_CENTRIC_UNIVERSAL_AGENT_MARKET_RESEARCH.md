# MCP vs. "Client-Centric 범용 API 에이전트" — 시장·연구 조사 리포트

**작성일**: 2026-08-05 (v1.1 — GitHub 오픈소스 생태계 실증 §4 보강)
**작성자**: Copilot (BMAD PM 역할, 리서치 전용 — 코드 변경 없음)
**관련 문서**: [SELF_SERVICE_RAG_INTELLIDECISION_ADVANCEMENT_RESEARCH.md](SELF_SERVICE_RAG_INTELLIDECISION_ADVANCEMENT_RESEARCH.md)(§3, 유사 리서치 형식 재사용), [self-service-ai-assistant-prd.md](../product/self-service-ai-assistant-prd.md) FR32/FR33(Story 1.26~1.33 — 본 리포트가 다루는 아이디어의 실제 구현 선례)

---

## 0. 질문 재정의

사용자가 제시한 아이디어를 정확히 정리하면 다음과 같다.

1. **MCP(Model Context Protocol)**: 서버(도구 제공자) 쪽을 표준화한다 — "서버를 잘 만들어두면"
   어떤 클라이언트(Claude, ChatGPT, Cursor 등)든 자연어로 그 서버의 기능을 붙여 쓸 수 있다.
   핵심은 **서버 측 인터페이스의 보편화**다.
2. 사용자의 아이디어는 그 반대 방향이다 — **클라이언트(에이전트) 쪽을 잘 만들어서**, 이미 세상에
   존재하는(REST API로 동작하는) 수많은 시스템을 **그 시스템을 위해 서버를 새로 만들지 않고도**
   자연어로 다룰 수 있게 하자는 것이다.
3. 구체적으로는: 어떤 시스템이든 **API 문서·매뉴얼 설명(텍스트)만 업로드**하면, 그 문서를 읽은
   AI 에이전트가 해당 시스템에 맞춰 자연어로 응대하고, API 문서에 나온 대로 설정을 바꾸거나
   값을 조회해 사용자에게 알려주는 것까지 할 수 있어야 한다.

**결론(先공개)**: 이 아이디어는 **이미 있는 개념**이며, 크게 3갈래(①학술 연구 ②상용 프로덕트
③시장 수렴 추세)로 존재한다. 아래에서 각 갈래를 실제 사례·원문·링크와 함께 정리한다.

---

## 1. MCP란 무엇인가(대조군으로서 재확인)

> **원문(Anthropic 공식 문서, [modelcontextprotocol.io/introduction](https://modelcontextprotocol.io/introduction))**:
> "MCP (Model Context Protocol) is an open-source standard for connecting AI applications to
> external systems. ... Think of MCP like a USB-C port for AI applications. Just as USB-C
> provides a standardized way to connect electronic devices, MCP provides a standardized way to
> connect AI applications to external systems."

**번역**: MCP는 AI 애플리케이션을 외부 시스템에 연결하는 오픈소스 표준이다. AI 애플리케이션용
"USB-C 포트"라고 생각하면 된다 — USB-C가 전자기기를 연결하는 표준 방식을 제공하듯, MCP는 AI
애플리케이션을 외부 시스템에 연결하는 표준 방식을 제공한다.

**상세 설명**: MCP는 "서버"(도구/데이터 제공자)가 표준 프로토콜로 자신의 기능을 노출하면, 그
서버를 지원하는 어떤 "클라이언트"(Claude, ChatGPT, VS Code, Cursor 등)에서도 즉시 쓸 수 있게
하는 구조다. 문서가 명시하듯 "Broad ecosystem support"(광범위한 생태계 지원)가 핵심 가치이며,
**서버 개발자가 한 번만 잘 만들면 어디서든 재사용된다("build once and integrate everywhere")**는
"서버 표준화" 전략이다.

**우리 아이디어와의 차이**: MCP는 "이 시스템을 위한 MCP 서버를 누군가 새로 만들어야 한다"는
전제가 있다. 반면 사용자의 아이디어는 **서버(레거시 REST API)는 전혀 건드리지 않고, 클라이언트가
문서만 보고 알아서 적응**하는 것을 목표로 한다 — 이는 "이미 존재하는 수많은 REST API 시스템에
전부 MCP 서버를 새로 만들어 붙일 수는 없다"는 실용적 문제의식에서 출발한 접근이다.

---

## 2. 상용 프로덕트 사례 — "클라이언트가 문서/스펙만 보고 임의 시스템에 적응"

### 2.1 OpenAI **GPT Actions** — 사용자의 아이디어와 가장 근접한 상용 사례

> **원문([developers.openai.com/api/docs/actions/introduction](https://developers.openai.com/api/docs/actions/introduction))**:
> "GPT Actions empower ChatGPT users to interact with external applications via RESTful APIs
> calls outside of ChatGPT simply by using natural language. They convert natural language text
> into the json schema required for an API call. ... developers can now simply describe the
> schema of an API call, configure authentication, and add in some instructions to the GPT, and
> ChatGPT provides the bridge between the user's natural language questions and the API layer."

**번역**: GPT Actions는 ChatGPT 사용자가 자연어만으로 ChatGPT 밖의 외부 애플리케이션과 RESTful
API 호출을 통해 상호작용할 수 있게 한다. 자연어 텍스트를 API 호출에 필요한 JSON 스키마로
변환한다. 개발자는 API 호출의 스키마를 기술하고, 인증을 설정하고, GPT에 몇 가지 지침만 추가하면
되며, ChatGPT가 사용자의 자연어 질문과 API 계층 사이의 다리 역할을 한다.

**실사용 예시(공식 문서 그대로)**: 개발자가 weather.gov의 두 API(`/points/{lat},{lon}` →
`/gridpoints/{office}/{x},{y}/forecast`)의 JSON 스키마만 등록해두면, 사용자가 "이번 주말
워싱턴 DC 여행에 뭘 챙겨가야 해?"라고 물었을 때 ChatGPT가 위경도를 알아내 두 API를 순서대로
호출하고 일기예보 기반 짐 목록을 자연어로 답한다.

**상세 설명·시사점**: 이것이 정확히 사용자가 설명한 모델이다 — **서버(weather.gov)는 전혀
수정하지 않고, 클라이언트(ChatGPT)가 API 스키마 문서만 등록받아 자연어 ↔ API 호출을 양방향
번역**한다. 다만 GPT Actions는 (a) OpenAI의 폐쇄 생태계(ChatGPT/Custom GPT) 안에서만 동작하고
(b) 스키마를 "정적으로 미리 등록"해야 하며 런타임에 임의 문서를 업로드해 즉석에서 적응하지는
않는다는 점에서, 우리 시스템(Story 1.26 — 런타임 업로드+RAG 기반 동적 적응)과 차이가 있다.

### 2.2 ChatGPT **Plugins**(2023, 폐지됨) — 역사적 원조 사례이자 "시장 수렴"의 첫 증거

2023년 OpenAI가 최초로 선보인 "ChatGPT Plugins"는 제3자가 자사 API의 OpenAPI 스펙과 매니페스트
파일만 등록하면 ChatGPT가 자연어로 그 API를 호출하게 하는, GPT Actions의 전신 격 기능이었다.
이후 OpenAI는 이 기능을 **GPT Actions(Custom GPT 내장)로 흡수·대체**했고, 업계 전체는 이후
Anthropic이 주도한 MCP 표준으로 다시 수렴했다 — 즉 "클라이언트가 다양한 스펙을 알아서 이해하는"
접근이 처음 등장했다가, 결국 "서버 쪽 프로토콜을 표준화"하는 방향(MCP)으로 시장이 정리되고 있는
역사적 흐름을 보여주는 선례다.

### 2.3 Zapier: **Natural Language Actions(NLA)** → **MCP**로 전환

Zapier는 2023년경 "Natural Language Actions(NLA)"라는, ChatGPT Plugin 형태로 수천 개 연동
앱(Gmail, Slack, Notion 등)을 자연어로 조작하게 하는 API를 운영했다(`nla.zapier.com`). 2026-08
현재 시점에 해당 URL(`nla.zapier.com/docs/`)과 구 GPT 플랫폼 문서(`actions.zapier.com/docs/
platform/gpt`)에 접속하면 **자동으로 `mcp.zapier.com`(Zapier MCP 서버)로 리다이렉트**된다(직접
접속으로 확인).

**시사점**: 이는 "클라이언트가 자연어로 임의 앱을 조작"하게 하려던 초기 접근(NLA)이, 결국
"서버(Zapier)가 MCP라는 표준 프로토콜을 직접 지원"하는 방향으로 **시장이 자연스럽게 수렴**한
실제 사례다. 사용자의 아이디어(client-centric)와 MCP(server-centric)는 대립하는 개념이라기보다,
**시간이 지나며 서버 쪽이 표준을 지원하게 되면 client-centric 접근의 존재 이유가 줄어드는**
경향이 있음을 보여준다 — 단, "서버를 표준화할 수 없는"(레거시 시스템, 표준을 채택할 유인이
없는 소규모 서비스) 영역에서는 client-centric 접근이 여전히 유효하다는 반증이기도 하다.

### 2.4 **Composio** — "클라이언트(에이전트)가 각 서비스의 API를 이해하도록" 만드는 SaaS 미들레이어

> **원문([composio.dev](https://composio.dev/))**: "1,000+ integrations with just-in-time tool
> calls, secure delegated auth, sandboxed environments, and parallel execution." / "Tools
> resolved by intent, not configuration" / "Your agent has the intelligence. Now let it execute.
> Go from chatbot to general-purpose agent in five lines of code."

**번역**: 1,000개 이상의 통합에 대해 적시(just-in-time) Tool 호출, 안전한 위임 인증, 샌드박스
실행 환경, 병렬 실행을 제공한다. "Tool은 설정이 아니라 의도(intent)로 결정된다." "에이전트는
이미 지능을 갖고 있다. 이제 그것이 실행하게 하라 — 챗봇에서 범용 에이전트로, 5줄의 코드로."

**상세 설명**: Composio는 Gmail·Slack·GitHub·Notion·Stripe·Sentry·Linear 등 1,000개 이상의
실제 서비스에 대해 **미리 정규화된 Tool 스키마 + OAuth 인증 대행**을 제공하고, 에이전트(Claude,
GPT 등 어떤 LLM이든)가 자연어 의도만으로 그 Tool들을 호출하게 한다(공식 예시: "Sentry 오류를
확인하고 Linear 티켓을 만들어줘" → `SENTRY_LIST_ISSUES` → LLM 분류 → `LINEAR_CREATE_ISSUE`
자동 실행). **핵심은 Composio가 "서버(각 SaaS)를 대신해 표준 Tool 인터페이스를 미리 만들어두는"
중개자 역할**을 한다는 점 — 즉 "서버를 새로 만들 필요 없이, 이미 있는 REST API를 감싸는 계층을
만들어 클라이언트가 자연어로 쓸 수 있게 한다"는 사용자의 아이디어와 사업 모델이 정확히 같다.
다만 Composio는 "사전에 통합해둔 1,000개 서비스"에 한정되며, 사용자가 문서를 업로드해 **처음
보는 임의의 사내 시스템**에 즉석으로 적응하는 것까지는 지원하지 않는다(우리 시스템의
차별점이자, §4.4/§6에서 다시 언급).

---

## 3. 학술 연구 사례 — "LLM이 API 문서만으로 임의 API를 다루는 일반 능력"

### 3.1 **Gorilla**(UC Berkeley, NeurIPS 2024) — "방대한 API에 연결된 LLM"

> **원문([gorilla.cs.berkeley.edu](https://gorilla.cs.berkeley.edu/))**: "Rather have the user
> at the center, Gorilla enables users to interact with a wide range of services through LLMs.
> Gorilla is an open-source, state-of-the-art LLM that invokes API calls to interact with
> services!"

**번역**: 사용자를 중심에 두고, Gorilla는 사용자가 LLM을 통해 광범위한 서비스와 상호작용할 수
있게 한다. Gorilla는 서비스와 상호작용하기 위해 API를 호출하는 오픈소스 최첨단 LLM이다.

**상세 설명**: Gorilla는 (1) OpenFunctions — Java/REST/Python 등 다양한 언어의 함수 호출을
네이티브로 지원하도록 학습된 LLM, (2) **Berkeley Function-Calling Leaderboard(BFCL)** — REST
API를 포함한 함수 호출 능력을 2,000개 이상의 질문-함수-정답 쌍으로 평가하는 공개 리더보드,
(3) **GoEx**(Gorilla Execution Engine) — LLM이 생성한 API 호출을 실제로 실행하는 런타임으로,
"post-facto validation"(사후 검증)과 **"undo"·"damage confinement"**(되돌리기·피해 격리)
추상화를 제공해 완전 자율 실행의 위험을 관리한다. 이 세 요소로 구성된다.
링크: [Gorilla GitHub](https://github.com/ShishirPatil/gorilla), [BFCL 리더보드](https://gorilla.cs.berkeley.edu/leaderboard.html),
[GoEx 논문](https://arxiv.org/abs/2404.06921).

**시사점**: GoEx의 "undo/damage confinement" 개념은 우리 저장소가 이미 채택한 원칙(Story 1.17
Undo Tool, FR33-B의 "실제 실행 매칭은 Non-Goal — 안전성 우선" 판단)과 정확히 같은 문제의식이다
— **임의 API를 자동 실행하게 할수록 되돌리기·피해 범위 제한 장치가 필수**라는 것이 학계 컨센서스.

### 3.2 **RestGPT**(2023, arXiv:2306.06624) — "실제 세계의 RESTful API에 LLM 연결"

> **원문([arxiv.org/abs/2306.06624](https://arxiv.org/abs/2306.06624))**: "we explore a more
> realistic scenario by connecting LLMs with RESTful APIs, which adhere to the widely adopted
> REST software architectural style for web service development. ... RestGPT ... exploits the
> power of LLMs and conducts a coarse-to-fine online planning mechanism to enhance the abilities
> of task decomposition and API selection. RestGPT also contains an API executor tailored for
> calling RESTful APIs, which can meticulously formulate parameters and parse API responses."

**번역**: 우리는 널리 채택된 REST 소프트웨어 아키텍처 스타일을 따르는 RESTful API에 LLM을
연결하는, 더 현실적인 시나리오를 탐구한다. RestGPT는 LLM의 능력을 활용해 "거친 단계에서 세밀한
단계로(coarse-to-fine)" 온라인 계획을 수립하는 메커니즘으로 작업 분해와 API 선택 능력을
향상시킨다. RestGPT는 또한 RESTful API 호출에 특화된 API 실행기(executor)를 포함하는데, 이는
파라미터를 정교하게 구성하고 API 응답을 파싱한다.

**상세 설명**: RestGPT는 사용자의 아이디어 3번("API 문서대로 동작하면서 설정하거나 조회해서
값을 알려주는")을 학술적으로 가장 정확히 구현한 사례다 — 실제 RESTful API(스포티파이, TMDB 등)
문서를 주고 복잡한 자연어 지시를 API 호출 시퀀스로 분해·실행·응답 해석까지 end-to-end로
수행한다. 저자들은 이를 검증하기 위한 벤치마크 **RestBench**도 함께 공개했다.
링크: [RestGPT/RestBench 프로젝트 페이지](https://restgpt.github.io/), [논문 PDF](https://arxiv.org/pdf/2306.06624).

### 3.3 **API-Bank**(EMNLP 2023, arXiv:2304.08244) — "도구 활용 LLM"을 위한 최초의 종합 벤치마크

> **원문([arxiv.org/abs/2304.08244](https://arxiv.org/abs/2304.08244))**: "we introduce API-Bank,
> a groundbreaking benchmark, specifically designed for tool-augmented LLMs. ... We annotate 314
> tool-use dialogues with 753 API calls ... we construct a comprehensive training set containing
> 1,888 tool-use dialogues from 2,138 APIs spanning 1,000 distinct domains."

**번역**: 우리는 Tool을 활용하는 LLM을 위해 특별히 설계된 획기적인 벤치마크 API-Bank를 소개한다.
753개 API 호출을 포함한 314개의 도구 사용 대화에 주석을 달았다. 2,138개 API·1,000개의 서로
다른 도메인에 걸친 1,888개의 도구 사용 대화로 구성된 종합 학습 데이터셋을 구축했다.

**상세 설명·시사점**: "2,138개 API·1,000개 도메인"이라는 규모 자체가, "특정 도메인에 종속되지
않고 임의의 API 문서를 이해해 자연어로 응대하는 능력"이 이미 2023년부터 학계의 표준 연구
주제였음을 보여준다. 즉 사용자가 제시한 "도메인 비종속적 범용 API 에이전트"라는 아이디어는
**이미 이름이 붙어있는 연구 분야(Tool-Augmented LLM / Tool Learning)**다.

---

## 4. GitHub 오픈소스 생태계 실증 — "OpenAPI → MCP/Tool 자동 변환기"는 이미 하나의 카테고리다

GitHub 코드검색(`github.com/search?q=openapi+to+mcp&type=repositories`)에서 **"openapi to mcp"**로만
검색해도 **437개 저장소**가 나온다(2026-08-05 직접 검색·확인). 상위 결과들은 사용자의 아이디어를
정확히 구현한, 이미 수백~수천 스타를 받은 활발한 오픈소스 프로젝트들이다.

### 4.1 automation-ai-labs/**mcp-link**(622 stars) — "모든 OpenAPI V3 API를 MCP 서버로 변환"

> **원문([github.com/automation-ai-labs/mcp-link](https://github.com/automation-ai-labs/mcp-link))**:
> "Manual creation of MCP interfaces is time-consuming and error-prone. Lack of standardized
> conversion processes. MCP Link solves these issues through automation and standardization,
> allowing any API to easily join the AI-driven application ecosystem." / **Key Features**:
> "Automatic Conversion: Generate complete MCP Servers based on OpenAPI Schema" / "**Zero Code
> Modification**: Obtain MCP compatibility without modifying the original API implementation."

**번역**: MCP 인터페이스를 수작업으로 만드는 건 시간이 오래 걸리고 오류가 많다. 표준화된 변환
프로세스가 없다. MCP Link는 자동화와 표준화로 이 문제를 해결해, 어떤 API든 쉽게 AI 기반
애플리케이션 생태계에 합류할 수 있게 한다. **핵심 기능**: 자동 변환(OpenAPI 스키마 기반으로
완전한 MCP 서버 생성), **원본 코드 무수정**(원본 API 구현을 전혀 건드리지 않고 MCP 호환성 확보).

**시사점**: "**서버는 그대로 두고**(Zero Code Modification) 문서(OpenAPI 스키마)만으로 적응
계층을 만든다"는 문장이 사용자의 아이디어 그 자체다. 실제 사용 예시로 Brave/Figma/GitHub/Notion/
Slack/Stripe/TMDB 등 서로 무관한 도메인의 API들을 **동일한 변환기 하나**로 커버하는 것을 README가
직접 시연한다(도메인 비종속성 실증).

### 4.2 janwilmake/**openapi-mcp-server**(900 stars) — "복잡한 OpenAPI 문서를 쉬운 말로 탐색하게"

> **원문**: "A Model Context Protocol (MCP) server for Claude/Cursor that enables searching and
> exploring OpenAPI specifications through oapis.org. ... The MCP works by applying a 3 step
> process: 1. It figures out the openapi identifier you need 2. It requests a summary of that in
> simple language 3. It determines which endpoints you need, and checks out how exactly they work
> (again, in simple language)."

**번역**: Claude/Cursor용 MCP 서버로, oapis.org를 통해 OpenAPI 스펙을 검색·탐색하게 한다. 3단계로
동작한다 — ①필요한 openapi 식별자를 파악 ②그것을 쉬운 말로 요약 요청 ③필요한 엔드포인트를
결정하고 정확한 동작 방식을 (역시 쉬운 말로) 확인.

**시사점**: "복잡한 API 문서를 쉬운 말로 요약해 필요한 엔드포인트만 찾아준다"는 이 3단계는 우리
Story 1.31(`OpenApiSpecAdapter`가 각 엔드포인트를 Q&A로 자동 변환 → RAG 검색으로 필요한 것만
찾음)과 구조적으로 동일한 접근이다 — **900개의 stars와 다수 기여자**(snaggle-ai, smithery 등)가
이 패턴의 실용성을 검증한다.

### 4.3 twilio-labs/**mcp**(공식 벤더 프로젝트, 108 stars) — 대기업이 채택한 동일 패턴

> **원문([github.com/twilio-labs/mcp](https://github.com/twilio-labs/mcp))**: "This monorepo
> contains two main packages: (1) mcp - MCP Server for all of Twilio's Public API (2)
> openapi-mcp-server - **An MCP server that serves the given OpenAPI spec**." / 트러블슈팅 섹션:
> "Context Size Limitations: Due to LLM context limits, load specific APIs using `--services` or
> `--tags`."

**번역**: 이 모노레포는 두 패키지로 구성된다 — (1) Twilio 전체 공개 API용 MCP 서버 (2) **주어진
임의의 OpenAPI 스펙을 그대로 서빙하는 범용 MCP 서버**. 트러블슈팅: "LLM 컨텍스트 제한 때문에
`--services`나 `--tags`로 특정 API만 로드하라."

**시사점**: **실제 상장 기업(Twilio)이 자사 팀 명의로** "임의 OpenAPI 스펙 → MCP" 범용 변환기를
별도 패키지로 공식 배포한다는 것은, 이 패턴이 실험적 취미 프로젝트 수준을 넘어 **프로덕션급
수요**가 있음을 보여준다. 또한 "컨텍스트 제한 때문에 API를 태그/서비스별로 필터링해야 한다"는
경고는, 우리 Story 1.33(유형 C 하이브리드 검색이 "도메인별로 소규모만 병렬 조회"하도록 설계한
이유)과 정확히 같은 실무적 제약을 확인해준다.

### 4.4 oomol-lab/**open-connector**(4,300+ stars) — Composio의 오픈소스 대안, 훨씬 큰 스타 수

> **원문([github.com/oomol-lab/open-connector](https://github.com/oomol-lab/open-connector))**:
> "OpenConnector is an open-source connector gateway for AI agents and an alternative to
> Pipedream/Composio. Connect user app accounts once, then expose a shared catalog of 1,000+
> providers and 10,000+ prebuilt Actions to agents and applications." 인터페이스는 "**MCP, HTTP,
> OpenAPI**" 세 가지를 동시에 지원한다.

**번역**: OpenConnector는 AI 에이전트를 위한 오픈소스 커넥터 게이트웨이이며 Pipedream/Composio의
대안이다. 사용자 앱 계정을 한 번만 연결하면, 1,000개 이상의 프로바이더와 10,000개 이상의 미리
만들어진 Action을 에이전트·애플리케이션에 공유 카탈로그로 노출한다.

**시사점**: §2.4의 Composio(상용, 비공개 소스)와 거의 동일한 가치제안을 오픈소스로 제공하며
**Composio 자체보다도 더 많은 GitHub 스타(4,300+)**를 받았다는 점이 흥미롭다 — "REST API를
클라이언트가 이해하기 좋은 형태로 미리 정규화해 자연어로 쓰게 한다"는 시장 수요가 상용/오픈소스
양쪽에서 독립적으로 큰 규모로 검증됐음을 보여준다. 다만 이 프로젝트 역시 "1,000+ 사전 통합
프로바이더" 카탈로그 방식이라, **처음 보는 임의의 사내 시스템 문서를 런타임에 업로드**하는
우리 시스템(Story 1.26)과는 여전히 차별점이 있다.

### 4.5 그 외 확인된 동일 카테고리 프로젝트(규모 실증용, 상세 인용 생략)

| 저장소 | Stars | 설명(README 발췌) |
|---|---|---|
| [open-webui/mcpo](https://github.com/open-webui/mcpo) | 4,333 | "A simple, secure MCP-to-OpenAPI **proxy** server" — 반대 방향(MCP→OpenAPI) 변환기도 활발함을 보여주는 사례 |
| [harsha-iiiv/openapi-mcp-generator](https://github.com/harsha-iiiv/openapi-mcp-generator) | 629 | "A tool that converts OpenAPI specifications to MCP server" |
| [higress-group/openapi-to-mcpserver](https://github.com/higress-group/openapi-to-mcpserver) | 277 | Alibaba Higress(API 게이트웨이) 팀이 공개한 변환기 |
| [ckanthony/openapi-mcp](https://github.com/ckanthony/openapi-mcp) | 191 | "Dockerized MCP Server to allow your AI agent to access any API with existing api docs" |
| [taskade/mcp](https://github.com/taskade/mcp) | 163 | "Build AI agent tools from **any** OpenAPI API and connect to Claude, Cursor, …" |

**종합 시사점**: "openapi to mcp"라는 단일 검색어로만 400개 이상의 저장소가 나오고, 그중 상위
다수가 (Twilio·Alibaba Higress 같은) 실제 기업이 공식 배포한 프로젝트라는 사실은, 사용자의
아이디어("서버는 그대로 두고 문서만으로 클라이언트가 적응")가 **이미 하나의 성숙한 오픈소스
카테고리(OpenAPI-to-Agent-Tool Generator)로 자리 잡았음**을 강하게 뒷받침한다.

---

## 5. 종합 비교표

| 구분                             | 접근 방향                                                             | 사전 통합 필요 여부                      | 실행(쓰기) 지원                        | 우리 시스템(Story 1.26~1.33)과의 관계       |
| -------------------------------- | --------------------------------------------------------------------- | ---------------------------------------- | -------------------------------------- | ------------------------------------------- |
| **MCP**                          | 서버 표준화                                                           | 서버가 MCP를 구현해야 함(신규 개발 필요) | 서버 구현에 따라 다름                  | 대조군 — 우리는 MCP 서버를 만들지 않음      |
| **OpenAI GPT Actions**           | 클라이언트가 사전 등록된 OpenAPI 스키마를 이해                        | 개발자가 스키마를 사전 등록(정적)        | 지원(함수 호출로 실행)                 | 가장 유사 — 단, 런타임 업로드형 적응은 없음 |
| **ChatGPT Plugins(폐지)**        | 클라이언트가 매니페스트+스펙을 이해                                   | 사전 등록                                | 지원                                   | 역사적 선례, GPT Actions로 흡수됨           |
| **Zapier NLA→MCP**               | (과거)클라이언트 이해 → (현재)서버 표준화                             | 과거: 사전 연동 앱만 / 현재: MCP         | 지원                                   | 시장이 MCP로 수렴한 실증 사례               |
| **Composio / open-connector**    | 중개 SaaS(또는 OSS)가 1,000+ 서비스를 사전 정규화                     | 사전 통합된 서비스만                     | 지원(샌드박스 실행)                    | 유사 — 단, "이미 등록된 서비스"에 한정      |
| **Gorilla/OpenFunctions/GoEx**   | LLM 자체가 다양한 API 호출을 학습                                     | 학습 데이터 필요(사전)                   | GoEx가 undo/damage confinement로 지원  | 안전장치(Undo) 설계 철학 일치               |
| **RestGPT**                      | LLM이 RESTful API 문서를 보고 실시간 계획·실행                        | **런타임 문서 제공만으로 가능**          | 지원(API Executor)                     | **가장 근접** — 우리 방향과 구조적으로 동일 |
| **API-Bank**                     | (벤치마크) 도메인 비종속 Tool 사용 평가                               | 해당 없음(평가셋)                        | 평가 대상에 포함                       | 우리 문제의식이 이미 표준 연구주제임을 실증 |
| **mcp-link / openapi-mcp-server 등(OSS)** | 범용 OpenAPI→MCP 변환기(수백~수천 stars, Twilio·Alibaba 등 벤더 채택 | **불필요(스펙 URL만 지정)**      | 지원(원본 API 그대로 호출, 무수정)      | **가장 근접** — "서버 무수정"이 핵심 공통점 |
| **우리 시스템(Story 1.26/1.31)** | 클라이언트(RAG+LangGraph)가 **런타임 업로드된** OpenAPI/매뉴얼을 이해 | **불필요(업로드만 하면 즉시 반영)**      | **미지원(Non-Goal로 명시, 후속 과제)** | —                                           |

---

## 6. 우리 시스템 대비 시사점 및 다음 방향 제안(참고용, 결정 아님)

1. **아이디어 자체는 이미 검증된 시장/연구 방향이다** — 사용자의 문제의식(MCP처럼 서버를 새로
   만들 수 없는 상황에서, 클라이언트가 문서만으로 적응)은 OpenAI GPT Actions·RestGPT가 상용/
   학술 양쪽에서 이미 증명한 패턴이다. **다만 우리 시스템(Story 1.26/1.31)이 갖는 차별점은
   "런타임 업로드 즉시 반영"** — GPT Actions·Composio는 모두 "사전 등록/사전 통합"이 필요한
   반면, 우리는 웹 업로드 즉시 지식베이스가 재구성된다(FR33-B).
2. **가장 큰 격차는 "실제 실행"이다** — RestGPT/GoEx/GPT Actions/Composio는 모두 **실제 API
   호출(쓰기 포함)까지** 수행하지만, 우리는 Story 1.31에서 이를 명시적 Non-Goal로 미뤄뒀다.
   시장 사례들이 공통으로 강조하는 안전장치(GoEx의 undo/damage confinement, Composio의 샌드박스
   실행+세분화된 권한)를 먼저 설계한 뒤 실행 기능을 열어야 한다는 점을 재확인했다.
3. **"서버 표준화(MCP)로의 수렴" 리스크를 인지할 것** — Zapier NLA→MCP 사례처럼, 장기적으로는
   업로드 대상 시스템들이 스스로 MCP 서버를 지원하게 될 가능성이 있다. 우리 아키텍처는 "MCP
   서버가 없는 레거시/사내 시스템"을 위한 **보완재**로 포지셔닝하는 것이 현실적이며, 향후
   "업로드된 OpenAPI 문서 대신 MCP 서버 URL을 직접 등록하는" 경로를 병행 지원하는 것도 검토
   가치가 있다(신규 Epic 후보, 지금 결정할 사안은 아님).

## 부록: 참고 링크 전체 목록

- MCP 공식 소개: https://modelcontextprotocol.io/introduction
- OpenAI GPT Actions 소개: https://developers.openai.com/api/docs/actions/introduction
- Composio: https://composio.dev/
- Gorilla 프로젝트 홈: https://gorilla.cs.berkeley.edu/
- Gorilla GitHub: https://github.com/ShishirPatil/gorilla
- Berkeley Function-Calling Leaderboard: https://gorilla.cs.berkeley.edu/leaderboard.html
- GoEx 논문(arXiv:2404.06921): https://arxiv.org/abs/2404.06921
- RestGPT 논문(arXiv:2306.06624): https://arxiv.org/abs/2306.06624
- RestGPT/RestBench 프로젝트: https://restgpt.github.io/
- API-Bank 논문(arXiv:2304.08244): https://arxiv.org/abs/2304.08244
- Zapier MCP(구 NLA/GPT Actions 리다이렉트 확인): https://mcp.zapier.com/
- GitHub 검색("openapi to mcp", 437건): https://github.com/search?q=openapi+to+mcp&type=repositories
- mcp-link(622 stars): https://github.com/automation-ai-labs/mcp-link
- openapi-mcp-server(900 stars): https://github.com/janwilmake/openapi-mcp-server
- Twilio MCP 공식 모노레포(108 stars): https://github.com/twilio-labs/mcp
- open-connector(4,300+ stars): https://github.com/oomol-lab/open-connector
- mcpo(4,333 stars, 역방향 MCP→OpenAPI): https://github.com/open-webui/mcpo
- openapi-mcp-generator(629 stars): https://github.com/harsha-iiiv/openapi-mcp-generator
- openapi-to-mcpserver(277 stars, Alibaba Higress): https://github.com/higress-group/openapi-to-mcpserver
- openapi-mcp(191 stars): https://github.com/ckanthony/openapi-mcp
- Taskade MCP(163 stars): https://github.com/taskade/mcp

---
*최종 업데이트: 2026-08-05*
