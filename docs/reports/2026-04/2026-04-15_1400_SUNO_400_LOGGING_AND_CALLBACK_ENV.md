## 메타

- **작성일(로컬)**: 2026-04-15
- **상태**: 구현 완료
- **관련 경로**: `sip-pbx/src/api/http_error_logging.py`, `sip-pbx/src/api/main.py`, `sip-pbx/src/services/ringback_service.py`, `sip-pbx/src/api/routers/ringback.py`, `sip-pbx/src/api/routers/call_control_api.py`

## 개요

Suno 연동 400은 대부분 `ensure_suno_generation_prerequisites()` / `_suno_callback_url()` 의 `ValueError`가 `HTTPException(400)`으로만 변환되는 경로(특히 착신 제어 «통화 연결음» 저장)에서 **structlog 호출이 없어 `app.log`에 흔적이 없었다.** 전역으로 **HTTP 4xx·422 시 detail + 요청 본문 미리보기**를 남기고, Suno 전제 검사 지점에 **명시적 warning**을 추가했다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `sip-pbx/src/api/http_error_logging.py` | 추가 | POST/PUT/PATCH `/api/*` 본문 캡처 + HTTPException/Validation 예외 로깅 | `request_body_preview` 최대 4KB |
| `sip-pbx/src/api/main.py` | 수정 | `register_http_error_logging(app)` 호출 | CORS 다음 등록 |
| `sip-pbx/src/services/ringback_service.py` | 수정 | API 키·콜백 URL 실패 시 `logger.warning`; 안내 문구에 `PUBLIC_API_BASE_URL` 명시 | |
| `sip-pbx/src/api/routers/ringback.py` | 수정 | `generate_music` bad_request 로그에 가사/스타일 길이 등 | |
| `sip-pbx/src/api/routers/call_control_api.py` | 수정 | Suno 전제 실패 시 `call_control_ringback_suno_prerequisite_failed` | |

## 주요 결정 사항

- **400 원인(로직)**: `SUNO_CALLBACK_URL` → `config.yaml` `ringback.suno_callback_url` → `ringback.public_api_base_url` 또는 환경변수 **`PUBLIC_API_BASE_URL`** + `/api/ringback/suno-callback` 순으로 콜백 URL을 만든다. 모두 비면 위와 동일한 안내의 `ValueError` → 400.
- **로그**: 단독 `uvicorn`으로 API만 띄우면 `app.log`가 아니라 콘솔일 수 있다. SIP 메인과 임베디드 API는 `main.initialize_logging` 이후 동일 structlog 체인을 쓴다.

## 잔여 과제

- 없음.
