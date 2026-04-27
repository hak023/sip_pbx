## 메타

- 작성일: 2026-04-14 (로컬)
- 상태: 구현 완료
- 관련 설계: `sip-pbx/docs/reports/2026-04/2026-04-14_1830_GRPC_MULTI_LOOP_ARCHITECTURE_DESIGN.md`

## 개요

옵션 A에 따라 FastAPI(uvicorn)와 aiohttp Socket.IO를 `asyncio.run(run_server)` 메인 루프 위에서 백그라운드 태스크로 기동해, grpc aio PollerCompletionQueue가 여러 이벤트 루프에 묶이지 않도록 했다. Windows `SelectorEventLoop` 정책은 기존 `main.py` import 시점 설정을 그대로 따른다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `sip-pbx/src/main.py` | 수정 | `_sip_pbx_embedded_http_ws`, `_log_asyncio_grpc_baseline`; 임베디드 시 `uvicorn.Server`·`start_server` 태스크; `finally`에서 API→WS→SIP 종료 순서 | `SIP_PBX_EMBEDDED_API` 롤백 |
| `sip-pbx/src/websocket/server.py` | 수정 | `_schedule_emit_on_ws_loop`, `stop_websocket_server`, runner/site 전역·`start_server` finally 정리 | |
| `sip-pbx/docs/reports/2026-04/2026-04-14_1830_GRPC_MULTI_LOOP_ARCHITECTURE_DESIGN.md` | 수정 | §7 구현 요약·상태 갱신 | |

## 주요 결정 사항

- 기본은 임베디드(`SIP_PBX_EMBEDDED_API` 미설정 또는 truthy). PoC·회귀 시 `0`/`false`/`legacy` 등으로 이전 스레드 모드 복구.
- `sip_internal_http` 는 별도 스레드 유지(2차 검토).

## 잔여 과제

- Windows에서 장시간 부하 후 10035·STT emit 유실 모니터링.
