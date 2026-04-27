## 메타

- 작성일: 2026-04-14 (로컬)
- 상태: 수정 완료
- 관련: 임베디드 `uvicorn.Server`, Ctrl+C 종료, `run_server` 메인 대기 루프

## 개요

임베디드 모드에서 `uvicorn.Server.serve()`가 `install_signal_handlers()`로 SIGINT를 등록하면(Windows: `signal.signal`), Ctrl+C 시 uvicorn만 graceful shutdown 로그를 남기고 종료한 뒤, **`run_server`의 `while sip_endpoint.is_running()`은 계속** 돌아 프로세스가 남는 현상이 있었다. 인스턴스에 대해 `install_signal_handlers` 를 no-op 으로 덮어 SIP·`finally` 종료 경로와 맞췄다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `sip-pbx/src/main.py` | 수정 | 임베디드 `uvicorn.Server` 생성 직후 `install_signal_handlers = lambda: None` | 설계대로 |

## 주요 결정 사항

- 프로세스 전체 종료는 기존처럼 **Ctrl+C → `KeyboardInterrupt` → `finally`(uvicorn should_exit·WS·SIP·로깅)** 로 통일한다.
- 레거시 스레드 모드(`SIP_PBX_EMBEDDED_API=0`)는 기존 `uvicorn.run` 동작 그대로다.

## 잔여 과제

- 콘솔 없이 서비스로 띄울 때 SIGTERM 처리가 필요하면 `asyncio` 루프 쪽에 별도 핸들러 추가 검토.
