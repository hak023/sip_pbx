# 아웃바운드 STT 에코 잘림 근본 수정 및 미션 완료 설계

- **작성일**: 2026-04-02 15:30
- **상태**: 설계 완료 · 미구현
- **관련 버그**: `call_data_record_20260401.log` – `outbound-ob-963a739a-66092994`

---

## 1. STT 에코 잘림 — 인바운드 vs 아웃바운드 차이 분석

### 1-1. 파이프라인 체인 비교

| 단계 | 인바운드 | 아웃바운드 | 차이 |
|------|---------|-----------|------|
| VAD 설정 | `PipecatVADProcessor(enable_barge_in=True)` | 동일 | **없음** |
| STT 인스턴스 | `create_google_stt_service_per_pipeline()` | 동일 | **없음** |
| STT 파라미터 | `telephony` 모델, ko-KR, interim=True | 동일 | **없음** |
| `allow_interruptions` | `PipelineParams(allow_interruptions=True)` | 동일 | **없음** |
| barge-in 전략 | `MinWordsUserTurnStartStrategy(min_words=3)` | 동일 | **없음** |
| **TTS 재생 중 STT 차단** | **없음** | **없음** | **없음** ← 공통 미비점 |
| Greeting 방식 | 단상 (KB → TTS) | 이상 (KB p1 + LLM p2 + TTS 완료 대기) | **있음** |

**핵심 결론**: STT 파이프라인 자체는 인바운드·아웃바운드가 **동일**하다.  
STT 에코 문제가 인바운드에서 안 보이고 아웃바운드에서 보이는 이유는 STT 경로 차이가 아니라 **아웃바운드의 통화 패턴 특성** 때문이다.

---

### 1-2. 아웃바운드에서만 에코가 두드러지는 실제 이유

#### 현상 1: `"요 3점이요"` — 이전 TTS 음절 에코

```
TTS 출력: "저번 상담에 대해 만족도 조사 중입니다. 1점부터 5점까지 중 평가해주세요"
          → 마지막 음절: "요"
사용자 발화: "3점이요"
STT 인식: "요 3점이요"   (앞에 TTS 잔향이 RTP로 돌아옴)
```

**원인**: 아웃바운드는 **AI가 먼저 길게 말한 뒤 사용자가 짧게 답변**하는 패턴이다.  
TTS 재생이 끝난 직후 STT가 활성화되는 시점에 RTP 경로에 TTS 오디오 잔향(echoed audio)이 수ms~수백ms 남아있을 수 있다.  
인바운드에서도 동일한 잔향이 있지만, 인바운드는 사용자가 먼저 길게 말하므로 잔향이 묻히거나 barge-in으로 무시된다.

**실제 STT 스트리밍 동작**:
- `enable_interim_results=True`일 때 Google STT는 스트리밍 세션이 열려있는 동안 오디오를 지속 수신한다.
- TTS 재생 종료 → 그 다음 오디오 청크에 잔향이 포함 → STT가 `"요"` 를 인식하고 내부적으로 interim 결과에 누적 → 실제 사용자 발화 `"3점이요"` 가 뒤따라와 final 결과가 `"요 3점이요"` 가 됨.

#### 현상 2: `"5점이요"` → `"오점이."` — 발화 경계 조기 끊김

```
사용자 발화: "오(5)점이요"
VAD 인식:   발화 시작 감지 → 발화 종료 감지
STT 결과:   "오점이."  (요 앞에서 끊김)
```

**원인**: SileroVAD는 에너지/발화 패턴으로 발화 종료를 판단한다.  
`"오점이요"` 에서 `"요"` 는 짧고 낮은 에너지라 VAD가 `"이"` 뒤를 발화 종료로 판단한다.  
인바운드에서도 같은 현상이 생길 수 있지만, 인바운드는 주로 긴 문장 위주여서 티가 안 난다.

---

### 1-3. 근본 수정 방향

#### 수정 A: TTS 재생 중 STT VAD 억제 (가장 효과적)

`pipeline_builder.py`에서 아웃바운드 통화(`outbound_purpose` 있음)에 한해  
**TTS 오디오가 재생되는 동안 VAD에 오디오를 투입하지 않도록** `SIPPBXTransport` 또는  
`VADWrapperProcessor`에서 `_is_tts_playing` 플래그 기반 오디오 뮤팅을 구현한다.

```
구현 위치: VADWrapperProcessor.process_frame()
조건:     is_tts_playing == True 인 동안 InputAudioRawFrame을 STT에 전달하지 않음
           (VAD에는 전달해 음성 감지 상태를 유지, STT 입력만 억제)

연동:     tts_sync_context["tts_playing"] = True/False 를
           TTSCompleteNotifier 또는 SIPPBXOutputTransport에서 설정
```

**장점**: 근본적으로 TTS 잔향이 STT에 들어가는 것을 막는다.  
**단점**: 인바운드에서는 barge-in이 필요하므로 아웃바운드 전용 플래그로 제한해야 한다.

#### 수정 B: Google STT 스트리밍 발화 경계 설정 (telephony 모델)

`factory.py`의 `GoogleSTTService.InputParams`에 아웃바운드용 파라미터 추가:

```python
# 아웃바운드 전용 옵션 (짧은 답변 대응)
# telephony 모델에서 지원 여부 확인 필요
_params = GoogleSTTService.InputParams(
    languages=[Language.KO_KR],
    model="telephony",
    enable_automatic_punctuation=True,
    enable_interim_results=True,
    # 짧은 발화에서 조기 종료 방지 (모델이 지원 시)
    speech_end_sensitivity="LOW",   # ← 낮을수록 발화 종료를 늦게 판단
)
```

**주의**: Pipecat의 `GoogleSTTService.InputParams`가 이 파라미터를 노출하는지 확인 필요.

#### 수정 C: VAD 발화 종료 감도 조정

`vad_wrapper.py` 또는 VAD 설정에서 아웃바운드 통화 시 `stop_secs`(묵음 유지 시간) 을 늘림:

```python
# 인바운드: stop_secs=0.5s (현재)
# 아웃바운드: stop_secs=0.8~1.0s  (짧은 답변 "3점이요" 에서 "요" 가 잘리지 않도록)
```

**구현 위치**: `call_manager.py`의 `_start_outbound_ai` 안에서  
VAD 파라미터를 아웃바운드 전용으로 다르게 생성.

---

### 1-4. 우선순위 수정 추천

| 우선순위 | 수정 | 난이도 | 효과 |
|----------|------|--------|------|
| 1 | **수정 A**: TTS 재생 중 STT 입력 억제 | 중 | 에코 완전 차단 |
| 2 | **수정 C**: VAD stop_secs 아웃바운드 분리 | 하 | 발화 경계 잘림 개선 |
| 3 | **수정 B**: STT speech_end_sensitivity | 중 | 모델 지원 시 효과 |

`stt_korean_normalize.py`의 후처리는 수정 A·C 이후에도 **마지막 안전망**으로 유지한다.

---

## 2. 아웃바운드 미션 완료 — 비정형 발화 보강 설계

### 2-1. 현재 흐름 (문제 재정의)

```
사용자 발화 → _process_with_agent() 호출
  → _apply_outbound_rating_heuristic()   ← [이번 추가] 점수형만 처리
  → LangGraph 호출 → generate_response_node 실행
    (이 시점에 invoke_state.outbound_answers 반영됨)
  → AI 응답 TTS 출력
  → asyncio.create_task(_check_outbound_mission_complete())  ← 비동기 별도 태스크
```

**문제**: 비정형 발화(`"그만해"`, `"미친놈아!"`, `"끊어"` 등)일 때:
1. heuristic → 점수 추출 실패 → `outbound_answers` 미반영
2. `generate_response_node`: `unanswered` 남아있음 → `next_question` 있음 → **질문 반복**
3. `_check_outbound_mission_complete`: LLM에게 "대화에서 답했는가?" 물어봄  
   → LLM은 "답변이 없다"로 판단 → `all_done=false` → **또 반복**

### 2-2. 비정형 발화 분류 및 처리 설계

비정형 발화를 세 카테고리로 분류한다:

| 카테고리 | 예시 발화 | 처리 |
|----------|----------|------|
| **거부/중단 요청** | "그만해", "끊어", "싫어", "안 할래", "필요없어" | 미션 즉시 종료 (질문 반복 금지) |
| **욕설/감정 폭발** | "미친놈아", "꺼져", "짜증나" | 사과 후 1회만 재질문, 이후 거부로 처리 |
| **모호한 짧은 답변** | "음", "뭐", "예", "아" | 재질문 1회 허용 |

### 2-3. 구현 설계

#### (A) `stt_korean_normalize.py`에 발화 분류 함수 추가

```python
# 추가할 함수
def classify_outbound_response(user_text: str) -> str:
    """
    Returns: "refuse" | "abuse" | "ambiguous" | "answer"
    """
```

판단 기준:
- **refuse**: `["그만", "끊", "됐", "안 해", "싫어", "필요없", "괜찮아"]` 포함
- **abuse**: 욕설 키워드 목록 포함
- **ambiguous**: 2글자 이하 또는 의미없는 감탄사
- **answer**: 그 외 (점수, 의견, 설명 등)

#### (B) `rag_processor.py` — `_process_with_agent` 입구에 분류 삽입

```python
# _apply_outbound_rating_heuristic 이후에 추가
_outbound_response_type = classify_outbound_response(user_text)
logger.info("outbound_response_classified", type=_outbound_response_type, ...)

if _outbound_response_type == "refuse":
    # 거부 → 남은 질문 전부 "거부" 처리 후 즉시 미션 완료
    for uq in [q for q in self._outbound_questions if q not in self._outbound_answers]:
        self._outbound_answers[uq] = "__refused__"
    logger.info("outbound_mission_refused_all", ...)
    asyncio.create_task(self._trigger_mission_complete(self._call_id or ""))
    return  # LLM 호출 없이 즉시 종료 → TTS도 없음 (또는 짧은 작별 인사)

elif _outbound_response_type == "abuse":
    # 욕설 → 사과 TTS + 욕설 카운터 증가
    # 카운터 ≥ 2이면 거부로 간주
    self._outbound_abuse_count = getattr(self, '_outbound_abuse_count', 0) + 1
    logger.info("outbound_abuse_detected", count=self._outbound_abuse_count, ...)
    if self._outbound_abuse_count >= 2:
        # 재질문 없이 종료
        for uq in [q for q in self._outbound_questions if q not in self._outbound_answers]:
            self._outbound_answers[uq] = "__refused_abuse__"
        asyncio.create_task(self._trigger_mission_complete(self._call_id or ""))
        return
    # 첫 욕설: 사과 TTS만 내보내고 계속 (generate_response_node가 처리)
    # → outbound_extra에 abuse_flag 전달

elif _outbound_response_type == "ambiguous":
    # 모호한 짧은 답변 → 재질문 허용 (기존 동작 유지)
    pass

# "answer" → 기존 heuristic + LLM 경로 유지
```

#### (C) `generate_response.py` — 거부 플래그 반영

`generate_response_node`에서 `state.get("outbound_refused")` 확인:

```python
if state.get("outbound_refused"):
    # 작별 멘트만 생성 (질문 반복 금지)
    mission_instruction = (
        "규칙: 통화 거부 의사를 밝히셨습니다. "
        "정중히 감사 인사를 전하고 통화를 마무리하세요. 1문장으로."
    )
```

#### (D) `_check_outbound_mission_complete` — 단락 조건 추가

```python
# 모든 answers가 채워졌으면 (refused 포함) 즉시 complete
unanswered = [q for q in self._outbound_questions if q not in self._outbound_answers]
if not unanswered:
    await self._trigger_mission_complete(call_id)
    return
```

이 조건은 이미 있으나, `"__refused__"` 값도 답변으로 처리되므로 자동으로 종료된다.

### 2-4. 욕설 목록 및 거부 표현 목록 파일 분리

`stt_korean_normalize.py`가 커지므로 별도 파일로 분리 권장:

```
src/ai_voicebot/
  stt_korean_normalize.py      (기존 유지)
  outbound_response_classifier.py  (신규: 발화 분류 전용)
    - REFUSE_KEYWORDS
    - ABUSE_KEYWORDS
    - AMBIGUOUS_PATTERNS
    - classify_outbound_response()
```

---

## 3. 작업 범위 및 우선순위 요약

### 이번 작업에서 할 것

| 번호 | 작업 | 파일 | 우선순위 |
|------|------|------|---------|
| 1-C | VAD `stop_secs` 아웃바운드 분리 | `call_manager.py` | ★★★ |
| 1-A | TTS 재생 중 STT 입력 억제 | `vad_wrapper.py`, `tts_complete_notifier.py`, `tts_sync_context` | ★★★ |
| 2-A | `outbound_response_classifier.py` 신규 | 신규 파일 | ★★★ |
| 2-B | `_process_with_agent` 거부/욕설 분기 | `rag_processor.py` | ★★★ |
| 2-C | `generate_response_node` 거부 플래그 | `generate_response.py` | ★★ |

### 다음 작업으로 미룰 것

| 번호 | 작업 | 이유 |
|------|------|------|
| 1-B | STT `speech_end_sensitivity` | Pipecat API 지원 여부 확인 필요 |

---

## 4. 연관 파일 목록

- `sip-pbx/src/sip_core/call_manager.py` — 아웃바운드 VAD 파라미터 분리
- `sip-pbx/src/ai_voicebot/pipecat/processors/vad_wrapper.py` — TTS 재생 중 STT 억제
- `sip-pbx/src/ai_voicebot/pipecat/processors/tts_complete_notifier.py` — `tts_playing` 플래그 설정
- `sip-pbx/src/ai_voicebot/pipecat/processors/rag_processor.py` — 거부/욕설 분기
- `sip-pbx/src/ai_voicebot/langgraph/nodes/generate_response.py` — 거부 플래그 처리
- `sip-pbx/src/ai_voicebot/outbound_response_classifier.py` (신규)
- `sip-pbx/src/ai_voicebot/factory.py` — 아웃바운드 STT 파라미터 분리 (선택)
