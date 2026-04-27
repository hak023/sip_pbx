## 메타

- 작성일: 2026-04-14 (로컬)
- 상태: 수정 완료
- 관련: 임베디드 API `uvicorn.Config`, uvicorn 0.24.x

## 개요

임베디드 FastAPI 기동 시 `uvicorn.Config(..., handle_signals=False)` 를 넘겼으나, 설치된 **uvicorn 0.24.0** 의 `Config.__init__` 시그니처에 `handle_signals` 가 없어 `TypeError` 로 기동이 중단되었다. 해당 인자를 제거했다. 메인 프로세스는 이미 `asyncio.run(run_server)` 로 시그널·종료 흐름을 갖는다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `sip-pbx/src/main.py` | 수정 | `uvicorn.Config` 에서 `handle_signals` 제거, 주석으로 버전 메모 | 설계대로 |

## 주요 결정 사항

- 런타임에 `inspect.signature` 로 분기할 수 있으나, 불필요한 복잡도를 피하고 **현재 지원 범위에 맞춘 최소 인자만** 전달한다. 이후 uvicorn 업그레이드 시 공식 문서에 맞춰 `handle_signals` 재도입을 검토할 수 있다.

## 잔여 과제

- 없음.
