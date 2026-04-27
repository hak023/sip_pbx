## 개요

Suno `callBackUrl`은 [공식 콜백 문서](https://docs.sunoapi.org/suno-api/generate-music-callbacks)대로 **서버가** `generate_suno_music` → `_suno_callback_url()`에서만 조립합니다. 프론트·REST 요청 본문으로 공개 URL을 받던 경로는 운영·보안 관점에서 부적절하므로 제거했습니다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|------------|------|------|
| `sip-pbx/frontend/app/settings/call-control/page.tsx` | 수정 | Suno 콜백 URL 입력·sessionStorage·저장 body 필드 제거, 서버 설정 안내 문구로 대체 | |
| `sip-pbx/src/call_control/models.py` | 수정 | `RingbackScheduleAssignmentCreate`/`Update`의 콜백 오버라이드 필드 삭제 | |
| `sip-pbx/src/api/routers/call_control_api.py` | 수정 | `_ringback_suno_callback_overrides_from` 삭제, `ensure`/`kickout` 단순화 | |
| `sip-pbx/src/api/routers/ringback.py` | 수정 | `GenerateMusicRequest` 콜백 필드 및 normalize import 제거 | |
| `sip-pbx/src/services/ringback_service.py` | 수정 | `ensure_suno_generation_prerequisites`·`_suno_callback_url`·`generate_suno_music`·`kickoff_suno_*`에서 요청 단위 오버라이드 제거, 오류 문구에서 ④ 제거 | |
| `sip-pbx/config/config.example.yaml` | 추가 | `ringback` 예시(suno_callback_url / public_api_base_url) 주석 | |

## 주요 결정 사항

- 공개 콜백 주소는 **환경변수 또는 `config/config.yaml`의 `ringback` 섹션**만 사용한다.
- 400은 설정 미비 시 그대로 유지되며, 안내는 서버 설정만을 가리킨다.

## 잔여 과제

- 배포 환경에 `PUBLIC_API_BASE_URL` 또는 `SUNO_CALLBACK_URL` 등 실제 공개 URL 반영.
