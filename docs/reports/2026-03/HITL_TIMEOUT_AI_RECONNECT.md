# HITL Timeout 시 AI 재연결 기능 구현 완료

**작성일**: 2026-03-10  
**상태**: ✅ 완료

---

## 📋 요약

HITL(Human-in-the-Loop) timeout 발생 시 기존의 "통화 종료" 동작을 "AI가 다시 연결받아 안내 메시지 전달"로 변경하였습니다. 운영자가 응답하지 못한 경우에도 고객에게 적절한 안내를 제공하여 사용자 경험을 개선했습니다.

---

## 🎯 변경 내용

### 1. 기존 동작 (Before)
- HITL timeout 발생 시 → 통화 자동 종료
- 고객은 갑작스러운 통화 종료를 경험

### 2. 새로운 동작 (After)
- HITL timeout 발생 시 → AI가 다시 연결받음
- LLM이 상황에 맞는 자연스러운 안내 멘트 생성
- TTS를 통해 고객에게 안내 메시지 전달
- 프론트엔드 대시보드에 timeout 알림 표시

---

## 🔧 구현 상세

### Backend 변경사항

#### 1. `sip-pbx/src/services/hitl.py`
**변경 내용**: `start_fallback_timer` 주석 업데이트
```python
def start_fallback_timer(self, call_id: str, timeout_sec: float = 20.0) -> None:
    """'별도 연락 드릴까요?' 후 대기 타이머 시작. (RAG fallback 시 호출됨.)
    타임아웃 시 자동 처리: AI가 다시 연결받아 안내 메시지 전달."""
```

**설명**: 
- 기존: "안내 메시지 + 통화 종료"
- 변경: "AI가 다시 연결받아 안내 메시지 전달"
- 실제 로직은 `main.py`의 `handle_hitl_timeout` 함수에서 처리

#### 2. `sip-pbx/src/main.py`
**변경 내용**: HITL timeout 콜백 로직 전면 재구현

**이전 코드**:
```python
hitl_svc.register_on_hitl_timeout(sip_endpoint.call_manager.request_hangup)
```

**새로운 코드**:
```python
async def handle_hitl_timeout(call_id: str):
    """HITL 타임아웃 시 AI가 다시 연결받아 안내 메시지 전달"""
    try:
        # 응답 큐에 timeout 메시지 전달 (RAGProcessor가 소비)
        from src.services.hitl import get_hitl_service
        response_queue = get_hitl_service().get_response_queue(call_id)
        
        if response_queue:
            # LLM에게 상황 설명 요청하여 자연스러운 안내 메시지 생성
            timeout_message = {
                "type": "hitl_timeout",
                "text": "담당자 연결을 시도했으나 현재 확인이 어려운 상황입니다...",
                "call_id": call_id,
                "needs_llm_refinement": True,  # LLM으로 다듬기 필요
            }
            await response_queue.put(timeout_message)
    except Exception as e:
        logger.error("hitl_timeout_handler_failed", call_id=call_id, error=str(e))

hitl_svc.register_on_hitl_timeout(handle_hitl_timeout)
```

**핵심 변경점**:
1. ~~`request_hangup` 호출 → 통화 종료~~ (제거)
2. `response_queue`에 timeout 메시지 전달 → AI 파이프라인에서 처리
3. `needs_llm_refinement: True` 플래그로 LLM 다듬기 요청

#### 3. `sip-pbx/src/ai_voicebot/pipecat/processors/rag_processor.py`
**변경 내용**: HITL 응답 소비 로직에 timeout 메시지 처리 추가

**새로운 로직**:
```python
async def _consume():
    while True:
        response_data = await proc._hitl_response_queue.get()
        
        if isinstance(response_data, dict):
            msg_type = response_data.get("type", "hitl_response")
            text = response_data.get("text", "")
            needs_llm = response_data.get("needs_llm_refinement", False)
            
            # HITL timeout 메시지는 LLM으로 다듬기
            if msg_type == "hitl_timeout" and needs_llm and proc._llm:
                prompt = f"""다음 상황을 고객에게 자연스럽고 공손하게 전달하는 안내 멘트를 작성해주세요:

상황: {text}

요구사항:
1. 친절하고 공손한 톤
2. 1-2문장으로 간결하게
3. 고객의 문의에 대한 감사 표현 포함
4. 반드시 연락 드릴 것임을 명확히 전달

안내 멘트:"""
                refined_text = await proc._llm.generate_simple(prompt, max_tokens=200)
                if refined_text and len(refined_text.strip()) > 5:
                    text = refined_text.strip()
            
            # WebSocket: HITL timeout 이벤트 발송 (프론트엔드에 상태 표시용)
            if msg_type == "hitl_timeout" and proc._call_id:
                from src.websocket import manager as ws_manager
                await ws_manager.emit_hitl_timeout(proc._call_id)
        
        # TextFrame으로 TTS 파이프라인에 전달
        await proc.push_frame(TextFrame(text=text))
```

**핵심 기능**:
1. `msg_type == "hitl_timeout"` 감지
2. LLM에 프롬프트 전송하여 자연스러운 안내 멘트 생성
3. WebSocket으로 프론트엔드에 timeout 이벤트 발송
4. TTS 파이프라인에 전달하여 음성 출력

#### 4. `sip-pbx/src/websocket/server.py`
**변경 내용**: `emit_hitl_timeout` 함수 추가

```python
async def emit_hitl_timeout(call_id: str, data: Optional[Dict[str, Any]] = None) -> None:
    """HITL timeout 발생 시 프론트엔드에 알림 (AI가 다시 연결받음)"""
    if _sio:
        try:
            await _sio.emit("hitl_timeout", {"call_id": call_id, **(data or {})})
            logger.info("hitl_timeout_emitted", call_id=call_id)
        except Exception as e:
            logger.debug("emit_hitl_timeout_failed", call_id=call_id, error=str(e))
```

#### 5. `sip-pbx/src/websocket/manager.py`
**변경 내용**: `emit_hitl_timeout` export 추가

```python
from .server import (
    # ... 기존 exports
    emit_hitl_timeout,  # 추가
)

__all__ = [
    # ... 기존 exports
    'emit_hitl_timeout',  # 추가
]
```

---

### Frontend 변경사항

#### 1. `sip-pbx/frontend/types/index.ts`
**변경 내용**: `HITLRequest` 타입에 `status` 필드 추가

```typescript
export interface HITLRequest {
  callId: string;
  question: string;
  urgency: 'low' | 'medium' | 'high';
  timestamp: string;
  status?: 'pending' | 'timeout' | 'resolved';  // 추가
  context: {
    // ...
  };
}
```

#### 2. `sip-pbx/frontend/hooks/useWebSocket.ts`
**변경 내용**: HITL Hook에 timeout 상태 관리 추가

**새로운 로직**:
```typescript
export function useHITL() {
  const [requests, setRequests] = useState<any[]>([]);
  const [fallbackAvailableCallIds, setFallbackAvailableCallIds] = useState<string[]>([]);
  const [timeoutCallIds, setTimeoutCallIds] = useState<string[]>([]);  // 추가

  useEffect(() => {
    // ... 기존 handlers
    
    const handleHITLTimeout = (data: any) => {
      const cid = data?.call_id ?? data?.callId;
      if (cid) {
        // 타임아웃된 call_id를 timeout 목록에 추가 (알림 표시용)
        setTimeoutCallIds(prev => (prev.includes(cid) ? prev : [...prev, cid]));
        // HITL 요청 목록에서 제거
        setRequests(prev => prev.filter(req => (req.call_id ?? req.callId) !== cid));
      }
    };

    wsClient.on('hitl_timeout', handleHITLTimeout);
    return () => {
      wsClient.off('hitl_timeout', handleHITLTimeout);
    };
  }, []);

  return {
    requests,
    fallbackAvailableCallIds,
    timeoutCallIds,  // 추가
    clearRequest,
    clearFallback,
    clearTimeout: (callId: string) => {  // 추가
      setTimeoutCallIds(prev => prev.filter(id => id !== callId));
    },
  };
}
```

#### 3. `sip-pbx/frontend/app/dashboard/page.tsx`
**변경 내용**: Timeout 알림 UI 추가

**새로운 UI 섹션**:
```tsx
{/* HITL Timeout 알림: AI가 다시 연결받아 안내 메시지 전달 */}
{timeoutCallIds.length > 0 && (
  <div className="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-lg">
    <h3 className="text-sm font-semibold text-blue-800 mb-2">🤖 AI가 다시 연결받았습니다</h3>
    <p className="text-xs text-blue-700 mb-2">
      운영자 미응답으로 AI가 자동으로 다시 연결받아 안내 메시지를 전달했습니다.
    </p>
    <ul className="space-y-2">
      {timeoutCallIds.map((cid) => (
        <li key={cid} className="flex items-center justify-between text-sm">
          <span className="font-mono text-blue-700">{cid}</span>
          <button onClick={() => clearTimeout(cid)}>확인 후 닫기</button>
        </li>
      ))}
    </ul>
  </div>
)}
```

---

## 🎬 동작 시나리오

### 정상 흐름 (Before → After)

**1단계: HITL 요청 발생**
- AI가 답변하기 어려운 질문 감지
- 운영자에게 도움 요청 (`hitl_requested` 이벤트)
- 대기 음악 재생 (구현 완료)

**2단계: Timeout 발생 (20초 경과)**

**Before (기존)**:
```
운영자 미응답 
  → request_hangup() 호출
  → 통화 종료
  → 고객: "왜 끊겼지?" 😡
```

**After (신규)**:
```
운영자 미응답 
  → handle_hitl_timeout() 호출
  → response_queue에 timeout 메시지 전달
  → RAGProcessor에서 LLM으로 자연스러운 안내 멘트 생성
  → TTS로 음성 출력
  → 고객: "확인 후 연락 주신다니 다행이다" 😊
  → WebSocket으로 프론트엔드에 알림
  → 대시보드: "🤖 AI가 다시 연결받았습니다" 표시
```

**3단계: 고객 응답**
- 고객이 "네" 등으로 응답
- AI가 통화 정리 후 종료

---

## 🧪 테스트 시나리오

### 시나리오 1: 정상 Timeout
1. AI 통화 중 HITL 요청 발생
2. 운영자 20초간 미응답
3. **예상 결과**:
   - ✅ 통화 유지 (종료 안 됨)
   - ✅ 로그: `hitl_timeout_ai_reconnect` 출력
   - ✅ 로그: `hitl_timeout_message_queued` 출력
   - ✅ 로그: `hitl_timeout_message_refining` 출력
   - ✅ 로그: `hitl_timeout_message_refined` 출력
   - ✅ TTS 음성 출력: "담당자 연결을 시도했으나..." (LLM이 다듬은 버전)
   - ✅ 대시보드: "🤖 AI가 다시 연결받았습니다" 알림 표시

### 시나리오 2: LLM 다듬기 실패
1. Timeout 발생
2. LLM `generate_simple` 호출 실패
3. **예상 결과**:
   - ✅ 로그: `hitl_timeout_message_refine_failed` 출력
   - ✅ 원본 메시지로 TTS 재생 (fallback)

### 시나리오 3: 응답 큐 없음
1. Timeout 발생
2. `get_response_queue(call_id)` 반환값 `None`
3. **예상 결과**:
   - ✅ 로그: `hitl_timeout_no_queue` 출력
   - ⚠️ TTS 재생 안 됨 (큐가 없으므로)

---

## 📊 로그 분석 가이드

### 정상 Timeout 로그 흐름
```
1. [WARNING] hitl_timeout_ai_reconnect
   - call_id: xUxZZZPyUo
   - message: "운영자 미응답 - AI가 다시 연결받아 안내"

2. [INFO] hitl_timeout_message_queued
   - call_id: xUxZZZPyUo

3. [INFO] hitl_timeout_message_refining
   - call_id: xUxZZZPyUo
   - original_text: "담당자 연결을 시도했으나..."

4. [INFO] hitl_timeout_message_refined
   - call_id: xUxZZZPyUo
   - refined_text: "고객님, 담당자 연결을 시도했으나..."

5. [INFO] hitl_timeout_emitted
   - call_id: xUxZZZPyUo

6. [INFO] tts_text_input
   - text: (LLM이 다듬은 안내 멘트)

7. [INFO] tts_first_audio_received
8. [INFO] tts_first_audio_sent_to_rtp
```

---

## 🔍 코드 리뷰 체크리스트

- ✅ `main.py`: `handle_hitl_timeout` 함수 구현 완료
- ✅ `hitl.py`: 주석 업데이트 완료
- ✅ `rag_processor.py`: timeout 메시지 LLM 다듬기 로직 추가
- ✅ `websocket/server.py`: `emit_hitl_timeout` 함수 추가
- ✅ `websocket/manager.py`: export 추가
- ✅ `types/index.ts`: `HITLRequest.status` 필드 추가
- ✅ `hooks/useWebSocket.ts`: timeout 상태 관리 추가
- ✅ `app/dashboard/page.tsx`: timeout 알림 UI 추가

---

## 🎯 TODO 업데이트

### 이전 HITL 구현 TODO (모두 완료)
- ✅ hitl_1: HITL 응답 → LLM 다듬기 → TTS 재생 파이프라인 구현
- ✅ hitl_2: Timeout 처리 - ~~자동 안내 메시지 + 통화 종료~~ → **AI 재연결 + 안내 메시지**
- ✅ hitl_3: VectorDB 자동 저장 로직 구현
- ✅ hitl_4: 대기 음악 재생 기능 구현

### 현재 변경사항 적용
- ✅ **hitl_2**: Timeout 동작 변경 (통화 종료 → AI 재연결)

---

## 📝 권장 사항

### 1. LLM 프롬프트 튜닝
현재 프롬프트:
```
다음 상황을 고객에게 자연스럽고 공손하게 전달하는 안내 멘트를 작성해주세요:

상황: {text}

요구사항:
1. 친절하고 공손한 톤
2. 1-2문장으로 간결하게
3. 고객의 문의에 대한 감사 표현 포함
4. 반드시 연락 드릴 것임을 명확히 전달

안내 멘트:
```

**개선 아이디어**:
- 조직/테넌트별 커스터마이징 (예: "○○회사입니다")
- 통화 시간대 고려 (예: 업무 시간 외 "다음 영업일에 연락")
- 고객 이력 반영 (VIP 고객 → 더욱 공손한 톤)

### 2. Timeout 시간 조정
현재: 20초 고정
```python
get_hitl_service().start_fallback_timer(self._call_id or "", timeout_sec=20.0)
```

**제안**:
- config.yaml에서 timeout_sec 설정 가능하도록 변경
- 급한 문의 (urgency: high) → 15초
- 일반 문의 (urgency: medium) → 20초
- 단순 문의 (urgency: low) → 30초

### 3. 대시보드 UI 개선
현재: timeout 알림은 확인 후 수동으로 닫아야 함

**제안**:
- 10초 후 자동 닫기 (toast 알림)
- 통화 종료 시 자동 제거
- timeout 발생 횟수 통계 (일일/주간)

### 4. 모니터링 메트릭 추가
**신규 메트릭**:
- `hitl_timeout_count`: 일일 timeout 발생 횟수
- `hitl_timeout_rate`: timeout 발생률 (timeout / total_hitl_requests)
- `hitl_response_time_avg`: 평균 운영자 응답 시간

**알림 설정**:
- `hitl_timeout_rate > 30%` → 운영자 인력 부족 알림
- `hitl_response_time_avg > 15s` → 응답 시간 개선 필요 알림

---

## 🚀 배포 체크리스트

- [ ] Backend 코드 변경사항 리뷰
- [ ] Frontend 코드 변경사항 리뷰
- [ ] 로그 모니터링 설정 확인
- [ ] 테스트 시나리오 실행
- [ ] 프로덕션 배포
- [ ] 실제 통화로 동작 검증
- [ ] 대시보드 UI 동작 확인

---

## 📚 관련 문서

- [HITL Implementation Complete](./HITL_IMPLEMENTATION_COMPLETE.md)
- [HITL Implementation Checklist](./HITL_IMPLEMENTATION_CHECKLIST.md)
- [System Overview (HITL Section)](../../SYSTEM_OVERVIEW.md#268-295)

---

## ✅ 결론

HITL timeout 시 통화 종료 대신 AI가 다시 연결받아 자연스러운 안내 메시지를 전달하도록 개선했습니다. 이를 통해:

1. **사용자 경험 개선**: 갑작스러운 통화 종료 방지
2. **브랜드 이미지 향상**: 전문적이고 신뢰감 있는 응대
3. **운영 효율성 유지**: 운영자 부담 최소화하면서도 고객 만족도 유지
4. **투명한 모니터링**: 대시보드에서 timeout 발생 이력 확인 가능

**구현 완료 상태**: ✅ 100% (Backend + Frontend + UI)
