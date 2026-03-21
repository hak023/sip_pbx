# 통화 점검: call_id fh0CbKB80u

**통화**: 1003 → 1004  
**시작**: 2026-03-16 15:48:14.409  
**종료**: 2026-03-16 15:49:07.121 (BYE 수신)  
**총 구간**: 약 52.7초 (녹음 기준), SIP 구간 약 62.8초 (CDR duration)

---

## 1. 진행 흐름 요약

| 시각 | 구간 | 이벤트 |
|------|------|--------|
| 15:48:14.409 | SIP 수립 | INVITE 수신 (1003→1004), call_session_added, 포트 할당, 미디어 세션 생성 (bypass) |
| 15:48:14.429 | Early Bind | RTP Relay Worker 생성 (ai_enabled: true), 소켓 바인딩, 녹음 시작 |
| 15:48:14.539 | Callee 응답 | 180 Ringing (callee_tag 수신) |
| 15:48:24.438 | **No-Answer → AI** | 10초 무응답으로 **no_answer_timeout_activating_ai**, CANCEL → Callee, AI Takeover |
| 15:48:24.439~440 | AI 전환 | ai_mode_activated, Pipecat 모드 준비, 200 OK → Caller, STUN Binding 전송 |
| 15:48:24.460 | Pipecat 기동 | pipecat_mode_enabled, pipeline_built, pipecat_task_created |
| 15:48:24.844 | Input/STT | StartFrame 수신, input_transport_first_frame, 오디오 루프 시작 |
| 15:48:25.019 | 통화 확립 | ACK 수신, **call_established** (caller: 1003, callee: AI) |
| 15:48:25.265~ | RTP→STT | caller_rtp_to_stt_input 시작, stt_path_rtp_first, Input → 파이프라인 |
| 15:48:25.267 | TTS 시작 | tts_first_audio_received (Phase1 인사말) |
| 15:48:25.326 | 인사말 | send_greeting_started, Phase1 "안녕하세요. AI 상담원입니다...", Phase2 "어떤 내용이 궁금하시면..." |
| 15:48:25.489 | **이슈** | **rtp_tts_queue_empty_timeout** (packets_sent: 0) — 인사말 첫 TTS 전에 1초 빈 구간 |
| 15:48:26.265~ | TTS→RTP | tts_first_audio_sent_to_rtp, pcm_chunk_queued, RTP 발송 루프 진행 |
| 15:48:27.672 | Phase1 완료 | notifier_endframe_processed (107프레임, 7.555초), **tts_rtp_duration_mismatch** (24.8%) |
| 15:48:30.761 | Phase2 | greeting_phase2_sent "어떤 내용이 궁금하시면 편하게 말씀해 주세요.", initial_greeting_sent |
| 15:48:31.670 | Phase2 완료 | output_endframe_processed, **tts_rtp_duration_mismatch** (21.7%) |
| 15:48:36.682~ | 빈 구간 | **rtp_tts_queue_empty_timeout** 반복 (empty_timeouts 2, 3, … 30) — packets_sent 472에서 정체 |
| 15:48:49~ | 사용자 발화 | STT → RAG: "말씀해 주세요." (transcription_frame_received, rag_llm_user_input) |
| 15:49:01.996 | LLM | query_rewrite_skip_candidate, classify_intent 등 대기 |
| 15:49:06.992 | 대기 안내 | llm_processing_notification → TTS "정보를 찾고 있습니다." |
| 15:49:07.118 | **BYE** | Caller가 BYE 전송 → 통화 종료 |
| 15:49:07.121~ | 정리 | bye_cleanup_triggered, pipecat_mode_stopped, pipeline_cancelled, 녹음·CDR·후처리 STT |

---

## 2. 이슈 사항 리스트

### 2.1 TTS·RTP 관련

| # | 이슈 | 로그 이벤트 | 설명 |
|---|------|-------------|------|
| 1 | **인사말 직후 1초 빈 구간** | `rtp_tts_queue_empty_timeout` (empty_timeouts: 1, packets_sent: 0) | Phase1 TTS 첫 오디오가 RTP 큐에 들어가기 전에 PCM 큐가 1초간 비어 있음. 인사말 맨 앞에서 **무음/끊김** 가능. |
| 2 | **Phase1 Notifier vs Output 불일치** | `tts_rtp_duration_mismatch` (diff_ratio_pct: 24.8) | Notifier 107프레임(7.555초) vs Output 13프레임(5.681초). TTS 음원의 약 25%가 RTP로 다 나가지 않았을 가능성. |
| 3 | **Phase2 Notifier vs Output 불일치** | `tts_rtp_duration_mismatch` (diff_ratio_pct: 21.7) | Notifier 59프레임(4.697초) vs Output 8프레임(3.68초). Phase2 말끝이 잘렸을 수 있음. |
| 4 | **RTP 20ms 간격 이탈** | `rtp_interval_violation` (violation_count 1~100) | 20ms 기대 간격에서 이탈(9.7ms~30.3ms). **violation_count 100**까지 누적. 음성 지터/깨짐 가능성. |
| 5 | **인사말 종료 후 장시간 PCM 큐 빈 구간** | `rtp_tts_queue_empty_timeout` (empty_timeouts: 2~30) | Phase2 송출 후 packets_sent 472에서 더 이상 증가 없이, 1초마다 empty_timeout 반복. 사용자 발화 대기 구간에서 **무음 또는 끊김** 구간 다수. |

### 2.2 STT·LLM·UX

| # | 이슈 | 설명 |
|---|------|------|
| 6 | **실시간 STT 인식 내용** | "말씀해 주세요." (인사말 Phase2의 끝부분이 사용자 발화로 인식됨 — 에코/오인식 가능성) |
| 7 | **LLM 응답 미재생** | BYE 직전 "정보를 찾고 있습니다." TTS 시작, 직후 BYE로 파이프라인 취소. "어떤 내용이 궁금하신지 말씀해 주시면 안내해 드릴게요." LLM 응답은 통화 종료 후 완료되어 발신자에게 재생되지 않음. |
| 8 | **LLM 지연** | classify_intent(LLM) 약 **12.9초** (process_utterance_complete total_elapsed 12.921s). 5초 경과 시 "정보를 찾고 있습니다." 안내 출력. |

#### 이슈 #8 상세: 12.9초는 “다른 문제” 가능성

- **실제 구간**: 로그상 12.9초는 **classify_intent(LLM) 한 번**에서만 소요됨. 이번 통화는 intent=**help**로 분류되어 check_cache/rewrite_query/adaptive_rag/generate_response 없이 곧바로 update_state로 끝났고, `timing_segment` 상으로 **classify_intent elapsed_sec=12.917**, 그 외 구간은 0초.
- **평소 대비**: 동일 app.log 내 다른 통화는 classify_intent(LLM)이 **2.4s~4.25s** (예: 02:31:49 2.45s, 20:46:48 2.81s, 22:17:40 3.11s). 즉 **한 번의 LLM 호출**이 평소보다 **약 3~5배** 길게 걸린 이상 구간으로 보는 것이 타당함.
- **가능 원인** (추가 점검 권장):
  - **Gemini API 지연/스파이크**: 네트워크, 리전, 또는 당시 API 부하로 1회 호출만 지연.
  - **재시도**: 클라이언트에 재시도가 있다면 첫 요청 실패 후 재시도로 12초가 될 수 있음 (코드에서 재시도·타임아웃 확인 필요).
  - **콜드 스타트**: 해당 통화가 서버/프로세스 기준 특정 시점의 첫 LLM 호출이었다면 웜업 부족 가능성 (동일일 다른 통화는 정상이므로 가능성은 낮음).
- **권장**: (1) LLM 클라이언트에 **요청 발송 시각/응답 수신 시각** 로그를 넣어 12초가 API 왕복인지 재시도 누적인지 구분, (2) 동일 조건 재현 시 **Gemini 대시보드/지연 메트릭** 확인, (3) 필요 시 classify_intent용 **타임아웃·재시도 정책** 검토.

#### 로그 강화 적용 (권장 조치 반영)

- **추가된 로그** (모든 LLM 호출 구간: classify_intent, rewrite_query, step_back, generate_response):
  - **llm_request_sent**: `call_site`, `request_sent_ts_iso`, `prompt_len`, `prompt_preview` — 요청을 보낸 시각과 내용 일부.
  - **llm_response_received**: `response_received_ts_iso`, `elapsed_ms` — 응답을 받은 시각과 경과 시간. **같은 call_site에서 request_sent 1회 ↔ response_received 1회**이면 1회 API 왕복; **request_sent가 여러 번**이면 클라이언트 내부 재시도 가능성.
  - **llm_request_failed**: `error_type`, `error_msg`, `elapsed_ms` — 예외 발생 시. **요청 잘못**으로 실패 시 여기서 원인 추적 가능.

#### 지연 외 재시도가 발생할 수 있는 이유 (요청 문제)

- **잘못된 요청**으로 API가 4xx/에러를 반환하면, 클라이언트가 재시도할 수 있음.
  - **Content filter / 안전 설정**: 프롬프트나 응답이 정책에 걸리면 차단·에러 → 재시도 시 지연.
  - **Rate limit (429)**: 동시 호출·분당 한도 초과 시 429 → 재시도 대기.
  - **잘못된 파라미터**: `max_tokens` 초과, 지원하지 않는 모델명, 인코딩 오류 등 → 400 계열 후 재시도.
  - **타임아웃**: 서버 응답 지연으로 클라이언트 타임아웃 → 재시도.
- **로그로 확인하는 방법**: `llm_request_sent`가 **같은 call_site에서 2회 이상** 찍히면 재시도 구간. `llm_request_failed`가 그 직전에 있으면 **실패 → 재시도** 흐름. `error_msg`에 429, 400, content filter, timeout 등이 포함되는지 확인.

### 2.3 기타

| # | 이슈 | 설명 |
|---|------|------|
| 9 | **org_manager_capabilities_loaded count: 0** | owner 1004용 capability 0건 로드. 기본값으로 진행. |
| 10 | **통화 종료 시점** | 발신자(BYE)가 LLM 응답 대기 중에 통화 종료. 정상 시나리오이나, 장시간 LLM 지연이 이탈 원인일 수 있음. |

---

## 3. 요약

- **시그널링·미디어·Pipecat 기동·STT 경로·녹음·CDR·후처리 STT**는 정상 동작.
- **TTS→RTP 구간**에서 (1) 인사말 직전 1초 빈 구간, (2) Phase1/Phase2 **tts_rtp_duration_mismatch**(약 22~25%), (3) 인사말 이후 **rtp_tts_queue_empty_timeout** 다수 발생으로, **인사말 끊김·말끝 잘림·구간 무음** 가능성이 있음.
- **RTP 20ms 간격 이탈**이 100회 기록되어, 음질/지터 개선 여지가 있음.
- **실시간 STT** "말씀해 주세요."는 인사말 꼬리 또는 에코로 보이며, **LLM 응답**은 통화 종료로 미재생.

상세 로그는 `logs/app.log`에서 `call_id: "fh0CbKB80u"` 로 검색하면 됨.
