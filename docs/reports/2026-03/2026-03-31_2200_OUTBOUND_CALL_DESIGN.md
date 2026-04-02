# 아웃바운드 통화 AI 대화 설계서 (v2)

| 항목 | 내용 |
|------|------|
| 작성일 | 2026-03-31 22:00 |
| 최종 업데이트 | 2026-03-31 22:30 (리서치 반영) |
| 상태 | 설계 확정 (구현 대기) |
| 대상 | SIP PBX AI 아웃바운드 통화 시나리오 |
| 관련 파일 | `sip_endpoint.py`, `rtp_relay.py`, `rag_processor.py`, `call_manager.py` |

---

## 1. 목표 시나리오

착신자가 전화를 받으면 AI Bot이 아래 흐름으로 대화를 진행한다.

```
1. 착신자 수신 확인 (200 OK)
2. AI 인사 (KB: greeting_phase1)
3. 통화 목적 발화 + 첫 번째 질문 던지기
4. 착신자 답변 수신 → STT → RAG 응대
5. 목적 달성 여부 판단 (LLM)
   ├─ 미달성: 다음 질문 or 자체 LLM 응대 → 4로 반복
   └─ 달성: 종료 멘트 (KB: farewell or 하드코딩) → SIP BYE
```

---

## 2. 현재 구현 상태 (As-Is)

### 2.1 RTP 포트 할당 — 버그 확인됨

**파일:** `src/sip_core/sip_endpoint.py` 4319–4327행

```python
# ❌ 문제: caller_leg와 callee_leg에 동일한 포트 배정
media_session.caller_leg.allocated_ports = [local_rtp_port, local_rtcp_port]
media_session.callee_leg.allocated_ports = [local_rtp_port, local_rtcp_port]
```

**결과:** `rtp_relay.py`의 `start()`에서 `caller_audio_rtp`(포트 10000) 바인딩 성공 후, `callee_audio_rtp`(동일 포트 10000) 바인딩 시도 → `[WinError 10048] 주소 이미 사용 중` 에러 → **착신자에게 오디오 전달 불가**.

### 2.2 인사 로직 — 아웃바운드 분기 없음

**파일:** `src/ai_voicebot/pipecat/processors/rag_processor.py` `send_greeting()` 함수

```python
# ❌ 문제: 인바운드와 동일한 인사 로직 사용
# purpose/questions 분기 없음
greeting = await self._agent.generate_greeting()          # KB greeting_phase1
cap_raw  = await self._agent.generate_capability_guide()  # KB greeting_phase2
```

- `_outbound_purpose`와 `_outbound_questions`가 `set_outbound_mission()`에 저장되어 있지만  
  `send_greeting()`에서는 참조하지 않음
- 착신자는 "무엇을 도와드릴까요?" 수준의 인바운드용 안내를 받게 됨

### 2.3 미션 체크 트리거

**파일:** `rag_processor.py` 1733–1738행

```python
# 각 턴의 LLM 응답 후 비동기로 미션 체크
if self._outbound_purpose or self._outbound_questions:
    asyncio.create_task(self._check_outbound_mission_complete(response), ...)
```

- 대화 이력이 비어 있으면 즉시 `return` → **첫 번째 착신자 발화 전에는 체크 안 됨** (정상)
- `_check_outbound_mission_complete()` 내에서 LLM 추가 호출하여 답변 수집 여부 판단

### 2.4 미션 완료 판단 — 취약한 문자열 매칭

**파일:** `rag_processor.py` 303행

```python
# ❌ 문제: 단순 부분 문자열 매칭 — 오판 가능성 높음
if result_text and "예" in result_text:
    await self._trigger_mission_complete(call_id)
```

- `"예" in result_text`는 "예를 들어", "예약" 등 다른 단어에서도 True가 됨
- JSON 형식으로 답변을 받는 `_outbound_questions` 경로와 일관성이 없음

### 2.5 종료 멘트 — 하드코딩됨

**파일:** `rag_processor.py` 322행

```python
farewell_text = "필요한 내용을 모두 확인했습니다. 감사합니다. 좋은 하루 되세요."
```

- KB의 `farewell` 카테고리 문서를 참조하지 않음

### 2.6 TTS 완료 대기 — 고정 sleep

**파일:** `rag_processor.py` 332행

```python
await asyncio.sleep(3.0)   # ❌ 고정 3초 — TTS 길이와 무관하게 대기 또는 조기 종료
```

### 2.7 음성 사서함(Voicemail) 감지 없음

- 착신자가 부재 중이거나 음성사서함으로 연결될 경우 감지 로직 없음
- AI가 음성사서함 안내 음성을 사람으로 오인하여 응대할 수 있음

### 2.8 통화 최대 시간 안전장치 없음

- `max_duration` 설정은 `OutboundCallManager`에서 SIP 레벨로 전달되나,  
  AI 파이프라인 내에 **독립적인 타임아웃 가드**가 없음

---

## 3. 수정 설계 (To-Be)

### 3.1 [수정 1 — 긴급] RTP 포트 할당 분리 — `sip_endpoint.py`

**위치:** `_start_outbound_rtp_worker()` 메서드 내 `MediaSession` 생성 부분 (4319–4327행)

**변경 내용:**

```python
media_session.caller_leg = MediaLeg()
media_session.caller_leg.original_ip = callee_ip
media_session.caller_leg.original_audio_port = local_rtp_port
media_session.caller_leg.allocated_ports = [local_rtp_port, local_rtcp_port]

# ✅ 수정: callee_leg 소켓 바인딩 스킵 (ai_mode=True에서 불필요)
media_session.callee_leg = MediaLeg()
media_session.callee_leg.original_ip = callee_ip
media_session.callee_leg.original_audio_port = callee_rtp_port
media_session.callee_leg.allocated_ports = [0, 0]   # ← 변경: 바인딩 스킵
```

**근거:**  
- `rtp_worker.ai_mode = True` 설정 시, `RTPRelayWorker`는 `caller_audio_rtp` 소켓에서  
  Pipecat이 생성한 RTP를 착신자(`callee_endpoint`)로 직접 전송하는 구조
- `callee_leg` 소켓은 AI 모드에서 실제 데이터를 수신·처리하지 않으므로 바인딩 불필요
- `allocated_ports = [0, 0]` → `get_audio_rtp_port()` → `0` 반환 →  
  `rtp_relay.start()`에서 `if callee_audio_rtp_port:` 조건 `False` → 바인딩 스킵 (기존 방어 로직 활용)

---

### 3.2 [수정 2 — 높음] 아웃바운드 인사 로직 — `rag_processor.py`

**위치:** `send_greeting()` 메서드

**변경 목표:** 아웃바운드인 경우 KB 인사(Phase 1) + 목적 + 첫 질문(Phase 2) 조합 발화

```python
async def send_greeting(self):
    ...
    if self._outbound_purpose:          # ✅ 아웃바운드 모드 분기 추가
        # Phase 1: KB greeting_phase1 (인사)
        if self._agent_available:
            p1 = (await self._agent.generate_greeting() or "").strip()
        else:
            p1 = (await self._generate_greeting_legacy() or "").strip()

        # Phase 2: 통화 목적 + 첫 번째 질문 조합
        first_q = self._outbound_questions[0] if self._outbound_questions else ""
        if first_q:
            p2 = f"{self._outbound_purpose} {first_q}"
        else:
            p2 = self._outbound_purpose

        logger.info(
            "outbound_greeting_with_purpose",
            call_id=self._call_id,
            purpose=self._outbound_purpose[:80],
            first_question=first_q[:80],
        )
    else:                               # 인바운드 모드 (기존 로직 유지)
        ...
```

**시나리오 예시:**

| Phase | 발화 내용 |
|-------|-----------|
| Phase 1 (p1) | "안녕하세요, 이탈리안 레스토랑 비스트로 벨라입니다." |
| Phase 2 (p2) | "4월 3일 14시 예약 확인 차 연락드렸습니다. 실제로 방문하실 예정인가요?" |

> **리서치 인사이트 (JustCall, 2025):**  
> AI 아웃바운드 인사는 3-part 구조 권장 — ① 짧은 환영 인사 ② 신원·목적 ③ 첫 번째 질문.  
> 이 구조는 착신자 신뢰 형성에 가장 효과적이며, "7초 안에 신뢰 확립"이 전환율을 결정함.  
> Phase 1 + Phase 2 분리 발화 구조는 이 3-part 패턴과 일치함.

---

### 3.3 [수정 3 — 중간] 미션 완료 판단 개선 — `rag_processor.py`

**현재 문제:** `"예" in result_text` 단순 매칭 → 오판 위험

**변경 내용:** JSON Structured Output 방식으로 통일

```python
# ✅ 수정: purpose-only 경로도 JSON 응답 강제
check_prompt = (
    f"다음은 AI 아웃바운드 통화 대화 기록입니다.\n\n"
    f"[통화 목적]\n{self._outbound_purpose}\n\n"
    f"[대화 기록]\n{history_text}\n\n"
    "위 통화 목적이 달성되었는지 판단하여 반드시 아래 JSON 형식으로만 답하세요.\n"
    '형식: {"achieved": true} 또는 {"achieved": false}'
)
...
m = re.search(r'\{[^}]*"achieved"\s*:\s*(true|false)[^}]*\}', result_text)
if m:
    import json
    data = json.loads(m.group())
    if data.get("achieved") is True:
        await self._trigger_mission_complete(call_id)
```

> **리서치 근거 (dev.to, 2026):**  
> LLM에게 자유 텍스트 대신 JSON 스키마를 강제하는 것이 AI 에이전트 자동화의 핵심.  
> `"예" in text` 방식은 "예를 들어", "예약" 등에서 False Positive 발생.  
> `{"achieved": true/false}` 형식 강제 시 파싱 오류율 접근 0%.  
> 참고: [Structured Outputs Are the Contract Your AI Agent Is Missing](https://dev.to/sitaram_srivatsavai/structured-outputs-are-the-contract-your-ai-agent-is-missing-24a)

---

### 3.4 [수정 4 — 중간] 종료 멘트 KB 참조 — `rag_processor.py`

**위치:** `_trigger_mission_complete()` 메서드 322행

```python
# ✅ 수정: KB farewell 카테고리 우선, 없으면 하드코딩 폴백
farewell_text = ""
if self._agent_available:
    try:
        farewell_text = (await self._agent.generate_farewell() or "").strip()
    except Exception:
        pass

if not farewell_text:
    farewell_text = "필요한 내용을 모두 확인했습니다. 감사합니다. 좋은 하루 되세요."

logger.info("outbound_farewell_source",
            call_id=call_id,
            source="kb" if farewell_text else "hardcoded",
            text=farewell_text[:80])
```

---

### 3.5 [수정 5 — 중간] TTS 완료 대기 이벤트 방식으로 전환 — `rag_processor.py`

**현재:** `await asyncio.sleep(3.0)` 고정 대기  
**문제:** 짧은 farewell은 3초 내 완료되어 조기 BYE 가능성, 긴 farewell은 잘릴 수 있음

**변경 내용:**

```python
# ✅ 수정: TTS 완료 이벤트 대기 (최대 10초 타임아웃)
tts_done = asyncio.Event()
self._tts_sync_context["on_tts_complete"] = tts_done
try:
    await asyncio.wait_for(tts_done.wait(), timeout=10.0)
    logger.info("outbound_farewell_tts_done_by_event", call_id=call_id)
except asyncio.TimeoutError:
    logger.warning("outbound_farewell_tts_timeout", call_id=call_id,
                   note="TTS 완료 이벤트 10초 미수신 — sleep 폴백")
    await asyncio.sleep(3.0)
```

> **리서치 근거 (MarkTechPost, 2026):**  
> 고정 sleep 타이머는 Voice AI의 주요 레이턴시 낭비 요인.  
> 이벤트 드리븐 방식(TTS 완료 신호)으로 전환하면 짧은 발화는 즉시 다음 단계로 이행.  
> 이미 `_tts_sync_context["on_tts_complete"]` 인프라가 `send_greeting()`에서 사용 중.

---

### 3.6 [신규 추가 — 높음] 음성사서함 감지 — `rag_processor.py` / `pipeline_builder.py`

**현재:** 음성사서함 감지 없음  
**문제:** AI가 "지금 전화를 받을 수 없습니다..." 안내 음성을 사람으로 오인하여 응대

**변경 내용:** Pipecat 공식 `VoicemailDetector` 모듈 도입

```python
# pipeline_builder.py — 아웃바운드 파이프라인 구성 시
from pipecat.extensions.voicemail.voicemail_detector import VoicemailDetector

voicemail_detector = VoicemailDetector(
    llm=classifier_llm,        # 분류 전용 경량 LLM (Gemini Flash)
    voicemail_response_delay=2.0
)

@voicemail_detector.event_handler("on_voicemail_detected")
async def handle_voicemail(processor):
    logger.info("outbound_voicemail_detected", call_id=call_id)
    # 음성사서함 메시지 남기기 (선택)
    await processor.push_frame(
        TTSSpeakFrame("안녕하세요. 통화 목적 관련하여 다시 연락드리겠습니다.")
    )
    await processor.push_frame(EndTaskFrame(), FrameDirection.UPSTREAM)

# 파이프라인에 삽입 위치:
pipeline = Pipeline([
    transport.input(),
    stt,
    voicemail_detector.detector(),    # ← STT와 context aggregator 사이
    context_aggregator.user(),
    llm,
    tts,
    voicemail_detector.gate(),        # ← TTS 직후
    transport.output(),
    context_aggregator.assistant(),
])
```

> **리서치 근거 (Pipecat 공식 문서, 2025):**  
> Pipecat은 `VoicemailDetector` 확장 모듈을 공식 제공.  
> 병렬 파이프라인 구조로 분류 지연 없이 실시간 판별.  
> TTS 게이팅 전략: 사람으로 확인될 때까지 생성된 오디오를 버퍼에 보관,  
> 음성사서함 판별 시 버퍼 클리어 → AI가 사서함에 응대하는 상황 방지.  
> 참고: [Pipecat Voicemail Detection](https://docs.pipecat.ai/guides/fundamentals/voicemail)

**아웃바운드 전용 적용:** 인바운드 파이프라인에는 미적용, `is_outbound` 플래그로 분기.

---

### 3.7 [신규 추가 — 중간] 대화 상태 머신(FSM) 도입 — `rag_processor.py`

**현재 문제:**  
- 질문 순서가 단순 List index 기반으로 관리됨
- "다음 질문을 던지는" 로직이 `_check_outbound_mission_complete()` 내에 없음  
  (미션 체크 후 완료가 아니면 자동으로 다음 질문을 push하지 않음)
- 즉, 착신자가 답을 안 해도 AI는 계속 RAG 응대만 하다가 종료됨

**변경 내용:** 아웃바운드 전용 간단한 상태 추적 추가

```python
# ✅ 신규: 아웃바운드 대화 상태
class OutboundState(str, Enum):
    GREETING   = "greeting"        # 인사 + 목적 발화
    QUESTIONING = "questioning"    # 질문 진행 중
    CONFIRMING  = "confirming"     # 미션 완료 확인
    FAREWELL    = "farewell"       # 종료 멘트
    DONE        = "done"           # BYE 완료

# _check_outbound_mission_complete() 수정:
# all_done=False이고 다음 질문이 있으면 → 자동으로 다음 질문 발화
if not all_done and remaining:
    next_q = remaining[0]
    logger.info("outbound_next_question", call_id=call_id, question=next_q)
    await self.push_frame(LLMFullResponseStartFrame())
    await self.push_frame(TextFrame(text=next_q))
    await self.push_frame(LLMFullResponseEndFrame())
```

> **리서치 근거 (Medium, 2026):**  
> 현대 AI 음성봇은 FSM(유한 상태 머신)을 뼈대로, LLM을 자연어 처리에만 활용하는  
> 하이브리드 구조가 권장됨. FSM이 없으면 LLM이 예상치 못한 결정을 내릴 수 있음.  
> 아웃바운드의 경우 "질문 → 답변 확인 → 다음 질문" 흐름이 FSM으로 표현하기 적합.  
> 참고: [Designing a FSM for Inbound Voice AI](https://medium.com/@ashishkumar_81395/designing-a-finite-state-machine-fsm-for-inbound-voice-ai-e67502c51bfa)

---

### 3.8 [추가] `LangGraphAgent.generate_farewell()` — `langgraph_agent.py`

KB의 `farewell` 카테고리 문서를 조회하는 메서드 추가.

```python
async def generate_farewell(self) -> str:
    """KB farewell 카테고리 문서 반환. 없으면 빈 문자열."""
    try:
        docs = await self._knowledge_service.search_by_category("farewell", top_k=1)
        return docs[0].text if docs else ""
    except Exception:
        return ""
```

---

## 4. 수정 후 시퀀스 다이어그램

```
착신자 200 OK
    │
    ▼
[VoicemailDetector] ─── 음성사서함 감지 → 메시지 남기고 BYE
    │ 사람 확인
    ▼
[send_greeting()]
    ├─ p1: KB greeting_phase1         → "안녕하세요, 비스트로 벨라입니다."
    └─ p2: purpose + questions[0]     → "예약 확인 차 연락드렸습니다. 방문하실 예정인가요?"

착신자 발화 → STT → RAG LLM 응대
    │
    ▼
[_check_outbound_mission_complete(response)]   ← 매 턴마다 비동기
    │  LLM: JSON {"achieved":bool} / {"answered":[...], "all_done":bool}
    │
    ├─ 미완료 + 다음 질문 있음 → questions[next] TTS 발화 → 반복
    ├─ 미완료 + 질문 소진 → 자체 LLM 응대 계속 → 반복
    │
    └─ 완료 (all_done=true / achieved=true)
           │
           ▼
       [_trigger_mission_complete()]
           ├─ KB farewell TTS (없으면 하드코딩)
           ├─ TTS 완료 이벤트 대기 (max 10초)
           └─ hangup_callback() → SIP BYE
```

---

## 5. 파일별 수정 요약

| 파일 | 수정 위치 | 수정 내용 | 우선순위 | 리서치 기반 |
|------|-----------|-----------|----------|-------------|
| `src/sip_core/sip_endpoint.py` | 4324–4327행 | callee_leg `allocated_ports = [0, 0]` | **긴급** | 코드 분석 |
| `rag_processor.py` | `send_greeting()` | 아웃바운드 시 purpose + first_question 발화 분기 | 높음 | JustCall 3-part 인사 패턴 |
| `rag_processor.py` | `_check_outbound_mission_complete()` | 다음 질문 자동 발화 로직 추가 | 높음 | FSM 패턴 |
| `rag_processor.py` | purpose 완료 판단 303행 | `{"achieved": bool}` JSON 방식으로 교체 | 중간 | Structured Output 원칙 |
| `rag_processor.py` | `_trigger_mission_complete()` 322행 | KB farewell 참조 + 하드코딩 폴백 | 중간 | — |
| `rag_processor.py` | `_trigger_mission_complete()` 332행 | `sleep(3.0)` → TTS 완료 이벤트 대기 | 중간 | 이벤트 드리븐 TTS 패턴 |
| `pipeline_builder.py` | 아웃바운드 파이프라인 구성 | `VoicemailDetector` 삽입 | 높음 | Pipecat 공식 |
| `langgraph_agent.py` | 신규 메서드 | `generate_farewell()` 추가 | 중간 | — |

---

## 6. 미해결 리스크

| 항목 | 내용 | 대응 방안 |
|------|------|-----------|
| `_check_outbound_mission_complete` 중복 실행 | 동일 턴에서 여러 번 호출될 가능성 | `_outbound_mission_done` 플래그로 중복 방지 (이미 구현됨) |
| 목적 달성 판단 오판 | `"예" in result_text` 단순 매칭 | **[수정 3]** JSON Structured Output으로 해결 |
| farewell TTS 완료 전 BYE | `sleep(3.0)` 고정 대기 | **[수정 5]** TTS 완료 이벤트 대기로 해결 |
| KB farewell 문서 없을 때 | 하드코딩 폴백 | **[수정 4]** 폴백 유지 |
| `org_manager_load_failed` (`vector_db` 없음) | KnowledgeService 초기화 순서 문제 | `call_manager.py` 282행 확인 필요 |
| 음성사서함 오인식 | 감지 없이 사서함 안내에 AI 응대 | **[수정 6]** VoicemailDetector 도입으로 해결 |
| 질문 미전달 | 미션 체크 후 다음 질문이 자동 발화되지 않음 | **[수정 7]** FSM 기반 다음 질문 push 로직으로 해결 |
| 통화 최대 시간 초과 | AI 파이프라인 내 독립 타임아웃 없음 | `max_duration` + `_outbound_mission_done` 강제 종료 검토 |

---

## 7. 리서치 참고 자료

| 항목 | 출처 | 핵심 인사이트 |
|------|------|---------------|
| 아웃바운드 인사 설계 | [JustCall AI Voice Agent Script Best Practices](https://justcall.io/blog/best-practices-ai-voice-agent-scripts.html) | 3-part 구조: 환영 + 신원/목적 + 질문. 7초 내 신뢰 확립이 전환율 결정 |
| 구조화 출력 (JSON) | [dev.to — Structured Outputs Are the Contract Your AI Agent Is Missing](https://dev.to/sitaram_srivatsavai/structured-outputs-are-the-contract-your-ai-agent-is-missing-24a) | LLM 자유 텍스트 파싱은 비신뢰성. JSON Schema 강제가 에이전트 자동화의 핵심 |
| 음성사서함 감지 | [Pipecat 공식 문서 — Voicemail Detection](https://docs.pipecat.ai/guides/fundamentals/voicemail) | `VoicemailDetector` 공식 모듈 제공. 병렬 파이프라인으로 레이턴시 없이 판별 |
| 대화 상태 머신 | [Medium — FSM for Voice AI (2026)](https://medium.com/@ashishkumar_81395/designing-a-finite-state-machine-fsm-for-inbound-voice-ai-e67502c51bfa) | FSM + LLM 하이브리드. FSM이 흐름 제어, LLM은 자연어 처리만 담당 |
| TTS 이벤트 드리븐 | [MarkTechPost — Streaming Voice Agent Architecture (2026)](https://www.marktechpost.com/2026/01/19/how-to-design-a-fully-streaming-voice-agent-with-end-to-end-latency-budgets-incremental-asr-llm-streaming-and-real-time-tts/) | 고정 sleep 타이머는 레이턴시 낭비. 이벤트 드리븐 아키텍처 권장 |
| 실제 콜드콜 분석 | [dev.to — 500 Real Cold Calls AI Dialer](https://dev.to/gamlin/how-we-built-an-ai-voice-agent-from-500-real-cold-calls-23jg) | Top 성과자는 스크립트 준수율 낮음(78%). 맥락 읽기와 흐름 조정이 성패를 결정 |
| Pipecat 강화 (2026) | [dev.to — Hardening Pipecat](https://dev.to/kollaikalrupesh/hardening-pipecat-a-month-of-fixing-what-matters-44l) | ServiceSwitcherStrategyFailover로 STT/TTS 자동 장애 전환. telephony 8kHz 리샘플링 필요 |

---

## 8. 구현 체크리스트

### Phase 1 — 긴급 (오디오 불통 수정)
- [x] `sip_endpoint.py`: callee_leg allocated_ports `[0, 0]` 변경

### Phase 2 — 핵심 시나리오 (인사 + 질문 흐름)
- [x] `rag_processor.py` `send_greeting()`: 아웃바운드 분기 추가 (purpose + first_question)
- [x] `rag_processor.py` `_check_outbound_mission_complete()`: 다음 질문 자동 발화 로직 추가
- [x] `rag_processor.py` purpose 완료 판단: JSON Structured Output 방식으로 교체

### Phase 3 — 품질 개선
- [x] `rag_processor.py` `_trigger_mission_complete()`: KB farewell 참조 로직
- [x] `rag_processor.py` TTS 완료 대기: sleep → 이벤트 드리븐 방식으로 전환
- [x] `langgraph_agent.py`: `generate_farewell()` 메서드 추가

### Phase 4 — 안정성 강화 (미적용 — 음성사서함 감지 불필요)
- [~] `pipeline_builder.py` + `rag_processor.py`: VoicemailDetector — **사용자 요청으로 제외**
- [ ] `rag_processor.py`: 아웃바운드 통화 AI 내부 타임아웃 가드 추가 (추후 검토)

---

## 9. 구현 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `src/sip_core/sip_endpoint.py` | 수정 | callee_leg `allocated_ports = [0, 0]` — callee 소켓 바인딩 스킵 | RTP [WinError 10048] 해결 |
| `src/ai_voicebot/pipecat/processors/rag_processor.py` | 수정 | `send_greeting()` 아웃바운드 분기 추가 — KB p1 + (목적+첫질문) p2 | 기존 인바운드 로직 유지 |
| `src/ai_voicebot/pipecat/processors/rag_processor.py` | 수정 | `_check_outbound_mission_complete()` 전면 재작성 | 아래 상세 참고 |
| `src/ai_voicebot/pipecat/processors/rag_processor.py` | 수정 | `_trigger_mission_complete()` — KB farewell + TTS 이벤트 대기 | 기존 sleep(3.0) 대체 |
| `src/ai_voicebot/langgraph/agent.py` | 추가 | `generate_farewell()` 메서드 신규 추가 | greeting 패턴과 동일 |

### `_check_outbound_mission_complete()` 상세 변경

- **변경 유형**: 수정 (전면 재작성)
- **변경 내용**:
  1. `_parse_first_json()` 내부 헬퍼 추가 — 중첩 깊이 추적 방식으로 greedy DOTALL 취약점 해소
  2. `_call_llm()` 내부 헬퍼로 LLM 호출 중복 제거
  3. purpose-only 경로: `"예" in result_text` → `{"achieved": true/false}` JSON 방식으로 교체
  4. questions 경로: 미완료 시 `remaining[0]` 다음 질문을 TTS push (기존 누락 로직 추가)
  5. JSON 파싱 실패 시 `outbound_mission_check_json_parse_failed` 로그로 추적 가능
- **기존 동작 제거**: `"예" in result_text` 단순 매칭 제거, `re.search(r'\{.*\}', ..., re.DOTALL)` greedy 파싱 제거
- **설계 대비**: 설계대로

## 10. 설계 문서 버전 이력

| 버전 | 날짜 | 변경 내용 |
|------|------|-----------|
| v1 | 2026-03-31 22:00 | 초안 작성 — RTP 버그, 인사 로직, farewell KB 참조 설계 |
| v2 | 2026-03-31 22:30 | 리서치 반영 추가 — JSON Structured Output, VoicemailDetector, FSM 기반 질문 시퀀스, TTS 이벤트 드리븐 대기 |
| v3 | 2026-03-31 22:50 | 구현 완료 반영 — 체크리스트 완료, 파일별 변경 이력 추가. VoicemailDetector 제외(사용자 요청) |
