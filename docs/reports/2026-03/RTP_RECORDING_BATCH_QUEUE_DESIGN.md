# RTP 녹음 인입: 배치 큐 + 단일 워커 설계·구현

- **작성일**: 2026-03-26  
- **상태**: 구현 반영 완료  
- **관련 코드**: `sip-pbx/src/sip_core/sip_call_recorder.py`, `sip-pbx/src/media/rtp_relay.py`  
- **배경**: `RTP_SENDER_PATH_STRUCTURE_REVIEW.md` §5.3 — 패킷마다 `asyncio.create_task(add_rtp_packet)` 로 인한 이벤트 루프 부하 완화

## 1. 문제

- RTP 릴레이에서 녹음이 켜진 경우, **패킷마다** `create_task`로 `add_rtp_packet` 코루틴을 스케줄하면 통화가 길어질수록 **태스크 생성·완료 오버헤드**가 누적된다.
- 송신 타이밍·다른 코루틴과 **동일 이벤트 루프**에서 경합할 여지가 있다.

## 2. 목표

- **단일 소비 태스크**만 유지하고, 인입은 **`put_nowait` 한 번**으로 끝낸다.
- 디코딩·버퍼 추가는 **동기 함수**로 묶어 워커(또는 폴백 경로)에서만 호출한다.

## 3. 설계

| 항목 | 값 / 동작 |
|------|-----------|
| 큐 | `asyncio.Queue(maxsize=32000)` (`_RTP_INGEST_QUEUE_MAX`) |
| 워커 | `_rtp_ingest_worker_loop` — `start_recording` 시 `_ensure_rtp_ingest_worker()`로 기동 |
| 배치 | 첫 패킷 `await get()` 후 `get_nowait()`로 최대 **64**개 (`_RTP_INGEST_BATCH_MAX`)까지 묶어 처리 |
| 양보 | 배치가 꽉 찼으면 루프당 `await asyncio.sleep(0)` 한 번 |
| 공개 API | `enqueue_rtp_packet(...)` — 이벤트 루프 스레드에서 호출, 성공 시 `True`, `QueueFull` 시 `False` + 경고 로그(최초 1회 상세) |
| 동기 코어 | `_ingest_rtp_packet_sync(...)` — 기존 `add_rtp_packet` 로직 |
| `add_rtp_packet` | 하위·테스트 호환: `await _ensure_rtp_ingest_worker()` 후 **동기 인입만** (큐 미경유). 릴레이는 `enqueue` 권장 |

### 3.1 워커 종료·폴백

- 워커가 **죽었거나 없을 때** `enqueue_rtp_packet`: 큐에 남은 항목을 `get_nowait()`로 **동기 drain**한 뒤 현재 패킷도 `_ingest_rtp_packet_sync` 처리 (패킷 유실 방지).
- 워커 **예외 종료** 시에도 동일하게 큐를 drain 시도 후 `finally`에서 태스크 핸들 정리.

### 3.2 백로그 관측

- 큐 크기가 `maxsize`의 약 80% 초과 시 `rtp_recording_ingest_queue_backlog_high` 경고(히스테리시스로 해제).

### 3.3 Graceful shutdown (프로세스·루프 종료)

| 단계 | 동작 |
|------|------|
| 플래그 | `_rtp_ingest_shutting_down = True` → `enqueue_rtp_packet`은 **큐 미사용**, 즉시 `_ingest_rtp_packet_sync` (센티넬 뒤에 RTP가 쌓이는 레이스 방지) |
| 종료 신호 | 워커가 살아 있으면 `await queue.put(None)` |
| 대기 | `asyncio.wait_for(worker_task, timeout=10)` 기본 |
| 타임아웃 | 워커 `cancel()` 후 `await task`, `_drain_rtp_ingest_queue_sync()` |
| 정리 | `finally`에서 `_rtp_ingest_queue = None`, 태스크 핸들 `None`, 플래그 해제 → 이후 `start_recording` 시 큐·워커 재생성 |

**진입점**

- `SIPCallRecorder.shutdown_rtp_ingest_worker(timeout=...)`
- `CallManager.shutdown_sip_recording_ingest()`
- `SIPEndpoint.shutdown_sip_recording_ingest()` (위임)

앱/서버의 **async 종료 훅**(lifespan, SIGTERM 핸들러에서 `create_task` 대신 await 가능한 경로)에서 `await endpoint.shutdown_sip_recording_ingest()` 호출을 권장한다.

## 4. 릴레이 변경

- `rtp_relay.py`: 녹음 분기에서 `create_task(add_rtp_packet)` 제거 → `sip_recorder.enqueue_rtp_packet(...)`; 성공 시에만 패킷 카운터 증가.

## 5. 트레이드오프·한계

- **지연**: 패킷이 큐에서 한 틱 더 머물 수 있으나, 녹음용 버퍼에는 일반적으로 허용 범위.
- **동시 shutdown**: 동일 루프에서 중첩 호출은 일반적으로 하지 않는다. 두 번째 호출은 큐/태스크가 이미 비어 있으면 즉시 반환한다.

## 6. 로그 키워드 (디버깅)

- `rtp_recording_ingest_worker_started` — 워커 기동  
- `rtp_recording_ingest_queue_backlog_high` — 적체  
- `rtp_recording_ingest_queue_full` — 드롭  
- `rtp_ingest_worker_fatal` — 워커 예외 종료  
- `rtp_ingest_queue_drain_sync_error` — drain 중 동기 인입 실패  
- `rtp_ingest_worker_shutdown_timeout` — 종료 대기 초과 후 cancel  
- `rtp_recording_ingest_worker_shutdown_complete` — shutdown 완료

---

*섹션 3.3·로그 키 갱신: 2026-03-26*
