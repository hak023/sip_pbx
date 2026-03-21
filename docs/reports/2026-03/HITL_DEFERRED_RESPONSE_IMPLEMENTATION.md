# HITL 지연 응답 구현 완료 보고서

**완료일**: 2026-03-17  
**설계 문서**: [HITL_DEFERRED_RESPONSE_DESIGN.md](../../design/HITL_DEFERRED_RESPONSE_DESIGN.md)  
**상태**: ✅ 구현 완료 (테스트 대기)

---

## 구현 요약

HITL timeout을 20분으로 확대하고, 운영자 응답 시 자연스러운 문맥 전환을 지원하는 새로운 HITL 로직을 구현했습니다.

---

## 구현 완료 사항

### ✅ Phase 1: HITL Timeout 20분으로 확대

**파일**: `src/services/hitl.py`

**변경 사항**:
```python
# 변경 전
self._timeout_seconds: float = 20.0
self._timeout_message: Optional[str] = None

# 변경 후
self._timeout_seconds: float = 1200.0  # 20분
self._timeout_message: Optional[str] = "죄송합니다. 확인이 지연되고 있습니다. 조금만 더 기다려 주시겠어요?"
```

**효과**:
- 운영자에게 20분의 충분한 응답 시간 제공
- 짧은 timeout으로 인한 불필요한 fallback 메시지 방지

---

### ✅ Phase 2: AI 응답 메시지 통일

**파일**: `src/ai_voicebot/pipecat/processors/hitl_processor.py`

**변경 사항**:
```python
class HITLManager:
    # 통일된 HITL 요청 메시지
    HITL_REQUEST_MESSAGE = "해당 내용은 제가 모르는 내용이라서 별도 확인 해보고 알려드리겠습니다."
    
    async def handle_hitl_result(...):
        # intent 무관하게 통일된 메시지 반환
        return self.HITL_REQUEST_MESSAGE
```

**효과**:
- transfer, complaint, low_confidence 모든 케이스에서 동일한 메시지
- 사용자 경험 일관성 향상

---

### ✅ Phase 3-1: HITLService.get_response_queue() 추가

**파일**: `src/services/hitl.py`

**추가된 메서드**:
```python
def get_response_queue(self, call_id: str) -> Optional[asyncio.Queue]:
    """통화별 응답 큐 반환"""
    return self._queues.get(call_id)
```

**효과**:
- WebSocket에서 호출하던 누락된 메서드 구현
- HITL 응답 전달 경로 정상화

---

### ✅ Phase 3-2: RAGProcessor 문맥 전환 로직

**파일**: `src/ai_voicebot/pipecat/processors/rag_processor.py`

**변경 사항**:

1. **Consumer에서 original_question 처리**:
```python
async def _consume():
    response_data = await proc._hitl_response_queue.get()
    original_question = response_data.get("original_question", "")
    
    # 문맥 전환 문구 추가
    if msg_type == "hitl_response" and original_question:
        text = proc._build_context_transition(original_question, text)
```

2. **문맥 전환 문구 생성 메서드 추가**:
```python
def _build_context_transition(self, original_question: str, operator_response: str) -> str:
    """아까 문의주신 '[질문]'에 대해 확인되어 알려드리겠습니다. [답변]"""
    question_summary = original_question[:30] + "..." if len(original_question) > 30 else original_question
    transition = f"아까 문의주신 '{question_summary}' 내용에 대해 확인되어 알려드리겠습니다. {operator_response}"
    return transition
```

3. **LLMFullResponseStartFrame/EndFrame 추가**:
```python
await proc.push_frame(LLMFullResponseStartFrame())
await proc.push_frame(TextFrame(text=text))
await proc.push_frame(LLMFullResponseEndFrame())
```

**효과**:
- 운영자 응답 도착 시 자연스러운 문맥 전환
- "아까 문의주신..." 문구로 대화 흐름 유지

---

### ✅ Phase 3-3: WebSocket original_question 전달

**파일**: `src/websocket/server.py`

**변경 사항**:
```python
@sio.event
async def submit_hitl_response(sid: str, data: dict) -> dict:
    original_question = data.get("original_question", "")  # 추가
    question = data.get("question", original_question)
    
    await response_queue.put({
        "type": "hitl_response",
        "text": refined_response,
        "original_text": response_text,
        "original_question": original_question,  # 추가
        "call_id": call_id,
    })
```

**효과**:
- Frontend에서 원래 질문을 Backend로 전달
- 문맥 전환 문구 생성에 활용

---

## 변경된 파일 목록

### Backend
1. ✅ `src/services/hitl.py` - Timeout 20분, get_response_queue() 추가
2. ✅ `src/ai_voicebot/pipecat/processors/hitl_processor.py` - 메시지 통일
3. ✅ `src/ai_voicebot/pipecat/processors/rag_processor.py` - 문맥 전환 로직
4. ✅ `src/websocket/server.py` - original_question 전달

---

## 데이터 흐름 (Before/After)

### Before (기존)
```
[11:00] HITL 발동 → "확인해보겠습니다" (20초 timeout 시작)
[11:00+20초] Timeout → "별도 연락 드릴까요?"
[11:05] 운영자 응답 → "답변 내용" (즉시 재생)
```

### After (개선)
```
[11:00] HITL 발동 → "해당 내용은 제가 모르는 내용이라서 별도 확인 해보고 알려드리겠습니다." (20분 timeout 시작)
[11:01] 사용자 다른 질문 → AI 정상 응답 (중간 대화 가능)
[11:05] 운영자 응답 → "아까 문의주신 '[원래 질문]' 내용에 대해 확인되어 알려드리겠습니다. [답변]"
```

---

## Frontend 수정 필요사항

⚠️ **Frontend 수정 필요** (Backend는 준비 완료)

### 필수 수정: HITL 응답 제출 시 original_question 포함

**파일**: `frontend/components/HITLDialog.tsx` (또는 해당 컴포넌트)

**변경 전**:
```typescript
socket.emit('submit_hitl_response', {
  call_id: callId,
  response_text: response,
  save_to_kb: saveToKb,
  category: category
});
```

**변경 후**:
```typescript
socket.emit('submit_hitl_response', {
  call_id: callId,
  response_text: response,
  original_question: hitlRequest.question,  // 추가
  save_to_kb: saveToKb,
  category: category
});
```

### Frontend 상태 관리 확인

HITL 요청 수신 시 `question` 필드를 상태로 저장하여 응답 제출 시 사용:

```typescript
// HITL 요청 수신
socket.on('hitl_requested', (data) => {
  setHitlRequest({
    callId: data.call_id,
    question: data.question,  // 이 값을 저장
    context: data.context,
    urgency: data.urgency
  });
});
```

---

## 테스트 계획

### 1. Timeout 테스트
- [ ] HITL 발동 후 20분 동안 대기 가능 확인
- [ ] 20분 경과 시 timeout 메시지 확인
- [ ] 중간에 다른 대화 가능 여부 확인

### 2. 메시지 통일 테스트
- [ ] transfer intent → "해당 내용은..." 메시지 확인
- [ ] complaint intent → "해당 내용은..." 메시지 확인
- [ ] low_confidence → "해당 내용은..." 메시지 확인

### 3. 문맥 전환 테스트
- [ ] 운영자 응답 시 "아까 문의주신..." 문구 생성 확인
- [ ] 질문이 30자 초과 시 "..." 생략 확인
- [ ] original_question이 없는 경우 fallback 동작 확인

### 4. 통합 시나리오 테스트
```
시나리오 1: 정상 흐름
1. 사용자: "환불은 어떻게 하나요?"
2. AI: "해당 내용은 제가 모르는 내용이라서 별도 확인 해보고 알려드리겠습니다."
3. 사용자: "배송은 얼마나 걸려요?" (중간 대화)
4. AI: "배송은 3-5일 소요됩니다."
5. 운영자 응답: "고객센터로 연락주세요"
6. AI: "아까 문의주신 '환불은 어떻게 하나요?' 내용에 대해 확인되어 알려드리겠습니다. 고객센터로 연락주세요."

시나리오 2: 긴 질문
1. 사용자: "이 제품을 구매했는데 환불하고 싶은데 어떻게 해야 되나요?"
2. AI: "해당 내용은..."
3. 운영자 응답: "..."
4. AI: "아까 문의주신 '이 제품을 구매했는데 환불하고 싶...' 내용에 대해..."

시나리오 3: Timeout
1. 사용자: "이거 뭐에요?"
2. AI: "해당 내용은..."
3. (20분 경과)
4. AI: "죄송합니다. 확인이 지연되고 있습니다. 조금만 더 기다려 주시겠어요?"
```

---

## 로그 키워드 (디버깅용)

구현된 로직 추적을 위한 로그 키워드:

### HITL 발동
- `hitl_alert_processing` - HITL 발동 시점
- `hitl_requested` - WebSocket 이벤트 발송

### 운영자 응답
- `hitl_response_queued` - 응답 큐에 추가
- `hitl_response_with_context` - 문맥 전환 문구 생성
- `hitl_response_received` - RAGProcessor에서 수신

### Timeout
- `hitl_timeout_message_refining` - LLM으로 메시지 다듬기
- `hitl_timeout_emitted` - Frontend에 timeout 알림

---

## 알려진 제약사항

1. **질문 길이 제한**: 30자 초과 시 "..." 생략
   - 개선 가능: LLM으로 질문 요약 생성

2. **여러 HITL 동시 발생**: 큐에 순서대로 쌓임
   - 현재 설계로 문제없으나, 향후 우선순위 추가 가능

3. **통화 종료 시**: 운영자 응답이 통화 종료 후 도착하면 전달 불가
   - 현재 설계상 통화별 격리이므로 정상 동작

---

## 롤백 가이드

각 Phase별로 독립적으로 롤백 가능:

### Phase 1 롤백
```python
# src/services/hitl.py
self._timeout_seconds: float = 20.0
self._timeout_message: Optional[str] = None
```

### Phase 2 롤백
```python
# src/ai_voicebot/pipecat/processors/hitl_processor.py
# 원래대로 intent별 메시지 반환
if intent == "transfer":
    return "담당자에게 연결해 드리겠습니다..."
```

### Phase 3 롤백
- `_build_context_transition()` 호출 제거
- `original_question` 필드 무시

---

## 다음 단계

1. **Frontend 수정** (필수)
   - HITL 응답 제출 시 `original_question` 포함
   - 예상 소요 시간: 10-15분

2. **테스트** (권장)
   - Backend 서버 재시작
   - 실제 통화로 시나리오 1, 2, 3 테스트
   - 예상 소요 시간: 30-60분

3. **모니터링** (권장)
   - 로그에서 위 키워드로 동작 추적
   - 문제 발생 시 즉시 롤백 가능

---

## 요약

✅ **모든 Backend 구현 완료**
- Timeout 20분 확대
- AI 응답 메시지 통일
- 문맥 전환 로직 구현
- WebSocket 데이터 전달 준비

⚠️ **Frontend 수정 필요** (1개 파일, 1개 필드 추가)
- `original_question` 필드만 추가하면 즉시 사용 가능

🎯 **기대 효과**
- 운영자에게 충분한 응답 시간 (20분)
- 자연스러운 대화 흐름 ("아까 문의주신...")
- 중간 대화 가능 (사용자 경험 개선)

---

**작성자**: AI Assistant  
**최종 업데이트**: 2026-03-17
