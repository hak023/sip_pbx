# app.log 364–425 라인 에러 점검 요약

해당 구간에서 발생한 에러/경고와 조치 내용입니다.

---

## 1. `jwt_invalid` / `ws_connection_rejected_jwt_error` (라인 369–370)

- **로그**: `jwt_invalid`, `ws_connection_rejected_jwt_error`, `progress: realtime`
- **원인**: 대시보드/실시간 연결 시 **JWT가 아닌 토큰**(예: extension 로그인용 `tok_*`)을 사용했는데, 서버가 JWT만 허용해 연결을 거부한 경우입니다.
- **조치**:
  - **Socket.IO 서버(8001)**: `src/websocket/server.py`는 이미 **모든 토큰(tok_*, JWT) 허용**으로 동작합니다. 해당 서버를 사용 중이라면 재시작 후에는 이 경고가 나오지 않아야 합니다.
  - **다른 경로에서 JWT 검사 시**: `src/api/auth_utils.py`에 추가된 `is_connection_token_acceptable(token)`을 사용해, `tok_*` 또는 유효한 JWT일 때만 연결을 허용하도록 변경할 수 있습니다. 연결 시 `decode_jwt`만 쓰고 있으면 `tok_*`에서 `JWTInvalidError`가 나므로, 먼저 `is_connection_token_acceptable(token)`으로 수락 여부를 판단한 뒤, extension이 필요할 때만 `extract_extension_from_token(token)`을 사용하세요.

---

## 2. STT streaming error – Audio Timeout (라인 371)

- **로그**: `400 Audio Timeout Error: Long duration elapsed without audio. Audio should be sent close to real time.`
- **원인**: Google STT 스트리밍에 **오디오가 일정 시간 동안 전혀 들어오지 않음**. AI 인사말(TTS)이 먼저 재생되는 동안 사용자 음성이 없어서 발생할 수 있습니다.
- **조치**: 통화 흐름상 자연스러운 동작일 수 있습니다. TTS 재생이 끝난 뒤 사용자가 말하면 STT가 다시 인식합니다. 문제가 반복되면 STT 시작 시점을 첫 TTS 종료 이후로 지연하거나, 스트리밍 타임아웃 설정을 확인하세요.

---

## 3. TTS synthesis error – language code (라인 373, 411)

- **로그**: `400 Requested language code 'ko' doesn't match the voice 'ko-KR-Chirp3-HD-Kore''s language code 'ko-kr'.`
- **원인**: TTS 요청 시 **언어 코드 `ko`**를 쓰는데, 보이스 `ko-KR-Chirp3-HD-Kore`는 **`ko-kr`(또는 `ko-KR`)만** 허용합니다.
- **조치**: **적용 완료.** `src/ai_voicebot/ai_pipeline/tts_client.py`에서 **`normalize_tts_language_code()`** 로 한 곳에서 정규화합니다. `"ko"`, `"ko-kr"`, `"ko_kr"`, `"koKR"` 등은 모두 **`ko-KR`**로 통일되며, Chirp 보이스(`voice_name`이 `ko-KR-...`)와도 자동으로 맞춰집니다. 다른 경로에서 TTS/보이스에 language를 넘길 때는 이 함수를 사용하면 됩니다.

---

## 4. LLM response truncated – MAX_TOKENS (라인 412–413)

- **로그**: `llm_response_truncated_max_tokens`, `max_output_tokens: 1024`, `response_len: 84`
- **원인**: LLM 응답이 **max_output_tokens(1024)** 제한에 걸려 잘림. 84자에서 잘린 것은 설정/요청에 따라 다를 수 있습니다.
- **조치**: 필요 시 설정에서 `max_output_tokens`를 늘리세요(예: 2048). 응답이 짧아도 괜찮다면 변경하지 않아도 됩니다.

---

## 5. DB client not configured (라인 415)

- **로그**: `DB client not configured, skipping LLM logging`
- **원인**: LLM 로그를 DB에 남기도록 되어 있으나, DB 클라이언트가 설정되지 않음.
- **조치**: DB 로깅이 필요하면 `ai_logger.set_db_client(db)` 등으로 클라이언트를 설정하세요. 불필요하면 무시해도 됩니다.

---

## 적용된 코드 변경 요약

| 파일 | 내용 |
|------|------|
| `src/ai_voicebot/ai_pipeline/tts_client.py` | `normalize_tts_language_code()` 도입 — `ko`/`ko-kr`/`ko_kr`/`koKR` 등 → `ko-KR` 통일, Chirp 보이스와 정렬 |
| `src/api/auth_utils.py` | `is_extension_token()`, `is_connection_token_acceptable()`, `extract_extension_from_token()` 추가 (tok_* 허용·extension 추출) |

재시작 후에도 같은 에러가 나오면, 해당 이벤트가 찍힌 코드 경로(예: 다른 WebSocket/실시간 모듈)에서 위 auth_utils 함수 사용 여부를 확인하면 됩니다.
