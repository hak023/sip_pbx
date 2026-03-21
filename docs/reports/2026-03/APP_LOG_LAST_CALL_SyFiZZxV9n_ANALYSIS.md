# app.log 마지막 호(SyFiZZxV9n) 시간대별 점검 및 잔존 이슈

**통화 ID**: SyFiZZxV9n (AI 응대)  
**기간**: 2026-03-14 16:23:36 ~ 16:25:44 (약 2분 8초)

---

## 1. 시간대별 흐름

| 시각(대략) | 구간 | 이벤트 요약 |
|------------|------|-------------|
| **16:23:36** | 접수 | INVITE 수신, B2BUA 설정, RTP 포트 할당, 녹음 시작 |
| **16:23:46** | AI 인수 | no_answer_timeout(10s) → 착신 무응답으로 AI 터크오버, Pipecat 파이프라인 기동, StartFrame 수신, 오디오 루프 시작 |
| **16:23:46~47** | 인사말 Phase1 | send_greeting_started, Phase1 TTS "안녕하세요. 기상청 AI 통화 비서입니다. 무엇을 도와드릴까요?" → 첫 RTP 전송 16:23:47.294 (약 0.6초 후) |
| **16:23:47** | RTP | rtp_interval_violation 다수 (20ms 기대 vs 9~33ms), rtp_tts_queue_empty_timeout(1회, packets_sent: 0) |
| **16:23:48** | Phase1 완료 | notifier_endframe_processed (Phase1 재생 8.24초), rag_greeting_blocking_end, Phase1→Phase2 gap sleep 2.79초 |
| **16:23:51** | 인사말 Phase2 | greeting_phase2_sent "저는 날씨 예보 조회, 기상 특보 안내, … 어떤 것이 궁금하신가요?", tts_flush_skipped_greeting_phase2 |
| **16:23:51~53** | Phase2 TTS | Phase2 TTS 재생 (~12.7초), tts_rtp_duration_mismatch 15.5% |
| **16:24:04** | TTS 소진 | tts_sending_active: false, 이후 rtp_tts_queue_empty_timeout 반복 (packets_sent: 865 유지) |
| **16:24:13** | 1차 사용자 발화 | STT 최종 "아네 안녕하세요 저는 어 기상청 상식에 대해서 궁금합니다." → RAG 도달 |
| **16:24:13** | **에러** | semantic_cache_check_error, **rag_search_error**: `'TextEmbedder' object has no attribute 'embed'` → adaptive_rag_no_results |
| **16:24:18** | 대기 안내 | LLM step_back 쿼리 생성, 동일 embed 에러로 RAG 실패 → "정보를 찾고 있습니다. 잠시만 기다려 주세요." TTS 재생 |
| **16:24:24** | 1차 응답 완료 | generate_response 88자 ("네, 기상청 상식에 대해 궁금하시군요. 어떤 내용이…"), hitl_alert (low_confidence), **hitl_alert_callback_error**, **record_hitl_request_failed** |
| **16:24:41** | 2차 사용자 발화 | STT "저는 오늘의 날씨가 궁금합니다." |
| **16:24:43** | 캐시/검색 | classify_intent(question), semantic_cache_check_error(embed), adaptive_rag_no_results |
| **16:24:44** | HITL 타임아웃 | hitl_timeout_ai_reconnect, hitl_timeout_message_queued → LLM 다듬기 |
| **16:24:46** | HITL 안내 TTS | hitl_timeout_message_refined "고객님의 문의 감사" (짧게 잘림), "정보를 찾고 있습니다.", "잠시만 기다려 주세요." 재생 |
| **16:24:47** | 2차 RAG 실패 | rewrite_query "오늘의 날씨 정보" → **rag_search_error**(embed) → no_results |
| **16:24:55** | step_back 후 검색 실패 | step_back_query_generated → **rag_search_error**(embed) |
| **16:24:58** | 2차 응답 | generate_response 51자, hitl_alert, hitl_alert_callback_error, record_hitl_request_failed |
| **16:25:24~54** | 3차 발화 "혹시 더 기다려야 되나요?" | process_utterance_complete 30.29s, 응답 66자, hitl_alert, hitl_alert_callback_error, record_hitl_request_failed, semantic_cache_update_error(embed) |
| **16:25:44** | 종료 | BYE 수신, bye_cleanup_triggered, pipecat_pipeline_cancelled_on_bye |
| **16:26:08** | 사후 처리 | 녹음 정리, STT 사후 전사(callee 131단어, caller 24), transcript 저장, knowledge_extraction_skipped(ai_call) |
| **16:26:14** | HITL 타임아웃(통화 종료 후) | hitl_timeout_ai_reconnect, hitl_timeout_message_queued → refined "고객님, 문의" (매우 짧음) |

---

## 2. 잔존 이슈 정리

### 2.1 이미 코드에서 수정된 항목 (재기동 후 반영)

| 이슈 | 상태 | 비고 |
|------|------|------|
| `'TextEmbedder' object has no attribute 'embed'` | **수정됨** | `rag_engine.py`에서 `embed_text()` 및 `vector_db.query()` 사용. **LangGraph semantic_cache** 도 **적용 완료**: `check_cache_node` / `update_cache_node`에서 `embed_text` 사용으로 통일 (sync/async 분기). |
| 지식 정제 `judgment_max_output_tokens` 2048 | **수정됨** | `llm_client.py`에서 기본 4096, 일반 max_tokens 폴백 제거. 재기동 후 적용. |

### 2.2 권장 조치 적용 완료 (이번 수정)

| 구분 | 적용 내용 |
|------|-----------|
| **RAG/캐시 embed** | `semantic_cache.py`: `embedder.embed(query)` → `embed_text` 우선 사용 (sync/async 분기), 미지원 시 `embed` 폴백. |
| **HITL 콜백** | `hitl_processor.py`: `on_alert(call_id, alert_data)` → `on_alert(alert_data)` 1인자 호출로 변경. `_default_hitl_alert(context)` 시그니처와 호환. TypeError 시 `(call_id, alert_data)` 폴백 유지. |
| **HITL 기록** | `call_history.py`: `record_hitl_request(call_id, callee_id, user_question, ai_confidence, caller_id)` 함수 추가, 인메모리 `_hitl_requests` 저장. |
| **통화 종료 후 HITL** | `src/services/hitl.py` 신규: `HITLService`에 `cancel_timer(call_id)`, `unregister_call(call_id)` 추가. `pipeline_builder.py` finally에서 `call_ended` 직전에 `cancel_timer` + `unregister_call` 호출. |

### 2.3 아직 남은 이슈 (추가 점검/선택 조치)

| 구분 | 내용 | 권장 |
|------|------|------|
| **TTS vs RTP 길이** | `tts_rtp_duration_mismatch` (Phase1 21.8%, Phase2 15.5% 등) | Notifier vs Output PCM 불일치. 상세: [TTS_CHOPPY_ISSUE_ANALYSIS.md](./TTS_CHOPPY_ISSUE_ANALYSIS.md). |
| **RTP 간격** | `rtp_interval_violation` 다수 (expected 20ms, actual 7~33ms) | 20ms 이탈·누적 지터. rtp_timing_drift_reset 1회. 모니터링 유지, 필요 시 버퍼/간격 보정. |
| **PCM 큐 공백** | `rtp_tts_queue_empty_timeout` (TTS 사이·LLM 대기 구간) | 큐 비어 1초 타임아웃 반복. 해당 구간 침묵/끊김 가능. 대기 구간 filler 또는 타임아웃 정책 검토. |
| **HITL 타임아웃 메시지** | hitl_timeout_message_refined 7~10자로 과도하게 짧음 | 현재 `max_tokens=200`. 프롬프트 강화 또는 최소 길이/예시 문장 추가 검토. |

### 2.4 참고 (다른 call_id, 동일 로그 파일)

- **dHXzWkU1Jp**: 지식 추출 파이프라인에서 `llm_judgment_response` (finish_reason MAX_TOKENS, response_length 174), `llm_judgment_truncated`, `JSON parse failed`. → judgment 4096 + 전체 로깅 적용 후 재기동하면 개선 예상.

---

## 3. 권장 조치 순서 및 상태

| # | 조치 | 상태 |
|---|------|------|
| 1 | **RAG/캐시 embed** — LangGraph semantic_cache `embed_text` 통일 | **완료** (`semantic_cache.py`) |
| 2 | **HITL** — 콜백 `(context)` 시그니처, `record_hitl_request` 구현 | **완료** (`hitl_processor.py`, `call_history.py`) |
| 3 | **HITL 타임아웃** — BYE/cleanup 시 타이머 취소 | **완료** (`services/hitl.py`, `pipeline_builder.py`) |
| 4 | **TTS/RTP** — 인사말은 정상·이후 TTS 끊김 → flush 논블로킹 적용, [TTS_CHOPPY_ISSUE_ANALYSIS.md](./TTS_CHOPPY_ISSUE_ANALYSIS.md) 참고 | **일부 적용** (flush 논블로킹) |
| 5 | **서버 재기동** — RAG·HITL 반영 후 동일 시나리오 로그 재확인 | **권장** |
