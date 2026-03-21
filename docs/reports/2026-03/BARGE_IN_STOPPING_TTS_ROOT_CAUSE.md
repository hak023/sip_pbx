# "Barge-in detected, stopping TTS" 반복 원인 정리

**목표**: 바지인은 켜 두되, **TTS가 멈추는 경우는 사용자 발화 인식 시(3자 이상 등 기존 로직)에만** 허용.  
VAD/STT 감지만으로는 TTS가 멈추면 안 됨.

---

## 1. 현상

- 로그에 `Barge-in detected, stopping TTS`, `TTS stop requested`, `TTS stopped` 가 반복 발생.
- Phase 2 인사말이 시작 직후 TTS가 중단됨.

---

## 2. 원인 (두 경로)

### 2.1 다운스트림: InterruptionFrame

- Pipecat TTS 서비스(`tts_service.py`)는 **`InterruptionFrame`** 수신 시 `_handle_interruption()`으로 TTS를 멈춤.
- 우리는 **InterruptionFrame / StartInterruptionFrame / StopInterruptionFrame** 만 차단하고 있었음.
- Pipecat 0.0.85+ 에서는 **`InterruptionFrame`(기본 클래스)** 사용 → 해당 타입도 차단 필요.

### 2.2 업스트림: InterruptionTaskFrame → Task가 InterruptionFrame 변환 (근본 원인)

- **STT 등** 일부 프로세서는 음성 감지 시 **`push_interruption_task_frame_and_wait()`** 를 호출.
- 이 함수는 **`InterruptionTaskFrame`** 을 **업스트림**으로 푸시.
- **Pipeline Task** 는 업스트림으로 들어온 `InterruptionTaskFrame` 수신 시  
  **`InterruptionFrame`** 으로 변환해 **다운스트림**으로 `queue_frame()` 함.
- 따라서 **InterruptionTaskFrame을 차단하지 않으면**  
  Task가 InterruptionFrame을 큐에 넣고, 파이프라인을 따라 TTS까지 전달 → **TTS가 멈춤**.
- 우리는 **InterruptionFrame(다운스트림)** 만 막고, **InterruptionTaskFrame(업스트림)** 은 막지 않아  
  Task까지 전달되고, 그 결과로 InterruptionFrame이 TTS에 도달하고 있었음.

**요약**:  
- **InterruptionTaskFrame(업스트림)** 을 막지 않음 → Task가 수신 → **InterruptionFrame(다운스트림)** 발사 → TTS 수신 → "Barge-in detected, stopping TTS".

---

## 3. 적용한 수정

### 3.1 `BargeInSuppressProcessor` (barge_in_suppress.py)

- **차단 대상 확장**
  - **InterruptionTaskFrame** (업스트림) 추가 차단.
  - InterruptionFrame / StartInterruptionFrame / StopInterruptionFrame (다운스트림) 유지.
- **InterruptionTaskFrame 흡수 시**
  - `frame.event.set()` 호출로, `push_interruption_task_frame_and_wait()` 호출 측이 타임아웃까지 블로킹되지 않도록 함.
- **효과**
  - STT 등이 InterruptionTaskFrame을 올려도 Task까지 전달되지 않음 → Task가 InterruptionFrame을 만들지 않음 → TTS는 InterruptionFrame을 받지 않음 → TTS가 멈추지 않음.

### 3.2 (기존) 다운스트림 차단

- InterruptionFrame / StartInterruptionFrame / StopInterruptionFrame 은 계속 차단.
- Task가 다른 경로로 InterruptionFrame을 넣는 경우에도 TTS 직전에서 한 번 더 막음.

---

## 4. 참고: Pipecat 플로우

1. **업스트림**  
   어떤 프로세서(예: STT)가 `push_interruption_task_frame_and_wait()`  
   → `InterruptionTaskFrame` 업스트림 푸시  
   → 이전 프로세서들 → **Source** → Task의 `_source_push_frame()`.
2. **Task**  
   `InterruptionTaskFrame` 수신 시  
   `_pipeline.queue_frame(InterruptionFrame(event=frame.event))`  
   → **InterruptionFrame** 이 파이프라인 **다운스트림** 큐에 들어감.
3. **다운스트림**  
   Source → … → **BargeInSuppressProcessor** → … → TTS.  
   InterruptionTaskFrame을 중간에서 흡수하면 1→2가 일어나지 않음.  
   InterruptionFrame도 BargeInSuppressProcessor에서 차단하면 TTS에 안 감.

---

## 5. 검증

- 수정 후 재시작하여 통화 시도.
- 로그에서 `Barge-in detected, stopping TTS` / `TTS stop requested` / `TTS stopped` 가 더 이상 나오지 않고,  
  `vad_barge_in_suppressed` (frame_type=`InterruptionTaskFrame` 또는 `InterruptionFrame`) 만 나오는지 확인.
- Phase 2 인사말이 끝까지 재생되는지 확인.
