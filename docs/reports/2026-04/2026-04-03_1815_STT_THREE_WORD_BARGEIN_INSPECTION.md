# STT 3단어·바지인(Barge-in) 점검

- **작성일**: 2026-04-03 (로컬)
- **상태**: 코드 분석 완료 (이번 작업에서 소스 변경 없음)
- **관련 경로**: `sip-pbx/src/ai_voicebot/pipecat/pipeline_builder.py`, `sip-pbx/src/ai_voicebot/pipecat/barge_in_strategy.py`, Pipecat `0.0.102` (`pipeline/task.py`)

## 요약

「AI 발화 중 STT로 **3단어 이상** 들어왔을 때만 TTS를 멈추고 사용자 발화를 처리한다」는 동작은 **현재 파이프라인에서 사실상 연결되어 있지 않습니다.**  
주석·문서·`MinWordsUserTurnStartStrategy` 생성 코드는 있으나, **Pipecat `PipelineTask`가 해당 인자를 받지 않아 조용히 폴백**되고, STT 기반 3단어 게이트용 **`SmartBargeInProcessor`는 파이프에 없습니다.**

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|------------|------|------|
| (없음) | - | 본 문서는 분석 전용, 코드 수정 없음 | - |

## 1. 기대했을 수 있는 두 가지 구현

| 구분 | 역할 | 현재 상태 |
|------|------|-----------|
| **A. `MinWordsUserTurnStartStrategy(min_words=3)`** | 사용자 턴 시작(및 바지인 시 인터럽션)을 N단어 이상일 때만 인정 | `pipeline_builder`에서 `UserTurnStrategies` 생성 후 `PipelineTask(..., user_turn_strategies=...)` 로 전달 시도 |
| **B. `SmartBargeInProcessor`** | STT `TranscriptionFrame`을 보고 3단어·키워드·(선택) LLM으로 `StartInterruptionFrame` 여부 결정 | `barge_in_strategy.py`에만 존재, **파이프라인 체인에 미포함** |

## 2. A안이 먹히지 않는 이유 (Pipecat 0.0.102)

`pipecat.pipeline.task.PipelineTask.__init__` 시그니처에 **`user_turn_strategies` 파라미터가 없습니다.**  
공식 권장은 `LLMUserAggregator` / `LLMContextAggregatorPair`의 `user_turn_strategies` 쪽입니다.

현재 프로젝트 코드:

```323:344:c:\work\workspace_sippbx\sip-pbx\src\ai_voicebot\pipecat\pipeline_builder.py
        # 바지인 켬: 3단어 이상 말했을 때만 TTS 중단 (새 API: user_turn_strategies, DeprecationWarning 없음)
        if PipelineParams is None:
            _params = None
            task = PipelineTask(pipeline)
        else:
            _user_turn_strategies = None
            if _USER_TURN_STRATEGIES_AVAILABLE and MinWordsUserTurnStartStrategy is not None and UserTurnStrategies is not None:
                try:
                    _user_turn_strategies = UserTurnStrategies(
                        start=[MinWordsUserTurnStartStrategy(min_words=3)],
                    )
                except Exception as e:
                    logger.debug("user_turn_strategies_init_skip", error=str(e))
            # PipelineParams: allow_interruptions=True로 바지인 활성화 (interruption_strategies는 deprecated, 사용 안 함)
            _params = PipelineParams(allow_interruptions=True)
            try:
                if _user_turn_strategies is not None:
                    task = PipelineTask(pipeline, params=_params, user_turn_strategies=_user_turn_strategies)
                else:
                    task = PipelineTask(pipeline, params=_params)
            except TypeError:
                task = PipelineTask(pipeline, params=_params)
```

- `_user_turn_strategies`가 정상 생성되면 **`PipelineTask(..., user_turn_strategies=...)` 호출 시 `TypeError`** 가 납니다.
- 그 예외가 **`except TypeError`에서 삼켜지고**, 결과적으로 **`PipelineTask(pipeline, params=_params)`만 실행**됩니다.
- 따라서 **3단어 전략 객체는 만들어지지만 Task에 붙지 않습니다.**

또한 내부 문서 `docs/reports/2026-03/PIPECAT_BARGE_IN_OPTIONS.md` §5에 정리된 대로, **`RAGLLMProcessor`만 쓰고 `LLMUserAggregator`를 쓰지 않는 구조**에서는 턴 전략이 평가될 위치가 원래도 부족합니다.

## 3. B안(`SmartBargeInProcessor`) 상태

`SmartBargeInProcessor`는 주석상 위치가 `STT → [SmartBargeIn] → RAG-LLM` 이지만, `pipeline_builder`의 `processor_names` / `Pipeline([...])` 에 **등장하지 않습니다.**  
즉 **STT 텍스트 기준 3단어 게이트는 실행 경로에 없습니다.**

## 4. 실제로 TTS를 끊는 경로 (참고)

- `allow_interruptions=True` + VAD/STT 쪽에서 올라오는 **`StartInterruptionFrame` / `InterruptionFrame`** 등이 TTS 중단을 유발하는 일반적인 Pipecat 동작입니다.
- 커스텀 `PipecatVADProcessor`는 **오디오/VAD·`is_barge_in()` 기준**으로 인터럽트를내며, **STT 단어 수와는 별개**입니다.

그래서 체감상:

- 「3단어 넘게 말했는데도 AI가 안 멈춤」→ 위 A/B 미연결 + 인터럽트가 다른 조건에만 걸리는 경우 등과 일치할 수 있고,
- 「짧게 말했는데 끊김」→ VAD/에코/스마트폰 환경 등 **단어 수 게이트가 없어서** 발생할 수 있습니다.

## 5. 권장 후속 (구현 시 선택지)

1. **STT 후단 게이트**: `stt`와 `rag_llm` 사이에 `SmartBargeInProcessor` 삽입(또는 동등 로직), `tts_playing`과 `InterimTranscriptionFrame`/`TranscriptionFrame` 연동을 명확히 할 것.
2. **Pipecat 표준 턴 관리**: `LLMContextAggregatorPair` + `LLMUserAggregatorParams(user_turn_strategies=...)` 로 파이프 재구성(대규모 변경).
3. **폴백 제거·가시화**: `PipelineTask`에 없는 kwargs를 넘기기 전에 Pipecat 버전별 시그니처를 확인하고, `TypeError` 삼키기 대신 **로그로 “3단어 전략 미적용”을 경고**해 재발을 막을 것.

---

## 참고

- `sip-pbx/docs/reports/2026-03/PIPECAT_BARGE_IN_OPTIONS.md` (특히 §5)
