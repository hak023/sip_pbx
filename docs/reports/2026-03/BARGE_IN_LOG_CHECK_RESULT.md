# Barge-in 점검 결과 — 결정 로직 정리 및 로그로 경로 파악

## 1. 올바른 방향: 기능은 쓰되, STOP TTS만 결정 로직에서 막기

- **사용자 발화는 인식되어야 하므로 barge-in(음성 인식) 자체는 막을 수 없다.**
- **TTS를 멈추는 것**만 제어해야 한다. 즉, **“STOP TTS”를 결정하는 로직**에서만 멈추지 않도록 해야 한다.

따라서:

- **파이프라인 최전방(Input)에서 Interruption* 을 흡수하는 방식은 제거했다.**  
  → 그렇게 하면 Interruption 관련 프레임이 전부 막혀, 필요한 동작까지 깨질 수 있다.
- **현재 로직**:  
  - 사용자 오디오(**InputAudioRawFrame**)는 그대로 **RTP → 큐 → Input → VAD → STT** 로 흐르고, **발화 인식**은 유지된다.  
  - **InterruptionFrame / InterruptionTaskFrame** 등은 **BargeInSuppressProcessor(중간)** 에서 흡수한다.  
  → “TTS 멈춤” 지시만 TTS에 전달되지 않고, **발화 인식(바지인 기능)은 유지**된다.

즉, **“결정되는 로직”** = TTS에 “멈춤”을 보내는 경로를 **BargeInSuppress에서 차단**하는 것이 맞다.

---

## 2. 현재 로직 이해

| 구분 | 내용 |
|------|------|
| **발화 인식** | InputAudioRawFrame → VAD → STT → RAG. 이 경로는 건드리지 않음. |
| **STOP TTS** | VAD/STT 등이 InterruptionTaskFrame(업스트림) → Task가 InterruptionFrame(다운스트림) → TTS 수신 시 TTS 멈춤. |
| **우리 목표** | 발화 인식은 그대로 두고, **Interruption* 이 TTS까지 가지 않게** 해서 STOP TTS가 실행되지 않게 함. |
| **적용** | **BargeInSuppressProcessor** 에서 Interruption* (InterruptionTaskFrame, InterruptionFrame, Start/StopInterruptionFrame) 수신 시 **하류로 push 하지 않고 흡수**. InterruptionTaskFrame 이면 `frame.event.set()` 호출. |

Pipecat 쪽 **MinWordsInterruptionStrategy** 는 LLMUserAggregator 등이 있는 표준 파이프라인에서 평가된다. 우리는 **RAGLLMProcessor** 만 사용하므로 해당 전략이 적용되지 않을 수 있어, **BargeInSuppress 로 Interruption* 차단**이 맞는 방식이다.

---

## 3. “추가 로그가 없다”의 의미 (이전 점검)

- **barge_in_suppress_blocked**, **vad_interruption_absorbed** 가 **한 번도 안 나온다**  
  → Interruption* 이 **우리 체인(VAD 래퍼, BargeInSuppress)을 거치지 않았다**는 뜻일 수 있다.
- 그럴 경우: Task가 넣는 경로가 다르거나, TTS 내부/다른 경로에서 Interruption이 처리되고 있을 수 있음.
- **대응**: Input 최전방 흡수는 제거했고, **로그로 경로를 추적**하는 쪽으로 정리한다.

---

## 4. 로그로 경로 파악하기

다음 로그를 보면 **Interruption* 이 우리 파이프라인을 타는지** 알 수 있다.

| 이벤트 | 의미 |
|--------|------|
| **vad_interruption_absorbed** | VAD 래퍼에서 Interruption* 흡수 (enable_barge_in=False 시). |
| **barge_in_suppress_blocked** | BargeInSuppress에서 Interruption* 차단. |

- **위 로그가 나온다**  
  → Interruption* 이 우리 체인을 타고 있고, BargeInSuppress/VAD 래퍼에서 막고 있는 것.  
  → 그런데도 "Barge-in detected, stopping TTS" 가 나오면, **같은 통화에서 Interruption* 이 두 번 발생**했거나(하나는 막힌 경로, 하나는 다른 경로), 또는 **TTS 직전 어딘가에서 또 생성**되는지 추가 추적 필요.
- **위 로그가 전혀 없다**  
  → Interruption* 이 **우리 체인을 거치지 않고** TTS에 전달되는 경로가 있다는 뜻.  
  → Pipecat Task/파이프라인 구조, 또는 TTS/서비스 내부에서 Interruption을 만드는지 리서치 필요.

---

## 5. Pipecat 사용 리서치 (요약)

- **allow_interruptions=False** 로 두면, Task/StartFrame 쪽에서 “인터럽션 허용 여부”가 전달된다.  
  하지만 **VAD/STT가 InterruptionTaskFrame 을 업스트림으로 보내는 동작**은 별도라, Task 가 그걸 받아 InterruptionFrame 으로 바꿔 다운스트림에 넣을 수 있다.
- **InterruptionFrame** 이 **파이프라인 앞단(Source → 첫 프로세서)** 에 들어가면, 문서상 우리 체인(transport.input() → … → barge_in_suppress → … → tts)을 **타는 것이 맞다.**  
  그런데도 중간 로그가 없다면, **실제 사용 중인 Pipecat 버전**에서 queue_frame/다운스트림 주입 위치가 다르거나, **TTS 쪽에서만 직접 받는 경로**가 있을 수 있다.
- **다음 단계**:  
  - 동일 시나리오로 통화한 뒤 **barge_in_suppress_blocked**, **vad_interruption_absorbed** 가 나오는지 확인.  
  - 나오지 않으면, 설치된 Pipecat 소스에서 `InterruptionFrame`, `queue_frame` 사용처를 검색해 **TTS로 가는 경로**를 특정.

---

## 6. 요약

- **최전방(Input) 흡수는 하지 않는다.** 발화 인식(barge-in 기능)을 올바르게 쓰기 위함.
- **STOP TTS만 막는다** = **BargeInSuppress(및 필요 시 VAD 래퍼)** 에서 Interruption* 을 흡수하는 현재 로직이 “결정 로직”에 해당한다.
- **원인 추적**은 **vad_interruption_absorbed**, **barge_in_suppress_blocked** 로그로 Interruption* 이 우리 체인을 타는지 먼저 확인하고, 없으면 Pipecat/TTS 경로 리서치로 이어가면 된다.
- 테스트 후 **동작 여부 점검**은 [DEBUG_LOG_VERIFICATION.md](DEBUG_LOG_VERIFICATION.md) 의 Barge-in 체크리스트를 참고하면 된다.

---

## 7. app.log 기반 원인 분석 (call_id: iVDhYrJSf8, 2026-03-13 09:58)

### 타임라인

| 시각 | 이벤트 |
|------|--------|
| 09:58:42.805 | Phase2 TTS started (barge-in disabled), 85자 가이드 |
| **09:58:42.817** | **Barge-in detected, stopping TTS** (TTS 시작 **12ms 후**) |
| 09:58:42.817 | TTS stop requested, TTS stopped |
| 09:58:44.800 | TTS stopped (barge-in), 2-Phase Greeting completed, AI call handling started |

### 로그로 확인한 사실

- **app.log 전체**에서 이 통화(call_id: iVDhYrJSf8) 구간에 **`barge_in_suppress_blocked`**, **`vad_interruption_absorbed`**, **`output_interruption_frame_absorbed`** 가 **한 건도 없다.**
- 즉, **Interruption\*** 프레임이 **우리가 로그를 넣은 경로**(VAD 래퍼 → BargeInSuppress → … → Output Transport)를 **거치지 않았다.**

### 결론: "Barge-in detected, stopping TTS" 발생 원인

1. **다른 경로로 TTS에 도달**  
   Interruption\* 이 **파이프라인 체인(transport.input() → … → BargeInSuppress → … → TTS)** 이 아닌, **Task가 TTS에 직접 넣는 경로** 또는 **TTS 프로세서 내부**에서 처리되고 있음.  
   그래서 우리가 차단하는 BargeInSuppress / Output 구간을 타지 않고, Pipecat TTS가 "Barge-in detected, stopping TTS"를 출력한 것으로 보는 것이 맞음.

2. **12ms 만에 발생**  
   TTS 시작 12ms 후에 바지인이 감지됨. 사용자가 그 짧은 시간에 말을 시작했다고 보기 어렵고, **TTS 시작 직후**  
   - 이전 Phase/백그라운드 잔향·노이즈, 또는  
   - Pipecat/내부 VAD의 초기화·임계값  
   에 의해 **바지인으로 오인**되었을 가능성이 있음.

3. **다음에 할 일**  
   - Pipecat 소스에서 **"Barge-in detected, stopping TTS"** 로그가 **어느 클래스/메서드**에서 출력되는지, 그리고 **InterruptionFrame이 어디서 주입되는지** 확인.  
   - Task → Pipeline 큐잉 시 **다운스트림이 Source가 아닌 특정 노드(TTS 등)로 직접 가는 경로**가 있는지 확인.  
   - 위 경로가 있으면, 그 경로 앞단에서 Interruption\* 을 흡수하거나, TTS 쪽 바지인 비활성화 옵션이 있는지 검토.

---

## 8. 추가 원인: ai_orchestrator에서의 "Barge-in detected, stopping TTS"

**"Barge-in detected, stopping TTS"** 는 **우리 코드** `ai_orchestrator.py` 의 `on_audio_packet` 에서도 출력된다.  
(RTP Worker가 **Orchestrator 모드**로 패킷을 넘길 때, `self.vad.is_barge_in() and self.is_speaking and self.state != ConversationState.GREETING` 이면 로그 후 `stop_speaking()` 호출.)

### 적용한 수정 (Orchestrator)

- **인사말 전체(Phase1 + Phase2)** 동안에는 바지인으로 TTS를 중단하지 않도록 함.
- **Phase2 시작 시** `state = SPEAKING` 으로 바꾸던 코드 제거 → **state는 계속 GREETING 유지**.
- `on_audio_packet` 에서 `state == GREETING` 이면 바지인을 무시하고, **디버깅용** `barge_in_ignored_during_greeting` 로그만 남김.

이렇게 하면 **Orchestrator 경로**로 들어오는 VAD 바지인은 인사말 구간에서 TTS를 끊지 않는다.

### Pipecat 경로 로그 강화

- **pipeline_built**: `processor_chain` 로 프로세서 순서 확인 가능.
- **pipecat_task_created**: `allow_interruptions` 값과 Task 생성 시점 확인.
- **barge_in_suppress_blocked**: 기존 + **pipecat_interruption_frame_reached_suppress** (debug) — Interruption\* 이 우리 BargeInSuppress에 도달했을 때.
- **output_interruption_frame_absorbed**: 기존 + **pipecat_interruption_frame_reached_output** (debug) — Interruption\* 이 중간을 거치지 않고 Output까지 온 경우.

이 로그들로 **Pipecat 쪽**에서 Interruption\* 이 어느 경로로 흐르는지 추적할 수 있다.
