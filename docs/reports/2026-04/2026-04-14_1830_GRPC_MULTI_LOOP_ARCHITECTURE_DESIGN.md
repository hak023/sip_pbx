## 메타

- 작성일: 2026-04-14
- 상태: 옵션 A **구현 완료** (기본값). 레거시 스레드 모드는 환경변수로 선택 가능.
- 관련: Windows `BlockingIOError` 10035, `grpc._cygrpc.aio.PollerCompletionQueue`, 다중 asyncio 이벤트 루프

## 1. 현상과 질문에 대한 답

**“소켓 동시 사용 문제냐?”**  
부분적으로는 맞다. 다만 애플리케이션이 같은 RTP/SIP 소켓을 두 스레드가 잡는 문제가 아니라, **grpc Python aio가 프로세스 단위로 공유하는 완료 큐(내부 알림용 소켓)** 에 대해 **서로 다른 `asyncio` 이벤트 루프가 각각 `add_reader`를 걸고**, 완료 바이트를 **한 루프만 읽고 나머지는 빈 소켓을 읽다 `WSAEWOULDBLOCK`(10035)** 가 나는 **경쟁(race)** 에 가깝다. API는 이미 `200 OK`로 끝날 수 있다.

## 2. 목표 (구조 개선이 해결해야 할 것)

| 목표 | 설명 |
|------|------|
| G1 | **grpc aio가 바인딩되는 이벤트 루프를 사실상 하나로 수렴**시켜 PollerCompletionQueue 다중 구독을 제거한다. |
| G2 | Windows에서 **UDP SIP용 `SelectorEventLoop`** 요구를 유지한다 (기존 `main.py` 정책). |
| G3 | **FastAPI·WebSocket**과 **SIP/AI 초기화**가 동일 프로세스에서 동작 가능하게 유지한다. |
| G4 | 장애 시 **원인 추적 가능한 로그**와 롤백 가능한 단계적 전환이 가능하다. |

## 3. 설계 옵션 (택·조합)

### 옵션 A — 단일 이벤트 루프에서 HTTP·WS·SIP (권장 1순위)

**아이디어:** `uvicorn`을 **별 스레드 + `uvicorn.run`** 이 아니라, **이미 돌고 있는 메인 `asyncio` 루프** 위에서 ASGI 서버를 띄운다.

- **구현 스케치:** `uvicorn.Server` + `uvicorn.Config`를 메인 루프에서 `await server.serve()`를 **백그라운드 태스크**로 실행하거나, `hypercorn` 등 동일 패턴.
- **WebSocket:** 동일 루프에서 별 태스크로 `websockets`/`uvicorn`의 WS 라우트 통합.
- **장점:** grpc·`httpx`·Google 클라이언트가 한 루프에만 붙음 → **본 이슈 근본 제거**.
- **리스크:** SIP·AI 기동 순서와 **서버 종료 시 cancel 순서** 설계 필요 (기존 “스레드로 분리해 pending task 방지” 주석과 트레이드오프). **Graceful shutdown** 문서화 필수.

### 옵션 B — API(및 선택적 WS) 별 프로세스

**아이디어:** `127.0.0.1:8000` API만 **자식 프로세스**로 실행. PBX 프로세스는 SIP·내부 HTTP 릴레이만.

- **장점:** 프로세스당 루프 1개 → grpc 충돌 없음. 구현 단순.
- **리스크:** `CallManager`/`get_vector_db` 등 **공유 메모리 객체**는 IPC·HTTP로만 접근해야 함. 현재 “인프로세스 주입” 패턴과 **맞물림 검토** 필요.

### 옵션 C — grpc 사용 경로만 메인 루프로 직렬화 (프록시)

**아이디어:** API 스레드의 루프는 유지하되, **STT/TTS/LLM 등 grpc 호출만** `asyncio.run_coroutine_threadsafe` 또는 **전용 큐 + 메인 루프 워커**에서 실행.

- **장점:** SIP/uvicorn 구조 변경 최소.
- **리스크:** **모든 grpc 진입점**을 빠짐없이 옮겨야 하고, 타임아웃·취소·백압 설계가 복잡하다.

## 4. 권장 로드맵 (단계)

1. **현 상태 계측**  
   - 어떤 스레드에서 어떤 루프가 돌고 있는지(메인 / API / WS) 한 페이지로 정리.  
   - `grpcio` 버전·`google-cloud-*` 버전 고정.

2. **PoC: 옵션 A의 일부**  
   - API만 먼저 메인 루프에 붙이고, WS는 잠시 기존 스레드 유지 시 **충돌이 줄는지** 확인 (완전 제거는 아닐 수 있음).  
   - 이후 WS도 동일 루프로 이전.

3. **옵션 A 완료 시**  
   - `main.py`의 API·WS **스레드 기동 제거**, `lifespan`/취소 순서로 “destroyed but pending” 재발 방지.

4. **옵션 A가 SIP 타이밍과 충돌할 경우**  
   - 옵션 B로 API만 분리하고, 내부는 기존 `SIP_MESSAGE_RELAY` 패턴처럼 **HTTP 브리지**로 통일.

## 5. 비권장·보조

- **grpcio만 올려서 끝**내기: 증상 완화에는 도움이 될 수 있으나 **다중 루프 구조가 남으면 재발 가능** (보조책).
- **예외만 삼키기:** 로그 노이즈는 줄어도 **경쟁 상태 자체는 남는다**.

## 6. 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `sip-pbx/docs/reports/2026-04/2026-04-14_1830_GRPC_MULTI_LOOP_ARCHITECTURE_DESIGN.md` | 수정 | 옵션 A 구현 요약 §7 반영 | 구현 반영 |
| `sip-pbx/docs/reports/2026-04/2026-04-14_1716_GRPC_SINGLE_LOOP_OPTION_A_IMPL.md` | 추가 | 옵션 A 구현 리포트 | 설계대로 |

## 7. 구현 요약 (2026-04-14)

| 항목 | 내용 |
|------|------|
| 진입점 | `src/main.py` 의 `run_server()` — `asyncio.create_task(uvicorn.Server.serve())`, `create_task(websocket.server.start_server)` |
| 계측 | `start_async_logging` 직후 `asyncio_main_loop_baseline` 로그 (`loop_id`, `loop_class`, `thread_name`, `grpcio_version`, `sip_pbx_embedded_http_ws`) |
| 롤백 | `SIP_PBX_EMBEDDED_API=0` (또는 `false`/`no`/`off`/`legacy`) 시 기존처럼 API·WS 각각 **전용 스레드 + 별도 이벤트 루프** |
| 종료 순서 | `finally`: uvicorn `should_exit` → `wait_for(api_task)` → WS 태스크 `cancel`/`await` → SIP `stop` → 비동기 로깅 중지 |
| WS 정리 | `src/websocket/server.py` — `stop_websocket_server()`, `start_server` 의 `finally`에서 runner/site 정리·`_sio`/`_ws_loop` 해제 |
| emit | 동일 루프에서 호출 시 `create_task`, 타 스레드는 `run_coroutine_threadsafe` 유지 |
| **미포함(2차)** | `sip_internal_http` 의 `uvicorn.run` 스레드 — grpc 미사용 시 우선순위 낮음 |

## 잔여 과제

- 운영에서 10035 재발 여부 확인 후 `grpcio` 핀 고정 여부 검토.
- 필요 시 `sip_internal_http` 도 메인 루프에 embed 하거나 별 프로세스로 분리.
