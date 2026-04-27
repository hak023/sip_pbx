# Google Calendar 예약 연동 구현

- **작성일**: 2026-04-13 15:45
- **상태**: 완료
- **관련 설계**: 설계 플랜 파일 (`google_calendar_예약_연동_0982fb3c.plan.md`)

---

## 개요

Owner(사업자)가 Google OAuth 2.0으로 로그인하면 자체 DB의 예약이 Google Calendar에 자동 동기화되고, 운영자가 프론트엔드에서 캘린더를 조회·관리할 수 있는 기능을 전면 구현하였다. 연동 방식은 Google Calendar API v3 직접 호출(서버 사이드)로 결정하였으며, 동기화 실패가 예약 생성을 블로킹하지 않도록 설계하였다.

---

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|---|---|---|---|
| `src/booking/database.py` | 수정 | `google_tokens`, `gcal_event_map` DDL 추가 | 기존 `_DDL` 문자열에 append |
| `src/services/gcal_service.py` | **신규** | Google Calendar API 래퍼 (토큰 관리 + 이벤트 CRUD + 일괄 동기화) | 설계대로 |
| `src/api/routers/google_calendar.py` | **신규** | OAuth start/callback/status/disconnect + calendar events + sync 엔드포인트 | 설계대로 |
| `src/api/main.py` | 수정 | `google_calendar_router` 등록 | `app.include_router` 추가 |
| `src/services/booking_service.py` | 수정 | `create_booking`, `update_booking`, `cancel_booking`, `reschedule_booking`에 gcal 훅 추가 | 실패 시 예약 블로킹 없음 |
| `config/config.yaml` | 수정 | `google_calendar` 블록 추가 (client_id, client_secret, redirect_uri, calendar_id) | 빈 값 — 실제 키는 별도 입력 필요 |
| `config/config.example.yaml` | 수정 | 동일하게 `google_calendar` 블록 + 환경변수 안내 추가 | |
| `requirements.txt` | 수정 | `google-auth>=2.0`, `google-auth-oauthlib>=1.0`, `google-api-python-client>=2.0` 추가 | |
| `frontend/components/AppHeader.tsx` | 수정 | NAV_ITEMS에 `{ href: '/settings/integrations', label: '설정' }` 추가 | |
| `frontend/app/settings/integrations/page.tsx` | **신규** | Google Calendar 연동 관리 UI (상태 조회, 연동/해제, 일괄 동기화 버튼) | |
| `frontend/app/booking/page.tsx` | 수정 | 메인 탭 추가 (`예약 목록` / `Google 캘린더`) + `GoogleCalendarTab` 인라인 컴포넌트 | |

---

## 주요 결정 사항

### 1. 연동 방식: Google Calendar API v3 직접 호출

- Google Calendar MCP(`@cocal/google-calendar-mcp`)는 LLM agent가 자연어로 캘린더를 다룰 때 적합하지만, 서버 사이드 자동 동기화에는 불필요한 레이어 추가.
- 서버 사이드에서 직접 `google-api-python-client`로 이벤트 CRUD → 단순하고 안정적.

### 2. 토큰은 owner(테넌트) 단위로 SQLite 저장

- 한 사업자당 Google 계정 1개 연결.
- access_token 만료 시 `_get_credentials()` 내부에서 refresh_token으로 자동 갱신 후 DB 재저장.

### 3. 동기화 실패는 예약 생성을 블로킹하지 않음

- booking_service의 모든 훅은 `try/except` + `logger.warning()`으로 처리.
- Google Calendar 오류가 예약 워크플로를 깨는 일이 없도록 보장.

### 4. 예약 ↔ 이벤트 매핑은 `gcal_event_map` 테이블로 관리

- `booking_id → gcal_event_id` 1:1 매핑.
- update/cancel 시 이 테이블로 이벤트 ID를 역조회하여 Google Calendar 이벤트를 수정/삭제.
- 매핑이 없는 경우 update는 새 이벤트를 생성한다(새로 연동한 owner의 기존 예약 대응).

### 5. 일괄 동기화 API (`POST /api/google/calendar/sync`)

- 최초 연동 시 미래 확정 예약(`status=confirmed`, `slot_date >= today`)을 한 번에 캘린더에 등록.
- 기존 매핑이 있으면 update, 없으면 create.

---

## API 엔드포인트 요약

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/google/oauth/start?owner=` | Google OAuth 인증 화면으로 리다이렉트 |
| GET | `/api/google/oauth/callback` | 인가 코드 → 토큰 교환 후 저장, 프론트로 리다이렉트 |
| GET | `/api/google/oauth/status?owner=` | 연동 여부·캘린더 ID 반환 |
| DELETE | `/api/google/oauth/disconnect?owner=` | 토큰 및 이벤트 매핑 삭제 |
| GET | `/api/google/calendar/events?owner=&date_from=&date_to=` | 이벤트 목록 조회 |
| POST | `/api/google/calendar/sync?owner=` | 미래 예약 일괄 동기화 |

---

## 사용 전 설정

1. GCP Console에서 OAuth 2.0 클라이언트 ID(웹 애플리케이션) 생성.
2. Authorized redirect URIs에 `http://localhost:8000/api/google/oauth/callback` 추가.
3. `config/config.yaml`의 `google_calendar.client_id`, `client_secret`에 실제 값 입력.
4. 또는 환경변수 `GCAL_CLIENT_ID`, `GCAL_CLIENT_SECRET` 설정.
5. 의존성 설치: `pip install google-auth google-auth-oauthlib google-api-python-client`

---

## 잔여 과제

- 프로덕션 환경에서 `OAUTHLIB_INSECURE_TRANSPORT=1`을 제거하고 HTTPS를 구성해야 함.
- Google Calendar 이벤트에서 예약을 수정하는 역방향 웹훅(Google → SIP PBX) 연동은 미구현 (향후 Google Calendar Push Notification 활용 검토).
- 캘린더 뷰 UI의 월/주 형태 시각화는 현재 테이블 형식으로만 제공. 풀 캘린더 라이브러리 통합 검토 가능.
