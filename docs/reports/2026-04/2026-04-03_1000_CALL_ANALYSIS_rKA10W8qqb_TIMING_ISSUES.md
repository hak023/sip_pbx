# 통화 분석 리포트: rKA10W8qqb — 프로세스 타이밍 및 이슈 점검

| 항목 | 내용 |
|------|------|
| 작성일 | 2026-04-03 10:00 |
| call_id | `rKA10W8qqb` |
| 통화 방향 | Inbound (1003 → 1004) |
| 통화 시간 | 09:24:53 ~ 09:26:55 (총 122초) |
| 상태 | 분석 완료 |
| 데이터 소스 | `logs/call_data_record_20260403.log`, `logs/app.log` |

---

## 1. 통화 타임라인 전체 흐름

```
09:24:53.680  INVITE 수신 (SIP 시그널링)
09:24:53.683  미디어 포트 할당 / RTP Relay 시작
09:25:03.993  call_connected  ← SIP 연결 완료 (INVITE→ACK = 10.31초)
09:25:04.474  greeting_phase1_sent  ("안녕하세요. KT 통화매니저...")
09:25:07.770  greeting_phase2_sent  ("저는 내일 날씨...")
09:25:33.771  stt_final [seq=1] — "날씨 정보를 휴대폰인 줄까요?"
09:25:43.649  tts_text_pushed — AI 응답 발화 시작
09:26:40.245  stt_final [seq=2] — "여보세요!"
09:26:40.258  tts_text_pushed — 인삿말 재응답
09:26:41.888  BYE 수신 (발신자 종료)
09:26:55.671  call_ended
09:26:55.865  transcript 저장 (6 messages)
09:27:01.162  call_summary 생성 완료
```

---

## 2. SIP 연결 지연 분석

| 단계 | 시각 | 소요 |
|------|------|------|
| INVITE 수신 | 09:24:53.680 | — |
| call_connected | 09:25:03.993 | **10.31초** |
| greeting_phase1_sent | 09:25:04.474 | +0.48초 |
| greeting_phase2_sent | 09:25:07.770 | +3.30초 (TTS 재생 시간) |

> **⚠️ INVITE → connected 10.31초** : SIP 착신 응답 대기 시간. B2BUA가 내부 endpoint(1004)에 INVITE를 보내고 200 OK를 받기까지 걸린 시간. 일반적으로 3~5초를 넘으면 주의 필요. 이번 통화는 정상 범위 상단으로 확인.

---

## 3. Utterance #1: "날씨 정보를 휴대폰인 줄까요?" — 처리 타이밍 상세

```
09:25:33.771  stt_final (STT 확정)
                         ↓ [+0.000s] stt_to_llm
09:25:35.360  intent_classify  +1.585s   ← ⚠️ LLM 경로 분류
09:25:39.058  semantic_cache_miss  +3.691s  ← ⚠️ 캐시 탐색
09:25:41.307  rewrite_query  +2.214s     ← ⚠️ LLM 쿼리 재작성
09:25:41.494  rag_search_done  +0.186s   ✅ RAG 벡터 검색
09:25:43.641  llm_generate_response  +2.121s  ← LLM 응답 생성
09:25:43.649  agent_graph_total  = 9.874s (전체)
09:25:43.649  tts_text_pushed   ← TTS 발화 시작
```

### agent_graph 노드별 소요 시간

| 노드 | 소요 | 비율 | 상태 |
|------|------|------|------|
| `check_cache` (semantic cache) | **3.724s** | 37.7% | 🔴 **최대 병목** |
| `rewrite_query` (LLM 쿼리 재작성) | **2.218s** | 22.5% | 🟡 느림 |
| `generate_response` (LLM 응답) | **2.124s** | 21.5% | 🟡 느림 |
| `classify_intent` (의도 분류) | **1.588s** | 16.1% | 🟡 느림 |
| `adaptive_rag` (벡터 검색) | 0.211s | 2.1% | ✅ 정상 |
| `update_cache` / `hitl_alert` 등 | ~0.006s | ~0% | ✅ 정상 |
| **합계** | **9.874s** | 100% | 🔴 **전체 응답 지연 9.9초** |

### STT → TTS 총 응답 지연

```
STT 확정 → TTS 발화 시작 = 09:33.771 → 09:43.649 = 9.878초
```

> **🔴 약 10초의 응답 지연** — 통화 AI 기준 2~3초 내 응답이 이상적. 10초는 사용자가 "여보세요?"를 다시 부를 만한 수준.

---

## 4. Utterance #2: "여보세요!" — 처리 타이밍

```
09:26:40.245  stt_final
09:26:40.245  intent_classify  +0.000s (keyword 경로)
09:26:40.258  agent_graph_total  = 0.014s
09:26:40.258  tts_text_pushed
```

| 노드 | 소요 |
|------|------|
| `classify_intent` | 0.0017s |
| `greeting_farewell_kb` | 0.0048s |
| **전체** | **0.014s** |

> ✅ **키워드 캐시 히트** (`rag_cache_hit: true`) — "여보세요" 같은 인사말은 즉시 KB에서 응답. 0.014초로 매우 빠름.

---

## 5. 주요 이슈 목록

### 🔴 이슈 1: semantic_cache_check 3.724초 — 최대 병목

- **현상**: `check_cache` 노드가 3.72초 소요. `semantic_cache_miss` 로그에서 `miss_reason: "no_search_results"` (qa_cache 컬렉션에 결과 없음)
- **원인**: ChromaDB semantic cache에서 `qa_cache` 컬렉션 검색 시 임베딩 생성 + 벡터 검색에 네트워크 또는 로컬 연산 지연 발생. 결과가 없음에도 3.7초 소요.
- **심각도**: 🔴 High — 전체 지연의 37.7% 차지

### 🟡 이슈 2: intent_classify (LLM 경로) 1.585초

- **현상**: `path: "llm_merged"` — 키워드 매칭 실패 후 LLM으로 분류. 1.585초 소요.
- 비교: Utterance #2 "여보세요"는 `path: "keyword"` → **0.0017초**
- **원인**: "날씨 정보를 휴대폰인 줄까요?"는 키워드 패턴 미매칭 → LLM API 호출 필요
- **심각도**: 🟡 Medium

### 🟡 이슈 3: rewrite_query (LLM) 2.218초

- **현상**: "날씨 정보를 휴대폰인 줄까요?" → "날씨 정보 휴대폰으로 전송"으로 재작성. LLM API 호출 2.2초.
- **원인**: 모호한 STT 텍스트("휴대폰인 줄까요?" — STT 오인식 가능성)로 인해 쿼리 재작성 필요
- **심각도**: 🟡 Medium

### 🟡 이슈 4: generate_response (LLM) 2.121초

- **현상**: RAG 컨텍스트 11개 문서 포함 LLM 응답 생성 2.1초
- **원인**: Gemini 2.5 Flash API 레이턴시. rag_hit_count=11로 컨텍스트 길이가 다소 김.
- **심각도**: 🟡 Medium (모델 특성상 정상 범위)

### 🟡 이슈 5: semantic cache miss — `no_search_results`

- `qa_cache` 컬렉션에서 결과 자체가 없음 (`raw_result_count: 0`)
- ChromaDB 검색 임계값 0.85로 매우 엄격 → 거의 모든 쿼리가 miss
- 3.7초를 소요하고도 miss가 되므로 **캐시 검색 자체의 비용 대비 효과가 낮음**

### 🟡 이슈 6: RAG 신뢰도 낮음 (confidence: 0.342)

- rank 1 문서 score: 0.3624 (임계값 0.35 겨우 초과)
- STT 오인식 "휴대폰인 줄까요?" → 실제 의도와 다른 쿼리로 검색
- soft_fallback으로 9개 문서가 recall_backfill 추가됨 (관련성 낮은 문서 다수 포함)

### ⚠️ 이슈 7: TTS UDP 큐 적체 (통화 종료 직전)

- 09:26:41 BYE 수신 후 09:26:50~51 구간에서 `tts_udp_out_queue_backlog_high` 경고 대량 발생
- queue_size: 415 → 487 (약 72패킷 누적)
- `udp_packets_sent_stat: 4822` vs `thread_packets_queued: 5309` → 송신 스레드가 실제 sendto보다 빠르게 큐에 쌓음
- 통화 종료 후 잔여 버퍼 소진 과정에서 발생 — **기능적 영향 없음** (발신자 이미 BYE)
- `total_dropped: 0`, `send_errors: 0` → 실제 패킷 손실 없음

---

## 6. 통화 품질 요약

| 항목 | 결과 | 평가 |
|------|------|------|
| 통화 연결 (INVITE→ACK) | 10.31초 | 🟡 정상 상단 |
| 인사말 출력 | phase1: 0.48s, phase2: +3.3s | ✅ 정상 |
| Utterance#1 응답 지연 | **9.878초** | 🔴 과도한 지연 |
| Utterance#2 응답 지연 | 0.014초 | ✅ 최우수 (캐시 히트) |
| STT 오인식 | "휴대폰인 줄까요?" | 🟡 불명확 발화 |
| RAG 답변 정확도 | confidence 0.342 | 🟡 낮음 |
| 패킷 드롭 | 0 | ✅ 정상 |
| 통화 요약 생성 | 성공 | ✅ 정상 |

---

## 7. 응답 지연 원인 상세 (Utterance #1 기준)

```
총 9.878초 분해:

[check_cache]       3.724s ████████████████████████ 37.7%  ← 1순위 개선 대상
[rewrite_query]     2.218s ██████████████           22.5%  ← 2순위
[generate_response] 2.124s █████████████            21.5%  ← 3순위
[classify_intent]   1.588s ██████████               16.1%  ← 4순위
[adaptive_rag]      0.211s █                         2.1%  ← 정상
[기타]              0.008s                           0.1%
```

---

## 8. 개선 제안

### 즉시 적용 가능

| 우선순위 | 항목 | 예상 절감 |
|---------|------|----------|
| **1** | **semantic cache 검색에 타임아웃 추가** (현재 무제한 대기) | ~2~3s |
| **2** | **cache miss 시 임베딩 생성 병렬화** — intent_classify와 동시 실행 | ~1.5s |
| **3** | **의도 분류 키워드 패턴 확장** — "날씨", "휴대폰" 등 자주 나오는 질문 패턴 추가 | ~1.5s |

### 중기 개선

| 우선순위 | 항목 | 예상 절감 |
|---------|------|----------|
| **4** | **semantic cache 임계값 완화** (0.85 → 0.75) — 캐시 히트율 향상으로 check_cache 비용 회수 | cache hit 시 ~7s |
| **5** | **rewrite_query 병렬화** — rag 검색과 동시 실행 가능 여부 검토 | ~2s |
| **6** | **RAG 컨텍스트 수 제한** — recall_backfill 상한 설정 (현재 9개 추가) | ~0.5s |

### 최적 시나리오 (모두 적용 시)

```
예상 응답 지연: 9.878s → 3~4s 수준으로 개선 가능
```

---

## 9. STT 오인식 가능성

- 사용자 발화: "날씨 정보를 **휴대폰인 줄까요**?"
- 실제 의도 추정: "날씨 정보를 **휴대폰으로** 줄까요?" (SMS 수신 문의)
- STT `latest_long` 모델로 변경 후 재테스트 시 개선 여지 있음 (현재 통화는 아직 telephony 모델 사용)
