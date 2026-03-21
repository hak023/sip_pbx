# 마지막 통화 점검 리포트 (call_id: 4udhVMNr2o)

**통화 개요**: 1003 → 1004 (기상청), no_answer 타임아웃 후 AI 인수, Pipecat 파이프라인.  
**기간**: 2026-02-21 15:54:06 (INVITE) ~ 15:57:21 (BYE 수신).  
**로그 기준**: `logs/app.log`

---

## 1. 통화 타임라인 요약

| 시점 | 이벤트 |
|------|--------|
| 15:54:06.331 | INVITE 수신 (1003 → 1004) |
| 15:54:06.339 | RTP Relay·녹음 시작, no_answer_timer 10초 |
| 15:54:06.641 | 180 Ringing (착신 1004에서 수신) |
| **15:54:16.340** | **no_answer_timeout → AI 인수** (CANCEL to callee, 200 OK to caller, Pipecat 시작) |
| 15:54:16.801 | call_established (caller: 1003, callee: AI) |
| 15:54:16.805 | TTS 첫 오디오 RTP 전송 (인사 Phase1) |
| 15:54:18.018 | Phase1 TTS 완료 (duration 6.7s, RTP 6.5s — 거의 일치) |
| 15:54:25.380 | Phase2 인사말 전송 (총 greeting 8.48s) |
| 15:54:27.068 | **tts_rtp_duration_mismatch** (Phase2: 13.2s vs 20.6s, 약 35.7%) |
| 15:54:51.680 | 사용자: "저는 내일의 날씨가 궁금해요." |
| 15:55:00.641 | LLM 응답: "네, 오늘 날씨 예보를" (12자, **의도와 불일치** — 내일 요청에 오늘 답변) |
| 15:55:01.034 | **tts_rtp_duration_mismatch** (94.2%: RTP 2.1s vs TTS 35.5s) |
| 15:55:33.299 | 사용자: "오늘의 날씨 말고 내일의 날씨가 궁금해요." |
| 15:55:38.197 | LLM 응답: "네, 내일의 날씨 예보를 안내해 드릴 수 있습니다. 어떤 지역의" (35자) |
| 15:55:38.922 | **tts_rtp_duration_mismatch** (88.7%: RTP 4.7s vs TTS 41.8s) |
| 15:56:11.005 | 사용자: "서울 지역을 알려주세요." |
| 15:56:19.790 | LLM 응답: "서울 지역의 내일 날씨 예보는 기상청 홈페이지(www.kma." (34자, **문장 중간 절단**) |
| 15:56:20.729 | **tts_rtp_duration_mismatch** (85.9%: RTP 6.9s vs TTS 49.0s) |
| 15:56:41.595 | 사용자: "감사합니다." → intent: farewell, response_len: 0 (정상 종료 응답 없음) |
| 15:57:21.635 | BYE 수신 (발신자 1003), 200 OK 응답, cleanup |
| 15:57:21.945 | Mixed WAV 저장, STT 사후 처리 시작 (caller/callee 분리 전사) |

---

## 2. 발견된 문제점

### 2.1 TTS → RTP 전송 불일치 (심각)

- **증상**: `tts_rtp_duration_mismatch` 경고가 **4회** 발생.  
  Notifier가 누적한 TTS 음원 길이가, Output이 큐에 넣은 PCM 양(→ RTP로 나가는 양)보다 **35~94%** 큼.
- **구체 수치**:
  - Phase2 인사: 20.6s vs 13.2s (약 35.7% 차이)
  - "네, 오늘 날씨 예보를": 35.5s vs 2.1s (**94.2%** — 극심)
  - "네, 내일의 날씨 예보를...": 41.8s vs 4.7s (88.7%)
  - "서울 지역의 내일 날씨...": 49.0s vs 6.9s (85.9%)
- **영향**: 발신자(1003)가 들을 수 있는 TTS 길이가 실제 합성된 음원보다 **짧음**. 앞부분만 들리거나 끊겨 들릴 수 있음.
- **원인 추정**: EndFrame이 해당 응답의 TTS 오디오보다 먼저 Output에 도달해, Output이 “이번 응답”에서 적은 바이트만 집계하는 프레임 순서 이슈. (자세한 분석: [TTS_RTP_QUEUE_REVIEW.md](./TTS_RTP_QUEUE_REVIEW.md))

- **구간 정의**: Notifier·Output 모두 응답 1건당 집계. Notifier에도 StartFrame 수신 시 누적값 리셋을 추가해, StartFrame~EndFrame 구간을 Output과 동일하게 맞춤.

### 2.2 LLM 응답 내용 오류

- **첫 번째 질의**: "저는 내일의 날씨가 궁금해요."  
  **응답**: "네, **오늘** 날씨 예보를" (12자).  
  사용자는 **내일**을 요청했는데, LLM/캐시가 **오늘**로 응답. semantic_cache_hit(0.947)로 캐시된 답변이 잘못 매칭된 가능성.
- **두 번째 질의**: "오늘의 날씨 말고 내일의 날씨가 궁금해요."  
  **응답**: "네, 내일의 날씨 예보를 안내해 드릴 수 있습니다. 어떤 지역의" — 이번에는 의도에 맞으나 **문장이 끊김** (끝이 "어떤 지역의").

### 2.3 LLM 응답 문장 절단

- **질의**: "서울 지역을 알려주세요."  
  **응답**: "서울 지역의 내일 날씨 예보는 기상청 홈페이지(**www.kma.**" (34자).  
  URL/문장 중간에서 끊겨, **max_output_tokens 또는 스트리밍 종료**로 인한 절단으로 보임.
- **원인 점검**: 대화 생성은 `config.yaml`의 `max_output_tokens: 500` 사용. 500 토큰은 2~3문장+URL에 경계선이라 **길이 제한으로 잘릴 수 있음**. 재테스트 시 `llm_generate_response_finish_reason`(MAX_TOKENS 여부) 로그로 확인. 자세한 내용은 [LLM_RESPONSE_LENGTH_CHECK.md](./LLM_RESPONSE_LENGTH_CHECK.md) 참고.
- **영향**: TTS는 이 짧은 문장만 읽어 주며, 사용자에게 완전한 안내(기상청 URL 등)가 전달되지 않음.

### 2.4 인사 종료 시 빈 응답 → **조치 완료: 마무리 멘트 구성**

- **당시 증상**: "감사합니다." → intent: farewell, business_state: closing. **응답**: `response_len: 0`. TTS로 재생할 문구 없음.
- **구성 내용**:
  - **farewell 시**: LangGraph `update_state` 노드에서 `state["response"]`에 마무리 멘트를 설정하도록 수정.
  - **DB(VectorDB tenant_config)**: `closing_templates` 필드에 JSON 배열로 마무리 멘트 목록 저장. `OrganizationInfoManager.get_random_closing_template()`으로 랜덤 선택.
  - **기본값**: DB에 없거나 비어 있으면 `"감사합니다. 필요하시면 다시 연락 주세요."` 사용.
- **문서**: [technical-architecture.md](../architecture/technical-architecture.md) tenant_config 스키마, [multi-tenant-rag-and-dashboard.md](../design/multi-tenant-rag-and-dashboard.md) 예시·흐름 참고.

### 2.5 DB/로깅 설정 경고 (통화 품질과 무관)

- `DB client not configured, skipping RAG logging`  
- `DB client not configured, skipping knowledge match logging`  
  AI DB 로깅이 꺼져 있어, RAG/지식 매칭 이벤트가 DB에 남지 않음. (설정 가이드: [AI_DB_LOGGING_SETUP.md](../guides/AI_DB_LOGGING_SETUP.md))

### 2.6 no_answer_timeout 중복 로그

- `no_answer_timeout_activating_ai` 가 동일 시점(15:54:16.340, 15:54:16.341)에 **2회** 기록됨.  
  로직상 한 번만 처리되더라도, 이벤트가 두 번 발생한 것처럼 보이므로 중복 발화 방지나 로그 정리가 필요할 수 있음.

---

## 3. 정상 동작으로 확인된 부분

- **SIP/B2BUA**: INVITE → 180 → no_answer 후 CANCEL/200 OK → ACK → 통화 연결 → BYE 수신 후 200 OK 및 정리.
- **AI 인수**: no_answer 10초 후 Pipecat 모드 전환, RTP 포트 유지, STUN 요청 전송.
- **녹음**: 시작/종료, 믹싱, caller/callee 분리 WAV 저장, STT 사후 처리(LongRunningRecognize) 시작까지 로그에 기록됨.
- **STT**: 사용자 발화 "저는 내일의 날씨가 궁금해요.", "오늘의 날씨 말고 내일의 날씨가 궁금해요.", "서울 지역을 알려주세요.", "감사합니다." 가 순서대로 인식됨.
- **RAG**: "오늘의 날씨 말고 내일의..." / "서울 지역을..." 에 대해 Vector 검색·adaptive_rag 완료, top_doc 등 반영됨.
- **인사 Phase1/Phase2**: Phase1 TTS 6.7s, Phase2 전송 전 event 대기 및 gap 대기(7.32s) 동작.
- **통화 종료**: BYE 수신 → bye_cleanup_triggered, call_session_removed, Mixed WAV 저장, STT 플로우 시작.

---

## 4. 조치 권장 사항

| 우선순위 | 항목 | 권장 조치 |
|----------|------|-----------|
| **완료** | TTS–RTP 불일치 | TTSEndFrameForwarder에서 upstream EndFrame 미전달, TTSStoppedFrame 수신 후에만 synthetic EndFrame 전송하도록 수정함. 재테스트 시 tts_rtp_duration_mismatch 감소 여부 확인. [TTS_RTP_QUEUE_REVIEW.md](./TTS_RTP_QUEUE_REVIEW.md) §7 참고. |
| **높음** | LLM 오늘/내일 혼동 | semantic cache 키/스코어 또는 의도 분류가 “내일 날씨”와 “오늘 날씨”를 구분하도록 점검. 쿼리 정규화(rewrite) 시 “내일”이 유지되는지 확인. |
| **중간** | LLM 응답 절단 | “서울 지역…” 답변의 max_output_tokens 또는 스트리밍 종료 조건 확인. URL/긴 문장이 끝까지 생성되도록 조정. |
| **완료** | farewell 빈 응답 | DB tenant_config.closing_templates + update_state에서 마무리 멘트 설정. 기본값 제공. |
| **참고** | DB 로깅 | 운영에서 RAG/지식 매칭 분석이 필요하면 `ai_logger.set_db_client(db)` 및 [AI_DB_LOGGING_SETUP.md](../guides/AI_DB_LOGGING_SETUP.md) 적용. |

---

## 5. 참고 문서

- [TTS_RTP_QUEUE_REVIEW.md](./TTS_RTP_QUEUE_REVIEW.md) — TTS 출력·queueing·불일치 원인 분석  
- [TTS_RTP_AND_HITL_DESIGN.md](./TTS_RTP_AND_HITL_DESIGN.md) — TTS→RTP·HITL 설계  
- [AI_DB_LOGGING_SETUP.md](../guides/AI_DB_LOGGING_SETUP.md) — AI DB 로깅 설정
