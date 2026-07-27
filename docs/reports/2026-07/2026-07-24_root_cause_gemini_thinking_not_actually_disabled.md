# [근본 원인 확정] chitchat 응답 6.8~9.6초 지연 — Gemini "thinking" 비활성화가 실제로는 동작하지 않음

**작성일**: 2026-07-24
**심각도**: 🔴 Critical — 시스템 전체 LLM 호출에 영향(chitchat뿐 아니라 classify_intent 3차 LLM 분류,
self-service Tool-calling 등 `LLMClient`를 쓰는 모든 경로)
**관련 문서**:
- [2026-07-24_ai_pipeline_qa_endpoint_and_latency_findings.md](2026-07-24_ai_pipeline_qa_endpoint_and_latency_findings.md) — 이 리포트가 다루는 9.6~9.75초 재현 케이스의 상세 breakdown
- [voice-latency-turn-taking-architecture.md](../../architecture/voice-latency-turn-taking-architecture.md)
- [../../src/ai_voicebot/ai_pipeline/llm_client.py](../../src/ai_voicebot/ai_pipeline/llm_client.py)

## 문제 요약

`agent_elapsed_sec=9.66초`(chitchat)의 원인을 `langgraph_node_durations_sec` 로그로 노드별 분해한
결과, 지연이 **오케스트레이션 오버헤드가 아니라 `generate_response` 노드 하나(6.8~9.6초)**에
집중되어 있었다. 이 시간은 `llm_first_sentence_ready` 이벤트(Gemini `generate_content(stream=True)`
호출 시작~첫 문장 텍스트 확보까지)와 정확히 일치해, **LLM API 호출 자체의 TTFT(첫 토큰까지의
시간)**가 원인임을 확인했다. 프롬프트 길이는 848~876자로 매우 짧아 프롬프트 크기는 원인이 아니다.

## 근본 원인 (코드 + 실제 SDK 상태를 직접 확인해 확정, 추측 없음)

`src/ai_voicebot/ai_pipeline/llm_client.py`의 `_thinking_off()`가 모든 LLM 호출에서 Gemini 2.5
Flash의 "thinking"(내부 추론) 모드를 끄도록 설계되어 있고, 코드 주석에도 "thinking 활성화 시
TTFT 3~6초 지연 발생"이라고 명시되어 있다. 그러나 이 메커니즘이 **실제로는 단 한 번도 동작한 적이
없다**:

```python
@staticmethod
def _thinking_off() -> Any:
    try:
        return genai.types.ThinkingConfig(thinking_budget=0)
    except (AttributeError, TypeError):
        logger.debug("llm_thinking_config_not_supported", ...)  # ← 이 경로가 항상 실행됨
        return None
```

실제 설치된 SDK(`google-generativeai==0.8.6`, **2026-07-24 기준 이미 공식 지원 종료(deprecated)
패키지**)를 직접 임포트해 확인한 결과:

```
>>> genai.types.ThinkingConfig(thinking_budget=0)
AttributeError: module 'google.generativeai.types' has no attribute 'ThinkingConfig'
```

`protos.GenerationConfig`의 실제 protobuf 필드 목록(`candidate_count`, `stop_sequences`,
`max_output_tokens`, `temperature`, `top_p`, `top_k`, `response_mime_type`, `response_schema`,
`presence_penalty`, `frequency_penalty`, `response_logprobs`, `logprobs`,
`enable_enhanced_civic_answers`, `response_modalities`, `speech_config`)에도 **thinking 관련 필드가
전혀 존재하지 않는다** — 이 SDK가 번들한 protobuf 스키마 자체가 Gemini 2.5 thinking 기능이
API에 추가되기 이전 버전이라, **애초에 이 SDK로는 thinking을 끌 방법이 없다.**

`_thinking_off()`의 `except (AttributeError, TypeError): pass` 구문이 이 실패를 **완전히
침묵시켜(로그도 debug 레벨이라 운영 로그에서 사실상 안 보임)**, 코드를 작성한 개발자도 이후
누구도 "thinking이 실제로 꺼지고 있는지"를 검증하지 못한 채 몇 달간 유지된 것으로 보인다.

## 결론

- **Gemini 2.5 Flash의 thinking 모드가 이 시스템의 모든 LLM 호출에서 사실상 항상 켜져 있었다.**
  chitchat 응답뿐 아니라 `classify_intent_node`의 3차 LLM 분류, self-service Tool-calling,
  booking_agent 등 `LLMClient`/`generate_response_streaming`/`generate_simple`을 쓰는 **모든 경로가
  동일한 지연 패턴의 영향을 받고 있을 가능성이 높다**(이번 실측에서 `classify_intent`가 2.845초
  걸린 케이스도 동일 원인으로 추정 — 별도 검증 필요).
- 이는 2026-03-30 리포트의 "평균 8.69초" 실측치, 그리고 오늘 재현한 6.8초·9.617초와 정확히
  같은 크기(수 초)의 지연이며, "thinking 활성 시 TTFT 3~6초+"라는 기존 코드 주석의 경고와도
  정합한다 — **즉 이 프로젝트의 응답 지연 문제 대부분은 TTFT 스트리밍 아키텍처 문제가 아니라
  이 SDK 버그(thinking 비활성화 실패)가 근본 원인일 가능성이 매우 높다.**
- Epic 4(TTFT 파이프라인 전환)는 여전히 유효한 개선이지만, **thinking이 계속 켜진 채로는 TTFT를
  아무리 개선해도 "첫 문장"까지 6~9초가 걸리는 것 자체는 해결되지 않는다** — 우선순위 재검토
  필요.

## 권장 조치 (결정 필요, 코드 변경 전 사용자 확인)

1. **`google-generativeai` → `google-genai` SDK 마이그레이션** (Google 공식 권고, deprecated
   패키지 경고에 명시된 유일한 공식 경로). `google-genai`는 `types.ThinkingConfig(thinking_budget=0)`
   를 정식 지원한다. 다만 API 표면이 달라 `llm_client.py` 전반의 마이그레이션이 필요(범위가 크고
   `booking_gemini_fc.py` 등 다른 모듈과의 연동도 함께 검토 필요 — 별도 Story로 분리 권장).
2. **(임시 완화, 비권장)** 특정 REST 필드(`generationConfig.thinkingConfig.thinkingBudget`)를
   SDK를 우회해 raw HTTP 요청으로 직접 보내는 방법 — SDK 마이그레이션 전 임시 조치로 가능하나
   유지보수성이 떨어짐.
3. **(대안, 검증 결과 실패 — 채택 불가)** thinking budget을 지원하지 않는 대신 더 저지연인
   모델로 임시 전환 시도. 실제 API 키로 확인한 결과:
   - `gemini-2.0-flash` → **완전 폐지(404 "no longer available")**
   - `gemini-2.5-flash-lite` → **이 계정에서 신규 사용 불가(404 "no longer available to new users")**
   - 즉 현재 사용 가능한 Gemini 모델 중 thinking 없는 대안이 이 계정에는 존재하지 않는다.
   **대안 3은 채택 불가로 결론**, 조치 1(SDK 마이그레이션) 또는 2(REST 우회) 중 선택 필요.

**본 리포트는 원인 확정까지만 수행했으며, 위 조치 중 어떤 것을 채택할지는 사용자 결정이 필요하다
(SDK 마이그레이션은 시스템 전반에 영향을 주는 큰 변경이므로 별도 PRD/Story로 분리해 계획 후
착수 권장).**

## 부록: 서버 재기동 지연 이슈(별건, 같은 세션에서 발견)

thinking 검증을 위해 여러 차례 재시작하는 과정에서 `TextEmbedder`(`sentence-transformers`
`paraphrase-multilingual-mpnet-base-v2`, 로컬 캐시 로드) 초기화가 매번 170~183초 걸리는 현상을
발견했다(평소 ~5.5초). 반복할수록 느려져 OS 파일 캐시 문제가 아니라 **Windows Defender 실시간
검사가 venv/HuggingFace 캐시의 대용량 바이너리를 매번 재검사하는 것으로 추정**된다. 사용자가
`Add-MpPreference -ExclusionPath`로 `sip-pbx\venv`, `~/.cache/huggingface`, `sip-pbx\data`를
제외 목록에 추가 완료(효과 검증은 다음 재시작에서 확인 예정, 이 리포트와는 별개 이슈이므로
후속 조사 필요 시 별도 리포트로 분리).

*최종 업데이트: 2026-07-24*
