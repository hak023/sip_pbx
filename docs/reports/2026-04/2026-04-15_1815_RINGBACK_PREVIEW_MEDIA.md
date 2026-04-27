## 메타

- 작성일: 2026-04-15
- 상태: 완료
- 관련: `src/api/routers/call_control_api.py`, `frontend/app/settings/call-control/page.tsx`

## 개요

착신 제어 통화 연결음(Suno/TTS) 생성 후 브라우저에서 미리듣기할 수 있도록, 할당 단위 로컬 파일을 Bearer 인증으로 내려주는 API와 프론트 Blob URL 재생 UI를 추가했다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----|-----|---|---|
| `sip-pbx/src/api/routers/call_control_api.py` | 수정 | `GET .../ringback-assignments/{id}/media`, `data/` 하위 파일만 허용 | |
| `sip-pbx/frontend/app/settings/call-control/page.tsx` | 수정 | `RingbackMediaPreview`, 목록 카드·수정 모달 | `getApiUrl`+`authHeaders` fetch |
| `sip-pbx/docs/reports/2026-04/2026-04-15_1815_RINGBACK_PREVIEW_MEDIA.md` | 추가 | 본 리포트 | |

## 주요 결정 사항

- `<audio src="/api/...">` 는 Authorization 헤더를 붙일 수 없어 **fetch → Blob URL** 패턴 사용.
- 로컬 경로는 **`cwd/data` 이하**로만 서빙해 디렉터리 이탈 방지.
- Suno 완료인데 로컬 경로가 없고 `suno_audio_url` 만 있으면 **원격 URL 직접** `<audio>` (CORS는 원격 서버 정책에 따름).

## 잔여 과제 (선택)

- 수정 모달을 연 채로만 WS로 목록이 갱신되면, 모달 안 `row`는 구버전일 수 있음 — 필요 시 편집 중 할당만 재조회 API 호출.
