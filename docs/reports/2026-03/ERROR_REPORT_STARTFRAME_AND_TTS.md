# 에러 점검 리포트: StartFrame not received yet / TTS 미송출

**분석 대상**
- `app.log` 2507–2645 (통화 T9bwxix-S4, 2026-03-13 13:17:56–13:18:00)
- 콘솔(터미널) ERROR 로그: `pipecat.processors.frame_processor._check_started` (라인 946)

**요약**
- 콘솔: `BargeInSuppressProcessor#0`, `RAGLLMProcessor#0`에서 “Trying to process … but **StartFrame not received yet**” 반복.
- 앱 로그: 인사말 Phase1 전송·RAG 블로킹까지는 진행되나 **packets_sent: 0**, `rtp_tts_queue_empty_timeout` 반복 → **TTS가 caller에게 한 번도 송출되지 않음**.

---

## 1. 콘솔 에러 정리

| 발생처 | 메시지 요지 | 비고 |
|--------|-------------|------|
| BargeInSuppressProcessor#0 | OutputTransportMessageUrgentFrame 처리 시 StartFrame not received yet | VAD 오류 메시지: "TaskManager is still not initialized" |
| BargeInSuppressProcessor#0 | InputAudioRawFrame#0 ~ #164 처리 시 StartFrame not received yet | 입력 경로(Input → … → barge_in_suppress) |
| RAGLLMProcessor#0 | LLMFullResponseStartFrame / TextFrame / LLMFullResponseEndFrame 처리 시 StartFrame not received yet | 인사말 텍스트가 RAG→TTS 쪽으로 전달될 때 |

Pipecat `FrameProcessor` 기반 클래스는 **StartFrame을 먼저 받아야** `_check_started`를 통과하고, 그렇지 않으면 위와 같이 ERROR 로그를 남긴다.

---

## 2. 원인 분석

### 2.1 BargeInSuppressProcessor가 StartFrame을 “받은 것으로” 기록하지 않음

- 파이프라인 순서:  
  `Source → Input → rec_input → vad_wrapped → barge_in_suppress → stt → rag_llm → barge_in_suppress_before_tts → tts → …`
- `app.log` 상으로는 **Input**에서 StartFrame 수신·전달이 확인됨:
  - `input_transport_first_frame` (frame_type=StartFrame)
  - `input_transport_startframe_received`
  - `input_audio_loop_task_created` → `pipecat_input_transport_started`
- 즉, StartFrame은 Source → Input → rec_input → vad_wrapped 까지는 흐르고, 그 다음 **barge_in_suppress**에도 전달된다(코드상 `push_frame` 연쇄로 전달됨).

그런데도 콘솔에서는 **BargeInSuppressProcessor#0**가 “StartFrame not received yet”라고 한다.  
이는 Pipecat 기본 클래스의 **내부 상태(`_started`)** 가 StartFrame 수신으로 갱신되지 않았기 때문이다.

- **BargeInSuppressProcessor**의 `process_frame()` 구현을 보면 **`super().process_frame(frame, direction)`를 호출하지 않는다.**
- Pipecat `FrameProcessor`에서는:
  - `super().process_frame()` 안에서 StartFrame 수신 시 `_started`를 설정하고,
  - 그 외 프레임에 대해서는 `_check_started()`로 “StartFrame을 이미 받았는지” 검사한다.
- 따라서 `super().process_frame()`을 호출하지 않으면:
  - StartFrame이 와도 기본 클래스는 “StartFrame을 받았다”고 기록하지 않고,
  - 이후 InputAudioRawFrame 등이 올 때마다 `_check_started()`에서 “StartFrame not received yet” ERROR가 난다.

정리하면, **BargeInSuppressProcessor가 `super().process_frame()`을 호출하지 않아서** 기본 클래스의 StartFrame 처리 및 `_check_started` 계약이 만족되지 않는 것이 콘솔 에러의 직접 원인이다.

### 2.2 RAGLLMProcessor의 “StartFrame not received yet”

- RAGLLMProcessor는 **`await super().process_frame(frame, direction)`를 호출한다** (rag_processor.py 261행).
- 그럼에도 RAGLLMProcessor에서 “StartFrame not received yet”가 나온다면, **실제로 해당 인스턴스에 StartFrame이 도달하기 전에** LLMFullResponseStartFrame/TextFrame 등이 도달한 경우다.
- 파이프라인 상 StartFrame은 **입력 경로**를 따라 흐른다:  
  Source → Input → rec_input → vad_wrapped → **barge_in_suppress** → stt → **rag_llm** → …
- 반면 인사말은 **RAG가 비동기로** LLMFullResponseStartFrame/TextFrame을 푸시한다.  
  만약 (1) StartFrame이 barge_in_suppress 쪽에서 막혀 하류로 잘 안 흐르거나, (2) 오디오 루프 등이 빨리 InputAudioRawFrame을 쏟아내고, (3) 파이프라인 스케줄링/큐 순서 때문에 **RAG로 가는 경로에는 StartFrame보다 인사말 프레임이 먼저 도달**할 수 있다.
- 즉, **BargeInSuppressProcessor에서 `super().process_frame()`를 호출하지 않아 StartFrame이 정식으로 “처리”되지 않고, 그 다음 래그들(stt, rag_llm)로의 전달이 지연되거나 순서가 꼬이면**, RAGLLMProcessor는 StartFrame을 아직 못 받은 상태에서 인사말 프레임을 받을 수 있다.

따라서 RAG 측 에러도, 근본적으로는 **입력 경로 상의 BargeInSuppressProcessor가 StartFrame을 기반 클래스와 계약대로 처리하지 않는 것**과 연결된다.

### 2.3 TTS 미송출 (packets_sent: 0, rtp_tts_queue_empty_timeout)

- `greeting_phase1_sent`, `rag_greeting_blocking_start` 등으로 **인사말 생성·Phase1 전송 시도**는 이루어졌다.
- 하지만 **TTS → Output → RTP** 구간에서 실제로 패킷이 나가지 않았다:
  - `rtp_tts_queue_empty_timeout` (packets_sent: 0) 반복.
- 가능한 연결 고리:
  - 위에서 기술한 대로, **StartFrame이 하류 프로세서들에 “정식으로” 전달되지 않으면** Pipecat 내부에서 일부 컴포넌트가 “아직 시작 전”으로 보고 프레임을 버리거나 전달하지 않을 수 있다.
  - 그 결과 TTS/Output 쪽으로 유효한 오디오 프레임이 흐르지 않아 `packets_sent: 0`이 될 수 있다.
- 추가로, 콘솔 첫 줄의 **`PipecatVADProcessor#0 TaskManager is still not initialized`** 는 VAD 초기화/타이밍 이슈를 시사한다. 이 오류 프레임이 파이프라인에 먼저 들어가면, StartFrame 전파와 혼합되어 하류 프로세서들의 “시작” 상태를 더 꼬이게 할 수 있다.

---

## 3. 수정 사항 (권장)

### 3.1 BargeInSuppressProcessor에서 `super().process_frame()` 호출 (필수)

- **파일**: `sip-pbx/src/ai_voicebot/pipecat/processors/barge_in_suppress.py`
- **내용**: `process_frame()` 진입 시 **맨 먼저** `await super().process_frame(frame, direction)` 호출.
- **효과**:
  - StartFrame 수신 시 기본 클래스가 `_started`를 설정하고,
  - 이후 InputAudioRawFrame 등에 대해 `_check_started()`가 통과하여 “StartFrame not received yet” ERROR 제거.
  - 입력 경로를 따라 StartFrame이 stt → rag_llm까지 정상 전파되도록 돕고, RAGLLMProcessor의 동일 에러와 TTS 미송출 가능성을 줄인다.

### 3.2 (선택) StartFrame 전파 우선 보장

- Input Transport에서 StartFrame을 `push_frame()`한 직후 **오디오 루프**를 바로 시작하면, 같은 타이밍에 많은 InputAudioRawFrame이 쏟아져 하류 큐에서 StartFrame보다 먼저 처리될 수 있다.
- 필요 시, StartFrame을 push한 뒤 **짧은 지연**(예: `await asyncio.sleep(0)` 또는 0.05~0.1초) 후 `_start_audio_loop_if_needed()`를 호출하거나, 오디오 루프 시작을 한 틱 미루는 방식으로 StartFrame이 먼저 하류로 흐르게 할 수 있다.  
  (우선은 3.1만 적용해도 상당 부분 완화될 가능성이 큼.)

### 3.3 (선택) VAD “TaskManager is still not initialized” 조사

- 첫 번째 콘솔 에러는 **OutputTransportMessageUrgentFrame** (VAD 오류 메시지)가 BargeInSuppressProcessor에 도달했을 때 발생했다.
- Pipecat VAD 초기화 순서/타이밍과 TaskManager 설정 시점을 확인해, 가능하면 StartFrame 전파 이후에 VAD가 프레임을 내보내도록 하면, 오류 프레임으로 인한 혼선을 줄일 수 있다.

---

## 4. 로그·콘솔 요약 표

| 구분 | 내용 |
|------|------|
| app.log | input_transport_first_frame=StartFrame, input_transport_startframe_received, greeting_phase1_sent, rag_greeting_blocking_start 까지 정상 기록 |
| app.log | packets_sent: 0, rtp_tts_queue_empty_timeout 반복 → TTS 미송출 |
| 콘솔 | BargeInSuppressProcessor#0 / RAGLLMProcessor#0 “StartFrame not received yet” 반복 |
| 결론 | BargeInSuppressProcessor에 `super().process_frame()` 추가로 기본 클래스 StartFrame 계약 충족 필요 |

---

**작성일**: 2026-03-13  
**대상 통화**: T9bwxix-S4 (callee 1004, 기상청)
