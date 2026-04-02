# 아웃바운드 STT 억제 + 비답변 분기 구현 완료 보고

- **작성일**: 2026-04-02 17:00
- **상태**: 구현 완료
- **관련 설계**: `sip-pbx/docs/reports/2026-04/2026-04-02_1530_OUTBOUND_STT_ECHO_AND_MISSION_COMPLETE_DESIGN.md`

---

## 1. STT 에코 근본 수정 (1-A)

### 문제
아웃바운드 통화에서 TTS 재생 중 RTP 에코가 STT로 유입되어:
- TTS 끝부분 "요"가 다음 발화 앞에 붙음 (`"요 3점이요?"`)
- TTS 재생 중 STT가 활성화되어 TTS 음성 자체가 짧은 발화로 인식됨

### 구현 내용

#### `tts_complete_notifier.py`
- `LLMFullResponseStartFrame` 수신 시 `tts_sync_context["tts_playing"] = True` 설정
- `LLMFullResponseEndFrame` 수신 후 **0.3초 딜레이** 후 `tts_playing = False` 해제
  - 0.3초 버퍼: RTP tail echo 흡수 (TTS 합성 완료 후 실제 RTP 재생 종료까지 지연 대응)
- 새 상수: `KEY_TTS_PLAYING = "tts_playing"`

#### `vad_wrapper.py` (VADWrapperProcessor)
- 생성자에 신규 파라미터 추가:
  ```python
  suppress_stt_during_tts: bool = False
  tts_sync_context: Optional[dict] = None
  ```
- `InputAudioRawFrame` 처리 시:
  - `suppress_stt_during_tts=True` + `tts_sync_context["tts_playing"]=True` 이면 `return` (STT 하류로 전달 안 함)
  - 억제 해제 시 `vad_stt_suppression_ended` 로그 출력 (억제된 프레임 수 포함)
- **중요**: VAD 자체에는 계속 `process_frame()` 전달 → VAD 상태 유지 (barge-in 로직 무결)

#### `wrap_vad_with_logging()` 함수
- `suppress_stt_during_tts`, `tts_sync_context` 파라미터 추가해 외부에서 주입 가능

#### `pipeline_builder.py`
- `build_pipeline()` 에 `is_outbound: bool = False` 파라미터 추가
- `wrap_vad_with_logging()` 호출 시 `is_outbound` 여부에 따라 억제 활성화:
  ```python
  vad_wrapped = wrap_vad_with_logging(
      vad,
      call_id=call_id,
      enable_barge_in=True,
      suppress_stt_during_tts=is_outbound,
      tts_sync_context=tts_sync_context if is_outbound else None,
  )
  ```
- `build_and_run()` 에서 `_is_outbound = bool(outbound_purpose or outbound_questions)` 로 자동 판별

### 적용 범위
- **아웃바운드만** TTS 재생 중 STT 억제 활성화
- **인바운드**는 기존 동작 그대로 (변경 없음)

---

## 2. 미션 완료 비답변 분기 재설계 (2-B/C)

### 사용자 피드백
> "욕설, 감탄사, 거절 등은 답이 안 되었으니 공통적으로 다시 LLM을 통해 적절한 응대와 질문으로 이어나가면 돼."

### 구현 내용

#### `rag_processor.py` (`_process_with_agent`)
heuristic 적용 전·후로 `_outbound_answers` 변화를 비교:

```python
_unanswered_before = {q for q in self._outbound_questions if q not in self._outbound_answers}
self._apply_outbound_rating_heuristic(user_text)
_unanswered_after = {q for q in self._outbound_questions if q not in self._outbound_answers}

# 답변이 추가되지 않았으면 non_answer
_is_non_answer = bool(_unanswered_before) and (_unanswered_after == _unanswered_before)
```

- `outbound_non_answer=True` 를 LangGraph state에 전달

#### `agent.py`
- `invoke_state["outbound_non_answer"] = bool(kwargs.get("outbound_non_answer", False))` 추가

#### `state.py`
- `outbound_non_answer: bool` 필드 추가

#### `generate_response.py` (`generate_response_node`)
- `outbound_non_answer` 플래그에 따라 다른 `mission_instruction` 프롬프트 적용:

| `outbound_non_answer` | 프롬프트 방향 |
|---|---|
| `False` (정상 발화) | 발화에 반응 → 다음 질문 자연스럽게 이어서 질문 |
| `True` (비답변) | 발화를 자연스럽게 받아줌 → **표현을 바꿔서** 같은 질문 재질문 |

- `"질문을 그대로 반복하지 말고 표현을 약간 바꿔서 자연스럽게 물어보세요"` 지시 포함

### 적용 케이스
- `"미친놈아!"` → non_answer=True → "죄송합니다, 혹시 저번 상담 서비스는 어떠셨나요?"
- `"그만해."` → non_answer=True → "불편하게 해드려 죄송합니다. 잠깐만요, 평점을 1점부터 5점 중 하나로 말씀해 주실 수 있을까요?"
- `"음..."` → non_answer=True (점수 패턴 미매칭) → 재질문
- `"오점이요"` → heuristic 적용 → non_answer=False → 정상 완료 처리

---

## 변경 파일 목록

| 파일 | 변경 내용 |
|---|---|
| `src/ai_voicebot/pipecat/processors/tts_complete_notifier.py` | `tts_playing` 플래그 set/clear |
| `src/ai_voicebot/pipecat/processors/vad_wrapper.py` | TTS 중 STT 억제 로직, `wrap_vad_with_logging` 파라미터 추가 |
| `src/ai_voicebot/pipecat/pipeline_builder.py` | `is_outbound` 파라미터, 아웃바운드 억제 활성화 |
| `src/ai_voicebot/pipecat/processors/rag_processor.py` | non_answer 판별 + outbound_extra 주입 |
| `src/ai_voicebot/langgraph/agent.py` | `outbound_non_answer` invoke_state 전달 |
| `src/ai_voicebot/langgraph/state.py` | `outbound_non_answer` 필드 추가 |
| `src/ai_voicebot/langgraph/nodes/generate_response.py` | non_answer 분기 프롬프트 적용 |
