## 개요

Google Calendar OAuth 콜백 완료 후 `/settings/integrations?gcal_connected=1`로 리다이렉트 시 FastAPI(포트 8000)가 해당 경로를 알 수 없어 404를 반환하는 문제를 수정했다. 리다이렉트 URL을 상대 경로에서 프론트엔드 절대 URL로 변경했다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|---|---|---|---|
| `src/api/routers/google_calendar.py` | 수정 | `_frontend_url()` 헬퍼 추가, OAuth 콜백 성공/실패 리다이렉트를 절대 URL로 변경 | - |
| `.env` | 수정 | `FRONTEND_URL=http://localhost:3000` 추가 | 배포 시 실제 URL로 변경 필요 |

## 주요 결정 사항

- **원인**: `RedirectResponse(url="/settings/integrations?...")` 상대 경로는 FastAPI 서버(8000번 포트) 기준으로 해석되어 Next.js 프론트엔드(3000번 포트)로 이동하지 않는다.
- **해결**: `_frontend_url()` 헬퍼를 추가하고, 환경변수 `FRONTEND_URL`(기본값 `http://localhost:3000`)을 읽어 절대 URL로 리다이렉트한다.
- 성공/오류 두 곳의 `RedirectResponse` 모두 동일하게 수정했다.

## 잔여 과제

- 프로덕션 배포 시 `.env`의 `FRONTEND_URL`을 실제 도메인으로 변경해야 한다.
