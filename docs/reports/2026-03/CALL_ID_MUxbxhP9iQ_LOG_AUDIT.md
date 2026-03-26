# 로그 점검: call_id `MUxbxhP9iQ`

- **작성일**: 2026-03-24 (로컬)
- **상태**: `app.log` 기반 사실 정리
- **관련 로그**: `sip-pbx/logs/app.log`

## 1. 통화가 “끊긴” 원인

### 최종 종료 (SIP)

- `bye_received` — `2026-03-24T15:33:53.135`, `from_addr`: `172.21.26.47:34134`
- 이어서 `bye_response_sent`, `bye_cleanup_triggered` (`reason`: `BYE received in AI mode`), `pipecat_pipeline_cancelled_on_bye`, `recording_stopped` (약 138s)

**해석**: 발신 단말(또는 그 쪽 SIP 스택)이 **정상 BYE**로 통화를 종료했습니다. 서버가 임의로 끊은 흔적은 아닙니다.

### 초기 “착신 무응답 후 전환” (끊김으로 오해하기 쉬운 구간)

- `no_answer_timeout_activating_ai` — `15:31:44.941`, `timeout`: 10
- 착신(1004) 쪽으로 `CANCEL` 전송, `487_not_relayed_ai_mode` (AI 모드에서 487 미중계는 설계 로그)

**해석**: 10초 무응답 후 **AI 테이크오버**로 넘어간 구간입니다. SIP 상 “통화 실패”가 아니라 **콜레그 전환**에 가깝습니다.

---

## 2. 대기 멘트(“정보를 확인 중…” / “잠시만…”)와 RTP

### 구현·로그상 특징

- `llm_processing_notification`, `wait_sec`: **12.0** — LLM이 오래 걸릴 때 **대기 안내 TTS 1회** 트리거.
- `tts_text_input`이 **문장 단위로 쪼개짐**: 먼저 `"정보를 확인 중입니다."`, 이어서 `"잠시만 기다려 주세요."` (각각 별도 TTS 호출로 보임).

### 첫 번째 대기 멘트 구간 (`~15:32:23`)

- `llm_processing_notification` 직전 구간에 `rtp_tts_queue_empty_timeout` (PCM 큐 공백) — **이전 TTS가 끝난 뒤 LLM 대기 중 묵음**과 일치.
- 대기 멘트 재생 후 `tts_rtp_duration_mismatch` 경고: **Notifier 오디오 프레임 수(55) vs Output 쪽 프레임 수(8)** 등 불일치. 로그 주석대로 **EndFrame·파이프라인 순서** 이슈 가능 (일반 응답과 동일 RTP 경로이나, **짧은/분할 TTS에서 타이밍·프레이밍이 더 두드러질 수 있음**).

### 두 번째 대기 멘트 직후 RTP가 “끊긴 것처럼” 보이는 결정적 이유

- `15:33:52.832` — `llm_processing_notification` + 첫 `tts_text_input` (“정보를 확인 중입니다.”)
- `15:33:52.848` — `tts_first_audio_received`
- **`15:33:53.135` — `bye_received`** (약 **0.3초** 후)
- `15:33:53.140` — `pipecat_input_transport_stopped`
- `15:33:53.273` — `tts_first_audio_sent_to_rtp` (정리 루프와 레이스)
- `rtp_absolute_timing_summary`에 **`total_packets_sent`: 1** — **거의 한 패킷만 나가고 파이프라인 취소**

**해석**: “대기 멘트만 RTP가 죽는다”기보다, **BYE가 대기 멘트 직후에 들어와** TTS/RTP가 시작 단계에서 **취소**된 사례로 로그가 강하게 지지합니다. 첫 번째 대기 멘트는 상대적으로 긴 구간이 재생·로그에 남음.

---

## 3. LLM 관련 시간이 길어 보이는 포인트 (이 호 기준)

`app.log`에 `agent_graph_total` 같은 세부 타이밍 JSON은 이 통화 구간에서 거의 없고, **타임스탬프 차이**로 구간을 나눌 수 있습니다.

| 구간 | 대략적 시간 | 비고 |
|------|-------------|------|
| 첫 발화 STT→RAG | `15:32:11.394` `timing_stt_final_to_rag` | 이후 **약 12s**에 `llm_processing_notification` → LangGraph/LLM이 **12s 넘게 지속** |
| 동일 발화 후 RAG 한 번 더 | `15:32:37.211` `⏱️ [TIMING] adaptive_rag 완료` | 발화 시각 기준 **~26s** 후에야 해당 RAG 완료 로그 (그래프 내 **다단계·재검색/재작성** 가능성) |
| “도와줄 수 있나요?” | `15:33:11.056` → `15:33:17.500` `help_response_llm_*` | **~6.4s**, `parse_ok: false` → **폴백** |
| “기상 감정서…” | `15:33:40.834` → `15:33:47.969` adaptive_rag | **~7.1s** 후 RAG 완료 |
| 동일 발화 후 다시 대기 안내 | `15:33:52.832` `llm_processing_notification` | STT 직후 **약 12s** 경과 시점과 일치 → **또 LLM 장시간** |

**요약**: 병목 후보는 (1) **LangGraph 전체 실행 시간**(12s 워치독이 두 번 울림), (2) **help 응답 LLM 파싱 실패**로 인한 추가 지연/폴백, (3) **RAG는 수백 ms 수준**으로 로그상 짧고, **벡터 검색 자체보다 그래프·생성 단계**가 길어 보임.

---

## 권장 후속 (코드/운영)

- 대기 멘트 직후 BYE 레이스 재현 시: **BYE 시점**과 `llm_processing_notification` 상대 시각을 같은 대시보드/트레이스에 묶어 확인.
- ~~`tts_rtp_duration_mismatch`가 대기 멘트에서만 두드러지면~~ **반영됨 (2026-03-24)**: `rag_processor` 대기 멘트를 문장별 `LLMFullResponseStart` → `TextFrame` → `LLMFullResponseEnd` ×2 + 청크 간 `sleep(0.05)` 로 본 응답과 동일 패턴 정렬.
- ~~LLM 구간 정밀 분석~~ **반영됨 (2026-03-24)**: `langgraph/agent.py` `ConversationAgent.process_utterance`가 `graph.astream(..., stream_mode=["updates","values"])`로 **단일 실행**에서 최종 state를 쓰고, `updates` 키(노드명)로 구간 시간을 합산 → `langgraph_node_durations_sec` 로그 + `call_data` `agent_graph_total`에 `agent_graph_node_durations_sec` 포함. 미지원/실패 시 `ainvoke` 폴백.
