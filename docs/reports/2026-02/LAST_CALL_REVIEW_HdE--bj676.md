# 마지막 AI 통화 로그 리뷰 — HdE--bj676

**로그:** `sip-pbx/logs/app.log`  
**통화 ID:** HdE--bj676 (1003 → 1004, no-answer 후 AI 터치다운)  
**분석 일자:** 2026-02-21

---

## 1. Call 관련 로그 — 시간순 정리

| 시각 (UTC) | 이벤트 | 비고 |
|------------|--------|------|
| **01:07:56.144** | INVITE 수신 (1003→1004) | b2bua_invite_received, call_id=HdE--bj676 |
| 01:07:56.150 | no_answer_timer_started (10초) | b2bua_call_setup_in_progress |
| 01:07:56.328 | 180 Ringing (callee 측) | callee_tag=JPWUZ7K |
| **01:08:06.164** | no_answer_timeout_activating_ai | 10초 무응답 → AI 터치다운 |
| 01:08:06.166 | ai_mode_activated, CANCEL → callee | Pipecat 모드로 전환 |
| 01:08:06.167 | 200 OK → caller (AI 연결) | STUN Binding 전송 |
| 01:08:06.169 | Pipecat pipeline 시작 | activating_ai_voicebot_for_no_answer |
| 01:08:06.176 | org_manager_loaded_from_vectordb | owner=1004, tenant_name=기상청 |
| 01:08:06.958 | pipecat_pipeline_built (0.788s) | TTSEndFrameForwarder, TTSCompleteNotifier 포함 |
| 01:08:06.960 | call_established (caller ↔ AI) | ACK 수신, 487 not relayed (ai_mode) |
| 01:08:06.962 | pipecat_input_transport_started | 미디어 구간 시작 |
| **01:08:07.047** | greeting phase1/phase2 텍스트 생성 | rag_llm_greeting_phase1, phase2, phase1_sent |
| 01:08:07.047 | streaming_tts_gateway_flushed (phase1) | chunks_sent=1, total_time=0.00s |
| **01:08:25.919** | greeting_phase_gap_tts_complete_timeout | Notifier 미수신 → fallback_gap_sec=7.35, wait_timeout_sec=11.5 |
| 01:08:25.919 | greeting_phase2_sent, greeting_total | total_elapsed=18.872s |
| 01:08:25.919 | streaming_tts_gateway_flushed (phase2) | chunks_sent=1 |
| **01:08:40.380** | rag_llm_user_input | "네 저는 오늘 날씨가 궁금해요." |
| 01:08:42.253 | classify_intent (LLM), intent=question | elapsed=1.869s |
| 01:08:42.345 | rag_search_completed | results_count=2, confidence=0.838 |
| 01:08:44.136 | LLM response generated | response_len=12, "네, 오늘 날씨 예보를" |
| 01:08:44.271 | process_utterance 완료 | langgraph_elapsed=3.889s, business_state=resolution |
| 01:08:44.275 | streaming_tts_gateway_flushed (응답 턴) | chunks_sent=1 |
| **01:09:00.453** | BYE 수신 (caller) | bye_received, bye_cleanup_triggered |
| 01:09:00.463 | Mixing caller/callee audio, recording 저장 | duration_sec=53.88 |
| 01:09:09.258 | stt_transcript_saved (후처리 STT) | transcript_length=216 (AI 발화 포함) |
| 01:09:09.263 | knowledge_extraction_skipped | reason=ai_call |
| 01:13:39.208 | pipecat_input_transport_stopped | pipeline 정리 완료 |

**요약:** INVITE → 10초 무응답 → AI 터치다운 → 인사 Phase1 즉시 재생, Phase2는 Notifier 대기 타임아웃(11.5초) 후 fallback으로 약 18.9초 만에 재생 → 사용자 발화 1회(RAG+LLM 정상) → BYE로 종료. 전반적으로 AI 통화 플로우는 설계대로 동작.

---

## 2. 에러/경고 점검

| 레벨 | 이벤트 | 비고 |
|------|--------|------|
| **warning** | greeting_phase_gap_tts_complete_timeout | Phase1 TTS 완료 Notifier를 11.5초 안에 받지 못해, 예상 재생시간+버퍼(7.35초) 대기 후 Phase2 전송. 인사말 지연 원인. |
| **warning** | no_answer_timeout_activating_ai | 설계 동작(10초 무응답 시 AI 터치다운). |
| (전통화) | JSON parse failed, attempting cleanup (x8ceI-ir8A 지식 추출) | `"confidence\": 0` 등 불완전 JSON → cleanup 후 confidence=0.0 적용. 동일 통화 아님. |

**결론:** 이번 AI 통화(HdE--bj676) 구간에서는 **치명적 에러 없음**. Notifier 미수신으로 인한 **greeting_phase_gap_tts_complete_timeout** 1건만 해당.

---

## 3. Notifier 미수신 이슈 — 로그로 점검

### 3.1 로그로 확인 가능한 것

- **tts_complete_notifier_signalled**  
  이 통화 구간에서 **한 번도 출력되지 않음** → TTSCompleteNotifier가 `LLMFullResponseEndFrame`을 **한 번도 받지 못함**.
- **greeting_phase_gap_tts_complete_timeout**  
  Phase1 전송 후 `on_tts_complete` 이벤트가 **wait_timeout_sec(11.5초) 내에 set되지 않아** 타임아웃 발생 → Phase2는 fallback gap(7.35초) 대기 후 전송.

즉, 로그만으로도 **“Notifier가 TTS 완료 신호를 받지 못했다”**는 사실은 명확히 확인 가능.

### 3.2 로그만으로는 부족한 부분

- **TTSEndFrameForwarder의 synthetic EndFrame 발송 여부**  
  - synthetic 발송 시 `tts_end_frame_forwarder_synthetic_end`를 **logger.debug**로만 남김.  
  - 현재 로그 레벨이 INFO이면 이 메시지가 안 찍혀 **“Google TTS가 EndFrame을 안 넘겼는지” vs “넘겼는데 Notifier까지 안 갔는지”** 구분 불가.
- **TTSStoppedFrame 수신 시점**  
  - Pipecat/Google TTS가 Phase1 오디오에 대해 `TTSStoppedFrame`을 언제 보내는지 로그에 없음.  
  - 11.5초 안에 TTSStoppedFrame이 오지 않았을 가능성(스트리밍 지연 등)은 있으나, 로그만으로는 확인 불가.

### 3.3 점검 권장 사항 (해결보다는 원인 수집)

1. **tts_end_frame_forwarder_synthetic_end**  
   - `logger.debug` → `logger.info`로 상향해, 다음 통화부터 **synthetic EndFrame 발송 여부**를 로그로 확인.
2. **TTSStoppedFrame 로그**  
   - TTSEndFrameForwarder(또는 TTS 직후 한 곳)에서 `TTSStoppedFrame` 수신 시 `logger.info` 한 줄 추가하면, Phase1 구간에서 **TTS 완료 시점**과 **Notifier 대기 타임아웃(11.5초)** 관계를 나중에 분석하기 쉬움.

이렇게 하면 “Notifier를 못 받는 이유”가 **Upstream EndFrame 미전달**인지, **TTSStopped 지연**인지, **synthetic은 보냈는데 Notifier 미동작**인지 구분할 수 있음.

---

## 4. 인사말 Phase2 TTS가 짤린 현상 — 원인 점검

### 4.1 Phase2 전달 방식 (Phase1과 동일한 “한 번에” 전달)

- **RAGLLMProcessor**  
  - Phase2는 **단일 TextFrame** 한 번만 전송:  
    `await self.push_frame(TextFrame(text=capability_guide))`  
  - 문장 단위로 쪼개지 않음.
- **StreamingTTSGateway**  
  - `_text_frame_count > 1`일 때만 `_try_send_sentences()` 호출(문장 끝 패턴으로 분할).  
  - 인사말은 **TextFrame 1개 + EndFrame**이므로 `_text_frame_count`는 1 → **문장 분할 로직 미진입**.  
  - Phase1과 동일하게 **버퍼에 넣었다가 EndFrame 시 한 번에 flush** → Phase2도 **한 덩어리로** TTS에 전달됨.

따라서 **“Phase1에서 마침표 옵션 false로 해서 한 번에 보냈던 것”과 동일한 방식**이 Phase2에도 적용되어 있음. Phase2가 **문장 단위로 잘려서** 짤린 것은 아님.

### 4.2 Phase2 “짤림” 가능 원인 (추정)

- **재생/전송 구간**  
  - TTS(Google) 또는 RTP/버퍼에서 중간에 끊겼을 가능성.  
  - 로그에는 “Phase2 전체 텍스트가 gateway를 한 번에 통과했다”만 나오고, **실제 오디오 샘플 수/길이**는 없음.
- **통화 종료 타이밍**  
  - BYE는 phase2_sent 기준 약 34초 후(01:09:00). 사용자가 말하다가 끊었을 수도 있어, “시스템이 Phase2를 잘랐다” vs “사용자가 끊었다” 구분은 로그만으로는 어렵음.

**권장:** Phase2 텍스트 길이(char)와, 가능하면 “이번 응답으로 TTS에 넘긴 총 문자 수”를 한 줄 로그로 남기면, 나중에 “전부 넘겼는데 재생만 짧다”인지 여부를 확인하기 좋음.

---

## 5. LLM / RAG 동작 리뷰

### 5.1 인사말 (Greeting)

- **Phase1:** "안녕하세요. 기상청입니다. 날씨와 관련된 문의를 도와드리겠습니다." (36자)
- **Phase2:** "저는 날씨 예보 조회, 기상 특보 안내, … 어떤 것이 궁금하신가요?" (capability_guide 전체)
- LangGraph 모드, org_manager(1004, 기상청) 기반으로 생성된 것으로 보임. **정상**.

### 5.2 사용자 발화 1턴 — "네 저는 오늘 날씨가 궁금해요."

| 단계 | 이벤트 | 값 |
|------|--------|-----|
| STT | rag_llm_user_input | text="네 저는 오늘 날씨가 궁금해요." |
| Intent | classify_intent (LLM) | intent=question, elapsed=1.869s |
| RAG | rag_search_completed | owner_filter=1004, results_count=2, latency_ms=32 |
| RAG | adaptive_rag 완료 | confidence=0.838, raw_count=2, expanded_count=2 |
| LLM | LLM response generated | context_docs_count=1, latency_ms=1789, response_len=12 |
| 응답 | langgraph_agent_result | business_state=resolution, needs_human=false, confidence=0.838 |
| 응답 | llm_response_sent | response_preview="네, 오늘 날씨 예보를" |

- **의도 분류:** question → RAG 경로 진입.  
- **RAG:** 2건 검색, confidence 0.838, 문서 1개 컨텍스트로 LLM 호출.  
- **LLM:** 12자 생성("네, 오늘 날씨 예보를" 등), 1.789초.  
- **비즈니스 상태:** resolution, HITL 없음.

**정리:** 이 턴은 **RAG + LLM + 상태 전이**까지 설계대로 동작했고, 에러 없음.

### 5.3 파이프라인 구성

- `pipecat_pipeline_built` 시 components:  
  SIPPBXTransport → SileroVAD → SmartTurnV3 → GoogleSTT → SmartBargeIn → **RAG-LLM(LangGraph)** → StreamingTTSGateway → GoogleTTS → **TTSEndFrameForwarder** → **TTSCompleteNotifier** → SIPPBXOutput  
- LangGraph 캐시 히트, RAG/캐시 사용으로 초기화. **현재 상태 정상**.

---

## 6. 요약 및 권장

| 항목 | 상태 | 비고 |
|------|------|------|
| Call 시간순 흐름 | 정상 | INVITE → no-answer → AI 터치다운 → 인사 → 1턴 대화 → BYE. |
| 에러 | 없음 | timeout 1건(Notifier 미수신)만 해당. |
| Notifier 미수신 | 로그로 “미수신” 확정, 원인은 부분적 | synthetic 발송/Stopped 시점 로그 추가 권장(INFO + TTSStopped 한 줄). |
| Phase2 짤림 | 파이프라인 상 분할 없음 | Phase1과 동일하게 단일 TextFrame으로 한 번에 전달. 재생/네트워크 쪽 추가 로그로 원인 수집 권장. |
| LLM/RAG | 정상 | intent=question, RAG 2건, confidence 0.838, resolution, 응답 생성까지 정상. |

이 문서는 **점검 위주**로 작성되었으며, Notifier와 Phase2 짤림은 **원인 수집을 위한 로그 보강**을 권장하는 수준으로 정리함.
