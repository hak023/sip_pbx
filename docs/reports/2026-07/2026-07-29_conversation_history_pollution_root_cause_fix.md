# conversation_history 오염발 메타 JSON 유출 근본 원인 수정 + Story 4.2 Task 5 섀도우 로깅

**작성일**: 2026-07-29
**작성자**: Copilot (BMAD Dev/QA 역할)
**상태**: 완료
**관련 문서**:
- [4.2.ttft-safe-subset-implementation.story.md](../../stories/4.2.ttft-safe-subset-implementation.story.md)
- [2026-07-29_story_3.3_and_4.2_stage1_implementation.md](2026-07-29_story_3.3_and_4.2_stage1_implementation.md)(이전 리포트, 결함 최초 발견 기록)

## 배경

이전 세션에서 Story 4.2 Task 6(실서버 스모크 테스트) 도중, 본 스토리 변경과 무관해 보이는
간헐적 실패(`tts_response_meta_json_blocked`, 3회 중 1회 재현)를 발견했다. 사용자가 "지금 조사·
수정을 진행"하도록 지시해 근본 원인을 규명하고 수정했다.

## 근본 원인

`LLMClient.generate_response()`(`src/ai_voicebot/ai_pipeline/llm_client.py`)는 **호출 목적과
무관하게 항상** 요청/응답을 인스턴스 전역 `self.conversation_history`에 append한다. 그런데
`classify_intent_node`(의도 분류)·`rewrite_query_node`(쿼리 재작성)·`knowledge_service`(지식
라벨 생성)처럼 **사용자에게 전혀 들려주지 않는 내부 LLM 호출**도 동일한 `generate_response()`를
호출하고 있었다.

한 턴 안에서 실행 순서는 다음과 같다:

```
classify_intent_node → llm.generate_response(classify_prompt) → conversation_history에
    {"role": "user", "content": classify_prompt}
    {"role": "assistant", "content": '{"intent": "chitchat", "search_query": "..."}'}
    append됨
        ↓
generate_response_streaming_node → llm.generate_response_streaming(...)
    → _build_conversation_prompt()가 conversation_history[-10:]를 "이전 대화"로 프롬프트에 삽입
    → 프롬프트에 "AI: {"intent": "chitchat", "search_query": "..."}"가 직전 발화처럼 포함됨
    → 모델이 이 패턴을 모방해 자연어 대신 JSON을 그대로 반환하는 경우가 간헐적으로 발생
```

즉, 내부 분류용 호출의 부산물이 실제 응답 생성 LLM의 few-shot 컨텍스트를 오염시킨 것이 원인이었다.

## 수정 내용

1. `LLMClient.generate_response()`에 `update_history: bool = True` 파라미터 추가 — `False`면
   `conversation_history` append를 건너뛴다(하위 호환을 위해 기본값은 기존과 동일한 `True`).
2. 아래 3개 내부 전용 호출부를 `update_history=False`로 수정:
   - `src/ai_voicebot/langgraph/nodes/classify_intent.py`(의도 분류)
   - `src/ai_voicebot/langgraph/nodes/rewrite_query.py`(쿼리 재작성)
   - `src/ai_voicebot/knowledge/knowledge_service.py`(지식 라벨 생성)
3. `step_back_prompt.py`도 동일 패턴이나, 2026-04-03에 이미 그래프에서 제거된 죽은 코드(미사용
   확인됨)라 이번엔 수정하지 않음.

## 검증

- **단위 회귀**: `tests_new/unit` 전체(무관 사전 결함 3개 파일 제외) 370+건 통과. 기존 mock들이
  `generate_response(self, **kwargs)` 형태라 신규 파라미터에 영향받지 않음을 확인.
- **실서버(사용자 재시작 후)**: 프로세스 시작 시각이 모든 수정 파일의 최종 수정 시각보다 늦음을
  확인해 최신 코드 반영 확인. 동일 chitchat 발화("안녕하세요, 오늘 날씨 진짜 좋네요") 8회 반복
  실행 → **8/8 정상**(수정 전 재현율 1/3, 즉 약 33% 실패 → 수정 후 0%). `app.log`를 조회해
  수정 이후 시점에 `tts_response_meta_json_blocked` 신규 발생이 없음을 확인(기존 2건은 모두
  재시작 이전 타임스탬프).

## Story 4.2 Task 5 사전 준비 — 섀도우(로깅 전용) 콜백

사용자 요청("barge-in 실제 통화 테스트는 나중에, 지금은 로그를 상세히 남겨두자")에 따라
`rag_processor.py`의 `process_utterance()` 호출에 `on_first_sentence=_shadow_on_first_sentence`
콜백을 연결했다. **TTS 프레임은 전혀 건드리지 않고 로깅만** 수행한다:

- `ttft_shadow_first_sentence_would_fire`: Story 4.1 안전 서브셋 조건이 충족되어 "조기 전송이
  가능했을 시점"을 턴 시작 후 경과 시간과 함께 기록.
- `langgraph_agent_turn_cancelled`(기존 이벤트)에 `ttft_shadow_fired_before_cancel`/
  `ttft_shadow_fired_sec_before_cancel` 필드를 추가 — 섀도우 발동 이후 이 턴이 실제로
  Supersede/취소됐는지를 상관관계로 기록.

이 로깅은 실제 통화(SIP)를 통해서만 트리거되며(텍스트 QA 하네스는 `rag_processor.py`를 거치지
않는 별도 경로), 다음 실통화 QA 시 이 로그만 집계하면 "조기 송출이 가능했던 턴이 실제로 얼마나
자주 barge-in으로 취소되는지"를 코드 변경 없이 사전 파악할 수 있다.

## 다음 단계

1. 실제 통화(음성) QA 시 `ttft_shadow_first_sentence_would_fire` / `ttft_shadow_fired_before_cancel`
   로그를 수집해 barge-in 상호작용 리스크의 실제 빈도를 파악한다.
2. 리스크가 낮다고 판단되면 Story 4.2 Task 5(실제 TTS push_frame 연결, 2단계)를 진행한다.
3. Story 4.3(TTFT 실측 검증) → Story 5.2 재작성 → 5.3 → 5.4 순서로 계속 진행.

---
*최종 업데이트: 2026-07-29*
