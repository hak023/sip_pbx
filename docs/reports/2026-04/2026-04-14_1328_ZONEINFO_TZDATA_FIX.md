## 개요

`routing_engine.py`에서 `ZoneInfo("Asia/Seoul")` 호출 시 Windows 환경에 `tzdata` 패키지가 없어 `ZoneInfoNotFoundError`가 발생, `/api/call-control/status/{owner}` API가 500 오류를 반환하는 버그를 수정했다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|---|---|---|---|
| `src/call_control/routing_engine.py` | 수정 | `ZoneInfo` 사용을 `_get_tz()` 헬퍼로 래핑, tzdata 없을 때 고정 UTC 오프셋 폴백 | 불필요한 `re`, `RoutingRule`, `Schedule` import 제거 |
| `venv` (설치) | 추가 | `pip install tzdata==2026.1` 실행 | requirements.txt 없음 — 별도 관리 필요 |

## 원인 분석

- Windows 11에는 OS 레벨 tz 데이터베이스가 없으므로 Python `zoneinfo` 모듈이 `tzdata` 패키지에 의존한다.
- 기존 코드: `ZoneInfoNotFoundError` catch → fallback으로 `ZoneInfo("Asia/Seoul")` 재시도 → 동일 오류 반복 발생.
- 결과: 스케줄이 등록된 owner에 대해 `GET /api/call-control/status/{owner}` 호출마다 500 Internal Server Error.

## 주요 결정 사항

1. **근본 해결**: `pip install tzdata` 로 패키지 설치 → `ZoneInfo("Asia/Seoul")` 정상 동작.
2. **방어 코드**: `_get_tz(tz_name)` 헬퍼 추가 — tzdata 없어도 알려진 타임존은 고정 UTC 오프셋으로 폴백 (기본 UTC+9).
3. **로그 메시지**: Windows CP949 콘솔 인코딩 오류를 피하기 위해 em dash(`—`) 등 특수문자 제거, ASCII로 통일.

## 잔여 과제

- `requirements.txt` (또는 `pyproject.toml`) 파일 생성 및 `tzdata>=2026.1` 추가 필요.
- `holidays` 패키지도 미설치 상태 (`pip install holidays` 권장).
