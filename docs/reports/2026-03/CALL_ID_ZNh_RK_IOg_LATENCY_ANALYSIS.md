# call_id `ZNh~RK-IOg` 지연 구간 분석 (LLM / RAG / TTS / STT)

- **작성일**: 2026-03-24
- **상태**: 분석 완료 (일부 구간은 로그 한계 명시)
- **근거 로그**: `sip-pbx/logs/call_data_record_20260321.log` (동일 `call_id` 행)

## 요약

| 구간 | 판단 | 비고 |
|------|------|------|
| **LLM(에이전트 전체)** | **가장 큰 병목** | `llm_exchange.agent_elapsed`가 턴별 **약 2.5s ~ 32s** |
| **RAG(벡터 검색·캐시)** | 상대적으로 짧음 | `semantic_cache_miss.elapsed_sec` **~0.02–0.16s**, `rag_search_done.search_elapsed_sec` **~0.025–0.127s** |
| **STT → LLM 진입** | **~1s 안팎** | `stt_final` → `stt_to_llm` (디바운스/큐 가능성, 순수 STT 지연과 분리 어려움) |
| **TTS 합성 지연** | **로그로 분리 불가** | `tts_text_pushed` 등에 **합성 소요 시간(ms) 필드 없음** — 재생·버퍼는 RTP 측 추적 필요 |

## 턴별 수치 (`call_data_record` 기준)

### 인사 (TTS만, LLM 없음)

| 이벤트 | 시각(로컬 ts) | 해석 |
|--------|----------------|------|
| `call_connected` | 20:06:39.842 | 착신 |
| `greeting_phase1_sent` | 20:06:40.329 | Phase1까지 **~0.49s** |
| `greeting_phase2_sent` | 20:06:45.072 | Phase1→Phase2 **~4.74s** (문구 길이·재생·파이프라인 간격 포함) |

### 턴 1 — 「내일의 날씨…」

- `stt_final` → `stt_to_llm`: **~0.99s**
- `semantic_cache_miss`: `elapsed_sec` **0.108**
- `rag_search_done`: `search_elapsed_sec` **0.127**
- `llm_exchange`: `agent_elapsed` **20.098s** ← 이 턴 지연의 대부분

### 턴 2 — 「찾아가는 길…」

- `stt_final` → `stt_to_llm`: **~0.99s**
- `semantic_cache_miss`: **0.16s**
- `rag_search_done`: `search_elapsed_sec` **0.025**
- `llm_exchange`: `agent_elapsed` **10.602s**

### 턴 3 — help (단축 경로)

- `stt_final` → `stt_to_llm`: **~0.99s**
- RAG 검색 로그 없음 (`llm_rag_context_source`: `shortcut_help`)
- `llm_exchange`: `agent_elapsed` **2.465s**

### 턴 4 — 「일반 기상 상식…」

- `stt_final` → `stt_to_llm`: **~0.99s**
- `semantic_cache_miss`: **0.024s**
- `rag_search_done`: `search_elapsed_sec` **0.03**
- `llm_exchange`: `agent_elapsed` **31.988s** ← 최장

### 턴 5 — 「네 감사합니다」(farewell 추정)

- `stt_final` 20:10:24.577 → `stt_to_llm` 20:10:25.586: **~1.01s**
- 이후 `call_ended` 20:10:36.755까지 **~11.2s** — 그래프·TTS·BYE 등이 섞여 **구간 분해는 본 로그만으로 불명확**

## 결론

1. **느린 구간**: 질문+RAG+`generate_response`를 타는 턴에서 **`agent_elapsed`(LangGraph+LLM 위주)** 가 수 초~30초대로 지배적이다. RAG 검색 자체는 밀리초~수백 ms 수준으로 보인다.
2. **STT**: 최종 텍스트 확정 후 LLM으로 넘기기까지 **약 1초** 패턴이 반복된다 (VAD/디바운스/워커 큐일 수 있음).
3. **TTS**: 현재 `call_data_record`에는 **합성 시작~완료 duration**이 없어, “TTS가 느린지”는 이 파일만으로 판단하기 어렵다.

## 로그 보완 (코드 반영)

다음 이벤트를 `call_data_record`의 `category: "timing"`으로 추가·강화했다 (재배포 후 동일 분석 시 구간 분해 가능).

| 이벤트 | 파일 | 의미 |
|--------|------|------|
| `intent_classify` | `classify_intent.py` (기존/보강) | 의도 분류 소요·경로 |
| `rewrite_query` | `rewrite_query.py` | 쿼리 재작성(스킵/LLM) `elapsed_sec`, `path` |
| `llm_generate_response` | `generate_response.py` | 실제 응답 생성 LLM 호출 구간 `elapsed_sec` |
| `agent_graph_total` | `agent.py` | `graph.ainvoke` 전체 `graph_elapsed_sec`, `total_elapsed_sec` |

추가로 TTS 합성 시간이 필요하면 `tts_started` / `tts_completed`(또는 동등 이벤트)에 **`synthesis_ms` 또는 `elapsed_sec`** 를 넣는 것을 권장한다.
