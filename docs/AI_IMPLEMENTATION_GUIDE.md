# 🚀 AI 응대 모드 구현 가이드

## 📋 목차

1. [Phase 1: AI Orchestrator 연결](#phase-1-ai-orchestrator-연결)
2. [Phase 2: AI 모드 호 분기 처리](#phase-2-ai-모드-호-분기-처리)
3. [Phase 3: AI → 발신자 SIP 응답](#phase-3-ai--발신자-sip-응답)
4. [Phase 4: RTP 스트림 AI 연결](#phase-4-rtp-스트림-ai-연결)
5. [Phase 5: 실시간 STT/TTS 파이프라인](#phase-5-실시간-stttts-파이프라인)
6. [Phase 6: AI 통화 종료 처리](#phase-6-ai-통화-종료-처리)

---

## Phase 1: AI Orchestrator 연결

### 🎯 목표
- `ai_orchestrator`를 `CallManager`에 주입
- `None` 체크 제거 및 실제 AI 호출

### 📝 수정 1: `src/main.py` - AI Orchestrator 주입

**위치:** `src/main.py` Line ~330

**변경 전:**
```python
# CallManager 생성
call_manager = CallManager(
    b2bua_ip=advertised_ip,
    media_enabled=True,
    ai_enabled=config.ai.enabled,
    recording_enabled=recording_enabled,
    enable_post_stt=enable_post_stt,
    # ... 기타 설정 ...
)
```

**변경 후:**
```python
# CallManager 생성
call_manager = CallManager(
    b2bua_ip=advertised_ip,
    media_enabled=True,
    ai_enabled=config.ai.enabled,
    recording_enabled=recording_enabled,
    enable_post_stt=enable_post_stt,
    ai_orchestrator=ai_orchestrator,  # ✅ 추가!
    # ... 기타 설정 ...
)

# AI 준비 완료 대기 (옵션)
if ai_voicebot_config and not ai_ready:
    logger.info("waiting_for_ai_initialization")
    # ai_init_task가 완료될 때까지 대기 (최대 60초)
    try:
        await asyncio.wait_for(ai_init_task, timeout=60.0)
    except asyncio.TimeoutError:
        logger.warning("ai_init_timeout", message="AI initialization timed out")
```

### 📝 수정 2: `src/sip_core/call_manager.py` - AI Orchestrator 파라미터 추가

**위치:** `src/sip_core/call_manager.py` Line ~50

**변경 전:**
```python
def __init__(
    self,
    b2bua_ip: str,
    media_enabled: bool = True,
    ai_enabled: bool = False,
    recording_enabled: bool = False,
    # ... 기타 파라미터 ...
):
    self.ai_orchestrator = None  # ❌ 항상 None
```

**변경 후:**
```python
def __init__(
    self,
    b2bua_ip: str,
    media_enabled: bool = True,
    ai_enabled: bool = False,
    recording_enabled: bool = False,
    ai_orchestrator = None,  # ✅ 파라미터로 받기
    # ... 기타 파라미터 ...
):
    self.ai_orchestrator = ai_orchestrator  # ✅ 주입된 객체 저장
    
    if self.ai_orchestrator:
        logger.info("ai_orchestrator_injected",
                   orchestrator_type=type(self.ai_orchestrator).__name__)
    else:
        logger.warning("ai_orchestrator_not_provided",
                      message="AI features will be disabled")
```

---

## Phase 2: AI 모드 호 분기 처리

### 🎯 목표
- AI 모드일 때 착신자로 INVITE 전송하지 않기
- 즉시 AI 통화 세션 생성

### 📝 수정 3: `src/sip_core/sip_endpoint.py` - AI 모드 분기

**위치:** `src/sip_core/sip_endpoint.py` Line ~1900 (`_handle_invite_b2bua` 메서드 내)

**변경 전:**
```python
# 부재중 상태 체크 (웹에서 수동 설정)
from src.sip_core.operator_status import get_operator_status_manager
status_manager = get_operator_status_manager()

if status_manager.is_away(callee_username):
    away_message = status_manager.get_away_message(callee_username)
    logger.info("callee_is_away_activating_ai", ...)
    
    # 즉시 AI 모드 활성화
    if self.call_manager:
        await self.call_manager.handle_no_answer_timeout(call_id, callee_username)
    
    # TODO: AI Voicebot이 응답하도록 처리
    # 현재는 정상 호 처리를 계속 진행 (추후 분기 처리 필요)

# 새로운 Call-ID 생성 (B2BUA leg)
new_call_id = f"b2bua-{random.randint(100000, 999999)}-{call_id[:8]}"
# ... 정상 호 처리 계속 ...
```

**변경 후:**
```python
# 부재중 상태 체크 (웹에서 수동 설정)
from src.sip_core.operator_status import get_operator_status_manager
status_manager = get_operator_status_manager()

if status_manager.is_away(callee_username):
    away_message = status_manager.get_away_message(callee_username)
    logger.info("callee_is_away_activating_ai", ...)
    
    # ✅ AI 모드로 호 처리 (착신자로 INVITE 전송 안 함)
    if self.call_manager and self.call_manager.ai_orchestrator:
        await self._handle_ai_call(
            request=request,
            caller_addr=caller_addr,
            call_id=call_id,
            caller_username=caller_username,
            callee_username=callee_username,
            sdp=sdp,
            via=via,
            from_hdr=from_hdr,
            to_hdr=to_hdr,
            cseq=cseq
        )
        return  # ✅ AI가 처리했으므로 정상 호 처리 중단
    else:
        logger.error("ai_orchestrator_not_available", ...)
        # Fallback: 503 Service Unavailable 응답
        response = (
            "SIP/2.0 503 Service Unavailable\r\n"
            f"Via: {via}\r\n"
            f"From: {from_hdr}\r\n"
            f"To: {to_hdr};tag=b2bua-{random.randint(1000, 9999)}\r\n"
            f"Call-ID: {call_id}\r\n"
            f"CSeq: {cseq}\r\n"
            "Content-Length: 0\r\n"
            "\r\n"
        )
        self._send_response(response, caller_addr)
        return

# 정상 호 처리 (AI 모드가 아닐 때만 실행됨)
new_call_id = f"b2bua-{random.randint(100000, 999999)}-{call_id[:8]}"
# ...
```

### 📝 수정 4: `src/sip_core/sip_endpoint.py` - `_handle_ai_call` 메서드 추가

**위치:** `src/sip_core/sip_endpoint.py` (새 메서드 추가)

```python
async def _handle_ai_call(
    self,
    request: str,
    caller_addr: tuple,
    call_id: str,
    caller_username: str,
    callee_username: str,
    sdp: str,
    via: str,
    from_hdr: str,
    to_hdr: str,
    cseq: str
) -> None:
    """AI 응대 모드 호 처리
    
    착신자 단말로 INVITE를 전송하지 않고,
    AI Orchestrator가 직접 응답합니다.
    
    Args:
        request: 원본 INVITE 요청
        caller_addr: 발신자 주소
        call_id: 호 ID
        caller_username: 발신자 사용자명
        callee_username: 착신자 사용자명 (AI가 대신 응답)
        sdp: SDP body
        via, from_hdr, to_hdr, cseq: SIP 헤더들
    """
    try:
        logger.info("ai_call_handling_start",
                   call_id=call_id,
                   caller=caller_username,
                   callee=callee_username)
        
        print(f"\n🤖 AI Call Mode Activated!")
        print(f"   Caller: {caller_username}")
        print(f"   AI responding as: {callee_username}")
        
        # 1. Active call 정보 저장
        caller_tag = self._extract_tag(from_hdr)
        ai_tag = f"ai-{random.randint(1000, 9999)}"
        
        call_info = {
            'original_call_id': call_id,
            'caller_username': caller_username,
            'callee_username': callee_username,
            'caller_addr': caller_addr,
            'caller_tag': caller_tag,
            'callee_tag': ai_tag,  # AI의 tag
            'original_from': from_hdr,
            'original_to': to_hdr,
            'original_via_branch': self._extract_via_branch(via),
            'original_cseq': cseq,
            'sdp': sdp,
            'state': 'ai_inviting',  # AI 모드 상태
            'start_time': datetime.now(),
            'is_ai_call': True,  # ✅ AI 호 플래그
            'ai_mode_activated': True
        }
        
        self._active_calls[call_id] = call_info
        
        # 2. 100 Trying 전송
        trying_response = (
            "SIP/2.0 100 Trying\r\n"
            f"Via: {via}\r\n"
            f"From: {from_hdr}\r\n"
            f"To: {to_hdr}\r\n"
            f"Call-ID: {call_id}\r\n"
            f"CSeq: {cseq}\r\n"
            "Content-Length: 0\r\n"
            "\r\n"
        )
        self._send_response(trying_response, caller_addr)
        
        # 3. AI Orchestrator에게 호 전달
        if self.call_manager and self.call_manager.ai_orchestrator:
            # RTP 포트 할당
            media_ports = await self.call_manager.allocate_media_ports(call_id)
            ai_rtp_port = media_ports['caller_audio_rtp']  # AI가 사용할 RTP 포트
            
            # AI Orchestrator 시작
            await self.call_manager.ai_orchestrator.handle_incoming_call(
                call_id=call_id,
                caller_username=caller_username,
                callee_username=callee_username,
                caller_sdp=sdp,
                ai_rtp_port=ai_rtp_port
            )
            
            logger.info("ai_orchestrator_call_started",
                       call_id=call_id,
                       ai_rtp_port=ai_rtp_port)
        
        # 4. 180 Ringing 전송 (AI 준비 중)
        ringing_response = (
            "SIP/2.0 180 Ringing\r\n"
            f"Via: {via}\r\n"
            f"From: {from_hdr}\r\n"
            f"To: {to_hdr};tag={ai_tag}\r\n"
            f"Call-ID: {call_id}\r\n"
            f"CSeq: {cseq}\r\n"
            "Contact: <sip:{callee_username}@{self.config.sip.listen_ip}:{self.config.sip.listen_port}>\r\n"
            "Content-Length: 0\r\n"
            "\r\n"
        )
        self._send_response(ringing_response, caller_addr)
        
        logger.info("ai_call_ringing_sent", call_id=call_id)
        
        # 5. AI 준비 완료 후 200 OK 전송 (Phase 3에서 구현)
        # await self._send_ai_200_ok(call_info, ai_sdp)
        
    except Exception as e:
        logger.error("ai_call_handling_error",
                    call_id=call_id,
                    error=str(e),
                    exc_info=True)
        
        # 에러 시 503 응답
        error_response = (
            "SIP/2.0 503 Service Unavailable\r\n"
            f"Via: {via}\r\n"
            f"From: {from_hdr}\r\n"
            f"To: {to_hdr};tag=error-{random.randint(1000, 9999)}\r\n"
            f"Call-ID: {call_id}\r\n"
            f"CSeq: {cseq}\r\n"
            "Content-Length: 0\r\n"
            "\r\n"
        )
        self._send_response(error_response, caller_addr)
```

---

## Phase 3: AI → 발신자 SIP 응답

### 🎯 목표
- AI가 준비되면 200 OK 전송
- AI의 SDP 생성 및 전달

### 📝 수정 5: `_send_ai_200_ok` 메서드 추가

```python
async def _send_ai_200_ok(
    self,
    call_info: dict,
    ai_sdp: str
) -> None:
    """AI가 발신자에게 200 OK 응답
    
    Args:
        call_info: 호 정보
        ai_sdp: AI의 SDP (RTP 포트 포함)
    """
    try:
        call_id = call_info['original_call_id']
        caller_addr = call_info['caller_addr']
        
        # 200 OK 생성
        ok_response = (
            "SIP/2.0 200 OK\r\n"
            f"Via: SIP/2.0/UDP {caller_addr[0]}:{caller_addr[1]};branch={call_info['original_via_branch']}\r\n"
            f"From: {call_info['original_from']}\r\n"
            f"To: {call_info['original_to']};tag={call_info['callee_tag']}\r\n"
            f"Call-ID: {call_id}\r\n"
            f"CSeq: {call_info['original_cseq']}\r\n"
            f"Contact: <sip:{call_info['callee_username']}@{self.config.sip.listen_ip}:{self.config.sip.listen_port}>\r\n"
            "Allow: INVITE, ACK, BYE, CANCEL, OPTIONS\r\n"
            "Content-Type: application/sdp\r\n"
            f"Content-Length: {len(ai_sdp)}\r\n"
            "\r\n"
            f"{ai_sdp}"
        )
        
        self._send_response(ok_response, caller_addr)
        
        call_info['state'] = 'ai_answered'
        call_info['answer_time'] = datetime.now()
        
        logger.info("ai_200_ok_sent",
                   call_id=call_id,
                   ai_sdp_length=len(ai_sdp))
        
        print(f"✅ AI 200 OK sent to caller")
        print(f"   Waiting for ACK...")
        
    except Exception as e:
        logger.error("ai_200_ok_send_error",
                    call_id=call_info.get('original_call_id'),
                    error=str(e),
                    exc_info=True)
```

### 📝 수정 6: AI SDP 생성 로직

**위치:** `src/ai_voicebot/orchestrator.py` (AI Orchestrator 내부)

```python
def generate_ai_sdp(
    self,
    caller_sdp: str,
    ai_rtp_ip: str,
    ai_rtp_port: int
) -> str:
    """AI의 SDP 생성
    
    발신자의 SDP를 기반으로 AI가 응답할 SDP를 생성합니다.
    
    Args:
        caller_sdp: 발신자의 SDP
        ai_rtp_ip: AI의 RTP IP (B2BUA IP)
        ai_rtp_port: AI의 RTP 포트
        
    Returns:
        AI의 SDP
    """
    import time
    
    # 발신자 코덱 추출 (PCMU, PCMA 등)
    caller_codecs = self._extract_codecs_from_sdp(caller_sdp)
    
    # AI SDP 생성 (간단한 예제)
    ai_sdp = f"""v=0
o=ai_voicebot {int(time.time())} {int(time.time())} IN IP4 {ai_rtp_ip}
s=AI Voicebot Session
c=IN IP4 {ai_rtp_ip}
t=0 0
m=audio {ai_rtp_port} RTP/AVP 0 8
a=rtpmap:0 PCMU/8000
a=rtpmap:8 PCMA/8000
a=sendrecv
"""
    
    return ai_sdp

def _extract_codecs_from_sdp(self, sdp: str) -> list:
    """SDP에서 코덱 목록 추출"""
    import re
    codecs = []
    for line in sdp.split('\n'):
        if line.startswith('m=audio'):
            # m=audio 5004 RTP/AVP 0 8 → [0, 8]
            parts = line.split()
            if len(parts) > 3:
                codecs = [int(c) for c in parts[3:] if c.isdigit()]
    return codecs
```

---

## Phase 4: RTP 스트림 AI 연결

### 🎯 목표
- 발신자 RTP → AI Engine
- AI Engine → 발신자 RTP

### 📝 수정 7: AI RTP Relay Worker 생성

**위치:** `src/sip_core/call_manager.py`

```python
async def setup_ai_rtp_relay(
    self,
    call_id: str,
    caller_rtp_addr: tuple,  # (ip, port)
    ai_rtp_port: int
) -> None:
    """AI 통화용 RTP Relay 설정
    
    Args:
        call_id: 호 ID
        caller_rtp_addr: 발신자 RTP 주소
        ai_rtp_port: AI Engine RTP 포트
    """
    from src.media.rtp_relay import RTPRelayWorker
    
    # RTP Relay Worker 생성 (단일 방향)
    # 발신자 → AI, AI → 발신자
    
    relay_worker = RTPRelayWorker(
        call_id=call_id,
        caller_endpoint=caller_rtp_addr,
        callee_endpoint=("127.0.0.1", ai_rtp_port),  # AI Engine (로컬)
        ai_enabled=True,
        recording_enabled=self.recording_enabled,
        bind_ip=self.rtp_bind_ip
    )
    
    # RTP 소켓 시작
    await relay_worker.start()
    
    self._rtp_workers[call_id] = relay_worker
    
    logger.info("ai_rtp_relay_started",
               call_id=call_id,
               caller=f"{caller_rtp_addr[0]}:{caller_rtp_addr[1]}",
               ai_port=ai_rtp_port)
```

---

## Phase 5: 실시간 STT/TTS 파이프라인

### 🎯 목표
- RTP 패킷 → STT → LLM → TTS → RTP 패킷

### 📝 수정 8: AI Orchestrator 콜백 연결

**위치:** `src/ai_voicebot/orchestrator.py`

```python
async def handle_incoming_call(
    self,
    call_id: str,
    caller_username: str,
    callee_username: str,
    caller_sdp: str,
    ai_rtp_port: int
) -> None:
    """수신 호 처리 (AI 응대)
    
    Args:
        call_id: 호 ID
        caller_username: 발신자
        callee_username: 착신자 (AI가 대신 응답)
        caller_sdp: 발신자 SDP
        ai_rtp_port: AI가 사용할 RTP 포트
    """
    try:
        logger.info("ai_orchestrator_handling_call",
                   call_id=call_id,
                   caller=caller_username,
                   callee=callee_username)
        
        # 1. STT 시작
        await self.stt_client.start_streaming(
            call_id=call_id,
            rtp_port=ai_rtp_port,
            callback=self._on_stt_result
        )
        
        # 2. 인사말 TTS
        greeting = f"안녕하세요, {callee_username}의 AI 비서입니다. 무엇을 도와드릴까요?"
        await self.tts_client.speak(
            text=greeting,
            call_id=call_id,
            rtp_port=ai_rtp_port
        )
        
        # 3. 대화 세션 생성
        self.active_sessions[call_id] = {
            'caller': caller_username,
            'callee': callee_username,
            'start_time': datetime.now(),
            'conversation_history': []
        }
        
        logger.info("ai_call_session_started", call_id=call_id)
        
    except Exception as e:
        logger.error("ai_call_handling_error",
                    call_id=call_id,
                    error=str(e),
                    exc_info=True)

async def _on_stt_result(
    self,
    call_id: str,
    text: str,
    is_final: bool
) -> None:
    """STT 결과 콜백
    
    Args:
        call_id: 호 ID
        text: 인식된 텍스트
        is_final: 최종 결과 여부
    """
    if not is_final:
        return  # Interim result 무시
    
    logger.info("ai_stt_result",
               call_id=call_id,
               text=text)
    
    # LLM에 질의
    response_text = await self.llm_client.generate_response(
        user_input=text,
        context=self.active_sessions[call_id]['conversation_history']
    )
    
    # TTS로 응답
    await self.tts_client.speak(
        text=response_text,
        call_id=call_id,
        rtp_port=self.active_sessions[call_id]['rtp_port']
    )
    
    # 대화 히스토리 업데이트
    self.active_sessions[call_id]['conversation_history'].append({
        'role': 'user',
        'content': text
    })
    self.active_sessions[call_id]['conversation_history'].append({
        'role': 'assistant',
        'content': response_text
    })
```

---

## Phase 6: AI 통화 종료 처리

### 🎯 목표
- BYE 수신 시 AI 세션 종료
- RTP Relay 정리
- 녹음 및 STT 후처리

### 📝 수정 9: AI BYE 처리

**위치:** `src/sip_core/sip_endpoint.py` (`_handle_bye` 메서드)

```python
async def _handle_bye(self, request: str, addr: tuple) -> None:
    """BYE 처리 (AI 호 포함)"""
    # ... 기존 코드 ...
    
    call_info = self._active_calls.get(call_id)
    if not call_info:
        return
    
    # AI 호인지 확인
    is_ai_call = call_info.get('is_ai_call', False)
    
    if is_ai_call:
        logger.info("ai_call_bye_received", call_id=call_id)
        
        # AI Orchestrator 종료
        if self.call_manager and self.call_manager.ai_orchestrator:
            await self.call_manager.ai_orchestrator.end_call(call_id)
        
        # 200 OK 전송
        ok_response = (
            "SIP/2.0 200 OK\r\n"
            f"Via: {via}\r\n"
            f"From: {from_hdr}\r\n"
            f"To: {to_hdr}\r\n"
            f"Call-ID: {call_id}\r\n"
            f"CSeq: {cseq}\r\n"
            "Content-Length: 0\r\n"
            "\r\n"
        )
        self._send_response(ok_response, addr)
        
        # 호 정리
        await self.call_manager.cleanup_terminated_call(call_id)
        
        logger.info("ai_call_terminated", call_id=call_id)
    else:
        # 일반 호 처리
        # ... 기존 코드 ...
```

---

## 🔄 전체 시퀀스 다이어그램

```
발신자          SIP PBX            AI Orchestrator       AI Engine
  |                |                      |                   |
  |-- INVITE ----->|                      |                   |
  |                |-- Check Away Status  |                   |
  |                |-- 100 Trying ------->|                   |
  |<-- 100 Trying -|                      |                   |
  |                |-- handle_call() ---->|                   |
  |                |                      |-- Start STT ----->|
  |                |                      |-- TTS Greeting -->|
  |<-- 180 Ring ---|                      |                   |
  |                |-- AI SDP Generate -->|                   |
  |<-- 200 OK -----|<-- AI SDP -----------|                   |
  |-- ACK -------->|                      |                   |
  |                |                      |                   |
  |<=== RTP ======>|<====== RTP =========>|<=== Process ====>|
  |   (음성 대화)   |                      |  STT→LLM→TTS     |
  |                |                      |                   |
  |-- BYE -------->|                      |                   |
  |                |-- end_call() ------->|                   |
  |                |                      |-- Stop STT ------>|
  |<-- 200 OK -----|                      |                   |
  |                |-- cleanup() -------->|                   |
```

---

## ✅ 체크리스트

### Phase 1: AI Orchestrator 연결
- [ ] `main.py`에서 `ai_orchestrator` 주입
- [ ] `CallManager`에서 `ai_orchestrator` 파라미터 추가
- [ ] 로그로 연결 확인

### Phase 2: AI 모드 호 분기
- [ ] `_handle_invite_b2bua`에서 AI 모드 체크
- [ ] `_handle_ai_call` 메서드 구현
- [ ] 100 Trying, 180 Ringing 전송

### Phase 3: AI SIP 응답
- [ ] `_send_ai_200_ok` 메서드 구현
- [ ] AI SDP 생성 로직
- [ ] ACK 수신 처리

### Phase 4: RTP 연결
- [ ] AI RTP Relay Worker 생성
- [ ] RTP 소켓 바인딩
- [ ] 양방향 RTP 스트림 확인

### Phase 5: STT/TTS 파이프라인
- [ ] `handle_incoming_call` 구현
- [ ] STT 스트리밍 시작
- [ ] LLM 응답 생성
- [ ] TTS 응답 전송

### Phase 6: 통화 종료
- [ ] AI BYE 처리
- [ ] AI 세션 정리
- [ ] 녹음 및 STT 후처리

---

## 🧪 테스트 방법

### 1. Phase별 테스트

**Phase 1 테스트:**
```python
# 서버 시작 후 로그 확인
grep "ai_orchestrator_injected" logs/app.log
```

**Phase 2 테스트:**
```python
# 부재중 설정 후 전화
# 로그 확인:
grep "ai_call_handling_start" logs/app.log
```

**Phase 3 테스트:**
```python
# AI 200 OK 전송 확인
grep "ai_200_ok_sent" logs/app.log
```

### 2. 통합 테스트

1. 부재중 설정
2. 전화 걸기
3. AI 인사말 듣기
4. 말하기 (STT)
5. AI 응답 듣기 (TTS)
6. 전화 끊기
7. 녹음 파일 확인

---

## 📚 참고 자료

- [RFC 3261 - SIP](https://tools.ietf.org/html/rfc3261)
- [RTP Relay 구현 가이드](./RTP_RELAY.md)
- [AI Voicebot 아키텍처](./AI_VOICEBOT_ARCHITECTURE.md)

---

## ⚠️ 주의사항

1. **성능 최적화**
   - STT/TTS 지연시간 최소화 필요
   - RTP 버퍼링 최적화

2. **에러 처리**
   - AI 엔진 실패 시 Fallback
   - 네트워크 끊김 대응

3. **보안**
   - AI 세션 격리
   - RTP 암호화 (SRTP) 고려

---

## 🔗 다음 단계

1. Phase 1부터 순서대로 구현
2. 각 Phase별로 테스트
3. 통합 테스트 및 디버깅
4. 성능 최적화 및 모니터링

질문이나 막히는 부분이 있으면 언제든 문의하세요! 🚀
