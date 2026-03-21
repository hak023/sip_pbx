---
title: AI 응대 시 RTP 연결 끊김 근본 원인 분석
date: 2026-03-11T19:00
type: root_cause_analysis
severity: CRITICAL
status: INVESTIGATING
---

# AI 응대 시 RTP 연결 끊김 근본 원인 분석

## 🔴 문제 정의

**증상**: AI 응대 인사말 TTS 첫 청크 생성 후 29ms 만에 RTP 연결 끊김

**영향**:
- AI 인사말 오디오 전송 실패
- `ai_audio_send_error` 100회+ 반복
- 사용자에게 음성이 들리지 않음

---

## 📊 타임라인 분석

```
18:07:53.976  [AI Takeover] 200 OK 전송
18:07:54.420  [SIP] ACK 수신 → call_established
18:07:54.422  [TTS] 인사말 시작 ("안녕하세요, AI 비서입니다...")
              ↓ (1.875초 TTS 생성)
18:07:56.295  [TTS] 첫 청크 생성 완료 (115,256 bytes)
18:07:56.295  [TTS] 첫 청크 yielding 시작
              ↓ (29ms 후)
18:07:56.324  ❌ [RTP] callee_audio_rtp connection_lost
18:07:56.324  ❌ [RTP] Transport cleared
18:07:56.337  ❌ [RTP] caller_audio_rtp connection_lost
18:07:56.349  ❌ [AI] ai_audio_send_error 시작 (100회+)
```

### 핵심 포인트
- **TTS 생성 완료 후 29ms 만에** RTP 연결 끊김
- **사용자의 의도적인 전화 종료가 아님** (BYE 메시지 없음)
- **AI 시스템 내부에서 RTP 연결이 끊어짐**

---

## 🔍 가능한 원인 분석

### 원인 1: Windows ProactorEventLoop UDP 불안정성 ✅ (수정 완료)

**문제**:
- Windows의 `ProactorEventLoop`는 UDP Datagram Transport에서 불안정
- 빠른 데이터 전송 시 `AssertionError` 발생 가능

**증거**:
- 터미널 로그에서 `Fatal write error on datagram transport` 발견
- `AsyncError

: assert fut is self._write_fut`

**수정**:
- `main.py`에서 `WindowsSelectorEventLoopPolicy()` 적용 완료
- 다음 테스트에서 확인 필요

---

### 원인 2: STUN Binding 실패

**의심 사항**:
```
18:07:53.976  [STUN] Binding Request #1 (BEFORE 200 OK)
18:07:53.976  [STUN] Binding Request #1 (AFTER 200 OK)
18:07:54.002  [STUN] Binding Request #2
18:07:54.002  [STUN] Binding Request #2
18:07:54.028  [STUN] Binding Request #3
18:07:54.028  [STUN] Binding Request #3
```

**문제점**:
1. **STUN Binding Request가 중복 전송됨**
2. **STUN Response 수신 로그 없음**
3. **RTP 엔드포인트가 제대로 학습되지 않았을 수 있음**

**RTP 엔드포인트 상태** (Line 202):
```json
{
  "callee_endpoint": "0.0.0.0:0",  // ← 여전히 0.0.0.0:0 (초기값)
  "caller_endpoint": "10.129.219.83:41953"
}
```

**결론**: `callee_endpoint`가 `0.0.0.0:0`인 상태로 남아있음 → **AI가 Callee 역할을 하지만 엔드포인트가 학습되지 않음**

---

### 원인 3: AI Takeover 시 Callee Transport 미설정

**문제**:
- AI Takeover 시 Caller와의 RTP는 설정되지만
- **Callee Transport(AI → Caller)가 제대로 초기화되지 않음**

**코드 추정**:
```python
# AI Takeover 시
self.caller_audio_endpoint = (caller_ip, caller_rtp_port)  # ✅ OK

# ❌ Callee Transport는?
self.callee_audio_endpoint = ("0.0.0.0", 0)  # ← 여전히 초기값
```

**결과**:
- TTS 오디오를 Callee Transport로 전송 시도
- Transport가 유효하지 않아 `connection_lost` 발생

---

### 원인 4: UDP Socket Timeout

**가능성**:
- UDP 소켓이 일정 시간 동안 패킷을 주고받지 않으면 OS가 연결을 끊을 수 있음
- **18:07:53.976 (200 OK) → 18:07:56.324 (connection_lost)** = 약 2.3초

**의심 로직**:
```python
# UDP 소켓 타임아웃 설정?
socket.settimeout(2.0)  # 2초?
```

**검증 필요**:
- RTP Worker의 UDP 소켓 타임아웃 설정 확인
- Keep-alive 패킷 전송 여부

---

## 🛠️ 근본 원인 가설

### 가설 1: AI Takeover 시 Callee Transport 초기화 누락 (가능성 높음)

**문제 흐름**:
```
1. 일반 INVITE (1003 → 1004)
   → RTP Relay Worker 생성
   → Caller/Callee Transport 설정

2. No Answer Timeout (10초)
   → AI Takeover 시작
   → CANCEL 전송 to Callee
   → 200 OK 전송 to Caller (AI와 연결)

3. AI Mode 활성화
   → RTP Worker에 ai_mode=True 설정
   → ❌ Callee Transport는 여전히 "0.0.0.0:0"
   
4. TTS 오디오 생성
   → Callee Transport로 전송 시도
   → ❌ 유효하지 않은 Transport
   → connection_lost
```

**해결 방안**:
```python
# AI Takeover 시 Callee Transport 재설정
async def enable_ai_mode(self):
    """AI 모드 활성화"""
    self.ai_mode = True
    
    # ✅ Callee Transport를 Caller로 리다이렉트
    # AI → Caller로 직접 오디오 전송
    self.callee_audio_endpoint = self.caller_audio_endpoint
    self.callee_rtcp_endpoint = self.caller_rtcp_endpoint
    
    logger.info("ai_takeover_transport_redirected",
               caller_endpoint=self.caller_audio_endpoint,
               note="Callee Transport → Caller로 리다이렉트")
```

---

### 가설 2: Pipecat Transport 연결 문제

**문제**:
- Pipecat의 Datagram Transport가 제대로 초기화되지 않음
- `connection_lost()` 콜백이 예상치 못하게 호출됨

**검증 방법**:
```python
def connection_lost(self, exc):
    """Transport 연결 종료 콜백"""
    logger.warning("datagram_transport_connection_lost",
                  socket_type=self._socket_type,
                  exception=str(exc),
                  exception_type=type(exc).__name__,
                  stack_trace=traceback.format_stack())
```

---

## 🔬 디버깅 계획

### Step 1: STUN Response 확인

**로그 추가**:
```python
def datagram_received(self, data, addr):
    """UDP 패킷 수신"""
    # STUN Response 감지
    if len(data) >= 20 and data[0:2] == b'\x01\x01':
        logger.info("stun_response_received",
                   call_id=self.call_id,
                   from_addr=addr,
                   data_len=len(data))
```

### Step 2: Callee Transport 상태 확인

**AI Takeover 시점에 로그 추가**:
```python
logger.info("ai_takeover_transport_state",
           call_id=self.call_id,
           caller_endpoint=self.caller_audio_endpoint,
           callee_endpoint=self.callee_audio_endpoint,  # ← 확인 필요
           ai_mode=self.ai_mode)
```

### Step 3: connection_lost 원인 추적

**상세 로그**:
```python
def connection_lost(self, exc):
    logger.error("rtp_transport_connection_lost_detail",
                call_id=self.call_id,
                socket_type=self._socket_type,
                exception=str(exc),
                exception_type=type(exc).__name__,
                local_addr=self.transport.get_extra_info('sockname'),
                remote_addr=getattr(self, 'remote_addr', None),
                stack_trace=traceback.format_exc())
```

---

## ✅ 즉시 적용 가능한 수정

### 수정 1: AI Takeover 시 Transport 리다이렉트

**파일**: RTP Worker 또는 관련 파일

```python
async def enable_ai_mode(self, ai_orchestrator):
    """AI 모드 활성화 + Transport 리다이렉트"""
    self.ai_mode = True
    self.ai_orchestrator = ai_orchestrator
    
    # ✅ Callee Transport를 Caller로 리다이렉트
    # (AI는 Caller에게만 오디오 전송)
    if self.caller_audio_endpoint:
        self.callee_audio_endpoint = self.caller_audio_endpoint
        self.callee_rtcp_endpoint = self.caller_rtcp_endpoint
        
        logger.info("ai_takeover_transport_redirected",
                   call_id=self.call_id,
                   caller_endpoint=self.caller_audio_endpoint,
                   note="Callee → Caller 리다이렉트 완료")
```

---

## 🎯 결론

### 가장 가능성 높은 원인

**AI Takeover 시 Callee Transport가 "0.0.0.0:0"로 남아있음**
- AI가 Callee 역할을 하지만
- Callee Transport는 실제 Callee (1004)를 가리킴
- 실제 Callee는 CANCEL로 인해 통화 종료
- Transport가 유효하지 않아 `connection_lost` 발생

### 해결 방안

1. **즉시**: AI Takeover 시 Callee Transport를 Caller로 리다이렉트
2. **중기**: STUN Response 처리 개선
3. **장기**: Pipecat Transport 안정성 강화

---

## 📝 다음 단계

### P0 (즉시)
- [ ] AI Takeover 시 Transport 리다이렉트 로직 추가
- [ ] 상세 로깅 추가 (Transport 상태, connection_lost 원인)

### P1 (테스트 후)
- [ ] STUN Response 처리 확인
- [ ] Windows SelectorEventLoop 효과 검증

---

**작성일**: 2026-03-11T19:00  
**상태**: 🔴 **조사 중 - 수정 필요**
