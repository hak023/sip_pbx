# STT 동결 버그 분석 및 수정 — TTS 억제 구간 후 STT 재개 실패

- **작성일**: 2026-04-02 15:00
- **상태**: 수정 완료
- **대상 call_id**: `outbound-ob-34f23cd8-34334050`
- **관련 파일**: `sip-pbx/src/ai_voicebot/pipecat/processors/vad_wrapper.py`

---

## 1. 현상

- 아웃바운드 통화 수립 후 예외 발화(다른 사람의 음성)가 STT에 입력됨
- AI bot이 해당 발화에 적절히 응대하고 TTS를 출력함
- TTS 완료(`vad_stt_suppression_ended`) 이후 STT가 완전히 멈춤
- 30초 후 `stt_silence_watchdog_alert`, 80초 후 `stt_transcript_watchdog_alert` 발생
- RTP 오디오 패킷은 정상 수신 중(caller_audio_packets 계속 증가)

---

## 2. 근본 원인

### 버그: 억제 중에도 내부 VAD에 오디오 전달

**수정 전 코드** (`vad_wrapper.py` process_frame):

```python
# VAD 프로세서로 전달 (Interruption* 제외)
if self._vad:
    await self._vad.process_frame(frame, direction)  # ← 억제 여부와 관계없이 호출

# 오디오 프레임 처리
elif isinstance(frame, InputAudioRawFrame):
    ...
    if self._suppress_stt_during_tts and self._tts_sync_context.get("tts_playing"):
        ...
        return  # ← VAD는 이미 호출된 후
```

**문제 흐름**:
1. TTS 재생 중 억제 구간에서도 내부 VAD(`SileroVAD`)에 `InputAudioRawFrame`이 전달됨
2. VAD가 발화를 감지하면 `UserStartedSpeakingFrame`을 하류(Google STT)로 push
3. STT는 `UserStartedSpeakingFrame`을 받아 스트리밍 세션을 시작하려 함
4. 그러나 실제 오디오 데이터(`InputAudioRawFrame`)는 억제로 STT에 전달되지 않음
5. STT gRPC 스트리밍 큐가 비어있어 스트리밍이 시작되지 않고 polling 루프만 돌음
6. TTS 억제 종료 후에는 VAD가 이미 발화 중 상태로 인식하여 새로운 `UserStartedSpeakingFrame`을 push하지 않음
7. STT가 새 스트리밍 세션을 시작하지 못해 영구적으로 멈춤

### 추가 문제: 워치독 오발령

억제 구간에서 `_last_speech_event_time`이 갱신되지 않아, 억제 20초 이상 지속 시 STT 동결 워치독이 오발령.

---

## 3. 수정 내용

### `vad_wrapper.py` 변경

**1) VAD 호출 순서 변경**: VAD 호출을 `InputAudioRawFrame` 억제 로직 이후로 이동
- 억제 중 `return`이 발생하면 VAD 호출 코드(맨 아래)에 도달하지 않음
- 억제가 아닌 경우만 VAD에 오디오 전달

**2) 워치독 오발령 방지**: 억제 중 `_last_speech_event_time`을 현재로 갱신
```python
# 워치독 기준 시각을 현재로 갱신 — 억제 구간을 무음으로 오판하지 않도록
self._last_speech_event_time = now_m
```

**3) 억제 종료 후 VAD 리셋**: 억제가 끝날 때 VAD가 발화 중이었다면 `UserStoppedSpeakingFrame`을 전달해 VAD 상태를 "무음"으로 리셋
```python
if self._vad and self._is_speaking:
    await self._vad.process_frame(UserStoppedSpeakingFrame(), direction)
    self._is_speaking = False
```

---

## 4. 수정 후 기대 동작

```
TTS 시작
 └─ tts_playing = True
 └─ [억제 구간] InputAudioRawFrame → VAD 전달 차단, STT 전달 차단
 └─ _last_speech_event_time 매 프레임마다 갱신 (워치독 오발령 방지)

TTS 종료
 └─ tts_playing = False (0.3초 버퍼 후)
 └─ vad_stt_suppression_ended 로그
 └─ VAD 상태 리셋 (UserStoppedSpeakingFrame 전달)

억제 종료 후 첫 오디오
 └─ VAD에 InputAudioRawFrame 전달 → 발화 감지 시작
 └─ UserStartedSpeakingFrame → STT로 전달
 └─ 이후 오디오도 정상 STT 전달 → 정상 인식
```

---

## 5. 로그 포인트

| 이벤트 | 의미 |
|--------|------|
| `vad_stt_suppressed_tts_playing` | 억제 중 (VAD+STT 모두 차단) |
| `vad_stt_suppression_ended` | 억제 종료, VAD+STT 재개 |
| `vad_stt_suppression_vad_reset` | 억제 종료 후 VAD 리셋 완료 |
| `vad_speech_started` | 억제 종료 후 새 발화 감지 (정상 복구 확인) |
