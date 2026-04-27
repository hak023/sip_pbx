# Suno callBackUrl 필수 오류 대응

- **작성일**: 2026-04-14 (로컬)
- **상태**: 구현 완료
- **관련**: `app.log` `suno_generate_no_task_id` / Suno 응답 `Please enter callBackUrl`

## 개요

Suno `POST .../api/v1/generate` 요청에 `callBackUrl`을 빈 문자열로 보내 API가 400을 반환했고, 상위 로직은 `taskId` 부재로 `suno_generate_no_task_id` 및 링백 생성 실패로 이어졌다. 비공백·유효한 콜백 URL을 설정으로 조합하고, 해당 URL로 들어오는 POST를 수신하는 최소 엔드포인트를 추가했다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|------------|------|------|
| `sip-pbx/src/services/ringback_service.py` | 수정 | `_suno_callback_url()` 추가, generate 페이로드에 반영, 환경변수 문서화 | 설정 없으면 `ValueError` → API 400 |
| `sip-pbx/src/api/routers/ringback.py` | 수정 | `POST /api/ringback/suno-callback` 추가(로그 + 200) | 폴링이 주 완료 경로 유지 |
| `sip-pbx/config/config.yaml` | 수정 | `suno_callback_url` / `public_api_base_url` 주석 안내 | 운영 시 값 설정 필요 |

## 주요 결정 사항

- 콜백 본문으로 DB·WS를 즉시 갱신하지 않고, 기존 `poll_and_notify` 폴링을 유지한다. Suno 측 필수 필드 충족과 외부 도달 검증이 목적이다.
- URL 해석 우선순위: `SUNO_CALLBACK_URL` → `ringback.suno_callback_url` → `ringback.public_api_base_url` 또는 `PUBLIC_API_BASE_URL` + 고정 경로 `/api/ringback/suno-callback`.

## 잔여 과제

- 운영 환경에서 **공개 HTTPS**로 위 경로가 Suno 서버에서 POST 가능한지(방화벽·리버스 프록시·ngrok 등) 확인한다.
- 필요 시 콜백 페이로드 파싱 후 폴링 보조·중복 알림 방지 로직을 추가할 수 있다.
