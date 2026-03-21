# call_id yQpeFs~dWm 로그 리뷰 및 문제점

## 호 개요

| 항목 | 내용 |
|------|------|
| **call_id** | `yQpeFs~dWm` (b2bua-185628-yQpeFs~d) |
| **시작** | 2026-03-15 20:46:18.735 — INVITE 1003→1004 |
| **no_answer → AI** | 20:46:28.750 (10초 타임아웃) |
| **BYE 수신** | 20:47:41.040 (발신자 끊음) |
| **통화 구간** | 약 82초 (AI 구간 약 72초) |

**흐름 요약**: 1003→1004 INVITE → 180 Ringing → 10초 no_answer → AI 터크오버 → Pipecat 기동 → 인사말 Phase1/2 TTS → 사용자 "오늘의 날씨가 궁금합니다." STT(20:46:45) → RAG 검색 0건 → LLM "해당 내용은 확인이 필요합니다. 잠시만 기다려 주세요." → HITL 알림(low_confidence) → HITL 타임아웃 구간에서 **타임아웃 정제 메시지** "고객님, 문의해 주셔서"가 로그에 `hitl_response_received`로 기록됨(실제 운영자 응답이 아님). 이후 발신자 BYE로 종료.

---

## 문제점 리스트

### 1. RAG 검색 결과 없음 (지식 DB 미활용)

| 로그 | 내용 |
|------|------|
| `rag_search_completed` | results_count=0, query="오늘의 날씨", owner_filter="1004" |
| `adaptive_rag_no_results` | Vector 검색 결과 없음 |
| `step_back` 검색 | "날씨 정보를 확인하는 방법은 무엇인가요?" → results_count=0 |

**원인**: owner=1004 지식 컬렉션에 "날씨" 관련 문서가 없거나, 시드가 안 된 상태.  
**영향**: AI가 지식 기반 답변 대신 일반 LLM 응답 + HITL(확인 필요)으로 처리.

---

### 2. org_manager_capabilities_loaded count=0

| 로그 | 내용 |
|------|------|
| `org_manager_capabilities_loaded` | count=0, owner=1004 (인사말 Phase1 직전) |

**원인**: capability 문서 0건 로드 (get_all_capabilities 실패 또는 DB에 capability 없음).  
**영향**: 인사말 Phase2 등 capability 기반 문구가 비어 있을 수 있음.

---

### 3. TTS ↔ RTP 재생 길이 불일치 (tts_rtp_duration_mismatch)

| 구간 | Notifier 프레임/길이 | Output 큐 투입 | diff_ratio_pct |
|------|----------------------|----------------|-----------------|
| Phase1 인사말 | 107 frames, 8.335s | 14 frames, 6.481s | 22.2% |
| Phase2 인사말 | 48 frames, 4.638s | 8 frames, 3.84s | 17.2% |
| 대기 안내 | 53 frames, 4.258s | 8 frames, 3.361s | 21.1% |
| 최종 응답 | 47 frames, 4.758s | 9 frames, 4.0s | 15.9% |

**원인**: Notifier(음원 길이·프레임 수)와 Output(큐 투입 바이트·프레임 수) 불일치. 프레임 수/바이트 누락 또는 sample_rate·경계 이슈 가능.  
**영향**: TTS 재생 시 일부 구간 끊김·침묵·짧게 들릴 수 있음.

**인사말은 손실 없고 이후 대답에서만 손실이 나는 이유 (추정)**: 인사말은 **flush 없이 연속 스트림**으로 재생되고, 이후 응답은 **tts_flush_requested_nonblocking** 후 **StartFrame → 새 TTS** 경로를 탄다. 이때 (1) flush 직후 또는 StartFrame 직후 첫 청크가 Output(큐)까지 도달하지 못하거나, (2) 응답 경계에서 Notifier/Output의 “이 응답” 카운트 리셋 타이밍이 어긋나 누락이 발생하는 것으로 추정.  
**디버깅 로그 강화**: 응답 단위 식별(`response_id`/`phase`), Notifier/Output 각각 이 응답의 누적 바이트·첫 청크 시각, flush/StartFrame 경계 시 로그를 추가하면 원인 좁히기 쉬움. 상세 스펙·체크리스트는 `docs/design/TTS_RTP_LOSS_DEBUG_LOGGING.md` 참고.

---

### 4. RTP 20ms 간격 이탈 (rtp_interval_violation)

| 로그 | 내용 |
|------|------|
| 다수 | actual_ms 5.7~36.1, expected_ms 20, violation_count 1~150 |

**원인**: TTS→RTP 발송 루프에서 20ms 기준 간격 이탈(지터).  
**영향**: 소규모 오디오 지터, 일부 환경에서만 체감 가능.

---

### 5. PCM 큐 빈 구간 반복 (rtp_tts_queue_empty_timeout)

| 로그 | 내용 |
|------|------|
| 다수 | empty_timeouts 1~30, "PCM 큐 1초간 비어 있음 — 해당 구간 음성 끊김/깨짐 가능" |

**원인**: TTS 청크가 RTP 발송 루프에 도달하기 전에 큐가 비는 구간 발생.  
**영향**: 해당 구간에서 침묵 또는 끊김 체감 가능.

---

### 6. DB client 미설정 (RAG 로깅 스킵)

| 로그 | 내용 |
|------|------|
| `DB client not configured, skipping RAG logging` | hint: ai_logger.set_db_client(db) |

**원인**: RAG 검색 로그를 DB에 남기려 하나 DB 클라이언트 미설정.  
**영향**: 분석/디버깅용 RAG 로그가 DB에 쌓이지 않음.

**구현 완료**: `ai_logging` 모듈에서 DB 로깅 구현됨. 앱 기동 시 `ai_logging.set_db_client(db)` 또는 `ai_logging.use_sqlite_file("data/rag_log.db")` 후 `init_sqlite_schema()` 호출하고, RAG 검색 직후 `log_rag_search(call_id, query, owner_filter, results_count, ...)` 호출하면 됨. 상세: `docs/design/RAG_DB_LOGGING.md`.

---

### 7. HITL low_confidence 및 운영자 응답 미반영

| 로그 | 내용 |
|------|------|
| `hitl_alert_triggered` | confidence=0.000, reason="AI가 모르는 내용으로 응답했습니다. 확인이 필요합니다." |
| `hitl_alert_processing` | alert_type=low_confidence |
| `llm_exchange_full` | response="해당 내용은 확인이 필요합니다. 잠시만 기다려 주세요." |
| `hitl_timeout_message_refining` | original_text="확인이 지연되고 있습니다. 확인되는 대로 연락 드리겠습니다." (타임아웃 템플릿) |
| `hitl_timeout_message_refined` | refined_text_full="고객님, 문의해 주셔서" (LLM이 타임아웃 문구 정제 결과) |
| `hitl_response_received` | text_preview="고객님, 문의해 주셔서" ← **실제 운영자 응답이 아님** |

**원인**: RAG 0건 + LLM 지식 없이 응답 → confidence 0 → HITL 발동.  
**운영자 응답이 반영되지 않은 이유**: 백엔드가 **HITL 타임아웃** 시 생성한 **정제 폴백 메시지**(`hitl_timeout_message_refined`: "고객님, 문의해 주셔서")를 **운영자 응답**과 같은 경로로 처리하여 `hitl_response_received`로 로깅·TTS에 사용한 것으로 추정됨. 즉, 타임아웃 경로와 운영자 `submit_hitl_response` 경로가 혼동되었거나, 타임아웃이 먼저 실행되어 실제 운영자 응답이 무시/덮어쓴 가능성 있음.  
**영향**: 운영자가 다른 내용으로 답했어도, 통화에는 타임아웃 정제 문구만 반영되거나 로그에만 잘못 기록됨.

**조치**: HITL → 프론트(운영자 응답) → 백엔드 수신 → LLM(선택) → TTS 흐름 및 타임아웃 경로 분리 설계는 `docs/design/HITL_OPERATOR_RESPONSE_FLOW.md` 참고. 백엔드에서 타임아웃 시 `hitl_response_received`를 호출하지 않고, `submit_hitl_response` payload의 `response_text`만 운영자 응답으로 사용하도록 수정 필요.

---

### 8. step_back RAG 검색 시 call_id 비어 있음

| 로그 | 내용 |
|------|------|
| `rag_search_completed` (20:46:59.838) | call_id="", owner_filter="1004", query="날씨 정보를 확인하는 방법은 무엇인가요?" |

**원인**: step_back 경로에서 RAG 검색 시 call_id를 전달하지 않음.  
**영향**: 로그/분석 시 해당 검색을 통화에 연결하기 어렵고, call_id 기반 필터가 있다면 동작 오류 가능성.

---

## 정상 동작으로 확인된 항목

- INVITE → 180 → no_answer 10초 → AI 터크오버 → 200 OK → ACK → call_established
- Pipecat 파이프라인 기동, STT 경로(RTP→큐→파이프라인) 정상
- STT "오늘의 날씨가 궁금합니다." → RAG → classify_intent → rewrite_query → generate_response
- HITL 알림 발동; 타임아웃 시 hitl_timeout_message_refining → hitl_timeout_message_refined("고객님, 문의해 주셔서")가 hitl_response_received로 잘못 로깅됨(실제 운영자 응답 아님)
- BYE 수신 → cleanup → 녹음 mixed 저장, post_stt(LongRunningRecognize) 시작

---

## 권장 조치 (우선순위)

| 순위 | 항목 | 조치 |
|------|------|------|
| 1 | RAG 0건 | 1004 테넌트에 날씨/기상 지식 시드 추가. scripts/README_KNOWLEDGE_SEED.md 참고. |
| 2 | TTS-RTP 불일치 | Notifier vs Output 프레임/바이트 경계·sample_rate 일치 여부 점검. (TTS_CHOPPY_ISSUE_ANALYSIS 등 참고) |
| 3 | step_back call_id | step_back RAG 검색 시 call_id 전달하도록 수정. |
| 4 | capabilities 0건 | 1004 capability 시드 또는 get_all_capabilities 실패 원인 확인. |
| 5 | RTP violation / empty_timeout | RTP 발송 루프·TTS 청크 도달 타이밍 튜닝 (필요 시). |
| 6 | RAG DB 로깅 | `ai_logging` 모듈 구현됨. `use_sqlite_file()` 또는 `set_db_client()` + `log_rag_search()` 연동. `docs/design/RAG_DB_LOGGING.md` 참고. |

---

---

## 이전 통화(VPl-nSRqkr) 지식 추출 → 저장 여부 (추가 분석)

**질문**: 이전 통화에서 지식베이스에 입력된 것처럼 보이는데 맞는가?

**결론: 아니요. 지식베이스에는 입력되지 않았습니다.**

| 단계 | 로그 | 의미 |
|------|------|------|
| Stage 2 완료 | knowledge_count=2, total_items=2 | LLM이 2건 추출 (날씨 FAQ·정보) |
| Stage 3 완료 | **skipped_halluc=2**, skipped_dedup=0, skipped_quality=0, **verified=0** | 품질 검증에서 2건 모두 **환각(haluc)으로 판단해 스킵** |
| Stage 4 저장 | (저장 대상 0건) | 검증 통과한 항목이 없음 |
| 추출 완료 | **stored=0** | 실제 VectorDB 저장 **0건** |

- **RAG 검색이 되지 않은 이유**: 위와 같이 이전 통화에서 추출된 2건이 **저장되지 않았기 때문**입니다. owner=1004 지식 컬렉션에 날씨 관련 문서가 없어서 yQpeFs~dWm 호에서 `rag_search_completed` results_count=0이 된 것이 맞습니다.
- **점검 필요**: Pipeline v2의 **Stage 3 품질 검증(haluc 판정)** 로직이 통화 원문에 있는 날씨 답변을 왜 전부 “환각”으로 스킵했는지 확인이 필요합니다. 해당 파이프라인 코드(Stage 3, skipped_halluc를 남기는 부분)는 **현재 워크스페이스에 없습니다**(git status 상 삭제된 파일들에 포함된 것으로 추정). 지식 추출·저장 로직을 점검하려면 해당 백엔드 코드를 복구한 뒤, “원문에 명시된 착신자 발화만 추출”한 경우 haluc로 스킵하지 않도록 조건을 완화하거나 로그를 추가해 원인을 파악하는 것이 좋습니다.

### 수정 방안 (반영 완료)

환각으로 잡히지 않도록 아래 네 가지가 설계·구현되어 있습니다.

| # | 요구사항 | 반영 내용 |
|---|----------|-----------|
| 1 | **환각 로직 필요 여부** | 필요하되, **문자열 일치 대신 의미 기반 검증**으로 변경. 설계: `docs/design/KNOWLEDGE_STAGE3_AND_LOGGING.md` §1. |
| 2 | **의미 기반 검증 + 전사 재구성** | Stage 3에서 **전사 착신자만 재구성**(문장 단위 선택 가능) 후 **임베딩 유사도**로 검증. 구현: `knowledge_pipeline/stage3_verify.py` (`reconstruct_callee_transcript`, `verify_extracted_items`). |
| 3 | **이미 존재하는 지식은 저장 제외** | Stage 4 저장 전 **기존 KB와 유사도**로 중복 검사, `threshold_dedup` 이상이면 저장 스킵. 구현: `knowledge_pipeline/stage3_verify.py` (`filter_duplicates_for_save`). |
| 4 | **지식 저장·RAG 상세 로그** | Stage 3/4·RAG용 이벤트 스펙 및 로그 포인트 정리. 설계: `docs/design/KNOWLEDGE_STAGE3_AND_LOGGING.md` §4. 구현: `knowledge_pipeline/stage3_verify.py`(Stage 3/4), `knowledge_pipeline/logging_events.py`(이벤트 상수·RAG 헬퍼). |

- **통합 방법**: 기존 파이프라인 코드가 있는 위치에서 `knowledge_pipeline`을 import해 Stage 2 출력 → `verify_extracted_items` → `filter_duplicates_for_save` → 저장 루프에서 `knowledge_stage4_stored_item` 로그 호출. 예시는 설계 문서 §5.1 참고.

---

## 왜 환각(haluc)으로 판정했는지 — 추정 이유

Stage 3 품질 검증 코드는 워크스페이스에 없어 **정확한 판정 근거는 코드로 확인할 수 없습니다.** 다만 로그에 남은 **원문 전사**와 **LLM 추출 문장**을 비교하면, 아래와 같은 이유로 “원문에 없다”고 보고 환각으로 스킵했을 가능성이 큽니다.

### 1. 원문 전사 형태 (실제 입력)

전사는 **발신자/착신자가 한 단어·짧은 구절 단위로 번갈아** 나오는 형태입니다.

```
착신자: 오늘의    발신자: 오늘의
착신자: 날씨가   발신자: 날씨가
...
착신자: 날씨 는  발신자: 는 맑
착신자: 맑 다가  발신자: 다가
착신자: 한       발신자: 한
착신자: 때       발신자: 때
착신자: 비가     발신자: 비가
...
착신자: 시 부터는  발신자: 시 부터는
착신자: 이기     발신자: 이기
착신자: 때문에 우 발신자: 때문에 우
착신자: 산 을    발신자: 산
착신자: 하셔야 겠습니다  발신자: 되겠습니다
```

- 착신자만 이어 붙이면:  
  `"오늘의 날씨가 어떻게 될까요? 네 오늘의 **날씨 는** **맑 다가** 한 때 비가 올 예정입니다. 오후 3 **시 부터는** ... **이기** 때문에 우**산 을** 꼭 준비 **하셔야 겠습니다** ..."`
- 즉, **띄어쓰기 비정규**("날씨 는", "맑 다가", "시 부터는", "하셔야 겠습니다")이고, **조각 나 있는 형태**입니다.

### 2. LLM이 추출한 문장 (정제 결과)

| # | 추출 text |
|---|-----------|
| 1 | "오늘의 날씨는 맑다가 한때 비가 올 예정입니다." |
| 2 | "오후 3시부터는 비가 올 예정이기 때문에 우산을 꼭 준비하셔야 겠습니다." |

- 의미상으로는 전사와 동일한 내용이지만, **정규화된 문장**(띄어쓰기·붙쓰기 수정)이라 **원문 문자열과 완전히 일치하지 않습니다.**

### 3. Stage 3에서 환각으로 판정했을 가능성이 큰 이유

일반적인 “환각 검사” 방식과 조합하면 다음과 같이 설명할 수 있습니다.

| 추정 메커니즘 | 설명 |
|---------------|------|
| **원문 대조(grounding)** | “추출된 text가 **원문(전사) 문자열에 그대로 포함**되어 있는가?” 또는 “원문의 **부분문자열**로 복원 가능한가?”를 검사. 원문이 조각·비정규 띄어쓰기라 정제 문장이 **literal로 존재하지 않음** → **미충족 → 환각**으로 처리. |
| **유사도/임계값** | 임베딩 유사도나 문장 유사도를 쓰는 경우, 전사가 조각나 있어서 정제 문장과의 유사도가 **임계값 미만**으로 나와 “원문에 기반하지 않음”으로 판단 → 환각. |
| **NLI/entailment** | “추출 문장이 전사로부터 유도(entail)되는가?”를 검사하는 모델을 쓰는 경우, 전사가 짧은 조각 나열이라 **entailment 점수가 낮게** 나와 환각으로 분류. |

즉, **“원문에 있는 착신자 발화를 정리한 것”인데도**,  
- 원문이 **조각 + 비정규 띄어쓰기**이고  
- 검증기가 **문자열 일치 또는 과도하게 엄격한 grounding**만 사용할 경우  

**정제된 문장이 원문에 “그대로 없다”고 보고 전부 환각으로 스킵했을 가능성이 높습니다.**

### 4. 정리 및 제안

- **판정 이유(추정)**: “추출된 문장이 **원문 전사와 문자열/형태가 다르다**”는 식의 **과도하게 엄격한 grounding** 때문에, 실제로는 원문 기반인 2건이 전부 환각으로 처리된 것으로 보는 것이 타당합니다.
- **개선 방향** (파이프라인 코드 복구 후):  
  - 전사에서 **착신자 발화만 추출해 하나의 문자열로 이어 붙인 뒤**, 그 문자열과 추출 text를 비교하거나,  
  - **정규화(띄어쓰기·공백 제거)** 후 포함 관계/유사도를 보거나,  
  - **의미 기반 검증**(NLI/유사도)을 쓰되 **전사는 문장 단위로 재구성**한 뒤 비교하도록 Stage 3 로직을 조정하는 것이 좋습니다.

---

## 참고

- **로그 구간**: app.log 약 1850행 ~ 2355행 (call_id yQpeFs~dWm, b2bua-185628-yQpeFs~d).
- **녹음**: recordings/20260315_204618_1003_to_1004 (mixed.wav 71.18초, caller/callee 분리).
- **이전 통화 지식 추출**: app.log 약 1825~1848행 (call_id VPl-nSRqkr).
