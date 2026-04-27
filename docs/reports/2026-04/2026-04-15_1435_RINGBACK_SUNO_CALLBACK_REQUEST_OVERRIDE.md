# Ringback Suno callBackUrl 요청 단위 오버라이드

- **작성일(로컬)**: 2026-04-15
- **상태**: 구현 완료
- **관련**: [Suno Music Generation Callbacks](https://docs.sunoapi.org/suno-api/generate-music-callbacks), `ringback_service._suno_callback_url`, `call_control_api` 통화 연결음 할당

## 개요

로그의 400은 Suno 업스트림이 아니라 PBX가 `callBackUrl`을 구성하지 못할 때 `ensure_suno_generation_prerequisites`에서 나는 사전 검사 오류였다. 로컬에서 `config.yaml`에 `public_api_base_url` 등이 없으면 계속 실패하므로, **이번 API 요청에만** 공개 베이스 URL 또는 전체 콜백 URL을 넘길 수 있게 하고, 백그라운드 `kickoff_suno_after_assignment_saved`와 `generate_suno_music`까지 동일 값을 전달해 Suno `POST /api/v1/generate` JSON의 `callBackUrl`과 일치시켰다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|------------|------|------|
| `sip-pbx/src/api/routers/call_control_api.py` | 수정 | 할당 생성·수정 시 콜백 임시 필드를 `data`에서 제거하고 `ensure`/`kickoff`에 전달 | DB 미저장 |
| `sip-pbx/src/services/ringback_service.py` | 수정 | `generate_suno_music`·`kickoff_suno_after_assignment_saved`에 오버라이드 인자 추가 | `_suno_callback_url` 연동 |
| `sip-pbx/src/api/routers/ringback.py` | 수정 | `GenerateMusicRequest`에 동일 선택 필드, `ensure` 후 `generate_suno_music`에 전달 | |
| `sip-pbx/frontend/app/settings/call-control/page.tsx` | 수정 | Suno 모드에 공개 베이스·전체 콜백 입력, `sessionStorage` 보존, 저장 body에 포함 | |

## 주요 결정 사항

- 문서상 `callBackUrl`은 Suno가 인터넷에서 POST하므로 공개 URL이 필수이다. PBX는 여전히 localhost 호스트를 거절한다.
- 운영 설정(env/config)이 없을 때 개발자가 UI에서 ngrok 베이스만 넣어도 저장·생성이 통과하도록 요청 단위 오버라이드를 우선 적용한다.

## 잔여 과제

- 장기적으로는 `ringback.public_api_base_url` 등 서버 설정을 권장한다.
