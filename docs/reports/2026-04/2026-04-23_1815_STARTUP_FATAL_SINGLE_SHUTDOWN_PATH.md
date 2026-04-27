## 개요

기동 실패(`startup_fatal_api_server_thread_failed` 등) 직후 로그에 `sip_server_stopped`만 보이고 `sip_shutdown_phase_complete` 등 **finally 정리 구간이 자연스럽지 않다**는 점을 점검했다. 원인은 **예외 처리기에서 `sip_endpoint.shutdown_async()`를 먼저 호출**한 뒤, 함수 말미 **finally에서 다시 호출**하는데, `shutdown_async`가 **첫 호출 후 idempotent no-op**이라 두 번째에서 `sip_shutdown_phase_complete` 로그가 나오지 않는 구조였다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|------------|------|------|
| `sip-pbx/src/main.py` | 수정 | CallManager 주입·embedder·API·WS 기동 실패 시 `shutdown_async` 선호출 제거 | 정리는 finally 단일 경로 |

## 주요 결정 사항

- SIP·임베디드 HTTP/WS 정리 순서는 기존 **finally 블록**이 담당하도록 통일한다. 이중 `shutdown_async`를 피해 관측 가능한 종료 로그가 한 번만 나가게 한다.
- `folder_id` 등으로 API import 단계에서 실패하는 경우에도 **동일 finally**가 실행되므로 SIP UDP·트래픽 로그 닫기가 한 경로로만 수행된다.

## 잔여 과제

- 기동 실패 원인(DB 스키마 등)은 별도 수정과 병행할 것.
