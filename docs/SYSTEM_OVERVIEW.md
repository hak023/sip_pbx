# AI SIP PBX — 시스템 소개

**AI SIP PBX**는 Python 기반 **SIP B2BUA(Back-to-Back User Agent)** 위에 **실시간 음성 AI**, **웹 운영 콘솔**, **지식·연락처·문자·예약**을 한데 묶은 통합 플랫폼이다.

| 항목 | 내용 |
|------|------|
| **대상 독자** | 기획·운영·개발 온보딩, 아키텍처 이해가 필요한 이해관계자 |
| **최종 수정** | 2026-04-27 |
| **이전 문서 백업** | 상세 항목·API 표가 필요하면 [`SYSTEM_OVERVIEW_2026-04-27_before_rewrite.md`](SYSTEM_OVERVIEW_2026-04-27_before_rewrite.md) 참고 |

### 다이어그램 (PNG) — 다른 문서·슬라이드에서 재사용

렌더된 그림은 `docs/images/system-overview/` 에 있으며, 편집용 Mermaid 소스는 `docs/diagrams/system-overview/*.mmd` 이다. PNG는 **`mermaid-frontend.json` + `mermaid-frontend.css`** 로 생성해 **밝은 UI 톤·카드형 패널·넉넉한 노드 간격**을 맞춘다(상세·재생성: [diagrams/system-overview/README.md](diagrams/system-overview/README.md)).

| PNG | 절 | 소스(`.mmd`) |
|-----|----|--------------|
| [`01-logical-architecture.png`](images/system-overview/01-logical-architecture.png) | §3.1 | [`01-logical-architecture.mmd`](diagrams/system-overview/01-logical-architecture.mmd) |
| [`02-inbound-voice-sequence.png`](images/system-overview/02-inbound-voice-sequence.png) | §3.4 | [`02-inbound-voice-sequence.mmd`](diagrams/system-overview/02-inbound-voice-sequence.mmd) |
| [`03-rtp-modes.png`](images/system-overview/03-rtp-modes.png) | §4.2 | [`03-rtp-modes.mmd`](diagrams/system-overview/03-rtp-modes.mmd) |
| [`04-smart-barge-in.png`](images/system-overview/04-smart-barge-in.png) | §4.3 | [`04-smart-barge-in.mmd`](diagrams/system-overview/04-smart-barge-in.mmd) |
| [`05-intent-routing.png`](images/system-overview/05-intent-routing.png) | §4.4 | [`05-intent-routing.mmd`](diagrams/system-overview/05-intent-routing.mmd) |
| [`06-knowledge-flow.png`](images/system-overview/06-knowledge-flow.png) | §4.5 | [`06-knowledge-flow.mmd`](diagrams/system-overview/06-knowledge-flow.mmd) |
| [`07-booking-tools.png`](images/system-overview/07-booking-tools.png) | §4.6 | [`07-booking-tools.mmd`](diagrams/system-overview/07-booking-tools.mmd) |
| [`08-sip-message-sequence.png`](images/system-overview/08-sip-message-sequence.png) | §4.7 | [`08-sip-message-sequence.mmd`](diagrams/system-overview/08-sip-message-sequence.mmd) |
| [`09-ringback-suno.png`](images/system-overview/09-ringback-suno.png) | §4.9 | [`09-ringback-suno.mmd`](diagrams/system-overview/09-ringback-suno.mmd) |
| [`10-call-control-priority.png`](images/system-overview/10-call-control-priority.png) | §4.10 | [`10-call-control-priority.mmd`](diagrams/system-overview/10-call-control-priority.mmd) |

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

*편집·재렌더: [`diagrams/system-overview/01-logical-architecture.mmd`](diagrams/system-overview/01-logical-architecture.mmd)*

### 3.2 런타임·포트 (개발 기준)

| 경로 | 역할 |
|------|------|
| **SIP** | 일반적으로 UDP **5060** (설정에 따름) |
| **RTP** | **포트 풀** (예: 10000–20000) — 레그·방향별 할당 |
| **REST** | **8000** — 인증, 통화이력, 지식, 착신 제어, 링백, 예약 등 |
| **실시간** | **8001** — STT/TTS/통화 이벤트, HITL, CDR 트레이스 |
| **프론트** | **3000** — 대시보드, 설정(착신/링백/페르소나/연락처 등) |

### 3.3 데이터·테넌트

- **테넌트**는 대개 **착신 내선(SIP user)** 기준(`owner`)으로 식별한다.
- **ChromaDB**에 `knowledge` / `qa_cache` / `persona` 등 **owner별 컬렉션**으로 격리한다.
- **SQLite**에 예약(`booking` DB), **착신 제어**(`call_control` DB), 통화/연락처 관련 기록 등을 둔다(마이그레이션·경로는 배포마다 `config`/`env` 확인).

### 3.4 주요 제어 루프 (인입 음성)

![인입 음성: INVITE ~ 일반 응답 vs AI 경로](images/system-overview/02-inbound-voice-sequence.png)

*편집·재렌더: [`diagrams/system-overview/02-inbound-voice-sequence.mmd`](diagrams/system-overview/02-inbound-voice-sequence.mmd)*

---

## 4. 핵심 기능

### 4.1 SIP PBX 처리

**역할**: RFC 3261에 가까운 **B2BUA**로, 발신·착신 레그를 **독립** 관리하며 `INVITE`/`ACK`/`BYE`/`CANCEL`/`REGISTER`/`OPTIONS` 등을 처리한다.

**흐름 (요지)**:

1. `INVITE` 수신 → SDP 파싱, **미디어 세션·포트** 할당.
2. 착신 측에 **2차 INVITE** — 링/조기미디어(early media) 경로는 **통화 연결음**과 결합될 수 있다(§4.9).
3. **미디어 모드**에 따라 `Direct` / `Bypass·Reflecting` / **AI** 경로로 분기.
4. **호전환·아웃바운드**는 `CallManager` / `TransferManager` / `OutboundCallManager` 등과 연동.

**장점 (요약)**: 한 프로세스에서 **시그널링 + RTP + AI**를 엮을 수 있어, 단순 SBC만으로는 어려운 **AI 인수·재개** 시나리오를 코드 레벨에서 제어한다.

---

### 4.2 RTP 처리 (케이스별)

**사용자 간 릴레이 (Bypass)**: 상담원·내선이 응답한 **인간–인간 통화**는 **초저지연** 양방향 릴레이를 목표로 한다.

**AI 응대 모드**: TTS·STT 쪽으로 붙는 구간은 **지속적인 RTP 타이밍**이 중요하다. **20ms 격자**로 PCM을 밀어 넣고, 큐가 비면 **무음 프레임**을 넣어 디코더가 끊기지 않게 설계한다(연속 silence).

| 모드(개념) | 설명 |
|------------|------|
| **Bypass** | 정상 상담 연결 후 양자 릴레이 |
| **AI** | 봇 음성/수신 STT — **TTS·PCM 큐**와 **전송 스레드** |
| **Bridge** | 호전환 후 **새 대상**과의 미디어 브릿지 |

![RTP: 인간–인간 Bypass vs AI 레그](images/system-overview/03-rtp-modes.png)

*편집·재렌더: [`diagrams/system-overview/03-rtp-modes.mmd`](diagrams/system-overview/03-rtp-modes.mmd)*

**에코/품질**: **AEC(에코 캔슬레이션)** 경로를 두고, STT 쪽에는 **후처리 필터**로 짧은 발화·에코성 잔여를 걸러 LLM에 넘길지 판단한다(§4.3).

---

### 4.3 AI 음성 — Voice Agent 파이프라인

**구성(개념)**: `SIPPBX` 트랜스포트 → (녹음) → **VAD** → **STT** → **RAG+LLM** → **TTS** → (녹음) → 송신.

| 요소 | 구현·역할 (코드베이스 기준) |
|------|---------------------------|
| **VAD** | 음성 구간 감지 — **무음/발화** 구간을 STT·턴 타이밍에 사용 |
| **Endpointing(실질)** | **STT 최종 결과** + **VAD/후처리**로 “이번 턴 끝”에 가깝게 처리(제품에 따라 **고정 m/s 엔드포인터**는 별도 모듈명으로 두지 않을 수 있음) |
| **Turn-taking** | `MinWordsUserTurnStartStrategy` 등 — **최소 N어절** 이후 사용자 턴으로 간주 |
| **Barge-in** | TTS 중 사용자 발화 시 **interruption** — **스마트 바지인**으로 단계화(아래 시퀀스) |
| **Backchannel(맞장구)** | **짧은 수긍(“네”, “음” 등)** 은 `BACKCHANNEL_PATTERNS` + **LLM 판별**로 **끼어들기와 구분** (`barge_in_strategy.py`) |
| **노이즈/품질** | **전용 RNNoise 같은 별도 노드**가 항상 있는 것은 아니고, **STT Telephony 모델·AEC·STT Post Filter**로 실질적 품질을 맞춘다 |

**스마트 Barge-in (3단계, 요지)**:

![스마트 Barge-in: 키워드 → 단어 수 → LLM 맞장구/끼어들기](images/system-overview/04-smart-barge-in.png)

*편집·재렌더: [`diagrams/system-overview/04-smart-barge-in.mmd`](diagrams/system-overview/04-smart-barge-in.mmd)*

---

### 4.4 LangGraph 대화 에이전트 (의도·경로)

**역할**: 발화(텍스트)에 대해 **의도**를 정하고, **RAG / 페르소나 / 예약 / HITL** 등으로 **라우팅**한다.

- **의도 집합**은 `greeting` … `booking` … `nlu_fallback` 등 **고정 택소노미** + **예약 휴리스틱 병합**(`booking_intent_heuristic`)로 보강된다.
- **복합 발화**는 **접속사 뒤 핵심 절** 추출(`_extract_main_clause`)로 앞뒤 잡담을 줄이고 **질문 본질**에 집중한다.
- **아웃바운드**는 `outbound_purpose` 등이 있을 때 **분류를 스킵**하고 **미션 응답** 경로로 간다(구현은 `classify_intent` 등 참고).

**단순 의도 → 처리 경로(개략)**:

![의도 분류 → Persona / RAG / booking / Transfer / HITL](images/system-overview/05-intent-routing.png)

*편집·재렌더: [`diagrams/system-overview/05-intent-routing.mmd`](diagrams/system-overview/05-intent-routing.mmd)*

---

### 4.5 지식 베이스

| 구성요소 | 설명 |
|----------|------|
| **자동 적재** | 통화·추출 파이프라인으로 **Q&A/요약**을 ChromaDB에 **upsert** (품질 게이트·유사도 중복 정책) |
| **시맨틱 캐시** | `qa_cache` — **유사 질문**이면 LLM·RAG를 생략 |
| **페르소나** | 업무 범위·톤·**scope 키워드**·유사도로 **chitchat vs question** 가름 |
| **CID·연락처** | `GET /api/call-history/caller-context` 등으로 **직전 인입** 맥락을 UI에 표시, **연락처 트UI·콜 독**과 연동(단계적 확장) |
| **답을 못할 때** | **신뢰도/정책**에 따라 **HITL**(운영자 텍스트 → 정제 → TTS) 또는 **에스컬레이션 모드**에 따라 **내선 호전환** (페르소나 `escalation_mode`) |

![지식: 분류 → RAG·페르소나·캐시 → 응답·에스컬레이션](images/system-overview/06-knowledge-flow.png)

*편집·재렌더: [`diagrams/system-overview/06-knowledge-flow.mmd`](diagrams/system-overview/06-knowledge-flow.mmd)*

---

### 4.6 Tool 처리 — 예약 (slot, 조회/변경/취소)

**DB**: `booking` 관련 테이블 — **슬롯**(`booking_slots`), **예약**(`bookings`), **테넌트 설정**(`booking_settings`), **도메인 필드**(`booking_schema_fields`) 등.

**런타임**: `booking_agent` 노드에서 **LLM + bind_tools**로 루프 — `check_available_slots` → `create_booking` / `search_my_bookings` → `update`·`cancel` / **예약 SMS** tool 등(버전·이름은 `booking_tools` 및 리포트 참고).

**흐름(개략)**:

![예약: 휴리스틱 → LLM+도구 루프 → DB·TTS·SMS](images/system-overview/07-booking-tools.png)

*편집·재렌더: [`diagrams/system-overview/07-booking-tools.mmd`](diagrams/system-overview/07-booking-tools.mmd)*

**음성 전용 보조**: `booking_intent_heuristic`으로 **STT가 booking으로 잘 못 잡는 경우**를 줄이고, CDR에 **`booking_*` 이벤트**를 남겨 사후 분석한다.

---

### 4.7 문자 메시지 처리 (SIP MESSAGE, SMS/RCS, 웹)

- **SIP MESSAGE** 수신 시 — 설정(`chat_relay_settings` 등)이 켜져 있으면 **동일 LangGraph 에이전트**로 **텍스트만** 응답 (`sip_message_ai_reply.py`). STT/TTS/RTP는 타지 않는다.
- **재진입 방지**: PBX가 보내는 자동 응답에 **`X-PBX-Skip-AI-Reply`** 를 붙여 **무한 루프**를 막는다.
- **웹**: 채팅·**연락처·콜 독**·**미해결 통화** 화면과 연결해 **상담 후속 문자**를 보낼 수 있게 구성(세부는 `end_call_sms`·`chat_relay` 등).

![SIP MESSAGE → 설정 확인 → Text Agent → 응답](images/system-overview/08-sip-message-sequence.png)

*편집·재렌더: [`diagrams/system-overview/08-sip-message-sequence.mmd`](diagrams/system-overview/08-sip-message-sequence.mmd)*

---

### 4.8 AI 자동 발신 (Outbound)

**`OutboundCallManager`**: 웹·API로 요청된 **AI 발신**을 **대기열**에 넣고, `INVITE` → **응답 시 AI 파이프라인** → **최대 통화시간/재시도**를 관리한다.

- **상태** 예: `pending` → `calling` → `answered` → `completed` / `failed` (구현·필드는 모델 참고).
- **에코/미션** 시나리오는 인바운드와 다른 STT/억제 정책이 있을 수 있어 **outbound 전용** 분기·로그를 둔다(리포트 `OUTBOUND_*` 참고).

---

### 4.9 통화 연결음 (Ringback) — Suno + LLM

**타이밍**: 착신이 응답해 **200 OK** 하기 **전** — **early media** 구간에 발신자에게 **인사 TTS** + **연결음(음원)** 을 **RTP**로 흘린다.

**음원 생성 (Suno)** — `ringback_service.py` 요지:

1. (선택) **LLM**이 **가사·스타일** 태그를 생성 — **페르소나/설정**을 참고할 수 있음.
2. **Suno API** `generate` → **`callBackUrl`** 로 완료 **콜백**(공인 HTTPS·ngrok 등 필요).
3. **MP3** 캐시·로컬 저장 후 **RingbackPlayer**가 **PCM 16k**로 변환·루프.
4. **200 OK** 또는 **AI가 통화를 인수**하면 **정지**한다.

![통화 연결음: LLM → Suno → 콜백·캐시 → RingbackPlayer → early RTP](images/system-overview/09-ringback-suno.png)

*편집·재렌더: [`diagrams/system-overview/09-ringback-suno.mmd`](diagrams/system-overview/09-ringback-suno.mmd)*

**운영 주의**: Suno 콜백은 **localhost가 아닌 공인 URL**이어야 하므로, 로컬 개발 시 **ngrok**·`ringback` 설정을 함께 둔다.

---

### 4.10 착신 제어 (AI 자동응답, 그룹·대표번호 성격)

**저장**: SQLite **`call_control.db`** (경로는 환경으로 바뀔 수 있음) — `RoutingRule`, `Schedule`, `AnnouncementProfile`, **착신 그룹**·**전달 대상** 등.

**평가 순서(요지)**: `sip_endpoint` 인입에서 **발신자 필터** → **스케줄+규칙** → **기존 operator/away 폴백** 등(상세는 `call_control` 리포트).

| 동작(모델) | 의미 (사용자 관점) |
|------------|-------------------|
| `direct` | A→B 직접 연결 |
| `no_answer_ai` | N초 **무응답** 후 **AI** |
| `immediate_ai` | **항상** AI 먼저(착신자는 정책에 따라) |
| `forward_*` / `ring_group` | **착신전환** 또는 **다중 내선(동시/순차 링)** — “대표번호/헌트”에 가까운 운용 |

![착신 제어: 필터 → 스케줄·규칙 → 폴백 → 동작 모드](images/system-overview/10-call-control-priority.png)

*편집·재렌더: [`diagrams/system-overview/10-call-control-priority.mmd`](diagrams/system-overview/10-call-control-priority.mmd)*

> **주의**: **링 그룹**의 **SIP 동시/순차 링**은 모델·API와 함께 **지속 구현**되는 영역이 있다(배포마다 `docs/reports`의 최신 착신 제어 리포트 확인).

**안내멘트**: 규칙에 연결된 `AnnouncementProfile` 텍스트는 **초기 인사 TTS**에 **`greeting_override`** 로 주입된다.

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

*이 문서는 읽기 쉬운 **소개·온보딩**에 초점을 맞췄다. 경계 조건·플래그·정확한 엔드포인트는 코드와 리포트를 함께 본다.*
