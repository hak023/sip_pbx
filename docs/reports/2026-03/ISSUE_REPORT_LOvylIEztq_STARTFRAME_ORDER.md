# 이슈 점검 리포트: StartFrame not received yet (통화 LOvylIEztq)

**대상**
- `app.log` 3490–3658 (통화 LOvylIEztq, 2026-03-13 14:07:28–14:07:39)
- 터미널: `BargeInSuppressProcessor#0` — InputAudioRawFrame#77 처리 시 "StartFrame not received yet"

---

## 1. 요약

- **Input**: StartFrame 수신 후 **먼저 push**, 50ms 지연 후 오디오 루프 시작(수정 반영됨).
- **BargeInSuppress**: 맨 처음 도달한 프레임이 여전히 **OutputTransportMessageUrgentFrame** (passed_count=1).  
  그 후 **InputAudioRawFrame#77**까지 "StartFrame not received yet" 발생 → **StartFrame이 BargeInSuppress에 도달하기 전에** 다른 프레임과 오디오 프레임이 먼저 처리됨.
- **결론**: 50ms 지연만으로는 해결되지 않음. **VAD 래퍼**에서 `_vad.process_frame()` 호출 시 내부 VAD가 **OutputTransportMessageUrgentFrame**을 먼저 push하고, 그 다음에 래퍼가 `push_frame(StartFrame)`를 호출하는 구조라, BargeInSuppress에는 UrgentFrame이 먼저 도달함.

---

## 2. 로그 타임라인 (요약)

| 시각 | 이벤트 | 비고 |
|------|--------|------|
| 14:07:38.344 | input_transport_first_frame (StartFrame), input_transport_startframe_received | StartFrame 먼저 push, 오디오 루프 지연 시작 |
| 14:07:38.373 | **barge_in_suppress_passed** (frame_type=**OutputTransportMessageUrgentFrame**, passed_count=1) | BargeInSuppress에 **첫 번째로 도달한 프레임** = UrgentFrame |
| 14:07:38.410 | input_audio_loop_task_created | 50ms(66ms) 후 오디오 루프 시작 |
| 14:07:38.638 | input_audio_frame_to_pipeline (frame_count=1) | RTP→STT 경로 정상 |
| 14:07:38.839 | send_greeting_started, greeting_phase1_sent | 인사말 Phase1 전송 |
| 14:07:40.196 | (터미널) BargeInSuppressProcessor — InputAudioRawFrame**#77** "StartFrame not received yet" | StartFrame이 #77 전에 도달하지 못함 |

→ **StartFrame**은 Input → rec_input까지는 흐르지만, **vad_wrapped**에서 내부 VAD가 먼저 UrgentFrame을 push하고, 그 다음에 StartFrame이 push되므로, BargeInSuppress 입장에서는 **UrgentFrame이 먼저** 오고, StartFrame은 그 뒤(또는 아직 큐 뒤쪽)에 있음.  
또한 Pipecat 내부에서 **같은 링크로** VAD가 push하는 프레임이 우리가 push하는 StartFrame보다 먼저 전달될 수 있음.

---

## 3. 원인 정리

1. **Input**: StartFrame을 먼저 push하고 50ms 후 오디오 루프 시작 → 의도대로 동작.
2. **rec_input**: StartFrame을 그대로 하류(vad_wrapped)로 전달한다고 가정.
3. **vad_wrapped**:  
   - `await self._vad.process_frame(frame, direction)` 를 **먼저** 호출하고,  
   - 그 다음 `await self.push_frame(frame, direction)` 로 StartFrame을 전달.  
   - 내부 VAD(`_vad`)가 `process_frame(StartFrame)` 처리 중 **OutputTransportMessageUrgentFrame**(예: "TaskManager is still not initialized")을 **먼저** push하면,  
   - BargeInSuppress에는 **OutputTransportMessageUrgentFrame → (나중에) StartFrame** 순으로 도달.
4. **BargeInSuppress**:  
   - Pipecat 기본 클래스는 **StartFrame을 받아야** `_started`가 설정됨.  
   - 첫 프레임이 StartFrame이 아니므로 `_check_started()`에서 ERROR 로그 발생.  
   - StartFrame이 나중에 도달해도, 그때까지 쌓인 InputAudioRawFrame(#0~#77)이 먼저 처리되거나, 큐/스케줄링에 따라 StartFrame이 #77 이후에 처리될 수 있음.  
   - 그 결과 **InputAudioRawFrame#77** 처리 시점에도 `_started`가 False인 상태로 "StartFrame not received yet" 발생.

---

## 4. 권장 수정: VAD 래퍼에서 StartFrame 선행 전달

- **파일**: `sip-pbx/src/ai_voicebot/pipecat/processors/vad_wrapper.py`
- **내용**:  
  - **StartFrame**(및 필요 시 EndFrame, CancelFrame)은 **먼저** `await self.push_frame(frame, direction)` 로 하류에 보낸 뒤,  
  - `await self._vad.process_frame(frame, direction)` 호출.  
- **효과**:  
  - BargeInSuppress에는 **StartFrame이 OutputTransportMessageUrgentFrame보다 먼저** 도달.  
  - "StartFrame not received yet" 및 연쇄적인 하류(RAG/TTS) 문제 완화.

---

## 5. 검증 체크리스트 (수정 후)

| 항목 | 확인 방법 |
|------|-----------|
| BargeInSuppress 첫 프레임 | app.log에서 `barge_in_suppress_passed` **첫 건**의 frame_type이 **StartFrame** |
| 콘솔 에러 | "StartFrame not received yet" 미발생 |
| 인사말/TTS | greeting_phase1_sent 이후 packets_sent > 0, caller 측 인사말 수신 |

---

**작성일**: 2026-03-13  
**통화 ID**: LOvylIEztq
