## 메타

- 작성일: 2026-04-14 (로컬)
- 상태: 점검·수정 반영
- 관련: `sip-pbx/src/main.py` 임베디드 `uvicorn.Server`, 종료 시퀀스

## 개요

Uvicorn 0.27에서 `timeout_graceful_shutdown` 기본값이 `None`이면 `Server.shutdown()` 안의 `asyncio.wait_for(..., timeout=None)`이 **사실상 무제한**으로 연결·백그라운드 태스크 종료를 기다릴 수 있다. 대시보드 등 **짧은 주기 폴링 + keep-alive**가 있으면 “graceful shutdown이 안 된다”처럼 느껴지거나 종료가 길어질 수 있어, **초 단위 상한**을 두고 `finally`에서 **SIP 정리가 빠지지 않도록** 예외 타입을 넓혔다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|------------|------|------|
| `sip-pbx/src/main.py` | 수정 | `uvicorn.Config`에 `timeout_graceful_shutdown`(기본 10초, `UVICORN_GRACEFUL_SHUTDOWN_SEC`로 1~120 조정), `NO_COLOR` 시 `use_colors=False` | Uvicorn 내장 shutdown 타임아웃 |
| `sip-pbx/src/main.py` | 수정 | `finally`에서 HTTP/WS 정리 실패 시에도 `sip_endpoint.stop()`이 실행되도록 `except BaseException` + 내부 `finally` | Ctrl+C 재입력 등 |

## 주요 결정 사항

- **기본 10초**: 초과 시 Uvicorn이 미완료 태스크를 취소하고 lifespan shutdown으로 진행한다(라이브러리 동작).
- **색상**: `NO_COLOR` 환경 변수가 있으면 로그 ANSI 비활성화(일부 PowerShell/리다이렉트 환경에서 `[32m` 등이 그대로 보이는 현상 완화).

## 운영 메모

- 상한만 바꾸려면: `UVICORN_GRACEFUL_SHUTDOWN_SEC=20` (1~120 정수 권장).

## 잔여 과제

- 통화 중 BYE 등 SIP 전용 graceful 정책은 별도 설계(현재는 `stop()`으로 수신 루프 중단).
