# call_id njFvF7yFhr 이슈 리뷰 및 트래킹

## 호 개요

| 항목 | 내용 |
|------|------|
| **call_id** | `njFvF7yFhr` (b2bua-680504-njFvF7yF) |
| **시작** | 2026-03-15 02:30:56.981 — INVITE 1003→1004 |
| **no_answer → AI** | 02:31:07.003 (10초 타임아웃) |
| **BYE 수신** | 02:31:49.322 (발신자가 전화 끊음) |
| **통화 구간** | 약 52초 (INVITE~BYE), AI 구간 약 42초 |

**흐름 요약**: 1003→1004 INVITE → 180 Ringing → 10초 no_answer → AI 터크오버 → Pipecat 기동 → 인사말 Phase1/2 TTS 재생 → 사용자 "오늘의 이씨가 궁금합니다." STT(02:31:47) → RAG/LLM 처리 진행 중 **사용자가 BYE(02:31:49)** → 통화 종료 후에도 classify_intent·rewrite_query·rag_search 완료(02:31:57) → **AI 최종 응답이 사용자에게 전달되지 않음**.

---

## 이슈 트래킹

### 1. 사용자 발화 후 응답 전에 BYE — 응답 미전달

| 항목 | 내용 |
|------|------|
| **현상** | 사용자: "오늘의 이씨가 궁금합니다." (STT 02:31:47) → 약 2초 후 BYE(02:31:49). LLM classify_intent는 02:31:49.526에 완료, rewrite_query·RAG 검색은 02:31:57에 완료. |
| **원인** | LLM/RAG 처리 지연( classify_intent ~2.4s, rewrite_query ~8s)으로 첫 응답이 나오기 전에 사용자가 전화를 끊음. |
| **영향** | AI가 생성한 응답이 발신자에게 재생되지 않음. |
| **권장** | (1) "잠시만 기다려 주세요" 등 대기 안내 TTS를 STT→RAG 구간 초기에 재생하거나, (2) LLM/rewrite/RAG 지연 단축(캐시·모델·쿼리 단순화), (3) `llm_processing_notification`(5초 경과 안내)를 더 앞당겨 재생하는 방안 검토. |

---

### 2. RAG 검색 결과 없음 — 지식 DB에 해당 내용 부재

| 항목 | 내용 |
|------|------|
| **로그** | `rag_search_completed` results_count=0, query="오늘 이씨에 대한 정보를 검색합니다.", owner_filter="1004" |
| **원인** | 질의에 맞는 지식이 벡터 DB에 없음(또는 owner=1004 문서만 검색하여 0건). |
| **영향** | adaptive_rag_no_results 경로로 동작하며, 지식 기반 응답 대신 일반 LLM 응답에 의존. |
| **권장** | 해당 질의용 지식 시드 추가 여부 검토. 필요 시 RAG 없을 때 안내 문구/폴백 응답 정리. |

---

### 3. org_manager_capabilities_loaded count=0

| 항목 | 내용 |
|------|------|
| **로그** | 인사말 Phase1 직전 `org_manager_capabilities_loaded` count=0, owner=1004 |
| **의미** | capability 문서가 0건 로드됨. (이전 호 WffK2U7gOs에서의 get_all_capabilities_failed 수정 반영 시, 에러 없이 0건일 수 있음.) |
| **영향** | 인사말 Phase2 등 capability 기반 문구가 비어 있을 수 있음. |
| **권장** | 1004 소유 capability 시드 데이터 등록 여부 확인. |

---

### 4. RTP/TTS 큐 빈 구간 — 음성 끊김 가능성

| 항목 | 내용 |
|------|------|
| **로그** | `rtp_tts_queue_empty_timeout` empty_timeouts=1, 10, 20, 30 — PCM 큐가 1초간 비어 있음. packets_sent=440 등. |
| **의미** | TTS→RTP 구간에서 재생할 PCM이 없는 구간이 반복됨. |
| **영향** | 해당 구간에서 음성 끊김/침묵 체감 가능. |
| **권장** | TTS 생성 지연, RTP 발송 루프와의 정렬, 버퍼링 정책 점검. (기존 TTS_CHOPPY_ISSUE_ANALYSIS 등 참고.) |

---

### 5. RTP 20ms 간격 이탈 (경미)

| 항목 | 내용 |
|------|------|
| **로그** | `rtp_interval_violation` actual_ms=29 expected_ms=20, actual_ms=11 expected_ms=20 등. |
| **의미** | 20ms 기준 RTP 패킷 간격이 일부 구간에서 이탈. |
| **영향** | 소규모 지터, 일부 환경에서만 체감될 수 있음. |
| **권장** | 지속적일 경우 RTP 발송 루프·절대 시간 보정 로직 재검토. |

---

### 6. DB client 미설정 — RAG 로깅 스킵

| 항목 | 내용 |
|------|------|
| **로그** | `DB client not configured, skipping RAG logging` (hint: ai_logger.set_db_client(db)) |
| **의미** | RAG/LLM 상호작용 로깅을 DB에 남기려 했으나 DB 클라이언트가 설정되지 않음. |
| **영향** | 분석/디버깅용 RAG 로그가 DB에 쌓이지 않음. |
| **권장** | 필요 시 ai_logger에 DB 클라이언트 설정하여 RAG 로깅 활성화. |

---

## 참고 로그 위치

- **app.log**: call_id `njFvF7yFhr` / b2bua `b2bua-680504-njFvF7yF` 구간 (약 1063행~1465행).
- **녹음/트랜스크립트**: `recordings/20260315_023056_1003_to_1004/` (mixed.wav, caller.wav, callee.wav, transcript.txt).
- **CDR**: cdr-2026-03-15.jsonl 등.

---

## 요약

| 우선순위 | 이슈 | 조치 방향 |
|----------|------|------------|
| 높음 | 사용자 BYE로 AI 응답 미전달 | 대기 안내 TTS·LLM/RAG 지연 단축·알림 타이밍 조정 |
| 중간 | RAG 결과 0건 | 지식 시드·owner 필터·폴백 응답 정리 |
| 중간 | capabilities 0건 | 1004 capability 시드 등록 검토 |
| 낮음 | rtp_tts_queue_empty_timeout | TTS/RTP 버퍼·타이밍 점검 |
| 낮음 | rtp_interval_violation | RTP 발송 루프 점검 |
| 참고 | RAG DB 로깅 미동작 | ai_logger DB 설정 필요 시 적용 |
