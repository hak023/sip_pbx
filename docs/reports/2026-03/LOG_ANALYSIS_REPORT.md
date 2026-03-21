# app.log 분석 보고서 — 이슈·지연·Max Tokens·PCM

**기준 로그**: `sip-pbx/logs/app.log` (2026-03-09 기동·통화 1건)  
**목적**: (1) 이슈 점검 (2) 사용자 발화 후 AI 응대 지연 구간 분석 (3) max tokens 잘림·PCM 큐 비어있음 정리

---

## 1. 로그에서 발견된 이슈 요약

| 구분 | 이슈 | 심각도 | 비고 |
|------|------|--------|------|
| **1.1** | **tts_rtp_duration_mismatch** | 경고 | TTS Notifier duration vs RTP queued duration 불일치(예: 21.4%, 12.3%, 13.8%). Phase1/Phase2 잘림 또는 샘플레이트 불일치 가능. |
| **1.2** | **rtp_tts_queue_empty_timeout** | 정보 | PCM 큐가 1초간 비어 있음. 인사 Phase2 직후·사용자 발화 후 LLM+TTS 대기 구간에서 반복(1,2,3…10,20,30,40,50회). 예상 대기 구간이지만 로그 다발. |
| **1.3** | **llm_generate_response_finish_reason** | 혼동 가능 | 로그 note에 "MAX_TOKENS=길이 제한으로 잘림"이 항상 붙어 있어, finish_reason이 STOP(정상)인데도 잘림으로 오해할 수 있음. |
| **1.4** | **DB client 미설정** | 경고 | RAG/지식 매칭 로깅 시 "DB client not configured" — `ai_logger.set_db_client(db)` 미호출. |

---

## 2. 사용자 발화 후 AI 응대 지연 — 구간별 분석

**흐름**: 사용자 "날씨 알려 줘." → STT 완료 → LangGraph(의도분류·캐시·쿼리재작성·RAG·응답생성) → TTS → RTP

### 2.1 구간별 지연 (해당 로그 기준)

| 구간 | 역할 | 소요 시간 | 비고 |
|------|------|-----------|------|
| **STT** | 사용자 음성 → 최종 텍스트 | 매우 짧음 | 최종 결과 19:13:36.028 근처. 병목 아님. |
| **LLM (LangGraph 전체)** | 의도분류·캐시·재작성·RAG·응답생성 | **~22.9초** | **주요 병목** |
| ├ classify_intent | 의도 분류(LLM) | ~4.8초 | |
| ├ check_cache | 캐시 조회 | ~4.6초 | |
| ├ rewrite_query | 쿼리 재작성 | ~8.7초 | |
| ├ adaptive_rag | RAG 검색 | ~0.12초 | |
| └ generate_response | 응답 생성 | ~4.6초 | |
| **RAG** | 벡터 검색 | ~0.12초 | 병목 아님. |
| **TTS** | 첫 텍스트 → 첫 오디오 | ~0.1초 | 응답 직후 빠름. |
| **RTP** | PCM 큐 → SIP/RTP 전송 | 첫 오디오 후 ~0.5초 | 큐가 비어 있을 때는 대기만 함. |

### 2.2 결론

- **체감 “AI가 느리다”의 원인**: **LLM 파이프라인**(특히 classify_intent, check_cache, rewrite_query, generate_response)이 순차 실행되며 **총 ~23초**를 차지.
- **RTP/STT/TTS 자체**: 해당 로그에서는 지연의 주 원인이 아님. RTP는 “PCM 큐가 비어 있는 동안 1초 타임아웃”으로 대기하는 것이 반복될 뿐.

### 2.3 개선 방향 (참고)

- LangGraph 노드 중 **캐시·RAG**는 병렬화 검토.
- **classify_intent**·**rewrite_query**는 모델/프롬프트 경량화 또는 캐시 활용으로 구간 단축 검토.
- **generate_response**는 스트리밍 출력 시 첫 토큰까지 지연 단축이 체감 품질에 유리.

---

## 3. Max tokens “잘림” 로그 점검

### 3.1 로그 내용

- `llm_generate_response_finish_reason` 이벤트에 `finish_reason: "STOP"`, `response_len`, `max_output_tokens`와 함께  
  **note: "STOP=정상 종료, MAX_TOKENS=길이 제한으로 잘림"** 이 붙어 있음.

### 3.2 실제 동작

- **Gemini `finish_reason`**:  
  - `1` = STOP (정상 종료)  
  - `2` = MAX_TOKENS (최대 토큰 도달로 잘림)
- 해당 로그에서는 **모두 STOP**으로 기록됨 → **실제 잘림 없음**.
- 다만 note가 “MAX_TOKENS=길이 제한으로 잘림”을 항상 함께 적어 두어, **STOP인 경우에도 잘림으로 오해**할 수 있음.

### 3.3 조치

- **코드 수정**: `sip-pbx/src/ai_voicebot/ai_pipeline/llm_client.py`
  - `finish_reason == "STOP"`일 때는 `llm_generate_response_finish_reason` **info 로그를 남기지 않음** (또는 debug로만 출력).
  - **MAX_TOKENS**일 때만 **warning** + “응답이 max_output_tokens에서 잘림” 로그 유지.
- 이렇게 하면 “max tokens 길이 제한으로 잘림”은 **실제로 잘렸을 때만** 로그에 나타남.

---

## 4. PCM 큐 비어있음(rtp_tts_queue_empty_timeout) 점검

### 4.1 로그 내용

- `rtp_tts_queue_empty_timeout`: PCM 큐가 **1초 동안 비어 있어** 타임아웃이 발생했다는 정보 로그.
- `empty_timeouts`: 1, 2, 3, 10, 20, 30, 40, 50 … 형태로 증가.

### 4.2 원인

- RTP 발신 루프(`_pipecat_tts_sender_loop`)는 **PCM 큐에서 20ms 단위로 읽어 RTP로 전송**.
- **인사 Phase2 직후** 또는 **사용자 발화 직후 ~ LLM+TTS 완료 전**에는 아직 TTS가 큐에 넣은 데이터가 없음 → 큐가 비어 있음.
- 따라서 **해당 구간에서 1초 타임아웃이 반복되는 것은 설계상 예상 동작**에 가깝고, “음성 끊김/깨짐” 가능성은 **TTS가 데이터를 넣기 시작한 이후**에 큐가 자주 비는지로 판단하는 것이 맞음.

### 4.3 현재 구현

- `sip-pbx/src/media/rtp_relay.py`에서 이미 **로그 억제** 적용:
  - `empty_timeout_count <= 3` 또는 `empty_timeout_count % 10 == 0` 일 때만 info 로그 출력.
- 따라서 “PCM 큐 비어있음” 로그 다발은 어느 정도 정리된 상태.

### 4.4 정리

- **예상 대기 구간**(인사 후·사용자 발화 후 LLM 응답 전)의 empty timeout은 **에러가 아니라 정상**.
- **실제 문제**로 보려면: TTS가 이미 보내고 있는 구간에서 empty_timeout이 빈번한지, 또는 **tts_rtp_duration_mismatch**와 함께 재생 끊김이 보고되는지 확인하는 것이 좋음.

---

## 5. 요약

| 항목 | 내용 |
|------|------|
| **이슈** | tts_rtp_duration_mismatch(경고), rtp_tts_queue_empty_timeout(정보·억제됨), finish_reason note 오해 가능, DB client 미설정. |
| **지연** | 사용자 발화 후 체감 지연의 대부분은 **LLM 파이프라인**(classify_intent → check_cache → rewrite_query → generate_response) 구간. STT/RAG/TTS/RTP는 상대적으로 짧음. |
| **Max tokens** | 로그에는 모두 STOP. “잘림”은 **MAX_TOKENS일 때만** warning으로 남기고, STOP일 때는 info 로그 생략으로 오해 방지. |
| **PCM 큐 비어있음** | 예상 대기 구간에서의 empty timeout은 정상. 이미 3회+10회 단위로 로그 억제 적용됨. |

---

*문서: app.log 분석 기준 | finish_reason·PCM 동작 반영*
