# 로그 기반 점검: StartFrame 도달 순서 (g0gTRzvL1~)

**대상**: app.log 3237–3365, 콘솔 818–890 (통화 g0gTRzvL1~, 2026-03-13 13:39:57–13:40:07)

---

## 1. 추가 로그로 확인된 사항

### 1.1 Input 구간 (정상)

| 이벤트 | 시각 | 의미 |
|--------|------|------|
| input_transport_first_frame | 13:39:57.551 | frame_type=**StartFrame**, is_start_frame=true |
| input_transport_startframe_received | 13:39:57.551 | StartFrame 수신 후 오디오 루프 시작 |
| input_audio_loop_task_created | 13:39:57.551 | _read_audio_loop() 태스크 생성 |
| pipecat_input_transport_started | 13:39:57.551 | Input Transport 오디오 스트림 읽기 시작 |
| stt_path_rtp_first | 13:39:57.985 | RTP → 큐 첫 투입 |
| stt_path_queue_first | 13:39:57.985 | 큐 → Input 첫 소비 |
| input_audio_frame_to_pipeline | 13:39:57.985~ | frame_count 1, 2, … 200 |

→ **Input에는 StartFrame이 먼저 도달**했고, 이후 RTP→큐→파이프라인 경로도 정상 기동.

### 1.2 BargeInSuppress 구간 (문제)

| 이벤트 | 시각 | 의미 |
|--------|------|------|
| **barge_in_suppress_passed** | 13:39:57.555 | **frame_type=OutputTransportMessageUrgentFrame**, passed_count=**1** |

→ BargeInSuppress에 **맨 처음 도달한 프레임이 StartFrame이 아니라 OutputTransportMessageUrgentFrame**임.  
(같은 통화에서 콘솔에는 InputAudioRawFrame#201~218 에 대해 "StartFrame not received yet" 반복.)

### 1.3 RTP / TTS

- greeting_phase1_sent, rag_greeting_blocking_start 까지 기록됨.
- **rtp_tts_queue_empty_timeout**, **packets_sent: 0** 반복 → TTS→RTP 전송 0건.
- stt_path_queue_timeout (5초), packets_consumed_so_far: 219.

---

## 2. 추론: 프레임 도달 순서

1. **Source → Input**: StartFrame이 Input에 먼저 옴 (로그로 확인).
2. **Input → rec_input → vad_wrapped → barge_in_suppress**:  
   Input이 `push_frame(StartFrame)` 후 곧바로 `_start_audio_loop_if_needed()`로 **오디오 루프 태스크**를 만들고, 해당 태스크가 **InputAudioRawFrame**을 연속 push.
3. 파이프라인/러너 쪽에서 **OutputTransportMessageUrgentFrame**(VAD 등 제어/에러 메시지)이 별도 경로로 푸시될 수 있음.
4. 그 결과 **BargeInSuppress에는 StartFrame보다 OutputTransportMessageUrgentFrame(또는 InputAudioRawFrame)이 먼저 도달**할 수 있음.
5. Pipecat FrameProcessor는 **StartFrame을 먼저 받아야** `_started`가 설정됨.  
   → 첫 프레임이 StartFrame이 아니면 그 시점에 "StartFrame not received yet" 로그 발생, 이후 InputAudioRawFrame들도 동일 에러 반복.
6. RAGLLMProcessor도 StartFrame을 아직 받지 못한 상태에서 인사말 프레임을 받으면 동일 에러가 나며, TTS→RTP 경로가 활성화되지 않아 **packets_sent: 0**으로 이어짐.

정리하면, **super().process_frame() 호출만으로는 해결되지 않고, “StartFrame이 하류 프로세서에 **가장 먼저** 도달하도록” 하는 쪽 수정이 필요**함.

---

## 3. 적용한 수정: StartFrame 선행 전달

- **Input Transport** (`rtp_transport.py`):
  - StartFrame 수신 시 **먼저** `await self.push_frame(StartFrame)` 호출(오디오 루프 시작 전에 StartFrame 전달).
  - 그 다음 `asyncio.create_task(self._delayed_start_audio_loop(0.05))`로 50ms 지연 후 오디오 루프 시작.
  - `_delayed_start_audio_loop(delay)`에서 `await asyncio.sleep(delay)` 후 `_start_audio_loop_if_needed()` 호출.
- 목적: StartFrame이 rec_input → vad_wrapped → **barge_in_suppress**에 먼저 도달한 뒤 InputAudioRawFrame이 전달되도록 함.

---

## 4. 체크리스트 (수정 후 검증)

| 항목 | 확인 방법 |
|------|-----------|
| BargeInSuppress 첫 프레임 | app.log에서 barge_in_suppress_passed 첫 건의 frame_type이 **StartFrame** |
| 콘솔 에러 | "StartFrame not received yet" 미발생 |
| RTP 전송 | packets_sent > 0, rtp_tts_queue_empty_timeout 감소 또는 미발생 |
| 인사말 청취 | caller 측에서 인사말 음성 수신 |

---

**작성일**: 2026-03-13  
**통화 ID**: g0gTRzvL1~
