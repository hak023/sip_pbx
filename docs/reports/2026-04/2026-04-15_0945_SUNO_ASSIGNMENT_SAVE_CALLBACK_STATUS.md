## 개요

Suno 통화 연결음 할당 저장 시 `callBackUrl` 미설정으로 발생하던 400(동일 메시지)을 **저장 직전 동기 검증**으로 명확히 하고, **저장 시 자동 Suno 생성**·**목록의 생성 중/비활성 표시**·**폴링 완료 시 MP3 자동 반영**을 구현했다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `sip-pbx/src/call_control/db.py` | 수정 | `suno_generation_status` 컬럼·마이그레이션·CRUD 반영 | 설계대로 |
| `sip-pbx/src/call_control/models.py` | 수정 | 할당 모델에 `suno_generation_status` | 설계대로 |
| `sip-pbx/src/services/ringback_service.py` | 수정 | `ensure_suno_generation_prerequisites`, 할당용 캐시 파일명, `poll_and_notify` 완료 시 다운로드+complete, `kickoff_suno_after_assignment_saved` | 설계대로 |
| `sip-pbx/src/api/routers/call_control_api.py` | 수정 | 저장 시 전제 검증·pending 주입·BackgroundTasks로 kickoff, 업데이트 시 중복 생성 방지 | 설계대로 |
| `sip-pbx/src/api/routers/ringback.py` | 수정 | apply-music 시 `suno_generation_status=complete` | 설계대로 |
| `sip-pbx/frontend/app/settings/call-control/page.tsx` | 수정 | 음원 생성/새로고침/적용 UI 제거, 저장 시 검증, 목록 pending UI, WS로 목록 갱신 | 설계대로 |

## 주요 결정 사항

- **400 원인**: Suno API는 `callBackUrl` 필수. 기존에도 `_suno_callback_url()` 미충족 시 `ValueError` → 400이었으나, 이제 **할당 저장 경로에서도 동일하게** `ensure_suno_generation_prerequisites()`로 저장 전에 검증한다.
- **저장 트리거**: `POST/PUT` 후 `kickoff_suno_after_assignment_saved`를 백그라운드로 실행. `PUT`은 `pending` 중이거나 내용 변경 없으면 **재요청하지 않는다**(프론트가 전체 필드를내도 안전).
- **완료 처리**: `poll_and_notify`가 할당용일 때 첫 트랙 `audio_url`을 다운로드해 `suno_audio_path`에 넣고 `complete`로 둔다(수동 «적용» 불필요).
- **콜백 URL**: 여전히 공개 URL이 필요하다. 콜백 엔드포인트는 기존 `POST /api/ringback/suno-callback`이며, 실제 완료 반영은 **서버 폴링**이 담당한다.

## 잔여 과제 (선택)

- 운영 환경에서 `ringback.public_api_base_url` 또는 `SUNO_CALLBACK_URL`을 반드시 설정할 것(ngrok 등).
