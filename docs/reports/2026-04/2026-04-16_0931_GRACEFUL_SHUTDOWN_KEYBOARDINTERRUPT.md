## 메타

- 작성일: 2026-04-16 (로컬)
- 상태: 완료
- 관련: `sip-pbx/src/main.py`, Ctrl+C / SIGINT 종료

## 개요

Windows에서 Ctrl+C로 SIP PBX를 종료할 때 Uvicorn은 graceful shutdown 로그를 남긴 뒤 정상적으로 내려가지만, `asyncio.run()`이 이벤트 루프의 `select()` 대기나 러너 정리 단계에서 SIGINT 핸들러에 의해 **추가로** `KeyboardInterrupt`가 발생하면 `async def run_server` 안의 `except KeyboardInterrupt` 밖으로 전파되어 **traceback**이 출력되는 경우가 있다. 동기 진입점 `main()`에서 해당 예외를 흡수해 종료 코드 0으로 마치도록 했다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|------------|------|------|
| `sip-pbx/src/main.py` | 수정 | `asyncio.run(run_server(config))`를 내부 try/except로 감싸 `KeyboardInterrupt` 시 `return 0` | 설계대로 |

## 주요 결정 사항

- **왜 `run_server`만으로 부족한가**: 코루틴 본문과 `finally`에서 잡히지 않는 타이밍(러너·selector 경계)의 `KeyboardInterrupt`가 있을 수 있다.
- **왜 `main()`에서 처리하는가**: 프로세스 진입점에서 한 번만 처리하면 플랫폼별 루프 동작과 무관하게 사용자에게는 조용한 정상 종료로 보인다.
- **트레이드오프**: 진짜 버그로 인한 `KeyboardInterrupt`도 동일하게 삼킨다. 이 프로젝트에서는 서버 프로세스의 Ctrl+C가 주된 원인이므로 허용 범위로 본다.

## 잔여 과제 (선택)

- 이중 SIGINT·강제 종료 시 일부 리소스 정리 순서를 더 단단히 하려면 별도 시그널 정책(Unix `signal` 모듈 등) 검토 가능.
