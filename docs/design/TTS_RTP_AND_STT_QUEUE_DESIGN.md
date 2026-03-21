# TTS→RTP 및 STT 입력 큐 설계

**목적**: TTS 생성 패킷을 큐에 안정적으로 넣고, 20ms 간격으로 안정 전송. STT 입력도 동일 관점에서 검토.

---

## 1. TTS → RTP (적용 완료)

### 1.1 기존 문제

- **RTP 패킷 큐**에 TTS가 한 번에 많은 패킷을 `put_nowait` (예: 청크 1개 → 25패킷).
- 발송 루프는 20ms당 1개만 전송 → 큐 적체 → 버스트 전송·간격 이탈·유실.

### 1.2 해결: PCM 큐 + 단일 발송 루프

- **PCM 큐** (`_pipecat_pcm_queue`): TTS는 **PCM 청크만** 넣음 (RTP로 변환하지 않음).
- **단일 발송 루프** (`_pipecat_tts_sender_loop`):
  1. `get(pcm_queue)` → PCM 청크 1개
  2. `build_packets(pcm)` → RTP 패킷 리스트
  3. **패킷마다** `sendto()` 후 `await asyncio.sleep(0.02)` (20ms)
- 효과:
  - 큐에는 “청크”만 쌓이므로 버스트가 RTP 단이 아님.
  - 전송은 항상 한 스레드에서 20ms 간격만 사용 → 지터·이탈 최소화.
  - 큐 가득 시 PCM 청크 1개만 드롭하고 로깅.

### 1.3 새 TTS 시작 시 큐 플러시 (RTP 겹침 방지)

- **요구사항**: 새 TTS가 시작되면 **기존에 큐에 쌓인 TTS PCM을 버리고** 새 TTS만 RTP로 전송해야 함. 이전 발화를 멈추고 새 발화만 재생되도록.
- **구현**:
  - `LLMFullResponseStartFrame` 수신 시(Output Transport) `request_tts_flush()` 호출.
  - `request_tts_flush()`는 PCM 큐에 **플러시 센티넬**(`_TTS_FLUSH`)을 넣음.
  - 발송 루프(`_pipecat_tts_sender_loop`)에서 센티넬을 꺼내면 **큐를 전부 비움**(get_nowait 루프로 기존 PCM 폐기), 이후 정상적으로 새 TTS 청크만 처리.
- **효과**: RTP 스트림이 겹치지 않고, 새 응답만 순서대로 재생됨.

### 1.4 설정

- `_pipecat_pcm_queue`: `maxsize=150` (약 5초 분량, 인사말 버스트 시 empty_timeout/끊김 완화).
- 백로그 경고: qsize >= 120 시 1회 `rtp_tts_pcm_queue_backlog_high`.
- 드롭 시: `rtp_tts_packets_dropped` 및 `pipecat_pcm_queue_full_dropping` 로그.

---

## 2. STT 입력 (RTP → Pipecat)

### 2.1 현재 구조

- **생산자**: RTP 수신 콜백 (`_on_rtp_received`) → `rtp_to_pcm16k` → `_pipecat_audio_queue.put_nowait(pcm)`.
- **소비자**: `get_caller_audio_stream()` → `await queue.get(timeout=5.0)` → yield to pipeline.
- **큐**: `maxsize=1000` (약 20초 분량).

### 2.2 검토 결과

- **단일 생산자·단일 소비자**로 이미 안정적.
- RTP 콜백은 **동기** (소켓 이벤트)이므로, 여기서 `await put()`으로 블로킹하면 이벤트 루프가 막힘.
- 따라서 **가득 찼을 때**는 `put_nowait` 실패 → 드롭이 맞고, “안정적으로 넣기”는 **큐 크기**와 **드롭 로깅**으로 처리하는 것이 적절.

### 2.3 권장 사항

- **큐 크기 유지**: 1000 (STT 지연·타임아웃 여유 확보).
- **드롭 시 로깅**: `put_nowait` 실패 시 `QueueFull` 로그 추가 (현재는 `pass`만 있음).
- **옵션**: 나중에 “백프레셔”가 필요하면, RTP 수신 시 `asyncio.create_task(enqueue_with_put_timeout(pcm))`로 짧은 timeout `put()`을 시도한 뒤 실패 시 드롭하는 방식 가능 (순서 보장은 동일 태스크로 유지).

---

## 3. 요약

| 구간 | 조치 | 상태 |
|------|------|------|
| TTS → RTP | PCM 큐 + 단일 발송 루프(20ms 패이싱) | ✅ 적용 |
| TTS → RTP | 새 TTS 시작 시 PCM 큐 플러시 (RTP 겹침 방지) | ✅ 적용 |
| STT 입력 | 단일 큐·단일 소비자 유지, QueueFull 시 로깅 권장 | ✅ 검토 반영 |

---

## 4. 참고 코드 위치

- TTS PCM 큐·발송 루프: `sip-pbx/src/media/rtp_relay.py`
  - `enable_pipecat_mode()` → `_pipecat_pcm_queue`, `_pipecat_tts_sender_loop`
  - `send_audio_to_caller()` → `_pipecat_pcm_queue.put_nowait(pcm_data)`
  - **플러시**: `request_tts_flush()` → `_TTS_FLUSH` 투입; `_pipecat_tts_sender_loop`에서 센티넬 수신 시 큐 드레인
- 새 TTS 시 플러시 호출: `sip-pbx/src/ai_voicebot/pipecat/rtp_transport.py`  
  - `SIPPBXOutputTransport.process_frame`에서 `LLMFullResponseStartFrame` 수신 시 `await self._rtp_worker.request_tts_flush()` 후 `push_frame`
- STT 입력 큐: `_pipecat_audio_queue`, `get_caller_audio_stream()`, RTP 콜백 내 `put_nowait`.
