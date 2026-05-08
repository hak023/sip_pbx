# AI Outbound Call (AI 발신 통화) 기능 설계서
> **클러스터 안내**: 세부·히스토리 설계 문서입니다. 통합 관점·경계는 아래 대표 문서를 우선 참고하세요.
> 
> **대표 문서**: [`multi-tenant-rag-and-dashboard.md`](multi-tenant-rag-and-dashboard.md)
>
---


> **Version**: 1.1  
> **Date**: 2026-01-29  
> **Status**: Implemented  
> **Author**: AI Assistant  

---

## 1. 개요

### 1.1 목적

유저(운영자)가 웹 대시보드를 통해 **발신번호, 착신번호, 통화 목적, 확인 필요 사항**을 입력하면, AI가 해당 고객에게 **자동으로 전화를 걸어 목적을 전달하고 확인 사항을 질문한 뒤**, 결과를 웹에서 확인할 수 있는 기능을 설계한다.

### 1.2 핵심 시나리오

```
1. 운영자가 웹 UI에서 아웃바운드 콜 요청 생성
   - 발신번호: 070-1234-5678
   - 착신번호: 010-9876-5432
   - 통화 목적: "내일 오후 2시 미팅 일정 확인"
   - 확인 사항: "참석 가능 여부", "장소 변경 필요 여부"

2. 서버가 SIP INVITE를 착신번호로 발신
   - B2BUA가 직접 INVITE 생성 (서버 → 착신자)
   - SDP에 서버 미디어 정보 포함

3. 착신자가 전화를 받으면 AI 대화 시작
   - AI: "안녕하세요, [회사명] AI 비서입니다. 내일 오후 2시 미팅 일정 관련하여 연락드렸습니다."
   - AI: "참석 가능하신지 확인 부탁드립니다."
   - 고객: "네, 참석 가능합니다."
   - AI: "감사합니다. 장소 변경이 필요하신 부분이 있으신가요?"
   - 고객: "아니요, 기존 장소로 괜찮습니다."
   - AI: "확인 감사합니다. 좋은 하루 되세요."

4. 통화 종료 후 결과 저장
   - 대화록 (transcript)
   - 각 확인 사항별 응답 결과
   - 통화 상태, 시간 등 메타데이터

5. 운영자가 웹에서 결과 확인
   - 통화 상태 (성공/실패/미응답)
   - 전체 대화록
   - 확인 사항별 응답 요약
```

### 1.3 핵심 원칙

| 원칙 | 설명 |
|------|------|
| **Server-Initiated Call** | B2BUA가 직접 SIP INVITE를 생성하여 발신 (인바운드 호 없음) |
| **Goal-Oriented Dialogue** | 통화 목적과 확인 사항을 기반으로 목적 지향적 대화 수행 |
| **Task Completion Detection** | LLM이 모든 확인 사항에 대한 응답을 받았는지 판단 |
| **Structured Result** | 대화 결과를 구조화된 형태로 저장 (JSON) |
| **기존 인프라 재활용** | Transfer 기능의 SIP/RTP/AI 인프라를 최대한 재활용 |

---

## 2. 기술 리서치

### 2.1 업계 사례 분석

| 서비스 | 아키텍처 | 핵심 특징 |
|--------|----------|-----------|
| **Bland AI** | Self-hosted 풀스택 (STT+LLM+TTS 코로케이션) | Pathway 기반 대화 흐름, E.164 번호 API, < 500ms 레이턴시 |
| **Vapi** | 미들웨어 (외부 LLM 연동) | BYO-LLM, Function Calling, 유연한 커스텀 |
| **Retell AI** | 미들웨어 | 감정 인식, 멀티턴 대화, 대화 분석 |
| **LiveKit Agents** | 오픈소스 프레임워크 | SIP 트렁크 + Python Agent, Voicemail 감지, DTMF |
| **ElevenLabs** | TTS 특화 | 고품질 음성, 아웃바운드 에이전트, Revenue 최적화 |

### 2.2 오픈소스 참고 프로젝트

| 프로젝트 | 스택 | 참고 포인트 |
|----------|------|-------------|
| [livekit-examples/outbound-caller-python](https://github.com/livekit-examples/outbound-caller-python) | LiveKit + Python | 아웃바운드 콜 워크플로우, Voicemail 감지, Function Calling |
| [aicc2025/sip-to-ai](https://github.com/aicc2025/sip-to-ai) | Pure asyncio Python | SIP → AI 브릿지, G.711 코덱 변환, 멀티 AI 모델 지원 |
| [videosdk-community/ai-telephony-demo](https://github.com/videosdk-community/ai-telephony-demo) | VideoSDK + Gemini | 인바운드/아웃바운드, SIP 트렁크, 라우팅 규칙 |

### 2.3 핵심 기술 요소

#### 2.3.1 서버 발신 SIP (RFC 3725 - 3PCC)

기존 Transfer 구현에서 이미 3PCC 패턴을 사용 중이며, Outbound Call은 이를 단순화한 형태:

```
Transfer (기존):  Controller → INVITE(B) + Bridge(A↔B)   ← 2개 레그
Outbound (신규):  Controller → INVITE(B) + AI(Server↔B)  ← 1개 레그
```

| 항목 | Transfer | Outbound |
|------|----------|----------|
| 발신 트리거 | AI가 RAG로 감지 | 유저가 웹 UI로 요청 |
| 원래 호 존재 | 있음 (발신자↔AI) | 없음 |
| SIP INVITE | 서버 → 착신자 | 서버 → 착신자 (동일) |
| 미디어 모드 | BRIDGE (Caller↔Callee) | AI (Server↔Callee) |
| AI 역할 | 전환 후 없음 | 전 통화 중 대화 수행 |

#### 2.3.2 Goal-Oriented Dialogue (목적 지향 대화)

최신 연구 (Conversation Routines, InstructTODS)에서 검증된 접근법:

```
┌─────────────────────────────────────────────────┐
│           Goal-Oriented Dialogue Flow            │
├─────────────────────────────────────────────────┤
│                                                   │
│  System Prompt (Dynamic)                          │
│  ├─ Role: "AI 비서" (발신자 역할 명시)            │
│  ├─ Purpose: "{통화 목적}"                        │
│  ├─ Questions: ["{확인사항1}", "{확인사항2}", ...] │
│  ├─ Rules:                                        │
│  │   ├─ 목적을 먼저 밝힐 것                       │
│  │   ├─ 확인 사항을 하나씩 질문할 것              │
│  │   ├─ 답변이 불명확하면 재질문할 것             │
│  │   └─ 모두 확인되면 끝인사 후 종료              │
│  └─ Output: 각 확인사항별 결과 JSON               │
│                                                   │
│  Dialogue Turn Loop                               │
│  ├─ AI Greeting → Purpose Statement               │
│  ├─ For each question:                            │
│  │   ├─ Ask question                              │
│  │   ├─ Listen to response                        │
│  │   ├─ Validate: 충분한 답변인가?                │
│  │   │   ├─ Yes → Mark complete, next question    │
│  │   │   └─ No → Clarify / Re-ask                 │
│  │   └─ Update task_state                         │
│  ├─ All questions answered?                       │
│  │   ├─ Yes → Closing greeting → BYE              │
│  │   └─ No → Continue dialogue                    │
│  └─ Abnormal: 상대방 거부/끊음 → 결과 저장       │
│                                                   │
└─────────────────────────────────────────────────┘
```

#### 2.3.3 Task Completion Detection (태스크 완료 판정)

LLM에게 대화 상태를 구조화하여 추적시킴:

```json
{
  "task_state": {
    "purpose_stated": true,
    "questions": [
      {
        "id": "q1",
        "text": "참석 가능 여부",
        "status": "answered",          // pending | answered | unclear | refused
        "answer": "참석 가능",
        "confidence": 0.95
      },
      {
        "id": "q2", 
        "text": "장소 변경 필요 여부",
        "status": "pending",
        "answer": null,
        "confidence": 0.0
      }
    ],
    "all_completed": false,
    "should_end_call": false
  }
}
```

### 2.4 기존 코드베이스 재활용 분석

| 컴포넌트 | 재활용 가능 영역 | 수정 필요 사항 | 신규 구현 |
|----------|-----------------|---------------|-----------|
| **SIP Endpoint** | `send_transfer_invite`, `_resolve_transfer_target`, CANCEL/BYE | 외부번호 → SIP Gateway 라우팅 | `send_outbound_invite()` |
| **AI Orchestrator** | `handle_call`, STT/TTS/LLM, `speak()`, `on_audio_packet()` | 아웃바운드 전용 진입점, 발신자/착신자 방향 조정 | `handle_outbound_call()` |
| **RTP Relay** | AI 모드 전체 (STT 스트리밍, TTS 재생) | 아웃바운드 세션 생성 | 미디어 세션 초기화 경로 |
| **Transfer Manager** | 콜백 패턴, 상태 머신, Ring Timeout | 아웃바운드 전용 흐름 (Announce 없음, Bridge 없음) | `OutboundCallManager` |
| **Config** | `TransferConfig` 패턴 | 아웃바운드 설정 섹션 | `OutboundConfig` |
| **API Router** | FastAPI 패턴, Pydantic 모델 | 아웃바운드 전용 엔드포인트 | `outbound.py` 라우터 |
| **Frontend** | Transfer 페이지 레이아웃/테이블/통계 | 아웃바운드 전용 UI | 요청 폼 + 이력 페이지 |

---

## 3. 시스템 아키텍처

### 3.1 전체 아키텍처

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Outbound Call System                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌──────────────┐     ┌──────────────────────────────────────────────┐ │
│  │  Frontend     │     │              Backend Server                  │ │
│  │  (Next.js)    │     │                                              │ │
│  │              │     │  ┌──────────────┐   ┌─────────────────────┐ │ │
│  │ [요청 폼]    │────►│  │ Outbound API │──►│ OutboundCallManager │ │ │
│  │              │ REST│  │ (FastAPI)    │   │                     │ │ │
│  │ [결과 조회]  │◄────│  └──────────────┘   │ ├─ initiate_call()  │ │ │
│  │              │     │                      │ ├─ on_answered()    │ │ │
│  │ [실시간현황] │◄─WS─│                      │ ├─ on_completed()   │ │ │
│  └──────────────┘     │                      │ └─ on_failed()      │ │ │
│                        │                      └──────────┬──────────┘ │ │
│                        │                                 │             │ │
│                        │          ┌──────────────────────┼─────┐      │ │
│                        │          │                      ▼     │      │ │
│                        │          │  ┌──────────────────────┐  │      │ │
│                        │          │  │   SIP Endpoint       │  │      │ │
│                        │          │  │   send_outbound_     │  │      │ │
│                        │          │  │   invite()           │  │      │ │
│  ┌──────────────┐     │          │  └────────┬─────────────┘  │      │ │
│  │  Customer     │     │          │           │ SIP INVITE     │      │ │
│  │  (착신자)     │◄────┼──────────┼───────────┘                │      │ │
│  │              │     │          │                             │      │ │
│  │              │ SIP │          │  ┌──────────────────────┐  │      │ │
│  │              │◄───►│          │  │   RTP Relay (AI Mode)│  │      │ │
│  │              │ RTP │          │  │   Server ↔ Customer  │  │      │ │
│  └──────────────┘     │          │  └────────┬─────────────┘  │      │ │
│                        │          │           │                │      │ │
│                        │          │  ┌────────▼─────────────┐  │      │ │
│                        │          │  │   AI Orchestrator    │  │      │ │
│                        │          │  │   (Outbound Mode)    │  │      │ │
│                        │          │  │   ├─ STT (Listen)    │  │      │ │
│                        │          │  │   ├─ LLM (Dialogue)  │  │      │ │
│                        │          │  │   ├─ TTS (Speak)     │  │      │ │
│                        │          │  │   └─ Task Tracker    │  │      │ │
│                        │          │  └──────────────────────┘  │      │ │
│                        │          └────────────────────────────┘      │ │
│                        └──────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

### 3.2 호 흐름 시퀀스

```
 Operator(Web)      Backend API      OutboundMgr      SIPEndpoint       Customer
      │                  │                │                │                │
      │  POST /outbound  │                │                │                │
      │  {from,to,       │                │                │                │
      │   purpose,       │                │                │                │
      │   questions}     │                │                │                │
      │─────────────────►│                │                │                │
      │                  │ initiate()     │                │                │
      │                  │───────────────►│                │                │
      │                  │                │ send_outbound  │                │
      │                  │                │ _invite()      │                │
      │                  │                │───────────────►│                │
      │                  │                │                │  SIP INVITE    │
      │                  │                │                │───────────────►│
      │  202 Accepted    │                │                │                │
      │  {outbound_id}   │                │                │                │
      │◄─────────────────│                │                │                │
      │                  │                │                │  180 Ringing   │
      │                  │                │  provisional   │◄───────────────│
      │                  │                │◄───────────────│                │
      │  WS: ringing     │                │                │                │
      │◄ ─ ─ ─ ─ ─ ─ ─ ─│                │                │                │
      │                  │                │                │  200 OK (+SDP) │
      │                  │                │  answered      │◄───────────────│
      │                  │                │◄───────────────│                │
      │                  │                │                │  ACK           │
      │                  │                │                │───────────────►│
      │                  │                │                │                │
      │                  │                │  start_ai()    │                │
      │                  │                │───────────────►│                │
      │  WS: connected   │                │                │                │
      │◄ ─ ─ ─ ─ ─ ─ ─ ─│                │                │   RTP ↔ AI    │
      │                  │                │                │◄══════════════►│
      │                  │                │                │                │
      │                  │                │                │   (AI 대화)    │
      │                  │                │                │   목적 전달    │
      │                  │                │                │   확인사항 질문│
      │                  │                │                │   답변 수집    │
      │                  │                │                │                │
      │                  │                │  task_complete  │                │
      │                  │                │◄───────────────│                │
      │                  │                │                │   BYE          │
      │                  │                │                │───────────────►│
      │  WS: completed   │                │                │                │
      │◄ ─ ─ ─ ─ ─ ─ ─ ─│                │                │                │
      │                  │                │  save_result   │                │
      │                  │                │───────────────►│                │
      │                  │                │                │                │
      │  GET /outbound   │                │                │                │
      │  /{id}/result    │                │                │                │
      │─────────────────►│                │                │                │
      │  {transcript,    │                │                │                │
      │   answers,       │                │                │                │
      │   summary}       │                │                │                │
      │◄─────────────────│                │                │                │
```

### 3.3 SIP 호 흐름 상세

```
    SIP PBX Server                                        Customer Phone
         │                                                      │
         │  INVITE sip:01098765432@gateway.example.com SIP/2.0  │
         │  From: <sip:07012345678@pbx.local>;tag=outb-xxx      │
         │  To: <sip:01098765432@gateway.example.com>           │
         │  Call-ID: outbound-call-xxxxx                        │
         │  CSeq: 1 INVITE                                      │
         │  Contact: <sip:pbx@{b2bua_ip}:{sip_port}>           │
         │  Content-Type: application/sdp                       │
         │  X-Outbound-Call-ID: ob-xxxxx                        │
         │                                                      │
         │  v=0                                                 │
         │  o=- {session_id} {session_ver} IN IP4 {b2bua_ip}   │
         │  s=Talk                                              │
         │  c=IN IP4 {b2bua_ip}                                │
         │  t=0 0                                               │
         │  m=audio {rtp_port} RTP/AVP 0 8 101                 │
         │  a=rtpmap:101 telephone-event/8000                   │
         │  a=rtcp:{rtcp_port}                                  │
         │─────────────────────────────────────────────────────►│
         │                                                      │
         │  SIP/2.0 100 Trying                                  │
         │◄─────────────────────────────────────────────────────│
         │                                                      │
         │  SIP/2.0 180 Ringing                                 │
         │◄─────────────────────────────────────────────────────│
         │                                                      │
         │  SIP/2.0 200 OK (+ SDP)                              │
         │◄─────────────────────────────────────────────────────│
         │                                                      │
         │  ACK sip:customer@{customer_ip} SIP/2.0              │
         │─────────────────────────────────────────────────────►│
         │                                                      │
         │  ═══════════ RTP (AI Mode) ═══════════               │
         │  Server audio port ◄──────► Customer audio port      │
         │                                                      │
         │  (AI 대화 진행...)                                    │
         │                                                      │
         │  BYE sip:customer@{customer_ip} SIP/2.0              │
         │─────────────────────────────────────────────────────►│
         │                                                      │
         │  SIP/2.0 200 OK                                      │
         │◄─────────────────────────────────────────────────────│
```

---

## 4. 데이터 모델

### 4.1 OutboundCallRequest (API 요청)

```python
class OutboundCallRequest(BaseModel):
    """유저가 웹에서 입력하는 아웃바운드 콜 요청"""
    caller_number: str                 # 발신번호 (e.g., "07012345678")
    callee_number: str                 # 착신번호 (e.g., "01098765432")
    purpose: str                       # 통화 목적 (e.g., "내일 오후 2시 미팅 일정 확인")
    questions: List[str]               # 확인 필요 사항 리스트
    # 선택 사항
    caller_display_name: Optional[str] # 발신자 표시 이름
    max_duration: int = 180            # 최대 통화 시간 (초, 기본 3분)
    priority: int = 5                  # 우선순위 (1-10)
    scheduled_at: Optional[datetime]   # 예약 발신 시간 (None이면 즉시)
    retry_on_no_answer: bool = True    # 미응답 시 재시도
    metadata: Optional[Dict] = None    # 사용자 정의 메타데이터
```

### 4.2 OutboundCallRecord (내부 레코드)

```python
@dataclass
class OutboundCallRecord:
    """아웃바운드 콜 전체 생명주기 레코드"""
    # 식별자
    outbound_id: str                    # "ob-{uuid[:8]}"
    call_id: Optional[str] = None       # SIP Call-ID (INVITE 발신 후 할당)
    
    # 요청 정보
    caller_number: str                  # 발신번호
    callee_number: str                  # 착신번호
    purpose: str                        # 통화 목적
    questions: List[str]                # 확인 사항 목록
    caller_display_name: str = ""       # 발신자 표시명
    max_duration: int = 180             # 최대 통화 시간
    
    # 상태
    state: OutboundCallState = OutboundCallState.QUEUED
    
    # 타임스탬프
    created_at: datetime                # 요청 생성 시각
    started_at: Optional[datetime]      # INVITE 발신 시각
    answered_at: Optional[datetime]     # 200 OK 수신 시각
    completed_at: Optional[datetime]    # 통화 종료 시각
    
    # 결과
    result: Optional[OutboundCallResult] = None
    
    # 시도 이력
    attempt_count: int = 0              # 시도 횟수
    max_retries: int = 2                # 최대 재시도
    failure_reason: Optional[str] = None
    
    # 메타데이터
    metadata: Optional[Dict] = None
    requested_by: str = "operator"      # 요청자
```

### 4.3 OutboundCallState (상태 머신)

```python
class OutboundCallState(str, Enum):
    """아웃바운드 콜 상태"""
    QUEUED = "queued"               # 대기열에 추가됨
    DIALING = "dialing"             # INVITE 발신 중
    RINGING = "ringing"             # 착신측 벨 울림 (180 수신)
    CONNECTED = "connected"         # 통화 연결 (200 OK, AI 대화 중)
    COMPLETED = "completed"         # 정상 완료 (모든 확인 사항 수집)
    NO_ANSWER = "no_answer"         # 미응답 (타임아웃)
    BUSY = "busy"                   # 통화중 (486)
    REJECTED = "rejected"           # 거절 (603)
    FAILED = "failed"               # 시스템 오류
    CANCELLED = "cancelled"         # 운영자 취소
```

### 4.4 OutboundCallResult (통화 결과)

```python
@dataclass
class OutboundCallResult:
    """아웃바운드 콜 결과"""
    # 대화 결과
    answers: List[QuestionAnswer]       # 각 확인 사항별 답변
    summary: str                        # LLM이 생성한 전체 요약
    task_completed: bool                # 모든 확인 사항 수집 완료 여부
    
    # 대화록
    transcript: List[TranscriptEntry]   # 전체 대화 기록
    
    # 통화 메타
    duration_seconds: int               # 통화 시간
    ai_turns: int                       # AI 발화 횟수
    customer_turns: int                 # 고객 발화 횟수
    
    # 감성 (향후)
    # customer_sentiment: Optional[str] = None

@dataclass
class QuestionAnswer:
    """개별 확인 사항 응답"""
    question_id: str                    # "q1", "q2", ...
    question_text: str                  # 원래 질문
    status: str                         # "answered" | "unclear" | "refused" | "not_asked"
    answer_text: Optional[str]          # 고객 응답 원문
    answer_summary: Optional[str]       # 요약된 답변
    confidence: float                   # 0.0 ~ 1.0

@dataclass  
class TranscriptEntry:
    """대화록 엔트리"""
    timestamp: float                    # 통화 시작 후 경과 시간 (초)
    speaker: str                        # "ai" | "customer"
    text: str                           # 발화 내용
```

---

## 5. 핵심 컴포넌트 설계

### 5.1 OutboundCallManager

전체 아웃바운드 콜 생명주기를 관리하는 핵심 컴포넌트.

```python
class OutboundCallManager:
    """AI Outbound Call 생명주기 관리"""
    
    def __init__(self, config: OutboundConfig):
        self.config = config
        self.call_queue: asyncio.Queue = asyncio.Queue()     # 대기열
        self.active_calls: Dict[str, OutboundCallRecord] = {}  # outbound_id → record
        self.call_id_map: Dict[str, str] = {}                # sip_call_id → outbound_id
        self.call_history: List[OutboundCallRecord] = []      # 완료된 콜 이력
        self._callbacks = {}
    
    # ── 콜백 설정 ──
    def set_callbacks(
        self,
        send_invite: Callable,      # SIPEndpoint.send_outbound_invite
        send_cancel: Callable,      # SIPEndpoint.send_outbound_cancel
        send_bye: Callable,         # SIPEndpoint.send_outbound_bye
        start_ai: Callable,         # AI 모드 시작
        stop_ai: Callable,          # AI 모드 중지
        emit_event: Callable,       # WebSocket 이벤트 발행
    ): ...
    
    # ── 콜 생명주기 ──
    async def create_call(self, request: OutboundCallRequest) -> OutboundCallRecord:
        """아웃바운드 콜 요청 생성 → 대기열 추가"""
        ...
    
    async def process_queue(self):
        """대기열에서 콜 꺼내서 발신 (동시 발신 수 제한)"""
        ...
    
    async def _dial(self, record: OutboundCallRecord):
        """실제 SIP INVITE 발신"""
        record.state = OutboundCallState.DIALING
        record.started_at = datetime.now()
        record.attempt_count += 1
        call_id = await self._send_invite_cb(
            to_number=record.callee_number,
            from_number=record.caller_number,
            outbound_id=record.outbound_id,
        )
        record.call_id = call_id
        self.call_id_map[call_id] = record.outbound_id
        # Ring timeout 설정
        self._schedule_ring_timeout(record)
    
    # ── SIP 응답 핸들러 ──
    async def on_provisional(self, call_id: str, status_code: int):
        """180 Ringing 등 수신"""
        record = self._get_record_by_call_id(call_id)
        if record and status_code == 180:
            record.state = OutboundCallState.RINGING
            await self._emit_event("outbound_ringing", record)
    
    async def on_answered(self, call_id: str, callee_sdp: str):
        """200 OK 수신 → AI 대화 시작"""
        record = self._get_record_by_call_id(call_id)
        if not record:
            return
        record.state = OutboundCallState.CONNECTED
        record.answered_at = datetime.now()
        self._cancel_ring_timeout(record)
        
        # AI 모드 시작 (아웃바운드 전용 컨텍스트 전달)
        await self._start_ai_cb(
            call_id=call_id,
            outbound_context={
                "outbound_id": record.outbound_id,
                "purpose": record.purpose,
                "questions": record.questions,
                "caller_display_name": record.caller_display_name,
            }
        )
        await self._emit_event("outbound_connected", record)
    
    async def on_rejected(self, call_id: str, status_code: int):
        """4xx/5xx/6xx 수신"""
        record = self._get_record_by_call_id(call_id)
        if not record:
            return
        if status_code == 486:
            record.state = OutboundCallState.BUSY
        elif status_code == 603:
            record.state = OutboundCallState.REJECTED
        else:
            record.state = OutboundCallState.FAILED
        record.failure_reason = f"SIP {status_code}"
        await self._handle_failure(record)
    
    async def on_task_completed(self, call_id: str, result: OutboundCallResult):
        """AI가 모든 태스크 완료 보고 → BYE 발신"""
        record = self._get_record_by_call_id(call_id)
        if not record:
            return
        record.result = result
        record.state = OutboundCallState.COMPLETED
        record.completed_at = datetime.now()
        # BYE 발신
        await self._send_bye_cb(call_id)
        await self._cleanup(record)
        await self._emit_event("outbound_completed", record)
    
    async def on_bye_received(self, call_id: str):
        """상대방이 먼저 끊음"""
        record = self._get_record_by_call_id(call_id)
        if not record:
            return
        if record.state == OutboundCallState.CONNECTED:
            # AI에서 현재까지 결과 수집
            partial_result = await self._stop_ai_cb(call_id)
            record.result = partial_result
            record.state = OutboundCallState.COMPLETED
            record.completed_at = datetime.now()
        await self._cleanup(record)
        await self._emit_event("outbound_ended", record)
    
    async def cancel_call(self, outbound_id: str, reason: str = "operator_cancel"):
        """운영자가 취소"""
        ...
    
    # ── 실패 처리 ──
    async def _handle_failure(self, record: OutboundCallRecord):
        """실패 시 재시도 또는 최종 실패 처리"""
        if record.retry_on_no_answer and record.attempt_count < record.max_retries:
            # 재시도 대기열에 추가
            await asyncio.sleep(self.config.retry_interval)
            await self._dial(record)
        else:
            record.completed_at = datetime.now()
            await self._cleanup(record)
            await self._emit_event("outbound_failed", record)
    
    # ── 조회 ──
    def get_call(self, outbound_id: str) -> Optional[OutboundCallRecord]: ...
    def get_active_calls(self) -> List[OutboundCallRecord]: ...
    def get_call_history(self, limit: int = 50) -> List[OutboundCallRecord]: ...
    def get_stats(self) -> Dict: ...
```

### 5.2 Outbound AI Orchestrator (Goal-Oriented Dialogue)

기존 `AIOrchestrator`를 확장하여 아웃바운드 전용 대화 모드를 추가.

```python
# ai_orchestrator.py 확장

class AIOrchestrator:
    # ... 기존 코드 ...
    
    async def handle_outbound_call(
        self, 
        call_id: str, 
        outbound_context: Dict
    ):
        """아웃바운드 콜 AI 대화 시작"""
        self._outbound_context = outbound_context
        self._task_tracker = TaskTracker(outbound_context["questions"])
        
        # 아웃바운드 전용 시스템 프롬프트 구성
        system_prompt = self._build_outbound_system_prompt(outbound_context)
        self._conversation_history = [{"role": "system", "content": system_prompt}]
        
        # 첫 인사 + 목적 전달
        greeting = await self._generate_outbound_greeting(outbound_context)
        await self.speak(greeting)
        
        # 대화 루프 시작 (기존 listen loop 재활용)
        # STT → LLM → TTS 루프는 기존과 동일
    
    def _build_outbound_system_prompt(self, context: Dict) -> str:
        """아웃바운드 전용 시스템 프롬프트 생성"""
        questions_text = "\n".join(
            f"  {i+1}. {q}" for i, q in enumerate(context["questions"])
        )
        return f"""당신은 {context.get('caller_display_name', '회사')}의 AI 비서입니다.
고객에게 전화를 걸어 아래 목적과 확인 사항을 처리해야 합니다.

## 통화 목적
{context['purpose']}

## 확인해야 할 사항
{questions_text}

## 대화 규칙
1. 먼저 자기소개와 통화 목적을 간결하게 밝히세요.
2. 확인 사항을 하나씩 자연스럽게 질문하세요.
3. 답변이 불명확하면 정중하게 다시 한번 확인하세요.
4. 모든 확인 사항에 대한 답변을 받으면 감사 인사를 하고 통화를 마무리하세요.
5. 고객이 바쁘거나 거부하면 양해를 구하고 통화를 종료하세요.
6. 반드시 한국어로 대화하세요.
7. 존댓말을 사용하세요.

## 응답 시 내부 태스크 상태 추적
매 응답 후 아래 JSON 형식으로 현재 상태를 [TASK_STATE] 태그로 출력하세요:
[TASK_STATE]{{"questions": [{{"id": "q1", "status": "answered|pending|unclear|refused", "answer": "..."}}], "all_completed": false, "should_end_call": false}}[/TASK_STATE]
"""

    async def _generate_outbound_greeting(self, context: Dict) -> str:
        """첫 인사말 생성"""
        display_name = context.get("caller_display_name", "")
        greeting_prompt = f"""아래 정보로 전화 첫 인사말을 만들어주세요. 
        - 발신자: {display_name} AI 비서
        - 통화 목적: {context['purpose']}
        자기소개와 목적을 간결하게 1-2문장으로 밝혀주세요."""
        
        response = await self.llm.generate_response(greeting_prompt, ...)
        return response
    
    async def _process_outbound_response(self, user_text: str):
        """아웃바운드 모드에서 고객 발화 처리"""
        # LLM에게 대화 이력 + 현재 발화 전달
        response = await self.llm.generate_response(
            user_text, 
            conversation_history=self._conversation_history
        )
        
        # 태스크 상태 파싱
        task_state = self._parse_task_state(response)
        if task_state:
            self._task_tracker.update(task_state)
        
        # 응답 텍스트에서 태스크 상태 태그 제거 후 TTS
        clean_response = self._strip_task_tags(response)
        await self.speak(clean_response)
        
        # 태스크 완료 확인
        if self._task_tracker.is_all_completed():
            # 결과 생성 및 통화 종료 요청
            result = await self._generate_outbound_result()
            await self._outbound_complete_cb(self._call_id, result)
    
    def _parse_task_state(self, response: str) -> Optional[Dict]:
        """LLM 응답에서 [TASK_STATE] 태그 파싱"""
        import re
        match = re.search(r'\[TASK_STATE\](.*?)\[/TASK_STATE\]', response, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        return None
```

### 5.3 TaskTracker (태스크 추적기)

```python
class TaskTracker:
    """아웃바운드 콜의 확인 사항 진행 상태 추적"""
    
    def __init__(self, questions: List[str]):
        self.questions = {
            f"q{i+1}": {
                "id": f"q{i+1}",
                "text": q,
                "status": "pending",      # pending | answered | unclear | refused
                "answer": None,
                "confidence": 0.0,
            }
            for i, q in enumerate(questions)
        }
        self.purpose_stated = False
        self.should_end_call = False
    
    def update(self, task_state: Dict):
        """LLM이 보고한 태스크 상태로 업데이트"""
        for q_update in task_state.get("questions", []):
            qid = q_update.get("id")
            if qid in self.questions:
                self.questions[qid].update(q_update)
        self.should_end_call = task_state.get("should_end_call", False)
    
    def is_all_completed(self) -> bool:
        """모든 확인 사항이 완료(answered/refused)되었는지"""
        return all(
            q["status"] in ("answered", "refused") 
            for q in self.questions.values()
        ) or self.should_end_call
    
    def get_progress(self) -> Dict:
        """진행률 반환"""
        total = len(self.questions)
        done = sum(1 for q in self.questions.values() if q["status"] in ("answered", "refused"))
        return {"total": total, "completed": done, "progress": done / total if total > 0 else 0}
    
    def to_result(self) -> List[QuestionAnswer]:
        """최종 결과 변환"""
        return [
            QuestionAnswer(
                question_id=q["id"],
                question_text=q["text"],
                status=q["status"],
                answer_text=q.get("answer"),
                answer_summary=q.get("answer"),
                confidence=q.get("confidence", 0.0),
            )
            for q in self.questions.values()
        ]
```

### 5.4 SIP Endpoint 확장

```python
# sip_endpoint.py 확장

class SIPEndpoint:
    # ... 기존 코드 ...
    
    async def send_outbound_invite(
        self,
        to_number: str,
        from_number: str,
        outbound_id: str,
    ) -> str:
        """아웃바운드 콜 SIP INVITE 발신"""
        
        # 1. 대상 해석 (외부번호 → SIP Gateway)
        target = self._resolve_outbound_target(to_number)
        
        # 2. 미디어 포트 할당
        rtp_port, rtcp_port = self._port_pool.allocate(2)
        
        # 3. Call-ID 생성
        call_id = f"outbound-{outbound_id}-{uuid4().hex[:8]}"
        
        # 4. SDP 구성 (AI 200 OK / Transfer INVITE와 동일한 검증된 형식)
        b2bua_ip = self._get_b2bua_ip()
        session_id = str(int(time.time()))
        
        sdp = (
            f"v=0\r\n"
            f"o=- {session_id} {session_id} IN IP4 {b2bua_ip}\r\n"
            f"s=Talk\r\n"
            f"c=IN IP4 {b2bua_ip}\r\n"
            f"t=0 0\r\n"
            f"m=audio {rtp_port} RTP/AVP 0 8 101\r\n"
            f"a=rtpmap:101 telephone-event/8000\r\n"
            f"a=rtcp:{rtcp_port}\r\n"
        )
        
        # 5. INVITE 메시지 구성
        branch = f"z9hG4bK-outbound-{uuid4().hex[:8]}"
        from_tag = f"outb-{uuid4().hex[:8]}"
        
        invite_msg = (
            f"INVITE sip:{to_number}@{target['host']}:{target['port']} SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP {b2bua_ip}:{self._sip_port};branch={branch}\r\n"
            f"From: <sip:{from_number}@{b2bua_ip}>;tag={from_tag}\r\n"
            f"To: <sip:{to_number}@{target['host']}>\r\n"
            f"Call-ID: {call_id}\r\n"
            f"CSeq: 1 INVITE\r\n"
            f"Contact: <sip:{from_number}@{b2bua_ip}:{self._sip_port}>\r\n"
            f"Max-Forwards: 70\r\n"
            f"Content-Type: application/sdp\r\n"
            f"Content-Length: {len(sdp)}\r\n"
            f"X-Outbound-Call-ID: {outbound_id}\r\n"
            f"\r\n"
            f"{sdp}"
        )
        
        # 6. 내부 상태 등록
        self._active_calls[call_id] = {
            "type": "outbound",
            "outbound_id": outbound_id,
            "from_tag": from_tag,
            "branch": branch,
            "rtp_port": rtp_port,
            "rtcp_port": rtcp_port,
            "target": target,
            "state": "dialing",
        }
        
        # 7. 전송
        self._socket.sendto(
            invite_msg.encode(),
            (target["host"], target["port"])
        )
        
        return call_id
    
    def _resolve_outbound_target(self, number: str) -> Dict:
        """외부 번호를 SIP Gateway로 라우팅"""
        gateway = self.config.get("outbound", {}).get("default_gateway")
        if gateway:
            # 설정된 SIP Gateway 사용
            # e.g., "sip:gw.example.com:5060"
            host, port = self._parse_gateway(gateway)
            return {"host": host, "port": port, "username": number}
        
        # Gateway 미설정 시: 등록된 유저 검색
        if number in self._registered_users:
            user_info = self._registered_users[number]
            return {"host": user_info["ip"], "port": user_info["port"], "username": number}
        
        raise ValueError(f"Cannot resolve outbound target: {number}")
```

---

## 6. API 설계

### 6.1 REST API 엔드포인트

| Method | Path | 설명 | 인증 |
|--------|------|------|------|
| POST | `/api/outbound/` | 아웃바운드 콜 요청 생성 | Required |
| GET | `/api/outbound/` | 아웃바운드 콜 목록 조회 | Required |
| GET | `/api/outbound/active` | 활성 콜만 조회 | Required |
| GET | `/api/outbound/stats` | 통계 조회 | Required |
| GET | `/api/outbound/{outbound_id}` | 개별 콜 상세 | Required |
| GET | `/api/outbound/{outbound_id}/result` | 통화 결과 조회 (답변, 대화록) | Required |
| POST | `/api/outbound/{outbound_id}/cancel` | 콜 취소 | Required |
| POST | `/api/outbound/{outbound_id}/retry` | 재시도 | Required |

### 6.2 API 상세

#### POST /api/outbound/ (아웃바운드 콜 생성)

**Request:**
```json
{
  "caller_number": "07012345678",
  "callee_number": "01098765432",
  "purpose": "내일 오후 2시 미팅 일정 확인",
  "questions": [
    "참석 가능 여부",
    "장소 변경 필요 여부"
  ],
  "caller_display_name": "ABC 주식회사",
  "max_duration": 180,
  "retry_on_no_answer": true
}
```

**Response (202 Accepted):**
```json
{
  "outbound_id": "ob-a1b2c3d4",
  "state": "queued",
  "created_at": "2026-02-13T14:30:00+09:00",
  "message": "아웃바운드 콜이 대기열에 추가되었습니다."
}
```

#### GET /api/outbound/{outbound_id}/result (결과 조회)

**Response:**
```json
{
  "outbound_id": "ob-a1b2c3d4",
  "state": "completed",
  "caller_number": "07012345678",
  "callee_number": "01098765432",
  "purpose": "내일 오후 2시 미팅 일정 확인",
  "duration_seconds": 95,
  "task_completed": true,
  "answers": [
    {
      "question_id": "q1",
      "question_text": "참석 가능 여부",
      "status": "answered",
      "answer_text": "네, 참석 가능합니다.",
      "answer_summary": "참석 가능",
      "confidence": 0.95
    },
    {
      "question_id": "q2",
      "question_text": "장소 변경 필요 여부",
      "status": "answered",
      "answer_text": "아니요, 기존 장소로 괜찮습니다.",
      "answer_summary": "장소 변경 불필요",
      "confidence": 0.92
    }
  ],
  "summary": "고객은 내일 오후 2시 미팅에 참석 가능하며, 장소 변경은 필요 없다고 답변했습니다.",
  "transcript": [
    {"timestamp": 0.0, "speaker": "ai", "text": "안녕하세요, ABC 주식회사 AI 비서입니다. 내일 오후 2시 미팅 일정 관련하여 연락드렸습니다."},
    {"timestamp": 5.2, "speaker": "ai", "text": "참석 가능하신지 확인 부탁드립니다."},
    {"timestamp": 8.1, "speaker": "customer", "text": "네, 참석 가능합니다."},
    {"timestamp": 10.5, "speaker": "ai", "text": "감사합니다. 장소 변경이 필요하신 부분이 있으신가요?"},
    {"timestamp": 14.3, "speaker": "customer", "text": "아니요, 기존 장소로 괜찮습니다."},
    {"timestamp": 17.0, "speaker": "ai", "text": "확인 감사합니다. 좋은 하루 되세요."}
  ],
  "created_at": "2026-02-13T14:30:00+09:00",
  "answered_at": "2026-02-13T14:30:15+09:00",
  "completed_at": "2026-02-13T14:31:50+09:00"
}
```

### 6.3 WebSocket 이벤트

| 이벤트 | 트리거 | payload |
|--------|--------|---------|
| `outbound_queued` | 요청 생성됨 | `{outbound_id, callee_number, purpose}` |
| `outbound_dialing` | INVITE 발신 | `{outbound_id, attempt}` |
| `outbound_ringing` | 180 수신 | `{outbound_id}` |
| `outbound_connected` | 200 OK, AI 대화 시작 | `{outbound_id, answered_at}` |
| `outbound_progress` | 확인 사항 진행 업데이트 | `{outbound_id, progress: {total, completed}}` |
| `outbound_completed` | 정상 완료 | `{outbound_id, task_completed, summary}` |
| `outbound_failed` | 실패 | `{outbound_id, reason}` |
| `outbound_ended` | 상대방 종료 | `{outbound_id}` |

---

## 7. Frontend 설계

### 7.1 페이지 구조

```
/outbound
├── page.tsx                    # 메인: 요청 목록 + 통계
├── new/
│   └── page.tsx                # 새 아웃바운드 콜 요청 폼
└── [outbound_id]/
    └── page.tsx                # 개별 결과 상세 (대화록 + 답변)
```

### 7.2 새 아웃바운드 콜 요청 폼 (`/outbound/new`)

```
┌──────────────────────────────────────────────────────────┐
│  🔔 AI 아웃바운드 콜 요청                                │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  발신번호 *                                              │
│  ┌────────────────────────────────────────────┐          │
│  │ 070-1234-5678                              │          │
│  └────────────────────────────────────────────┘          │
│                                                          │
│  착신번호 *                                              │
│  ┌────────────────────────────────────────────┐          │
│  │ 010-9876-5432                              │          │
│  └────────────────────────────────────────────┘          │
│                                                          │
│  발신자 표시명                                           │
│  ┌────────────────────────────────────────────┐          │
│  │ ABC 주식회사                               │          │
│  └────────────────────────────────────────────┘          │
│                                                          │
│  통화 목적 *                                             │
│  ┌────────────────────────────────────────────┐          │
│  │ 내일 오후 2시 미팅 일정 확인               │          │
│  │                                            │          │
│  └────────────────────────────────────────────┘          │
│                                                          │
│  확인 필요 사항 *                                        │
│  ┌────────────────────────────────────────────┐          │
│  │ 1. 참석 가능 여부                     [✕]  │          │
│  │ 2. 장소 변경 필요 여부                [✕]  │          │
│  │ + 항목 추가                                │          │
│  └────────────────────────────────────────────┘          │
│                                                          │
│  ── 고급 설정 ──────────────────────────────             │
│  최대 통화 시간: [180] 초                                │
│  미응답 시 재시도: [✓]  최대 재시도: [2]회               │
│                                                          │
│  ┌──────────────┐  ┌──────────┐                          │
│  │  📞 발신 요청  │  │   취소   │                          │
│  └──────────────┘  └──────────┘                          │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

### 7.3 아웃바운드 콜 이력 페이지 (`/outbound`)

```
┌──────────────────────────────────────────────────────────────────────┐
│  📊 AI 아웃바운드 콜                                    [+ 새 발신]  │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│  │ 전체     │ │ 완료     │ │ 진행중   │ │ 미응답   │ │ 성공률   │ │
│  │  156     │ │  98      │ │   3      │ │  32      │ │  76.2%   │ │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘ │
│                                                                      │
│  필터: [전체 상태 ▾]  검색: [_________________]                      │
│                                                                      │
│  ┌───┬──────────┬──────────┬────────────────┬──────┬──────┬──────┐ │
│  │ # │ 시간     │ 착신번호 │ 통화 목적      │ 상태 │ 시간 │ 결과 │ │
│  ├───┼──────────┼──────────┼────────────────┼──────┼──────┼──────┤ │
│  │ 1 │ 14:30    │ 010-9876 │ 미팅 일정 확인 │ ✅   │ 95초 │ 보기 │ │
│  │ 2 │ 14:25    │ 010-1111 │ 배송 일정 안내 │ ✅   │ 62초 │ 보기 │ │
│  │ 3 │ 14:20    │ 010-2222 │ 설문 조사      │ 📞   │  --  │  --  │ │
│  │ 4 │ 14:15    │ 010-3333 │ 예약 확인      │ 🔕   │  --  │ 재시도│ │
│  └───┴──────────┴──────────┴────────────────┴──────┴──────┴──────┘ │
└──────────────────────────────────────────────────────────────────────┘
```

### 7.4 결과 상세 페이지 (`/outbound/{id}`)

```
┌──────────────────────────────────────────────────────────────────────┐
│  📋 아웃바운드 콜 결과 — ob-a1b2c3d4                    [← 목록]    │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ── 기본 정보 ──                                                     │
│  발신번호: 070-1234-5678 (ABC 주식회사)                              │
│  착신번호: 010-9876-5432                                             │
│  통화 목적: 내일 오후 2시 미팅 일정 확인                             │
│  상태: ✅ 완료  |  통화 시간: 95초  |  시도: 1회                     │
│                                                                      │
│  ── 확인 사항 결과 ──                                                │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │ ✅ Q1. 참석 가능 여부                                         │ │
│  │    답변: "참석 가능"                       신뢰도: 95%        │ │
│  │    원문: "네, 참석 가능합니다."                                │ │
│  ├────────────────────────────────────────────────────────────────┤ │
│  │ ✅ Q2. 장소 변경 필요 여부                                    │ │
│  │    답변: "장소 변경 불필요"                 신뢰도: 92%        │ │
│  │    원문: "아니요, 기존 장소로 괜찮습니다."                     │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ── AI 요약 ──                                                       │
│  고객은 내일 오후 2시 미팅에 참석 가능하며, 장소 변경은             │
│  필요 없다고 답변했습니다.                                           │
│                                                                      │
│  ── 전체 대화록 ──                                                   │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │ 🤖 [00:00] 안녕하세요, ABC 주식회사 AI 비서입니다.            │ │
│  │           내일 오후 2시 미팅 일정 관련하여 연락드렸습니다.     │ │
│  │ 🤖 [00:05] 참석 가능하신지 확인 부탁드립니다.                 │ │
│  │ 👤 [00:08] 네, 참석 가능합니다.                               │ │
│  │ 🤖 [00:10] 감사합니다. 장소 변경이 필요하신 부분이            │ │
│  │           있으신가요?                                          │ │
│  │ 👤 [00:14] 아니요, 기존 장소로 괜찮습니다.                    │ │
│  │ 🤖 [00:17] 확인 감사합니다. 좋은 하루 되세요.                │ │
│  └────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 8. 설정 (config.yaml)

```yaml
ai_voicebot:
  outbound:
    enabled: true
    
    # SIP Gateway 설정
    default_gateway: "sip:gateway.example.com:5060"   # 외부 발신용 SIP Gateway
    # gateway 미설정 시 등록된 유저로만 발신 가능
    
    # 발신 제어
    max_concurrent_calls: 5          # 동시 아웃바운드 콜 최대 수
    ring_timeout: 30                 # 링 타임아웃 (초)
    max_call_duration: 300           # 최대 통화 시간 (초, 기본 5분)
    
    # 재시도 정책
    retry:
      enabled: true
      max_retries: 2                 # 최대 재시도 횟수
      retry_interval: 300            # 재시도 간격 (초, 기본 5분)
      retry_on: ["no_answer", "busy"]  # 재시도 대상 상태
    
    # AI 대화 설정
    ai:
      greeting_template: >
        안녕하세요, {display_name} AI 비서입니다.
        {purpose} 관련하여 연락드렸습니다.
      closing_template: >
        확인 감사합니다. 좋은 하루 되세요.
      max_turns: 20                  # 최대 대화 턴 수 (무한 루프 방지)
      task_completion_check: true    # 태스크 완료 자동 감지
    
    # 결과 저장
    result:
      save_transcript: true          # 대화록 저장
      save_recording: true           # 녹음 파일 저장
      generate_summary: true         # AI 요약 생성
      summary_model: "gemini-2.5-flash"  # 요약 생성 모델
```

---

## 9. 구현 계획

### 9.1 Phase 구조

```
Phase 1: Core Backend (핵심 발신 + AI 대화)          ─── 3일
Phase 2: 결과 수집 + 저장                            ─── 2일
Phase 3: REST API + WebSocket                         ─── 1일
Phase 4: Frontend UI                                  ─── 2일
Phase 5: 통합 테스트 + Edge Case                      ─── 2일
                                              Total: ~10일
```

### 9.2 Phase 1: Core Backend

| # | 작업 | 파일 | 설명 |
|---|------|------|------|
| 1-1 | `OutboundCallState` enum | `src/sip_core/models/enums.py` | 상태 열거형 추가 |
| 1-2 | `OutboundCallRecord` + `OutboundCallResult` | `src/sip_core/models/outbound.py` (NEW) | 데이터 모델 |
| 1-3 | `OutboundCallManager` | `src/sip_core/outbound_manager.py` (NEW) | 콜 생명주기 관리 |
| 1-4 | `send_outbound_invite()` | `src/sip_core/sip_endpoint.py` | SIP INVITE 발신 |
| 1-5 | `_resolve_outbound_target()` | `src/sip_core/sip_endpoint.py` | Gateway 라우팅 |
| 1-6 | 아웃바운드 SIP 응답 처리 | `src/sip_core/sip_endpoint.py` | 180/200/4xx-6xx 라우팅 |
| 1-7 | `OutboundConfig` | `src/config/models.py` | 설정 모델 |
| 1-8 | `config.yaml` 확장 | `config/config.yaml` | outbound 섹션 추가 |

### 9.3 Phase 2: AI 대화 + 결과 수집

| # | 작업 | 파일 | 설명 |
|---|------|------|------|
| 2-1 | `handle_outbound_call()` | `src/ai_voicebot/orchestrator/ai_orchestrator.py` | 아웃바운드 전용 AI 진입점 |
| 2-2 | `TaskTracker` | `src/ai_voicebot/orchestrator/task_tracker.py` (NEW) | 태스크 완료 추적 |
| 2-3 | 아웃바운드 시스템 프롬프트 | `src/ai_voicebot/orchestrator/ai_orchestrator.py` | Goal-Oriented 프롬프트 |
| 2-4 | 결과 생성 (`_generate_outbound_result`) | `src/ai_voicebot/orchestrator/ai_orchestrator.py` | 대화록 + 답변 + 요약 |
| 2-5 | RTP AI 모드 아웃바운드 초기화 | `src/media/rtp_relay.py` | 아웃바운드 미디어 세션 |

### 9.4 Phase 3: REST API + WebSocket

| # | 작업 | 파일 | 설명 |
|---|------|------|------|
| 3-1 | Outbound REST API | `src/api/routers/outbound.py` (NEW) | CRUD + 결과 조회 API |
| 3-2 | API 모델 | `src/api/models.py` | 요청/응답 Pydantic 모델 |
| 3-3 | 라우터 등록 | `src/api/main.py` | `/api/outbound` 마운트 |
| 3-4 | WebSocket 이벤트 | `src/sip_core/outbound_manager.py` | 실시간 상태 이벤트 |

### 9.5 Phase 4: Frontend

| # | 작업 | 파일 | 설명 |
|---|------|------|------|
| 4-1 | 아웃바운드 목록 + 통계 | `frontend/app/outbound/page.tsx` (NEW) | 메인 페이지 |
| 4-2 | 새 발신 요청 폼 | `frontend/app/outbound/new/page.tsx` (NEW) | 입력 폼 |
| 4-3 | 결과 상세 페이지 | `frontend/app/outbound/[id]/page.tsx` (NEW) | 대화록 + 답변 |
| 4-4 | 대시보드 네비게이션 | `frontend/app/dashboard/page.tsx` | "AI 발신" 링크 추가 |

### 9.6 Phase 5: 통합 + Edge Case

| # | 작업 | 설명 |
|---|------|------|
| 5-1 | Ring Timeout + 재시도 | 미응답 시 자동 재시도 로직 |
| 5-2 | Max Duration 강제 종료 | 최대 통화 시간 초과 시 BYE |
| 5-3 | 고객 먼저 끊기 | 부분 결과 수집 + 저장 |
| 5-4 | 동시 발신 제한 | max_concurrent_calls 제어 |
| 5-5 | 예약 발신 (향후) | scheduled_at 기반 스케줄러 |

---

## 10. Transfer vs Outbound 비교

기존 Transfer 기능과의 차이를 명확히 정리:

| 항목 | Transfer (기존) | Outbound (신규) |
|------|----------------|-----------------|
| **트리거** | AI가 RAG로 자동 감지 | 유저가 웹 UI로 수동 요청 |
| **원래 호** | 있음 (발신자 ↔ AI) | 없음 (서버 단독 발신) |
| **AI 역할** | 전환 안내 → 연결 후 빠짐 | 전 통화 대화 수행 (주체) |
| **미디어 모드** | AI → BRIDGE (Caller↔Callee) | AI 모드 (Server↔Customer) |
| **대화 목표** | 없음 (연결이 목표) | 있음 (확인 사항 수집) |
| **결과** | 연결 성공/실패 | 대화록 + 답변 + 요약 |
| **재시도** | 1회 (전환 실패 시) | 다회 (미응답/통화중 시) |
| **BYE 주체** | 양쪽 모두 | AI가 태스크 완료 시 발신 |

---

## 11. 보안 및 제약 사항

### 11.1 보안

| 항목 | 대책 |
|------|------|
| 무분별한 발신 방지 | `max_concurrent_calls` 제한, 인증 필수 |
| 발신번호 위변조 | 등록된 발신번호만 허용 (화이트리스트) |
| 개인정보 보호 | 착신번호 마스킹 표시, 대화록 암호화 저장 |
| 과금 제어 | `max_call_duration` 강제, 일일 발신 한도 |
| 스팸 방지 | Rate Limiting, 동일 번호 중복 발신 차단 |

### 11.2 제약 사항

| 항목 | 설명 |
|------|------|
| SIP Gateway 필요 | 외부 번호 발신 시 SIP Trunk/Gateway 필요 |
| 코덱 제한 | G.711 (PCMU/PCMA) + telephone-event만 지원 |
| 동시 통화 수 | 포트 풀 크기에 의존 |
| 음성 메일 감지 | 향후 구현 (Voicemail Detection) |

---

## 12. 향후 확장

| 기능 | 설명 | 우선순위 |
|------|------|----------|
| **예약 발신** | `scheduled_at` 기반 스케줄링 | High |
| **대량 발신 (Campaign)** | CSV 업로드 → 순차 발신 | High |
| **Voicemail 감지** | 음성사서함 감지 시 메시지 남기기/재시도 | Medium |
| **대화 템플릿** | 반복 사용 가능한 목적+질문 템플릿 저장 | Medium |
| **감정 분석** | 고객 감정(긍정/부정/중립) 분석 | Low |
| **다국어 지원** | 영어, 중국어 등 | Low |
| **Webhook 알림** | 결과 완료 시 외부 시스템 알림 | Medium |
| **통계 대시보드** | 성공률, 평균 통화 시간, 질문별 응답 분포 | Medium |

---

## 13. 참고 자료

### RFC / 표준
- **RFC 3725** - Best Current Practices for Third Party Call Control (3PCC) in SIP
- **RFC 3261** - SIP: Session Initiation Protocol
- **RFC 3264** - An Offer/Answer Model with the Session Description Protocol

### 오픈소스 / 프로젝트
- [livekit-examples/outbound-caller-python](https://github.com/livekit-examples/outbound-caller-python) - LiveKit 아웃바운드 콜러
- [aicc2025/sip-to-ai](https://github.com/aicc2025/sip-to-ai) - SIP-to-AI 브릿지 (Pure asyncio)
- [videosdk-community/ai-telephony-demo](https://github.com/videosdk-community/ai-telephony-demo) - VideoSDK AI 텔레포니

### 연구 / 논문
- **Conversation Routines** (2025) - Task-Oriented Dialog Systems 프롬프트 엔지니어링 프레임워크
- **InstructTODS** - LLM 기반 End-to-End Task-Oriented Dialogue
- **Beyond IVR** (2025) - 고객 지원 LLM Agent의 비즈니스 정책 준수 벤치마크

### 상용 서비스 참고
- **Bland AI** - Self-hosted 풀스택, Pathway 기반, < 500ms 레이턴시
- **ElevenLabs Outbound Agents** - 고품질 TTS 기반 아웃바운드
- **LiveKit Agents** - SIP 트렁크 + Python Agent 프레임워크
