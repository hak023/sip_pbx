# "Already recording" 로그 및 Barge-in 계속 발생 원인 리서치

## 1. "Already recording" 로그

### 1.1 검색 결과

- **sip-pbx 코드베이스**: `"Already recording"` 문자열 **없음** (grep 전체 검색).
- **app.log / 로그 이벤트**: `event` 필드가 `"Already recording"` 인 로그는 샘플에서 확인되지 않음.  
  (다른 로그 파일이나 stderr/콘솔에서 보였을 수 있음.)

### 1.2 가능한 출처

| 출처 | 설명 |
|------|------|
| **Pipecat** | 파이프라인 내 레코딩/입력 처리에서 "Already recording" 메시지 출력 가능성. 공식 소스 검색 결과는 없음. |
| **Google Cloud TTS / STT** | 스트리밍 API에서 세션/버퍼 상태 로그로 출력할 수 있음. |
| **Deepgram 등 STT** | 스트리밍 연결이 이미 열린 상태에서 다시 시작할 때 유사 메시지 가능. |
| **기타 의존성** | `create_recording_processors` 의 CallRecordingCollector 외에, Pipecat 내부에 별도 "recording" 관련 프로세서가 있다면 해당 코드에서 출력 가능. |

### 1.3 확인 방법

1. **로그 컨텍스트**: "Already recording" 이 나올 때 바로 위/아래 로그의 `call_id`, `event` 를 확인해 어떤 컴포넌트 직후인지 파악.
2. **의존성 소스 검색**:  
   `pip show pipecat` 로 설치 경로 확인 후, 해당 경로에서 `Already` / `recording` 검색.  
   동일하게 `pipecat-google-*`, `pipecat-deepgram` 등 사용 중인 서비스 패키지 내부 검색.
3. **stderr 캡처**: 앱 실행 시 stderr를 파일로 리다이렉트해 두면, structlog가 아닌 print/logger에서 나온 메시지도 확인 가능.

---

## 2. Barge-in detected, stopping TTS 가 계속되는 원인 (VAD 래퍼)

### 2.1 설정 요약

- `PipelineParams(allow_interruptions=False)`
- `wrap_vad_with_logging(..., enable_barge_in=False)`
- `BargeInSuppressProcessor` 2개 (업스트림/다운스트림)
- RTP Output: Interruption* 수신 시 전달하지 않고 흡수

이미 InterruptionFrame / InterruptionTaskFrame 을 여러 단계에서 막고 있음에도 **TTS까지 InterruptionFrame이 도달**하는 경우가 있었음.

### 2.2 근본 원인: VAD 래퍼의 처리 순서

**기존 동작 (문제):**

1. `VADWrapperProcessor.process_frame(frame, direction)` 에서 **모든 프레임**에 대해  
   먼저 `await self._vad.process_frame(frame, direction)` 호출.
2. **InterruptionFrame** (또는 Start/Stop) 이 들어오면, **내부 Pipecat VAD**가 이 프레임을 처리하면서  
   내부적으로 **`push_frame()`** 을 호출해 **다음 프로세서(하류)** 로 그대로 전달.
3. 그 다음 우리 코드에서 `elif isinstance(frame, InterruptionFrame, ...)` 로 분기하고  
   `enable_barge_in=False` 이면 **`return`** 해서 우리는 `push_frame()` 을 호출하지 않음.
4. 그러나 **이미 내부 VAD가 push_frame()으로 하류에 전달한 상태**이므로,  
   BargeInSuppressProcessor / RTP 등으로 InterruptionFrame이 전달되고,  
   TTS에 도달해 "Barge-in detected, stopping TTS" 가 발생.

즉, **Interruption* 프레임을 내부 VAD에 넘기면 안 됨**.  
내부 VAD가 해당 프레임을 하류로 푸시하기 때문에, 우리가 마지막에 `return` 해도 이미 늦음.

### 2.3 수정 내용 (vad_wrapper.py)

- **Interruption\*** (InterruptionFrame, StartInterruptionFrame, StopInterruptionFrame) 인 경우:
  - **`enable_barge_in=False`** 이면  
    **`_vad.process_frame()` 호출 없이** 즉시 `return` (하류로도 전달하지 않음).
  - **`enable_barge_in=True`** 이면  
    기존처럼 `_vad.process_frame()` 호출 후 로깅하고 `push_frame()` 한 번만 호출하고 `return`.
- 그 외 프레임은 기존과 동일하게  
  `_vad.process_frame()` 호출 후, UserStartedSpeakingFrame / UserStoppedSpeakingFrame 로깅 등 수행하고  
  마지막에 `push_frame()`.

이렇게 하면 **바지인 끔**일 때 Interruption* 이 내부 VAD를 거치지도, 하류로 나가지도 않아  
TTS가 "Barge-in detected, stopping TTS" 를 수행하지 않음.

### 2.4 요약

| 구분 | 내용 |
|------|------|
| **원인** | VAD 래퍼가 Interruption* 도 **먼저** `_vad.process_frame()` 에 넘겨서, 내부 VAD가 `push_frame()` 으로 하류 전달. |
| **수정** | Interruption* 은 **`_vad.process_frame()` 호출 전에** 분기하고, `enable_barge_in=False` 이면 내부 VAD 호출 없이 전달 없이 return. |
| **관련 파일** | `sip-pbx/src/ai_voicebot/pipecat/processors/vad_wrapper.py` |

---

## 3. 참고 문서

- `BARGE_IN_STOPPING_TTS_ROOT_CAUSE.md` — InterruptionTaskFrame / InterruptionFrame 차단 경로.
- `PIPECAT_BARGE_IN_OPTIONS.md` — Pipecat 바지인 옵션 정리.
- `PIPECAT_VERSION_AND_TASK_TTS_PATH.md` — "Barge-in detected, stopping TTS" 로그는 Pipecat 메인에는 없고, TTS 서비스(예: Google) 쪽 가능성 명시.
