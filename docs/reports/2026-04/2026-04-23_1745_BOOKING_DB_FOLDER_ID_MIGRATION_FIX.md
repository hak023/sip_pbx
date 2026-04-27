## 개요

API 기동 시 `OperationalError: no such column: folder_id` 로 스레드가 죽는 현상을 점검했다. 원인은 **구버전 `caller_contacts`에 `folder_id`가 없는 상태**에서 `_DDL`의 `CREATE INDEX ... (folder_id)` 가 먼저 실행되어 `executescript`가 중단되고, 이후 `ALTER TABLE ... ADD COLUMN folder_id` 마이그레이션에 도달하지 못한 것이었다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|------------|------|------|
| `sip-pbx/src/booking/database.py` | 수정 | `idx_caller_contacts_folder` 생성을 DDL에서 제거, 마이그레이션에서 `ADD COLUMN` 뒤에 `CREATE INDEX` | 구 DB 호환 |

## 주요 결정 사항

- SQLite는 `CREATE TABLE IF NOT EXISTS`가 기존 테이블을 건너뛰어도, 같은 스크립트의 인덱스 생성은 **현재 테이블 스키마**를 본다. `folder_id` 없는 구 테이블이면 인덱스 DDL 한 줄이 전체 초기화를 막는다.
- 신규 DB는 테이블 정의에 이미 `folder_id`가 있으므로 `ADD COLUMN`은 duplicate로 무시되고, 인덱스만 마이그레이션에서 생성하면 된다.

## 잔여 과제

- 과거에 깨진 트랜잭션으로 DB가 이상한 경우는 `booking.db` 백업 후 재초기화 또는 수동 `PRAGMA`/SQL 점검.
