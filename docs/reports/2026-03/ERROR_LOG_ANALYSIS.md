# 로그 에러 점검 보고서

## 📋 점검 개요

**점검 일시**: 2026-03-11  
**로그 파일**: `sip-pbx/logs/app.log`  
**점검 범위**: Error/Warning 레벨 로그  

---

## 🚨 발견된 주요 이슈

### 1. ⚠️ AI Orchestrator 사용 불가 (Critical)

**발생 시간**: 2026-03-11 09:55:36  
**Call ID**: `cCNYiLs2Rx`  
**심각도**: **HIGH**

#### 에러 로그

```json
{
  "timestamp": "2026-03-11T09:55:36.294",
  "level": "warning",
  "event": "ai_orchestrator_not_available",
  "call_id": "cCNYiLs2Rx",
  "callee": "1004",
  "message": "AI Orchestrator is None - cannot activate AI mode"
}
```

#### 상황 분석

1. **트리거**: 10초 no_answer_timeout 발생
2. **예상 동작**: AI Orchestrator가 자동으로 통화 응대 시작
3. **실제 동작**: AI Orchestrator가 `None` 상태
4. **결과**: AI 자동 응대 실패

#### 영향

- ❌ AI 자동 응답 기능 완전 동작 불가
- ❌ 부재중 통화 처리 실패
- ❌ 고객이 10초 대기 후 통화 종료

#### 근본 원인 추정

```python
# 가능한 원인:

1. AI Orchestrator 초기화 실패
   - Google Cloud 인증 실패
   - LLM/STT/TTS 클라이언트 생성 실패
   - Vector DB 연결 실패

2. CallManager에 AI Orchestrator 주입 안 됨
   - main.py에서 주입 로직 누락
   - 초기화 타이밍 이슈

3. 메모리 부족 또는 리소스 제약
   - AI 컴포넌트 로딩 중 OOM
   - GPU 메모리 부족
```

---

### 2. ⚠️ RTP Relay 무효 Remote 경고 (반복 발생)

**발생 시간**: 2026-03-11 09:55:36~38 (약 2초간)  
**발생 횟수**: **100+ 회**  
**Call ID**: `cCNYiLs2Rx`  
**심각도**: **MEDIUM**

#### 에러 로그

```json
{
  "timestamp": "2026-03-11T09:55:36.377",
  "level": "warning",
  "event": "rtp_relay_skip_invalid_remote",
  "call_id": "cCNYiLs2Rx",
  "socket_type": "caller_audio_rtp"
}
```

#### 상황 분석

1. **시점**: 통화 연결 직후 ~ ACK 수신 전
2. **원인**: Callee의 RTP 주소가 아직 확정되지 않음
3. **동작**: RTP 패킷 수신 시 relay를 스킵
4. **영향**: 초기 몇 초간 오디오 드롭 가능

#### 발생 패턴

```
09:55:36.294 - no_answer_timeout (AI 활성화 시도 실패)
09:55:36.377 - rtp_relay_skip_invalid_remote (시작)
09:55:36.410 - rtp_relay_skip_invalid_remote
09:55:36.590 - rtp_relay_skip_invalid_remote
...
09:55:38.237 - rtp_relay_skip_invalid_remote (종료)
```

**지속 시간**: ~2초 (100+ 패킷)

#### 영향

- ⚠️ 통화 시작 후 초기 오디오 손실 (첫 2초)
- ⚠️ 발신자가 "여보세요?" 반복할 가능성
- ✅ 이후 정상 통화 가능 (경미한 이슈)

---

## 📊 에러 통계

| 에러 유형 | 발생 횟수 | 심각도 |
|----------|----------|--------|
| **AI Orchestrator 사용 불가** | 3회 | 🔴 HIGH |
| **RTP Relay 무효 Remote** | 100+ 회 | 🟡 MEDIUM |

---

## 🔍 원인 분석

### AI Orchestrator 사용 불가

#### 가능한 원인 1: 초기화 실패

서버 시작 로그를 확인해야 합니다:

```bash
# 확인 필요
- "AI Orchestrator initialized successfully"
- "AI Voicebot initialization completed"
- Google Cloud API 인증 성공 여부
```

#### 가능한 원인 2: 주입 누락

```python
# main.py 확인 필요
call_manager = get_call_manager()
ai_orchestrator = get_ai_orchestrator()

# 주입 확인
call_manager.set_ai_orchestrator(ai_orchestrator)
```

#### 가능한 원인 3: 타이밍 이슈

```
서버 시작 → SIP 즉시 Listen → 통화 수신
                                     ↓
                          AI 초기화 중 (백그라운드)
                                     ↓
                          통화는 이미 진행 중 (AI 없음)
```

---

### RTP Relay 무효 Remote

#### 정상적인 동작

이 경고는 **예상된 동작**입니다:

1. **INVITE 전송** → Caller RTP 포트 할당
2. **200 OK 대기** → Callee RTP 주소 미확정
3. **RTP 패킷 수신** → Remote 주소 없어서 스킵
4. **200 OK 수신** → Callee RTP 주소 확정
5. **ACK 전송** → 이후 정상 Relay

#### 문제

- 10초 동안 AI가 응답하지 않아 200 OK가 늦게 옴
- 그 사이 RTP 패킷이 100+ 개 누적
- 모두 스킵되어 초기 오디오 손실

---

## ✅ 해결 방안

### 1. AI Orchestrator 사용 불가 수정

#### Step 1: 초기화 상태 확인

```python
# main.py 또는 서버 시작 로그 확인
logger.info("ai_orchestrator_status",
           available=ai_orchestrator is not None,
           initialized=getattr(ai_orchestrator, '_initialized', False))
```

#### Step 2: 주입 확인

```python
# src/sip_core/call_manager.py
def set_ai_orchestrator(self, orchestrator):
    self.ai_orchestrator = orchestrator
    logger.info("ai_orchestrator_injected",
               available=orchestrator is not None)
```

#### Step 3: 초기화 대기

```python
# main.py
async def wait_for_ai_ready(timeout=120):
    """AI Orchestrator 초기화 완료 대기"""
    start = time.time()
    while time.time() - start < timeout:
        if ai_orchestrator and ai_orchestrator.is_ready():
            logger.info("ai_orchestrator_ready")
            return True
        await asyncio.sleep(1)
    
    logger.error("ai_orchestrator_timeout")
    return False

# 서버 시작 전
await wait_for_ai_ready()
```

#### Step 4: Fallback 처리

```python
# src/sip_core/call_manager.py
async def handle_no_answer_timeout(self, call_id, callee):
    if not self.ai_orchestrator:
        logger.warning("ai_not_available_sending_busy")
        # 486 Busy 전송 (AI 사용 불가)
        await self._send_busy_to_caller(call_id)
        return
    
    # AI 활성화 진행
    await self.activate_ai_mode(call_id, callee)
```

---

### 2. RTP Relay 무효 Remote 개선

이 경고는 정상 동작이지만, 로그 노이즈를 줄일 수 있습니다:

#### Option 1: 로그 레벨 조정

```python
# src/media/rtp_relay.py
if not self.remote_endpoint or self.remote_port == 0:
    # WARNING → DEBUG로 변경 (정상 동작이므로)
    logger.debug("rtp_relay_skip_invalid_remote",
                call_id=self.relay_worker.media_session.call_id,
                socket_type=self.socket_type)
    return
```

#### Option 2: 초기화 체크

```python
# RTP 패킷 수신 시
if not self._remote_confirmed:
    # 최초 1회만 로그
    if not self._skip_warning_logged:
        logger.info("rtp_relay_waiting_for_remote",
                   call_id=call_id,
                   note="Waiting for 200 OK with SDP")
        self._skip_warning_logged = True
    return
```

---

## 🧪 검증 방법

### 1. AI Orchestrator 확인

```bash
# 서버 시작 후 로그 확인
grep "ai_orchestrator" sip-pbx/logs/app.log

# 예상 출력:
# ✅ ai_orchestrator_initialized
# ✅ ai_orchestrator_injected
# ✅ ai_orchestrator_ready
```

### 2. AI 통화 테스트

```
1. 1003 → 1004 전화
2. 1004 응답 안 함 (10초 대기)
3. AI 자동 응대 확인
   ✅ "안녕하세요, AI 비서입니다"
```

### 3. RTP Relay 로그 확인

```bash
# 경고 횟수 확인
grep "rtp_relay_skip_invalid_remote" sip-pbx/logs/app.log | wc -l

# 목표: 100+ → 0 또는 1~2개 (DEBUG 레벨)
```

---

## 📝 추가 조치 사항

### 1. 서버 시작 로그 전체 검토

```bash
# AI Orchestrator 초기화 과정 확인
grep -A 5 "AI Voicebot 백그라운드 초기화" sip-pbx/logs/app.log

# Google Cloud API 인증 확인
grep "Google Cloud" sip-pbx/logs/app.log

# LLM/STT/TTS 클라이언트 초기화 확인
grep "initialized" sip-pbx/logs/app.log | grep -E "STT|TTS|LLM"
```

### 2. 환경 변수 확인

```bash
# Google Cloud 인증 파일 존재 확인
ls -la config/gcp-key.json

# 환경 변수 확인
echo $GOOGLE_APPLICATION_CREDENTIALS
```

### 3. 메모리 사용량 확인

```bash
# Python 프로세스 메모리
ps aux | grep "python.*main.py"

# GPU 메모리 (CUDA 사용 시)
nvidia-smi
```

---

## 🎯 우선순위

| 순위 | 작업 | 예상 시간 | 영향도 |
|-----|------|----------|--------|
| **P0** | AI Orchestrator 초기화 상태 확인 | 10분 | 🔴 HIGH |
| **P0** | CallManager 주입 확인 | 5분 | 🔴 HIGH |
| **P1** | 초기화 대기 로직 추가 | 30분 | 🟡 MEDIUM |
| **P2** | RTP Relay 로그 레벨 조정 | 10분 | 🟢 LOW |

---

## 📌 결론

### 핵심 문제

**AI Orchestrator가 초기화되지 않아 AI 자동 응대 기능이 완전히 동작하지 않습니다.**

### 즉시 조치 필요

1. ✅ 서버 시작 로그에서 AI 초기화 성공 여부 확인
2. ✅ `main.py`에서 AI Orchestrator 주입 확인
3. ✅ Google Cloud API 인증 확인

### 예상 효과

- ✅ AI 자동 응대 기능 복구
- ✅ 부재중 통화 처리 정상화
- ✅ 고객 경험 개선

---

**작성자**: AI Assistant  
**점검 일시**: 2026-03-11  
**상태**: 조치 필요 🔴
