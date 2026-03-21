# AI 응대 에러 점검 보고서

**작성일**: 2026-03-11  
**버전**: 1.0  
**상태**: 긴급 조치 필요 🔴  
**Call ID**: `shO~u8oPf3`  

---

## 🚨 핵심 문제

### **AI Orchestrator 초기화 실패**

AI 응대 기능이 완전히 동작하지 않는 상태입니다.

#### 에러 로그

```json
{
  "timestamp": "2026-03-11T10:11:43.717",
  "level": "warning",
  "event": "🔄 [AI Takeover] AI Orchestrator not available",
  "call_id": "shO~u8oPf3"
}

{
  "timestamp": "2026-03-11T10:11:43.718",
  "level": "warning",
  "event": "ai_orchestrator_not_available",
  "call_id": "shO~u8oPf3",
  "callee": "1004",
  "message": "AI Orchestrator is None - cannot activate AI mode"
}
```

---

## 📋 상황 분석

### 1. 통화 흐름

```
2026-03-11T10:11:33.709 - 1003 → 1004 전화 시작
2026-03-11T10:11:43.717 - 10초 no_answer_timeout 발생
                       - AI 자동 응대 시도
                       - ❌ AI Orchestrator not available
2026-03-11T10:12:13.396 - 발신자가 BYE 전송 (통화 종료)
```

**지속 시간**: 약 40초 (AI 없이 무음 상태)

### 2. 시스템 초기화 상태

#### ✅ 정상 초기화된 컴포넌트

```
✅ SIP Endpoint (10:08:00.399)
✅ Knowledge Extraction Pipeline v2 (10:08:00.351)
✅ ChromaDB (40 documents, 10:08:00.351)
✅ STT Client (10:08:04.262)
✅ TTS Client
✅ RTP Relay
✅ VAD Detector
✅ Audio Buffer
```

#### ❌ 실패한 컴포넌트

```
❌ AI Orchestrator (초기화 로그 없음)
```

### 3. 근본 원인

서버 시작 로그(line 1~178)를 분석한 결과:

1. **Knowledge Extraction Pipeline v2 초기화 성공** (line 50-51)
2. **AI Voicebot 컴포넌트 초기화 시작** (line 88-100)
3. **AI Orchestrator 초기화 완료 로그 부재** ❌

#### 예상 원인

1. **백그라운드 초기화 실패**:
   - `ai_voicebot_background_init_starting` 로그는 있음 (line 88)
   - `AI Orchestrator initialized` 로그 없음
   - 초기화 중 예외 발생 후 에러 로그가 억제된 것으로 추정

2. **CallManager에 AI Orchestrator 주입 누락**:
   ```python
   # src/main.py
   call_manager.ai_orchestrator = None  # 또는 주입 실패
   ```

3. **초기화 타이밍 이슈**:
   - 서버는 10:08:00에 시작
   - 첫 통화는 10:11:33 (3분 33초 후)
   - AI가 3분 이상 초기화에 실패했거나, 초기화 도중 종료됨

---

## 🔍 상세 로그 분석

### 통화 시작 (10:11:33.709)

```json
{"event": "b2bua_invite_received", "call_id": "shO~u8oPf3", "caller": "1003", "callee": "1004"}
{"event": "call_session_added", "call_id": "shO~u8oPf3"}
{"event": "no_answer_timer_started", "call_id": "shO~u8oPf3", "timeout": 10}
```

✅ 정상: SIP 시그널링 및 RTP 설정 완료

### AI 응답 시도 (10:11:43.717)

```json
{"event": "no_answer_timeout_activating_ai", "callee": "1004", "timeout": 10}
{"event": "🔄 [AI Takeover] Sending CANCEL to callee"}
{"event": "ai_mode_activated", "call_id": "shO~u8oPf3", "callee": "1004"}
{"event": "🔄 [AI Takeover] Enabling AI mode on RTP Worker"}
{"event": "🔄 [AI Takeover] AI Orchestrator not available"} ⚠️
{"event": "ai_orchestrator_not_available", "message": "AI Orchestrator is None"} ❌
```

✅ SIP 절차: CANCEL → 200 OK → ACK 정상  
❌ AI 초기화: AI Orchestrator가 None 상태

### RTP Relay 경고 (10:11:44~10:12:13)

```json
// 약 1,500회 반복
{"event": "rtp_relay_skip_invalid_remote", "socket_type": "caller_audio_rtp"}
```

**원인**: AI가 활성화되지 않아 RTP 엔드포인트가 설정되지 않음  
**영향**: 발신자가 아무 소리도 듣지 못함 (무음 상태)

### 통화 종료 (10:12:13.396)

```json
{"event": "bye_received", "call_id": "shO~u8oPf3"}
{"event": "Empty buffer, skipping WAV save"} // caller.wav, callee.wav, mixed.wav
{"event": "recording_stopped", "duration": 39.682834, "has_transcript": false}
```

✅ 정상 종료 처리  
⚠️ 녹음 파일 없음 (버퍼 비어있음)  
⚠️ 대화 내용 없음 (AI 미동작)

---

## ✅ 해결 방안

### Step 1: AI Orchestrator 초기화 로그 확인

```bash
# 서버 시작 로그에서 AI Orchestrator 초기화 확인
grep -E "AI Orchestrator|ai_orchestrator_ready|voicebot initialization completed" sip-pbx/logs/app.log

# 예상 출력:
# ✅ AI Orchestrator initialized successfully
# ✅ AI Voicebot initialization completed
```

**예상 결과**: 해당 로그가 없을 것으로 추정

### Step 2: 백그라운드 초기화 에러 확인

```bash
# 초기화 중 발생한 예외/에러 확인
grep -E "exception|traceback|failed|error" sip-pbx/logs/app.log | grep -A 5 "ai_voicebot"
```

### Step 3: main.py에서 AI Orchestrator 주입 확인

```python
# src/main.py 확인 필요
async def main():
    # ...
    
    # ✅ AI Orchestrator 초기화 확인
    ai_orchestrator = await ai_factory.create_ai_orchestrator()
    
    # ✅ CallManager에 주입 확인
    call_manager.set_ai_orchestrator(ai_orchestrator)
    
    # ✅ 초기화 완료 로그
    logger.info("ai_orchestrator_injected",
               available=ai_orchestrator is not None)
```

### Step 4: 초기화 대기 로직 추가 (권장)

```python
# src/main.py
async def wait_for_ai_orchestrator(timeout=120):
    """AI Orchestrator 초기화 완료 대기"""
    start = time.time()
    while time.time() - start < timeout:
        if call_manager.ai_orchestrator is not None:
            logger.info("ai_orchestrator_ready",
                       elapsed=time.time() - start)
            return True
        await asyncio.sleep(1)
    
    logger.error("ai_orchestrator_timeout",
                elapsed=timeout)
    return False

# 서버 시작 전 호출
await wait_for_ai_orchestrator()
```

### Step 5: 서버 재시작 및 검증

```bash
# 1. 서버 재시작
python sip-pbx/src/main.py

# 2. 초기화 로그 확인
tail -f sip-pbx/logs/app.log | grep -E "AI Orchestrator|ai_orchestrator"

# 3. 테스트 통화
# 1003 → 1004 전화
# 10초 대기 (no_answer_timeout)
# ✅ AI 자동 응답 확인: "안녕하세요, AI 비서입니다"
```

---

## 🎯 우선순위

| 순위 | 작업 | 예상 시간 | 영향도 |
|------|------|----------|--------|
| **P0** | AI Orchestrator 초기화 실패 원인 확인 | 10분 | 🔴 CRITICAL |
| **P0** | main.py에서 AI Orchestrator 주입 확인 | 5분 | 🔴 CRITICAL |
| **P1** | 백그라운드 초기화 에러 로그 확인 | 10분 | 🟡 HIGH |
| **P1** | 초기화 대기 로직 추가 | 20분 | 🟡 HIGH |
| **P2** | RTP 경고 로그 레벨 조정 (DEBUG) | 5분 | 🟢 LOW |

---

## 📊 영향 범위

### 사용자 경험

```
❌ AI 자동 응답 불가
❌ 발신자가 10초 대기 후 무음 상태 경험
❌ 발신자가 40초 동안 아무 응답 없이 대기
❌ 발신자가 직접 통화 종료
```

### 시스템 상태

```
✅ SIP 시그널링 정상
✅ RTP Relay 정상 (AI 없이)
✅ 녹음 기능 정상 (단, 버퍼 비어있음)
✅ CDR 기록 정상
❌ AI Voicebot 완전 동작 불가
❌ STT/TTS/LLM/RAG 미활용
```

---

## 🔧 즉시 조치 사항

### 1. 서버 로그 전체 검토

```bash
# AI Orchestrator 관련 모든 로그 추출
grep -n "AI Orchestrator\|ai_orchestrator\|create_ai_orchestrator" sip-pbx/logs/app.log > ai_init_logs.txt
```

### 2. src/main.py 확인

```python
# 다음 항목 확인:
1. ai_orchestrator = await ai_factory.create_ai_orchestrator()
2. call_manager.set_ai_orchestrator(ai_orchestrator)
3. logger.info("ai_orchestrator_injected", ...)
```

### 3. 예외 처리 확인

```python
# src/ai_voicebot/factory.py
async def create_ai_orchestrator(self):
    try:
        orchestrator = AIOrchestrator(...)
        logger.info("ai_orchestrator_created_successfully")
        return orchestrator
    except Exception as e:
        logger.error("ai_orchestrator_creation_failed",
                    error=str(e),
                    traceback=traceback.format_exc())
        raise
```

---

## 📌 결론

### 핵심 문제

**AI Orchestrator가 초기화되지 않아 AI 자동 응대 기능이 완전히 동작하지 않습니다.**

### 즉시 필요한 조치

1. ✅ AI Orchestrator 초기화 실패 원인 파악
2. ✅ main.py에서 주입 로직 확인
3. ✅ 백그라운드 초기화 예외 로그 확인
4. ✅ 서버 재시작 후 검증

### 예상 효과

- ✅ AI 자동 응대 기능 복구
- ✅ 발신자가 10초 후 AI 응답 청취
- ✅ STT/TTS/LLM 정상 동작
- ✅ 고객 경험 개선

---

**작성자**: AI Assistant  
**점검 일시**: 2026-03-11 10:13  
**상태**: 긴급 조치 필요 🔴  

**관련 문서**:  
- [ERROR_LOG_ANALYSIS.md](ERROR_LOG_ANALYSIS.md) - 이전 동일 이슈 분석  
- [SYSTEM_OVERVIEW.md](../SYSTEM_OVERVIEW.md) - AI Voicebot 아키텍처  
- [ai-voicebot-architecture.md](../ai-voicebot-architecture.md) - 상세 설계  

---

*최종 업데이트: 2026-03-11*
