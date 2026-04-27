## 개요

기존 통화 연결음(Ringback) 기능의 두 가지 잔여 과제를 해결했다.  
1. 프론트엔드 5초 폴링을 제거하고 서버 측 폴링 + WebSocket push로 전환  
2. 음원을 회차별 목록(`ringback_music_items` 테이블)으로 관리하고 UI에서 조회·교체·삭제 가능하게 변경

---

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 |
|---|---|---|
| `src/booking/database.py` | 수정 | `ringback_music_items` 테이블 DDL 추가 |
| `src/services/ringback_service.py` | 수정 | `save_music_items`, `get_music_items`, `set_active_music_item`, `delete_music_item`, `poll_and_notify` 추가 |
| `src/websocket/server.py` | 수정 | `emit_ringback_music_ready`, `emit_ringback_music_failed` 추가 |
| `src/websocket/manager.py` | 수정 | 신규 emit 함수 2개 `__all__`에 추가 |
| `src/api/routers/ringback.py` | 수정 | `generate-music`에 `asyncio.create_task(poll_and_notify)` 추가, `GET /music-list`, `DELETE /music-item/{id}` 신규 |
| `frontend/app/settings/ringback/page.tsx` | 수정 | setInterval 폴링 제거, WS `ringback_music_ready`/`ringback_music_failed` 구독, 섹션 3(저장된 음원 목록) 추가 |

---

## 주요 결정 사항

### 1. 서버 사이드 폴링 + WS push
- 기존: 프론트 → `GET /music-status` setInterval 5초마다 반복
- 변경: `generate-music` API 반환 즉시 `asyncio.create_task(poll_and_notify)` 실행  
  - 서버에서 5초마다 `poll_suno_task` 호출 (최대 300초)  
  - 완료 → `save_music_items()` + `emit_ringback_music_ready()` WS 브로드캐스트  
  - 실패/타임아웃 → `emit_ringback_music_failed()` WS 브로드캐스트

### 2. ringback_music_items 테이블
- `owner + task_id + index_in_task` 조합으로 회차별 곡 저장
- `is_active=1` 인 항목이 현재 통화 연결음으로 사용 중
- `apply-music` 시 해당 item_id의 `is_active`를 1로, 나머지를 0으로 갱신

### 3. 프론트엔드 UI 구조
- 섹션 2 (생성): WS 이벤트 수신 시 `newItems` 갱신, 라디오로 선택 후 "이 음원 사용" 클릭 → 다운로드+활성화
- 섹션 3 (저장 목록): 페이지 로드/WS 수신 후 자동 갱신, 행마다 미리 듣기(`<audio>`)+사용+삭제 버튼
- 생성 중 상태는 "완료 시 알림 수신" 텍스트로 안내 (폴링 없음)

---

## 잔여 과제

- `poll_and_notify` 백그라운드 태스크가 FastAPI 종료 시 강제 취소될 수 있음 → 추후 TaskGroup 또는 생성 상태를 DB에 별도 저장 검토
- 저장된 음원의 `local_path`가 있으면 서버에서 직접 스트리밍하는 엔드포인트 추가 고려 (외부 URL 만료 대비)
