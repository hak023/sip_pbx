# 실시간 통화 대시보드 구현 완료

## 구현 완료 항목

### 1. JWT 인증 시스템 ✅
**파일**: `src/api/auth_utils.py`, `src/api/routers/auth.py`

- JWT 토큰 생성 및 검증 유틸리티 구현
- `create_jwt()`: extension, role, tenant 정보를 포함한 JWT 생성
- `decode_jwt()`: JWT 검증 및 파싱 (만료/무효 시 예외 처리)
- `/api/auth/login`: JWT 토큰 반환
- `/api/auth/me`: JWT에서 extension 추출하여 사용자 정보 반환
- `get_current_extension()`: FastAPI Depends로 사용 가능한 인증 미들웨어

### 2. Callee 추출 공통 유틸 ✅
**파일**: `src/sip_core/utils.py`

- `extract_extension_from_uri()`: SIP URI에서 username(extension) 추출
- 정규식 기반 파싱: `sip:([^@;>]+)@`
- 다양한 형식 지원: `sip:1004@domain`, `<sip:1004@domain>`, `sip:1004@domain;tag=abc`

### 3. 활성 통화 API (callee 필터) ✅
**파일**: `src/api/routers/calls.py`

- `GET /api/calls/active`: JWT 인증 필수, callee == 로그인 extension인 통화만 반환
- CallStateRepository 연동하여 실제 세션 조회
- CallSession → ActiveCall 변환 로직 구현
- `GET /api/calls/{call_id}/transcript`: callee 권한 검사 추가
- CallManager 인스턴스 주입 방식 (`set_call_manager()`)

### 4. WebSocket JWT 인증 및 권한 검사 ✅
**파일**: `src/websocket/server.py`

#### 연결 시 JWT 검증
- `connect()`: auth.token 검사, JWT 파싱하여 extension 추출
- 세션에 extension, role, tenant_name 저장
- 연결 거부: 토큰 없음/만료/무효 시 False 반환

#### subscribe_call 권한 검사
- CallSession 조회 후 callee extension 추출
- callee === 로그인 extension 일 때만 `call_{call_id}` 룸 입장 허용
- 권한 실패 시 `{'success': False, 'error': 'forbidden'}` 반환
- 최대 구독 수 제한 (10개)
- 구독 목록 추적 (`subscribed_calls` set)

#### CallManager 주입
- `set_call_manager()`: WebSocket에서 CallSession 조회용

### 5. 통화 시작/종료 이벤트 발송 ✅
**파일**: `src/sip_core/call_manager.py`

#### 통화 시작 (ACK 수신 시)
- `handle_ack()`: 통화 성립 시 `emit_call_started()` 호출
- payload: caller, callee, is_ai_handled, timestamp

#### 통화 종료 (BYE 처리 시)
- `handle_bye()`: 통화 종료 시 `emit_call_ended()` 호출
- payload: call_id

### 6. Pipecat STT/TTS 실시간 이벤트 연동 ✅
**파일**: 
- `src/ai_voicebot/pipecat/processors/rag_processor.py`
- `src/ai_voicebot/pipecat/pipeline_builder.py`

#### RAGLLMProcessor 수정
- `call_id` 파라미터 추가 (생성자에서 받음)
- **STT 이벤트**:
  - `TranscriptionFrame` 수신 시 `emit_stt_transcript(call_id, text, is_final=True)` 호출
  - `InterimTranscriptionFrame` 수신 시 `emit_stt_transcript(call_id, text, is_final=False)` 호출
- **TTS 이벤트**:
  - TextFrame push 전 `emit_tts_started(call_id, text)` 호출
  - LLMFullResponseEndFrame push 후 `emit_tts_completed(call_id)` 호출

#### Pipeline Builder 수정
- `call_context["call_id"]`를 RAGLLMProcessor에 전달

---

## 새로 생성된 파일

1. **`src/api/auth_utils.py`**: JWT 인증 유틸리티
2. **`src/sip_core/utils.py`**: SIP URI 파싱 유틸리티

---

## 수정된 파일

1. **`src/api/routers/auth.py`**: JWT 발급 및 검증 적용
2. **`src/api/routers/calls.py`**: 실제 세션 조회 + callee 필터
3. **`src/websocket/server.py`**: JWT 인증 + 권한 검사
4. **`src/sip_core/call_manager.py`**: WebSocket 이벤트 발송
5. **`src/ai_voicebot/pipecat/processors/rag_processor.py`**: STT/TTS 이벤트 발송
6. **`src/ai_voicebot/pipecat/pipeline_builder.py`**: call_id 전달

---

## 통합 및 설정 (TODO)

### main.py 수정 필요
```python
# src/api/main.py
from src.api.routers import calls
from src.websocket import server as ws_server

# CallManager 인스턴스 주입
calls.set_call_manager(sip_endpoint.call_manager)
ws_server.set_call_manager(sip_endpoint.call_manager)
```

### requirements.txt 추가
```
PyJWT>=2.8.0
```

### 환경 변수 설정 (권장)
```env
JWT_SECRET_KEY=<강력한-시크릿-키>
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=480
```

### WebSocket 서버 시작
- 현재 `src/websocket/server.py`에 `start_server()` 함수 존재
- main.py에서 별도 asyncio task로 시작하거나, 별도 프로세스로 실행

---

## 테스트 시나리오

### 1. JWT 로그인
```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"extension": "1004"}'

# 응답: {"access_token": "<JWT>", "user": {...}, "tenant": {...}}
```

### 2. 활성 통화 조회 (본인 extension만)
```bash
curl -X GET http://localhost:8000/api/calls/active \
  -H "Authorization: Bearer <JWT>"

# 응답: [{"call_id": "...", "callee": {"number": "1004"}, ...}]
```

### 3. WebSocket 연결 (JWT 인증)
```javascript
const socket = io('http://localhost:8001', {
  auth: { token: '<JWT>' }
});

socket.on('connection_established', (data) => {
  console.log('연결 성공:', data.extension);
});
```

### 4. 통화 구독 (권한 검사)
```javascript
socket.emit('subscribe_call', { call_id: 'abc123' }, (response) => {
  if (response.success) {
    console.log('구독 성공');
  } else {
    console.error('구독 실패:', response.error); // 'forbidden' if not your call
  }
});

// 실시간 이벤트 수신
socket.on('call_started', (data) => { /* ... */ });
socket.on('stt_transcript', (data) => { /* ... */ });
socket.on('tts_started', (data) => { /* ... */ });
socket.on('call_ended', (data) => { /* ... */ });
```

---

## 보안 고려사항

1. **JWT Secret Key**: 프로덕션에서는 환경 변수로 강력한 키 사용
2. **HTTPS**: API와 WebSocket 모두 TLS 적용 권장
3. **CORS**: WebSocket의 `cors_allowed_origins`를 프로덕션 도메인으로 제한
4. **Rate Limiting**: 로그인 API에 적용 권장
5. **Refresh Token**: 장기 세션을 위해 Refresh Token 패턴 도입 고려

---

## 로깅 및 모니터링

모든 주요 이벤트에 `progress="realtime"` 태그 추가:
- `ws_client_connected`
- `ws_call_subscribed`
- `subscribe_call_forbidden`
- `active_calls_retrieved`

```bash
# 실시간 이벤트만 필터
jq 'select(.progress == "realtime")' logs/app.log
```

---

*구현 완료: 2026-02-19*
