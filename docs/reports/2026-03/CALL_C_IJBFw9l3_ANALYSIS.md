# 콜 C~IJBFw9l3 AI 응대 시나리오 점검 보고

**call_id**: `C~IJBFw9l3`  
**시나리오**: AI 응대 (무응답 10초 후 AI 터크오버)  
**기간**: 2026-03-14 17:09:22 ~ 17:11:46 (약 2분 24초)

---

## 1. 통화 흐름 요약

| 시각 | 이벤트 | 비고 |
|------|--------|------|
| 17:09:22 | INVITE 수신 (1003→1004) | B2BUA, RTP 릴레이·녹음 시작 |
| 17:09:32 | 무응답 10초 → AI 터크오버 | CANCEL to callee, 200 OK to caller, Pipecat 시작 |
| 17:09:33 | 통화 연결(ACK), 인사말 Phase1 전송 | "안녕하세요. 기상청 AI 통화 비서입니다. 무엇을 도와드릴까요?" |
| 17:09:38 | 인사말 Phase2 전송 | "저는 날씨 예보 조회, … 어떤 것이 궁금하신가요?" |
| 17:09:55 | 사용자 1차 발화 STT → LLM | "오늘의 날씨가 궁금합니다." |
| 17:10:02 | 5초 경과 → 대기 안내 TTS | "정보를 찾고 있습니다. 잠시만 기다려 주세요." (semantic_cache 오류 직후) |
| 17:10:07 | RAG 검색 완료 | query "오늘의 날씨를 검색합니다.", 3건, confidence 0.832 |
| 17:10:15 | LLM 응답 → TTS 푸시 | 84자, agent_elapsed 19.743s |
| 17:10:37 | 사용자 2차 발화 | "혹시 거기 찾아가려면 어떻게 가야 되나요?" |
| 17:11:05 | LLM 응답 (2차) | 71자, agent_elapsed 28.039s |
| 17:11:19 | 사용자 3차 발화 | "네 연결해 주세요." → **transfer_request_detected** |
| 17:11:46 | BYE 수신 → 통화 종료 | bye_cleanup_triggered, Pipecat 정리 |

---

## 2. 정상 동작으로 보이는 부분

- **AI 터크오버**: 무응답 10초 후 CANCEL/200 OK, Pipecat 파이프라인 기동 정상.
- **인사말**: Phase1·Phase2 순차 전송, `tts_flush_skipped_greeting_phase2` 로 Phase2 시 flush 스킵 적용.
- **STT → RAG → LLM**: 1·2차 발화 모두 TranscriptionFrame → LLM → 응답 생성 → TTS 푸시까지 완료.
- **RAG**: 1차 "오늘의 날씨를 검색합니다." 3건 검색, 2차 "기상청 가는 길" 1건 검색.
- **통화 종료**: BYE 수신 후 cleanup, 녹음 저장(mixed.wav 125초) 정상.

---

## 3. 이슈 및 권장 조치

### 3.1 [이슈] Semantic Cache API 불일치 (ChromaDBClient)

**로그**:
- `semantic_cache_check_error`: `'ChromaDBClient' object has no attribute 'search_collection'` (17:10:02.477)
- `semantic_cache_update_error`: `'ChromaDBClient' object has no attribute 'upsert_to_collection'` (17:10:15.043)

**원인**: LangGraph semantic_cache 노드는 `search_collection` / `upsert_to_collection` 를 호출하는데, 현재 ChromaDB 클라이언트(또는 RAG용 래퍼)는 `get` / `query` 만 제공함.

**영향**:
- 캐시 조회 실패 → 매 턴 캐시 미스, 응답 지연 증가.
- 캐시 저장 실패 → 동일 질의 재발 시에도 캐시 히트 불가.

**권장**: 
- semantic_cache에서 사용하는 벡터 DB 클라이언트에 `search_collection`, `upsert_to_collection` 시그니처를 추가하거나,
- 해당 노드가 사용하는 클라이언트를 현재 ChromaDB `get`/`query` 기반 API에 맞게 수정(이름 매핑 또는 어댑터 추가).

---

### 3.2 [이슈] 1차 응답 지연 (~20초)

- **STT 도달**: 17:09:55.215  
- **LLM 응답 TTS 푸시**: 17:10:15.046 (약 19.8초)

**구간별** (app.log timing_segment):
- classify_intent: 약 2.98s  
- check_cache: 약 4.19s (에러로 실패, 캐시 미사용)  
- rewrite_query: 약 4.48s  
- adaptive_rag: 0.049s  
- generate_response: 8.01s  

**구간별 동작 상세 및 소요 시간 점검**

| 구간 | 동작 내용 | 소요 시간 적절성 |
|------|-----------|------------------|
| **classify_intent** | 1) 키워드 기반 빠른 분류 시도(의도 키워드/질문 패턴). 2) 미매칭 시 **LLM 1회 호출**로 의도 분류(한 단어 응답, 최근 2턴 맥락 포함). "오늘의 날씨가 궁금합니다"는 키워드에 없어 LLM 경로 진입. | **적절**. LLM 1회 왕복(네트워크 + 토큰 생성) 기준 2~4초는 일반적. 2.98s는 정상 범위. |
| **check_cache** | 1) **임베딩 1회**: `embedder.embed_text(query)` (예: SentenceTransformer 문장 임베딩). 2) **벡터 검색**: `vector_db.search_collection("qa_cache", vector, top_k=1)`. 당시 API 불일치로 검색에서 예외 발생 → 캐시 미사용. | **과다**. 정상 시에는 임베딩 ~0.5~2초 + Chroma 검색 ~10~50ms 수준 기대. 4.19s는 임베딩(첫 호출/CPU 부담) + 예외 처리까지 포함된 값으로 보임. 캐시 복구 후에는 히트 시 수십 ms, 미스 시에도 1~2초대까지 감소 기대. |
| **rewrite_query** | 1) 5단어 미만 또는 대명사/모호 표현 포함 여부 판단. 2) 필요 시 **LLM 1회 호출**로 "구어체 → 검색용 쿼리" 변환(최근 3턴 맥락 포함). "오늘의 날씨가 궁금합니다"는 공백 기준 짧은 편이라 rewrite 경로 진입. | **적절**. LLM 1회 호출 4~5초는 classify_intent와 유사한 수준. 프롬프트/히스토리 길이에 따라 4.48s는 타당. |
| **adaptive_rag** | 1) **Vector 검색**: `rag_engine.search(rewritten_query, top_k=6)` (문장 단위 Small retrieval). 2) Small-to-Big 확장(상위 문단). 3) Contextual Compression(질문 관련 부분만 추출). LLM 호출 없음. | **적절**. 벡터 검색 + 메모리 내 확장/압축만 수행. 0.049s(49ms)는 소규모 Chroma 검색에 부합하며, 오히려 빠른 편. |
| **generate_response** | 1) RAG 결과·대화 기록·기관 정보로 시스템 프롬프트 조립. 2) **LLM 1회 호출**로 최종 답변 생성(2~3문장, 통화용). 스트리밍 시 첫 문장 완성 시점에 청크 반환. | **적절**. 가장 긴 프롬프트와 2~3문장 생성. 8초 전후는 API 지연 + 생성 시간으로 일반적. |

**요약**: classify_intent·rewrite_query·generate_response의 LLM 구간(2.98s, 4.48s, 8.01s)은 각 1회 API 호출 기준으로 적절한 수준. check_cache 4.19s는 당시 캐시 API 오류로 비정상적으로 길었을 가능성이 크며, 3.1 조치(캐시 복구) 후 재측정 권장. adaptive_rag 0.049s는 정상.

---

### 3.3 [관찰] TTS–RTP duration 불일치 (tts_rtp_duration_mismatch)

| 구간 | Notifier(음원) | RTP(큐 투입) | diff_ratio_pct |
|------|----------------|--------------|----------------|
| Phase1(인사말) | 7.396s | 5.681s | **23.2%** |
| Phase2(인사말) | 12.995s | 11.241s | **13.5%** |
| 대기 안내 TTS | 9.245s | 4.361s | **52.8%** |
| 1차 답변 TTS | 13.915s | 12.32s | **11.5%** |

- Phase1/Phase2는 약 10~23% 수준으로, sample_rate·프레임 누락 가능성 문서화된 상태와 일치.
- **대기 안내** 구간 52.8%는 해당 TTS가 짧은 문장이라 타이밍/프레임 경계 이슈가 클 수 있음. 필요 시 해당 구간만 로그 추가로 원인 추적.

---

### 3.4 [관찰] RTP 구간 공백 (rtp_tts_queue_empty_timeout)

- 인사말 종료(약 17:09:40) ~ 1차 사용자 응답 첫 TTS(17:10:02.882) 사이에 `rtp_tts_queue_empty_timeout` 다수(empty_timeouts 2→3→…→9).  
- 1차 응답 TTS 종료 ~ 2차 응답 TTS 사이에도 empty_timeouts 반복.

**해석**: LLM 처리 중에는 TTS가 없어 PCM 큐가 비는 구간이 생기는 것이 자연스러움. 사용자 체감은 “침묵”으로 느껴질 수 있으므로, 3.1 캐시 복구 및 3.2 지연 개선으로 공백 구간 단축이 도움이 됨.

---

### 3.5 [원인 확정] 호 전환(transfer) 실패 — 연락처 검색 진입 전 import 오류

- **17:11:19.291** `transfer_request_detected` (query: "네 연결해 주세요.")
- **17:11:19.291** `user_message_worker_error`: **`No module named 'src.ai_voicebot.pipecat.knowledge'`**
- **call_data_record** 상 다음 이벤트는 **17:11:46.835** `call_ended` 뿐임.

**원인**: `rag_processor`에서 호 전환 시 `from ..knowledge import ContactKnowledgeExtractor` 사용. `..knowledge`는 `pipecat.knowledge`를 가리키는데, 해당 패키지는 없고 `ContactKnowledgeExtractor`는 **`src.ai_voicebot.knowledge`**에 있음. import 실패로 연락처 검색(`search_contact`)이 실행되지 않았고, `transfer_contact_found` / `transfer_contact_not_found` / `call_transfer_initiated` 중 어느 것도 기록되지 않음.

**조치**: `rag_processor.py`에서 연락처 검색 import를 **`from src.ai_voicebot.knowledge import ContactKnowledgeExtractor`**로 수정 완료. 재현 테스트 권장.

---

### 3.6 [관찰] RTP 간격 경고 (rtp_interval_violation) — 로직 점검 요약

- 20ms 기대 간격 대비 10~31ms 등 violation 다수 (violation_count 1~450 구간).
- 인사말·이후 TTS 구간 모두 발생.

**전송이 주기적으로 되지 않는 이유 (로직 관점)**  
- **20ms 발송 루프 위치**: 실제 RTP 패킷을 20ms 간격으로 보내는 루프는 파이프라인에 주입되는 **RTP Worker** 쪽에 있음. 본 repo의 `sip-pbx/src/ai_voicebot/pipecat/rtp_transport.py`는 `send_audio_to_caller()`로 **큐에만 적재**하고, Worker 내부의 `_pipecat_outgoing_sender_loop` 같은 루프가 큐에서 꺼내 20ms 간격으로 전송한다고 주석에 명시됨.  
- **간격 이탈이 나는 흔한 이유**:  
  1. **큐가 비어 있을 때 대기** — TTS 청크가 도착하기 전까지 보낼 데이터가 없어, 다음 청크 도착 시점까지 대기 → 그 다음 패킷 간격이 20ms를 넘어감.  
  2. **TTS 청크 도착이 배치적** — 청크가 20ms 단위로 균등하게 오지 않고 한꺼번에 오면, 루프는 “한 번에 한 프레임만” 보내고 다음 20ms까지 sleep하므로, 실제 간격은 20ms 근처이지만 **기준 시각과의 정렬**이 어긋나 violation으로 찍힐 수 있음.  
  3. **이벤트 루프/스케줄링 지터** — `asyncio.sleep(0.02)` 또는 동등한 대기가 정확히 20ms가 아니면 누적되어 violation_count 증가.  
- **조치**: `rtp_interval_violation` 로그를 남기는 코드는 현재 sip-pbx Python 소스 트리에는 없고 RTP Worker(별도 모듈)에 있을 가능성이 큼. 끊김/깨짐이 없으면 참고용으로 두고, 끊김 이슈 시 3.1·3.2·TTS flush(기존 분석 문서) 우선 권장.

---

## 4. 요약

| 구분 | 내용 |
|------|------|
| **진행** | AI 터크오버, 인사말 Phase1/2, 사용자 3회 발화(STT→RAG→LLM→TTS), 호 전환 요청 감지, BYE 종료까지 전 구간 로그 상 추적 가능. |
| **필수 조치 (완료)** | **Semantic cache**용 ChromaDB: `chromadb_client._VectorDbWrapper`에 `search_collection` / `upsert_to_collection` 매핑 추가 완료. **호 전환**: `ContactKnowledgeExtractor` import를 `src.ai_voicebot.knowledge`로 수정 완료. |
| **권장** | 1차 응답 지연·공백 구간 재측정(캐시 복구 후). TTS-RTP 불일치 로그는 notifier/output 프레임 수·바이트 포함하도록 강화 완료. |

---

**로그 출처**: `logs/app.log`, `logs/call_data_record_20260314.log`
