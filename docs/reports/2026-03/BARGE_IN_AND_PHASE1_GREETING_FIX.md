# Barge-in 반복 발생 및 Phase1 인사말 누락 원인·수정

**일자**: 2026-03-12

---

## 1. "Barge-in detected, stopping TTS" 가 계속 발생하는 이유

### 1.1 가능 원인

1. **Pipecat Task 경로**  
   STT가 `InterruptionTaskFrame`을 푸시하면 Pipeline Task가 이를 받아 `InterruptionFrame`으로 변환한 뒤 **다운스트림으로 전달**할 수 있음. 이때 경로가 우리가 둔 `BargeInSuppressProcessor`를 거치지 않고 TTS로 직접 갈 수 있음.

2. **프레임 타입**  
   Pipecat 쪽에서 `InterruptionFrame`의 **서브클래스**를 쓰는 경우, `isinstance(frame, InterruptionFrame)`만으로는 걸리지 않을 수 있음.

3. **Output 전달**  
   `SIPPBXOutputTransport`가 `StartInterruptionFrame` 수신 시 로그만 남기고 **그대로 `push_frame()`** 해서, 마지막 구간에서조차 차단되지 않았음 (이미 TTS는 중단된 뒤일 수 있으나, 동일 프레임이 다시 전달되는 경로 차단용).

### 1.2 적용한 수정

| 위치 | 내용 |
|------|------|
| **rtp_transport.py (SIPPBXOutputTransport)** | `StartInterruptionFrame` 및 `InterruptionFrame` / `InterruptionTaskFrame` / `StopInterruptionFrame` 수신 시 **전달하지 않고 흡수** (로그 후 `return`). |
| **barge_in_suppress.py** | `isinstance(...)`에 더해 **`"Interruption" in type(frame).__name__`** 조건 추가 → Pipecat 서브클래스까지 차단. |

이후에도 로그가 나오면, Pipecat 내부에서 TTS가 **다른 경로**(예: Task → TTS 직접 주입)로 interruption을 받는지 여부를 추가로 확인해야 함.

---

## 2. Phase1 인사말에서 "AI 비서입니다" 가 안 들리는 이유

### 2.1 가능 원인

1. **템플릿 내용**  
   VectorDB `tenant_config.greeting_templates`에 **짧은 문장만** 들어 있는 경우  
   (예: `"안녕하세요. 무엇을 도와드릴까요?"`)  
   → `get_random_greeting_template()`이 그대로 반환하고, 그 문장에는 "AI 비서입니다"가 없음.

2. **Barge-in으로 TTS 중단**  
   전체 인사말이 `"안녕하세요. AI 비서입니다. 무엇을 도와드릴까요?"`인데,  
   재생 중간에 바지인으로 TTS가 끊기면 "안녕하세요." 까지만 들리고,  
   이후 다른 문장(예: Phase2 또는 다음 턴)에서 "무엇을 도와드릴까요?"만 들릴 수 있음.  
   → 사용자 인상은 "안녕하세요. 무엇을 도와드릴까요?"만 들린 것처럼 보일 수 있음.

3. **fallback 문구**  
   `greeting`이 비었을 때/예외 시 사용하던 fallback이  
   `"안녕하세요. 무엇을 도와드릴까요?"` 로만 되어 있어,  
   "AI 비서입니다"가 포함된 문장이 나갈 기회가 없었음.

### 2.2 적용한 수정

| 위치 | 내용 |
|------|------|
| **rag_processor.py** | `phase1_text` fallback을 `"안녕하세요. AI 비서입니다. 무엇을 도와드릴까요?"` 로 통일. 예외 시 fallback도 동일 문구로 변경. |
| **langgraph/agent.py** | `generate_greeting()`에서 `get_random_greeting_template()` 결과를 쓸 때, **길이 ≥ 25자**이고 **"비서" 또는 "상담원"**이 포함된 경우에만 템플릿 사용. 그 외(짧은 문장·중간 문구 없음)는 `"안녕하세요. {org_name} AI 통화 비서입니다. 무엇을 도와드릴까요?"` 반환. |

이렇게 하면:

- DB에 짧은 인사말만 있어도, 기본적으로는 "AI 비서입니다"가 들어간 문장이 나가고  
- Barge-in 수정과 함께 적용하면, Phase1이 중간에 잘리지 않아 인사말 전체가 들릴 가능성이 높아짐.

---

## 3. Phase1 인사말이 "잘려서" 출력되는 경우 (duration 2.65s 등)

### 3.1 현상

- 로그: `TTS synthesis done, audio_bytes: 115256` (약 3.6초 분량) 인데 `TTS ended, duration: 2.65s` 로만 기록됨.
- 사용자에는 Phase1 인사말 전체가 아니라 앞부분만 들림.

### 3.2 원인

1. **EndFrame이 오디오보다 먼저 도착**  
   TTS가 “합성 완료” 시점에 EndFrame을 보내면, 아직 파이프라인에 남아 있는 오디오 청크(예: 0.95초 분량)보다 EndFrame이 먼저 Notifier/Output에 도착할 수 있음.  
   → 그 시점의 `rtp_sent_sec` / `play_sec` 는 **부분 길이(예: 2.65초)** 만 반영됨.

2. **Phase2 대기가 그 부분 길이 기준**  
   `gap_sec = rtp_sent_sec + 1` (또는 `play_sec + 1`) 만 쓰면, 예: 2.65+1 = 3.65초만 대기함.  
   Phase1 전체는 약 3.6초인데, 남은 오디오가 RTP 큐에 있는 동안 Phase2 **StartFrame** 이 나가면, Output에서 `request_tts_flush()` 가 호출되어 **PCM 큐가 비워지고** 남은 Phase1 오디오가 버려짐.

3. **결과**  
   Phase1은 “2.65초만 재생된 것처럼” 끝나고, 그 뒤가 잘려서 들림.

### 3.3 수정 (rag_processor.py)

- Phase2 전송 전 대기 시간을 **Phase1 전체 예상 재생 시간 이상**으로 보장.
- `gap_sec = max(rtp_sent_sec, play_sec, estimated_full_sec) + _PHASE_GAP_BUFFER_SEC`  
  (`estimated_full_sec = len(phase1_text) / _TTS_CHARS_PER_SEC`).
- EndFrame이 일찍 와서 `rtp_sent_sec` 가 2.65초여도, `estimated_full_sec`(예: 28자/5.5 ≈ 5.1초)를 쓰므로 최소 약 6.1초 대기 후 Phase2 전송 → 남은 Phase1 PCM이 RTP로 다 나간 뒤 Phase2가 시작되도록 함.

---

## 4. 검증 방법

1. **Barge-in**  
   - 통화 후 로그에서 `Barge-in detected, stopping TTS` / `TTS stop requested` / `TTS stopped` 가 Phase1/Phase2 중에 나오는지 확인.  
   - `vad_barge_in_suppressed`, `output_interruption_frame_absorbed` 로그가 찍히는지 확인.

2. **Phase1 인사말**  
   - 로그 `rag_llm_greeting_phase1` / `greeting_phase1_sent` / `tts_text_input` 에서  
     `text` 가 `"안녕하세요. ... AI 비서입니다. 무엇을 도와드릴까요?"` (또는 org_name 포함 풀 문장)인지 확인.  
   - 실제 통화에서 "안녕하세요. [기관명/]AI 비서입니다. 무엇을 도와드릴까요?" 가 끝까지 재생되는지 확인.
