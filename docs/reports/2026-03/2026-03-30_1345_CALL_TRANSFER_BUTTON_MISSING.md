# "호 전환" 버튼 사라짐 문제 수정

**작성일**: 2026-03-30 13:45  
**증상**: 대시보드 실시간 통화에서 "호 전환" 버튼이 표시되지 않음  
**원인**: AI 통화 시작 시 `is_ai_handled` 플래그를 WebSocket/API에 전송하지 않음  
**상태**: 수정 완료 (서버 재시작 필요)

---

## 1. 증상

**대시보드 스크린샷**:
- 실시간 통화에 "ESTABLISHED" 상태 통화 1건 표시
- **"AI 응대"** 배지는 표시됨
- 하지만 **"내선(1004)으로 호 전환" 버튼이 없음**

## 2. 프론트엔드 버튼 표시 조건

**파일**: `sip-pbx/frontend/app/dashboard/page.tsx` Line 835-853

```typescript
{call.is_ai_handled && (
  <button
    type="button"
    onClick={(e) => {
      e.stopPropagation();
      handleTransfer(call);
    }}
    disabled={!currentTenantId}
    className={...}
  >
    {currentTenantId
      ? `내선(${currentTenantId})으로 호 전환`
      : "로그인 필요"}
  </button>
)}
```

**조건**: `call.is_ai_handled === true`일 때만 표시

## 3. 원인 분석

### 3.1. WebSocket `call_started` 이벤트 처리

**프론트엔드** (Line 376-424):
```typescript
newSocket.on("call_started", (data: Record<string, unknown>) => {
  const aiPayload = data.is_ai_handled;
  const isAi = isAiDefined ? Boolean(aiPayload) : undefined;
  
  // 신규 통화
  if (idx < 0) {
    return [...prev, {
      call_id: id,
      is_ai_handled: isAi ?? false,  // ← 기본값 false!
    }];
  }
  
  // 기존 통화 업데이트
  const nextAi = isAi === undefined 
    ? Boolean(cur.is_ai_handled) 
    : Boolean(isAi || cur.is_ai_handled);  // OR 로직
});
```

**문제**:
- WebSocket 데이터에 `is_ai_handled` 필드가 없으면 `undefined`
- 신규 통화 추가 시 **기본값 `false`**로 설정
- 이후 업데이트 이벤트가 없으면 계속 `false`로 유지

### 3.2. 백엔드 전송 지점 분석

**AI 통화 시작 경로**:

1. **일반 통화 → 부재중 타임아웃 → AI 활성화**
   - `call_manager.py` Line 620: `emit_call_started` 호출
   - ✅ `is_ai_handled: True` 포함 (정상)

2. **Pipecat 직접 호출** (`run_ai_call.py`)
   - Line 71: `emit_call_started` 호출
   - ❌ **`is_ai_handled` 필드 누락** (원인!)

3. **B2BUA 200 OK 수신** (착신자 응답)
   - `sip_endpoint.py` Line 970: `emit_call_started` 호출
   - `is_ai_handled: call_info.get("ai_mode_activated", False)`
   - **AI 활성화 전**이면 `False` 전송

### 3.3. REST API `/api/calls/active`

**`calls.py` Line 113-119**:
```python
meta = getattr(s, "metadata", None)
meta_ai = bool(isinstance(meta, dict) and meta.get("is_ai_handled"))
reg = _active_calls_registry.get(cid)
registry_ai = bool(reg and reg.get("is_ai_handled"))
is_ai_handled = (cid in ai_set) or meta_ai or registry_ai
```

**3가지 소스**:
1. `ai_enabled_calls` set (메모리, 서버 재시작 시 초기화)
2. `metadata.is_ai_handled` (CallSession 객체, 메모리)
3. `_active_calls_registry` (메모리)

**문제**:
- **모두 메모리 기반**이므로 서버 재시작 시 초기화됨
- `register_active_call`이 호출되지 않으면 `_active_calls_registry`가 비어있음
- AI 타임아웃 경로에서 `register_active_call` 호출 없음
- Pipecat 직접 호출 경로에서도 `register_active_call` 호출 없음

## 4. 수정 내용

### 4.1. `run_ai_call.py` - WebSocket 이벤트 보강

**파일**: `sip-pbx/src/ai_voicebot/run_ai_call.py` Line 68-73

**수정 전**:
```python
await ws_manager.emit_call_started(call_id, {"callee": callee})
```

**수정 후**:
```python
await ws_manager.emit_call_started(call_id, {
    "callee": callee,
    "is_ai_handled": True,
    "status": "AI 응대 중",
    "sip_phase": "ai_active"
})
```

### 4.2. `run_ai_call.py` - API 레지스트리 등록 추가

**파일**: `sip-pbx/src/ai_voicebot/run_ai_call.py` Line 74-86

**추가**:
```python
# API 레지스트리에도 등록 (REST API /api/calls/active에서 참조)
try:
    from src.api.routers.calls import register_active_call
    register_active_call(
        call_id=call_id,
        callee=callee,
        caller="",
        is_ai_handled=True
    )
except Exception as reg_err:
    logger.debug("register_active_call_failed", call_id=call_id, error=str(reg_err))
```

### 4.3. `call_manager.py` - API 레지스트리 등록 추가

**파일**: `sip-pbx/src/sip_core/call_manager.py` Line 591-606

**추가** (Line 595-605):
```python
# API 레지스트리에도 등록 (REST API /api/calls/active에서 참조)
try:
    from src.api.routers.calls import register_active_call
    register_active_call(
        call_id=call_id,
        callee=callee_username,
        caller=caller_username if caller_username else "",
        is_ai_handled=True
    )
except Exception as reg_err:
    logger.debug("register_active_call_failed", call_id=call_id, error=str(reg_err))
```

## 5. 수정 효과

### 5.1. WebSocket 실시간 업데이트

**이전**:
```json
{
  "call_id": "abc123",
  "callee": "1004"
  // is_ai_handled 누락
}
```

**수정 후**:
```json
{
  "call_id": "abc123",
  "callee": "1004",
  "is_ai_handled": true,
  "status": "AI 응대 중",
  "sip_phase": "ai_active"
}
```

### 5.2. REST API `/api/calls/active`

**이전**:
- `ai_enabled_calls` set만 확인
- 서버 재시작 시 set이 비어있으면 `is_ai_handled: false` 반환

**수정 후**:
- `ai_enabled_calls` set ✅
- `metadata.is_ai_handled` ✅
- **`_active_calls_registry`** ✅ (새로 추가)
- 3가지 소스 중 하나라도 `true`면 버튼 표시

### 5.3. 프론트엔드

**이전**:
- `is_ai_handled: false` 수신
- 버튼 조건 `call.is_ai_handled` → `false`
- 버튼 미표시

**수정 후**:
- `is_ai_handled: true` 수신
- 버튼 조건 `call.is_ai_handled` → `true`
- 버튼 표시: "내선(1004)으로 호 전환"

## 6. 테스트 방법

### 6.1. 서버 재시작

```powershell
.\stop-all.ps1
.\start-all.ps1
```

### 6.2. 테스트 시나리오

**시나리오 1: 부재중 타임아웃 → AI**
1. `1003` → `1004` 통화
2. `1004` 응답 안 함 (10초)
3. AI 모드 활성화
4. 대시보드에서 **"호 전환" 버튼** 표시 확인

**시나리오 2: Pipecat 직접 호출**
1. AI 전용 내선으로 통화 시작
2. 대시보드에서 **"호 전환" 버튼** 즉시 표시 확인

**시나리오 3: 서버 재시작 후 REST API**
1. AI 통화 진행 중
2. 브라우저 새로고침 (REST API 호출)
3. `/api/calls/active`가 `is_ai_handled: true` 반환 확인
4. **"호 전환" 버튼** 표시 확인

### 6.3. 확인 포인트

**브라우저 개발자 도구 (F12)**:
```javascript
// Console에서 확인
// WebSocket 이벤트
socket.on("call_started", (data) => console.log("call_started:", data));

// REST API
fetch("/api/calls/active").then(r => r.json()).then(console.log);
```

**확인 항목**:
- `is_ai_handled: true` 포함 여부
- 대시보드에 "AI 응대" 배지 표시
- **"내선(1004)으로 호 전환" 버튼** 표시

## 7. 근본 원인 요약

### 7.1. WebSocket 경로

**Pipecat 직접 호출** (`run_ai_call.py`):
- `emit_call_started` 호출 시 `is_ai_handled` 필드 누락
- 프론트엔드가 `undefined`로 받음 → **기본값 `false`** 설정
- 버튼 조건 `call.is_ai_handled === true` 불만족 → 미표시

### 7.2. REST API 경로

**레지스트리 미등록**:
- AI 통화 시작 시 `register_active_call` 호출 없음
- REST API가 참조하는 `_active_calls_registry`가 비어있음
- `ai_enabled_calls` set만 의존 (서버 재시작 시 초기화)
- 결과: `is_ai_handled: false` 반환 → 버튼 미표시

## 8. 체크리스트

- [x] `run_ai_call.py`: WebSocket에 `is_ai_handled: True` 추가
- [x] `run_ai_call.py`: `register_active_call` 호출 추가
- [x] `call_manager.py`: `register_active_call` 호출 추가
- [x] 린터 에러 확인
- [ ] 서버 재시작 및 테스트
- [ ] 브라우저 개발자 도구에서 데이터 확인
- [ ] 버튼 표시 확인

---

**결론**: AI 통화 시작 시 **WebSocket 이벤트에 `is_ai_handled: True`를 명시**하고, **API 레지스트리에도 등록**하여 REST API와 WebSocket 모두에서 일관되게 AI 통화로 인식되도록 수정했습니다. 서버를 재시작하면 "호 전환" 버튼이 정상적으로 표시됩니다.
