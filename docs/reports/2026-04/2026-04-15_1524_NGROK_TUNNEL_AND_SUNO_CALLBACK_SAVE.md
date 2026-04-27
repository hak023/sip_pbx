## 개요

Suno `callBackUrl`을 로컬 **ngrok 에이전트 API**(`RINGBACK_USE_NGROK_TUNNEL=1`)로부터 자동 조합할 수 있게 하고, `POST /api/ringback/suno-callback`에서 수신한 완료 콜백으로 **MP3 다운로드·DB·WebSocket**까지 처리하도록 했다. 기존 `poll_and_notify`는 `_finalize_suno_generation_success`를 공유하며, 할당이 이미 `complete`이면 조기 종료한다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|------------|------|------|
| `sip-pbx/src/services/ringback_service.py` | 수정 | ngrok 로컬 API 폴백, 콜백 처리·finalize 공통화, 폴링 중복 스킵 | |
| `sip-pbx/src/api/routers/ringback.py` | 수정 | `suno-callback`에서 `BackgroundTasks`로 비동기 처리 | |
| `sip-pbx/src/call_control/db.py` | 수정 | `get_ringback_schedule_assignment_by_suno_task_id`, 인덱스 마이그레이션 | |
| `sip-pbx/config/config.example.yaml` | 수정 | ngrok 환경변수 안내 | |

## 주요 결정 사항

- ngrok 조회는 **옵트인**(`RINGBACK_USE_NGROK_TUNNEL`)으로 두어 4040에 무심코 붙는 일을 줄였다.
- 콜백은 **즉시 200** 후 백그라운드에서 다운로드한다(Suno 콜백 타임아웃 고려).
- `callbackType`이 `first`/`text`인 콜백은 저장하지 않고 로그만 남긴다.

## 잔여 과제

- 운영 서버에서는 `PUBLIC_API_BASE_URL` 또는 고정 도메인이 ngrok보다 적합하다.
