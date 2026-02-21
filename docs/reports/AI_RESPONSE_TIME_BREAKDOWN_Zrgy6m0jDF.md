# AI Response Time Breakdown — Call Zrgy6m0jDF

**Source:** `logs/app.log`  
**Call ID:** Zrgy6m0jDF  
**Analyzed:** Last AI call in log (2026-02-21).

---

## ⚠️ TTS 시간 처리 방식 (점검 결과)

### “TTS 완료”가 빨라 보이는 이유

- **사용한 이벤트:** `streaming_tts_gateway_flushed`
- **의미:** “**첫 텍스트 청크가 Gateway → Google TTS로 전달된 시각**” (gateway가 TTS에 넘긴 시점).
- **로그 문구:** `"note": "gateway→TTS 전달 완료, TTS 합성/재생 완료 아님"`  
  → 즉 **TTS 합성 완료·재생 완료가 아님**.

따라서 아래 표의 “TTS done”은 **TTS가 말하기 끝난 시각이 아니라**, “첫 문장이 TTS 엔진에 넘겨진 시각”입니다.  
그래서 LLM 완료 직후 0.08~0.11초만에 “TTS done”이 찍혀 **빨라 보입니다.**

### 로그의 `total_time` (0.08s, 0.09s, 0.11s) 의미

- **계산 위치:** `StreamingTTSGateway` (`streaming_tts_processor.py`)
- **계산식:** `time.time() - self._first_chunk_time`  
  → **첫 TextFrame을 Gateway가 받은 시각**부터 **버퍼를 플러시해 TTS로 넘긴 시각**까지의 구간.
- **의미:** Gateway 내부 버퍼 대기 시간(문장 완성 또는 min_chars 도달)일 뿐, **Google TTS 합성 구간은 포함되지 않음.**

### 이 통화에서 “진짜 TTS 합성 완료” 시각이 없는 이유

- `tts_complete_notifier_signalled` 이벤트가 이 로그 구간에 **없음** (Notifier가 EndFrame을 받지 못했던 당시 동작).
- TTSEndFrameForwarder 적용 이후 통화에서는 `tts_complete_notifier_signalled` 로 **해당 턴의 TTS 합성 완료 시각**을 쓸 수 있음.

### 권장 정리

| 지표 | 사용 이벤트 | 의미 |
|------|-------------|------|
| **첫 청크 TTS 전달** (현 표 “TTS done”) | `streaming_tts_gateway_flushed` | 첫 문장이 TTS에 넘겨진 시각 (체감 “말하기 시작” 근사) |
| **TTS 합성 완료** (말하기 끝) | `tts_complete_notifier_signalled` | 해당 턴 TTS가 모두 끝난 시각 (앞으로 로그에 쓸 예정) |

---

## Summary Table (STT → 첫 청크 TTS 전달)

**“TTS done” = 첫 텍스트 청크가 Gateway에서 TTS로 전달된 시각** (TTS 합성/재생 완료 아님).

| Turn | User said | STT time | LLM done | 첫 청크→TTS 전달 | Total (STT→첫 청크 전달) |
|------|------------|----------|----------|------------------|---------------------------|
| 1 | 아네 안녕하세요. | 00:05:46.996 | 00:05:48.955 (1.96s) | 00:05:49.041 | **2.05 s** |
| 2 | 기상청 AI 비서 만나요. | 00:05:54.049 | 00:05:57.830 (3.78s) | 00:05:57.920 | **3.87 s** |
| 3 | 주차는 어디다 해야 되는지 궁금합니다. | 00:06:06.662 | 00:06:12.632 (5.97s) | 00:06:12.742 | **6.08 s** |

---

## Extraction Details

### 1. User utterances (STT) — `rag_llm_user_input`

| Timestamp | User text |
|-----------|-----------|
| 2026-02-21T00:05:46.996 | 아네 안녕하세요. |
| 2026-02-21T00:05:54.049 | 기상청 AI 비서 만나요. |
| 2026-02-21T00:06:06.662 | 주차는 어디다 해야 되는지 궁금합니다. |
| 2026-02-21T00:06:22.717 | 오늘의 날씨가 궁금해요. |
| 2026-02-21T00:06:45.500 | 내일의 날씨가 궁금합니다. |

*(Table above uses first 3 turns; turns 4–5 available in log.)*

### 2. LLM response timing

- **process_utterance 완료** (`langgraph_elapsed`):
  - Turn 1: 00:05:48.955 — langgraph_elapsed **1.958s**
  - Turn 2: 00:05:57.830 — langgraph_elapsed **3.778s**
  - Turn 3: 00:06:12.632 — langgraph_elapsed **5.970s**

- **LLM response generated** (`latency_ms`):
  - Turn 1: 00:05:48.726 — **1716 ms**
  - Turn 2: 00:05:57.785 — **1800 ms**
  - Turn 3: 00:06:12.566 — **2478 ms**

### 3. TTS 관련 이벤트 (처리 방식)

- **streaming_tts_gateway_flushed** (첫 청크가 Gateway → TTS로 전달된 시각, **TTS 합성 완료 아님**):
  - Turn 1: 00:05:49.041 — `total_time` 0.08s (Gateway 내부: 첫 TextFrame 수신 → 플러시까지)
  - Turn 2: 00:05:57.920 — `total_time` 0.09s  
  - Turn 3: 00:06:12.742 — `total_time` 0.11s  

- **tts_complete_notifier_signalled:** 이 통화 로그에는 없음 (당시 Notifier 미수신).  
  이후 통화에서는 TTSEndFrameForwarder로 “TTS 합성 완료” 시각 수집 가능.

---

## Computed totals (STT → 첫 청크 TTS 전달)

- **Turn 1:** 00:05:49.041 − 00:05:46.996 = **2.045 s**
- **Turn 2:** 00:05:57.920 − 00:05:54.049 = **3.871 s**
- **Turn 3:** 00:06:12.742 − 00:06:06.662 = **6.080 s**

*(위는 “말하기 시작” 근사치. “말하기 끝”은 이 로그에서는 측정 불가.)*

---

## Notes

- Pipeline: RAG-LLM (LangGraph) → StreamingTTSGateway → Google TTS → (TTSEndFrameForwarder) → TTSCompleteNotifier.
- Turn 3 is slower due to intent classification + RAG (step-back query) + generate_response; LangGraph total 5.97s, LLM latency 2478 ms.
- Greeting phase had a separate `streaming_tts_gateway_flushed` at 00:05:36.716 (phase1) and 00:05:55.599 (phase2); not counted as user-turn responses.
- **코드 참고:** `streaming_tts_gateway_flushed` 및 `total_time` 계산 — `src/ai_voicebot/pipecat/processors/streaming_tts_processor.py` (첫 TextFrame 수신 시각 기준).
