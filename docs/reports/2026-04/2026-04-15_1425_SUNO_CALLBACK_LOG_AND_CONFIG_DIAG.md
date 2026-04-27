## 메타

- **작성일(로컬)**: 2026-04-15
- **상태**: 완료
- **관련 경로**: `sip-pbx/src/services/ringback_service.py`, `sip-pbx/src/api/routers/call_control_api.py`, `sip-pbx/src/api/http_error_logging.py`

## 개요

Suno 콜백 URL 미설정 시 앞단 경고 로그에 HTTP 요청 맥락이 없고, 콜백이 «요청에 안 실린 것처럼」 보이는 혼동을 줄이기 위해 설정 파일 진단 필드를 추가했다. 통화 연결음 저장 실패(`call_control_ringback_suno_prerequisite_failed`)에는 URL·클라이언트·본문 미리보기·파싱 payload 미리보기를 넣었다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `sip-pbx/src/services/ringback_service.py` | 수정 | `ringback_config_yaml_path` / `ringback_config_load_diag`; 콜백 관련 warning에 경로·파일 존재·`ringback` 키·env 플래그·설계 노트 | |
| `sip-pbx/src/api/routers/call_control_api.py` | 수정 | ringback create/update에 `Request`; 실패 로그에 `_http_request_log_fields` | |
| `sip-pbx/src/api/http_error_logging.py` | 수정 | `http_exception`/`request_validation_error`에 `http_request_url`, `http_request_client_host` | |

## 주요 결정 사항

- **callBackUrl**은 구조상 **HTTP 요청 JSON에 포함되지 않는다**. Suno `generate` 페이로드는 서버가 `_suno_callback_url()`로 조합하며, 값은 `SUNO_CALLBACK_URL` / `config.yaml` → `ringback` / `PUBLIC_API_BASE_URL` 등에서만 온다.
- 로그 421행의 `request_body_preview`는 이미 요청 본문이나, 앞선 `suno_*` 줄에는 없어서 **같은 정보를 `call_control_*`에도 실었다**.

## 잔여 과제

- `config.yaml`이 없거나 `ringback:` 블록이 비어 있으면 로그의 `config_yaml_exists` / `ringback_section_keys`로 즉시 구분 가능.
