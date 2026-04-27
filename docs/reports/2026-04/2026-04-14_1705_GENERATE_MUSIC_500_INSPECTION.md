## 메타

- 작성일: 2026-04-14
- 상태: 점검·수정 완료
- 관련: `POST /api/ringback/generate-music` HTTP 500

## 개요

`generate-music`은 Suno 호출 후 `save_settings(owner, {"suno_task_id": task_id})`만 수행한다. 기존 `save_settings`가 **INSERT 시 전 컬럼에 `data.get(...)`만 넣어** `enabled_greeting` / `enabled_ringback` 등 **NOT NULL 컬럼에 NULL**이 들어가면 SQLite 제약 위반으로 **500**이 난다. 이를 **기존 행과 병합 후 UPSERT**하도록 이미 반영되어 있으며, 이번에 **예외 분류 로깅·HTTP 코드 정리**와 보컬 성별 정규화 `_norm_vg`를 추가했다.

## 원인 정리

| 가능 원인 | 증상·구분 |
|-----------|-----------|
| **부분 저장 + NOT NULL** | `suno_task_id`만 넘길 때 `enabled_*` NULL INSERT → IntegrityError → FastAPI 500 |
| **SUNO_API_KEY 미설정** | `ValueError` → 이제 **400** + 경고 로그 |
| **Suno HTTP 비정상** | `RuntimeError` → 이제 **502** + error 로그 |
| **기타** | `logger.exception` + **500** |

`app.log`에 `suno_generate_failed`가 없고 가사만 성공한 경우에도 위 DB 오류면 500이 날 수 있다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `sip-pbx/src/services/ringback_service.py` | 수정 | `save_settings` 병합 UPSERT(기존)·`_norm_vg` 추가 | NOT NULL 500 방지 |
| `sip-pbx/src/api/routers/ringback.py` | 수정 | `generate_music`에서 ValueError→400, RuntimeError→502, 공통 예외 로깅 | 설계대로 |

## 주요 결정 사항

- 클라이언트 설정 오류(Suno 키 없음)와 업스트림(Suno API) 실패를 HTTP로 구분해 원인 파악을 쉽게 했다.

## 잔여 과제

- 여전히 502면 Suno 응답 본문·`SUNO_API_KEY`·`SUNO_API_BASE`를 확인한다.
