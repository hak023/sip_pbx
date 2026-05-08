# 파이프라인 코드로 기존 AI 응대 대체 검증
> **클러스터 안내**: 세부·히스토리 설계 문서입니다. 통합 관점·경계는 아래 대표 문서를 우선 참고하세요.
> 
> **대표 문서**: [`TTS_RTP_AND_STT_QUEUE_DESIGN.md`](TTS_RTP_AND_STT_QUEUE_DESIGN.md)
>
---


## 1. 검증 목적

- 새로 만든 **PipelineBuilder**가 **기존 AI 응대 흐름을 대체**해 사용할 수 있는지 검증.
- 사용 전 **전제조건·누락 의존성·위험 요소**를 정리해 실제 연동 시 문제가 없도록 함.

---

## 2. 대체 관계 정리

| 구분 | 기존 AI 응대 | 파이프라인으로 대체 시 |
|------|--------------|-------------------------|
| **진입점** | (별도 Orchestrator/CallManager 등) | **`run_ai_voice_pipeline(callee, rtp_worker, vad=..., stt=..., tts=..., llm_client=...)`** 한 번 호출 (`src/ai_voicebot/run_ai_call.py`) |
| **오디오 수신** | RTP Worker 등 | `SIPPBXTransport.input()` → `get_caller_audio_stream()` |
| **STT → LLM → TTS** | 별도 조합 | 동일한 `RAGLLMProcessor` 사용. 파이프라인에서 `vad → stt → rag_llm → tts` 순서로 연결 |
| **녹음** | (기존 미구현) | `rec_input` / `rec_output` 로 `mixed.wav` 자동 저장 |
| **통화 종료 정리** | (호출부에서 처리) | `on_call_ended(call_id)` → `emit_call_ended` 로 HITL 해제·이벤트 발송 일원화 |

**구현 상태**: 기존 AI 응대 코드는 **`run_ai_voice_pipeline` 호출 한 곳으로 대체**됨. CallManager(또는 RTP Worker)는 AI 통화 시작 시 이 함수만 호출하면 됨. 내부에서 `emit_call_started` → `PipelineBuilder.build_and_run`(레코딩·HITL·WebSocket 연동 포함) → `emit_call_ended` 까지 처리함.

**결론**: 기존에 “AI 응대”를 하던 코드 경로가 있다면, 그 경로를 **파이프라인 한 번 실행**으로 대체하는 것이 체계적이며, 동일한 RAGLLMProcessor·HITL·WebSocket 이벤트를 그대로 사용할 수 있음.

---

## 3. 전제조건 (사용하려면 갖춰야 할 것)

### 3.1 rtp_worker 계약

파이프라인은 아래 인터페이스를 가진 **rtp_worker** 객체를 요구함.

| 항목 | 요구 사항 |
|------|-----------|
| `rtp_worker.media_session` | 존재하며 아래 속성 보유 |
| `media_session.call_id` | str, 통화 ID |
| `media_session.callee` | str (선택), 착신번호. 없으면 call_id로 대체 시도 |
| `get_caller_audio_stream()` | async generator, 16kHz 16bit mono PCM bytes yield |
| `send_audio_to_caller(audio: bytes, sample_rate)` | 호출 시 RTP로 발신자에게 오디오 전송 |

기존 AI 응대 코드가 **동일한 RTP Worker**를 쓰고 있다면 그대로 넘기면 됨. 다른 형태면 어댑터로 위 계약을 만족시키면 됨.

### 3.2 필수 주입 컴포넌트

호출 측에서 **반드시 생성해 넘겨야 하는 것**:

- **vad**: Pipecat VAD FrameProcessor (예: Silero VAD)
- **stt**: Pipecat STT FrameProcessor (예: Google STT)
- **tts**: Pipecat TTS FrameProcessor (예: Google TTS)
- **llm_client**: RAGLLMProcessor가 기대하는 LLM 클라이언트 (Gemini 등)

이들은 이 레포에 구현되어 있지 않으며, `pipecat` / `pipecat-services-*` 등으로 호출 측에서 생성해 전달해야 함.

### 3.3 선택 주입

- **knowledge_service**: 있으면 `OrganizationInfoManager(owner=callee)` 생성·로드 후 RAGLLMProcessor에 전달.
- **rag_engine, embedder, vector_db**: RAG/캐시용. 없으면 RAG 없이 동작.
- **hitl_on_alert**: HITL 알림 시 호출할 콜백 (예: `emit_hitl_requested` 연동).

---

## 4. 의존성 점검 및 조치

### 4.1 빌드 시점 필수 (파이프라인 생성 시)

| 의존성 | 상태 | 비고 |
|--------|------|------|
| `pipecat.pipeline` (Pipeline, PipelineTask, PipelineRunner) | 외부 패키지 | `pipecat-ai` 설치 필요 |
| `src.ai_voicebot.pipecat.stt_post_filter.STTPostFilter` | ✅ 추가됨 | `src/ai_voicebot/pipecat/stt_post_filter.py` 구현. 없으면 RAGLLMProcessor 생성 시 ImportError |
| `src.services.hitl.get_hitl_service` | ✅ 존재 | `src/services/hitl.py` |
| `src.ai_voicebot.pipecat.processors.hitl_processor.HITLManager` | ✅ 존재 | |
| `src.ai_voicebot.langgraph.agent.ConversationAgent` | ✅ 존재 | |

### 4.2 런타임 시 사용 (경로 따라 필요)

RAGLLMProcessor 내부에서 **실제 통화 중 특정 경로**에서만 import하는 모듈들. 해당 경로가 실행될 때 없으면 ImportError 발생.

| 의존성 | 용도 | 권장 조치 |
|--------|------|------------|
| `src.ai_voicebot.greeting_store` | 인사말 Phase1/2 저장·조회 | 구현하거나, RAGLLMProcessor에서 import를 try/except로 감싸고 없을 때 무시 |
| `src.ai_voicebot.pipecat.processors.tts_complete_notifier` | Phase1 재생 완료 후 Phase2 전송 동기화 | 파이프라인에 Notifier 추가 시 필요. 없으면 Phase2 대기 로직이 동작하지 않을 수 있음 |
| `src.services.follow_up_service` | 후속 조치 서비스 | 구현하거나 해당 분기에서 try/except 처리 |
| `src.websocket.manager` | emit_stt_transcript, emit_tts_*, emit_ai_greeting 등 | ✅ 존재. 통화 중 이벤트 발송용 |

**권장**:  
- **즉시 파이프라인만 도입**할 경우: `greeting_store`, `tts_complete_notifier`, `follow_up_service` 는 선택 구현. 없으면 해당 기능만 비활성화되도록 RAGLLMProcessor에서 `try/except` 로 import 또는 호출을 감싸 두는 것이 안전함.  
- **전 기능 사용**할 경우: 위 모듈 구현 후 파이프라인에 TTSCompleteNotifier 등 필요한 프로세서를 추가.

---

## 5. 동작 검증 포인트

### 5.1 프레임 흐름

- **StartFrame**: Pipecat `PipelineTask`가 파이프라인 시작 시 자동 전달. `SIPPBXInputTransport`는 StartFrame 수신 시 `get_caller_audio_stream()` 루프 시작.
- **EndFrame**: 통화 종료 시 파이프라인에 EndFrame이 흘러야 레코딩이 저장됨.  
  - RTP/통화 종료 시 `get_caller_audio_stream()` 이 끝나고, 상위에서 파이프라인에 EndFrame을 넣거나 `task.cancel()` / `task.stop_when_done()` 등으로 종료하는 구조가 필요함.  
  - 현재 `build_and_run`은 `await runner.run(task)` 만 하므로, **통화 종료를 감지하는 쪽**에서 `task`에 접근해 종료 신호를 주거나, runner가 스트림 종료를 감지해 EndFrame을 넣는 방식이 있어야 함. (구현체에 따라 상이할 수 있음.)

### 5.2 레코딩

- `rec_input` / `rec_output` 가 파이프라인에 포함되어 있으므로, EndFrame이 출력 단까지 전달되면 `RecordingOutputProcessor`가 `save_mixed_wav` 호출.  
- 저장 경로는 기존 recordings API와 동일 (`RECORDINGS_DIR / {call_id} / mixed.wav`).

### 5.3 HITL·WebSocket

- RAGLLMProcessor가 그대로 사용되므로, 기존처럼 `get_hitl_service().register_call(call_id, queue)` 및 `emit_hitl_requested` 등 WebSocket 이벤트는 동일하게 동작.  
- `on_call_ended(call_id)` 에 `emit_call_ended` 를 넣으면, 통화 종료 시 HITL 해제·프론트 알림이 기존과 동일하게 처리됨.

---

## 6. 사용 가능 여부 요약

| 항목 | 판단 |
|------|------|
| 기존 AI 응대를 파이프라인 한 번 실행으로 대체 가능 여부 | ✅ 가능. 동일 RAGLLMProcessor·HITL·이벤트 사용. |
| 파이프라인 빌드 시 필수 의존성 | ✅ stt_post_filter 추가로 해소. pipecat-ai 및 vad/stt/tts/llm_client 주입 필요. |
| rtp_worker 계약 | 호출 측에서 위 3.1 계약 만족 객체 전달 필요. |
| 런타임 선택 의존성 | greeting_store, tts_complete_notifier, follow_up_service 는 경로에 따라 필요. 없으면 해당 기능만 제한되고, try/except로 감싸면 파이프라인 자체는 동작 가능. |
| 통화 종료·EndFrame | 실제 통화 종료와 task 종료(EndFrame 또는 cancel)를 연결하는 로직이 호출 측 또는 runner 쪽에 필요. |

**종합**:  
- **체계적으로 사용하는 장점**은 그대로 유지되고,  
- **즉시 사용**하려면: (1) rtp_worker 계약 만족, (2) vad/stt/tts/llm_client 주입, (3) 통화 종료 시 task/runner 종료 처리만 맞추면 됨.  
- **전 기능**을 쓰려면: greeting_store, tts_complete_notifier, follow_up_service 구현 또는 RAGLLMProcessor 내 예외 처리로 안전하게 만든 뒤 사용하면 됨.

---

## 7. 기존 코드 대체 후 사용 방법

AI 통화는 **아래 한 곳만** 호출하면 된다. (기존 별도 진입점·Orchestrator 호출 제거)

```python
from src.ai_voicebot.run_ai_call import run_ai_voice_pipeline

# AI 통화 시작 시 (CallManager / RTP Worker 등에서)
await run_ai_voice_pipeline(
    callee="1003",
    rtp_worker=rtp_worker,
    vad=vad,
    stt=stt,
    tts=tts,
    llm_client=llm_client,
    knowledge_service=knowledge_service,  # 선택
)
```

- `emit_call_started` / `emit_call_ended` / HITL `emit_hitl_requested` 연동은 `run_ai_voice_pipeline` 내부에서 처리됨.  
- 레코딩(rec_input/rec_output)은 파이프라인에 포함되어 있으므로 별도 호출 불필요.
