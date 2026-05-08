# AI 호 연결 (Call Transfer) 기능 설계서
> **클러스터 안내**: 세부·히스토리 설계 문서입니다. 통합 관점·경계는 아래 대표 문서를 우선 참고하세요.
> 
> **대표 문서**: [`AI_DYNAMIC_CALL_TRANSFER_DESIGN.md`](AI_DYNAMIC_CALL_TRANSFER_DESIGN.md)
>
---


> **Version**: 1.1  
> **Date**: 2026-01-29 (Updated: 2026-02-13)  
> **Status**: Implemented (Phase 1-4)  
> **Author**: AI Assistant  

---

## 1. 개요

### 1.1 목적

AI Voicebot이 발신자의 요청에 따라 특정 부서/담당자에게 **호를 연결(Transfer)** 하는 기능을 설계한다. 기존 AI 응대 모드에서 발신자의 전화 연결 요청을 인식하고, RAG 기반으로 대상을 검색하여, B2BUA 방식으로 제3자 통화를 성립시킨다.

### 1.2 핵심 시나리오

```
1. AI가 2차 인사말에서 "개발부서 호 연결" 등 가능한 업무를 소개
2. 발신자: "개발부서에 호 연결해줘"
3. AI → RAG 검색 → 개발부서 전화번호 확인 → 안내 멘트 재생 + SIP INVITE 발신
4. 착신자 응답 → 안내 멘트 중단 → 발신자↔착신자 미디어 브릿지
5. 대시보드에서 전환 상태 실시간 모니터링
```

### 1.3 핵심 원칙

| 원칙 | 설명 |
|------|------|
| **B2BUA 미디어 경로 유지** | 발신자 ↔ 서버 ↔ 착신자 (직접 연결 X) |
| **AI 주도 전환** | AI가 의도를 파악하고 자동으로 전환 프로세스 시작 |
| **안내 후 연결** | 연결 전 안내 멘트를 반드시 재생 |
| **실패 복구** | 연결 실패 시 AI 대화 모드로 자동 복귀 |
| **대시보드 가시성** | 전환 과정의 모든 상태가 실시간 표시 |

---

## 2. 업계 벤치마킹

### 2.1 LiveKit - Warm Transfer

LiveKit의 `WarmTransferTask`는 현재 가장 성숙한 AI 호 전환 구현체이다.

**아키텍처:**
- **2-Room 패턴**: Caller Room + Consultation Room으로 분리
- **Agent Handoff**: SupportAgent → TransferAgent로 역할 전환
- **Function Calling**: `@function_tool` 데코레이터로 전환 함수 정의
- **SIP 통합**: `CreateSIPParticipant` API로 아웃바운드 호 생성

**핵심 흐름:**
```
1. Caller on hold (audio input/output disabled)
2. Consultation room 생성
3. TransferAgent가 supervisor에게 context 요약 전달
4. Supervisor를 caller room으로 이동 (MoveParticipant)
5. Agent 퇴장, caller↔supervisor 직접 통화
```

**우리 시스템에 적용할 점:**
- Function calling 패턴 (AI가 전환 함수를 호출)
- Hold → Announce → Bridge 3단계 패턴
- 실패 시 caller에게 복귀하는 fallback 패턴

### 2.2 Vocode - Warm Transfer (Beta)

**아키텍처:**
- **Conference 기반**: Steering pool의 전화번호로 컨퍼런스 구성
- **3-Way Merge**: Primary on hold → Dial third party → Merge all
- **Twilio 의존**: SIP trunking은 Twilio 기반

**우리 시스템에 적용할 점:**
- Hold music 재생 패턴
- Transfer 실패 시 429 에러 핸들링 (동시 전환 제한)

### 2.3 Asterisk - Attended Transfer (전통 PBX)

**아키텍처:**
- **SIP REFER + Replaces**: RFC 3515 기반 표준 전환
- **Bridge 관리**: 두 개의 Bridge를 merge
- **ARI 지원**: `PJSIP_TRANSFER_HANDLING()=ari-only`로 이벤트 제어

**우리 시스템에 적용할 점:**
- Bridge 재구성 패턴 (RTP relay 모드 전환)
- SDP 재협상 (re-INVITE) 패턴

### 2.4 RFC 3725 - Third Party Call Control (3pcc)

**핵심 패턴:**
- **Flow I**: Controller가 양쪽 모두에게 INVITE (우리 B2BUA 패턴)
- **Controller 역할**: B2BUA가 양쪽 호를 독립적으로 관리
- **SDP 교환**: Controller가 양쪽의 SDP를 중개

**우리 시스템에 직접 적용:**
- B2BUA가 Controller 역할 수행
- 발신자 SDP와 착신자 SDP를 서버 포트로 rewrite
- 미디어 경로: Caller ↔ Server Port A ↔ Server Port B ↔ Callee

### 2.5 벤치마킹 비교표

| 기능 | LiveKit | Vocode | Asterisk | **Our System (설계)** |
|------|---------|--------|----------|----------------------|
| Transfer 방식 | SIP Participant API | Conference | REFER/Bridge | **B2BUA INVITE** |
| 미디어 경로 | Cloud 경유 | Twilio 경유 | Local Bridge | **Server Relay** |
| AI 역할 | Function Tool | API Call | Dialplan | **RAG + Auto-detect** |
| Hold 처리 | Audio disable | Conference hold | MOH | **TTS 안내 + Hold Music** |
| 실패 복구 | Agent 복귀 | 429 Error | Timeout | **AI 대화 복귀** |
| 대시보드 | Cloud Dashboard | API | AMI Events | **WebSocket 실시간** |

---

## 3. 시스템 아키텍처

### 3.1 전체 흐름 시퀀스 다이어그램

```
 발신자(Caller)        B2BUA Server          AI Orchestrator       착신자(Callee)
      |                     |                      |                      |
      |===== AI 응대 모드 (기존) ====|                      |                      |
      |--RTP(음성)--------->|---audio packet------->|                      |
      |                     |                      |                      |
      |     [발신자: "개발부서에 호 연결해줘"]                |                      |
      |--RTP(음성)--------->|---audio packet------->|                      |
      |                     |                      |--STT 인식             |
      |                     |                      |--RAG 검색             |
      |                     |                      |  → response_type:     |
      |                     |                      |    "transfer"         |
      |                     |                      |  → transfer_to:       |
      |                     |                      |    "sip:8001@server"  |
      |                     |                      |                      |
      |===== 전환 시작 (Phase 1: 안내) ====|                      |                      |
      |                     |                      |                      |
      |                     |<--transfer_request---|                      |
      |                     |   (call_id,          |                      |
      |                     |    transfer_to,      |                      |
      |                     |    department_name,   |                      |
      |                     |    phone_display)     |                      |
      |                     |                      |                      |
      |<--TTS(안내 멘트)----|<--announce_tts--------|                      |
      |  "개발부서로 전화     |                      |                      |
      |   연결하겠습니다.    |                      |                      |
      |   번호는 8001입니다. |                      |                      |
      |   잠시만 기다려주세요"|                      |                      |
      |                     |                      |                      |
      |===== 전환 실행 (Phase 2: INVITE) ====|                      |                      |
      |                     |                      |                      |
      |                     |---INVITE(Server SDP)----------------------->|
      |                     |<--100 Trying---------------------------------------|
      |                     |<--180 Ringing--------------------------------|
      |                     |                      |                      |
      |<--Hold Music/안내---|                      |                      |
      |  "연결 중입니다..."  |                      |                      |
      |                     |                      |                      |
      |===== 연결 완료 (Phase 3: Bridge) ====|                      |                      |
      |                     |                      |                      |
      |                     |<--200 OK(Callee SDP)------------------------|
      |                     |---ACK------------------------------------------->|
      |                     |                      |                      |
      |                     |--[AI 분리, Bridge 모드 전환]--              |
      |                     |                      |                      |
      |--RTP(음성)--------->|---RTP(relay)------------------------------>|
      |<--RTP(음성)---------|<--RTP(relay)------------------------------|
      |                     |                      |                      |
      |===== 통화 종료 ====|                      |                      |
      |                     |                      |                      |
      |---BYE------------->|---BYE------------------------------------------->|
      |                     |   (or vice versa)    |                      |
```

### 3.2 실패 시나리오 시퀀스

```
 발신자(Caller)        B2BUA Server          AI Orchestrator       착신자(Callee)
      |                     |                      |                      |
      |<--TTS(안내)---------|<--announce------------|                      |
      |                     |---INVITE(SDP)------------------------------>|
      |                     |<--180 Ringing--------------------------------|
      |                     |                      |                      |
      |    (ring_timeout 초과 또는 거절)              |                      |
      |                     |<--408/480/486/603----|                      |
      |                     |                      |                      |
      |                     |--transfer_failed---->|                      |
      |<--TTS(실패 안내)----|<--announce------------|                      |
      |  "죄송합니다.       |                      |                      |
      |   개발부서와 연결이  |                      |                      |
      |   되지 않습니다.    |                      |                      |
      |   다른 도움이        |                      |                      |
      |   필요하시면         |                      |                      |
      |   말씀해주세요."    |                      |                      |
      |                     |                      |                      |
      |===== AI 대화 모드 복귀 ====|                      |                      |
      |--RTP(음성)--------->|---audio packet------->|                      |
```

### 3.3 컴포넌트 아키텍처

```
┌─────────────────────────────────────────────────────────────────┐
│                        SIP PBX Server                            │
│                                                                   │
│  ┌─────────────┐   ┌──────────────┐   ┌──────────────────────┐  │
│  │ SIPEndpoint  │   │ CallManager  │   │  TransferManager     │  │
│  │              │←→│              │←→│  (NEW)               │  │
│  │ - INVITE TX  │   │ - Session    │   │  - initiate()        │  │
│  │ - SDP Build  │   │ - State      │   │  - on_ringing()      │  │
│  │ - Response   │   │ - Lifecycle  │   │  - on_answered()     │  │
│  │   Handler    │   │              │   │  - on_failed()       │  │
│  └──────┬───────┘   └──────┬───────┘   │  - cancel()          │  │
│         │                  │           └──────────┬───────────┘  │
│         │                  │                      │              │
│  ┌──────┴──────────────────┴──────────────────────┴───────────┐  │
│  │                    RTP Relay Engine                          │  │
│  │                                                              │  │
│  │  Mode: AI_MODE ──────→ BRIDGE_MODE                          │  │
│  │                                                              │  │
│  │  [Caller Port] ←→ [Server] ←→ [Callee Port]               │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                    AI Orchestrator                            │  │
│  │                                                              │  │
│  │  STT → Intent Detection → RAG Search → Transfer Handler     │  │
│  │                              ↓                               │  │
│  │                    VectorDB (Capabilities)                   │  │
│  │                    - response_type: "transfer"               │  │
│  │                    - transfer_to: "sip:8001@..."             │  │
│  │                    - department_name: "개발부서"               │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                    API Gateway (FastAPI)                     │  │
│  │                                                              │  │
│  │  /api/transfers/          - Transfer 목록/상태 조회           │  │
│  │  /api/transfers/{id}      - 개별 Transfer 상세               │  │
│  │  /api/capabilities/       - 부서/연결처 관리 (기존)           │  │
│  │  WebSocket: transfer_status_update 이벤트                    │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│                      Frontend (Next.js)                          │
│                                                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │  Dashboard    │  │  Capabilities │  │  Transfer Monitor   │   │
│  │  (기존 확장)  │  │  (기존)       │  │  (NEW)              │   │
│  │              │  │              │  │  - 실시간 상태        │   │
│  │  - Transfer  │  │  - transfer  │  │  - Transfer 이력     │   │
│  │    상태 표시  │  │    type 관리 │  │  - 통계              │   │
│  └──────────────┘  └──────────────┘  └──────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

---

## 4. 상세 설계

### 4.1 호 전환 상태 머신 (State Machine)

```
                    ┌──────────────┐
                    │   AI_MODE    │ (기존 AI 응대 상태)
                    └──────┬───────┘
                           │ transfer intent detected
                           ▼
                    ┌──────────────────┐
                    │ TRANSFER_ANNOUNCE │ AI 안내 멘트 재생 중
                    └──────┬───────────┘
                           │ announcement started + INVITE sent
                           ▼
                    ┌──────────────────┐
                    │ TRANSFER_RINGING │ 착신 시도 중 (링백)
                    └──────┬───────────┘
                          ╱│╲
                     200 OK │ ╲ timeout/reject
                         ╱  │  ╲
                        ▼   │   ▼
              ┌────────────┐│ ┌──────────────────┐
              │ TRANSFERRED ││ │ TRANSFER_FAILED  │
              │ (Bridged)   ││ │                  │
              └──────┬──────┘│ └──────┬───────────┘
                     │       │        │ AI 복귀
                     │       │        ▼
                     │       │ ┌──────────────┐
                     │       │ │   AI_MODE    │ (AI 대화 재개)
                     │       │ └──────────────┘
                     │
                     │ BYE (either side)
                     ▼
              ┌──────────────┐
              │  TERMINATED  │
              └──────────────┘
```

### 4.2 Transfer 데이터 모델

#### 4.2.1 TransferRecord

```python
@dataclass
class TransferRecord:
    """호 전환 기록"""
    transfer_id: str              # 고유 ID (uuid)
    call_id: str                  # 원래 호 ID (발신자-서버)
    transfer_leg_call_id: str     # 전환 호 ID (서버-착신자)
    
    # 대상 정보
    department_name: str          # "개발부서"
    transfer_to: str              # "sip:8001@pbx.local" or phone number
    phone_display: str            # "8001" (사용자에게 보여줄 번호)
    
    # 발신자 정보
    caller_uri: str               # 원래 발신자 SIP URI
    caller_display: str           # 발신자 표시명
    
    # 상태
    state: TransferState          # ANNOUNCE → RINGING → CONNECTED / FAILED
    
    # 타임스탬프
    initiated_at: datetime        # 전환 시작 시각
    ringing_at: Optional[datetime]  # 링 시작 시각
    connected_at: Optional[datetime]  # 연결 완료 시각
    ended_at: Optional[datetime]      # 종료 시각
    
    # 결과
    failure_reason: Optional[str]  # 실패 사유 (timeout, rejected, busy, etc.)
    duration_seconds: Optional[int]  # 통화 시간 (연결 후)
    
    # AI 컨텍스트
    ai_conversation_summary: Optional[str]  # AI 대화 요약 (착신자 참고용)
    user_request_text: str         # 발신자의 원래 요청 텍스트
```

#### 4.2.2 TransferState Enum

```python
class TransferState(str, Enum):
    ANNOUNCE = "announce"          # AI 안내 멘트 재생 중
    RINGING = "ringing"            # 착신 시도 중
    CONNECTED = "connected"        # 발신자↔착신자 연결됨
    FAILED = "failed"              # 연결 실패
    CANCELLED = "cancelled"        # 발신자가 취소 (barge-in 등)
```

#### 4.2.3 Capability 확장 (VectorDB)

기존 Capability 모델의 `response_type: "transfer"` 활용:

```python
# VectorDB에 저장되는 transfer type capability 예시
{
    "id": "cap_dev_transfer",
    "doc_type": "capability",
    "display_name": "개발부서 호 연결",
    "text": "개발부서, 개발팀, 개발실로 전화 연결을 해드립니다.",
    "category": "호 연결",
    "response_type": "transfer",
    "transfer_to": "sip:8001@pbx.local",  # SIP URI 또는 내선번호
    "phone_display": "8001",               # 안내 시 표시할 번호
    "keywords": ["개발부서", "개발팀", "개발실", "개발"],
    "is_active": true,
    "priority": 1,
    "owner": "system"
}
```

### 4.3 AI Orchestrator 전환 처리

#### 4.3.1 Intent Detection + RAG 검색

```python
async def generate_and_speak_response(self, user_text: str, call_id: str):
    """사용자 응답 처리 - 전환 의도 감지 포함"""
    
    # 1. RAG 검색
    rag_results = await self.rag.search(
        query=user_text, 
        owner_filter="system", 
        call_id=call_id
    )
    
    # 2. 상위 결과의 response_type 확인
    if rag_results and len(rag_results) > 0:
        top_result = rag_results[0]
        response_type = top_result.metadata.get("response_type")
        similarity_score = top_result.score
        
        # Transfer intent 감지 (높은 유사도 + transfer 타입)
        if response_type == "transfer" and similarity_score >= 0.75:
            await self._handle_transfer_intent(
                call_id=call_id,
                user_text=user_text,
                rag_result=top_result
            )
            return
    
    # 3. 일반 응답 처리 (기존 로직)
    # ...
```

#### 4.3.2 Transfer Intent Handler

```python
async def _handle_transfer_intent(
    self, 
    call_id: str, 
    user_text: str, 
    rag_result
):
    """호 전환 의도 처리"""
    
    department_name = rag_result.metadata.get("display_name", "담당부서")
    transfer_to = rag_result.metadata.get("transfer_to")
    phone_display = rag_result.metadata.get("phone_display", transfer_to)
    
    if not transfer_to:
        # transfer_to가 없으면 일반 응답으로 fallback
        await self._speak("죄송합니다. 해당 부서의 연결 정보를 찾을 수 없습니다.")
        return
    
    # 1. 안내 멘트 생성 (LLM 또는 템플릿)
    announcement = await self._generate_transfer_announcement(
        department_name=department_name,
        phone_display=phone_display
    )
    
    # 2. 안내 멘트 재생 (barge-in OFF)
    await self._speak(announcement, allow_barge_in=False)
    
    # 3. SIP 레이어에 전환 요청
    await self._request_transfer(
        call_id=call_id,
        transfer_to=transfer_to,
        department_name=department_name,
        phone_display=phone_display,
        user_request_text=user_text
    )
```

#### 4.3.3 Transfer Announcement 생성

두 가지 방식을 지원:

**A. 템플릿 기반 (기본, 빠름):**
```python
async def _generate_transfer_announcement(
    self, department_name: str, phone_display: str
) -> str:
    """전환 안내 멘트 생성"""
    template = self.config.get(
        "transfer_announcement_template",
        "{department}로 전화 연결하겠습니다. "
        "연결되는 전화번호는 {phone}입니다. "
        "연결되는 동안 잠시만 기다려주세요."
    )
    return template.format(
        department=department_name,
        phone=phone_display
    )
```

**B. LLM 기반 (자연스러움):**
```python
async def _generate_transfer_announcement_llm(
    self, department_name: str, phone_display: str, context: str
) -> str:
    """LLM을 활용한 자연스러운 안내 멘트"""
    prompt = f"""사용자가 {department_name}로 전화 연결을 요청했습니다.
전화번호는 {phone_display}입니다.
자연스러운 한국어로 전환 안내 멘트를 생성해주세요.
반드시 포함할 내용: 부서명, 전화번호, 잠시 기다려달라는 안내.
1-2문장으로 간결하게."""
    
    return await self.llm.generate_short(prompt)
```

### 4.4 SIP 레이어: Transfer INVITE 발신

#### 4.4.1 TransferManager (신규 모듈)

```python
class TransferManager:
    """호 전환 관리자 - B2BUA 기반 제3자 호 제어"""
    
    def __init__(
        self, 
        sip_endpoint,          # SIPEndpoint 참조
        call_manager,          # CallManager 참조
        media_session_manager, # MediaSessionManager 참조
        config                 # Transfer 설정
    ):
        self.sip_endpoint = sip_endpoint
        self.call_manager = call_manager
        self.media_session_manager = media_session_manager
        self.config = config
        
        # 활성 전환 기록
        self.active_transfers: Dict[str, TransferRecord] = {}
        # transfer_leg_call_id → call_id 매핑
        self.transfer_leg_map: Dict[str, str] = {}
        
    async def initiate_transfer(
        self,
        call_id: str,
        transfer_to: str,
        department_name: str,
        phone_display: str,
        user_request_text: str
    ) -> TransferRecord:
        """호 전환 시작"""
        
        # 1. 전환 기록 생성
        transfer_id = f"xfer-{uuid4().hex[:12]}"
        transfer_leg_call_id = f"xfer-leg-{uuid4().hex[:8]}-{call_id[:8]}"
        
        record = TransferRecord(
            transfer_id=transfer_id,
            call_id=call_id,
            transfer_leg_call_id=transfer_leg_call_id,
            department_name=department_name,
            transfer_to=transfer_to,
            phone_display=phone_display,
            caller_uri=self._get_caller_uri(call_id),
            caller_display=self._get_caller_display(call_id),
            state=TransferState.ANNOUNCE,
            initiated_at=datetime.utcnow(),
            user_request_text=user_request_text
        )
        
        self.active_transfers[call_id] = record
        self.transfer_leg_map[transfer_leg_call_id] = call_id
        
        # 2. 이벤트 발행 (대시보드)
        await self._emit_event("transfer_initiated", record)
        
        # 3. 미디어 포트 할당 (착신 레그용)
        callee_ports = self.media_session_manager.allocate_ports(2)
        # callee_ports = (rtp_port, rtcp_port)
        
        # 4. SDP 구성 (서버의 미디어 정보)
        server_sdp = self._build_transfer_sdp(callee_ports)
        
        # 5. INVITE 발신
        target_addr = self._resolve_transfer_target(transfer_to)
        
        await self.sip_endpoint.send_transfer_invite(
            call_id=transfer_leg_call_id,
            target_addr=target_addr,
            transfer_to_uri=transfer_to,
            sdp=server_sdp,
            caller_display=record.caller_display
        )
        
        # 6. 상태 업데이트
        record.state = TransferState.RINGING
        record.ringing_at = datetime.utcnow()
        await self._emit_event("transfer_ringing", record)
        
        # 7. 링 타임아웃 설정
        self._ring_timeout_task = asyncio.create_task(
            self._ring_timeout_handler(call_id)
        )
        
        return record
```

#### 4.4.2 Transfer SDP 구성

```python
def _build_transfer_sdp(self, callee_ports: Tuple[int, int]) -> str:
    """착신 레그용 SDP 생성 (서버의 미디어 정보)"""
    
    server_ip = self.config.get("server_ip", "0.0.0.0")
    rtp_port, rtcp_port = callee_ports
    
    sdp = (
        "v=0\r\n"
        f"o=- {int(time.time())} {int(time.time())} IN IP4 {server_ip}\r\n"
        "s=SIP-PBX Transfer\r\n"
        f"c=IN IP4 {server_ip}\r\n"
        "t=0 0\r\n"
        f"m=audio {rtp_port} RTP/AVP 0 8 101\r\n"
        "a=rtpmap:0 PCMU/8000\r\n"
        "a=rtpmap:8 PCMA/8000\r\n"
        "a=rtpmap:101 telephone-event/8000\r\n"
        "a=fmtp:101 0-16\r\n"
        "a=sendrecv\r\n"
        f"a=rtcp:{rtcp_port}\r\n"
    )
    return sdp
```

#### 4.4.3 Transfer Target 해석

```python
def _resolve_transfer_target(self, transfer_to: str) -> Tuple[str, int]:
    """전환 대상 주소 해석
    
    지원 형식:
    - "sip:8001@pbx.local"    → 내선번호 (registered users에서 조회)
    - "sip:8001@192.168.1.10" → 직접 IP 주소
    - "8001"                   → 내선번호 shorthand
    - "+821012345678"          → 외부 번호 (SIP trunk 경유)
    """
    
    if transfer_to.startswith("sip:"):
        # SIP URI 파싱
        user, host = parse_sip_uri(transfer_to)
        
        # 등록된 사용자인지 확인
        if user in self.sip_endpoint._registered_users:
            reg_info = self.sip_endpoint._registered_users[user]
            return (reg_info.contact_ip, reg_info.contact_port)
        
        # 직접 IP로 연결
        return (host, 5060)
    
    elif transfer_to.isdigit():
        # 내선번호 shorthand
        if transfer_to in self.sip_endpoint._registered_users:
            reg_info = self.sip_endpoint._registered_users[transfer_to]
            return (reg_info.contact_ip, reg_info.contact_port)
        
        raise TransferError(f"Extension {transfer_to} not registered")
    
    elif transfer_to.startswith("+"):
        # 외부 번호 → SIP trunk 경유
        trunk_addr = self.config.get("sip_trunk_address")
        return (trunk_addr, 5060)
    
    raise TransferError(f"Cannot resolve transfer target: {transfer_to}")
```

### 4.5 Transfer 응답 처리

#### 4.5.1 Provisional Response (180 Ringing)

```python
async def on_transfer_ringing(self, transfer_leg_call_id: str):
    """착신측 링 수신"""
    call_id = self.transfer_leg_map.get(transfer_leg_call_id)
    if not call_id:
        return
    
    record = self.active_transfers[call_id]
    record.state = TransferState.RINGING
    
    # 발신자에게 링백톤 또는 대기 안내 재생
    await self._play_ringback_or_hold(call_id)
    await self._emit_event("transfer_ringing", record)
```

#### 4.5.2 200 OK → Bridge 전환

```python
async def on_transfer_answered(
    self, 
    transfer_leg_call_id: str, 
    callee_sdp: str
):
    """착신자 응답 → 미디어 브릿지 구성"""
    
    call_id = self.transfer_leg_map.get(transfer_leg_call_id)
    if not call_id:
        return
    
    record = self.active_transfers[call_id]
    
    # 1. 링 타임아웃 취소
    if self._ring_timeout_task:
        self._ring_timeout_task.cancel()
    
    # 2. AI 안내 멘트 / Hold music 중단
    await self._stop_announcement(call_id)
    
    # 3. AI Orchestrator 분리
    await self._detach_ai(call_id)
    
    # 4. 착신자 SDP 파싱 → 미디어 엔드포인트 확인
    callee_media = SDPParser.parse(callee_sdp)
    callee_rtp_endpoint = (
        callee_media.connection_ip, 
        callee_media.audio_port
    )
    
    # 5. RTP Relay를 Bridge 모드로 전환
    rtp_worker = self.sip_endpoint._rtp_workers.get(call_id)
    if rtp_worker:
        rtp_worker.set_bridge_mode(
            callee_endpoint=callee_rtp_endpoint
        )
    
    # 6. 상태 업데이트
    record.state = TransferState.CONNECTED
    record.connected_at = datetime.utcnow()
    
    # 7. 이벤트 발행
    await self._emit_event("transfer_connected", record)
    
    logger.info(
        "transfer_connected",
        call_id=call_id,
        department=record.department_name,
        callee=record.transfer_to
    )
```

#### 4.5.3 Transfer 실패 처리

```python
async def on_transfer_failed(
    self, 
    transfer_leg_call_id: str, 
    status_code: int, 
    reason: str
):
    """전환 실패 → AI 모드 복귀"""
    
    call_id = self.transfer_leg_map.get(transfer_leg_call_id)
    if not call_id:
        return
    
    record = self.active_transfers[call_id]
    
    # 1. 상태 업데이트
    record.state = TransferState.FAILED
    record.failure_reason = f"{status_code} {reason}"
    record.ended_at = datetime.utcnow()
    
    # 2. Hold music 중단
    await self._stop_announcement(call_id)
    
    # 3. 실패 안내 멘트
    failure_msg = self._get_failure_message(
        department_name=record.department_name,
        status_code=status_code
    )
    await self._speak_to_caller(call_id, failure_msg)
    
    # 4. AI 대화 모드 복귀
    await self._resume_ai_mode(call_id)
    
    # 5. 이벤트 발행
    await self._emit_event("transfer_failed", record)

def _get_failure_message(
    self, department_name: str, status_code: int
) -> str:
    """상태 코드별 실패 메시지"""
    
    messages = {
        408: f"죄송합니다. {department_name}에서 응답이 없습니다. 다른 도움이 필요하시면 말씀해주세요.",
        480: f"죄송합니다. {department_name}이 현재 통화 불가능 상태입니다. 다른 도움이 필요하시면 말씀해주세요.",
        486: f"죄송합니다. {department_name}이 현재 통화 중입니다. 잠시 후 다시 시도하시겠습니까?",
        603: f"죄송합니다. {department_name}에서 전화를 받지 않았습니다. 다른 도움이 필요하시면 말씀해주세요.",
    }
    
    return messages.get(
        status_code, 
        f"죄송합니다. {department_name}과 연결이 되지 않았습니다. "
        f"다른 도움이 필요하시면 말씀해주세요."
    )
```

### 4.6 RTP Relay: Bridge 모드

#### 4.6.1 RTPRelayWorker 확장

```python
class RTPRelayWorker:
    """RTP 릴레이 워커 - Bridge 모드 추가"""
    
    class RelayMode(Enum):
        BYPASS = "bypass"          # 기존: Caller ↔ Callee 직접 릴레이
        AI = "ai"                  # 기존: Caller ↔ AI (TTS/STT)
        BRIDGE = "bridge"          # 신규: Caller ↔ Server ↔ New Callee
        HOLD = "hold"              # 신규: Caller에게 홀드 음악 재생
    
    def set_bridge_mode(self, callee_endpoint: Tuple[str, int]):
        """AI 모드 → Bridge 모드 전환
        
        Caller의 RTP는 New Callee로 릴레이
        New Callee의 RTP는 Caller로 릴레이
        """
        self.relay_mode = self.RelayMode.BRIDGE
        self.bridge_callee_endpoint = callee_endpoint
        
        # AI 오케스트레이터 분리
        self.ai_orchestrator = None
        
        logger.info(
            "rtp_relay_bridge_mode",
            callee_endpoint=callee_endpoint
        )
    
    def set_hold_mode(self, hold_audio_source=None):
        """Hold 모드 - 발신자에게 대기 음악/안내 재생
        
        Caller의 RTP는 무시 (또는 comfort noise)
        Server → Caller로 hold music 전송
        """
        self.relay_mode = self.RelayMode.HOLD
        self.hold_audio_source = hold_audio_source
    
    async def _relay_packet(self, data: bytes, source: str):
        """패킷 릴레이 - 모드별 분기"""
        
        if self.relay_mode == self.RelayMode.BYPASS:
            # 기존 로직: 상대방에게 직접 전달
            if source == "caller":
                self.callee_transport.sendto(data, self.callee_endpoint)
            else:
                self.caller_transport.sendto(data, self.caller_endpoint)
                
        elif self.relay_mode == self.RelayMode.AI:
            # 기존 로직: Caller 음성 → AI
            if source == "caller":
                await self.ai_orchestrator.on_audio_packet(data, "caller")
                
        elif self.relay_mode == self.RelayMode.BRIDGE:
            # 신규: Caller ↔ Server ↔ New Callee
            if source == "caller":
                # Caller → New Callee
                self.callee_transport.sendto(
                    data, self.bridge_callee_endpoint
                )
            else:
                # New Callee → Caller
                self.caller_transport.sendto(
                    data, self.caller_endpoint
                )
                
        elif self.relay_mode == self.RelayMode.HOLD:
            # Hold: Caller의 음성은 무시, hold music만 전송
            pass
```

#### 4.6.2 미디어 경로 다이어그램

```
[Normal B2BUA Mode - BYPASS]
  Caller:RTP ──→ Server:PortA ──relay──→ Server:PortB ──→ Callee:RTP
  Caller:RTP ←── Server:PortA ←─relay─── Server:PortB ←── Callee:RTP

[AI Mode]
  Caller:RTP ──→ Server:PortA ──→ AI STT/LLM
  Caller:RTP ←── Server:PortA ←── AI TTS

[Transfer Bridge Mode]  ★ 신규
  Caller:RTP ──→ Server:PortA ──relay──→ Server:PortC ──→ NewCallee:RTP
  Caller:RTP ←── Server:PortA ←─relay─── Server:PortC ←── NewCallee:RTP
  
  * PortC = Transfer INVITE의 SDP에 명시된 서버 포트
  * Caller는 자신의 RTP 경로가 변경되지 않음 (투명한 전환)
```

### 4.7 SIP INVITE 구성

#### 4.7.1 Transfer INVITE 메시지 형식

```
INVITE sip:8001@{callee_ip}:{callee_port} SIP/2.0
Via: SIP/2.0/UDP {server_ip}:{server_port};branch=z9hG4bK-xfer-{random}
Max-Forwards: 70
From: "{caller_display}" <sip:{caller_user}@{server_ip}>;tag={from_tag}
To: <sip:8001@{callee_ip}>
Call-ID: {transfer_leg_call_id}
CSeq: 1 INVITE
Contact: <sip:{server_ip}:{server_port}>
Content-Type: application/sdp
Content-Length: {sdp_length}
X-Transfer-Original-Call: {original_call_id}
X-Transfer-Department: {department_name}

v=0
o=- {session_id} {session_version} IN IP4 {server_ip}
s=SIP-PBX Transfer
c=IN IP4 {server_ip}
t=0 0
m=audio {server_rtp_port} RTP/AVP 0 8 101
a=rtpmap:0 PCMU/8000
a=rtpmap:8 PCMA/8000
a=rtpmap:101 telephone-event/8000
a=fmtp:101 0-16
a=sendrecv
a=rtcp:{server_rtcp_port}
```

**핵심 포인트:**
- `From`: 원래 발신자 정보를 표시 (착신자가 누구의 전화인지 알 수 있도록)
- `Call-ID`: 새로운 ID (전환 레그 전용)
- `SDP의 c=/m=`: 서버의 IP와 포트 (미디어 경로가 서버를 경유하도록)
- `X-Transfer-*`: 커스텀 헤더로 전환 메타데이터 전달

### 4.8 통화 종료 처리

```python
async def on_transfer_bye(self, leg_call_id: str, initiator: str):
    """전환 상태의 BYE 처리
    
    Args:
        leg_call_id: BYE를 받은 레그의 Call-ID
        initiator: "caller" 또는 "callee"
    """
    
    # 어떤 전환의 어떤 레그인지 확인
    call_id = self.transfer_leg_map.get(leg_call_id, leg_call_id)
    record = self.active_transfers.get(call_id)
    
    if not record or record.state != TransferState.CONNECTED:
        return
    
    # 한쪽이 끊으면 양쪽 모두 BYE
    if initiator == "caller":
        # 발신자가 끊음 → 착신자에게도 BYE
        await self.sip_endpoint.send_bye(record.transfer_leg_call_id)
    else:
        # 착신자가 끊음 → 발신자에게도 BYE
        await self.sip_endpoint.send_bye(record.call_id)
    
    # 기록 업데이트
    record.ended_at = datetime.utcnow()
    if record.connected_at:
        record.duration_seconds = int(
            (record.ended_at - record.connected_at).total_seconds()
        )
    
    # 정리
    await self._cleanup_transfer(call_id)
    await self._emit_event("transfer_ended", record)
```

---

## 5. Configuration (config.yaml)

```yaml
# config.yaml 추가 항목

ai_voicebot:
  # ... 기존 설정 ...
  
  transfer:
    enabled: true
    
    # 착신 대기 시간 (초) - 이 시간 내에 응답 없으면 실패 처리
    ring_timeout: 30
    
    # 안내 멘트 방식: "template" (빠름) | "llm" (자연스러움)
    announcement_mode: "template"
    
    # 템플릿 기반 안내 멘트
    announcement_template: >
      {department}로 전화 연결하겠습니다.
      연결되는 전화번호는 {phone}입니다.
      연결되는 동안 잠시만 기다려주세요.
    
    # 대기 중 안내 멘트 (링백 중)
    waiting_message: "연결 중입니다. 잠시만 기다려주세요."
    
    # 실패 시 재시도 허용
    retry_enabled: true
    max_retries: 2
    
    # Hold music 파일 (WAV, 8kHz, mono, G.711)
    hold_music_file: null  # null이면 TTS 대기 안내 사용
    
    # 전환 의도 감지 최소 유사도
    min_similarity_threshold: 0.75
    
    # 외부 번호 전환 시 SIP trunk 설정
    sip_trunk:
      enabled: false
      address: "sip-trunk.provider.com"
      port: 5060
      auth:
        username: ""
        password: ""
```

---

## 6. API 설계

### 6.1 Transfer 상태 API

#### GET /api/transfers/

활성 + 최근 전환 목록 조회

```json
// Response
{
  "transfers": [
    {
      "transfer_id": "xfer-a1b2c3d4e5f6",
      "call_id": "call-123456",
      "state": "connected",
      "department_name": "개발부서",
      "phone_display": "8001",
      "caller_display": "홍길동",
      "caller_uri": "sip:1001@192.168.1.100",
      "initiated_at": "2026-01-29T10:30:00Z",
      "ringing_at": "2026-01-29T10:30:02Z",
      "connected_at": "2026-01-29T10:30:08Z",
      "duration_seconds": 125,
      "user_request_text": "개발부서에 호 연결해줘"
    }
  ],
  "total": 1,
  "active_count": 1
}
```

#### GET /api/transfers/{transfer_id}

개별 전환 상세 조회

#### GET /api/transfers/stats

전환 통계 (성공률, 평균 연결 시간 등)

```json
{
  "total_transfers": 156,
  "success_rate": 0.89,
  "avg_ring_duration_seconds": 6.2,
  "avg_call_duration_seconds": 187,
  "by_department": {
    "개발부서": { "count": 45, "success_rate": 0.93 },
    "영업부서": { "count": 67, "success_rate": 0.87 },
    "고객지원": { "count": 44, "success_rate": 0.86 }
  },
  "failure_reasons": {
    "timeout": 8,
    "busy": 5,
    "rejected": 3,
    "unavailable": 1
  }
}
```

### 6.2 WebSocket 이벤트

```typescript
// Frontend에서 수신하는 WebSocket 이벤트

// 전환 시작
{
  event: "transfer_initiated",
  data: {
    transfer_id: string,
    call_id: string,
    department_name: string,
    phone_display: string,
    caller_display: string,
    state: "announce"
  }
}

// 링 시작
{
  event: "transfer_ringing",
  data: {
    transfer_id: string,
    state: "ringing"
  }
}

// 연결 완료
{
  event: "transfer_connected",
  data: {
    transfer_id: string,
    state: "connected",
    connected_at: string
  }
}

// 연결 실패
{
  event: "transfer_failed",
  data: {
    transfer_id: string,
    state: "failed",
    failure_reason: string
  }
}

// 통화 종료
{
  event: "transfer_ended",
  data: {
    transfer_id: string,
    duration_seconds: number
  }
}
```

---

## 7. Frontend 설계

### 7.1 대시보드 확장 (Dashboard)

기존 대시보드의 활성 통화 목록에 전환 상태 표시:

```
┌─────────────────────────────────────────────────────────────┐
│ 📊 대시보드                                                  │
│                                                              │
│ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐        │
│ │ 활성 호   │ │ AI 응대  │ │ 호 전환   │ │ 금일 총  │        │
│ │    3     │ │    1     │ │    1     │ │   47    │        │
│ └──────────┘ └──────────┘ └──────────┘ └──────────┘        │
│                                                              │
│ ┌──────────────────────────────────────────────────────────┐ │
│ │ 활성 통화 목록                                            │ │
│ │                                                          │ │
│ │ 📞 1001→8001  개발부서 전환 중  ⏳ 연결 중...    00:15  │ │
│ │ 🤖 1002→AI    AI 응대           💬 대화 중       01:23  │ │
│ │ 📞 1003→1004  일반 통화          🔊 통화 중       05:47  │ │
│ └──────────────────────────────────────────────────────────┘ │
│                                                              │
│ ┌──────────────────────────────────────────────────────────┐ │
│ │ 호 전환 상태 (실시간)                                     │ │
│ │                                                          │ │
│ │ [xfer-a1b2c3]                                           │ │
│ │ 발신자: 홍길동 (1001)                                    │ │
│ │ 대상: 개발부서 (8001)                                    │ │
│ │ 상태: 🟢 연결됨 (00:02:15)                               │ │
│ │ 요청: "개발부서에 호 연결해줘"                             │ │
│ │                                                          │ │
│ │ 타임라인:                                                │ │
│ │ 10:30:00 ── AI 의도 감지                                 │ │
│ │ 10:30:01 ── 안내 멘트 재생                               │ │
│ │ 10:30:02 ── INVITE 발신, 링 시작                         │ │
│ │ 10:30:08 ── 착신자 응답, 브릿지 연결                      │ │
│ └──────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 7.2 전환 이력 페이지 (/transfers)

```
┌─────────────────────────────────────────────────────────────┐
│ 📞 호 전환 이력                                              │
│                                                              │
│ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐        │
│ │ 총 전환   │ │ 성공률   │ │ 평균 링   │ │ 평균 통화 │        │
│ │   156    │ │  89.1%  │ │  6.2초   │ │  3분 7초 │        │
│ └──────────┘ └──────────┘ └──────────┘ └──────────┘        │
│                                                              │
│ 필터: [전체 ▾] [부서 선택 ▾] [날짜 범위]  🔍 검색           │
│                                                              │
│ ┌──────┬──────┬───────┬───────┬──────┬──────┬──────┐       │
│ │ 시각 │발신자│ 대상  │ 상태  │ 링   │ 통화 │ 비고 │       │
│ ├──────┼──────┼───────┼───────┼──────┼──────┼──────┤       │
│ │10:30 │홍길동│개발부서│🟢성공 │ 6초  │3:05 │      │       │
│ │10:15 │김철수│영업부서│🟢성공 │ 4초  │1:23 │      │       │
│ │09:50 │이영희│고객지원│🔴실패 │ 30초 │ -   │타임아웃│       │
│ │09:30 │박민수│개발부서│🟢성공 │ 8초  │5:47 │      │       │
│ └──────┴──────┴───────┴───────┴──────┴──────┴──────┘       │
│                                                              │
│ ◀ 1 2 3 ... 8 ▶                                             │
└─────────────────────────────────────────────────────────────┘
```

### 7.3 Capability 관리 페이지 확장

기존 `/capabilities` 페이지에서 `transfer` 타입 관리 강화:

```
┌─────────────────────────────────────────────────────────────┐
│ AI 서비스 추가                                               │
│                                                              │
│ 서비스명:     [개발부서 호 연결          ]                   │
│ 설명:         [개발부서로 전화 연결       ]                   │
│ 카테고리:     [호 연결 ▾]                                    │
│ 응답 유형:    [● 호 연결(Transfer)]                          │
│                                                              │
│ ── 호 연결 설정 ──                                           │
│ 전환 대상:    [sip:8001@pbx.local        ]                   │
│              ℹ️ SIP URI, 내선번호, 또는 외부 전화번호        │
│ 표시 번호:    [8001                       ]                   │
│              ℹ️ 발신자에게 안내할 때 표시되는 번호            │
│ 키워드:       [개발부서, 개발팀, 개발실   ]                   │
│                                                              │
│ [저장]  [취소]                                               │
└─────────────────────────────────────────────────────────────┘
```

---

## 8. 구현 계획

### Phase 1: Core Transfer (Backend)

| # | 작업 | 파일 | 예상 |
|---|------|------|------|
| 1.1 | TransferState enum 추가 | `models/enums.py` | 0.5h |
| 1.2 | TransferRecord 모델 | `models/transfer.py` (신규) | 1h |
| 1.3 | TransferManager 클래스 | `sip_core/transfer_manager.py` (신규) | 4h |
| 1.4 | SIPEndpoint.send_transfer_invite() | `sip_core/sip_endpoint.py` | 2h |
| 1.5 | Transfer 응답 핸들러 (180/200/4xx) | `sip_core/sip_endpoint.py` | 2h |
| 1.6 | RTPRelayWorker BRIDGE 모드 | `media/rtp_relay.py` | 2h |
| 1.7 | Transfer BYE 처리 | `sip_core/sip_endpoint.py` | 1h |

### Phase 2: AI Integration

| # | 작업 | 파일 | 예상 |
|---|------|------|------|
| 2.1 | RAG transfer intent 감지 | `orchestrator/ai_orchestrator.py` | 2h |
| 2.2 | Transfer announcement 생성 | `orchestrator/ai_orchestrator.py` | 1h |
| 2.3 | AI↔TransferManager 연동 | `orchestrator/ai_orchestrator.py` | 2h |
| 2.4 | Transfer 실패 → AI 복귀 | `orchestrator/ai_orchestrator.py` | 1h |

### Phase 3: Config & API

| # | 작업 | 파일 | 예상 |
|---|------|------|------|
| 3.1 | config.yaml transfer 섹션 | `config/config.yaml`, `config/models.py` | 1h |
| 3.2 | Transfer REST API | `api/routers/transfers.py` (신규) | 2h |
| 3.3 | Transfer WebSocket 이벤트 | `api/main.py` | 1h |

### Phase 4: Frontend

| # | 작업 | 파일 | 예상 |
|---|------|------|------|
| 4.1 | Dashboard transfer 상태 표시 | `frontend/app/dashboard/page.tsx` | 2h |
| 4.2 | Transfer 이력 페이지 | `frontend/app/transfers/page.tsx` (신규) | 3h |
| 4.3 | Capability 페이지 transfer 확장 | `frontend/app/capabilities/add/page.tsx` | 1h |
| 4.4 | WebSocket transfer 이벤트 연동 | `frontend/lib/websocket.ts` | 1h |

### Phase 5: Testing & Polish

| # | 작업 | 설명 | 예상 |
|---|------|------|------|
| 5.1 | 단위 테스트 | TransferManager, RTP Bridge | 2h |
| 5.2 | 통합 테스트 | 전체 시나리오 (성공 + 실패) | 2h |
| 5.3 | 엣지 케이스 | 동시 전환, 발신자 조기 종료 등 | 2h |

**총 예상 시간: ~35시간**

---

## 9. 엣지 케이스 및 예외 처리

### 9.1 발신자가 전환 중 전화를 끊는 경우

```python
async def on_caller_bye_during_transfer(self, call_id: str):
    """전환 진행 중 발신자 종료"""
    record = self.active_transfers.get(call_id)
    if not record:
        return
    
    if record.state in (TransferState.ANNOUNCE, TransferState.RINGING):
        # 아직 착신자에게 연결 안됨 → CANCEL 전송
        await self.sip_endpoint.send_cancel(record.transfer_leg_call_id)
        record.state = TransferState.CANCELLED
    
    elif record.state == TransferState.CONNECTED:
        # 이미 연결됨 → 착신자에게 BYE
        await self.sip_endpoint.send_bye(record.transfer_leg_call_id)
    
    record.ended_at = datetime.utcnow()
    await self._cleanup_transfer(call_id)
```

### 9.2 동시에 여러 전환 요청

- 같은 call_id에 대해 이미 active transfer가 있으면 거부
- 전환 대상이 이미 통화 중이면 486 Busy Here 응답 처리

### 9.3 전환 대상이 등록되지 않은 사용자

- `_resolve_transfer_target()`에서 예외 발생
- AI에게 "해당 부서의 전화가 현재 연결 불가능합니다" 안내

### 9.4 전환 중 AI Barge-In

- 안내 멘트 재생 중에는 barge-in OFF
- 링백/대기 중에는 barge-in ON (발신자가 "취소해줘" 등 말할 수 있도록)
- 취소 키워드 감지: "취소", "됐어", "그만", "안할래" 등

```python
async def _handle_barge_in_during_transfer(self, call_id: str, user_text: str):
    """전환 대기 중 발신자 음성 입력 처리"""
    
    cancel_keywords = ["취소", "됐어", "그만", "안할래", "안해", "끊어"]
    
    if any(kw in user_text for kw in cancel_keywords):
        # 전환 취소
        await self.cancel_transfer(call_id)
        await self._speak_to_caller(
            call_id, 
            "전화 연결을 취소했습니다. 다른 도움이 필요하시면 말씀해주세요."
        )
        await self._resume_ai_mode(call_id)
```

### 9.5 SIP Trunk 경유 외부 전환

- 외부 번호(+82...)로의 전환은 SIP Trunk 설정 필요
- `config.yaml`의 `transfer.sip_trunk` 설정 활용
- Trunk 인증 (Digest Auth) 지원

---

## 10. 보안 고려사항

| 항목 | 대응 |
|------|------|
| 무제한 전환 악용 | 세션당 최대 전환 횟수 제한 (config: `max_transfers_per_call`) |
| 외부 번호 전환 | 허용 번호 화이트리스트 또는 관리자 승인 필요 |
| 과금 공격 | 외부 trunk 전환 시 과금 제한 설정 |
| SIP 인증 | Transfer INVITE에도 적절한 인증 적용 |
| 대시보드 접근 | Transfer 이력/통계 조회 권한 관리 |

---

## 11. 모니터링 및 로깅

### 11.1 구조화 로그

```python
# Transfer 시작
logger.info("transfer_initiated", 
    call_id=call_id, 
    transfer_id=transfer_id,
    department=department_name,
    transfer_to=transfer_to)

# Transfer 성공
logger.info("transfer_connected",
    call_id=call_id,
    transfer_id=transfer_id,
    ring_duration_ms=ring_duration,
    department=department_name)

# Transfer 실패
logger.warning("transfer_failed",
    call_id=call_id,
    transfer_id=transfer_id,
    status_code=status_code,
    reason=reason,
    ring_duration_ms=ring_duration)
```

### 11.2 메트릭

| 메트릭 | 설명 |
|--------|------|
| `transfer_total` | 총 전환 시도 수 |
| `transfer_success_rate` | 성공률 |
| `transfer_ring_duration_avg` | 평균 링 시간 |
| `transfer_call_duration_avg` | 평균 통화 시간 |
| `transfer_by_department` | 부서별 전환 수 |
| `transfer_failure_by_reason` | 실패 사유별 수 |

---

## 12. 향후 확장 계획

### 12.1 Attended Transfer (상담형 전환)

현재 설계는 **Blind Transfer** (직접 연결) 패턴이다.  
향후 **Attended Transfer** (상담형 전환) 추가:

1. AI가 먼저 착신자에게 연결하여 "홍길동님이 개발 문의로 연결을 요청합니다" 전달
2. 착신자가 수락하면 발신자↔착신자 연결
3. 착신자가 거절하면 발신자에게 안내 후 AI 복귀

### 12.2 Conference (다자 통화)

- 발신자 + 착신자 + AI가 동시에 참여하는 3자 통화
- AI가 실시간 통역/요약 제공

### 12.3 Transfer Queue

- 착신 부서가 모두 통화 중일 때 대기열 관리
- "현재 대기 순서 3번째입니다" 등 안내

### 12.4 Call Recording

- 전환 전 AI 대화 녹음
- 전환 후 통화 녹음 (동의 여부 확인)
- 녹음 기반 후처리 (요약, QA 추출)

---

## 부록 A: 참고 자료

| 자료 | URL | 설명 |
|------|-----|------|
| LiveKit Warm Transfer | https://docs.livekit.io/sip/transfer-warm/ | 가장 성숙한 AI 호 전환 구현 |
| LiveKit Transfer Example | https://github.com/livekit/agents/tree/main/examples/warm-transfer | Python 구현 예제 |
| Vocode Warm Transfer | https://docs.vocode.dev/warm-transfer | Conference 기반 전환 |
| Asterisk Attended Transfer | https://docs.asterisk.org/Configuration/Interfaces/Asterisk-REST-Interface-ARI/Introduction-to-ARI-Transfer-Handling/ | 전통 PBX 전환 |
| RFC 3725 | https://rfc-editor.org/rfc/rfc3725.html | Third Party Call Control |
| RFC 3515 | https://www.rfc-editor.org/rfc/rfc3515 | SIP REFER Method |
| SIP-to-AI Bridge | https://github.com/aicc2025/sip-to-ai | Python SIP+RTP 브릿지 |
