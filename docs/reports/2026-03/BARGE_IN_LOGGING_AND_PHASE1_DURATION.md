# Barge-in 로그 분석 가이드 및 Phase1 duration / TTS enable-disable 정리

## 1. 로그로 Barge-in 분석하기

### 1.1 추가된 로그 이벤트

| event | 의미 | 확인할 것 |
|-------|------|------------|
| `vad_interruption_absorbed` | VAD 래퍼에서 Interruption* 프레임 흡수 (하류/내부 VAD로 안 넘김) | `frame_type`, `direction` — 업스트림이면 STT→Task 쪽 차단 |
| `barge_in_suppress_blocked` | BargeInSuppressProcessor에서 Interruption* 차단 | `frame_type`, `direction`, `suppressed_count` — 같은 시각에 "Barge-in detected" 나오면 경로 이탈 가능성 |
| `barge_in_suppress_interruption_passed` | **(에러)** Interruption*이 TTS로 전달됨 (나오면 안 됨) | 차단 로직 버그 |
| `output_interruption_frame_absorbed` | Output(RTP 직전)에서 Interruption* 흡수 | **이미 TTS를 지났음** — 이 로그가 나오면 TTS는 이미 "Barge-in detected" 했을 수 있음 |
| `notifier_endframe_processed` | TTS 완료 시점, 해당 구간 누적 재생 길이 | `duration_sec`, `audio_frame_count` |
| `tts_duration_short_possible_interrupt` | TTS 재생이 2.5초 미만·프레임 수 적음 (끊김 의심) | 직전에 `barge_in_suppress_blocked` 없으면 Interruption이 TTS까지 도달한 것 |
| `phase1_duration_short_possible_interrupt` | Phase1 재생이 예상(estimated_full_sec)의 80% 미만 | Phase1 인사말이 Interruption으로 조기 종료됐을 가능성 |
| `greeting_phase_gap_tts_complete_signalled` | Phase1 대기 후 Phase2 전송 직전 | `phase1_audio_sec`, `estimated_full_sec`, `phase1_short` |

### 1.2 "Barge-in detected, stopping TTS" 가 나올 때 확인 순서

1. **같은 타임스탬프 근처**에 `barge_in_suppress_blocked` 또는 `vad_interruption_absorbed` 가 있는지 확인.
   - **있음** → 우리 쪽에서는 차단했지만, **다른 경로**(예: Task가 파이프라인 외부에서 TTS 큐에 직접 넣는 등)로 InterruptionFrame이 TTS에 들어갔을 가능성.
   - **없음** → Interruption*이 우리 프로세서들을 **거치지 않고** TTS에 도달한 경로가 있음 (Pipecat Task/파이프라인 구조 재확인 필요).

2. **Phase1이 1.75s 등으로 짧을 때**
   - `notifier_endframe_processed` 의 `duration_sec` 가 2.5 미만이면 `tts_duration_short_possible_interrupt` 가 떠야 함.
   - `greeting_phase_gap_tts_complete_signalled` 에서 `phase1_short=True` 이고 `phase1_audio_sec` < `estimated_full_sec` 이면 Phase1이 예상보다 짧게 끝난 것.
   - 그 직전에 `barge_in_suppress_blocked` 가 없으면, Interruption*이 TTS까지 도달해 TTS가 조기 종료한 것으로 보는 것이 타당함.

3. **call_id** 로 한 통화만 필터해 시간순으로 정렬하면,  
   `vad_interruption_absorbed` → `barge_in_suppress_blocked` → (없으면) → `Barge-in detected` → `output_interruption_frame_absorbed` 순서로 추적 가능.

---

## 2. TTS "barge-in enabled" / "barge-in disabled" 로직

### 2.1 로그 출처

- **"TTS started, barge-in disabled"**, **"TTS ended, barge-in enabled"**, **"Barge-in detected, stopping TTS"**, **"TTS stop requested"**, **"TTS stopped"** 는 **우리 코드가 아니라 Pipecat 또는 Google TTS 서비스** 내부에서 출력하는 로그입니다.
- sip-pbx 코드베이스에는 해당 문자열이 없으며, Pipecat/Google TTS 쪽에서 세그먼트 단위로 barge-in 상태를 로그로 남기는 것으로 보입니다.

### 2.2 동작 해석 (정상 여부)

- **TTS started, barge-in disabled**  
  해당 TTS 세그먼트 재생을 시작할 때, 그 구간 동안 barge-in을 “끔” 상태로 둔다는 의미로 해석할 수 있습니다.
- **TTS ended, barge-in enabled**  
  해당 세그먼트 재생이 끝나면 다시 barge-in을 “켬” 상태로 둔다는 의미로 해석할 수 있습니다.

즉, **세그먼트 시작 시 disable, 세그먼트 종료 시 enable** 하는 것은 “한 구간만 안 끊기게 했다가 다시 끊기 허용”으로 보는 것이 자연스럽고, 설계상 그렇게 동작하는 것일 수 있습니다.

- 다만 우리 **의도**는 **바지인 자체를 끈 상태**(`allow_interruptions=False`, `enable_barge_in=False`)이므로,  
  **어디선가 InterruptionFrame이 TTS까지 전달되어** "Barge-in detected, stopping TTS"가 나오는 것이 문제입니다.
- 따라서 **로직이 “정상”인지**보다는, **InterruptionFrame이 TTS에 도달하지 않도록** 우리 쪽에서만 완전히 차단하는지가 핵심입니다.  
  위 1.2의 로그로 “TTS까지 도달한 Interruption 경로”가 있는지 확인하면 됩니다.

---

## 3. Phase1 인사말 duration 1.75s (끊김) 와 Interruption

### 3.1 현상

- Phase1 인사말이 **전체 재생되지 않고** 약 **1.75s** 에서 끊김.
- 정상이면 **3초 이상** (글자 수 기준 예상 재생 시간) 되어야 함.

### 3.2 원인 방향

- TTS가 **InterruptionFrame** (또는 동일 효과의 신호)을 받으면 재생을 중단하고,  
  그 시점까지의 재생 길이만 `last_tts_duration_sec` 등으로 전달됩니다.
- 따라서 **Phase1 구간에 Interruption*이 TTS까지 도달**하면:
  - Phase1이 조기 종료되고,
  - `notifier_endframe_processed` 의 `duration_sec` 가 1.75s 같이 짧게 나오며,
  - Phase2가 그 뒤에 이어서 시작됩니다.

### 3.3 적용한 대응

1. **VAD 래퍼**  
   - Interruption* (InterruptionFrame, **InterruptionTaskFrame**, StartInterruptionFrame, StopInterruptionFrame) 수신 시  
     `enable_barge_in=False` 이면 **내부 VAD로 넘기지 않고** 하류로도 보내지 않음.  
   - **InterruptionTaskFrame** 도 여기서 차단해, STT→Task 로 가는 경로를 막음.

2. **BargeInSuppressProcessor**  
   - 업스트림/다운스트림 모두에서 Interruption* 차단,  
     `barge_in_suppress_blocked` 로 **매 건** 로그 (분석용).

3. **Phase1 짧을 때 로그**  
   - `tts_duration_short_possible_interrupt`: Notifier에서 재생 길이 2.5초 미만·프레임 수 적을 때 경고.  
   - `phase1_duration_short_possible_interrupt` / `greeting_phase_gap_tts_complete_signalled` 의 `phase1_short`:  
     Phase1 재생이 예상(estimated_full_sec)의 80% 미만일 때 Phase1 끊김 가능성 경고.

4. **Output**  
   - Interruption* 은 RTP로 보내지 않고 흡수.  
   - 단, Output은 **TTS 이후**이므로, 여기서 흡수되는 건 “이미 TTS를 지난 뒤”이며,  
     **Barge-in detected 를 막으려면 반드시 TTS 직전(또는 업스트림)에서 차단해야 함.**

### 3.4 로그로 확인할 것

- Phase1 구간(인사말 첫 TTS)에서:
  - `barge_in_suppress_blocked` / `vad_interruption_absorbed` 가 **선으로** 나오고,
  - 그 다음에 `notifier_endframe_processed` 의 `duration_sec` 가 2.5 이상으로 나오면  
    → Phase1이 끊기지 않고 재생된 것으로 볼 수 있음.
- 반대로 **"Barge-in detected"** 직전에 `barge_in_suppress_blocked` 등이 없으면  
  → Interruption이 우리 프로세서를 거치지 않고 TTS에 도달한 경로가 있다는 뜻이므로,  
  Pipecat Task/파이프라인/큐 구조를 추가로 확인해야 합니다.

---

## 4. 요약

- **분석**: `vad_interruption_absorbed`, `barge_in_suppress_blocked`, `output_interruption_frame_absorbed`,  
  `tts_duration_short_possible_interrupt`, `phase1_duration_short_possible_interrupt`,  
  `greeting_phase_gap_tts_complete_signalled`(phase1_short) 로 **Interruption 경로**와 **Phase1 끊김** 여부를 추적.
- **TTS enable/disable**: Pipecat/Google TTS 내부 동작으로 보이며, 우리는 **Interruption*을 TTS 직전·업스트림에서 완전히 차단**하는지가 핵심.
- **Phase1 1.75s**: Interruption*이 TTS까지 도달해 조기 종료된 경우일 수 있으므로,  
  위 로그로 같은 시각에 차단 로그가 있는지 확인하면 원인 방향을 좁힐 수 있음.
