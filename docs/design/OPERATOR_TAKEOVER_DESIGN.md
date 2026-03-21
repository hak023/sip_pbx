# 상담원 실시간 개입 (Operator Takeover) 설계서

## 📋 문서 정보

**작성일**: 2026-03-11  
**버전**: 1.0  
**상태**: 설계 완료  
**관련 문서**: 
- `HITL_IMPLEMENTATION_COMPLETE.md`
- `OPERATOR_AWAY_MODE_DESIGN.md`

---

## 1. 개요

### 1.1 목적

AI가 통화를 응대하는 중에 **상담원이 실시간으로 통화를 가로채는(Takeover)** 기능을 제공합니다.

### 1.2 사용 시나리오

```
[시나리오]
1. 발신자(1003) → 착신자(1004) 전화
2. 1004 부재 → AI가 자동 응대 시작
3. 상담원이 대시보드에서 AI 응대 내용 모니터링
4. 상담원 판단: "내가 직접 응대해야겠다"
5. 상담원이 "전화 받기" 버튼 클릭
6. AI 응대 즉시 종료 → 상담원(1004)에게 통화 연결
7. 상담원-발신자 간 일반 통화 진행
```

### 1.3 핵심 요구사항

| 요구사항 | 설명 |
|---------|------|
| **실시간 모니터링** | 상담원이 AI 응대 내용을 실시간으로 확인 가능 |
| **원클릭 개입** | "전화 받기" 버튼 하나로 즉시 통화 전환 |
| **AI 안전 종료** | AI pipeline, TTS, STT 모두 정상 종료 |
| **SDP Relay** | 발신자-상담원 간 RTP 직접 연결 |
| **상태 동기화** | Frontend/Backend 통화 상태 일치 |

---

## 2. 시스템 아키텍처

### 2.1 전체 흐름도

```
┌─────────────┐
│  발신자     │
│  (1003)     │
└──────┬──────┘
       │ RTP (AI 응대 중)
       ↓
┌─────────────────────────────────────────┐
│          SIP B2BUA (PBX)                │
│  ┌─────────────┐      ┌──────────────┐ │
│  │ RTP Relay   │      │ AI Pipeline  │ │
│  │  Worker     │◄────►│  (STT/TTS)   │ │
│  └─────────────┘      └──────────────┘ │
└─────────────────────────────────────────┘
       │
       │ [상담원이 "전화 받기" 클릭]
       │
       ↓ INVITE (새로운 통화)
┌─────────────┐
│  상담원     │
│  (1004)     │
└─────────────┘

[전환 후]

┌─────────────┐                    ┌─────────────┐
│  발신자     │◄──── RTP ─────────►│  상담원     │
│  (1003)     │      Relay         │  (1004)     │
└─────────────┘                    └─────────────┘
       ↑                                  ↑
       └──────────────┬──────────────────┘
                      │
              ┌───────┴───────┐
              │  SIP B2BUA    │
              │  (Bypass)     │
              └───────────────┘
```

### 2.2 컴포넌트 구조

```
Frontend (React)
├─ LiveCallMonitor
│  ├─ AI 응대 내용 실시간 표시
│  └─ "전화 받기" 버튼 (AI 통화 시에만 표시)
│
Backend (FastAPI)
├─ WebSocket Manager
│  └─ operator_takeover 이벤트 수신
│
SIP Core
├─ CallManager
│  ├─ handle_operator_takeover() ← 새로운 메서드
│  └─ AI → Operator 전환 로직
│
├─ RTPRelayWorker
│  ├─ stop_ai_mode() ← AI pipeline 종료
│  └─ switch_to_bypass_mode() ← 일반 relay 전환
│
└─ AI Orchestrator
   └─ cleanup() ← AI 리소스 정리
```

---

## 3. 상세 설계

### 3.1 Frontend 설계

#### 3.1.1 UI 컴포넌트

**파일**: `frontend/components/LiveCallMonitor.tsx`

```typescript
interface LiveCallData {
  call_id: string;
  caller_id: string;
  callee_id: string;
  is_ai_call: boolean;  // ← AI 통화 여부
  status: 'ringing' | 'established' | 'ended';
  conversation: Array<{
    role: 'ai' | 'user';
    text: string;
    timestamp: string;
  }>;
}

// "전화 받기" 버튼
const TakeoverButton = ({ callId }: { callId: string }) => {
  const [taking, setTaking] = useState(false);
  
  const handleTakeover = async () => {
    setTaking(true);
    try {
      // WebSocket으로 takeover 요청
      socket.emit('operator_takeover', {
        call_id: callId,
        operator_id: currentUser.id,
      });
      
      toast.success('통화를 연결하고 있습니다...');
    } catch (error) {
      toast.error('전화 받기 실패');
      setTaking(false);
    }
  };
  
  return (
    <Button
      variant="primary"
      size="lg"
      onClick={handleTakeover}
      disabled={taking}
      className="takeover-button"
    >
      {taking ? '연결 중...' : '📞 전화 받기'}
    </Button>
  );
};
```

#### 3.1.2 버튼 표시 조건

```typescript
// LiveCallMonitor.tsx
{call.is_ai_call && call.status === 'established' && (
  <div className="takeover-section">
    <div className="ai-warning">
      ⚠️ 현재 AI가 응대 중입니다
    </div>
    <TakeoverButton callId={call.call_id} />
  </div>
)}
```

### 3.2 Backend WebSocket 설계

#### 3.2.1 WebSocket 이벤트 핸들러

**파일**: `src/websocket/server.py`

```python
@sio.on("operator_takeover")
async def handle_operator_takeover(sid, data):
    """
    상담원이 AI 통화를 가로채기
    
    Args:
        data: {
            "call_id": str,      # AI 응대 중인 call_id
            "operator_id": str,  # 상담원 사용자 ID (1004 등)
        }
    """
    call_id = data.get("call_id")
    operator_id = data.get("operator_id")
    
    logger.info("operator_takeover_requested",
               call_id=call_id,
               operator_id=operator_id,
               session_id=sid)
    
    # CallManager에게 위임
    try:
        from src.sip_core.call_manager import get_call_manager
        call_manager = get_call_manager()
        
        success = await call_manager.handle_operator_takeover(
            call_id=call_id,
            operator_id=operator_id,
        )
        
        if success:
            # 성공 알림
            await sio.emit("takeover_success", {
                "call_id": call_id,
                "message": "통화가 연결되었습니다",
            }, room=sid)
            
            logger.info("operator_takeover_success",
                       call_id=call_id,
                       operator_id=operator_id)
        else:
            await sio.emit("takeover_failed", {
                "call_id": call_id,
                "error": "통화 연결 실패",
            }, room=sid)
            
    except Exception as e:
        logger.error("operator_takeover_error",
                    call_id=call_id,
                    error=str(e),
                    exc_info=True)
        
        await sio.emit("takeover_failed", {
            "call_id": call_id,
            "error": str(e),
        }, room=sid)
```

### 3.3 SIP Core 설계

#### 3.3.1 CallManager 신규 메서드

**파일**: `src/sip_core/call_manager.py`

```python
async def handle_operator_takeover(
    self,
    call_id: str,
    operator_id: str,
) -> bool:
    """
    AI 통화를 상담원에게 전환
    
    Process:
    1. AI 통화 확인
    2. 상담원(operator_id)에게 INVITE 전송
    3. 200 OK 대기
    4. AI pipeline 종료
    5. RTP Relay를 Bypass 모드로 전환
    6. 발신자에게 re-INVITE (새로운 SDP)
    
    Args:
        call_id: AI 응대 중인 call_id
        operator_id: 상담원 사용자 ID (예: "1004")
        
    Returns:
        bool: 성공 여부
    """
    try:
        # 1. Call 정보 확인
        call_info = self.call_state_repo.get(call_id)
        if not call_info:
            logger.error("takeover_call_not_found", call_id=call_id)
            return False
        
        if not call_info.get("ai_mode"):
            logger.warning("takeover_not_ai_call",
                          call_id=call_id,
                          ai_mode=False)
            return False
        
        caller = call_info.get("caller")
        original_callee = call_info.get("callee")
        
        logger.info("operator_takeover_starting",
                   call_id=call_id,
                   caller=caller,
                   original_callee=original_callee,
                   operator=operator_id)
        
        # 2. 상담원 등록 확인
        operator_addr = self.sip_endpoint.registry.get(operator_id)
        if not operator_addr:
            logger.error("takeover_operator_not_registered",
                        operator_id=operator_id)
            return False
        
        # 3. RTP Relay 정보 가져오기
        media_session = self.media_session_manager.get(call_id)
        if not media_session or not media_session.rtp_relay:
            logger.error("takeover_no_rtp_relay", call_id=call_id)
            return False
        
        rtp_relay = media_session.rtp_relay
        
        # 4. 새로운 Call-ID 생성 (B2BUA → Operator)
        operator_call_id = f"takeover-{int(time.time() * 1000)}-{call_id[:8]}"
        
        # 5. Operator에게 INVITE 전송
        operator_tag = self._generate_tag()
        
        # SDP: PBX의 RTP 포트 (caller 쪽 포트 재사용)
        caller_rtp_port = media_session.caller_audio_port
        caller_rtcp_port = caller_rtp_port + 1
        
        sdp_body = self._build_sdp_for_takeover(
            rtp_port=caller_rtp_port,
            rtcp_port=caller_rtcp_port,
        )
        
        invite_msg = self._build_invite_to_operator(
            operator_id=operator_id,
            operator_addr=operator_addr,
            call_id=operator_call_id,
            from_tag=operator_tag,
            sdp=sdp_body,
            original_caller=caller,
        )
        
        # INVITE 전송
        self.sip_endpoint.transport.sendto(
            invite_msg.encode('utf-8'),
            operator_addr,
        )
        
        logger.info("takeover_invite_sent_to_operator",
                   call_id=call_id,
                   operator_call_id=operator_call_id,
                   operator_addr=f"{operator_addr[0]}:{operator_addr[1]}")
        
        # 6. 상태 저장 (응답 대기)
        self.call_state_repo.update(call_id, {
            "takeover_in_progress": True,
            "takeover_operator_id": operator_id,
            "takeover_operator_call_id": operator_call_id,
            "takeover_operator_tag": operator_tag,
        })
        
        # 7. 타임아웃 설정 (10초)
        async def takeover_timeout():
            await asyncio.sleep(10)
            if self.call_state_repo.get(call_id, {}).get("takeover_in_progress"):
                logger.warning("takeover_timeout",
                              call_id=call_id,
                              operator_id=operator_id)
                await self._cancel_takeover(call_id, "timeout")
        
        asyncio.create_task(takeover_timeout())
        
        return True
        
    except Exception as e:
        logger.error("operator_takeover_error",
                    call_id=call_id,
                    error=str(e),
                    exc_info=True)
        return False
```

#### 3.3.2 Operator 200 OK 처리

**파일**: `src/sip_core/sip_endpoint.py`

```python
async def _handle_200_ok(self, message: str, addr: tuple):
    """200 OK 처리 (기존 메서드 수정)"""
    
    # ... 기존 로직 ...
    
    # ✅ Takeover 200 OK 처리
    if call_info.get("takeover_in_progress"):
        await self._handle_takeover_200_ok(message, addr, call_id, call_info)
        return
    
    # ... 기존 로직 계속 ...

async def _handle_takeover_200_ok(
    self,
    message: str,
    addr: tuple,
    call_id: str,
    call_info: dict,
):
    """
    Operator가 전화를 받았을 때 (200 OK)
    
    Process:
    1. ACK 전송 (Operator에게)
    2. AI Pipeline 종료
    3. RTP Relay → Bypass 모드 전환
    4. Caller에게 re-INVITE (새로운 SDP: Operator의 RTP 주소)
    5. 상태 업데이트
    """
    try:
        logger.info("takeover_operator_answered",
                   call_id=call_id,
                   operator=call_info.get("takeover_operator_id"))
        
        # 1. Operator SDP 파싱
        operator_sdp = self._parse_sdp(message)
        operator_rtp_ip = operator_sdp.get("connection_ip")
        operator_rtp_port = operator_sdp.get("audio_port")
        
        # 2. ACK 전송 (Operator에게)
        ack_msg = self._build_ack(
            call_id=call_info.get("takeover_operator_call_id"),
            to_tag=self._extract_to_tag(message),
            from_tag=call_info.get("takeover_operator_tag"),
        )
        self.transport.sendto(ack_msg.encode('utf-8'), addr)
        
        logger.info("takeover_ack_sent_to_operator", call_id=call_id)
        
        # 3. AI Pipeline 종료
        media_session = self.call_manager.media_session_manager.get(call_id)
        if media_session and media_session.rtp_relay:
            rtp_relay = media_session.rtp_relay
            
            # AI 모드 종료
            await rtp_relay.stop_ai_mode()
            logger.info("takeover_ai_stopped", call_id=call_id)
            
            # Operator RTP 엔드포인트 설정
            rtp_relay.update_callee_endpoint(
                callee_ip=operator_rtp_ip,
                callee_rtp_port=operator_rtp_port,
                callee_rtcp_port=operator_rtp_port + 1,
            )
            
            # Bypass 모드로 전환
            rtp_relay.set_relay_mode(RelayMode.BYPASS)
            logger.info("takeover_switched_to_bypass",
                       call_id=call_id,
                       operator_rtp=f"{operator_rtp_ip}:{operator_rtp_port}")
        
        # 4. Caller에게 re-INVITE (Operator의 SDP)
        caller_addr = self._get_caller_addr(call_info)
        
        # SDP: PBX IP + Callee 쪽 RTP 포트 (Operator로 relay)
        reinvite_sdp = self._build_sdp_for_reinvite(
            rtp_port=media_session.callee_audio_port,
            rtcp_port=media_session.callee_audio_port + 1,
        )
        
        reinvite_msg = self._build_reinvite_to_caller(
            call_id=call_id,
            call_info=call_info,
            sdp=reinvite_sdp,
        )
        
        self.transport.sendto(reinvite_msg.encode('utf-8'), caller_addr)
        logger.info("takeover_reinvite_sent_to_caller", call_id=call_id)
        
        # 5. 상태 업데이트
        self.call_manager.call_state_repo.update(call_id, {
            "takeover_in_progress": False,
            "takeover_completed": True,
            "ai_mode": False,
            "callee": call_info.get("takeover_operator_id"),
            "state": "established",
        })
        
        # 6. WebSocket: 상태 변경 알림
        from src.websocket import manager as ws_manager
        await ws_manager.emit_call_status_changed(call_id, {
            "status": "operator_takeover_complete",
            "operator_id": call_info.get("takeover_operator_id"),
            "caller_id": call_info.get("caller"),
        })
        
        logger.info("operator_takeover_completed",
                   call_id=call_id,
                   caller=call_info.get("caller"),
                   operator=call_info.get("takeover_operator_id"))
        
    except Exception as e:
        logger.error("takeover_200_ok_error",
                    call_id=call_id,
                    error=str(e),
                    exc_info=True)
        await self._cancel_takeover(call_id, f"error: {e}")
```

#### 3.3.3 RTP Relay 수정

**파일**: `src/media/rtp_relay.py`

```python
async def stop_ai_mode(self):
    """
    AI 모드 종료 (Operator Takeover 시 호출)
    
    Process:
    1. AI Orchestrator cleanup
    2. TTS sender loop 종료
    3. STT 종료
    4. PCM 큐 클리어
    5. AI 관련 태스크 취소
    """
    if not self.ai_mode:
        logger.warning("stop_ai_mode_not_in_ai_mode",
                      call_id=self.media_session.call_id)
        return
    
    logger.info("stopping_ai_mode",
               call_id=self.media_session.call_id,
               reason="operator_takeover")
    
    try:
        # 1. AI Orchestrator cleanup
        if self.ai_orchestrator:
            await self.ai_orchestrator.cleanup(
                call_id=self.media_session.call_id,
            )
            logger.info("ai_orchestrator_cleaned_up",
                       call_id=self.media_session.call_id)
        
        # 2. TTS sender loop 종료
        if hasattr(self, '_tts_sender_task') and self._tts_sender_task:
            self._tts_sender_task.cancel()
            try:
                await self._tts_sender_task
            except asyncio.CancelledError:
                pass
            logger.info("tts_sender_loop_stopped",
                       call_id=self.media_session.call_id)
        
        # 3. PCM 큐 클리어
        if hasattr(self, '_tts_pcm_queue'):
            while not self._tts_pcm_queue.empty():
                try:
                    self._tts_pcm_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
        
        # 4. AI 모드 플래그 해제
        self.ai_mode = False
        self.ai_orchestrator = None
        
        # 5. RTP 타이밍 변수 리셋
        if hasattr(self, '_rtp_base_time'):
            self._rtp_base_time = None
            self._rtp_packets_sent_total = 0
        
        logger.info("ai_mode_stopped_successfully",
                   call_id=self.media_session.call_id)
        
    except Exception as e:
        logger.error("stop_ai_mode_error",
                    call_id=self.media_session.call_id,
                    error=str(e),
                    exc_info=True)

def set_relay_mode(self, mode: RelayMode):
    """
    Relay 모드 변경
    
    Args:
        mode: BYPASS, HOLD, BRIDGE, TRANSFER 등
    """
    old_mode = self.relay_mode
    self.relay_mode = mode
    
    logger.info("relay_mode_changed",
               call_id=self.media_session.call_id,
               old_mode=old_mode.name if old_mode else None,
               new_mode=mode.name)
```

### 3.4 SDP 구성

#### 3.4.1 Operator에게 보내는 INVITE SDP

```python
def _build_sdp_for_takeover(self, rtp_port: int, rtcp_port: int) -> str:
    """
    Operator에게 보낼 SDP
    
    - Connection IP: PBX IP (B2BUA)
    - Media Port: Caller 쪽 RTP 포트 (재사용)
    """
    return f"""v=0
o=- {int(time.time())} {int(time.time())} IN IP4 {self.b2bua_ip}
s=SIP Call
c=IN IP4 {self.b2bua_ip}
t=0 0
m=audio {rtp_port} RTP/AVP 0 8 101
a=rtpmap:0 PCMU/8000
a=rtpmap:8 PCMA/8000
a=rtpmap:101 telephone-event/8000
a=fmtp:101 0-15
a=sendrecv
a=rtcp:{rtcp_port}
"""
```

#### 3.4.2 Caller에게 보내는 re-INVITE SDP

```python
def _build_sdp_for_reinvite(self, rtp_port: int, rtcp_port: int) -> str:
    """
    Caller에게 보낼 re-INVITE SDP
    
    - Connection IP: PBX IP
    - Media Port: Callee 쪽 RTP 포트 (Operator로 relay)
    """
    return f"""v=0
o=- {int(time.time())} {int(time.time())} IN IP4 {self.b2bua_ip}
s=SIP Call
c=IN IP4 {self.b2bua_ip}
t=0 0
m=audio {rtp_port} RTP/AVP 0 8 101
a=rtpmap:0 PCMU/8000
a=rtpmap:8 PCMA/8000
a=rtpmap:101 telephone-event/8000
a=fmtp:101 0-15
a=sendrecv
a=rtcp:{rtcp_port}
"""
```

---

## 4. 시퀀스 다이어그램

### 4.1 전체 흐름

```
발신자(1003)    B2BUA(PBX)    AI Pipeline    Frontend    Operator(1004)
    |              |              |              |              |
    |─ RTP ───────►|              |              |              |
    |              |─ PCM ───────►|              |              |
    |              |              |─ TTS ───────►|              |
    |              |◄─ PCM ───────|              |              |
    |◄─ RTP ───────|              |              |              |
    |              |              |              |              |
    |              |              |              |              |
    |              |              |    [상담원이 모니터링 중]    |
    |              |              |              |              |
    |              |              |◄─ WebSocket ─┤              |
    |              |              |  (AI 응대    |              |
    |              |              |   내용 표시) |              |
    |              |              |              |              |
    |              |              |    [상담원: "전화 받기" 클릭]
    |              |              |              |              |
    |              |◄─ operator_takeover ────────┤              |
    |              |              |              |              |
    |              |─ INVITE ─────────────────────────────────►|
    |              |              |              |              |
    |              |◄─ 100 Trying ────────────────────────────|
    |              |◄─ 180 Ringing ───────────────────────────|
    |              |◄─ 200 OK ────────────────────────────────|
    |              |              |              |              |
    |              |─ ACK ────────────────────────────────────►|
    |              |              |              |              |
    |              |─ stop_ai_mode()             |              |
    |              |              |              |              |
    |              |              |─ cleanup() ─►|              |
    |              |              |   (AI 종료)  |              |
    |              |              |              |              |
    |              |─ set_relay_mode(BYPASS) ───►|              |
    |              |              |              |              |
    |              |─ re-INVITE ─►|              |              |
    |    (SDP: Operator RTP)      |              |              |
    |              |              |              |              |
    |◄─ 200 OK ────|              |              |              |
    |─ ACK ───────►|              |              |              |
    |              |              |              |              |
    |═══ RTP ══════════════════════════════ RTP ════════════════|
    |       (Caller ◄──► PBX ◄──► Operator)     |              |
    |              |              |              |              |
```

### 4.2 에러 처리 흐름

```
Frontend    Backend    CallManager    Operator(1004)
    |          |            |              |
    |─ takeover─►|          |              |
    |          |─ INVITE ──────────────────►|
    |          |            |              |
    |          |◄─ 486 Busy ───────────────|
    |          |            |              |
    |          |─ ACK ──────────────────────►|
    |          |            |              |
    |          |─ restore_ai_mode() ───────►|
    |          |            |              |
    |◄─ takeover_failed ───|              |
    |  (토스트 알림)        |              |
```

---

## 5. 데이터 구조

### 5.1 Call State 확장

**파일**: `src/data/call_state.py`

```python
@dataclass
class CallState:
    # ... 기존 필드 ...
    
    # Operator Takeover 관련
    takeover_in_progress: bool = False
    takeover_operator_id: Optional[str] = None
    takeover_operator_call_id: Optional[str] = None
    takeover_operator_tag: Optional[str] = None
    takeover_completed: bool = False
    takeover_timestamp: Optional[float] = None
```

### 5.2 WebSocket 이벤트

#### 5.2.1 Client → Server

```typescript
// operator_takeover
{
  "call_id": "GKpxoCcZqV",
  "operator_id": "1004",
}
```

#### 5.2.2 Server → Client

```typescript
// takeover_success
{
  "call_id": "GKpxoCcZqV",
  "message": "통화가 연결되었습니다",
  "operator_id": "1004",
}

// takeover_failed
{
  "call_id": "GKpxoCcZqV",
  "error": "상담원이 통화 중입니다",
  "reason": "busy",
}

// call_status_changed (takeover 완료)
{
  "call_id": "GKpxoCcZqV",
  "status": "operator_takeover_complete",
  "operator_id": "1004",
  "caller_id": "1003",
}
```

---

## 6. 에러 처리

### 6.1 에러 시나리오

| 에러 상황 | 처리 방법 |
|---------|---------|
| **Operator 미등록** | Frontend에 즉시 실패 알림, AI 응대 계속 |
| **Operator Busy** | 486 Busy 수신 → AI 복원 → Frontend 알림 |
| **Operator No Answer** | 10초 타임아웃 → AI 복원 → Frontend 알림 |
| **re-INVITE 실패** | Caller와 연결 유지 불가 → BYE 전송 |
| **AI 종료 실패** | 로그만 남기고 Relay 전환 진행 |

### 6.2 Rollback 처리

```python
async def _cancel_takeover(self, call_id: str, reason: str):
    """
    Takeover 실패 시 AI 모드로 복원
    
    Args:
        call_id: 통화 ID
        reason: 실패 이유 ("timeout", "busy", "error" 등)
    """
    logger.warning("takeover_cancelled",
                  call_id=call_id,
                  reason=reason)
    
    try:
        # 1. 상태 복원
        self.call_state_repo.update(call_id, {
            "takeover_in_progress": False,
            "takeover_operator_id": None,
            "takeover_operator_call_id": None,
        })
        
        # 2. AI pipeline 재개 (필요시)
        media_session = self.media_session_manager.get(call_id)
        if media_session and media_session.rtp_relay:
            # AI는 이미 실행 중이므로 특별한 조치 불필요
            pass
        
        # 3. Frontend 알림
        from src.websocket import manager as ws_manager
        await ws_manager.emit("takeover_failed", {
            "call_id": call_id,
            "error": f"통화 연결 실패: {reason}",
            "reason": reason,
        })
        
    except Exception as e:
        logger.error("cancel_takeover_error",
                    call_id=call_id,
                    error=str(e))
```

---

## 7. 테스트 시나리오

### 7.1 정상 시나리오

```
[Test Case 1: 기본 Takeover]
1. 1003 → 1004 전화
2. AI 응대 시작
3. 상담원이 "전화 받기" 클릭
4. 상담원 전화 받음 (200 OK)
5. AI 종료 → Bypass 전환
6. 1003 ◄─► 1004 일반 통화

Expected:
✅ AI 응대 즉시 중단
✅ RTP가 끊김 없이 전환
✅ Frontend 상태 업데이트
```

### 7.2 에러 시나리오

```
[Test Case 2: Operator Busy]
1. 1003 → 1004 전화 (AI 응대)
2. 1004가 다른 통화 중
3. 상담원이 "전화 받기" 클릭
4. 486 Busy 수신
5. AI 응대 계속

Expected:
✅ 토스트: "상담원이 통화 중입니다"
✅ AI 응대 중단 없음

[Test Case 3: Operator No Answer]
1. 1003 → 1004 전화 (AI 응대)
2. 상담원이 "전화 받기" 클릭
3. 1004 전화 벨만 울림 (10초)
4. 타임아웃

Expected:
✅ 토스트: "응답 없음"
✅ AI 응대 계속
```

### 7.3 성능 테스트

| 항목 | 목표 | 측정 방법 |
|------|------|----------|
| **Takeover 지연** | < 2초 | 버튼 클릭 → Operator 전화 벨 |
| **RTP 전환 시간** | < 500ms | AI 마지막 패킷 → Operator 첫 패킷 |
| **AI 종료 시간** | < 1초 | `stop_ai_mode()` 호출 → 완료 |

---

## 8. 로깅

### 8.1 주요 로그 이벤트

```python
# Takeover 요청
logger.info("operator_takeover_requested",
           call_id=call_id,
           operator_id=operator_id)

# INVITE 전송
logger.info("takeover_invite_sent_to_operator",
           call_id=call_id,
           operator_call_id=operator_call_id)

# Operator 응답
logger.info("takeover_operator_answered",
           call_id=call_id,
           response_time_ms=elapsed)

# AI 종료
logger.info("takeover_ai_stopped",
           call_id=call_id,
           ai_duration_seconds=duration)

# Bypass 전환
logger.info("takeover_switched_to_bypass",
           call_id=call_id,
           operator_rtp=f"{ip}:{port}")

# 완료
logger.info("operator_takeover_completed",
           call_id=call_id,
           total_elapsed_ms=elapsed)
```

---

## 9. 보안 고려사항

### 9.1 권한 확인

```python
# WebSocket 핸들러에서 권한 확인
@sio.on("operator_takeover")
async def handle_operator_takeover(sid, data):
    # 1. 세션 확인
    session = await sio.get_session(sid)
    user_id = session.get("user_id")
    
    # 2. Operator 권한 확인
    if user_id != data.get("operator_id"):
        await sio.emit("takeover_failed", {
            "error": "권한이 없습니다",
        }, room=sid)
        return
    
    # 3. Call 소유권 확인
    call_info = call_manager.get_call(data["call_id"])
    if call_info.get("callee") != user_id:
        await sio.emit("takeover_failed", {
            "error": "본인 통화만 받을 수 있습니다",
        }, room=sid)
        return
    
    # ... 나머지 로직 ...
```

### 9.2 Rate Limiting

```python
# 연속 Takeover 시도 제한 (1분에 5회)
from collections import defaultdict
from time import time

takeover_attempts = defaultdict(list)

def check_rate_limit(operator_id: str) -> bool:
    now = time()
    attempts = takeover_attempts[operator_id]
    
    # 1분 이내 시도 필터링
    recent = [t for t in attempts if now - t < 60]
    
    if len(recent) >= 5:
        return False
    
    recent.append(now)
    takeover_attempts[operator_id] = recent
    return True
```

---

## 10. 구현 우선순위

### Phase 1: 기본 기능 (Week 1)

1. ✅ Frontend 버튼 UI
2. ✅ WebSocket 이벤트 핸들러
3. ✅ CallManager.handle_operator_takeover()
4. ✅ Operator INVITE 전송
5. ✅ 200 OK 처리
6. ✅ AI 종료 로직

### Phase 2: 안정화 (Week 2)

1. ✅ re-INVITE 처리
2. ✅ Bypass 모드 전환
3. ✅ 에러 처리 (Busy, Timeout)
4. ✅ Rollback 로직
5. ✅ 로깅 강화

### Phase 3: 고도화 (Week 3)

1. ✅ 권한 확인
2. ✅ Rate limiting
3. ✅ 성능 최적화
4. ✅ UI/UX 개선

---

## 11. 관련 파일

### 11.1 신규 생성

- `frontend/components/TakeoverButton.tsx`
- `src/sip_core/takeover_handler.py` (optional)

### 11.2 수정 필요

- `frontend/components/LiveCallMonitor.tsx`
- `src/websocket/server.py`
- `src/sip_core/call_manager.py`
- `src/sip_core/sip_endpoint.py`
- `src/media/rtp_relay.py`
- `src/data/call_state.py`

---

## 12. 마일스톤

| 주차 | 목표 | 산출물 |
|-----|------|--------|
| **Week 1** | Phase 1 완료 | 기본 Takeover 동작 |
| **Week 2** | Phase 2 완료 | 에러 처리 완료 |
| **Week 3** | Phase 3 + 테스트 | 프로덕션 준비 완료 |

---

## 부록 A: SIP 메시지 예시

### A.1 Operator에게 보내는 INVITE

```
INVITE sip:1004@10.129.219.214:60732 SIP/2.0
Via: SIP/2.0/UDP 10.129.219.233:5060;branch=z9hG4bK-takeover-123
From: <sip:1003@10.129.219.233>;tag=operator-tag-456
To: <sip:1004@10.129.219.233>
Call-ID: takeover-1710137283000-GKpxoCcZ
CSeq: 1 INVITE
Contact: <sip:10.129.219.233:5060>
Max-Forwards: 70
Content-Type: application/sdp
Content-Length: 234

v=0
o=- 1710137283 1710137283 IN IP4 10.129.219.233
s=SIP Call
c=IN IP4 10.129.219.233
t=0 0
m=audio 10000 RTP/AVP 0 8 101
a=rtpmap:0 PCMU/8000
a=rtpmap:8 PCMA/8000
a=rtpmap:101 telephone-event/8000
a=sendrecv
a=rtcp:10001
```

### A.2 Caller에게 보내는 re-INVITE

```
INVITE sip:1003@10.129.219.83:51181 SIP/2.0
Via: SIP/2.0/UDP 10.129.219.233:5060;branch=z9hG4bK-reinvite-789
From: <sip:1004@10.129.219.233>;tag=original-from-tag
To: <sip:1003@10.129.219.233>;tag=original-to-tag
Call-ID: GKpxoCcZqV
CSeq: 2 INVITE
Contact: <sip:10.129.219.233:5060>
Max-Forwards: 70
Content-Type: application/sdp
Content-Length: 234

v=0
o=- 1710137284 1710137284 IN IP4 10.129.219.233
s=SIP Call
c=IN IP4 10.129.219.233
t=0 0
m=audio 10004 RTP/AVP 0 8 101
a=rtpmap:0 PCMU/8000
a=rtpmap:8 PCMA/8000
a=rtpmap:101 telephone-event/8000
a=sendrecv
a=rtcp:10005
```

---

**작성자**: AI Assistant  
**검토자**: -  
**승인자**: -  
**버전**: 1.0  
**최종 수정일**: 2026-03-11
