## 메타

- **작성일(로컬)**: 2026-04-21 15:03
- **상태**: 구현 완료

## 개요

`google_tokens.owner`는 예약·GCal 훅에서 사용하는 **테넌트 키(착신 owner)** 와 동일해야 한다. `gcal_service`는 처음부터 `get_token(owner)` / `save_token(owner, …)` 로 **행 단위 일치**를 전제로 했으나, **OAuth 콜백에서 `save_token`을 호출하는 FastAPI 라우터 모듈이 저장소에 없어** 운영에서 연동 URL만 문서로 안내되거나 수동 DB 삽입에 의존할 수 있었다. 본 작업으로 **state에 서명된 owner** → 콜백에서 **동일 owner로 DB 저장** 및 **연동 점검용 GET**을 추가했다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|------------|------|------|
| `sip-pbx/src/api/routers/google_calendar.py` | 추가 | `/api/google/oauth/start|callback`, `GET/DELETE /api/google/connection` | `main.py` import와 정합 |
| `sip-pbx/src/services/gcal_service.py` | 수정 | state 서명·인가 URL·코드 교환·`get_oauth_status` 보강·`oauth_app_credentials_ok` | 표준 라이브러리만으로 토큰 교환 |

## 주요 결정 사항

1. **owner 일치**: `oauth/start?owner=` 값을 `normalize_owner_username` 후 `sign_oauth_owner_state`에 넣고, 콜백에서 `verify`로 복원한 owner로만 `save_token` — 예약 파이프라인의 `owner`와 동일 규칙으로 맞춘다.
2. **state 위조 방지**: HMAC(`GCAL_OAUTH_STATE_SECRET` 또는 client_secret 폴백). 운영에서는 전용 시크릿 권장.
3. **연동 확인**: `GET /api/google/connection?owner=` → `has_refresh_token`, `token_expiry`, `access_token_prefix` 등(전체 시크릿 비노출).
4. **성공 후 이동**: 선택 `GCAL_OAUTH_SUCCESS_URL` — 없으면 JSON 응답.

## 운영 체크리스트

- Google Cloud Console **승인된 리다이렉트 URI** = `GCAL_REDIRECT_URI` / config `redirect_uri` (기본 `http://localhost:8000/api/google/oauth/callback`).
- 브라우저로 `GET /api/google/oauth/start?owner=1003` → Google 로그인 → 콜백 후 `GET /api/google/connection?owner=1003` 에서 `has_refresh_token: true` 확인.
- 예약 생성 시 `gcal_token_refresh_failed` 가 나오면 **리프레시 토큰 만료·폐기** — 재연동 필요.
