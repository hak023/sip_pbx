# HITL 지연 응답 설계 (Deferred HITL Response Design)
> **클러스터 안내**: 세부·히스토리 설계 문서입니다. 통합 관점·경계는 아래 대표 문서를 우선 참고하세요.
> 
> **대표 문서**: [`HITL_OPERATOR_RESPONSE_FLOW.md`](HITL_OPERATOR_RESPONSE_FLOW.md)
>
---


**작성일**: 2026-03-17  
**목적**: HITL timeout을 20분으로 늘리고, 운영자 응답 시 자연스러운 문맥 전환 지원  
**기반**: [HITL_CURRENT_LOGIC.md](./HITL_CURRENT_LOGIC.md)

---

## 1. 문제 정의

### 현재 문제점
1. **Timeout이 너무 짧음** (10~20초)
   - 실제 운영자 응답은 수 분이 걸리는 경우가 많음
   - 짧은 timeout으로 인해 "별도 연락 드릴까요?" fallback 메시지가 자주 발생

2. **응답 타이밍 부자연스러움**
   - HITL 요청 직후 timeout이 발생하여 대화 흐름이 끊김
   - 운영자 응답이 도착해도 "아까 그 질문에 대해..." 같은 문맥 전환이 없음

### 요구사항
1. **Timeout 20분으로 확대**
   - 운영자가 충분한 시간을 가지고 확인·응답 가능
   - 단, 사용자는 계속 다른 질문 가능 (대화 차단 없음)

2. **자연스러운 응답 전환**
   - HITL 요청 시: "해당 내용은 제가 모르는 내용이라서 별도 확인 해보고 알려드리겠습니다."
   - 중간에 다른 대화 진행 가능
   - 운영자 응답 도착 시: "아까 문의주신 [원래 질문] 내용에 대해 확인되어 알려드리겠습니다. [운영자 답변]"

---

## 2. 설계 개요

### 2.1 핵심 변경사항

| 항목 | 현재 | 변경 후 |
|------|------|---------|
| **Timeout 시간** | 20초 | 20분 (1200초) |
| **HITL 발동 시 AI 응답** | intent별 고정 문구 | "해당 내용은 제가 모르는 내용이라서 별도 확인 해보고 알려드리겠습니다." (통일) |
| **Timeout 시 동작** | "별도 연락 드릴까요?" | (없음 - 20분이므로 대부분 응답 도착) |
| **운영자 응답 도착 시** | 즉시 TTS 재생 | "아까 문의주신 [질문] 내용에 대해 확인되어 알려드리겠습니다. [답변]" |
| **중간 대화** | 불가능 (HITL 대기 중) | 가능 (다른 질문 계속 처리) |

### 2.2 시스템 흐름

```
[사용자] "이거 어떻게 하나요?"
    ↓
[LangGraph] needs_human=True → "제가 모르는 내용이라 확인해보고 알려드리겠습니다."
    ↓
[WebSocket] emit_hitl_requested (question="이거 어떻게 하나요?")
    ↓
[HITLService] start_fallback_timer(20분)
    ↓
[사용자] "그럼 다른 것도 물어볼게요..." (다른 대화 계속)
    ↓
[Agent] 일반 질문 처리 계속
    ↓
[운영자 대시보드] (5분 후) 응답 작성 완료 → submit_hitl_response
    ↓
[WebSocket] get_response_queue(call_id).put({ "type": "hitl_response", "text": "...", "original_question": "..." })
    ↓
[RAGLLMProcessor] consumer가 큐에서 가져옴
    ↓
[LLM] (선택) 문맥 전환 문구 생성: "아까 문의주신 [질문]에 대해 확인되어 알려드리겠습니다."
    ↓
[TTS] "아까 문의주신 이거 어떻게 하나요에 대해 확인되어 알려드리겠습니다. [운영자 답변]"
```

---

## 3. 상세 설계

### 3.1 Timeout 시간 변경

#### 수정 위치
**파일**: `src/ai_voicebot/pipecat/processors/rag_processor.py`

**변경 전**:
```python
get_hitl_service().start_fallback_timer(self._call_id or "", timeout_sec=20.0)
```

**변경 후**:
```python
# HITL 지연 응답 설계: timeout 20분 (1200초)
get_hitl_service().start_fallback_timer(self._call_id or "", timeout_sec=1200.0)
```

#### HITLService 기본값 변경
**파일**: `src/services/hitl.py`

```python
class HITLService:
    def __init__(self):
        self._default_timeout = 1200.0  # 20분
        self._default_timeout_message = "죄송합니다. 확인이 지연되고 있습니다. 조금만 더 기다려 주시겠어요?"
```

### 3.2 HITL 발동 시 AI 응답 통일

#### 수정 위치
**파일**: `src/ai_voicebot/pipecat/processors/hitl_processor.py`

**변경 전**:
```python
class HITLManager:
    def handle_hitl_result(...):
        if intent == "transfer":
            return "담당자에게 연결해 드리겠습니다. 잠시만 기다려 주세요."
        elif intent == "complaint":
            return "불편을 드려 죄송합니다. 더 정확한 안내를 위해 담당자를 연결해 드릴까요?"
        else:
            return "확인해보겠습니다. 잠시만 기다려 주세요."
```

**변경 후**:
```python
class HITLManager:
    # HITL 지연 응답 설계: 모든 케이스에 통일된 응답
    HITL_REQUEST_MESSAGE = "해당 내용은 제가 모르는 내용이라서 별도 확인 해보고 알려드리겠습니다."
    
    def handle_hitl_result(...):
        # intent 무관하게 통일된 메시지 반환
        return self.HITL_REQUEST_MESSAGE
```

### 3.3 운영자 응답 시 문맥 전환 문구 생성

#### 수정 위치
**파일**: `src/ai_voicebot/pipecat/processors/rag_processor.py`

**현재 로직**:
```python
async def _start_hitl_response_consumer(self):
    while True:
        msg = await self._hitl_response_queue.get()
        if msg["type"] == "hitl_response":
            response_text = msg["text"]
            # 즉시 TTS 재생
            await self.push_frame(TextFrame(response_text))
```

**변경 후**:
```python
async def _start_hitl_response_consumer(self):
    while True:
        msg = await self._hitl_response_queue.get()
        if msg["type"] == "hitl_response":
            operator_response = msg["text"]
            original_question = msg.get("original_question", "")
            
            # 문맥 전환 문구 생성
            if original_question:
                context_intro = self._build_context_transition(original_question, operator_response)
            else:
                context_intro = operator_response
            
            # TTS 재생
            await self.push_frame(LLMFullResponseStartFrame())
            await self.push_frame(TextFrame(context_intro))
            await self.push_frame(LLMFullResponseEndFrame())
```

**새 메서드 추가**:
```python
def _build_context_transition(self, original_question: str, operator_response: str) -> str:
    """운영자 응답 시 문맥 전환 문구 생성
    
    Args:
        original_question: 사용자의 원래 질문
        operator_response: 운영자가 작성한 답변
        
    Returns:
        "아까 문의주신 [질문]에 대해 확인되어 알려드리겠습니다. [답변]" 형식의 문자열
    """
    # 질문 요약 (너무 길면 앞부분만)
    question_summary = original_question[:30] + "..." if len(original_question) > 30 else original_question
    
    # 문맥 전환 문구 템플릿
    transition = f"아까 문의주신 '{question_summary}' 내용에 대해 확인되어 알려드리겠습니다. {operator_response}"
    
    return transition
```

### 3.4 WebSocket submit_hitl_response 수정

#### 수정 위치
**파일**: `src/websocket/server.py`

**변경 전**:
```python
@sio.on("submit_hitl_response")
async def handle_hitl_response(sid, data):
    call_id = data.get("call_id")
    response_text = data.get("response_text")
    
    # 큐에 넣기
    queue = get_hitl_service().get_response_queue(call_id)
    await queue.put({
        "type": "hitl_response",
        "text": response_text,
    })
```

**변경 후**:
```python
@sio.on("submit_hitl_response")
async def handle_hitl_response(sid, data):
    call_id = data.get("call_id")
    response_text = data.get("response_text")
    original_question = data.get("question", "")  # Frontend에서 원래 질문도 함께 전송
    
    # 큐에 넣기 (원래 질문 포함)
    queue = get_hitl_service().get_response_queue(call_id)
    await queue.put({
        "type": "hitl_response",
        "text": response_text,
        "original_question": original_question,  # 추가
    })
```

### 3.5 HITLService.get_response_queue 메서드 추가

#### 수정 위치
**파일**: `src/services/hitl.py`

**현재 상태**: 메서드 없음 (알려진 갭)

**추가 필요**:
```python
class HITLService:
    def get_response_queue(self, call_id: str) -> Optional[asyncio.Queue]:
        """통화별 응답 큐 반환
        
        Args:
            call_id: 통화 ID
            
        Returns:
            해당 통화의 응답 큐 (없으면 None)
        """
        return self._queues.get(call_id)
```

---

## 4. 데이터 구조 변경

### 4.1 HITL Request 메타데이터

**WebSocket emit_hitl_requested 페이로드**:
```json
{
  "call_id": "call_123",
  "question": "이거 어떻게 하나요?",
  "context": {
    "intent": "question",
    "confidence": 0.25,
    "reason": "답변 신뢰도가 매우 낮습니다",
    "alert_type": "low_confidence",
    "timestamp": "2026-03-17T11:30:00Z"
  },
  "urgency": "low_confidence"
}
```

### 4.2 HITL Response 큐 메시지

**현재**:
```python
{
    "type": "hitl_response",
    "text": "운영자 답변"
}
```

**변경 후**:
```python
{
    "type": "hitl_response",
    "text": "운영자 답변",
    "original_question": "이거 어떻게 하나요?",  # 추가
    "responded_at": "2026-03-17T11:35:00Z"
}
```

### 4.3 Frontend 수정 필요사항

**HITL 응답 제출 시**:
```typescript
// Before
socket.emit('submit_hitl_response', {
  call_id: callId,
  response_text: response,
  save_to_kb: saveToKb,
  category: category
});

// After
socket.emit('submit_hitl_response', {
  call_id: callId,
  response_text: response,
  original_question: originalQuestion,  // 추가: HITL 요청 시 받은 질문
  save_to_kb: saveToKb,
  category: category
});
```

---

## 5. 구현 순서

### Phase 1: Timeout 확대 (가장 간단, 즉시 적용 가능)
1. [ ] `rag_processor.py`: `timeout_sec=1200.0`으로 변경
2. [ ] `hitl.py`: 기본값 `_default_timeout = 1200.0`으로 변경
3. [ ] 테스트: HITL 발동 후 20분 동안 대기 가능 확인

### Phase 2: AI 응답 메시지 통일
1. [ ] `hitl_processor.py`: `HITLManager.HITL_REQUEST_MESSAGE` 상수 추가
2. [ ] `handle_hitl_result()`: intent 무관하게 통일된 메시지 반환
3. [ ] 테스트: transfer, complaint, low_confidence 모두 동일 메시지 확인

### Phase 3: 문맥 전환 문구 생성
1. [ ] `hitl.py`: `get_response_queue()` 메서드 추가
2. [ ] `rag_processor.py`: `_build_context_transition()` 메서드 추가
3. [ ] `_start_hitl_response_consumer()`: 문맥 전환 로직 추가
4. [ ] `websocket/server.py`: `original_question` 필드 추가
5. [ ] Frontend: HITL 응답 제출 시 `original_question` 포함
6. [ ] 테스트: "아까 문의주신..." 문구 생성 확인

---

## 6. 예상 동작 시나리오

### 시나리오 1: 정상 케이스 (5분 내 응답)

```
[11:00] 사용자: "환불은 어떻게 하나요?"
[11:00] AI: "해당 내용은 제가 모르는 내용이라서 별도 확인 해보고 알려드리겠습니다."
[11:00] → WebSocket: hitl_requested (question="환불은 어떻게 하나요?")
[11:01] 사용자: "그럼 배송은 얼마나 걸려요?"
[11:01] AI: "배송은 보통 3-5일 정도 소요됩니다." (일반 응답)
[11:05] 운영자: 응답 작성 완료 → submit_hitl_response
[11:05] AI: "아까 문의주신 '환불은 어떻게 하나요?' 내용에 대해 확인되어 알려드리겠습니다. 
         환불은 고객센터(1588-1234)로 연락주시면 처리해드립니다."
```

### 시나리오 2: 지연 응답 (15분 후)

```
[11:00] 사용자: "이 상품 재고 있나요?"
[11:00] AI: "해당 내용은 제가 모르는 내용이라서 별도 확인 해보고 알려드리겠습니다."
[11:02] 사용자: "배송 추적은 어디서 하나요?"
[11:02] AI: "배송 추적은 홈페이지 > 마이페이지에서 하실 수 있습니다."
[11:05] 사용자: "감사합니다."
[11:05] AI: "도움이 되셨다니 다행입니다."
[11:15] 운영자: 응답 작성 완료 → submit_hitl_response
[11:15] AI: "아까 문의주신 '이 상품 재고 있나요?' 내용에 대해 확인되어 알려드리겠습니다.
         현재 재고가 10개 남아있습니다."
```

### 시나리오 3: Timeout 발생 (20분 초과, 드물게)

```
[11:00] 사용자: "특수 주문 가능한가요?"
[11:00] AI: "해당 내용은 제가 모르는 내용이라서 별도 확인 해보고 알려드리겠습니다."
[11:20] → Timeout 발생
[11:20] AI: "죄송합니다. 확인이 지연되고 있습니다. 조금만 더 기다려 주시겠어요?"
         (또는 Frontend에 timeout 알림)
```

---

## 7. 고려사항 및 제약

### 7.1 중간 대화 처리
- ✅ **장점**: 사용자가 HITL 대기 중에도 다른 질문 가능 → 대화 흐름 자연스러움
- ⚠️ **주의**: 여러 HITL 요청이 동시에 발생할 수 있음
  - 각 HITL은 `original_question`으로 구분
  - 큐에 여러 `hitl_response` 메시지가 쌓일 수 있음
  - Consumer는 순서대로 처리

### 7.2 문맥 전환 문구 품질
- 현재 설계: 단순 템플릿 (`"아까 문의주신 '{question}'에 대해..."`)
- **개선 옵션** (선택):
  1. LLM으로 더 자연스러운 문구 생성
  2. 경과 시간에 따라 문구 조정 ("조금 전", "아까", "이전에")
  3. 사용자가 중간에 다른 대화를 많이 한 경우 더 명확한 문맥 제시

### 7.3 Timeout 메시지
- 20분은 매우 긴 시간이므로 timeout은 거의 발생하지 않을 것으로 예상
- 만약 발생 시: Frontend에 별도 알림 + 사용자에게 "조금만 더 기다려주세요" 재생
- **추후 개선**: timeout 시 "별도로 연락 드릴까요?" 워크플로 추가 가능

### 7.4 통화 종료 시 처리
- 사용자가 HITL 응답 도착 전에 통화 종료하는 경우
  - ✅ `HITLService.unregister_call()`에서 타이머·큐 정리
  - ✅ Frontend에서 `hitl_resolved` 또는 별도 상태 업데이트 필요
  - ⚠️ 운영자 응답이 늦게 도착하면 다음 통화에서 전달할 수 없음 (통화별 격리)

---

## 8. 테스트 계획

### 8.1 단위 테스트
- [ ] `HITLManager`: 통일된 메시지 반환 확인
- [ ] `_build_context_transition()`: 다양한 질문 길이에 대한 문구 생성
- [ ] `HITLService.get_response_queue()`: 큐 반환 로직

### 8.2 통합 테스트
- [ ] HITL 발동 → 20분 timeout 설정 확인
- [ ] 중간에 다른 대화 → 일반 응답 정상 동작
- [ ] 운영자 응답 도착 → 문맥 전환 문구 + 답변 TTS 재생
- [ ] 여러 HITL 동시 발생 → 각각 독립적으로 처리

### 8.3 시나리오 테스트
- [ ] 시나리오 1: 5분 내 응답
- [ ] 시나리오 2: 15분 후 응답 (중간 대화 포함)
- [ ] 시나리오 3: 20분 timeout 발생
- [ ] 시나리오 4: 통화 종료 후 운영자 응답 도착

---

## 9. 롤백 계획

만약 문제가 발생하면 단계별 롤백 가능:

### Phase 1 롤백
- `timeout_sec=20.0`으로 복구

### Phase 2 롤백
- `handle_hitl_result()`에서 intent별 메시지로 복구

### Phase 3 롤백
- `_build_context_transition()` 호출 제거
- `original_question` 필드 무시

---

## 10. 요약

| 구분 | 내용 |
|------|------|
| **목표** | HITL timeout 20분 확대, 운영자 응답 시 자연스러운 문맥 전환 |
| **핵심 변경** | 1) timeout 1200초, 2) AI 응답 통일, 3) 문맥 전환 문구 자동 생성 |
| **장점** | 운영자에게 충분한 시간, 사용자는 중간에 다른 대화 가능, 자연스러운 응답 |
| **구현 난이도** | Phase 1(쉬움), Phase 2(쉬움), Phase 3(중간) |
| **리스크** | 낮음 (단계별 롤백 가능, 기존 로직 유지) |

---

**작성자**: AI Assistant  
**검토 필요**: 사용자 확인 후 구현 시작
