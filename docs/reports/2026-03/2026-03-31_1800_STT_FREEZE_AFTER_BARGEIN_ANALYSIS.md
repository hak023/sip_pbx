# STT 동작 중단 분석 — 16:21:48 이후 (call_id: heZeOrmIli)

| 항목 | 내용 |
|---|---|
| 작성일 | 2026-03-31 18:00 |
| 상태 | 분석 완료 |
| 대상 콜 | `heZeOrmIli` (1004 → 1003) |
| 관련 파일 | `sip-pbx/logs/app.log`, `rag_processor.py`, `pipeline_builder.py`, `vad_wrapper.py` |

---

## 1. 증상 요약

| 시각 | 마지막 STT seq |
|---|---|
| 16:21:35 | seq=7 "에 대해서 알 수 있을까요?" |
| 16:21:48 이후 ~ 16:22:57 BYE | `transcription_frame_received` **0건** |

- 16:22:57 통화 종료 시 `vad_wrapper_cleanup` 로그: `total_speech_count=0, total_silence_count=0`  
  → VAD Wrapper가 `UserStartedSpeakingFrame`을 단 한 번도 수신하지 못한 상태
- `silence_streak` 지속 증가: `1526 → 1882 → 2632`  
  → 16:21:48 이후 PCM 큐에 TTS 오디오가 전혀 투입되지 않고 무음 연속

---

## 2. 타임라인

```
16:21:35.678  STT seq=7 ("에 대해서 알 수 있을까요?") RAG 도달
16:21:37      LLM 호출 시작 (generate_response)
16:21:48.007  Caller RTP → STT 입력 (packet_count=10300) — 마지막 stt_rtp 로그
16:21:48.090  [WARNING] tts_duration_short_possible_interrupt (25 frames, 2.259s)
              → TTS #1 (대기 안내 "정보를 확인 중입니다.") 조기 종료 의심
16:21:48.493  LLM 응답 수신 (generate_response elapsed=11.37s)
16:21:48.641  [WARNING] tts_duration_short_possible_interrupt (28 frames, 2.499s)
              → TTS #2 ("잠시만 기다려 주세요.") 조기 종료 의심
16:21:48.649  LLM 응답 TTS push 완료
16:21:48.094  pcm_chunk_gap_large — gap=46,356ms (46초) 큰 PCM 갭 경고
              → 이전 LLM 응답 완료 이후 TTS 입력이 46초간 없었음
--- 이후 transcription_frame_received 없음 ---
16:22:57.191  BYE 수신 → 통화 종료
```

---

## 3. 직접 원인 분석

### 3-1. `tts_duration_short_possible_interrupt` 2회 연속 발생

16:21:48에 **TTS 2개가 연속으로 `InterruptionFrame`(Barge-in)에 의해 조기 종료**된 것으로 추정됩니다.

Pipecat 파이프라인은 `allow_interruptions=True` 설정으로 구동 중이며, barge-in이 발생하면:
1. `StartInterruptionFrame` 발행 → TTS 중단
2. `UserStartedSpeakingFrame` 발행 → STT 처리 활성화

그런데 이 시점에 **LLM 응답 대기 중 TTS와 LLM 완료 후 TTS가 거의 동시에** 파이프라인에 투입되면서 두 TTS 모두 조기 종료됨.

### 3-2. STT 스트림 무응답 — VAD 이벤트 소실

`vad_wrapper_cleanup: total_speech_count=0` 이 핵심 증거입니다.

`VADWrapperProcessor`의 `_speech_count`는 `UserStartedSpeakingFrame`을 받을 때마다 증가합니다. 통화 4분여 동안 이것이 **0**이라는 것은 16:21:48 이후 `UserStartedSpeakingFrame`이 파이프라인에서 단 한 번도 생성·전달되지 않았음을 의미합니다.

`UserStartedSpeakingFrame` / `UserStoppedSpeakingFrame`의 실제 생성원은 **`GoogleSTTService`** (Pipecat 내장)입니다. 이 서비스가 스트리밍 인식 중 `UserStoppedSpeakingFrame`을 내보내야 STT 최종 결과도 생성됩니다.

### 3-3. 가능한 두 가지 시나리오

#### 시나리오 A: Google STT 스트리밍 세션 자동 종료 (가능성 높음)

Google Cloud STT 스트리밍 API는 최대 **5분** 동안만 단일 스트림을 유지할 수 있습니다. 이 통화에서:
- 통화 시작: 16:18:21
- STT 중단: 16:21:48
- 경과: **약 3분 27초**

5분 제한에는 못 미치지만, **Pipecat `GoogleSTTService` 내부에서 스트림 재연결 중 에러**가 발생했을 가능성이 있습니다. Pipecat은 스트림이 끊기면 자동 재연결을 시도하는데, 재연결 실패 시 STT 이벤트가 멈춥니다. 이 에러 로그가 `app.log`에는 남지 않았습니다(Pipecat 내부 에러 처리 때문).

#### 시나리오 B: Barge-in으로 인한 파이프라인 상태 불일치 (가능성 중간)

16:21:48에 barge-in이 연속 2회 발생하면서:
1. `InterruptionFrame` → Pipecat 파이프라인이 진행 중인 태스크를 일괄 취소
2. 취소 과정에서 `LLMFullResponseStartFrame` / `LLMFullResponseEndFrame` 쌍이 불균형해지거나
3. STT 서비스 내부의 speech_event 상태가 잘못 전환됨

이 경우 **파이프라인이 "TTS 재생 중" 상태로 잘못 고착**되어 이후 발화를 barge-in으로 처리하지 않고 무시했을 수 있습니다.

---

## 4. 증거 요약

| 증거 | 해석 |
|---|---|
| `tts_duration_short_possible_interrupt` 2회 연속 (16:21:48) | Barge-in 또는 조기 EndFrame으로 TTS 2개가 비정상 종료 |
| `silence_streak` 지속 증가 (1526→2632) | 이후 TTS 오디오가 전혀 투입되지 않음 |
| `vad_wrapper_cleanup: total_speech_count=0` | UserStartedSpeakingFrame이 단 한 번도 오지 않음 |
| `pcm_chunk_gap_large: gap_ms=46356` | 46초 PCM 갭 — 이전 LLM 응답이 끝난 후 다음 입력이 오지 않음 |
| `transcription_frame_received` 마지막: 16:21:35 | STT 최종 결과 생성 완전 중단 |
| `pipeline_transcript_flushed`: 발신자 마지막 발화 "에 대해서 알 수 있을까요?" | 실제로도 seq=7 이후 사용자 발화 없음 |

---

## 5. 추가 조사가 필요한 부분

현재 로그에는 다음 정보가 없습니다:

1. **Google STT 스트리밍 에러 로그** — Pipecat `GoogleSTTService` 내부 에러가 `app.log`에 기록되지 않음
2. **Pipecat `PipelineTask` 레벨의 TaskFrame 이벤트** — 파이프라인 전체 취소가 발생했는지 확인 불가
3. **16:21:48 직후 STT 서비스가 새 스트리밍을 시작했는지** 여부 (재시작 로그 없음)

---

## 6. 권장 대응 방안

### 즉시 적용 가능

**A. Google STT 스트리밍 에러 로깅 추가**

`factory.py`에서 `GoogleSTTService`를 생성할 때, 또는 `vad_wrapper.py`에서 `UserStartedSpeakingFrame`이 일정 시간(예: 60초) 동안 오지 않으면 경고 로그를 남기는 타임아웃 감지 로직 추가.

```python
# vad_wrapper.py 또는 rag_processor.py 내부에서
# 마지막 transcription 이후 N초 이상 침묵이면 경고
```

**B. STT 스트림 재시작 자동화**

Pipecat `GoogleSTTService`가 내부적으로 스트림을 끊고 재연결하는 로직이 있는지 확인하고, 없다면 워치독(watchdog) 태스크를 추가하여 N초 이상 `UserStartedSpeakingFrame`이 없으면 STT 서비스를 재시작.

**C. Barge-in 2회 연속 발생 방어 로직**

`_process_with_agent`에서 LLM 대기 TTS 완료 이벤트와 본 응답 TTS의 EndFrame 순서가 보장되도록 동기화 개선. 현재 `tts_duration_short_possible_interrupt`가 2회 연속 발생하는 구조적 원인 분석 필요.

---

## 7. 결론

**STT가 16:21:48 이후 멈춘 직접 원인은 명확하게 단정하기 어렵지만**, 가장 유력한 원인은:

> **16:21:48에 barge-in(InterruptionFrame)이 연속 2회 발생하면서 Pipecat `GoogleSTTService` 내부 스트리밍 세션이 비정상 종료되었고, Pipecat이 자동으로 재시작하지 못했거나 재시작 에러가 발생하여 이후 STT 이벤트가 생성되지 않았다.**

실제 사용자가 16:21:35 이후 더 이상 말하지 않았을 가능성도 있으나(통화 내용 전사 기준 seq=7이 마지막), `vad_wrapper_cleanup: total_speech_count=0`은 파이프라인 이상의 명확한 증거입니다.

추가 디버깅을 위해 **Pipecat 내부 STT 에러 로깅**과 **STT 이벤트 타임아웃 감지 로직**이 우선 필요합니다.
