# AI SIP PBX — 시스템 소개

**AI SIP PBX**는 Python 기반 **SIP B2BUA(Back-to-Back User Agent)** 위에 **실시간 음성 AI**, **웹 운영 콘솔**, **지식·연락처·문자·예약**을 한데 묶은 통합 플랫폼이다.

| 항목 | 내용 |
|------|------|
| **대상 독자** | 제품·운영·엔지니어링 이해관계자, 시스템 아키텍처 검토에 참여하는 팀 |
| **최종 수정** | 2026-04-27 |
| **이전 문서 백업** | 상세 항목·API 표가 필요하면 [`SYSTEM_OVERVIEW_2026-04-27_before_rewrite.md`](SYSTEM_OVERVIEW_2026-04-27_before_rewrite.md) 참고 |

### 다이어그램 (PNG) — 문서·교육 자료 등에 삽입

렌더된 그림은 `docs/images/system-overview/` 에 있으며, 편집용 Mermaid 소스는 `docs/diagrams/system-overview/`의 `01-`…`11-` 접두 `.md` 파일(아래 표·[README](diagrams/system-overview/README.md))이다. PNG는 **`mermaid-frontend.json` + `mermaid-frontend.css`** 로 생성해 **밝은 UI 톤·카드형 패널·넉넉한 노드 간격**을 맞춘다(상세·재생성: [diagrams/system-overview/README.md](diagrams/system-overview/README.md)).

| PNG | 절 | 소스(`.md`) |
|-----|----|--------------|
| [`01-logical-architecture.png`](images/system-overview/01-logical-architecture.png) | §3.1 | [`01-logical-architecture.md`](diagrams/system-overview/01-logical-architecture.md) |
| [`02-inbound-voice-sequence.png`](images/system-overview/02-inbound-voice-sequence.png) | §3.3 | [`02-inbound-voice-sequence.md`](diagrams/system-overview/02-inbound-voice-sequence.md) |
| [`03-rtp-modes.png`](images/system-overview/03-rtp-modes.png) | §4.2 | [`03-rtp-modes.md`](diagrams/system-overview/03-rtp-modes.md) |
| [`04-smart-barge-in.png`](images/system-overview/04-smart-barge-in.png) | §4.3 | [`04-smart-barge-in.md`](diagrams/system-overview/04-smart-barge-in.md) |
| [`05-intent-routing.png`](images/system-overview/05-intent-routing.png) | §4.4 | [`05-intent-routing.md`](diagrams/system-overview/05-intent-routing.md) |
| [`06-knowledge-flow.png`](images/system-overview/06-knowledge-flow.png) | §4.5 | [`06-knowledge-flow.md`](diagrams/system-overview/06-knowledge-flow.md) |
| [`07-booking-tools.png`](images/system-overview/07-booking-tools.png) | §4.6 | [`07-booking-tools.md`](diagrams/system-overview/07-booking-tools.md) |
| [`08-sip-message-sequence.png`](images/system-overview/08-sip-message-sequence.png) | §4.7 | [`08-sip-message-sequence.md`](diagrams/system-overview/08-sip-message-sequence.md) |
| [`09-ringback-suno.png`](images/system-overview/09-ringback-suno.png) | §4.9 | [`09-ringback-suno.md`](diagrams/system-overview/09-ringback-suno.md) |
| [`10-call-control-priority.png`](images/system-overview/10-call-control-priority.png) | §4.10 | [`10-call-control-priority.md`](diagrams/system-overview/10-call-control-priority.md) |
| [`11-outbound-campaign.png`](images/system-overview/11-outbound-campaign.png) | §4.8 | [`11-outbound-campaign.md`](diagrams/system-overview/11-outbound-campaign.md) |

---

## 1. 배경 및 목표

### 1.1 왜 만들었는가 (배경)

- 기존 **시나리오형 콜봇**은 초기 시나리오·답변셋 구축에 **높은 고정비**가 들고, 운영 중 변경도 **스크립트 단위 재작업**에 의존한다.
- 전형적인 **ARS 트리 구조**는 사용자 질문을 유연하게 받기 어렵고, 관리자가 **의도 밖 문의**를 체계적으로 흡수하기도 어렵다.
- **문제은행식 FAQ**만으로는 다양한 표현·후속 질문·맥락 전환을 커버하기 어렵다.

### 1.2 현황 (As-Is 관점에서의 문제)

- 지식이 **수동 입력**에 묶이면 최신성·규모 확장에 한계가 있다.
- 음성 경로가 **고정 TTS + 긴 지연**이면 실제 대화 같은 **턴교환**과 **끼어들기** 요구를 만족시키기 어렵다.
- AI가 답하지 못할 때 **상담원 연계**가 ARS·별도 시스템에 흩어지면 **일관된 고객 경험**을 주기 어렵다.

### 1.3 지향점 (To-Be 목표)

- **Agentic AICC**: LLM·도구·RAG를 묶어 **의도에 맞는 행동**(예약 조회·지식 검색·호전환)을 한 흐름에서 수행한다.
- **Active RAG**: 통화·문자 등 **운영 데이터가 쌓일수록** 지식과 캐시가 갱신되어 **한계 비용**을 낮춘다.
- **HITL + 상담원 전환**: AI 한계 구간을 **대시보드 협업** 또는 **내선 호전환**으로 연결해 **품질과 가용성**을 동시에 확보한다.
- **멀티 테넌트**: 내선(테넌트) 단위로 지식·페르소나·캐시를 **격리**해 **소규모 다수 테넌트** 운영이 가능하다.

---

## 2. Ideation: 해결 전략과 시스템 비교

### 2.1 전략 한 줄

**“표준 SIP/RTP로 통화는 안정적으로 중계하고, 음성·텍스트·툴은 Pipecat + LangGraph + FastAPI로 오케스트레이션한다.”**

- 시그널링·RTP는 **B2BUA**에서 일관되게 제어한다.
- AI 로직은 **대화 그래프(LangGraph)**와 **스토리지(ChromaDB, SQLite)**로 모듈화한다.
- 운영 UI는 **Next.js + Socket.IO**로 실시간 상황을 보여 주고, **착신 정책·연결음·채팅 AI**는 설정 화면으로 모은다.

### 2.2 기존 상용/일반적 구성 (As-Is) vs 본 시스템 (To-Be)

| 구분 | 일반적 As-Is | 본 시스템 To-Be |
|------|----------------|-----------------|
| **지식** | 수개월 시나리오·정적 FAQ | 통화/문자 기반 **자동 적재** + RAG, 시맨틱 캐시 |
| **대화** | ARS 트리, 규칙 매칭 | **의도 분류 + LLM 추론** + 필요 시 **툴 호출** |
| **상담 연계** | 별도 CTI, 수동 | **HITL·호전환·에스컬레이션 모드**를 동일 PBX 흐름에 통합 |
| **음성 UX** | 긴 TTS, 끼어들기 제한 | **VAD + 턴 전략 + 스마트 바지인**, 20ms 격자 **연속 RTP** (AI 모드) |
| **멀티채널** | 음성/문자 분리 제품 | **SIP MESSAGE·RCS/SMS**와 **동일 에이전트**를 맞댈 수 있음(설정 기반) |
| **착신 정책** | PBX/헤더에 분산 | **착신 제어 DB + 스케줄**로 “직접/지연 AI/즉시 AI/전달/그룹”을 한 곳에서 |

---

## 3. 현재 시스템 아키텍처 (상세)

### 3.1 논리 구성

![논리 아키텍처: 외부 단말·B2BUA·AI·데이터·웹](images/system-overview/01-logical-architecture.png)

*편집·재렌더: [`diagrams/system-overview/01-logical-architecture.md`](diagrams/system-overview/01-logical-architecture.md)*

### 3.2 데이터·테넌트 (「나만의 AI」를 가능하게 하는 구조)

**데이터** 저장·조회 위치, **고객사·조직** 단위(테넌트)로 **지식·응답**이 **분리**되는 방식을 아래에서 정리한다.

**비유**  
하나의 PBX/플랫폼을 **여러 ‘입주사’**가 쓰는 오피스와 같다. 건물(시스템)은 공유하지만, **각 사무실(테넌트) 서랍**에는 **그 회사만의 매뉴얼**이 들어 있다. 엘리베이터(전화)로 들어온 방문객(발신자)은 **접수처 안내(착신 내선)**에 따라 **어느 서랍을 열지**가 결정되고, AI는 **그 서랍에 있는 지식**만 꺼내 답한다.

**테넌트란**  
- 기술적으로는 보통 **착신 SIP 내선(사용자 ID)** 를 **테넌트 키**(`owner` 등)로 쓴다.  
- “A 번호로 걸리면 A 회사 AI”, “B 번호로 걸리면 B 회사 AI”처럼 **한 번에 하나의 ‘나만의 AI’ 페르소나·지식**이 선택된다.  
- **B 회사**가 올려 둔 FAQ가 **A 회사** 통화에 **섞이지 않도록** 설계한 것이 핵심이다.

**지식·AI가 테넌트별로 나뉘는 이유 (장점)**  
- **지식 격리**: **벡터 DB(ChromaDB)** 에서 `knowledge`·`qa_cache`·`persona` 등이 **owner(내선)별 컬렉션**으로 분리되어, RAG·캐시·인사/톤이 **다른 주체의 데이터에 의존하지 않는다**.  
- **나만의 AI**: 상담·영업팀이 올리는 **문서·Q&A**와 통화·문자로 쌓이는 **자동 적재**가 전부 **그 테넌트의 “두뇌”**에만 쌓인다. 경쟁사·다른 점포와 **지식이 섞일 위험**을 막는다.  
- **페르소나**: “우리는 이런 톤·이런 업무 범위”를 **조직마다** 다르게 둘 수 있어, 동일 LLM 뒤에서도 **브랜드에 맞는 응답**이 나온다.  
- **운영 단위**: 예약·착신 제어·연락처 등 **관계형 데이터(SQLite 등)**도 **테넌트/owner 단위**로 쪼개 관리해, **설정·이력**이 뒤엉키지 않게 한다.

**한 줄 요약**  
> **테넌트 = (대개) 착신 내선 1로 묶이는 “고객사·조직” 단위**이고, **지식·캐시·페르소나·업무 DB를 끊어 두어** “같은 플랫폼이지만 **우리만의 AI**”를 갖는 것이 이 구조의 본질이다.

(포트·호스트·배포 경로 등 **엔지니어용 런타임 표**는 [`SYSTEM_OVERVIEW_2026-04-27_before_rewrite.md`](SYSTEM_OVERVIEW_2026-04-27_before_rewrite.md) 또는 운영 가이드에서 다룬다.)

### 3.3 주요 제어 루프 (복잡 흐름: 무응답 → AI → HITL → 운영자 채팅 기반 응대)

가장 **많은 모듈이 엮이는** 인입 시나리오로 정리한다. (단순 “사람끼리 통화만 되고 끝”이 아닌 경우.)

1. **발신 → 착신(사람)**  
   B2BUA가 **2차 INVITE**로 벨을 울리지만, 착신이 **끄지 못하거나(무응답)** , 착신 정책상 **N초 후 AI** 등으로 **AI 음성 파이프라인**이 뜬다.  
2. **AI 1차 응대**  
   STT → LangGraph(의도·RAG·LLM) → TTS로 **고객과 음성 대화**가 이어진다.  
3. **HITL 에스컬레이션**  
   AI **신뢰도가 낮거나** 답이 어려운 intent 등으로 **HITL**이 켜지면, **대시보드**에 `hitl_requested` 등으로 **질문·call_id**가 올라간다. (고객에는 대기 멘트 TTS.)  
4. **운영자는 “전화”가 아니라 “채팅(텍스트)”으로 답**  
   운영자는 실시간으로 **웹·Socket.IO**를 통해 **짧은 사실/지시**를 입력한다(환경에 따라 대시보드 HITL 패널).  
5. **AI가 그 문구를 “그대로 읽기”가 아니라 가공**  
   시스템이 운영자 문장을 `format_hitl_reply` 를 포함한 흐름으로 **고객이 듣기 자연스운 한국어**로 정리한 뒤 **TTS**로 보낸다.  
6. **결과**  
   **사람(운영자)의 지식·판단**이 **그 통화의 AI 응답**에 반영되고, 이후 **지식베이스 자동 반영** 정책이 있으면 같은 질문을 AI가 **다음부터 직접** 처리할 수도 있다(제품/설정에 따름).

![복잡 루프: 무응답 → AI 음성 → HITL → 운영자 채팅 → 정제 TTS](images/system-overview/02-inbound-voice-sequence.png)

*편집·재렌더: [`diagrams/system-overview/02-inbound-voice-sequence.md`](diagrams/system-overview/02-inbound-voice-sequence.md)*

---

## 4. 핵심 기능 (User Story·경험 중심)

각 **4.1~4.10** 절의 구성은 **(1) 배경·페르소나·과정·효과 → (2) Journey 도식 + 시스템 도식 → (3) 절 맨 아래 User story 표** 이다. 상세·경계는 **도식**·`docs/reports`·코드로 병행한다.

### §4 하위 목차

| 절 | 주제 | **Journey**(사용자·상황) | **시스템**도식(기술) |
|----|------|----------------------------|----------------------|
| [4.1](#41-sip-pbxb2bua) | SIP·B2BUA | 12 | 01 |
| [4.2](#42-rtp) | RTP | 13 | 03 |
| [4.3](#43-ai-음성) | 음성 | 14 | 04 |
| [4.4](#44-langgraph) | 의도 | 15 | 05 |
| [4.5](#45-지식) | 지식·HITL | 16 | 06, 02 |
| [4.6](#46-예약) | 예약 | 17 | 07 |
| [4.7](#47-문자) | 문자 | 18 | 08 |
| [4.8](#48-outbound) | Outbound | 19 | 11 |
| [4.9](#49-연결음) | 연결음 | 20 | 09 |
| [4.10](#410-착신) | 착신 제어 | 21 | 10 |

---

### 4.1 SIP PBX·B2BUA

**이 기능이 쓰이는 이유 (배경)**  
대표번호·콜센터는 **한 통화** 안에서 **벨, 연결음, 첫 응답(사람/무응답, AI, 전환)**이 **연이어** 일어나야 한다. 일반 SBC(단순 전달)만으로는 **같은 세션**을 유지하며 **AI와 상담원을 갈아끼우기** 어렵다. **B2BUA**는 **발신 레그**와 **착신 레그**를 **분리**해 제어하므로, **한쪽만 AI**·**이후 Transfer** 같은 **시나리오**를 **소프트웨어**로 구현할 수 있다.

**핵심 페르소나**  
- **발신 고객**: “대표번호로 **한 번**” 걸어 **문의~상담**까지 **끊지 않기**를 기대한다.  
- **착신자(사람)**: **내선**이 울리고, **무응답**이면 **다음 정책(예: AI)**이 이어질 수 있다.  
- **운영·SRE**: **호**는 유지한 채 **AI**만 재기동·튜닝하거나, 장애 시 **SIP / RTP / AI** **범위**를 나누어 본다.

**의존·사용하는 능력**  
- SIP: **INVITE**, **200 OK**, **BYE**, CallManager / TransferManager / OutboundCallManager 등 **세션 동기** (가칭·상세는 구현·리포트).  
- **2차 INVITE**, **early media**(§4.9)와 결합될 수 있음.

**시간순 과정(요약)**  
1. 발신 **INVITE** → B2BUA가 **착신**에 2차 **INVITE** (벨, 연결음 가능).  
2. **200 OK** → 한동안 **인간–인간** Bypass(§4.2) 또는 **무응답/착신 정책**에 따라 **AI** 투입(§3.3, §4.3).  
3. **호전환** → **새** 대상과 **Bridge** / SIP 재협상.

**이때 느끼는 경험·효과**  
- **고객**: “끊었다 **다시** 걸지” 않고, **같은 통화**에서 **응답 주체**만 바뀌는 **경로**(정책·§4.10).  
- **비즈·운영**: **CX** 혼란↓, **장애** 시 **롤백 범위**↓(호·AI 분리).

#### 도식 ①: **사용자·상황** 흐름 (Journey)

![4.1 발신~응답~AI·전환](images/system-overview/12-journey-4-1-sip-pbx.png)

*소스: [`12-journey-4-1-sip-pbx.md`](diagrams/system-overview/12-journey-4-1-sip-pbx.md)*

#### 도식 ②: **시스템·논리** (기존)

![논리 아키텍처](images/system-overview/01-logical-architecture.png)

*소스: [`01-logical-architecture.md`](diagrams/system-overview/01-logical-architecture.md) · §3.1과 동일*

**요지**: B2BUA = **독립 레그** + **AI·Transfer** **끼움**. 메시지·필드는 SIP 구현·`docs/reports` 참고.

#### User story (절 맨 하단)

| ID | 페르소나 | **필요·동기** | **쓰는 기능·계층** | **과정(요약)** | **체감·결과** | **효과** |
|----|----------|---------------|-------------------|----------------|---------------|----------|
| US-4.1a | 발신 **고객** | 문의~상담을 **끊지 않고** 한 통화로 | B2BUA 세션, 2차 INVITE, Bypass/AI | 다이얼 → 벨·(연결음) → (조건) AI → (전환) 상담 | “한 흐름” | 이탈·이중 통화 느낌 감소 |
| US-4.1b | **SRE/운영** | 장애 시 **AI만** **재기동**·호는 유지 | 동일 런타임 내 SIP·RTP·AI 구분 | 이벤트·로그·배포 단위로 분리 | **범위 좁힌** 복구 | MTTR·리스크 감소 |

---

### 4.2 RTP

**이 기능이 쓰이는 이유 (배경)**  
**같은 PBX**라도 **인간끼리**는 **듣고 말하는 지연**을 최소로 **양방향 릴레이**하고, **AI** 구간은 **STT·LLM·TTS** 뒤에 **귀에 끊김이 덜** 느껴지도록 **20ms 격자 RTP·큐·무음**으로 **스트림**을 맞춘다. **호전환**이 나면 **Bridge**로 **새 담당**과 **미디어**를 이어 **다시 “사람 통화”**에 가깝게 돌아간다.

**핵심 페르소나**  
- **인간–인간(상담·고객)**: **끊김 없는** 대화, **에코** 완화.  
- **AI 통화 고객**: 로봇 목소리가 **끊기지 않고** 이어짐.  
- **운영**: **Bypass / AI / Bridge** 모드에 따라 **AEC·STT 튜닝** 정책을 다룸.

**의존·사용하는 능력**  
20ms 격자, **RTP** 큐, 무음 패딩, **AEC**, STT **후처리**(§4.3과 연동).

**시간순 과정(요약)**  
1. **200 OK** 이후 모드 판정: **Bypass**면 즉시 양방향.  
2. **AI**면: 마이크 → STT → … → TTS → **연속 RTP** 송신.  
3. **전환**이면: **Bridge**로 새 레그.

**이때 느끼는 경험·효과**  
- 인간 통화: **즉시성**. AI: **끊김 없는** 오디오. 모드 전환은 고객이 **“기술 용어”**가 아니라 **“누가 말하는지”**로만 느낌(정책).

#### 도식 ①: Journey (모드·경로)

![4.2 RTP 모드별 경로](images/system-overview/13-journey-4-2-rtp.png)

*소스: [`13-journey-4-2-rtp.md`](diagrams/system-overview/13-journey-4-2-rtp.md)*

#### 도식 ②: 시스템 (기존)

![RTP 모드](images/system-overview/03-rtp-modes.png)

*소스: [`03-rtp-modes.md`](diagrams/system-overview/03-rtp-modes.md)*

**품질**: AEC·STT 후처리는 §4.3과 연동.

#### User story (절 맨 하단)

| ID | 페르소나 | 필요·동기 | 쓰는 기능 | 과정(요약) | 체감·결과 | 효과 |
|----|----------|------------|----------|------------|----------|------|
| US-4.2a | 인간–인간 | 빠른 듣기·말하기 | Bypass, RTP 릴레이 | 200 OK 후 양방향 | 지연 못 느낌 | 만족도·NPS |
| US-4.2b | AI 통화 | 끊김 없는 TTS | 20ms RTP, 큐, 무음 | STT→LLM→TTS→RTP | 귀에 부담↓ | 끊김 민원↓ |

---

### 4.3 AI 음성 (Voice Agent)

**이 기능이 쓰이는 이유 (배경)**  
AI가 **TTS로 말하는 동안** 고객은 **짧게 “응”**만 할 수도 있고, **“잠깐만”**처럼 **진짜로 끼어들** 수도 있다. 둘을 **같은 “끼어들기”**로 처리하면 **불필요하게 TTS가 끊**기거나, 반대로 **질문이 묻힌다**. **VAD·턴·스마트 바지인**으로 **맞장구(짧은 수긍)**와 **실제 끼어들기**를 나누고, 잡음·짧은 음성이 **엉뚱한 LLM**으로 가지 않게 **후처리**한다.

**핵심 페르소나**  
- **고객**: **말이 끊기지 않는** 대화, **질문**은 **분명히** 전달.  
- **제품·QA**: 맞장구/끼어들기 **비율**, **TTS 중단** 횟수로 **품질**을 본다.

**의존·사용하는 능력**  
VAD, STT, 턴 전략, **스마트 바지인**(키워드·최소 단어·LLM), Pipecat 파이프라인(구현명은 리포트).

**시간순 과정(요약)**  
1. 고객 발화 → VAD·STT → **이번 발화 끝** 판정.  
2. AI TTS 재생 중 고객 발화 → **바지인**: 키워드·단어 수·LLM으로 **맞장구 vs 끼어들기**.  
3. 끼어들기면 TTS 중단 후 **새 턴** 처리.

**이때 느끼는 경험·효과**  
“**응**”만 할 때는 **AI가 말을 끝까지** 이어 가고, **질문**할 때만 **끊기고** 다시 듣는 **자연스러운** 전화 대화에 가깝다. **잡음**으로 **질문이 잘못 올라가는** 비율이 줄어 **비용·오답**이 줄 수 있다(튜닝·설정).

#### 도식 ①: Journey

![4.3 바지인·턴](images/system-overview/14-journey-4-3-voice.png)

*소스: [`14-journey-4-3-voice.md`](diagrams/system-overview/14-journey-4-3-voice.md)*

#### 도식 ②: 시스템 (기존)

![스마트 바지인](images/system-overview/04-smart-barge-in.png)

*소스: [`04-smart-barge-in.md`](diagrams/system-overview/04-smart-barge-in.md)*

#### User story (절 맨 하단)

| ID | 페르소나 | 필요·동기 | 쓰는 기능 | 과정(요약) | 체감·결과 | 효과 |
|----|----------|------------|----------|------------|----------|------|
| US-4.3a | 고객 | TTS 중 **맞장구**와 **질문**을 다르게 | 스마트 바지인, 맞장구 패턴/LLM | TTS 중 발화 | 맞장구면 **말 이어감** | 대화감·만족 |
| US-4.3b | 운영 | **잡음·짤막 음**이 LLM에 안 감 | VAD, STT 후필터 | 노이즈·짤막 제거/무시 | LLM **호출·오답** 감소 | 비용·CS↓ |

---

<a id="44-langgraph"></a>

### 4.4 LangGraph (의도·라우팅)

**이 기능이 쓰이는 이유 (배경)**  
같은 **“말 한마디”**도 **“예약해 주세요”**는 **캘린더 도구**로, **“왜 끊기지?”**는 **락/FAQ·사과** 톤으로, **“사람”**은 **HITL·Transfer**로 가야 한다. **의도**를 **일관된 라벨**로 쪼개 **LangGraph(또는 그에 준하는)** 노드·가드에 **연결**하지 않으면, **RAG**와 **도구**가 **뒤섞여** **오답**·**이중 질의**·**로그** 해석이 어려워진다. **Outbound**(§4.8)는 **미션이 먼저** 주어질 수 있어 **의도 생략** 경로가 **허용**된다(구현·리포트).

**핵심 페르소나**  
- **고객**: **맥락에 맞는** 다음 행동(예약·지식·사람)을 **기대**한다.  
- **CS·데이터**: **intent**·**turn**·**툴 호출**이 **대시보드/로그**에 **읽을 수 있게** 남기길 원한다.

**의존·사용하는 능력**  
STT(또는 텍스트) → **classify_intent** 등 → **Persona**·**RAG**·`booking` **도구**·**HITL**·**Transfer**·(선택) **Outbound 스킵**.

**시간순 과정(요약)**  
1. **문장**·**컨텍스트**·**최근 턴**이 그래프에 들어감.  
2. **의도** 결정(또는 **신뢰도**로 HITL).  
3. **한 가지** 메인 루트(예: 예약)로 **도구/LLM**이 이어짐, **TTS/전환**으로 끝.

**이때 느끼는 경험·효과**  
“**딴소리**”·“**또 뭐죠?**” **감소**, **A/B**·**장애** 시 **의도 단위**로 **원인**을 좁힐 수 있다.

#### 도식 ①: Journey

![4.4 의도·라우팅](images/system-overview/15-journey-4-4-intent.png)

*소스: [`15-journey-4-4-intent.md`](diagrams/system-overview/15-journey-4-4-intent.md)*

#### 도식 ②: 시스템 (기존)

![의도 라우팅](images/system-overview/05-intent-routing.png)

*소스: [`05-intent-routing.md`](diagrams/system-overview/05-intent-routing.md)*

#### User story (절 맨 하단)

| ID | 페르소나 | 필요·동기 | 쓰는 기능 | 과정(요약) | 체감·결과 | 효과 |
|----|----------|------------|----------|------------|----------|------|
| US-4.4a | 고객 | “예약”·“감정”·“사람”이 **다르게** 처리 | classify_intent, 그래프 분기 | 발화 → 의도 | **기대**한 행동 | 만족·CS↓ |
| US-4.4b | 운영 | **로그**에 **같은 라벨** | intent·툴 이벤트 | 저장·집계 | **원인** 추적 | MTTR·분석 |

---

### 4.5 지식 베이스·HITL

**이 기능이 쓰이는 이유 (배경)**  
**테넌트별(§3.2)** **문서·Q&A**를 **RAG**로 쓰되, **톤·범위**는 **페르소나**로 맞추고, **유사 질**은 **캐시**로 **지연**을 줄인다. **그래도** **결제·의료** 등 **한 번에 틀리면 안 되는** 경우는 **HITL**로 **초안**을 **사람**이 보고, **format_hitl_reply** 등으로 **TTS**에 **자연스러운** 한국어(§3.3)로 내려보낸다.

**핵심 페르소나**  
- **고객·발신**: **“우리 회사 말투”**·**답할 수 있는 주제** 안에서 **듣는다**.  
- **상담·오퍼**: **짧은 텍스트**로 **수정/승인**하고, **고객**은 **전화**로 **들을 뿐**이다.

**의존·사용하는 능력**  
ChromaDB·owner 컬렉션, RAG, **HITL** WebSocket, `format_hitl_reply`, TTS.

**시간순 과정(요약)**  
1. 질문 → **RAG**·(선택) **캐시** → 답 **초안** 또는 HITL **요청**.  
2. HITL 시 **초록/노랑/빨강**·승인/거절(§2.1·대시보드).  
3. **승인** 문구 → TTS(§3.3 **복잡 루프**).

**이때 느끼는 경험·효과**  
**브랜드·정확**을 동시에 잡고, **민감** 구간은 **사람**이 **최종**한다.

#### 도식 ①: Journey

![4.5 지식·HITL](images/system-overview/16-journey-4-5-knowledge.png)

*소스: [`16-journey-4-5-knowledge.md`](diagrams/system-overview/16-journey-4-5-knowledge.md)*

#### 도식 ②: 시스템 (지식)

![지식 흐름](images/system-overview/06-knowledge-flow.png)

*소스: [`06-knowledge-flow.md`](diagrams/system-overview/06-knowledge-flow.md)*

#### 도식 ③: **복잡 루프** (§3.3과 동일)

![무응답·AI·HITL](images/system-overview/02-inbound-voice-sequence.png)

*소스: [`02-inbound-voice-sequence.md`](diagrams/system-overview/02-inbound-voice-sequence.md)*

#### User story (절 맨 하단)

| ID | 페르소나 | 필요·동기 | 쓰는 기능 | 과정(요약) | 체감·결과 | 효과 |
|----|----------|------------|----------|------------|----------|------|
| US-4.5a | 고객 | **우리** 톤·범위 | RAG, persona | 질문→답/인사 | **낯익은** 응답 | 신뢰·NPS |
| US-4.5b | 상담 | **짧게** 써 **고객**은 **듣기** | HITL, format_hitl_reply | 승인→TTS | **전화**로 일관 | 정확·효율 |

---

### 4.6 예약

**이 기능이 쓰이는 이유 (배경)**  
고객이 **IVR**·**콜백** 없이 **말(또는 문자)**로 **빈 슬롯**을 **찾고**·**잡고**·**취소/변경**하길 원한다. **LLM**만으로 **날짜·이중 예약**을 **정확히** 맞추기 어려워, **내부 DB·캘린더(설정) 도구 루프**로 **사실**을 **쿼리**한다. `booking_*` **이벤트**는 **CS**·**사후 분석**에 쓴다.

**핵심 페르소나**  
- **고객(소비 B2B 등)**: **빨리** 확정, **취소**도 쉬움.  
- **운영**: **예약 충돌**·**노쇼**를 **같은** 이벤트 스트림으로 **본다**.

**의존·사용하는 능력**  
**booking** 관련 **LangChain** 도구, SQLite/캘린더(구현), **알림 SMS**(설정).

**시간순 과정(요약)**  
1. “내일 3시” 등 → **슬롯 조회** → **없으면** 대안.  
2. **확정**·**캘린더** 반영(연동 시).  
3. **알림**·`booking_*` 로그.

**이때 느끼는 경험·효과**  
**수기**·**또 전화** **감소**, **누가 언제 뭐라고 했는지** **추적** 가능.

#### 도식 ①: Journey

![4.6 예약](images/system-overview/17-journey-4-6-booking.png)

*소스: [`17-journey-4-6-booking.md`](diagrams/system-overview/17-journey-4-6-booking.md)*

#### 도식 ②: 시스템 (기존)

![예약 도구](images/system-overview/07-booking-tools.png)

*소스: [`07-booking-tools.md`](diagrams/system-overview/07-booking-tools.md)*

#### User story (절 맨 하단)

| ID | 페르소나 | 필요·동기 | 쓰는 기능 | 과정(요약) | 체감·결과 | 효과 |
|----|----------|------------|----------|------------|----------|------|
| US-4.6a | 고객 | **말/문자**로 예약 | booking 도구, LLM | 요청→슬롯→확정 | **끊지** 않고 확정 | IVR·수기↓ |
| US-4.6b | 운영 | **이벤트**로 추적 | `booking_*` | 로그·CDR | **감사**·분석 | CS·품질 |

---

### 4.7 문자 (SIP MESSAGE)

**이 기능이 쓰이는 이유 (배경)**  
**같은 고객**이 **전화** 없이 **문자**로 **문의**할 때, **RTP**·**STT** 없이 **텍스트**로 **에이전트**에 **넣**으면 **지연**·**비용**이 **줄**고, **채널**을 **골랐다**는 **경험**이 유지된다. **SIP MESSAGE** **수신** 후 **텍스트 파이프라인**(의도·RAG)으로 가고, **응답**을 **또** 보낼 때 **무한 루프**를 막기 위한 **헤더**(구현)가 있다.

**핵심 페르소나**  
- **고객**: **시끄럽지** 않게, **쉬는** 중에 **짧게** 문의.  
- **웹 상담**: **통화** **후** **같은** **사건**·**쓰레드**로 **문자**를 **담**고 싶다.

**의존·사용하는 능력**  
SIP MESSAGE, 텍스트 에이전트, `X-PBX-Skip-AI-Reply` 등(구현·리포트).

**시간순 과정(요약)**  
1. **문자** **수신** → **STT 생략** → **의도/지식** 동일 **스택**.  
2. **답** **반송** 시 **루프** 방지 **플래그** 검토.  
3. (선택) **웹**과 **ID**·**콜** **연동**.

**이때 느끼는 경험·효과**  
**멀티채널** **일원화** **인상**, **채널마다** **또** **설명**하지 않는 **CS** **품질**.

#### 도식 ①: Journey

![4.7 문자](images/system-overview/18-journey-4-7-sms.png)

*소스: [`18-journey-4-7-sms.md`](diagrams/system-overview/18-journey-4-7-sms.md)*

#### 도식 ②: 시스템 (기존)

![SIP MESSAGE](images/system-overview/08-sip-message-sequence.png)

*소스: [`08-sip-message-sequence.md`](diagrams/system-overview/08-sip-message-sequence.md)*

#### User story (절 맨 하단)

| ID | 페르소나 | 필요·동기 | 쓰는 기능 | 과정(요약) | 체감·결과 | 효과 |
|----|----------|------------|----------|------------|----------|------|
| US-4.7a | 고객 | **전화 없이** **같은** AI | 메시지 파이프라인 | 수신→응답 | **채널** 선택 | 편의 |
| US-4.7b | 상담(웹) | **이력** **한 화면** | 사건/콜 **연동** | 조회 | **반복** 설명↓ | **처리** 시간↓ |

---

### 4.8 Outbound (발신 캠페인)

**이 기능이 쓰이는 이유 (배경)**  
**리마인드**·**회수**·**알림**을 **고객이 먼저** 걸게만 두지 않고, **서버/업무**가 **대기열**·**윈도**를 지키며 **전화**를 **건다**. 수신 측은 **곧 인입(§4.1)**과 **같은** **AI**·**착신 정책**(§4.10)을 **경험**할 수 있어 **채널** **일치**에 유리하다. **미션이** 먼저 **정해지면** **의도**를 **짧게** **우회**하는 **경로**가 있을 수 있다(리포트).

**핵심 페르소나**  
- **캠페인 담당**: **API/스케줄**로 **볼륨**·**재시도**·**최대 동시** **통제**.  
- **수신 고객**: “**누가 왜**” **전화**했는지 **같은** **브랜드** **음성**으로 **듣는다**.

**의존·사용하는 능력**  
`OutboundCallManager`·**대기열**·**상태**·(선택) **캘린더**·리포트.

**시간순 과정(요약)**  
1. **작업** **등록** (번호·**미션**·**슬롯**).  
2. **순서**·**한도**에 따라 **OUT** **INVITE**.  
3. **연결** 시 **인입** **동일** **파이프라인**(TTS/AI/사람).

**이때 느끼는 경험·효과**  
**no-show**·**미회신** **감소**, **콜센터** **선제** **부담** **이동**.

#### 도식 ①: Journey

![4.8 Outbound](images/system-overview/19-journey-4-8-outbound.png)

*소스: [`19-journey-4-8-outbound.md`](diagrams/system-overview/19-journey-4-8-outbound.md)*

#### 도식 ②: 시스템 (기존)

![Outbound](images/system-overview/11-outbound-campaign.png)

*소스: [`11-outbound-campaign.md`](diagrams/system-overview/11-outbound-campaign.md)*

#### User story (절 맨 하단)

| ID | 페르소나 | 필요·동기 | 쓰는 기능 | 과정(요약) | 체감·결과 | 효과 |
|----|----------|------------|----------|------------|----------|------|
| US-4.8a | 캠페인 | **서버**가 **먼저** 전화 | API·대기열 | 등록→발신 | **알림** **도달** | **이용률**·회수 |
| US-4.8b | 수신 고객 | **인입**과 **같은** AI(설정) | 동일 B2BUA·RTP | **받는** 쪽 | **혼란**↓ | **채널** **일치** |

---

### 4.9 연결음 (Ringback)

**이 기능이 쓰이는 이유 (배경)**  
**착신**까지 **잠시** 걸리는 동안 **아무 소리**도 없으면 **끊긴** 느낌이 난다. **얼리 미디어**·**TTS 인사**·**짧은 음원**(Suno 등)으로 “**연결 중**” **브랜딩**과 대기 **체감**을 완화한다. **200 OK**로 **인간**이 받거나 **AI**가 인수하는 **시점**에 **연결음**을 끊어 **이중 재생**이 없게 한다(§4.1·정책).

**핵심 페르소나**  
- **발신 고객**: **빈** **대기**보다 **음성**·**로고** **느낌**의 **짧은** **신호**.  
- **마케팅/운영**: **인사 TTS** + **음원** **믹스** (Suno 콜백 **공인 URL**·ngrok 등, 리포트).

**의존·사용하는 능력**  
2차 **INVITE**·**early media**·(선택) **Suno** 파이프·TTS.

**시간순 과정(요약)**  
1. **기다리는** **동안** **연결음** **스트림**.  
2. **200 OK** **또는** **AI** **투입** **확정** **시** **정지/페이드**.

**이때 느끼는 경험·효과**  
**이탈**·**“끊겼나?”** **민원** **감소** (톤·볼륨·트리거 **튜닝** 필요).

#### 도식 ①: Journey

![4.9 연결음](images/system-overview/20-journey-4-9-ringback.png)

*소스: [`20-journey-4-9-ringback.md`](diagrams/system-overview/20-journey-4-9-ringback.md)*

#### 도식 ②: 시스템 (기존)

![Ringback](images/system-overview/09-ringback-suno.png)

*소스: [`09-ringback-suno.md`](diagrams/system-overview/09-ringback-suno.md)*

**배포**: Suno 콜백은 **공인 URL** 필요(예: ngrok).

#### User story (절 맨 하단)

| ID | 페르소나 | 필요·동기 | 쓰는 기능 | 과정(요약) | 체감·결과 | 효과 |
|----|----------|------------|----------|------------|----------|------|
| US-4.9a | 발신 | **빈 느낌 방지** | early media, Ringback | 대기 | **가동 중**인 음성 | **이탈**↓ |
| US-4.9b | 운영 | **인사+음원** | TTS+Suno | 콘텐츠 **적재** | **브랜드** 톤 | **대기** 체감↓ |

---

### 4.10 착신 제어

**이 기능이 쓰이는 이유 (배경)**  
**같은 대표번호**라도 **식당**·**B2B**·**콜센터**마다 “곧 **사람**” vs “**N초 후 AI**” vs “**첫 응답 AI**”가 **다르다**. **시간**·**휴일**·**전달**·**링 그룹**을 **DB 규칙**으로 모델링해, **B2BUA/CallManager**가 **첫 벨**·**2차 INVITE**·**다음 단계**(§3.3) **결정**에 쓴다. **SIP 헌트** 동시/순차 **세부**는 **릴리스마다** **확인**(리포트).

**핵심 페르소나**  
- **IT/관리**: **업무**·**휴일**·**오버플로** **정책**을 **한곳**에 둔다.  
- **고객**: **기다릴지**·**AI**에 **맡길지**가 **조직**이 약속한 것과 **맞기**를 바란다.

**의존·사용하는 능력**  
**SQLite(등)** **규칙**, `direct` / `no_answer_ai` / `immediate_ai` / `forward_*` / `ring_group`, `AnnouncementProfile`·`greeting_override`.

**시간순 과정(요약)**  
1. 콜 **알림** 시 **규칙** **매칭**(시간·모델).  
2. **모델**에 따라 **즉시 인간**·**N초 후**·**AI**·**다른 대상** **벨**.  
3. (선택) **맞**는 **인사 TTS** **오버라이드**.

**이때 느끼는 경험·효과**  
야간·피크 **누락**이 줄고, **사전**에 **밝힌** **정책**과 **실제** 첫 **응답**이 **맞**으면 **기대 관리**에 **도움**이 된다.

#### 도식 ①: Journey

![4.10 착신 제어](images/system-overview/21-journey-4-10-callcontrol.png)

*소스: [`21-journey-4-10-callcontrol.md`](diagrams/system-overview/21-journey-4-10-callcontrol.md)*

#### 도식 ②: 시스템 (기존)

![착신 우선순위](images/system-overview/10-call-control-priority.png)

*소스: [`10-call-control-priority.md`](diagrams/system-overview/10-call-control-priority.md)*

> **주의**: 링 그룹 **SIP** 동시/순차는 제품·리포트 **최신** 본 뒤 배포.

| 모델 | 경험에 대응 |
|------|-------------|
| `direct` | 곧장 인간 |
| `no_answer_ai` | N초 **무응답** 후 AI |
| `immediate_ai` | 첫 응답 **AI** (이후 사람 가능) |
| `forward_*` / `ring_group` | **전달**·**헌트** |

`AnnouncementProfile` + `greeting_override`로 **같은 규칙**에 **맞는** 인사 TTS.

#### User story (절 맨 하단)

| ID | 페르소나 | 필요·동기 | 쓰는 기능 | 과정(요약) | 체감·결과 | 효과 |
|----|----------|------------|----------|------------|----------|------|
| US-4.10a | IT | **시간**·**휴**일마다 **다른** **동작** | DB **규칙**, 모델 | 적용 | **누락** **감소** | **24h**·**BCP** |
| US-4.10b | 고객 | **N초**·**AI** **정책** **투명** | no_answer/immediate | 대기 | **기대** **맞음** | **CS**·**이탈** |

---

## 5. 기술 스택

| 층 | 기술 |
|----|------|
| **런타임** | Python 3.11+, **asyncio** |
| **API** | **FastAPI**, structlog |
| **실시간** | **python-socketio** / aiohttp |
| **SIP/RTP** | 자체 B2BUA + RTP (코덱·SDP 조작) |
| **Voice 프레임워크** | **Pipecat** (VAD, STT/TTS 프레임, 파이프라인) |
| **에이전트** | **LangGraph** + **LangChain** tools, **checkpointer** (SQLite 권장 패키지) |
| **LLM/STT/TTS** | **Google Cloud** (Gemini, STT, TTS) |
| **벡터 DB** | **ChromaDB** + **sentence-transformers** 계열 임베딩 |
| **관계 DB** | **SQLite** (예약, 착신제어, 통화 기록 등) |
| **프론트** | **Next.js** (App Router), **TypeScript**, Tailwind, **Zustand** 등 |
| **통화음 생성** | **Suno API** (sunoapi.org), **pydub**/ffmpeg(디코딩) |

**외부 옵션**: **ngrok** (Suno·웹훅), **Google Calendar OAuth** (예약·캘린더), **SMS/RCS** 연동(리포트·`booking_notify`·`end_call_sms` 등).

---

## 부록

- **API·이벤트·CDR 상세 표** — 백업 문서 [`SYSTEM_OVERVIEW_2026-04-27_before_rewrite.md`](SYSTEM_OVERVIEW_2026-04-27_before_rewrite.md) §4, §5.
- **날짜별 구현/장애 기록** — `docs/reports/YYYY-MM/`.
- **설계 세부** — `docs/design/` (프로젝트에 있을 때).
- **다이어그램 자산** — PNG: `docs/images/system-overview/` · Mermaid 소스: `docs/diagrams/system-overview/` (재생성은 [README](diagrams/system-overview/README.md)).

---

*이 문서는 고수준 **아키텍처**와 **기능**을 한데 묶은 **시스템 개요**에 초점을 맞췄다. 경계 조건·플래그·엔드포인트·API 상세는 코드와 `docs/reports` 리포트를 병행한다.*
