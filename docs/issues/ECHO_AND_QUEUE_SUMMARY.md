# 에코 처리 및 TTS/STT 큐 안정화 요약

**날짜**: 2026-03-09

---

## 1. 에코 처리 (TTS 중 STT 차단 없음)

### 1.1 방향

- **TTS 재생 중 STT를 차단하지 않음** (바지인·자연스러운 대화 유지).
- **WebRTC AEC**로 스피커→마이크 에코만 제거.

### 1.2 WebRTC AEC 요약

- **역할**: Far-end(TTS 재생 신호)를 참조로 두고, Near-end(마이크 입력)에서 에코 성분을 빼서 **사용자 음성만** STT로 전달.
- **특징**: 실시간·저지연, double-talk 대응, 비선형 왜곡 일부 보정(AEC3).
- **Python**: `aec-audio-processing` 등으로 16kHz 모노 스트림 처리 가능.

### 1.3 연동 구조 (설계)

- **Far-end 버퍼**: TTS PCM을 RTP 전송 직전에 ring buffer에 누적 (예: 200ms).
- **Near-end 처리**: Caller RTP → PCM 변환 후 `AEC.process_stream(near_end, far_end)` 호출.
- **출력**: AEC 출력만 `_pipecat_audio_queue`에 넣어 기존 Input Transport → STT 경로 유지.

### 1.4 문서

- **상세 설계**: `sip-pbx/docs/design/WEBRTC_AEC_DESIGN.md`
- 구현은 해당 문서의 “구현 단계”대로 진행하면 됨.

---

## 2. TTS → RTP 안정화 (적용 완료)

### 2.1 근본 원인

- RTP **패킷** 큐에 TTS가 한꺼번에 많은 패킷을 넣고, 발송 루프는 20ms당 1개만 전송 → 큐 적체·버스트·간격 이탈.

### 2.2 적용한 방식

- **PCM 큐** (`_pipecat_pcm_queue`, maxsize=30): TTS는 **PCM 청크만** 넣음.
- **단일 발송 루프** (`_pipecat_tts_sender_loop`):
  - PCM 청크 1개 꺼냄 → RTP 패킷들로 변환 → **패킷마다** sendto 후 20ms sleep.
- 효과: RTP 버스트 제거, 20ms 간격 유지, 유실·지터 감소.

### 2.3 코드

- `sip-pbx/src/media/rtp_relay.py`
  - `enable_pipecat_mode()`: `_pipecat_pcm_queue` 생성, `_pipecat_tts_sender_loop` 태스크 시작.
  - `send_audio_to_caller()`: `_pipecat_pcm_queue.put_nowait(pcm_data)` (가득 시 1청크 드롭 후 로깅).
  - `_pipecat_tts_sender_loop()`: PCM get → build_packets → 패킷당 send + sleep(0.02).

---

## 3. STT 입력 큐 검토 (반영 완료)

### 3.1 구조

- **생산자**: RTP 콜백 → PCM 변환 → `_pipecat_audio_queue.put_nowait`.
- **소비자**: `get_caller_audio_stream()` → pipeline.

### 3.2 결론

- 단일 생산자·단일 소비자로 구조는 적절.
- RTP 콜백은 동기이므로, 가득 찼을 때는 **드롭 + 로깅**이 맞음 (블로킹 불가).

### 3.3 변경 사항

- **QueueFull 시 로깅**: `stt_input_queue_full_dropping` 이벤트 추가 (한 통화당 한 번만 경고).

---

## 4. 문서 위치

| 항목 | 문서 |
|------|------|
| WebRTC AEC | `docs/design/WEBRTC_AEC_DESIGN.md` |
| TTS/STT 큐 | `docs/design/TTS_RTP_AND_STT_QUEUE_DESIGN.md` |
| 요약 | `docs/issues/ECHO_AND_QUEUE_SUMMARY.md` |
