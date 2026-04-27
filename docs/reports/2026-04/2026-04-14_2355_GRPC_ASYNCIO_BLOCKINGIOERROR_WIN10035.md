## 메타

- 작성일: 2026-04-14
- 상태: 분석 완료 · 권장 방향 보강 (2026-04-14)
- 관련: Windows, grpcio asyncio, 다중 이벤트 루프

## 개요

터미널에 나온 `PollerCompletionQueue._handle_events` → `BlockingIOError: [WinError 10035]` 는 **애플리케이션 로직 버그라기보다 grpc Python 비동기 구현과 Windows·다중 asyncio 루프 조합**에서 흔히 보이는 현상이다. 직전 `GET /api/knowledge ... 200 OK` 처럼 **요청은 정상 완료**될 수 있다.

## 스택 의미

| 항목 | 설명 |
|------|------|
| `WinError 10035` | Windows `WSAEWOULDBLOCK` — 비블로킹 소켓에서 **지금 읽을 데이터가 없음** |
| `grpc/_cygrpc/aio/completion_queue.pyx` | grpc aio가 C 코어와 Python 루프를 깨우기 위한 **내부 알림 소켓**을 `recv` 하는 경로 |
| `Exception in callback` | asyncio 기본 예외 핸들러가 **콜백 안에서 터진 예외**를 stderr에 찍은 것 |

## 기술적 원인 (요약)

1. grpc Python aio는 프로세스 단위로 공유되는 **`PollerCompletionQueue`**(알림용 소켓 한 쌍)를 사용한다.
2. **서로 다른 스레드에서 각각 `asyncio` 이벤트 루프**가 돌면, 같은 FD에 `loop.add_reader`가 여러 번 걸릴 수 있다.
3. 완료 이벤트 한 번에 쓰인 바이트는 **한 루프의 콜백만 `recv`로 가져가고**, 다른 루프 콜백은 빈 소켓을 읽다 **EWOULDBLOCK / 10035**가 난다.
4. 이 프로젝트는 `main.py`에서 **메인 루프**, **uvicorn API 스레드**, **WebSocket 전용 스레드+`new_event_loop()`** 등으로 루프가 나뉘어 있어, Google STT/TTS/Gemini 등 **grpc를 쓰는 경로**와 맞물리기 쉽다.

즉, **“썬더링 허드” 경쟁 조건으로 인한 잡음 로그**에 가깝고, 동일 증상은 [grpc 이슈 #25364](https://github.com/grpc/grpc/issues/25364) 등에서 오래 논의되었다.  
**근본 원인은 “grpc aio가 가정하는 루프 모델”과 “현재 프로세스의 다중 asyncio 루프”의 충돌**이므로, 장기적으로는 **구조를 맞추는 쪽이 정석**이다.

## 권장 대응 (우선순위)

### 1) 정석: 구조적 변경 (충돌 제거)

**목표:** `google.generativeai` / `google-cloud-*` 등 **grpc aio를 쓰는 코드 경로가 참조하는 asyncio 이벤트 루프를 하나로 수렴**시킨다. (스레드마다 `new_event_loop()`로 API·WS를 띄우는 패턴과 정면으로 맞지 않게 한다.)

현재 `main.py` 기준으로 겹치는 축은 대략 다음과 같다.

| 구성요소 | 루프 위치 | 비고 |
|----------|-----------|------|
| SIP·AI 백그라운드 등 | 메인 `run_server` 루프 | `WindowsSelectorEventLoopPolicy` (UDP 안정화) |
| FastAPI / uvicorn | **별도 스레드**에서 `uvicorn.run` → **자체 루프** |
| WebSocket 서버 | **별도 스레드** + `asyncio.new_event_loop()` |

**가능한 구조 방향 (택일 또는 조합):**

- **A. API·WS를 메인 루프에서 기동**  
  메인 이벤트 루프 위에서 `uvicorn`을 `asyncio.create_task` + `Config`/`Server` 비동기 수명주기로 올리거나, ASGI를 **같은 루프에서** 구동해 HTTP·WS·SIP가 한 루프를 공유하게 한다. (기존 주석의 “태스크 생명주기 분리” 이슈는 `lifespan`/취소 순서 설계로 완화.)
- **B. API(및 필요 시 WS)를 별 프로세스로 분리**  
  동일 머신이라도 **프로세스 단위로 루프가 하나**이면 grpc 공유 큐와의 충돌이 사라진다. 내부는 `127.0.0.1`·공유 설정으로 붙인다.
- **C. grpc를 쓰는 경로만 메인 루프로 프록시**  
  HTTP 스레드는 얇게 두고, STT/TTS/LLM 등 실제 grpc 호출은 **큐 + `run_coroutine_threadsafe`** 등으로 메인 루프에 위임한다. 변경 범위는 큼.

Windows에서 SIP용 Selector 루프를 유지해야 하면, **A 또는 B가 현실적인 정석 축**이고, C는 점진적 중간책에 가깝다.

### 2) 보조: grpcio 업그레이드

라이브러리 쪽에서 `BlockingIOError`를 삼키거나 줄이는 패치가 올라오므로, **google-cloud-*와 호환되는 범위에서 `grpcio`를 올리는 것은 증상 완화**로는 유효하다. 다만 **다중 루프 구조가 그대로면 재발 가능**하므로 정석을 대체하지는 못한다.

### 3) 관측만 할 때

API·통화가 정상이면 **즉시 장애로 단정하지 않아도 된다**. 다만 **로그 노이즈와 잠재 경쟁은 구조적으로 남는다**.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `sip-pbx/docs/reports/2026-04/2026-04-14_2355_GRPC_ASYNCIO_BLOCKINGIOERROR_WIN10035.md` | 수정 | 권장 대응: 구조적 변경을 정석으로 명시, 보조책 재배치 | 설계 입장 반영 |
