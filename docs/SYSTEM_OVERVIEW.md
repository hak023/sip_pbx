# AI SIP PBX 시스템 개요

**AI SIP PBX**는 Python 기반의 **B2BUA(Back-to-Back User Agent)** 통신 시스템으로,
**AI 음성 비서**, **실시간 운영자 대시보드**, **지식 자동 축적**을 통합한 차세대 통신 플랫폼이다.

**최종 수정**: 2026-03-30

---

## 1. 시스템 개요

### 1.0 배경 및 목표

**배경: 기존 AI 응대 CallBot의 한계**

- 인위적인 시나리오 구축에 따른 초기 투자 비용으로 **무거운 구축형 시스템**에 의존하는 경우가 많다.
- Call Server ARS의 **경직된 Tree 구조**로 사용자와 관리자 모두 활용 범위가 제한된다.
- **고정된 답변(문제은행 형태)** 위주로 응답 범위가 좁고 유연하지 않다.

**목표: Agentic AI 차세대 AICC 솔루션**

- 기존 시나리오 기반 챗봇·콜봇의 한계를 넘어 **스스로 학습하고 행동하는(Agentic)** 차세대 AI 컨택센터(AICC) 솔루션을 지향한다.
- 상담 이력의 **실시간 자산화(Active RAG)**와 **인간–AI 협업 루프(HITL)**로 시간이 지날수록 운영 비용이 줄고 지능이 높아지는 **Zero Marginal Cost** 모델을 추구한다.
- **자율형 AI 콜봇(Agentic AI CallBot)**을 SIP B2BUA·RAG·음성 파이프라인과 결합해 구현한다.

**기존 시스템 vs 제안 시스템 비교**

| 구분 | 기존 시스템 (As-Is) | 제안 시스템 (To-Be) |
|---|---|---|
| 지식 구축 | 수개월의 시나리오 및 답변셋 구축 공수 발생 | 통화 이력 기반 자동 생성(Auto-Gen) 및 즉시 반영 |
| ARS 구조 | 고정된 트리(Tree) 구조의 낮은 유연성 | 목적 지향형 AI Agent의 유연한 의도 파악 |
| 응대 품질 | Rule-based 기반의 단편적 문장 매칭 | LLM 기반 추론(Reasoning) 및 해결(Action) |
| 음성 경험 | 기계적 TTS 및 높은 지연 시간(Latency) | Natural Voice 기반의 인간 수준 대화 체감 |
| 비즈니스 민첩성 | 스크립트 변경 시 시스템 재설계 필요 | VectorDB 연동을 통한 실시간 지식 최신화 |

### 1.1 핵심 가치

| 가치 | 설명 |
|---|---|
| **완전한 SIP B2BUA** | 표준 SIP 프로토콜 완벽 지원 (INVITE, BYE, ACK, CANCEL, REGISTER, OPTIONS) |
| **지능형 AI 응대** | 부재중/영업시간 외 자동 응답, RAG 기반 지식 검색, 17가지 의도 분류 |
| **Human-in-the-Loop** | AI 신뢰도 부족 시 운영자에게 실시간 질문 전달, 답변 즉시 TTS 송출 |
| **실시간 웹 제어** | WebSocket 기반 통화 모니터링, STT/TTS 실시간 확인, 호 전환 |
| **지식 자동 축적** | 통화 후 자동 지식 추출, 시맨틱 캐시, 지식베이스 자동 성장 |
| **비용 효율** | Gemini 2.5 Flash 기반 초저비용 운영 (월 100통화 약 ₩6,400) |

### 1.2 전체 아키텍처

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        AI SIP PBX 통합 시스템                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌──────────────┐     ┌───────────────────┐     ┌───────────────────┐   │
│  │  SIP Callers  │◄───►│  SIP/RTP Engine    │◄───►│  AI Orchestrator  │   │
│  │  (전화 사용자) │     │  (Python asyncio)  │     │  (Pipecat Pipeline│   │
│  │              │     │                   │     │   + LangGraph)    │   │
│  │  SIP:5060    │     │  ├─ B2BUA Core    │     │                   │   │
│  │  RTP:10000+  │     │  ├─ RTP Relay     │     │  ├─ STT (Google)  │   │
│  └──────────────┘     │  ├─ Call Manager  │     │  ├─ LLM (Gemini)  │   │
│                       │  └─ Port Pool     │     │  ├─ RAG (Chroma)  │   │
│                       └─────────┬─────────┘     │  ├─ TTS (Google)  │   │
│                                 │               │  ├─ HITL Service  │   │
│                                 │               │  └─ VAD/Barge-in  │   │
│                       ┌─────────┴─────────┐     └───────────────────┘   │
│                       │  API & WebSocket   │               │            │
│                       │  ├─ REST  :8000    │               │            │
│                       │  └─ WS    :8001    │     ┌─────────┴─────────┐  │
│                       └─────────┬─────────┘     │  ChromaDB         │  │
│                                 │               │  (지식/캐시/페르소나│  │
│                       ┌─────────┴─────────┐     └───────────────────┘  │
│                       │  Web Dashboard     │                            │
│                       │  (Next.js 14)      │                            │
│                       │  :3000             │                            │
│                       └───────────────────┘                            │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.3 3계층 아키텍처

| 계층 | 역할 | 핵심 컴포넌트 |
|---|---|---|
| **Layer 1: SIP PBX Core** | 통신 기반 | SIP B2BUA, RTP Relay, Call Manager, Port Pool |
| **Layer 2: AI Voice Assistant** | 지능 확장 | STT, TTS, LLM, RAG, HITL, Barge-in, 호 전환 |
| **Layer 3: API & Frontend** | 연동·제어 | FastAPI REST, Socket.IO, Next.js 대시보드 |

---

## 2. 주요 기능 상세

### 2.1 SIP B2BUA 엔진

**기능**: 표준 SIP 프로토콜을 완벽히 지원하는 Back-to-Back User Agent

**유저 스토리**: 사용자가 전화를 걸면 PBX가 양쪽 레그를 독립적으로 관리하며,
착신자 미응답 시 자동으로 AI 모드로 전환한다.

**동작 로직**:
```
발신자 INVITE → SIPEndpoint 수신
    │
    ├─ SDP 파싱 + 미디어 세션 생성
    │   └─ MediaSessionManager: 8포트 할당 (RTP/RTCP × 2레그)
    │
    ├─ 착신자에게 2nd INVITE 전송 (B2BUA)
    │   └─ 180 Ringing → 발신자에게 전달
    │
    ├─ 착신자 200 OK → RTP 릴레이 시작 (Bypass 모드, <5ms)
    │
    └─ 착신자 무응답 (no_answer_timeout) → AI 모드 전환
        └─ run_ai_voice_pipeline() 호출
```

**기능적 장점**:
- 양쪽 레그(Caller/Callee) 완전 독립 관리
- SDP 협상으로 코덱 자동 조정
- Transaction 상태 기계로 SIP 신뢰성 보장
- 단일 Python 프로세스에서 시그널링 + 미디어 + AI 통합 관리

**지원 SIP 메서드**: INVITE, ACK, BYE, CANCEL, REGISTER, OPTIONS

### 2.2 RTP 미디어 릴레이

**기능**: 실시간 RTP 패킷 중계 및 AI 오디오 삽입

**유저 스토리**: 일반 통화는 초저지연(<5ms) 릴레이, AI 통화는 TTS 오디오를
끊김 없이 20ms 격자로 전송한다.

**동작 모드**:

| 모드 | 용도 | 지연 |
|---|---|---|
| **Bypass** | 일반 통화 (직접 중계) | <5ms |
| **AI** | AI 음성봇 응대 | 20ms 격자 |
| **Bridge** | 호 전환 후 상담원 연결 | <5ms |

**AI 모드 핵심 설계 — Continuous Silence**:
```
시간축: ───────────────────────────────────────►
        [silence][silence][media][media][silence]...
         20ms     20ms    20ms   20ms   20ms
```
- 미디어 유무와 관계없이 **항상 20ms 간격으로 패킷 전송**
- 전용 스레드(`_pcm_sender_thread_main`)가 PCM 큐에서 프레임 소비
- PCM 큐 비어있으면 무음(640 bytes) 전송 → RTP 스트림 끊김 없음
- 세션 종료 시 잔여 오디오 완전 드레인(최대 20초) 후 스레드 종료

**기능적 장점**:
- 연속 무음으로 수신측 디코더 안정화 (오디오 늘어짐/끊김 방지)
- UDP 큐(`_tts_udp_out_queue`)로 Windows Proactor 이벤트 루프 보호
- PCM 큐 maxsize=1000 (~31초 버퍼)으로 TTS 버스트 흡수
- AEC(음향 에코 제거) 통합

### 2.3 AI 음성봇 (Pipecat Pipeline)

**기능**: 실시간 음성 대화 파이프라인 (STT → NLU → RAG → LLM → TTS)

**유저 스토리**: 착신자가 부재중이면 AI 봇이 자동으로 전화를 받아
자연스러운 한국어로 대화하며, 지식베이스를 기반으로 정확한 정보를 안내한다.

**파이프라인 체인**:
```
RTP 수신 오디오
  → SIPPBXInputTransport (16kHz PCM 변환)
    → RecordingProcessor (입력 녹음)
      → VADWrapperProcessor (음성 활동 감지 + Barge-in)
        → GoogleSTTService (한국어 음성→텍스트)
          → RAGLLMProcessor (대화 처리 핵심)
            → KoreanTTSNumberProcessor (숫자 정규화: "3월" → "삼월")
              → DebugGoogleTTSService (텍스트→음성, 일괄 수집)
                → TTSCompleteNotifier (TTS 완료 알림)
                  → RecordingProcessor (출력 녹음)
                    → SIPPBXOutputTransport (RTP 전송)
```

**Barge-in (사용자 끼어들기)**:
- 최소 3단어 이상 발화 시 AI 응답 중단
- `allow_interruptions=True` 설정
- Output Transport에서 interruption 프레임 흡수

**기능적 장점**:
- Pipecat 프레임워크 기반으로 프로세서 교체/추가 용이
- VAD → STT → NLU → TTS 전체 파이프라인이 비동기로 동작
- 초기 인사 0.5초 지연으로 오디오 루프 안정화 후 전송
- 파이프라인 종료 시 각 프로세서 cleanup으로 리소스 누수 방지

### 2.4 LangGraph 대화 에이전트

**기능**: 사용자 의도를 분류하고 최적의 응답 경로를 선택하는 그래프 기반 대화 시스템

**유저 스토리**: 사용자가 "오늘 날씨 알려줘"라고 하면 의도를 `question`으로 분류하고,
시맨틱 캐시 → RAG 검색 → LLM 응답 생성 → HITL 판단 순으로 처리한다.

**의도 분류 (5단계 파이프라인)**:
```
사용자 발화
  → [1] 키워드 매칭 (confidence=1.0) — "감사합니다"→farewell
  → [2] 특수 규칙 — 인사+질문 패턴 → question
  → [3] 페르소나 기반 — 업무 무관 → chitchat
  → [4] 기본 폴백 — 짧은 발화 → question (confidence=0.7)
  → [5] LLM 병합 호출 — intent + search_query 동시 생성 (1회 LLM)
```

**17가지 의도** (참고 목록):
`greeting`, `farewell`, `affirm`, `deny`, `gratitude`, `doubt`,
`positive_reaction`, `negative_reaction`, `chitchat`, `repeat`,
`clarification`, `help`, `question`, `complaint`, `transfer`,
`out_of_scope`, `nlu_fallback`

**17개 의도 분류 및 처리 경로 상세**

| 그룹 | 의도 | 처리 방식 | LLM 호출 | 지식베이스 활용 |
|---|---|---|---|---|
| **A: 즉시 응답** | greeting | ChromaDB persona 컬렉션에서 인사말 조회 | 0회 | persona KB |
| **A: 즉시 응답** | farewell | ChromaDB에서 작별 인사 조회 | 0회 | persona KB |
| **B: 템플릿** | affirm, deny, gratitude, doubt, positive_reaction, negative_reaction, repeat | 고정 템플릿 랜덤 선택 또는 마지막 발화 재생 | 0회 | 없음 |
| **C: 소셜** | chitchat | 페르소나 임베딩 유사도 < 0.6 → 페르소나 템플릿 응답 | 0~1회 | persona KB |
| **D: 지식 검색** | question, complaint, clarification, help | 시맨틱 캐시 → RAG 검색 → LLM → HITL 판단 | 1~2회 | qa_cache + knowledge KB |
| **E: 특수 처리** | transfer | 호 전환 로직 실행 (TransferManager) | 0회 | 없음 |
| **F: 범위 외** | out_of_scope | 페르소나 기반 범위 외 응답 | 0~1회 | persona KB |
| **G: 폴백** | nlu_fallback | HITL 에스컬레이션 또는 모름 응답 | 1회 | 없음 |

**지식베이스(ChromaDB) 활용 경로**

```
사용자 발화
  → [의도 분류]
      ├─ greeting/farewell → persona 컬렉션 직접 조회 (0ms)
      ├─ chitchat/out_of_scope → persona 컬렉션 템플릿 조회
      ├─ question/complaint/help/clarification
      │     → qa_cache 컬렉션 시맨틱 검색 (유사도≥0.85 → 즉시 응답)
      │     → knowledge 컬렉션 RAG 검색 (top 3 문서)
      │     → LLM에 RAG 컨텍스트 주입 → 응답 생성
      │     → confidence < 0.3 → HITL 에스컬레이션
      │     → HITL 답변 → knowledge 컬렉션 자동 저장 (학습)
      └─ nlu_fallback → HITL 에스컬레이션
```

**응답 경로 요약**

| 의도 | 처리 | LLM 호출 |
|---|---|---|
| greeting / farewell | ChromaDB persona에서 직접 인사·작별 조회 | 0회 (~0.01초) |
| affirm, deny 등 B그룹 | 고정 템플릿 랜덤 선택 | 0회 |
| repeat | 마지막 AI 발화 재생 | 0회 |
| chitchat | 페르소나 템플릿(유사도 기준) 또는 LLM | 0~1회 |
| question, complaint, clarification, help | 캐시 → RAG → LLM → HITL | 1~2회 |
| transfer | TransferManager 호 전환 | 0회 |
| out_of_scope | 페르소나 기반 범위 외 | 0~1회 |
| nlu_fallback | HITL 또는 모름 응답 | 1회 |

**기능적 장점**:
- 그래프 컴파일 캐시로 ~7초 재컴파일 방지
- classify_intent + rewrite_query 병합으로 LLM 호출 1회 절감 (~0.5초)
- greeting/farewell KB 직접 조회로 인사말 즉시 응답
- 시맨틱 캐시(유사도 ≥ 0.85)로 동일 질문 즉시 응답

### 2.5 RAG (검색 증강 생성)

**기능**: ChromaDB 벡터 데이터베이스에서 관련 지식을 검색하여 LLM에 컨텍스트로 제공

**유저 스토리**: "기상감정서 발급법"을 물어보면 ChromaDB에서 관련 문서를 검색하고,
해당 정보를 LLM에 전달하여 정확한 답변을 생성한다.

**검색 파이프라인**:
```
사용자 쿼리
  → TextEmbedder (384차원 벡터 변환)
    → ChromaDB vector search (owner + category 필터, top 10)
      → Score 계산: 1/(1+distance)
        → 2-pass 검색 (원문 + rewrite 결과 병합)
          → Small-to-Big Expansion (문장→상위 문맥 확장)
            → Contextual Compression (키워드 매칭, 최대 1200자)
              → Top 3 결과 → LLM 컨텍스트로 전달
```

**Confidence 산출**: `(top_score × 0.7 + avg_score × 0.3) × 1.1`
- Top score에 70% 가중치 → 단일 고품질 문서 발견 시 신뢰도 반영

**기능적 장점**:
- 카테고리 기반 필터(`weather`, `disaster`, `faq` 등)로 검색 정밀도 향상
- 문장 레벨 검색 + 상위 문맥 확장으로 세밀하면서도 풍부한 컨텍스트
- Contextual Compression으로 LLM 입력 토큰 절감

### 2.6 HITL (Human-in-the-Loop)

**기능**: AI 신뢰도가 낮은 질문을 운영자에게 실시간 전달하고, 답변을 TTS로 송출

**유저 스토리**: AI가 "김 대리님 미팅 가능 시간"에 대해 확신이 없으면
운영자에게 WebSocket으로 질문을 전달하고, 운영자 답변을 자연스럽게 변환하여
고객에게 음성으로 안내한다.

**동작 흐름**:
```
LangGraph hitl_alert 노드
  │ (confidence < 0.3 또는 needs_follow_up)
  ▼
RAGLLMProcessor → WebSocket emit_hitl_requested
  │                     └─► 운영자 대시보드 알림
  │
  ├─ 고객에게 대기 멘트: "잠시만 확인중이니 기다려 주세요"
  │
  │ (운영자 답변 대기)
  ▼
_hitl_response_queue ◄── 운영자 API 응답
  │
  ├─ LLM format_hitl_reply_for_customer() — 운영자 텍스트를 자연어로 정제
  │
  ├─ STT 무입력 상태 확인 후 TTS 송출 (겹침 방지)
  │
  └─ 자동 지식베이스 저장 (선택)
```

**HITL 면제 의도**: `greeting`, `chitchat`, `out_of_scope`

**타임아웃 처리**:
- 운영자 무응답 → 설정된 timeout_message TTS 송출
- 운영자 자리 비움(away) → away_message 즉시 송출

**기능적 장점**:
- AI가 먼저 응답 시도 후 신뢰도 부족 시에만 운영자 개입 → 운영자 부담 최소화
- 운영자 답변을 LLM으로 자연스럽게 정제 후 TTS → 고객 체감 품질 향상
- 답변을 지식베이스에 저장하면 동일 질문 재발 시 AI가 직접 응답 가능 → 학습 효과

### 2.7 호 전환 (Call Transfer)

**기능**: AI 응대 중 사용자 요청 또는 운영자 수동 조작으로 상담원/담당자에게 통화를 전환

**유저 스토리**: 고객이 "기상청 담당부서 연결해줘"라고 하면 AI가 안내 멘트를 송출하고,
담당 번호로 전화를 걸어 연결한 후, RTP를 브릿지 모드로 전환한다.

**동작 흐름**:
```
[AI 의도 감지: transfer 또는 운영자 수동 전환]
  │
  ├─ TransferManager.initiate_transfer()
  │
  ├─ 안내 멘트 TTS: "담당자 연결 중입니다. 잠시만 기다려 주세요."
  │
  ├─ 대상에게 INVITE 전송 (새 transfer-leg Call-ID)
  │   └─ ring_timeout 내 200 OK 대기
  │
  ├─ 대상 응답 시:
  │   ├─ AI Pipeline 안전 종료
  │   ├─ RTP Relay → Bridge 모드 전환
  │   └─ 발신자 ◄──RTP──► 상담원 (끊김 없이 <500ms)
  │
  └─ 대상 미응답/거절 시:
      └─ AI 모드 자동 복귀
```

**수동 전환 (운영자)**:
- 대시보드에서 AI 응대 통화의 "호 전환" 버튼 클릭
- `manual_transfer_request` Socket.IO 이벤트 → 운영자 내선으로 INVITE

**기능적 장점**:
- RFC 3725 스타일 제3자 호 제어 (SIP REFER 불필요, 호환성 높음)
- TransferManager가 상태 기계 + UX 관리, SIPEndpoint가 SIP/RTP 명령 분리
- 전환 실패 시 AI 자동 복귀로 통화 끊김 방지

### 2.8 통화 녹음 및 지식 추출

**기능**: 모든 AI 통화를 녹음하고, 통화 종료 후 LLM으로 유용한 지식을 자동 추출

**유저 스토리**: AI가 응대한 통화를 자동으로 녹음하고, 통화 내용에서
"김 대리님은 수요일 오후 3시에 미팅 가능"같은 정보를 추출하여
지식베이스에 자동 등록한다.

**녹음 아키텍처**:
- `RecordingInputProcessor`: 발신자 오디오 수집
- `RecordingOutputProcessor`: AI TTS 오디오 수집
- `CallRecordingCollector`: 양쪽 오디오를 혼합 스테레오 WAV로 저장
- 저장 경로: `recordings/{call_id}/mixed.wav`

**지식 추출 파이프라인**:
```
통화 종료
  → 5초 대기 (STT 전사 완료 대기)
    → transcript.txt 로드
      → ExtractionPipeline (v2 멀티스텝):
        ├─ 전처리 + 화자 필터
        ├─ 요약 / QA / 엔티티 추출
        ├─ 품질·중복·환각 검사
        └─ ChromaDB upsert
```

**기능적 장점**:
- 비동기 스케줄링으로 통화 종료 처리와 추출 작업 분리
- 유용성 판단(LLM) + 품질 게이트로 저품질 지식 유입 방지
- 시간이 지날수록 지식베이스가 자동으로 풍부해지는 학습 효과

**유저간 통화 기반 지식 자동 성장**

- 상담원(유저)과 고객 간 통화 내용이 **실시간 STT**로 텍스트화된다.
- **화자 분리(Diarization)**: 발신자(Caller) 질문 / 착신자(Callee) 답변을 구분·태깅한다.
- LLM이 인사말·잡담을 제거한 뒤 의미 단위(Chunk)로 나누고, **질문–해결책(Q&A) 쌍**을 자동 추출한다.
- **메타데이터 구조화**: 문제 유형, 해결 방법, 카테고리 등과 함께 ChromaDB에 저장한다.
- **중복 방지**: 기존 지식과 **코사인 유사도**를 비교한다. 유사도 **> 0.9**이면 **upsert(업데이트)**, 신규이면 **insert**한다.
- **효과**: 별도 구축 없이 사람의 통화 정보를 자산화하여 지식 정보 시스템 구축 비용을 줄인다.

### 2.9 페르소나 서비스

**기능**: 조직별 AI 봇 성격을 정의하고, 발화의 업무 관련성을 판단

**유저 스토리**: "기상청 AI 봇"이라는 페르소나를 설정하면,
날씨 관련 질문은 knowledge 경로로, "오늘 뭐 먹지?" 같은 잡담은
페르소나 템플릿 응답으로 처리한다.

**동작 로직**:
- ChromaDB `persona` 컬렉션에 owner별 1건 저장
- `check_query_relevance`: 발화 임베딩 vs 페르소나 임베딩 유사도 계산
  - 유사도 < 0.6 → `chitchat` (업무 무관)
  - 유사도 ≥ 0.6 → `question` (업무 관련)
- 잡담 시 `chitchat_response_template` 사용 → LLM 호출 없이 즉시 응답

**API**: `GET/POST/PUT/DELETE /api/persona/{owner}`

### 2.10 시맨틱 캐시

**기능**: 유사한 질문에 대해 이전 답변을 재사용하여 응답 속도 극대화

**동작 로직**:
- ChromaDB `qa_cache` 컬렉션에 질문-답변 쌍 저장
- 새 질문 임베딩과 캐시된 질문의 유사도 비교
- 유사도 ≥ 0.85 + TTL 미만료 + 비폴백 답변 → 캐시 히트 → 즉시 응답

| 파라미터 | 값 |
|---|---|
| 유사도 임계값 | 0.85 |
| FAQ TTL | 24시간 |
| 일반 TTL | 1시간 |

**기능적 장점**: LLM + RAG 전체 경로를 스킵하여 ~0.01초 응답 가능

### 2.11 웹 대시보드 (운영자 화면)

**기능**: 실시간 통화 모니터링, HITL 응답, 호 전환, 지식베이스 관리

**유저 스토리**: 운영자가 웹 브라우저에서 현재 진행 중인 AI 통화를 실시간으로
모니터링하고, 필요 시 HITL 응답이나 호 전환으로 개입한다.

**주요 화면 (요약)**

| 화면 | 기능 |
|---|---|
| **대시보드** | 메트릭 카드, 실시간 통화 카드, STT/TTS 피드, 처리 로그, HITL 응답, 통화이력 |
| **지식베이스** | 지식 CRUD, 페르소나 설정, TXT 업로드, 카테고리 필터 |
| **통화이력** | 전체 통화 목록, 녹음 재생, 트랜스크립트, CDR 상세 |
| **로그인** | 테넌트(내선번호) 선택 로그인 |

**대시보드 (메인 화면)**

- **실시간 메트릭 카드**: 총 통화수, AI 처리율, 평균 응답시간, 활성 통화수
- **실시간 통화 카드**: 현재 진행 중인 AI 통화 목록, 호 전환 버튼
- **STT 피드**: 사용자 발화 실시간 텍스트 표시
- **TTS 피드**: AI 응답 텍스트 실시간 표시
- **AI 사고 처리 과정 트래킹 (CDR)**: 의도 분류, RAG 검색, LLM 응답, HITL 요청 등 처리 단계별 로그
- **HITL 요청 패널**: AI가 모르는 질문 실시간 알림 + 운영자 답변 입력창
- **통화이력 (대시보드 하단)**: 최근 통화 목록, 녹음 재생 버튼

**통화이력 화면**

- 전체 통화 목록 (날짜, 발신번호, 착신번호, 통화시간, AI 처리 여부)
- **녹음 재생**: 브라우저 내 오디오 플레이어
- **트랜스크립트**: STT 변환 텍스트 전문
- **CDR 상세**: 통화 중 AI 처리 단계별 기록 (`call_data_record` 로그)

**AI 발신 기능**

- 발신 목적(`purpose`) 및 확인 질문 목록(`questions`) 설정
- AI 봇이 지정 번호로 발신 후 목적에 따른 미션 수행
- 발신 이력 및 상태 관리 (`pending` / `calling` / `answered` / `completed` / `failed`)
- **재시도(retry)** 기능

**지식베이스 관리**

- 지식 **CRUD** (카테고리별 분류)
- **TXT 파일 업로드** (자동 청킹 및 임베딩)
- **페르소나 설정** (AI 봇 역할 및 업무 범위 정의)

**실시간 통신**:
- Socket.IO (`ws://localhost:8001`)로 통화 이벤트 수신
- 연결 끊김 시 REST 폴링(20초) 자동 전환
- 재연결 성공 시 전체 상태 갱신

**기술 스택**: Next.js 14 + Tailwind CSS + Radix UI + Socket.IO Client

### 2.12 멀티 테넌트 구조 (테넌트별 독립 AI)

**기능**: SIP 내선(테넌트) 단위로 지식·캐시·페르소나를 격리하여, 최소 설정으로 테넌트별 독립 AI 봇을 운용한다.

- **테넌트 = SIP 내선번호** (예: 1004, 1005, 1006).
- 테넌트별 **독립 ChromaDB 컬렉션** (`owner` 필드로 격리):
  - `knowledge_{owner}`: 지식베이스
  - `qa_cache_{owner}`: 시맨틱 캐시
  - `persona_{owner}`: 페르소나 정의
- **최소 설정으로 나만의 AI 봇 운용**:
  1. SIP 내선 등록 (기존 IP PBX 연동)
  2. 페르소나 설정 (역할, 업무 범위, 인사말)
  3. 초기 지식 업로드 (선택, TXT 파일)
  4. 이후 통화 이력으로 자동 학습 시작
- 유저간 통화가 쌓일수록 **해당 테넌트의 AI만** 독립적으로 성장한다.
- 다른 테넌트의 지식·캐시·페르소나와 **완전 격리** → 보안 및 개인화 보장.

**Active RAG 자율 학습 사이클**

```
유저간 통화 발생
  → STT 실시간 변환
    → 화자 분리 (발신자 질문 / 착신자 답변)
      → LLM 품질 게이트 (유용성 판단)
        → 중복 검사 (코사인 유사도 > 0.9 → upsert)
          → ChromaDB 저장 (해당 owner 컬렉션)
            → 다음 통화부터 RAG에 즉시 활용
              → 동일 질문 AI 자동 응답 (HITL 불필요)
                → 한계 비용(Marginal Cost) 점진적 감소
```

---

## 3. 유저 스토리 시나리오

### 3.1 영업시간 외 자동 응대

**페르소나**: 접수 담당자 (영업시간 외 문의 자동 처리)

```
[저녁 8시, 착신자 부재중]

📞 고객: (전화 연결)
🤖 AI: "안녕하세요. KT 기상청 AI 봇입니다. 무엇을 도와드릴까요?"
         (ChromaDB greeting 직접 조회, LLM 0회, ~0.01초)

👤 고객: "내일 서울 날씨 알려줘"
🤖 AI:   [classify_intent → question (키워드+LLM 병합)]
         [check_cache → miss]
         [adaptive_rag → ChromaDB 검색 → 3건 컨텍스트]
         [generate_response → Gemini 2.5 Flash 스트리밍]
         "내일 서울 지역은 오전에 구름이 많고, 오후부터 비가 오는 곳이 있겠습니다."
         (총 ~2.5초)

👤 고객: "감사합니다"
🤖 AI:   [classify_intent → farewell (키워드 매칭)]
         [greeting_farewell_kb → ChromaDB farewell 조회]
         "좋은 하루 보내세요. 이용해 주셔서 감사합니다."
         (LLM 0회, ~0.01초)

→ 통화 종료
→ 녹음 저장 (recordings/{call_id}/mixed.wav)
→ 지식 추출 (5초 후 비동기 실행)
→ CDR 기록 (logs/call_data_record_YYYYMMDD.log)
```

**효과**: 24시간 자동 응대, 단순 문의 자동 처리, 운영자 부담 제로

### 3.2 HITL 운영자 개입

**페르소나**: 고객센터 팀장 (AI가 처리 못하는 질문 실시간 지원)

```
👤 고객: "다음 주 수요일에 김 대리님 만날 수 있나요?"
🤖 AI:   [RAG 검색 → 관련 문서 없음]
         [generate_response → confidence=0.15]
         [hitl_alert → confidence < 0.3 → HITL 트리거]
         "잠시만 확인중이니 기다려 주세요."

         → WebSocket: hitl_requested → 운영자 대시보드 🔔

[운영자 대시보드]
┌─────────────────────────────────────┐
│ 🔔 HITL 요청                        │
│ 질문: "다음 주 수요일에 김 대리님    │
│       만날 수 있나요?"              │
│                                     │
│ 📝 답변: [수요일 오후 3시 가능___]  │
│ [전송]                              │
└─────────────────────────────────────┘

→ 운영자 답변 "수요일 오후 3시 가능"
→ LLM 정제: "확인해 드렸습니다. 다음 주 수요일 오후 3시에 미팅이 가능합니다."
→ TTS 송출 → 고객에게 안내
→ Q&A 자동 지식베이스 저장 → 동일 질문 재발 시 AI 직접 응답
```

**효과**: AI 오답 방지, 고객 대기 시간 최소화, 지식베이스 자동 성장

### 3.3 운영자 수동 호 전환

**페르소나**: 시니어 상담원 (AI 응대 중 긴급 상황 즉시 개입)

```
[운영자 대시보드 — 실시간 모니터링]

📞 활성 통화: 010-1234-5678
   경과: 00:02:34 | AI 응대중
   
   STT/TTS 피드:
   👤: "환불이 안 되면 소비자원에 신고할 거예요!"
   🤖: "확인해 드리겠습니다..."
   
   [호 전환] ← 클릭!

→ manual_transfer_request → Backend
→ 운영자 내선(1004)으로 INVITE 전송
→ 운영자 전화 벨 울림 → 응답
→ AI Pipeline 안전 종료
→ RTP Relay → Bridge 모드 전환
→ 발신자 ◄──RTP──► 운영자 (끊김 없이 <500ms)

운영자: "고객님, 제가 바로 도와드리겠습니다..."
```

**효과**: 즉각적 인간 개입(<2초), 고객 불만 사전 차단, 끊김 없는 통화 전환

### 3.4 통화 이력 분석

**페르소나**: 서비스 개선 담당 (고객 문의 패턴 파악)

```
[통화이력 페이지]

┌─────────────────────────────────────────────┐
│ 2026-03-30 14:23 | 010-1234-5678            │
│ AI 응대 | 2:34 | 기상감정서 발급 문의         │
│ ▶ [녹음 재생]                                │
│                                             │
│ ▼ 상세 확장                                  │
│   📝 트랜스크립트:                            │
│   👤 "기상감정서 발급하려면 어떻게 해야 하나요?"│
│   🤖 "기상감정서는 기상청 홈페이지에서..."     │
│                                             │
│   📊 처리 로그 (CDR):                        │
│   14:23:01 | stt | stt_final               │
│   14:23:02 | rag | rag_search_done (3건)    │
│   14:23:04 | llm | generate_response_done   │
│   14:23:05 | tts | tts_complete             │
└─────────────────────────────────────────────┘
```

**효과**: 데이터 기반 서비스 개선, 지식베이스 갭 분석, 운영 효율성 향상

---

## 4. API 엔드포인트

### 4.1 REST API (Port 8000)

| 카테고리 | 메서드 | 경로 | 설명 |
|---|---|---|---|
| **인증** | POST | `/api/auth/login` | 테넌트 로그인, 토큰 발급 |
| **인증** | GET | `/api/tenants` | 테넌트 목록 조회 |
| **통화** | GET | `/api/calls/active` | 활성 통화 목록 |
| **통화이력** | GET | `/api/call-history` | 통화이력 조회 (페이지네이션) |
| **통화이력** | GET | `/api/call-history/{id}/transcript` | 트랜스크립트 조회 |
| **통화이력** | GET | `/api/call-history/{id}/media/mixed` | 녹음 파일 다운로드 |
| **통화이력** | GET | `/api/call-history/{id}/debug-trace` | CDR 처리 로그 |
| **메트릭** | GET | `/api/metrics/dashboard` | 대시보드 메트릭 |
| **지식** | GET/POST | `/api/knowledge` | 지식 조회/추가 |
| **지식** | DELETE | `/api/knowledge/{id}` | 지식 삭제 |
| **지식** | POST | `/api/knowledge/upload-manual` | 파일 업로드 |
| **페르소나** | GET/POST/PUT/DELETE | `/api/persona/{owner}` | 페르소나 CRUD |
| **운영자** | GET/POST | `/api/operator/status` | 운영자 상태 조회/변경 |
| **발신** | POST | `/api/outbound/create` | 발신 통화 생성 |
| **발신** | POST | `/api/outbound/cancel` | 발신 취소 |
| **헬스** | GET | `/health` | 서비스 상태 확인 |

### 4.2 Socket.IO 이벤트 (Port 8001)

**서버→클라이언트**:

| 이벤트 | 설명 |
|---|---|
| `call_started` | 신규 통화 시작 |
| `call_ended` | 통화 종료 |
| `stt_transcript` | 실시간 STT (interim/final) |
| `tts_started` | AI TTS 응답 텍스트 |
| `ai_greeting` | AI 인사말 |
| `hitl_requested` | HITL 운영자 요청 |
| `hitl_resolved` | HITL 해결 완료 |
| `call_debug_trace` | CDR 실시간 전달 |
| `transfer_success` | 호 전환 성공 |
| `transfer_failed` | 호 전환 실패 |

**클라이언트→서버**:

| 이벤트 | 설명 |
|---|---|
| `manual_transfer_request` | 수동 호 전환 요청 |
| `submit_hitl_response` | HITL 응답 전송 |

---

## 5. CDR 및 로깅

### 5.1 Call Data Record (실시간 추적)

**파일**: `logs/call_data_record_YYYYMMDD.log` (JSON Lines)

통화 중 발생하는 모든 이벤트를 실시간으로 기록하며,
동시에 Socket.IO `call_debug_trace`로 대시보드에 전달한다.

**카테고리**: `llm`, `stt`, `tts`, `rag`, `knowledge`, `call_event`, `hitl` 등

```json
{
  "timestamp": "2026-03-30T14:55:11.287",
  "call_id": "abc-123",
  "category": "rag",
  "event": "rag_search_done",
  "top_score": 0.269,
  "num_results": 11,
  "elapsed_ms": 190
}
```

### 5.2 구조화된 앱 로그 (structlog)

**파일**: `logs/app.log`

structlog 기반 구조화 로그로, 모든 이벤트에 `call_id`, `event`, 타이밍 정보를 포함한다.

---

## 6. 설정 구조 (config.yaml)

```yaml
sip:
  bind_address: "0.0.0.0"
  port: 5060
  no_answer_timeout: 10          # AI 전환까지 대기 (초)

media:
  mode: "bypass"                  # direct | bypass | reflecting
  rtp_bind_ip: "0.0.0.0"
  port_pool: { start: 10000, end: 20000 }

ai_voicebot:
  enabled: true
  google_cloud:
    gemini:
      model: "gemini-2.5-flash"
      temperature: 0.3
      max_output_tokens: 256
    stt: { language_code: "ko-KR" }
    tts: { language_code: "ko-KR", voice_name: "ko-KR-Neural2-A" }
  rag:
    top_k: 10
    similarity_threshold: 0.15
  hitl:
    timeout_seconds: 60
  vector_db:
    chromadb: { persist_directory: "./data/chromadb" }
  embedding:
    model: "all-MiniLM-L6-v2"
    dimension: 384
  transfer:
    enabled: true
    ring_timeout: 15
  recording:
    enabled: true
    knowledge_extraction: { enabled: true }
```

---

## 7. 기술 스택

### 7.1 Backend

| 카테고리 | 기술 |
|---|---|
| 언어 | Python 3.11+ |
| 프레임워크 | FastAPI + asyncio |
| SIP/RTP | 순수 Python 구현 (B2BUA) |
| 파이프라인 | Pipecat (실시간 음성 처리) |
| 대화 그래프 | LangGraph (StateGraph) |
| WebSocket | Socket.IO (python-socketio, aiohttp) |
| 벡터 DB | ChromaDB |
| 임베딩 | Sentence Transformers (all-MiniLM-L6-v2) |
| 로깅 | structlog (구조화 로그) |

### 7.2 Frontend

| 카테고리 | 기술 |
|---|---|
| 프레임워크 | Next.js 14 (App Router) |
| 언어 | TypeScript |
| UI | Tailwind CSS + Radix UI |
| 실시간 | Socket.IO Client |
| 오디오 | WaveSurfer.js |
| 상태 | 컴포넌트 로컬 + Zustand (일부) |

### 7.3 External AI Services

| 서비스 | 용도 |
|---|---|
| Google Cloud STT | 음성→텍스트 (한국어 Telephony 모델, 16kHz) |
| Google Cloud TTS | 텍스트→음성 (Neural2 한국어 음성) |
| Google Gemini 2.5 Flash | LLM 대화 생성 (초저비용) |

---

## 8. 실행 방법

```powershell
# 전체 시스템 시작
.\start-all.ps1

# 프로세스:
#   - Frontend (Next.js): http://localhost:3000
#   - Backend (SIP+API): SIP:5060, REST:8000, WS:8001

# 전체 시스템 종료
.\stop-all.ps1
```

**프로세스 구성**:
- Backend: `python -m src.main` — SIP(5060) + RTP(10000+) + REST API(8000) + WebSocket(8001)
- Frontend: `npm run dev` — Next.js 개발 서버(3000)

---

## 9. 성능 지표

### 9.1 응답 시간

| 시나리오 | 평균 | 설명 |
|---|---|---|
| 인사/작별 (캐시 히트) | ~0.01초 | ChromaDB 직접 조회, LLM 0회 |
| 시맨틱 캐시 히트 | ~0.1초 | 동일 질문 재사용 |
| 일반 질문 (RAG+LLM) | ~2.5초 | RAG 검색 + LLM 스트리밍 |
| 복잡한 질문 | ~5초 | step_back 재검색 포함 |
| HITL (운영자 개입) | ~20초 | 운영자 응답 대기 |

### 9.2 비용 (월 100통화 기준)

| 서비스 | 월 비용 |
|---|---|
| Gemini 2.5 Flash | ~₩1,400 |
| Google STT | ~₩3,000 |
| Google TTS | ~₩2,000 |
| ChromaDB (로컬) | ₩0 |
| **합계** | **~₩6,400** |

---

## 10. 관련 문서

### 설계서

| 문서 | 설명 |
|---|---|
| [AI_VOICEBOT_ARCHITECTURE.md](design/AI_VOICEBOT_ARCHITECTURE.md) | AI 음성봇 아키텍처 상세 |
| [FRONTEND_ARCHITECTURE.md](design/FRONTEND_ARCHITECTURE.md) | Frontend 아키텍처 상세 |
| [TTS_RTP_AND_STT_QUEUE_DESIGN.md](design/TTS_RTP_AND_STT_QUEUE_DESIGN.md) | TTS→RTP 큐 설계 |
| [INTENT_HANDLING_DESIGN.md](design/INTENT_HANDLING_DESIGN.md) | Intent별 처리 로직 |
| [CHROMADB_CATEGORY_DESIGN.md](design/CHROMADB_CATEGORY_DESIGN.md) | ChromaDB 카테고리 설계 |
| [HITL_OPERATOR_RESPONSE_FLOW.md](design/HITL_OPERATOR_RESPONSE_FLOW.md) | HITL 운영자 응답 흐름 |
| [AI_RESPONSE_HUMANLIKE_DESIGN.md](design/AI_RESPONSE_HUMANLIKE_DESIGN.md) | 자연스러운 AI 응답 설계 |

### 가이드

| 문서 | 설명 |
|---|---|
| [QUICK_START.md](QUICK_START.md) | 빠른 시작 가이드 |
| [INDEX.md](INDEX.md) | 전체 문서 인덱스 |

### 리포트

| 폴더 | 설명 |
|---|---|
| [reports/2026-03/](reports/2026-03/) | 2026년 3월 분석·점검 리포트 |
