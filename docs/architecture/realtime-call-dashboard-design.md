# 실시간 통화 대시보드 설계 (Frontend)

## 1. 개요

Frontend 웹 페이지에서 **본인 착신번호(extension)에 대한 통화**만 조회·모니터링할 수 있도록 하는 기능 설계 문서이다.

### 1.1 목표 요구사항

| # | 요구사항 | 설명 |
|---|----------|------|
| 1 | **현재 통화 중인 내역** | Frontend에서 현재 진행 중인 통화 목록을 확인할 수 있어야 한다. |
| 2 | **STT/TTS 실시간 확인** | AI 응대 호뿐 아니라 **사람이 전화받을 때**도 STT/TTS를 실시간으로 볼 수 있어야 한다. |
| 3 | **계정·전화번호 일치** | 로그인한 계정(extension)과 통화의 **callee(착신번호)**가 일치할 때만 해당 통화를 조회·구독할 수 있다. (예: 1004 로그인 → callee가 1004인 호만 표시) |

### 1.2 용어

- **Extension**: 착신번호(예: 1004). 로그인 시 사용하는 계정 식별자.
- **Callee**: 통화의 수신측. SIP `To` 헤더에서 추출한 username(extension).
- **Caller**: 통화의 발신측. SIP `From` 헤더에서 추출.

---

## 2. 현재 구현 상태

### 2.1 이미 구현된 것

| 영역 | 구현 내용 | 위치 |
|------|-----------|------|
| **인증** | 착신번호(extension) 기반 로그인. 패스워드 없이 extension만으로 로그인. | `src/api/routers/auth.py` (`POST /api/auth/login`, `GET /api/auth/me`) |
| **Auth 응답** | 로그인 시 `User.id`, `TenantInfo.owner`에 extension 반환. | `LoginResponse`: `user.id`, `tenant.owner` |
| **통화 상태 저장소** | 활성 세션 조회 `get_active_sessions()`, `get_all()`. CallSession에 `get_callee_uri()`, `get_caller_uri()` 보유. | `src/repositories/call_state_repository.py`, `src/sip_core/models/call_session.py` |
| **활성 통화 API (목업)** | `GET /api/calls/active` 존재. 현재는 **Mock 데이터** 반환, 실제 CallManager/Repository 미연동. | `src/api/routers/calls.py` |
| **트랜스크립트 API (목업)** | `GET /api/calls/{call_id}/transcript` 존재. Mock 데이터만 반환. | `src/api/routers/calls.py` |
| **WebSocket 서버** | Socket.IO 기반. `subscribe_call` / `unsubscribe_call`로 특정 `call_id` 룸 구독. | `src/websocket/server.py` (포트 8001) |
| **실시간 이벤트 함수** | `emit_call_started`, `emit_call_ended`, `emit_stt_transcript`, `emit_tts_started`, `emit_tts_completed` 등 정의됨. `broadcast_to_call(call_id, event, data)`로 해당 통화 구독자에게만 전송. | `src/websocket/server.py` |
| **WebSocket 인증** | 연결 시 `auth.token` 검사. 현재는 `mock_token_*` 형태만 허용. **JWT/extension 추출 미구현**. | `server.py` `connect()` |
| **구독 시 권한 검사** | **없음**. `subscribe_call` 시 **callee와 로그인 extension 일치 여부 검사하지 않음**. | `server.py` `on_subscribe_call()` |

### 2.2 미구현 또는 부분 구현

| 영역 | 상태 | 비고 |
|------|------|------|
| **활성 통화 API 실제 연동** | 미구현 | CallStateRepository + CallManager 연동, **callee(extension) 필터** 필요. |
| **JWT 및 extension 추출** | 미구현 | `/api/auth/me`가 고정값 반환. 토큰에 extension 포함·검증 후 WebSocket/API에서 사용 필요. |
| **통화 시작/종료 시 WebSocket 발송** | 미구현 | SIP 통화가 시작/종료될 때 `emit_call_started` / `emit_call_ended` **호출하는 코드 없음**. (함수만 존재) |
| **STT 실시간 WebSocket 발송** | ✅ 구현됨 | `RAGLLMProcessor`에서 `TranscriptionFrame`/`InterimTranscriptionFrame` 수신 시 `emit_stt_transcript(call_id, text, is_final)` 호출. |
| **TTS 실시간 WebSocket 발송** | ✅ 구현됨 | `RAGLLMProcessor`에서 LLM 응답 전송 시 `emit_tts_started`, `emit_tts_completed` 호출. |
| **사람 수신 호의 STT/TTS** | 미구현 | 사람이 받는 일반 SIP 호에 대한 실시간 STT/TTS 파이프라인·이벤트 없음. (현재 STT는 Pipecat 내부 또는 통화 종료 후 녹음 기반 후처리) |
| **Frontend UI** | 별도 프로젝트 가능성 | 이 저장소에는 API·WebSocket 서버만 있음. Frontend 앱(React 등)은 다른 경로에 있을 수 있음. |

### 2.3 Callee 추출 방법 (기존 코드)

- **CallSession**: `get_callee_uri()` → SIP `To` URI 문자열 (예: `sip:1004@10.0.0.1`).
- **SIP Endpoint**: `_extract_username(sip_uri)`로 URI에서 username(extension) 추출. 정규식 `sip:([^@;>]+)@` 사용.
- API/WebSocket에서 **extension**과 비교할 때는 `get_callee_uri()` 결과에 동일한 규칙으로 username만 추출해 비교하면 됨.

---

## 3. 설계

### 3.1 전체 흐름

```
[Frontend]
  - 로그인: extension(예: 1004) → JWT에 extension 포함
  - GET /api/calls/active (Authorization: Bearer <JWT>)
    → 백엔드가 JWT에서 extension 추출
    → CallStateRepository.get_active_sessions() 후 callee extension == 로그인 extension 인 것만 반환
  - WebSocket 연결 시 auth: { token: JWT }
    → 서버가 JWT 검증 후 extension 추출, 세션에 저장
  - subscribe_call({ call_id })
    → 서버가 해당 call_id의 callee extension 조회
    → callee === 로그인 extension 일 때만 room 입장 허용
  - 실시간 이벤트: call_started, call_ended, stt_transcript, tts_started, tts_completed
    → 구독 중인 call_id에 대해 수신하여 UI 갱신
```

### 3.2 API 설계

#### 3.2.1 인증 및 Extension 추출

- **로그인**: 기존처럼 `POST /api/auth/login` Body `{ "extension": "1004" }` → 응답에 **JWT** 반환 (현재는 단순 문자열 토큰; 추후 JWT로 교체 권장).
- **JWT Payload**: 최소한 `sub` 또는 `extension` 필드에 extension(예: `"1004"`) 포함.
- **API 인증**: `GET /api/calls/active` 등에 `Authorization: Bearer <JWT>` 필수. 미들웨어/Depends에서 JWT 검증 후 `request.state.extension` 등에 설정.

#### 3.2.2 활성 통화 목록 (callee 필터)

- **Endpoint**: `GET /api/calls/active`
- **인증**: Bearer JWT 필수.
- **로직**:
  1. JWT에서 extension 추출.
  2. CallManager(또는 직접 CallStateRepository)에서 `get_active_sessions()` 호출.
  3. 각 CallSession에 대해 `get_callee_uri()` → URI에서 username(extension) 추출 (SIP endpoint와 동일 규칙).
  4. `extracted_callee == request.state.extension` 인 세션만 필터.
  5. `ActiveCall` 형태로 변환하여 반환 (call_id, caller, callee, status, is_ai_handled, duration 등).
- **응답**: `List[ActiveCall]`. 본인 extension에 대한 통화만 포함.

#### 3.2.3 트랜스크립트 조회 (선택)

- **Endpoint**: `GET /api/calls/{call_id}/transcript`
- **인증**: Bearer JWT + **해당 call_id의 callee가 로그인 extension과 일치할 때만** 200 및 본문 반환. 불일치 시 403/404.

### 3.3 WebSocket 설계

#### 3.3.1 연결 시 인증

- 클라이언트: `auth: { token: "<JWT>" }` 전달.
- 서버:
  - JWT 검증 후 payload에서 extension 추출.
  - `sio.save_session(sid, { 'extension': extension, ... })` 저장.
  - 연결 거부: 토큰 없음/무효 시 `return False`.

#### 3.3.2 subscribe_call 시 callee 검사

- **이벤트**: `subscribe_call`, payload `{ call_id: string }`.
- **로직**:
  1. CallManager/Repository에서 `call_id`로 CallSession 조회.
  2. 없으면 404 또는 `{ success: false, error: 'call not found' }`.
  3. CallSession에서 callee URI → username(extension) 추출.
  4. `sio.get_session(sid)`에서 로그인 extension 조회.
  5. **callee === 로그인 extension** 일 때만 `sio.enter_room(sid, "call_{call_id}")` 호출.
  6. 불일치 시 `{ success: false, error: 'forbidden' }` 반환 (403에 해당하는 의미).

#### 3.3.3 실시간 이벤트 (기존 정의 활용)

- **call_started**: 통화가 성립될 때(예: 200 OK 수신 후 또는 ACK 수신 후). payload에 `call_id`, `caller`, `callee`, `is_ai_handled` 등.
- **call_ended**: 통화 종료 시. payload `call_id`, `timestamp` 등.
- **stt_transcript**: 사용자 발화 STT. `call_id`, `text`, `is_final`, `timestamp`.
- **tts_started**: AI/시스템 TTS 재생 시작. `call_id`, `text`, `timestamp`.
- **tts_completed**: TTS 재생 완료. `call_id`, `timestamp`.

이미 `broadcast_to_call(call_id, event, data)`가 있으므로, **해당 call_id를 구독한 클라이언트(그리고 위 callee 검사로 구독한 사람만)**에게만 전달되면 된다.

### 3.4 실시간 STT/TTS 연동 (백엔드)

#### 3.4.1 AI 응대 호 (Pipecat)

- **call_id 전달**: Pipecat 파이프라인 생성 시 `call_context`에 `call_id`가 이미 전달됨. 파이프라인 내부(예: RAGLLMProcessor, StreamingTTSGateway)에서 **call_id를 참조할 수 있도록** 공유 컨텍스트 또는 프로세서 생성 인자로 전달 필요.
- **STT**: RAGLLMProcessor에서 `TranscriptionFrame` 수신 시 텍스트 + `is_final`(또는 interim 여부)로 WebSocket `emit_stt_transcript(call_id, text, is_final)` 호출.
- **TTS**:  
  - `emit_tts_started`: StreamingTTSGateway에서 문장/청크를 TTS로 보낼 때(또는 RAGLLMProcessor에서 TextFrame push 시) 호출.  
  - `emit_tts_completed`: 해당 응답 블록의 TTS가 끝날 때(예: LLMFullResponseEndFrame 처리 후 또는 TTSCompleteNotifier 근처) 호출.

Pipecat는 현재 **call_id를 프로세서에 넘기지 않음**. Pipeline Builder에서 `call_context["call_id"]`를 RAGLLMProcessor·StreamingTTSGateway 등에 옵션으로 전달하고, 해당 프로세서가 WebSocket manager를 호출하도록 하면 된다.

#### 3.4.2 사람이 받는 호 (일반 SIP)

- **현재**: 실시간 STT/TTS 스트림이 없음. 통화 종료 후 녹음 파일 기반 후처리 STT만 존재.
- **요구사항 충족을 위한 방향**:
  - **옵션 A**: 일반 SIP 호에도 “미디어 스니핑” 구간을 두고, RTP 스트림을 실시간 STT(TTS는 상대방 음성이라 STT만 해당)로 보내고, 결과를 WebSocket으로 브로드캐스트. (대규모 변경)
  - **옵션 B**: 1차적으로는 **AI 응대 호에만** 실시간 STT/TTS 제공하고, 사람 수신 호는 “현재 통화 중 목록”만 표시 + 종료 후 트랜스크립트/녹음 재생으로 제공. 이후 단계에서 일반 호 실시간 STT를 도입.

설계서에서는 **옵션 B를 1차 권장**하고, 사람 수신 호 실시간 STT는 “Phase 2”로 두는 것을 권장한다.

### 3.5 데이터 모델 (활성 통화)

- **ActiveCall** (기존 `api/models.py` 활용):
  - `call_id`, `caller`, `callee` (CallerInfo: uri, name?, number?), `status`, `is_ai_handled`, `duration`, `current_question?`, `ai_confidence?`, `needs_hitl`.
- CallSession → ActiveCall 변환 시:
  - `get_caller_uri()` / `get_callee_uri()`로 URI 추출.
  - URI에서 username 추출하여 number/name 매핑 (가능하면 테넌트/연락처 정보로 보강).
  - `is_ai_handled`: 해당 `call_id`가 `CallManager.ai_enabled_calls`에 있는지로 판단.

### 3.6 Callee(Extension) 추출 공통 유틸

- SIP URI 문자열에서 username 추출은 한 곳에서만 수행하는 것이 유지보수에 유리함.
- 제안: `src/sip_core/utils.py` 또는 기존 `sip_endpoint` 내 `_extract_username`를 공용 함수로 분리 (예: `extract_extension_from_uri(uri: str) -> str`). API·WebSocket·CallManager에서 동일 함수 사용.

---

## 4. 구현 체크리스트

### 4.1 백엔드 (API · 인증)

- [ ] JWT 발급: 로그인 응답에 JWT 포함, payload에 `extension`(또는 `sub`) 포함.
- [ ] JWT 검증 미들웨어/Depends: API 요청에서 Bearer 토큰 검증 후 `request.state.extension` 설정.
- [ ] `GET /api/auth/me`: JWT에서 extension 추출해 해당 사용자/테넌트 정보 반환 (목업 제거).
- [ ] Callee 추출 유틸: SIP URI → extension 문자열 반환하는 공용 함수 도입 및 사용처 통일.

### 4.2 백엔드 (활성 통화 API)

- [ ] CallManager(또는 Repository) 연동: `GET /api/calls/active`에서 실제 `get_active_sessions()` 호출.
- [ ] Callee 필터: 세션의 callee extension == JWT의 extension 인 것만 반환.
- [ ] CallSession → ActiveCall 변환: caller/callee URI → CallerInfo, status, is_ai_handled, duration 등 채우기.
- [ ] `GET /api/calls/{call_id}/transcript`: call_id에 해당하는 세션의 callee가 로그인 extension과 일치할 때만 200 + 데이터 반환.

### 4.3 백엔드 (WebSocket)

- [ ] 연결 시 JWT 검증 및 세션에 extension 저장.
- [ ] `subscribe_call`: call_id로 CallSession 조회 → callee extension 추출 → 로그인 extension과 일치 시에만 `enter_room("call_{call_id}")`.
- [ ] 불일치/없음 시 에러 응답 반환.

### 4.4 백엔드 (실시간 이벤트 발송)

- [ ] **통화 시작**: SIP에서 통화 성립 시점(예: ACK 수신 후 또는 AI takeover 시)에 `emit_call_started(call_id, call_data)` 호출. call_data에 callee, is_ai_handled 등 포함.
- [ ] **통화 종료**: BYE 처리 후 정리 단계에서 `emit_call_ended(call_id)` 호출.
- [ ] **STT (Pipecat)**: RAGLLMProcessor 등에서 TranscriptionFrame 수신 시 `emit_stt_transcript(call_id, text, is_final)` 호출. call_id는 파이프라인에서 프로세서로 주입.
- [ ] **TTS (Pipecat)**: TextFrame 전송 또는 스트리밍 청크 전송 시 `emit_tts_started`, 블록 완료 시 `emit_tts_completed`. call_id 주입 동일.

### 4.5 Pipecat 연동 상세

- [ ] Pipeline Builder에서 RAGLLMProcessor·StreamingTTSGateway 등에 `call_id`(및 필요 시 websocket emit 콜백) 전달.
- [ ] RAGLLMProcessor: TranscriptionFrame 처리 시 websocket emit_stt_transcript 호출.
- [ ] StreamingTTSGateway(또는 TTS 완료 알림 지점): TTS 시작/완료 시 emit_tts_started, emit_tts_completed 호출.

### 4.6 Frontend (참고)

- [ ] 로그인 후 JWT 저장, API 요청 시 `Authorization: Bearer <JWT>` 첨부.
- [ ] WebSocket 연결 시 `auth: { token: JWT }` 전달.
- [ ] `GET /api/calls/active`로 활성 통화 목록 표시 (본인 extension만 나오는지 확인).
- [ ] 통화 선택 시 `subscribe_call({ call_id })` 호출.
- [ ] 수신 이벤트: `call_started`, `call_ended`, `stt_transcript`, `tts_started`, `tts_completed` 수신하여 실시간 트랜스크립트/상태 UI 갱신.

### 4.7 (Phase 2) 사람 수신 호 실시간 STT

- [ ] 일반 SIP 호에 대한 실시간 음성 구간 스니핑 및 STT 파이프라인 설계·구현.
- [ ] 해당 호의 call_id에 대해 `emit_stt_transcript` 발송 및 권한은 동일하게 callee 일치 시에만 구독 가능하도록 유지.

---

## 5. 보안 요약

- **활성 통화 목록**: 로그인 extension과 callee가 일치하는 통화만 반환.
- **트랜스크립트 조회**: 해당 call_id의 callee가 로그인 extension과 일치할 때만 허용.
- **WebSocket 구독**: `subscribe_call` 시 동일하게 callee == 로그인 extension 검사. 통과한 클라이언트만 `call_{call_id}` 룸에 들어가므로, 이후 `broadcast_to_call`로 보내는 모든 이벤트는 이미 권한이 있는 사용자에게만 전달됨.

---

## 6. 참고 파일

| 용도 | 파일 |
|------|------|
| 활성 통화 API (목업) | `src/api/routers/calls.py` |
| 인증 API | `src/api/routers/auth.py` |
| API 모델 (ActiveCall, User, TenantInfo) | `src/api/models.py` |
| WebSocket 서버·이벤트 정의 | `src/websocket/server.py` |
| WebSocket 매니저 re-export | `src/websocket/manager.py` |
| 통화 상태 저장소 | `src/repositories/call_state_repository.py` |
| CallSession·Leg 모델 | `src/sip_core/models/call_session.py` |
| CallManager (ai_enabled_calls, no_answer 등) | `src/sip_core/call_manager.py` |
| SIP URI에서 username 추출 | `src/sip_core/sip_endpoint.py` (`_extract_username`) |
| Pipecat 파이프라인·call_context | `src/ai_voicebot/pipecat/pipeline_builder.py` |
| RAGLLMProcessor (TranscriptionFrame 처리) | `src/ai_voicebot/pipecat/processors/rag_processor.py` |
| 스트리밍 TTS | `src/ai_voicebot/pipecat/processors/streaming_tts_processor.py` |

---

*문서 버전: 1.0  
*최종 수정: 설계 초안 작성*
