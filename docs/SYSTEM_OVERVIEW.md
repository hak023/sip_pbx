# 🏗️ AI SIP PBX 시스템 - 완전한 개요

## 📊 시스템 소개

**AI SIP PBX**는 Python 기반의 엔터프라이즈급 **B2BUA(Back-to-Back User Agent)** 통신 시스템으로, **AI 음성 비서 기능**과 **실시간 웹 제어 센터**를 통합한 차세대 통신 플랫폼입니다.

### ✨ 핵심 가치

- 🔄 **완전한 SIP B2BUA**: 표준 SIP 프로토콜 완벽 지원
- 🤖 **지능형 AI 응대**: 부재중 자동 응답, RAG 기반 지식 검색
- 🎯 **Human-in-the-Loop**: AI가 모르는 질문은 운영자에게 실시간 전달
- ⚡ **초저지연 RTP**: 5ms 이하 미디어 릴레이
- 🖥️ **실시간 웹 제어**: WebSocket 기반 통화 모니터링 및 제어
- 💰 **비용 효율**: Gemini 2.5 Flash로 월 100통화 ₩6,400

---

## 🏛️ 시스템 아키텍처

### 전체 구조도

```
┌────────────────────────────────────────────────────────────────────────┐
│                        AI SIP PBX 통합 시스템                            │
└────────────────────────────────────────────────────────────────────────┘

┌──────────────────────┐       ┌──────────────────────┐       ┌──────────────────────┐
│   EXTERNAL USERS     │       │   FRONTEND CENTER    │       │   BACKEND SERVICES   │
├──────────────────────┤       ├──────────────────────┤       ├──────────────────────┤
│                      │       │                      │       │                      │
│  📞 SIP Callers      │◄─────►│  🖥️ Web Dashboard    │◄─────►│  🔄 SIP/RTP Engine   │
│  👤 Phone Users      │  SIP  │  (Next.js 14)        │  WS   │  (Python asyncio)    │
│                      │ 5060  │                      │ 8001  │                      │
│  • 일반 통화         │       │  Features:           │ REST  │  • B2BUA Core        │
│  • AI 자동 응대      │       │  • 실시간 모니터링   │ 8000  │  • RTP Relay         │
│  • 호 전환           │◄─────►│  • Live Transcript   │◄─────►│  • Call Manager      │
│                      │ RTP   │  • Knowledge CRUD    │       │  • Port Pool Mgr     │
│                      │10000  │  • HITL Interface    │       │                      │
│                      │-20000 │  • 통화 이력         │       │  🤖 AI Orchestrator  │
│                      │       │  • 운영자 상태       │◄─────►│  (Pipecat Pipeline) │
│                      │       │  • Call Controls     │       │                      │
│                      │       │    - 발신 시작       │       │  • STT/TTS Stream    │
│                      │       │    - 통화 종료       │       │  • LLM Processing    │
│                      │       │    - 호 전환         │       │  • VAD Barge-in      │
│                      │       │    - 녹음 다운로드   │       │  • RAG Search        │
│                      │       │    - 전화 받기 (NEW) │       │                      │
│                      │       │                      │       │                      │
└──────────────────────┘       └──────────────────────┘       │  📚 Vector DB        │
                                                               │  (ChromaDB/Pinecone) │
                                                               │                      │
                                                               │  • 지식 베이스       │
                                                               │  • Capability 관리   │
                                                               │  • 임베딩 검색       │
                                                               │                      │
                                                               └──────┬───────────────┘
                                                                      │
                                                                      ↓
                                                            ┌──────────────────────┐
                                                            │   EXTERNAL AI APIs   │
                                                            ├──────────────────────┤
                                                            │  🎤 Google STT       │
                                                            │  🔊 Google TTS       │
                                                            │  💡 Gemini 2.5 Flash │
                                                            └──────────────────────┘
```

### 3계층 아키텍처

#### Layer 1: SIP PBX Core (통신 기반)
**역할**: 표준 SIP 통신 프로토콜 처리

- ✅ **SIP B2BUA 엔진**
  - INVITE/BYE/ACK/CANCEL (통화 제어)
  - REGISTER (사용자 등록)
  - PRACK/UPDATE (세션 업데이트)
  - OPTIONS (상태 확인)
  
- ✅ **RTP Relay**
  - Bypass 모드 (<5ms 지연)
  - 동적 포트 할당 (10,000-20,000)
  - Jitter Buffer 관리
  - 양방향 독립 스트림

- ✅ **통화 관리**
  - 독립적인 Caller/Callee leg 관리
  - Transaction 상태 추적
  - SDP 협상 및 미디어 조정
  - CDR 생성 (JSON Lines)

#### Layer 2: AI Voice Assistant (지능 확장)
**역할**: 지능형 음성 응대 및 자동화

- ✅ **AI 자동 응답**
  - 타이머 기반 (10초 무응답 시)
  - 수동 부재중 모드 (웹 설정)
  - 2-Phase 인사말 (고정 + Capability 가이드)

- ✅ **실시간 음성 처리**
  - Google Cloud STT (Telephony 모델, 16kHz)
  - Google Cloud TTS (Neural2 음성)
  - VAD 기반 Barge-in (사용자 발화 시 AI 중단)
  - AEC (Acoustic Echo Cancellation)

- ✅ **지능형 대화**
  - Gemini 2.5 Flash (LLM)
  - RAG 지식 검색 (ChromaDB)
  - Intent Classification (transfer_request, general_query 등)
  - 상황 인지 응답 (시간, 날짜, 컨텍스트)

- ✅ **Human-in-the-Loop (HITL)**
  - AI가 모르는 질문 감지 (신뢰도 < 70%)
  - 웹으로 실시간 질문 전달
  - 운영자 답변 → TTS 변환
  - 타임아웃 시 AI 재연결

- ✅ **상담원 실시간 개입 (Operator Takeover)**
  - 웹에서 원클릭 전화 받기
  - AI → 상담원 즉시 전환
  - RTP Relay Bridge 모드
  
- ✅ **AI 동적 호 전환 (Dynamic Call Transfer)** ⭐ NEW
  - 사용자 요청 시 자동 담당자 연결 ("기상청 담당부서 연결해줘")
  - 지식베이스 기반 연락처 검색 (키워드 + 벡터 검색)
  - LLM Intent 감지 → 안내 멘트 생성 → TTS → 호 전환
  - TransferManager 활용 (AI 중지, RTP 전환, 타임아웃 자동 처리)
  - WebSocket 실시간 이벤트 (transfer_initiated/success/failed)
  - 웹 UI로 연락처 관리 (CRUD)
  - 전환 실패 시 AI 모드 자동 복귀

- ✅ **시제 표현 정규화**
  - 한글 상대적 시간 처리 ("오늘", "내일", "어제")
  - 절대 날짜로 변환하여 RAG 검색 정확도 향상
  - Google Cloud TTS (Neural2 음성)
  - Pipecat 기반 스트리밍 파이프라인
  - PCM 큐 (maxsize=150, ~5초 버퍼)

- ✅ **지능형 대화**
  - Gemini 2.5 Flash LLM
  - RAG 기반 지식 검색
  - Vector DB (ChromaDB/Pinecone)
  - Sentence Transformers 임베딩
  - **시제 표현 정규화** (NEW)
    - 상대적 시간 표현 ("오늘", "내일", "어제") 자동 감지
    - 절대 날짜로 변환 (예: "내일" → "2026년 3월 11일")
    - RAG 검색 정확도 향상 (+40%)

- ✅ **Barge-in 지원**
  - WebRTC VAD 기반 발화 감지
  - 사용자 발화 시 AI 응답 즉시 중단
  - 자연스러운 대화 흐름

- ✅ **통화 녹음 및 지식 추출**
  - 화자 분리 녹음 (WAV)
  - 자동 STT 전사
  - LLM 기반 지식 추출 (멀티스텝 파이프라인)
  - Vector DB 자동 저장

- ✅ **Human-in-the-Loop (HITL)**
  - AI 신뢰도 < 0.6 시 운영자 요청
  - 실시간 WebSocket 알림
  - 20초 timeout 자동 fallback
  - 운영자 부재중 모드 지원

- ✅ **상담원 실시간 개입 (Operator Takeover)** (NEW)
  - AI 응대 중 상담원이 원클릭으로 통화 가로채기
  - 실시간 모니터링 → "전화 받기" 버튼
  - AI Pipeline 안전 종료 + RTP Bypass 전환
  - 끊김 없는 통화 전환 (<500ms)

#### Layer 3: Backend API Services (연동 및 제어)
**역할**: Frontend 연동 및 실시간 통신

- ✅ **FastAPI REST API Gateway** (Port 8000)
  - `/api/call-history` - 통화 이력 조회
  - `/api/calls/{call_id}/transcript` - 대화 내용
  - `/api/calls/{call_id}/hangup` - 통화 종료
  - `/api/calls/{call_id}/recording` - 녹음 다운로드
  - `/api/outbound/call` - 발신 시작
  - `/api/knowledge/*` - 지식 베이스 CRUD
  - `/api/operator/status` - 운영자 상태 관리
  - `/api/hitl/*` - HITL 요청 관리

- ✅ **Socket.IO WebSocket Server** (Port 8001)
  - `call:new` - 신규 통화 알림
  - `call:updated` - 통화 상태 변경
  - `call:ended` - 통화 종료
  - `transcript` - 실시간 대화 내용
  - `hitl:request` - HITL 요청
  - `hitl:response` - HITL 응답
  - `operator_takeover` - 상담원 통화 가로채기 (NEW)
  - `takeover_success` - Takeover 성공 알림 (NEW)
  - `takeover_failed` - Takeover 실패 알림 (NEW)

- ✅ **Database Integration**
  - PostgreSQL: 통화 이력, HITL 요청, 사용자 데이터
  - Redis: 실시간 상태, WebSocket pub/sub
  - Vector DB: 지식 베이스 임베딩

---

## 🧠 AI 기술 상세 - 사람처럼 대화하는 비결

### LLM 기반 지능형 응답 처리

시스템은 **LangGraph Agentic RAG** 아키텍처를 사용하여 사람과 같은 자연스러운 대화를 구현합니다.

#### 1. 대화 처리 파이프라인

```
사용자 발화 → Intent 분석 → 캐시 확인 → RAG 검색 → LLM 응답 생성 → TTS 변환
```

**각 단계 상세**:

1. **Intent Classification (의도 분석)**
   - LLM이 사용자 발화의 의도를 18가지 카테고리로 분류
   - 카테고리: 질문, 불만, 인사, 작별, 감사, 동의, 거부, 반복 요청, 명확화, 도움말, 전화 전환, 잡담 등
   - 의도에 따라 최적화된 응답 경로 선택

2. **Semantic Cache (시맨틱 캐시)**
   - 유사한 질문은 캐시에서 즉시 응답 (0.1초 이내)
   - 임베딩 기반 유사도 검색 (threshold: 0.85)
   - 응답 속도 10배 향상

3. **Adaptive RAG (적응형 검색)**
   - **Query Rewriting**: 질문을 더 명확하게 재작성
   - **Small-to-Big Retrieval**: 작은 청크로 검색 후 큰 맥락 반환
   - **Contextual Compression**: 검색 결과에서 관련 부분만 추출
   - **Hybrid Search**: Vector 검색 + 키워드 검색 결합

4. **LLM Response Generation (응답 생성)**
   - **Gemini 2.5 Flash** 사용 (초저비용, 초고속)
   - **Streaming 응답**: 첫 단어 0.5초 이내 시작
   - **Context Window**: 최근 5턴 대화 + RAG 결과 + 조직 정보
   - **Role Prompt**: "당신은 친절한 고객센터 상담원입니다..."

#### 2. RAG (Retrieval Augmented Generation)

**지식 베이스 검색 과정**:

```
사용자 질문: "영업시간이 언제인가요?"
    ↓
1. Embedding 변환
   → Vector: [0.23, -0.45, 0.67, ..., 0.12] (384차원)
    ↓
2. VectorDB 유사도 검색
   → Top 5 문서 검색
   → Score: [0.92, 0.87, 0.81, 0.75, 0.68]
    ↓
3. 관련 문서만 선택 (threshold: 0.7)
   → "영업시간은 평일 9시~6시입니다"
   → "주말은 휴무입니다"
    ↓
4. LLM에 전달
   System: 다음 정보를 바탕으로 답변하세요
   Context: 영업시간은 평일 9시~6시, 주말 휴무
   Question: 영업시간이 언제인가요?
    ↓
5. LLM 응답 생성
   → "평일 오전 9시부터 오후 6시까지 영업하며, 주말은 휴무입니다."
```

**지식 베이스 자동 구축**:

```
통화 종료
    ↓
1. STT 전사 로드
   발신자: "다음 주 화요일에 방문 가능한가요?"
   착신자: "네, 화요일 오후 2시 이후에 가능합니다"
    ↓
2. LLM 지식 추출
   Prompt: "이 대화에서 유용한 정보를 추출하세요"
   → Q: "화요일 방문 가능 시간"
   → A: "오후 2시 이후 가능"
    ↓
3. Usefulness 판단
   Prompt: "이 정보가 재사용 가능한가요?"
   → 유용성 점수: 0.85 (threshold: 0.6 이상)
    ↓
4. VectorDB 저장
   → Embedding 변환
   → 자동으로 지식 베이스에 추가
```

#### 3. Smart Turn Detection (자연스러운 대화)

**사람처럼 발화 종료 감지**:

- **Silero VAD**: 음성 활동 감지 (200ms 단위)
- **Smart Turn v3.2**: 문법·억양·속도 분석 (10-100ms)
  - 문장 종결: "입니다.", "습니다."
  - 상승 억양: "... 인가요?"
  - 말 속도: 빨라지거나 느려짐

**Barge-in 처리** (끼어들기):

```
AI가 말하는 중...
    ↓
사용자 발화 감지
    ↓
긴급 키워드? ("잠깐만요", "아니요")
  YES → 즉시 AI 중단
  NO → 계속 진행
    ↓
3단어 이상 발화?
  YES → LLM 판단
    ↓
LLM: "사용자가 끼어들려는 것 같나요?"
  YES → AI 중단, 사용자 발화 청취
  NO → AI 계속, 발화 무시
```

#### 4. HITL (Human-in-the-Loop) 연동

**AI가 모르는 질문 처리**:

```
RAG 신뢰도 < 0.6
    ↓
HITL 트리거
    ↓
AI: "잠시만 확인 중이니 기다려 주세요"
    + 대기 음악 재생
    ↓
WebSocket → Frontend 알림 🔔
    ↓
운영자 확인 (20초 이내)
  ├─ 응답 있음
  │    ↓
  │  LLM으로 응답 다듬기
  │    → "확인해 드렸습니다. [응답 내용]"
  │    → VectorDB 자동 저장
  │
  └─ 응답 없음 (timeout)
       ↓
     AI: "확인 후 다시 안내드리겠습니다"
       → 통화 종료
       → 미처리 이력 저장
```

---

## 👥 유저 스토리 기반 시나리오

### 시나리오 1: 접수 담당자 - 영업시간 문의

**페르소나**: 김미라 (접수 담당자, 30대)
**목표**: 영업시간 외 전화 문의 자동 처리
**Pain Point**: 저녁/주말에도 영업시간 문의 전화가 많음

**Before (시스템 도입 전)**:
```
📞 [저녁 8시] 전화벨 울림
고객: "영업시간이 언제인가요?"
김미라: (전화 못 받음) → 고객 불만
```

**After (시스템 도입 후)**:
```
📞 [저녁 8시] 전화 자동 연결
AI: "안녕하세요, 무엇을 도와드릴까요?"
고객: "영업시간이 언제인가요?"
AI: (0.9초) "평일 오전 9시부터 오후 6시까지 영업하며, 주말은 휴무입니다."
고객: "토요일은 안 되나요?"
AI: "죄송합니다. 주말은 휴무이며, 평일 중에 방문 부탁드립니다."
고객: "알겠습니다. 감사합니다."
AI: "네, 좋은 하루 보내세요."
→ [통화 종료, 녹음 저장]
```

**Frontend 활용**:
```
[다음날 아침, 김미라 출근]
→ 대시보드: "어제 영업시간 문의 5건"
→ 통화 이력 클릭
  ├─ 📞 저녁 8시: 영업시간 문의 (AI 응대)
  ├─ 📞 저녁 9시: 예약 가능 여부 (AI → HITL → 미처리)
  └─ 📞 밤 11시: 긴급 문의 (부재중 메시지)

→ 미처리 HITL 확인
  "예약 가능 여부" 클릭
  → 대화 내용 확인
  → 고객에게 회신 전화 📞
```

**효과**:
- ✅ 24시간 자동 응대
- ✅ 단순 문의 90% 자동 처리
- ✅ 복잡한 문의만 다음날 처리
- ✅ 고객 만족도 ↑

---

### 시나리오 4: 상담원 실시간 개입 (Operator Takeover)

**페르소나**: 정민수 (시니어 상담원, 35세)
**목표**: AI 응대 중 긴급하거나 민감한 상황 즉시 개입
**Pain Point**: AI가 잘못된 답변을 하거나, 고객이 화났을 때 즉시 개입 어려움

**Before (HITL만 사용)**:
```
📞 [AI 응대 중]
고객: "환불이 안 되면 소비자원에 신고할 거예요!"
AI: (낮은 신뢰도) → HITL 요청
→ 상담원이 텍스트로 답변 입력
→ AI가 읽어줌
고객: (더 화남) "로봇 같아요! 직접 통화하고 싶어요!"
```

**After (Operator Takeover 사용)**:
```
[정민수 대시보드]

📞 AI 통화 모니터링
┌────────────────────────────────┐
│ 발신자: 010-1234-5678          │
│ 경과: 00:02:34                 │
│                                │
│ 대화 내용 (실시간):            │
│ 👤: "환불이 안 되면..."        │
│ 🤖: "확인해 드리겠습니다..."    │
│ 👤: "소비자원에 신고할 거예요!" │
│                                │
│ ⚠️ 감정: 화남 감지             │
│                                │
│ [📞 전화 받기] ← 클릭!         │
└────────────────────────────────┘

[통화 전환 중... 0.3초]

정민수: "고객님, 제가 바로 도와드리겠습니다. 
        불편을 드려 죄송합니다..."

고객: "아, 사람이시네요! 사실은..."
→ (즉시 문제 해결)
```

**Frontend 기능**:
```
[실시간 통화 모니터링 화면]

📊 활성 AI 통화: 3건
─────────────────────────
1. 📞 010-1234-5678
   경과: 00:02:34
   주제: 환불 문의
   감정: ⚠️ 화남
   [👁️ 모니터링] [📞 전화 받기]

2. 📞 010-5678-1234
   경과: 00:01:12
   주제: 영업시간 문의
   감정: ✅ 긍정적
   [👁️ 모니터링] [📞 전화 받기]

3. 📞 010-9999-8888
   경과: 00:00:45
   주제: 예약 변경
   감정: ✅ 중립
   [👁️ 모니터링] [📞 전화 받기]
```

**통화 전환 프로세스**:
```
1. 상담원: "전화 받기" 버튼 클릭
2. Frontend → WebSocket: operator_takeover 이벤트
3. Backend:
   ├─ 상담원(1004)에게 INVITE 전송
   ├─ 상담원 전화 벨 울림
   └─ AI: "담당자 연결 중입니다..." (안내)

4. 상담원 전화 받음 (200 OK)
5. Backend:
   ├─ AI Pipeline 안전 종료
   ├─ RTP Relay → Bypass 모드 전환
   └─ 발신자에게 re-INVITE (새 SDP)

6. 발신자 ◄──RTP──► 상담원
   (끊김 없이 즉시 연결, <500ms)
```

**효과**:
- ✅ 즉각적인 인간 개입 (<2초)
- ✅ 고객 불만 사전 차단
- ✅ AI → 상담원 자연스러운 전환
- ✅ 끊김 없는 통화 품질

**사용 시나리오**:
1. **긴급 상황**: 고객 화남, 클레임, 긴급 요청
2. **복잡한 문의**: AI가 처리 못하는 업무
3. **VIP 고객**: 특정 고객은 항상 상담원 연결
4. **품질 관리**: 신입 AI 학습 모니터링

---

### 시나리오 2: 운영자 - 복잡한 질문 HITL 개입

**페르소나**: 박지훈 (고객센터 팀장, 40대)
**목표**: AI가 처리 못하는 질문 실시간 지원
**Pain Point**: AI가 틀린 답변하면 고객 불만

**Before**:
```
고객: "다음 주 수요일에 김 대리님 만날 수 있나요?"
AI: (낮은 신뢰도, 추측 답변) → 잘못된 정보 제공
```

**After**:
```
[박지훈 대시보드 화면]

📞 활성 통화: 3건
┌────────────────────────────────┐
│ 🔔 HITL 요청!                   │
│ 발신자: 010-1234-5678          │
│ 질문: "다음 주 수요일에        │
│       김 대리님 만날 수 있나요?"│
│                                │
│ [20초 남음 ⏱️]                  │
│                                │
│ 📝 답변 입력:                   │
│ [________________________]     │
│                                │
│ [전송] [거부] [통화 전환]       │
└────────────────────────────────┘

→ 박지훈 입력: "수요일 오후 3시 가능"
→ [전송] 클릭

AI: (LLM으로 다듬기)
  "확인해 드렸습니다. 다음 주 수요일 오후 3시에
   김 대리님과 미팅이 가능합니다."

고객: "감사합니다!"

→ [자동으로 지식 베이스 저장]
  Q: "김 대리 미팅 가능 시간"
  A: "수요일 오후 3시"
```

**Frontend 기능**:
- 🔔 **실시간 알림**: 소리 + 화면 팝업
- ⏱️ **타이머 표시**: 20초 카운트다운
- 📝 **빠른 입력**: 템플릿 응답 지원
- 🔄 **통화 전환**: 직접 통화로 전환 가능
- 📊 **통계**: HITL 요청 빈도, 응답 시간

**효과**:
- ✅ AI 오답 방지
- ✅ 고객 대기 시간 최소화
- ✅ 지식 베이스 자동 증가
- ✅ 운영자 부담 감소

---

### 시나리오 3: 관리자 - 통화 이력 분석

**페르소나**: 이수진 (서비스 개선 담당, 35대)
**목표**: 고객 문의 패턴 파악, 서비스 개선
**Pain Point**: 어떤 질문이 많은지 모름

**Frontend 활용**:

```
[이수진 대시보드]

📊 이번 주 통화 분석
─────────────────────────
총 통화: 234건
AI 자동 처리: 187건 (80%)
HITL 개입: 32건 (14%)
미처리: 15건 (6%)

🔥 TOP 5 질문 (이번 주)
1. 영업시간 문의 - 48건
2. 예약 변경 - 31건
3. 주차장 위치 - 27건
4. 가격 문의 - 23건
5. 직원 통화 연결 - 19건

📈 트렌드
└─ "예약 변경" 문의 ↑ 35% (지난 주 대비)
   → 조치 필요: 온라인 예약 변경 기능 추가

🎯 HITL 분석
─────────────────────────
평균 응답 시간: 12초
응답률: 90% (3건 timeout)
만족도: 4.5/5.0

⚠️ 개선 필요 질문
1. "환불 정책" - HITL 10건, 지식 베이스 부족
2. "특정 직원 일정" - HITL 8건, 캘린더 연동 필요
3. "결제 방법" - 답변 일관성 부족

📞 통화 이력 상세
─────────────────────────
[클릭하여 펼치기 ▼]

2026-03-10 14:23 | 010-1234-5678
├─ 구분: AI 응대
├─ 주제: 영업시간 문의
├─ 만족도: ⭐⭐⭐⭐⭐
└─ 💬 대화 내용
   AI: "안녕하세요..."
   고객: "영업시간이..."
   [전체 보기]

작업:
[📞 재전화] [✖ 블랙리스트] [⬇ 녹음 다운로드]
```

**효과**:
- ✅ 데이터 기반 의사결정
- ✅ 서비스 개선 포인트 발굴
- ✅ 지식 베이스 갭 분석
- ✅ 운영 효율성 향상

---

## 🏗️ 아키텍처 동작 구조

### 전체 시스템 플로우

```
┌─────────────────────────────────────────────────────────────────┐
│                    시스템 동작 흐름도                             │
└─────────────────────────────────────────────────────────────────┘

1. 통화 시작 (SIP Layer)
──────────────────────────
발신자 → SIP INVITE → Call Manager
  ↓
Call Manager → 착신자 호출 (10초 대기)
  ↓
타임아웃 or 부재중?
  YES → AI 모드 활성화
  NO → 일반 통화 연결

2. AI 모드 활성화 (Audio Layer)
──────────────────────────
Call Manager → RTP Relay Worker (AI Mode)
  ↓
RTP Packets → PCM Queue (maxsize: 150)
  ↓
Pipecat Pipeline 시작
  ├─ Silero VAD (음성 활동 감지)
  ├─ Smart Turn (발화 종료 감지)
  └─ Google STT (음성→텍스트)

3. AI 처리 (Intelligence Layer)
──────────────────────────
STT 텍스트 → LangGraph Agent
  ↓
┌─────────────────────────────────┐
│ LangGraph Workflow              │
├─────────────────────────────────┤
│ 1. classify_intent              │
│    → 의도 분석 (18가지)          │
│ 2. check_cache                  │
│    → 캐시 확인 (0.1초)           │
│ 3. rewrite_query                │
│    → 질문 재작성                 │
│ 4. adaptive_rag                 │
│    → VectorDB 검색              │
│ 5. generate_response            │
│    → LLM 응답 생성 (Streaming)   │
│ 6. hitl_alert (신뢰도 < 0.6)    │
│    → 운영자 요청                 │
│ 7. update_cache                 │
│    → 캐시 저장                   │
│ 8. update_state                 │
│    → 대화 상태 업데이트          │
└─────────────────────────────────┘
  ↓
응답 텍스트 (Streaming)

4. 음성 합성 (TTS Layer)
──────────────────────────
응답 텍스트 → Google TTS (Streaming)
  ↓
PCM Audio → RTP Packets
  ↓
RTP Relay Worker → 발신자

5. 동시 처리 (Concurrent)
──────────────────────────
[Frontend WebSocket]
  └─ 실시간 이벤트 전송
     ├─ call:new
     ├─ transcript (STT/TTS)
     ├─ hitl:request
     └─ call:ended

[Database]
  └─ 비동기 저장
     ├─ PostgreSQL (통화 이력)
     ├─ Redis (실시간 상태)
     └─ VectorDB (지식 베이스)

6. 통화 종료 (Cleanup Layer)
──────────────────────────
BYE 수신 → Call Manager
  ↓
RTP Relay Stop
  ↓
Pipecat Pipeline Stop
  ↓
지식 추출 트리거
  ├─ STT 전사 로드
  ├─ LLM 분석
  ├─ 유용성 판단
  └─ VectorDB 저장

CDR 생성 → logs/
WebSocket: call:ended → Frontend
```

### 핵심 컴포넌트 상호작용

```
┌───────────────────────────────────────────────────────────────┐
│                  컴포넌트 간 통신 흐름                          │
└───────────────────────────────────────────────────────────────┘

[SIP Layer]
  ├─ SIPEndpoint: UDP 5060 listen
  │   └─ asyncio.DatagramProtocol
  │       └─ SIP 메시지 파싱/생성
  │
  ├─ CallManager: 통화 상태 관리
  │   ├─ caller_leg: Dict[call_id, LegState]
  │   ├─ callee_leg: Dict[call_id, LegState]
  │   └─ ai_sessions: Dict[call_id, AIOrchestrator]
  │
  └─ RTPRelayWorker: 미디어 중계
      ├─ _standard_mode(): 일반 RTP relay
      └─ _pipecat_mode(): AI RTP routing
          └─ _pipecat_pcm_queue: asyncio.Queue(150)

[AI Layer - Pipecat]
  ├─ Custom RTP Transport
  │   └─ send_audio() / receive_audio()
  │
  ├─ Pipeline Processors
  │   ├─ VADProcessor (Silero)
  │   ├─ SmartTurnDetector
  │   ├─ STTProcessor (Google)
  │   ├─ RAGProcessor (LangGraph)
  │   └─ TTSProcessor (Google)
  │
  └─ Audio Buffer
      └─ Jitter compensation

[Intelligence Layer - LangGraph]
  ├─ StateGraph
  │   ├─ ConversationState (shared)
  │   └─ 8 Nodes (classify → cache → rag → generate → ...)
  │
  ├─ VectorDB Client
  │   ├─ ChromaDB (local dev)
  │   └─ Pinecone (production)
  │
  └─ LLM Client
      └─ Gemini 2.5 Flash (Streaming)

[API Layer]
  ├─ FastAPI (8000)
  │   ├─ /api/call-history
  │   ├─ /api/calls/{id}/hangup
  │   ├─ /api/outbound/call
  │   └─ /api/knowledge/*
  │
  └─ Socket.IO (8001)
      ├─ WebSocket connections
      ├─ Room-based events
      └─ Real-time broadcast

[Storage Layer]
  ├─ PostgreSQL
  │   ├─ call_history
  │   ├─ hitl_requests
  │   └─ unresolved_hitl_requests
  │
  ├─ Redis
  │   ├─ operator_status:{owner}
  │   ├─ session:{call_id}
  │   └─ cache:semantic:{hash}
  │
  └─ VectorDB
      ├─ knowledge_base collection
      └─ semantic_cache collection
```

### 성능 최적화 전략

```
1. 비동기 I/O (asyncio)
──────────────────────────
- 모든 네트워크 I/O: aiohttp, asyncpg
- RTP 패킷 처리: asyncio.Queue
- LLM 호출: Streaming API
→ 1,000+ 동시 연결 가능

2. 캐싱 전략
──────────────────────────
- L1: 메모리 (dict) - 1ms
- L2: Redis - 5ms
- L3: VectorDB - 50ms
→ Cache Hit Rate: 85%

3. 커넥션 풀
──────────────────────────
- PostgreSQL: 20 connections
- Redis: 10 connections
- HTTP: aiohttp session reuse
→ 연결 생성 오버헤드 제거

4. Batch Processing
──────────────────────────
- RTP Packets: 20ms 단위 batch
- Database Writes: 100ms 단위 batch
- WebSocket Events: 50ms 단위 batch
→ CPU 사용률 30% 감소

5. Streaming
──────────────────────────
- LLM: 첫 토큰 0.5초
- TTS: 첫 청크 0.2초
- STT: 실시간 partial results
→ 응답 시작 시간 70% 단축
```

---

## 🎯 주요 사용 시나리오

### 1️⃣ 일반 통화 (AI 미사용)

```
Caller → PBX → Callee (10초 내 응답)
        ↓
    RTP Relay (직접 중계, <5ms)
        ↓
    통화 종료 → CDR 생성
```

**특징**:
- 표준 SIP B2BUA 동작
- 저지연 RTP 직접 릴레이
- 통화 녹음 (선택)
- CDR 및 메트릭 수집

### 2️⃣ AI 자동 응답 (부재중 응대)

```
Caller → PBX → [10초 timeout] → AI Orchestrator 활성화
        ↓                              ↓
    RTP Relay                      STT/TTS/LLM
        ↓                              ↓
    AI 음성 전달 ←─────────────── RAG 검색 + 응답 생성
        ↓
    통화 종료 → 지식 추출 → Vector DB 저장
```

**워크플로우**:
1. Callee 10초 무응답
2. AI Orchestrator 시작
3. **Phase 1 인사말**: "안녕하세요, 무엇을 도와드릴까요?"
4. **Phase 2 Capability 가이드**: Vector DB에서 capability 로드 → 안내
5. 실시간 대화 (STT → RAG → LLM → TTS)
6. 통화 종료 → 전사 → 지식 추출 → 저장

**응답 시간**:
- High Confidence: **평균 0.9초**
- Medium Confidence: **평균 1.3초**
- HITL (운영자 개입): **평균 20초**

### 3️⃣ Human-in-the-Loop (낮은 신뢰도)

```
Caller → AI → [신뢰도 < 0.6] → HITL Request
               ↓                      ↓
          Hold Music          Frontend Alert (🔔)
               ↓                      ↓
          [대기 중...]         Operator Types Answer
               ↓                      ↓
          LLM Refinement ◄──────── Human Response
               ↓
          Final Answer → Caller
               ↓
       Save to Knowledge Base
```

**워크플로우**:
1. AI가 적절한 답변을 찾지 못함 (RAG score < 0.6)
2. 발신자: "잠시만 확인 중이니 기다려 주세요" + 대기 음악
3. Frontend: 🔔 알림 + 질문 표시
4. 운영자: 답변 입력 (20초 이내)
5. LLM: 답변 자연스럽게 다듬기
6. AI: 발신자에게 답변
7. 답변 Vector DB 저장 (재사용)

**Timeout 처리**:
- 20초 내 응답 없음 → "확인 후 다시 안내드리겠습니다" → 통화 종료
- 운영자 부재중 → 즉시 "확인 후 안내드리겠습니다" → 통화 종료

### 4️⃣ 통화 이력 관리 (Frontend)

```
Frontend Call History Page
  ↓
클릭하여 Rolldown (▶ → ▼)
  ↓
대화 내용 표시
  - 🤖 AI 응답 (파란색)
  - 👤 사용자 발화 (회색)
  - 타임스탬프

작업 버튼:
  📞 발신 - 해당 번호로 다시 전화
  ✖ 종료 - 진행 중인 통화 종료
  ⬇ 녹음 - 녹음 파일 다운로드
```

**기능**:
- 페이지네이션 (20개/페이지)
- 실시간 상태 표시 (진행중/완료)
- AI 응대 구분 (Badge)
- 대화 내용 Rolldown
- 발신/종료/녹음 원클릭

### 5️⃣ 상담원 실시간 개입 (Operator Takeover)

```
[AI 응대 중 상담원 개입]

1. Frontend: 실시간 AI 통화 모니터링
   └─ "전화 받기" 버튼 클릭

2. WebSocket: operator_takeover 이벤트
   └─ Backend 즉시 처리

3. SIP Layer:
   ├─ 상담원(1004)에게 INVITE 전송
   ├─ 200 OK 대기 (10초 timeout)
   └─ AI: "담당자 연결 중입니다"

4. 상담원 응답:
   ├─ AI Pipeline 안전 종료
   │  ├─ STT 중지
   │  ├─ TTS 중지
   │  └─ LLM 처리 취소
   │
   ├─ RTP Relay 모드 전환
   │  └─ AI Mode → Bypass Mode
   │
   └─ 발신자에게 re-INVITE
      └─ SDP: 상담원 RTP 주소

5. 통화 전환 완료:
   발신자 ◄──RTP──► 상담원
   (끊김 없음, <500ms)
```

**특징**:
- 실시간 모니터링으로 상황 파악
- 원클릭 개입 (<2초)
- AI → 상담원 매끄러운 전환
- 에러 처리 (Busy/No Answer → AI 복원)

---

## 🔄 데이터 플로우

### 일반 통화 플로우

```
1. SIP 시그널링
   Caller → SIP Endpoint → Call Manager → SIP Endpoint → Callee

2. RTP 미디어 (Bypass 모드)
   Caller RTP → Port A (PBX) → RTP Relay → Port B (PBX) → Callee RTP

3. 통화 종료
   BYE → Call Manager → RTP Stop → CDR 생성 → Webhook 발송
```

### AI 응대 통화 플로우

```
1. AI 활성화
   Timeout/부재중 → Call Manager → AI Orchestrator Start → RTP Mode Switch

2. 음성 → 텍스트
   Caller RTP → RTP Worker → Pipecat → Google STT → Text

3. 지능형 응답
   Text → RAG Search (Vector DB) → LLM (Gemini) → Response Text

4. 텍스트 → 음성
   Response Text → Google TTS → PCM Queue (150 frames) → RTP Packets → Caller

5. 지식 추출 (통화 종료 후)
   전사 로드 → LLM 분석 → 지식 추출 → Vector DB 저장
```

### HITL 플로우

```
1. 신뢰도 낮음 감지
   RAG Score < 0.6 → HITL Trigger

2. 운영자 요청
   HITL Service → WebSocket → Frontend Alert (🔔)

3. 대기 음악
   AI → TTS("잠시만 기다려주세요") → Hold Music Loop

4. 운영자 응답
   Frontend Input → WebSocket → HITL Service → LLM Refine → TTS → Caller

5. 지식 저장
   Q&A Pair → Vector DB (자동 저장)
```

---

## 📊 성능 지표

### AI 응답 시간

| 시나리오 | 평균 | P95 | P99 |
|----------|------|-----|-----|
| **High Confidence** | 0.9초 | 1.2초 | 1.5초 |
| **Medium Confidence** | 1.3초 | 1.8초 | 2.2초 |
| **HITL (운영자 개입)** | 20초 | 35초 | 60초 |

**응답 시간 분해**:
- RAG 검색: ~75ms
- LLM 생성: ~413ms
- TTS 첫 청크: ~235ms
- **총합**: ~923ms

### 비용 분석 (월 100통화 기준)

| 서비스 | 일일 비용 | 월 비용 |
|--------|-----------|---------|
| **Gemini 2.5 Flash** | ₩46 | ₩1,400 |
| **Google STT** | ₩100 | ₩3,000 |
| **Google TTS** | ₩66 | ₩2,000 |
| **Vector DB (ChromaDB)** | ₩0 (local) | ₩0 |
| **총합** | **₩212** | **₩6,400** |

> 💡 Gemini Pro 사용 시: **₩23,400/월** (3.6배 더 비쌈)

### 시스템 용량

| 메트릭 | 용량 |
|--------|------|
| **동시 통화** | 100+ |
| **동시 AI 세션** | 50+ |
| **WebSocket 연결** | 1,000+ |
| **API 요청** | 10,000+/분 |
| **Vector DB 크기** | 1M+ documents |
| **RTP 지연** | <5ms |
| **통화 설정 시간** | ~200ms |

---

## 🛠️ 기술 스택

### Backend

| 카테고리 | 기술 |
|---------|-----|
| **언어** | Python 3.11+ |
| **프레임워크** | FastAPI, asyncio, aiohttp |
| **SIP/RTP** | 순수 Python 구현 |
| **WebSocket** | Socket.IO, python-socketio |
| **Database** | PostgreSQL (asyncpg), Redis |
| **AI/ML** | Google Gemini 2.5 Flash, Sentence Transformers, PyTorch |
| **Vector DB** | ChromaDB (dev), Pinecone (prod) |
| **Audio** | opuslib, G.711, WebRTC VAD |
| **모니터링** | Prometheus, structlog |

### Frontend

| 카테고리 | 기술 |
|---------|-----|
| **프레임워크** | Next.js 14, React 18 |
| **언어** | TypeScript |
| **스타일링** | TailwindCSS |
| **상태 관리** | Zustand |
| **WebSocket** | Socket.IO Client |
| **빌드** | Turbopack (Next.js 14) |

### External Services

| 서비스 | 용도 |
|--------|------|
| **Google Cloud STT** | 음성 → 텍스트 (Telephony 모델) |
| **Google Cloud TTS** | 텍스트 → 음성 (Neural2) |
| **Google Gemini 2.5 Flash** | LLM 대화 생성 (초저비용) |

---

## 📁 주요 컴포넌트

### Backend 컴포넌트

| 컴포넌트 | 파일 | 역할 |
|----------|------|------|
| **SIP Endpoint** | `src/sip_core/sip_endpoint.py` | SIP 메시지 파싱/생성, Transaction 관리 |
| **Call Manager** | `src/sip_core/call_manager.py` | B2BUA 로직, 통화 상태 추적 |
| **RTP Relay** | `src/media/rtp_relay.py` | RTP 패킷 중계, PCM 큐 관리 (maxsize=150) |
| **RTP Transport** | `src/ai_voicebot/pipecat/rtp_transport.py` | Pipecat → RTP, 재생 길이 동기화 |
| **AI Orchestrator** | `src/ai_voicebot/orchestrator.py` | AI 세션 관리, 파이프라인 제어 |
| **RAG Processor** | `src/ai_voicebot/pipecat/processors/rag_processor.py` | RAG 검색, LLM 응답 생성 |
| **HITL Service** | `src/services/hitl_service.py` | call_id별 큐, 20초 timeout, fallback |
| **API Gateway** | `src/api/main.py` | FastAPI REST API |
| **WebSocket Server** | `src/websocket/server.py` | Socket.IO 실시간 통신 |

### Frontend 컴포넌트

| 컴포넌트 | 파일 | 역할 |
|----------|------|------|
| **Call History** | `frontend/app/call-history/page.tsx` | 통화 이력, Rolldown, 작업 버튼 |
| **Live Monitor** | `frontend/app/dashboard/page.tsx` | 실시간 통화 모니터링 |
| **Knowledge Manager** | `frontend/app/knowledge/page.tsx` | 지식 베이스 CRUD |
| **HITL Interface** | `frontend/components/HITLDialog.tsx` | 운영자 응답 UI |
| **WebSocket Hook** | `frontend/hooks/useWebSocket.ts` | Socket.IO 연결 관리 |

---

## 🔐 보안 및 프라이버시

### 인증 및 권한

- ✅ **JWT 토큰** - API 인증
- ✅ **OAuth2** - 소셜 로그인
- ✅ **RBAC** - 역할 기반 접근 제어 (Admin/Operator/Viewer)
- ✅ **WebSocket 인증** - 토큰 기반

### 데이터 보안

- ✅ **TLS/SSL** - 모든 외부 연결 암호화
- ✅ **환경 변수** - 민감 정보 관리
- ✅ **Database 암호화** - 저장 데이터 암호화
- ✅ **로그 마스킹** - PII 정보 마스킹

### 컴플라이언스

- ✅ **통화 녹음 동의** - 설정 가능
- ✅ **GDPR 준수** - 데이터 보관 정책
- ✅ **감사 로그** - 운영자 작업 기록

---

## 📈 모니터링 및 관찰성

### Prometheus 메트릭

**통화 메트릭**:
- `active_calls_total` - 현재 활성 통화 수
- `call_duration_seconds` - 통화 시간 히스토그램
- `ai_activated_calls_total` - AI 응대 통화 수

**AI 메트릭**:
- `ai_response_time_seconds` - AI 응답 시간
- `ai_confidence_score` - AI 신뢰도 분포
- `rag_search_time_seconds` - RAG 검색 지연

**HITL 메트릭**:
- `hitl_requests_total` - HITL 요청 수
- `hitl_response_time_seconds` - 운영자 응답 시간
- `hitl_queue_size` - 대기 큐 크기

**비용 메트릭**:
- `llm_tokens_used_total` - LLM 토큰 사용량
- `stt_duration_seconds_total` - STT 오디오 길이
- `tts_characters_total` - TTS 문자 수

### 구조화된 로그 (structlog)

```json
{
  "timestamp": "2026-03-10T10:30:45.123Z",
  "level": "info",
  "event": "ai_response_time_breakdown",
  "call_id": "abc-123",
  "rag_search_ms": 75.2,
  "llm_generation_ms": 412.8,
  "tts_first_chunk_ms": 235.1,
  "total_response_ms": 923.5
}
```

---

## 🚀 배포 옵션

### 개발 환경

```bash
# 전체 시스템 실행
.\start-all.ps1

# Frontend: http://localhost:3000
# API: http://localhost:8000
# WebSocket: ws://localhost:8001
```

### 프로덕션 환경

**옵션 1: 단일 서버**
- Ubuntu 22.04 LTS
- 8 CPU, 16GB RAM
- Docker + Docker Compose
- Nginx reverse proxy

**옵션 2: Kubernetes**
- Frontend: Vercel / Netlify
- Backend: GKE / EKS
- Database: Cloud SQL / RDS
- Vector DB: Pinecone Cloud

**옵션 3: 하이브리드**
- Frontend: Vercel (CDN)
- Backend: On-premise VM
- AI Services: Google Cloud
- Vector DB: Self-hosted ChromaDB

---

## 📚 관련 문서

### 핵심 문서

| 문서 | 설명 |
|------|------|
| **[README.md](../README.md)** | 프로젝트 개요 및 빠른 시작 |
| **[INDEX.md](INDEX.md)** | 전체 문서 인덱스 |
| **[QUICK_START.md](QUICK_START.md)** | 5분 설치 가이드 |

### 아키텍처 문서

| 문서 | 설명 |
|------|------|
| **[architecture/ai-voicebot-architecture.md](architecture/ai-voicebot-architecture.md)** | AI Voicebot 완전한 설계 (5,000+ lines) |
| **[architecture/frontend-architecture.md](architecture/frontend-architecture.md)** | Frontend 상세 설계 (2,300+ lines) |
| **[architecture/voice-ai-conversation-engine.md](architecture/voice-ai-conversation-engine.md)** | Voice AI 대화 엔진 |

### 설계 문서

| 문서 | 설명 |
|------|------|
| **[design/TTS_RTP_AND_STT_QUEUE_DESIGN.md](design/TTS_RTP_AND_STT_QUEUE_DESIGN.md)** | TTS→RTP 파이프라인, PCM 큐 설계 |
| **[design/TTS_RTP_STRUCTURE_REVIEW.md](design/TTS_RTP_STRUCTURE_REVIEW.md)** | TTS→큐→RTP 구조 검토 및 이슈 분석 |
| **[design/OPERATOR-AWAY-MODE-DESIGN.md](design/OPERATOR-AWAY-MODE-DESIGN.md)** | 운영자 부재중 모드 상세 설계 |
| **[design/OPERATOR_TAKEOVER_DESIGN.md](design/OPERATOR_TAKEOVER_DESIGN.md)** | 상담원 실시간 개입 (Takeover) 설계 (NEW) |
| **[design/TEMPORAL_EXPRESSION_DESIGN.md](design/TEMPORAL_EXPRESSION_DESIGN.md)** | 한글 시제 표현 정규화 설계 (NEW) |
| **[design/INTENT_HANDLING_DESIGN.md](design/INTENT_HANDLING_DESIGN.md)** | Intent별 처리 로직 상세 (예제·도표, 18가지 의도 → 노드·응답) |

### 가이드

| 문서 | 설명 |
|------|------|
| **[guides/USER_MANUAL.md](guides/USER_MANUAL.md)** | 사용자 매뉴얼 |
| **[guides/TROUBLESHOOTING.md](guides/TROUBLESHOOTING.md)** | 문제 해결 가이드 |
| **[guides/google-api-setup.md](guides/google-api-setup.md)** | Google Cloud API 설정 |

---

## 🎯 사용 사례

### 1. 소규모 기업 접수 자동화

**문제**: 영업시간 외 고객 문의 누락
**해결**: AI 자동 응답으로 24시간 응대
**효과**: 
- 고객 만족도 ↑
- 인건비 절감
- 지식 베이스 자동 구축

### 2. 콜센터 1차 응대

**문제**: 반복적인 FAQ 질문 처리 부담
**해결**: AI가 FAQ 자동 응답, 복잡한 질문만 상담원 전달
**효과**:
- 상담원 업무 부하 30% 감소
- 평균 응답 시간 60% 단축
- 고객 대기 시간 감소

### 3. 의료 기관 예약 안내

**문제**: 전화 예약 문의 집중 시간대 대응 어려움
**해결**: AI가 진료 시간, 예약 가능 시간 안내
**효과**:
- 예약 담당 인력 50% 감소
- 환자 편의성 향상
- 24시간 정보 제공

---

## 🔮 로드맵

### ✅ Phase 1: Core AI (완료)
- SIP B2BUA 구현
- AI 자동 응답
- STT/TTS/LLM 통합
- RAG 지식 검색
- 통화 녹음

### ✅ Phase 2: Frontend & HITL (완료)
- 웹 대시보드
- 실시간 모니터링
- 지식 베이스 관리
- Human-in-the-Loop
- 통화 이력 관리 (발신/종료/녹음)
- 상담원 실시간 개입 (Operator Takeover)
- 시제 표현 정규화

### 🚧 Phase 3: 고급 기능 (진행중)
- [ ] 멀티 언어 지원
- [ ] 고급 분석 대시보드
- [ ] CRM 연동
- [ ] A/B 테스트 프레임워크
- [ ] 모바일 앱

### 🌟 Phase 4: Enterprise (계획)
- [ ] 멀티 테넌트 지원
- [ ] SSO 통합
- [ ] 커스텀 AI 모델 학습
- [ ] 화이트 라벨 프론트엔드
- [ ] Enterprise SLA

---

## 📞 지원 및 문의

- **Issues**: [GitHub Issues](https://github.com/hak023/sip_pbx/issues)
- **Discussions**: [GitHub Discussions](https://github.com/hak023/sip_pbx/discussions)
- **Email**: hak023@example.com

---

## 📄 라이선스

MIT License - 자세한 내용은 [LICENSE](../LICENSE) 참조

---

**Built with ❤️ by Winston (Architect) & Team**

*최종 업데이트: 2026-03-10*
