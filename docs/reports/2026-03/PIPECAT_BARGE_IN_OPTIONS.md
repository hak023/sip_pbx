# Pipecat Barge-in 관련 옵션 정리

**검색 기준**: Pipecat 공식 문서·GitHub (2026-03 기준)

---

## 1. PipelineParams (우리 파이프라인에서 사용 중)

우리 코드는 `PipelineTask(pipeline, params=PipelineParams(allow_interruptions=True))` 로 실행 중.

### 1.1 `allow_interruptions` (bool)

| 값 | 동작 |
|----|------|
| **True** (기본값) | 사용자 발화가 봇 응답을 **즉시 중단**할 수 있음 (InterruptionFrame 유발). |
| **False** | 파이프라인 레벨에서 인터럽션 비활성화. 사용자 발화가 TTS를 중단하지 않도록 할 때 사용. |

- **Deprecated**: 0.0.99부터 deprecated. 공식 권장은 아래 "User Turn Strategies" 쪽.
- **현재(0.0.102)**: 아직 동작하며, `StartFrame`에 담겨 파이프라인에 전달됨.

**예시 (바지인 완전 끄기)**:
```python
_params = PipelineParams(allow_interruptions=False)
task = PipelineTask(pipeline, params=_params)
```

---

### 1.2 `interruption_strategies` (list, deprecated)

- **의미**: "언제만 인터럽션을 허용할지" 조건 부여 (예: 최소 N단어).
- **Deprecated**: 0.0.99부터. 대체: User Turn Strategies의 `MinWordsUserTurnStartStrategy` 등.

**예시 (최소 3단어 말했을 때만 TTS 중단)**:
```python
from pipecat.audio.interruptions.min_words_interruption_strategy import MinWordsInterruptionStrategy

_params = PipelineParams(
    allow_interruptions=True,
    interruption_strategies=[MinWordsInterruptionStrategy(min_words=3)]
)
task = PipelineTask(pipeline, params=_params)
```

- `allow_interruptions=True` 여야 전략이 적용됨.
- 봇이 말하는 중일 때만 적용; 봇이 침묵일 때는 사용자 발화가 그대로 처리됨.

---

## 2. User Turn Strategies (신규 권장, 0.0.99+)

Interruption 여부는 **"User Turn Start"** 전략의 **`enable_interruptions`** 로 제어.

### 2.1 Start 전략 공통 파라미터

- **`enable_interruptions`** (bool): 사용자 턴이 시작될 때 **interruption frame을 보낼지** 여부.  
  `False`면 사용자 말 시작만 감지하고, TTS를 끊는 인터럽션은 보내지 않음.
- **`enable_user_speaking_frames`** (bool): `UserStartedSpeakingFrame` 등 발화 시작/종료 프레임 발사 여부.

### 2.2 주요 Start 전략

| 전략 | 설명 | 인터럽션 제어 |
|------|------|----------------|
| **VADUserTurnStartStrategy** | VAD로 발화 시작 감지. 가장 빠름. | `enable_interruptions=True/False` |
| **TranscriptionUserTurnStartStrategy** | STT 결과(전사)로 턴 시작. | `enable_interruptions=True/False` |
| **MinWordsUserTurnStartStrategy(min_words=N)** | 최소 N단어 말했을 때만 턴 시작(바지인 시에는 이때만 인터럽션). | `enable_interruptions=True/False` |
| **ExternalUserTurnStartStrategy** | 외부 프로세서가 턴 시작 제어. | 기본 `enable_interruptions=False` |

**MinWords 예시 (최소 3단어일 때만 인터럽션)**:
```python
from pipecat.turns.user_start import MinWordsUserTurnStartStrategy
from pipecat.turns.user_stop import SpeechTimeoutUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)

# LLMContextAggregatorPair 를 쓰는 파이프라인인 경우
user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
    context,
    user_params=LLMUserAggregatorParams(
        user_turn_strategies=UserTurnStrategies(
            start=[MinWordsUserTurnStartStrategy(min_words=3)],
            stop=[SpeechTimeoutUserTurnStopStrategy()],
        ),
    ),
)
```

- 우리 파이프라인은 **RAGLLMProcessor** 기반이라 `LLMContextAggregatorPair` / `LLMUserAggregatorParams` 를 쓰지 않음.
- 따라서 **지금 구조에서는 PipelineParams 쪽 옵션이 실제로 동작하는 경로**임.

---

## 3. 우리 프로젝트에 적용할 때

### 옵션 A: 바지인 완전 끄기 (가장 단순)

- **목적**: TTS가 사용자 발화로 인해 절대 중단되지 않게.
- **방법**: `PipelineParams(allow_interruptions=False)` 로 Task 생성.
- **장점**: Pipecat이 InterruptionFrame을 안 보내므로, "Barge-in detected, stopping TTS" 자체가 나오지 않음.
- **단점**: 사용자가 말을 걸어도 봇이 문장을 끝까지 말함.

### 옵션 B: 최소 N단어일 때만 인터럽션 (deprecated API)

- **목적**: "네", "응" 같은 짧은 소리로는 TTS가 안 끊기고, 어느 정도 말했을 때만 끊기게.
- **방법**: `PipelineParams(allow_interruptions=True, interruption_strategies=[MinWordsInterruptionStrategy(min_words=3)])` (0.0.102에서 해당 API가 아직 있다면).
- **주의**: deprecated이며, 우리가 이미 쓰는 **BargeInSuppressProcessor**와 중복될 수 있음. Pipecat이 InterruptionFrame을 덜 보내는지, 우리가 계속 막는지 선택 필요.

### 옵션 C: 현재 방식 유지 (프레임 차단)

- **현재**: `allow_interruptions=True` + **BargeInSuppressProcessor**로 InterruptionFrame/InterruptionTaskFrame 흡수.
- **의미**: Pipecat은 "바지인 허용" 상태지만, 우리가 TTS 쪽으로 가는 인터럽션만 막음.
- **장점**: Pipecat 업데이트나 내부 경로 변경에 덜 의존하고, 우리 쪽에서만 제어 가능.

---

## 4. 참고 링크

- PipelineParams: https://docs.pipecat.ai/server/pipeline/pipeline-params  
- User Turn Strategies: https://docs.pipecat.ai/server/utilities/turn-management/user-turn-strategies  
- Interruption Strategies (deprecated): https://docs.pipecat.ai/server/utilities/turn-management/interruption-strategies  
- GitHub 예제: `examples/foundational/42-interruption-config.py`  
- MinWordsInterruptionStrategy (deprecated): `pipecat.audio.interruptions.min_words_interruption_strategy`  
- MinWordsUserTurnStartStrategy (신규): `pipecat.turns.user_start.MinWordsUserTurnStartStrategy`

---

## 5. 우리 파이프라인에서 MinWords가 안 먹는 이유

- **interruption_strategies(MinWords 등)** 는 **StartFrame**에 실려 전달되지만,  
  실제로 이걸 **읽어서 평가하는 쪽은 LLMUserAggregator / user turn 처리** 쪽이다.
- 우리 파이프라인은 **RAGLLMProcessor**만 쓰고 **LLMUserAggregator·LLMContextAggregatorPair** 를 쓰지 않는다.
- 그래서 **VAD·STT가 감지하면 곧바로** Interruption(Task)Frame을 보내며,  
  **MinWords를 검사하는 컴포넌트가 없어** 3단어 전략이 적용되지 않는다.
- 따라서 **바지인을 끄려면**  
  - **PipelineParams(allow_interruptions=False)**  
  - **VAD 래퍼에서 enable_barge_in=False** (VAD에서 나온 Interruption* 프레임 하류 전달 차단)  
  두 가지를 함께 적용하는 방식으로 처리한다.

---

## 6. 권장

- **"바지인으로 TTS가 끊기는 현상"만 없애고 싶다면**  
  → **옵션 A** (`allow_interruptions=False`) + **VAD 래퍼 enable_barge_in=False** 적용 (현재 적용됨).

- **MinWords(3단어)만 허용하고 싶다면**  
  → 표준 Pipecat 파이프라인(LLMContextAggregatorPair + user_turn_strategies)으로 구성해야 전략이 동작함.

- **지금처럼 "바지인은 켜두되, TTS는 우리 조건으로만 끊기게"** 유지하려면  
  → BargeInSuppressProcessor + Output 흡수 로직 유지. 필요 시 위와 함께 enable_barge_in=False 로 VAD 경로 차단.
