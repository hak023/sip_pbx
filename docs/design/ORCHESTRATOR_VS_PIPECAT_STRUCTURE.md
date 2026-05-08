# Orchestrator vs Pipecat 구조 정리 및 권장 경로
> **클러스터 안내**: 설계·연구 문서입니다. 구현 스택·컴포넌트 경계는 Canonical 아키텍처를 우선합니다.
> 
> **참고**: [architecture/ai-voicebot-architecture.md](../architecture/ai-voicebot-architecture.md)
>
---


## 1. 현재 구조 요약

AI 부재 시 응대(no-answer takeover) 시 **두 가지 경로**가 있고, **설정 한 개**로만 갈림니다.

| 구분 | Orchestrator (Legacy) | Pipecat (Pipeline) |
|------|------------------------|---------------------|
| **선택 조건** | `pipeline_engine` == `"legacy"` (명시 시에만) | `pipeline_engine` == `"pipecat"` 또는 미설정 (기본값) |
| **설정 위치** | `ai_voicebot.pipeline_engine: legacy` | `ai_voicebot.pipeline_engine: pipecat` 또는 생략(기본 pipecat) |
| **실행 진입점** | `call_manager.handle_no_answer_timeout()` → `ai_orchestrator.handle_call()` | 동일 → `rtp_worker.enable_pipecat_mode()` + `pipecat_builder.build_and_run()` |
| **RTP → AI** | `rtp_worker.enable_ai_mode(ai_orchestrator)` → `on_audio_packet()` | RTP → `_pipecat_audio_queue` → 파이프라인 `get_caller_audio_stream()` |
| **인사말** | `ai_orchestrator.play_greeting()` → `speak()` → TTS 스트리밍 + `rtp_send_callback` | RAG `send_greeting()` → TextFrame → TTS → Output → `send_audio_to_caller()` |
| **STT** | Orchestrator가 `on_audio_packet()` 에서 `stt.send_audio()` | 파이프라인: Input → VAD → STT → RAG |
| **TTS** | `speak()` → `tts.synthesize_stream()` → 콜백으로 RTP 전송 | 파이프라인: RAG → TTS → Notifier → Output → `send_audio_to_caller()` |

**선택이 일어나는 곳**

- **main.py**  
  `create_pipecat_pipeline_builder(ai_config_dict)` 호출 →  
  **factory.py** 에서 `config.get("pipeline_engine", "legacy") == "pipecat"` 일 때만 Builder 생성 →  
  Builder 가 있으면 `call_manager.set_pipecat_builder(pipecat_builder)` 호출.
- **call_manager.handle_no_answer_timeout()**  
  `if self.pipecat_builder:` → Pipecat 경로,  
  `else:` → Legacy(Orchestrator) 경로.

기본값이 **pipecat** 이므로, 설정에 `pipeline_engine: legacy` 를 넣지 않으면 **Pipecat** 경로가 사용됩니다.

---

## 2. 두 경로 비교

| 항목 | Orchestrator (Legacy) | Pipecat |
|------|------------------------|---------|
| **인사말/TTS** | `play_greeting()` + `speak()` (콜백 기반 RTP) | RAG `send_greeting()` + 파이프라인 (프레임 기반, Phase1↔2 동기화·flush 제어 있음) |
| **바지인/끊김** | Orchestrator에서 VAD 바지인 제거함. 별도 3단어 로직 없음 | BargeInSuppress, flush 스킵 등으로 “인사말 잘림” 대응 로직이 Pipecat 쪽에만 있음 |
| **STT** | `on_audio_packet()` 으로 패킷 전달. 파이프라인과 분리 | Input → VAD → STT → RAG 로 **한 파이프라인** 안에서 처리. 블로킹 시 큐 백로그 등으로 추적 가능 |
| **코드 중복** | 인사말·TTS·STT가 Orchestrator 전용 코드로 따로 구현 | 인사말·TTS·STT·RAG가 파이프라인 한 흐름으로 구현 |
| **디버깅/로그** | Orchestrator 전용 로그만 의미 있음 (예: `orchestrator_speak_*`) | Pipecat 전용 로그만 의미 있음 (예: `greeting_phase*_sent`, `stt_path_*`) |

**정리**:  
- 지금처럼 **Legacy만 쓰면** Pipecat에 넣어 둔 인사말/바지인/STT 관련 수정·로그는 **전혀 타지 않음**.  
- **Pipecat만 쓰면** Orchestrator 인사말/TTS 경로는 타지 않음.

---

## 3. 권장: 한 경로로 통일

### 3.1 Pipecat을 기본 경로로 쓰는 것을 권장

이유 요약:

1. **한 파이프라인**  
   RTP → Input → VAD → STT → RAG → TTS → Output 으로 한 흐름이라, 인사말 잘림·바지인·STT 미동작 등을 **한 구조**에서만 보면 됨.
2. **이미 Pipecat 쪽에 맞춰 둔 작업**  
   BargeInSuppress, Phase1→2 flush 스킵, STT 경로 로그(`stt_path_*`), RAG 블로킹 로그 등이 **Pipecat 경로**에만 있음. 이 경로를 쓰는 편이 수정 효과를 보기 좋음.
3. **중복 제거**  
   인사말·TTS·STT를 Orchestrator와 Pipecat 두 군데서 유지하지 않고, **Pipecat 한 군데**로 모을 수 있음.
4. **설정 한 줄**  
   `pipeline_engine: pipecat` 만 넣으면 Pipecat 경로로 넘어감.  
   (Pipecat Builder 생성 실패 시 factory에서 이미 legacy로 fallback하고, main.py에서도 예외 처리 후 legacy로 동작함.)

### 3.2 구조를 Pipecat으로 맞추는 방법

1. **설정**  
   AI 보이스봇 설정(예: `ai_voicebot` 또는 해당 config dict)에 다음을 넣어 **항상 Pipecat**을 쓰게 할 수 있음.
   ```yaml
   ai_voicebot:
     enabled: true
     pipeline_engine: pipecat   # 이렇게 설정하면 Pipecat 경로 사용
   ```
   (`main.py`에서 `config.ai_voicebot`을 dict로 넘기므로, config 최상위의 `ai_voicebot` 아래에 `pipeline_engine` 키를 두면 됨. `factory.create_pipecat_pipeline_builder(ai_config_dict)`에서 `config.get("pipeline_engine", "legacy")`로 읽음.)

2. **기본값**  
   **config/models.py** 의 `AIVoicebotConfig` 에 `pipeline_engine` 필드 기본값이 `"pipecat"` 이고, **factory.py** 에서도 `config.get("pipeline_engine", "pipecat")` 로 읽음.  
   설정에 아무것도 넣지 않으면 Pipecat이 사용되고, Legacy를 쓰려면 `pipeline_engine: legacy` 를 명시하면 됨.

3. **동작 확인**  
   - 재시작 후 로그에  
     `"engine": "pipecat"`,  
     `"✅ [Pipecat] Pipeline task started"`,  
     `pipecat_builder_connected_to_call_manager`  
     등이 나오면 Pipecat 경로로 진입한 것.  
   - 인사말/STT 관련해서는 **Pipecat 전용 로그**  
     (`greeting_phase1_sent`, `greeting_phase2_sent`, `stt_path_*`, `tts_flush_skipped_greeting_phase2` 등)만 보면 됨.

### 3.3 Legacy를 유지할 경우

- **의도적으로 Orchestrator만** 쓰려면:  
  config에 `pipeline_engine: legacy` 를 넣으면 됨.  
- 이때는 **Orchestrator 쪽 로그/수정만** 의미 있음 (예: `orchestrator_speak_*`, `orchestrator_greeting_phase*_sent`).  
- Pipecat 전용 수정(인사말 잘림, 바지인, STT 경로)은 **이 경로에서는 적용되지 않음**이라고 보면 됨.

---

## 4. 요약

| 질문 | 답 |
|------|----|
| **어떤 것을 타게 하는가?** | 기본값 **pipecat**. 설정 `pipeline_engine`: `"legacy"` 일 때만 Orchestrator. |
| **어느 쪽을 쓰는 게 맞는가?** | **Pipecat 한 경로로 통일** (기본값으로 적용됨). Legacy는 `pipeline_engine: legacy` 로만 사용. |
| **구조를 맞추려면?** | 별도 설정 없이 재시작하면 Pipecat 사용. Legacy로 되돌리려면 config에 `pipeline_engine: legacy` 설정. |

이 문서는 “Orchestrator vs Pipecat 중 무엇을 타는지”, “어떤 경로로 구조를 맞출지”를 정리한 설계 문서입니다.
