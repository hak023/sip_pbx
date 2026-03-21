---
title: RTP Relay Invalid Remote 경고 분석
date: 2026-03-11
type: error_analysis
tags: [rtp, relay, ai, orchestrator, debugging]
call_id: ~heMLisqRq
---

# RTP Relay Invalid Remote 경고 분석 보고서

## 📋 문제 상황

### 증상

```log
{"timestamp": "2026-03-11T14:06:30.938", "level": "warning", "event": "rtp_relay_skip_invalid_remote", "call_id": "~heMLisqRq", "socket_type": "caller_audio_rtp"}
```

이 경고가 통화 중 **반복적으로 발생** (수백 번)하며 멈추지 않음.

### 발생 시나리오

1. Caller(1003) → Callee(1004)로 INVITE
2. Callee가 10초 내에 응답하지 않음
3. **No-Answer Timeout** → **AI Takeover** 모드 활성화
4. Caller가 RTP 패킷 전송 시작
5. **`rtp_relay_skip_invalid_remote` 경고 반복 발생**

---

## 🔍 원인 분석

### 1. 로그 타임라인 분석

```
14:02:28.134 - ✅ AI Orchestrator initialized successfully
14:06:19.851 - 📞 Call started (call_id: ~heMLisqRq)
14:06:19.851 - 🔧 RTP Relay Worker created
                  caller: "10.129.219.83:43835" ✅
                  callee: "0.0.0.0:0" ← ⚠️ 문제!
14:06:29.864 - ⏰ No-answer timeout
14:06:29.864 - 🤖 AI Takeover 시작
14:06:29.864 - ❌ AI Orchestrator not available (RTP Worker에서)
14:06:30.xxx - 🔁 rtp_relay_skip_invalid_remote 반복 발생
```

### 2. 핵심 문제

#### (1) Callee Remote Address가 `0.0.0.0:0`

```json
Line 186: {
  "event": "rtp_relay_worker_created",
  "caller": "10.129.219.83:43835",  ← ✅ 정상
  "callee": "0.0.0.0:0"              ← ❌ 문제
}
```

**이유**:
- AI Takeover 시나리오에서는 Callee(착신자)가 실제로 연결되지 않음
- 대신 AI Orchestrator가 Callee 역할을 해야 함
- 따라서 `callee: "0.0.0.0:0"`은 정상적인 초기 상태

#### (2) AI Orchestrator가 RTP Worker에 연결되지 않음

```json
Line 219: {
  "level": "warning",
  "event": "🔄 [AI Takeover] AI Orchestrator not available",
  "call_id": "~heMLisqRq"
}
```

**원인**:
- AI Orchestrator는 이미 초기화 완료됨 (14:02:28)
- 하지만 **RTP Worker에게 AI Orchestrator 참조가 전달되지 않음**
- RTP Worker가 AI 모드로 전환되었으나, 실제 AI 객체가 없음

#### (3) Caller가 RTP 패킷을 계속 전송

- Caller는 200 OK를 받았으므로 통화 연결됨으로 인식
- Caller는 20ms마다 RTP 패킷 전송 (정상)
- RTP Worker는 이 패킷을 받지만:
  - Callee remote address: `0.0.0.0:0` (유효하지 않음)
  - AI Orchestrator: `None` (연결되지 않음)
  - **→ 패킷을 relay할 수 없음**
  - **→ `rtp_relay_skip_invalid_remote` 경고 발생**

---

## 🎯 근본 원인

### **AI Orchestrator가 RTP Worker에 주입(inject)되지 않음**

```python
# 정상적인 플로우 (예상):
1. AI Orchestrator 초기화 ✅ (14:02:28)
2. Call Manager가 RTP Worker 생성
3. Call Manager가 RTP Worker에 AI Orchestrator 참조 전달 ← ❌ 이 단계가 누락됨
4. AI Takeover 시 RTP Worker가 AI Orchestrator 사용
```

### 현재 플로우 (실제):

```python
1. AI Orchestrator 초기화 ✅ (14:02:28)
2. Call Manager가 RTP Worker 생성 ✅
3. ❌ AI Orchestrator 참조가 전달되지 않음
4. AI Takeover 시 RTP Worker.ai_orchestrator = None ← ❌
5. RTP 패킷 처리 불가 → 경고 반복
```

---

## 📊 데이터 흐름 (정상 vs 현재)

### 정상적인 AI Takeover 흐름:

```
Caller (10.129.219.83:43835)
  ↓ RTP 패킷
B2BUA RTP Worker (10024)
  ↓ relay to
AI Orchestrator
  ↓ STT → LLM → TTS
B2BUA RTP Worker (10024)
  ↓ RTP 패킷
Caller (10.129.219.83:43835)
```

### 현재 문제:

```
Caller (10.129.219.83:43835)
  ↓ RTP 패킷
B2BUA RTP Worker (10024)
  ↓ relay to
❌ ai_orchestrator = None
  ↓
⚠️ rtp_relay_skip_invalid_remote
  (callee remote = 0.0.0.0:0, AI 없음)
```

---

## 🔧 해결 방법

### 1. AI Orchestrator 참조를 RTP Worker에 전달

**Call Manager 수정 필요**:

```python
# 예상 코드 위치: src/sip_core/call_manager.py 또는 유사 파일

class CallManager:
    def __init__(self):
        self.ai_orchestrator = None
    
    def set_ai_orchestrator(self, ai_orchestrator):
        """AI Orchestrator 참조 설정"""
        self.ai_orchestrator = ai_orchestrator
    
    def create_rtp_worker(self, call_id, ...):
        """RTP Worker 생성 시 AI Orchestrator 전달"""
        worker = RTPRelayWorker(
            call_id=call_id,
            ai_orchestrator=self.ai_orchestrator,  # ← 이 부분 추가/수정 필요
            ...
        )
        return worker
```

### 2. AI Takeover 시 Remote Address 업데이트

**RTP Worker 수정 필요**:

```python
class RTPRelayWorker:
    async def enable_ai_mode(self):
        """AI 모드 활성화"""
        if self.ai_orchestrator is None:
            logger.warning("AI Orchestrator not available")
            return False
        
        # AI가 있으면 Callee remote address를 AI의 RTP endpoint로 설정
        self.callee_remote_addr = self.ai_orchestrator.get_rtp_endpoint()
        self.ai_enabled = True
        
        # AI Pipeline 시작
        await self.ai_orchestrator.start_pipeline(self.call_id)
        return True
```

### 3. 초기화 순서 보장

**Main 시작 로직 수정**:

```python
# main.py 또는 초기화 파일

async def initialize():
    # 1. Call Manager 생성
    call_manager = CallManager()
    
    # 2. AI Orchestrator 생성
    ai_orchestrator = await create_ai_orchestrator()
    
    # 3. Call Manager에 AI 주입
    call_manager.set_ai_orchestrator(ai_orchestrator)  # ← 이 단계가 누락되어 있음
    
    # 4. SIP Server 시작
    sip_server = SIPServer(call_manager)
    await sip_server.start()
```

---

## 🧪 검증 방법

### 수정 후 확인할 로그:

```json
// 1. AI Orchestrator 주입 성공
{
  "event": "ai_orchestrator_injected",
  "call_manager": "CallManager",
  "ai_ready": true
}

// 2. RTP Worker 생성 시 AI 참조 전달
{
  "event": "rtp_relay_worker_created",
  "call_id": "...",
  "ai_orchestrator_available": true  // ← true로 변경되어야 함
}

// 3. AI Takeover 성공
{
  "event": "ai_mode_enabled",
  "call_id": "...",
  "ai_pipeline_started": true,
  "callee_remote_addr": "127.0.0.1:XXXXX"  // ← 0.0.0.0:0이 아님
}

// 4. RTP 패킷 정상 처리
{
  "event": "rtp_packet_relayed",
  "call_id": "...",
  "direction": "caller_to_ai",
  "size": 172
}
```

### 경고가 사라져야 함:

```diff
- {"event": "rtp_relay_skip_invalid_remote", ...}  ← 이 경고가 없어야 함
+ {"event": "rtp_packet_relayed_to_ai", ...}      ← 정상 처리 로그
```

---

## 📝 추가 확인 사항

### 1. SDP 협상은 정상

```json
Line 180: {
  "event": "sdp_after_media_port_replacement",
  "c": "10.129.219.233",  // ← B2BUA IP
  "m_audio": 10028,       // ← B2BUA Port
  "o": "10.129.219.233"   // ← Origin IP
}
```

SDP는 정상적으로 B2BUA IP/Port로 재작성되었음.

### 2. RTP 소켓 바인딩은 정상

```json
Line 187-190: {
  "event": "rtp_socket_bound",
  "port": 10024, "type": "caller_audio_rtp"   // ✅
  "port": 10025, "type": "caller_audio_rtcp"  // ✅
  "port": 10028, "type": "callee_audio_rtp"   // ✅
  "port": 10029, "type": "callee_audio_rtcp"  // ✅
}
```

RTP 소켓은 모두 정상 바인딩되었음.

### 3. Caller는 RTP 패킷을 정상 전송 중

```json
Line 297: {
  "event": "stun_binding_request_relaying",
  "from_addr": "10.129.219.83:54214"  // ← Caller가 패킷 전송 중
}
```

Caller는 문제없이 RTP 패킷을 B2BUA로 전송 중.

---

## ✅ 결론

### **이 경고는 버그가 아니라 구성(Configuration) 문제입니다.**

1. ✅ AI Orchestrator는 정상 초기화됨
2. ✅ RTP Worker는 정상 생성됨
3. ❌ **AI Orchestrator → RTP Worker 연결이 누락됨**
4. 결과: AI Takeover 시 RTP 패킷 처리 불가

### 해결 필요 파일:

- `src/sip_core/call_manager.py` - AI 주입 로직
- `src/sip_core/rtp_relay_worker.py` - AI 모드 활성화 로직
- `main.py` - 초기화 순서

### 다음 단계:

1. Call Manager 코드 확인
2. AI Orchestrator 주입 로직 추가
3. RTP Worker AI 연결 검증
4. 테스트 및 로그 확인

---

**작성일**: 2026-03-11
**분석자**: AI Agent
**우선순위**: 🔴 **HIGH** (AI 통화 기능이 동작하지 않음)
**상태**: 🔍 **원인 파악 완료** → 🔧 **수정 필요**
