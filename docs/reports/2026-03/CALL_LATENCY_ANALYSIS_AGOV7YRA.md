# 통화 지연 분석: call_id `aG~Ov-7yra` (AI 봇 응대·LLM 구간)

| 항목 | 내용 |
|------|------|
| 작성일 | 2026-03-26 |
| 상태 | 분석 완료 |
| 데이터 소스 | `sip-pbx/logs/call_data_record_20260325.log` |
| 관련 코드 | `langgraph/agent.py`, `nodes/classify_intent.py`, `nodes/step_back_prompt.py`, `nodes/semantic_cache.py` |

> 파일명에서 `AGOV7YRA`는 `aG~Ov-7yra`의 특수문자·물결표를 제거한 식별용 표기이다.

---

## 1. 요약

본 통화는 **약 4분 55초**(01:53:53 연결 ~ 01:58:49 종료) 동안 **다수 턴**이 오갔다. 느린 응대는 한 가지 원인이 아니라 **(1) LLM 의도 분류**, **(2) 시맨틱 캐시(임베딩+검색) 장시간 구간**, **(3) RAG 저신뢰로 인한 Step-back까지 포함한 풀 LLM 파이프라인**이 턴마다 겹치거나 연속으로 발생한 결과다.

**특히 주목할 점**

- **`intent_classify`의 `path: "llm"`** 인 턴에서 분류만 **약 2.5~9.6초** 소요된 사례가 반복된다. 이후 `clarification` 등은 **템플릿 단축 응답**이라 그래프 나머지는 ms 단위이나, **사용자가 체감하는 대기는 거의 전부 “의도 LLM”**이다.
- **`semantic_cache_miss`에서 `elapsed_sec: 6.032`** 구간이 한 번 기록되어, **LLM이 아닌 임베딩·벡터 검색**도 병목이 될 수 있음을 보여 준다.
- **`transfer` / `question` 풀 파이프라인**에서 **rewrite_query(~9~10s) + step_back(~6~11s) + generate_response(~9~12s)** 가 연속되며 **에이전트 총 **약 29.7s / 36.4s**가 측정되었다.
- **`call_ended`(01:58:49.119) 이후**에도 「일단은?」에 대한 **`intent_classify`·`rewrite_query`·`llm_generate_response`·`tts_text_pushed`가 01:59:17까지 이어짐** — 통화 종료 후에도 파이프라인이 완료되어, 리소스·로그상 혼선 및 “끊은 뒤에도 처리됨” 이슈로 이어질 수 있다.

---

## 2. 턴별 지연 하이라이트 (CDR)

### 2.1 빠른 턴 (참고)

| 구간 | 의도 경로 | `agent_graph_total` | 비고 |
|------|-----------|---------------------:|------|
| 병합 인사 후 응답 | `keyword` → `affirm` → template | **0.008s** | 템플릿 단축 |
| 다수 `affirm` 키워드 매칭 | `keyword` | **0.004~0.038s** | RAG/LLM 생성 없음 |

### 2.2 느린 턴 — 의도 분류가 LLM인 경우

`timing.intent_classify`의 **`path: "llm"`** 이 곧 **외부 LLM 호출 기반 분류**로 해석할 수 있다.

| 대략 시각 | 사용자 발화(요약) | `intent_classify` (s) | 최종 intent | `agent_total` (s) | 비고 |
|-----------|-------------------|----------------------:|-------------|------------------:|------|
| 01:54:28→46 | 하고. 어때요? → 긴 병합 | **6.35** | clarification | **6.358** | `classify_intent` 노드 ~6.35s, 응답은 단축 멘트 |
| 01:54:47→59 | SM 번호 긴 설명 | 0 (keyword) | affirm | 0.023 | 키워드 오매칭 가능성 (내용은 기술 설명) |
| 01:55:25→30 | IMG/SM 긴 설명 | **5.23** | clarification | **5.234** | 동일 패턴 |
| 01:55:45→51 | 70499 동일 질문 | **5.97** | clarification | **5.979** | 실질적 질문인데 clarification |
| 01:55:56→03 | 애플은 당연히. 똑같고. | **6.07** | affirm | **6.079** | 짧은 발화인데 LLM 분류 |
| 01:56:08→12 | 당연히 된 거지. | **3.45** | affirm | **3.451** | |
| 01:56:41→51 | 보내고 그 다음에. | **9.56** | clarification | **9.573** | **최장 분류 구간 중 하나** |
| 01:58:40→50 | 일단은? (통화 종료 후 로그 지속) | **9.24** | question | **36.443** (전체 그래프) | 아래 2.4 |

**정리**: `shortcut_clarification` / `shortcut_template_b_group` 응답은 가볍지만, **그 전 단계 LLM 분류가 3~9초대**이면 통화 품질은 “봇이 느리다”로 인식되기 쉽다.

### 2.3 시맨틱 캐시(비 LLM) 병목 사례

| 시각 | 이벤트 | `elapsed_sec` | 내용 |
|------|--------|---------------:|------|
| 01:54:37.530 | `semantic_cache_miss` | **6.032** | 질의 「하고. 어때요?」, `intent: question`, `raw_result_count: 0` |

`check_cache` 경로에서 **임베딩 + `qa_cache` 검색**이 **약 6초**까지 늘어난 사례로, “LLM만 느리다”가 아니라 **벡터/임베딩 지연**도 함께 점검해야 한다.

### 2.4 풀 RAG + 연쇄 LLM (최대 병목)

**A) `transfer` 턴** (01:57:40 `stt_to_llm` → 01:58:10 `tts`)

| 단계 (CDR) | 소요(초) | 설명 |
|------------|----------:|------|
| `rewrite_query` | **9.48** | LLM 질의 재작성 |
| RAG `confidence` | 0.126 | 0.4 미만 → Step-back 분기 |
| `step_back` (노드 집계) | **~11.03** | LLM + 재검색 등 |
| `llm_generate_response` | **9.063** | 최종 답변 생성 |
| **`agent_graph_total`** | **29.685** | 합계 |

**B) `question` 「일단은?」** (통화 종료 뒤 로그에 완료)

| 단계 (노드 집계) | 소요(초) |
|------------------|----------:|
| `classify_intent` | **9.246** |
| `rewrite_query` | **9.112** |
| `step_back` | **6.387** |
| `generate_response` | **11.567** |
| **`agent_graph_total`** | **36.443** |

짧은 발화 「일단은?」이 **일반 질문으로 분류**되며, 재작성 결과가 기상청 지식과 무관한 문장으로 흐르고, RAG 신뢰도가 낮아 **Step-back + 장문 생성**까지 가며 **총 30초대 후반**이 소요되었다.

---

## 3. 원인 정리 (LLM 관점 + 주변 시스템)

1. **의도 분류 LLM (`path: llm`)**  
   키워드·룰에 걸리지 않을 때마다 **수 초대 API 왕복**이 누적된다. `clarification`·`affirm`·`question` 모두에서 발생.

2. **질문이 `clarification`으로 잦은 분류**  
   실제 사용자 질문(예: 70499 동일 여부)이 **clarification + 고정 클리핑 멘트**로 처리되어 **도움이 되지 않는 응답**과 **불필요한 분류 비용**이 동시에 발생할 수 있다.

3. **키워드 `affirm` 과매칭**  
   긴 기술 설명에도 `keyword` → `affirm` → 템플릿이 적용된 턴이 있어, **지연은 줄지만 품질·신뢰는 떨어지는** 트레이드오프가 보인다.

4. **RAG confidence < 0.4 → Step-back**  
   기상청 도메인과 무관한 질의에서 히트 점수가 구조적으로 낮아 **rewrite + step_back + generate**가 연쇄한다.

5. **시맨틱 캐시 6초대**  
   LLM 외 병목으로 기록되었으므로 **임베딩 공급자·Chroma·네트워크** 점검이 필요하다.

6. **통화 종료 후 그래프 완료**  
   파이프라인 취소/짧은 회로가 없으면 **끊은 뒤에도 30초 가까운 처리**가 이어질 수 있다.

---

## 4. 개선 포인트 (우선순위)

### P0 — 의도 분류 가속·캐싱

- 동일 통화 내 **유사 발화 해시 / 최근 intent 캐시**로 **연속 LLM 분류** 완화.
- **짧은 발화(예: N글자 이하)** 는 LLM 대신 **휴리스틱·규칙·한 번의 초경량 분류**로 우선 처리.
- **질문 신호**(물음표, “뭐야/어디/왜/어떻게” 등)가 강하면 `question` 우선 검토해 **clarification 오분류** 감소.

### P0 — 도메인 밖·모호 발화의 파이프라인 단축

- `rewrite_query` **스킵 조건** 확대: 짧은/불완전 발화는 원문 RAG 또는 **즉시 상담원 연결 안내** 템플릿.
- **Step-back 비활성화 또는 완화**: `question`이면서 질의 길이·신뢰도 패턴이 “오탐”에 가깝면 step_back 생략.

### P0 — 통화 종료 시 인플라이트 작업 취소

- `call_ended` 시 해당 `call_id`의 **LangGraph/Pipecat LLM 태스크 취소**로 불필요한 비용·로그·혼선 방지.

### P1 — 시맨틱 캐시 지연

- `check_cache` 경로에 **임베딩 단계 / 검색 단계** 분리 로깅(이미 디버깅 규칙 방향과 일치).
- `qa_cache` 비어 있음(`raw_result_count: 0`)이 반복되면 **초기 시딩** 또는 임계·필터 재검토.

### P1 — `transfer` 키워드 확정 시 경량 응답

- 키워드로 `transfer`가 이미 잡힌 경우 **rewrite/step_back 생략**하고 정책 멘트 + HITL만 수행하는 분기 검토 (이미 일부 턴에서 `rewrite_query` skip이 있음 — 병합 후 긴 문장에서는 풀 파이프라인으로 빠진 사례가 있음).

### P2 — 모델·SLO

- 의도 분류 전용 **더 작은 지연 모델** 또는 **타임아웃 후 키워드 폴백**.
- `generate_response` **max_tokens**·스트리밍 정책으로 체감 지연 완화.

---

## 5. 부록: 본 통화와 도메인 정합성

대화 내용은 **딜리버리/SM 번호/레포트** 등 **기상청 FAQ 범위를 벗어난 기술 협의**에 가깝다. 이 경우 **빠른 상담원 연결 고지**가 사용자 가치에 더 맞을 수 있으며, 그를 위해서는 위 **파이프라인 단축 + 조기 transfer**가 특히 유효하다.

---

## 6. 부록: 현재 LLM·모델 변경으로 지연 줄이기 / LLM 외 지연

### 6.1 현재 사용 중인 LLM (확인 근거)

- **스택**: **Google Gemini** (`google.generativeai`), `LLMClient` (`sip-pbx/src/ai_voicebot/ai_pipeline/llm_client.py`).
- **설정 위치**: `ai_voicebot.google_cloud.gemini` (일반적으로 `config.yaml` 하위). 팩토리에서 `google_config.get("gemini", {})`를 그대로 `LLMClient`에 전달 (`factory.py`).
- **코드 기본값**: 설정에 `model`이 없으면 **`gemini-pro`** (`llm_client.py`의 `config.get("model", "gemini-pro")`).
- **해당 환경(로그 기준)**: `sip-pbx/logs/app.log`에 **`LLMClient initialized`, `model`: `gemini-2.5-flash`**, `temperature`: **0.5**로 기록됨 → **실제 런타임은 `gemini-2.5-flash`**로 동작한 것으로 보면 된다.

지식 추출 등 별도 경로(`sip_endpoint.py`)에서도 gemini 설정 읽을 때 기본 모델 문자열이 **`gemini-2.5-flash`**로 잡혀 있음.

### 6.2 모델·파라미터 변경으로 LLM 시간을 줄이는 방법

1. **더 가벼운 Flash / Flash-Lite 계열로 교체**  
   - 동일 파이프라인에서 **Pro 계열은 지연·비용이 커지기 쉬우므로** 음성 봇 기본값으로는 비권장.  
   - Google이 내놓는 **최신 Flash-Lite(저지연·고처리량용)** 는 공식 문서의 **모델 ID**를 확인한 뒤 `gemini.model`에 설정 ([Gemini API Models](https://ai.google.dev/gemini-api/docs/models)).  
   - **주의**: 모델 문자열은 시기별로 추가/폐기되므로, 반드시 **현재 API에서 노출되는 ID**와 **한국어 품질**을 소규모로 검증할 것.

2. **`max_output_tokens` / `max_tokens` 축소**  
   - 의도 분류·질의 재작성·Step-back 등 **짧은 JSON/한 문장**이면 출력 상한을 낮춰 **생성 구간**을 줄일 수 있음 (`llm_client.py`가 `max_output_tokens` 사용).

3. **온도·샘플링**  
   - 이미 **0.5**면 비교적 보수적. 분류 전용 호출은 **더 낮은 temperature**로 속도·결정성을 약간 얻을 수 있으나, 체감은 **출력 토큰 수·모델 종류**보다 작은 경우가 많음.

4. **아키텍처 측면 (모델만 바꿔도 한계가 있는 이유)**  
   - 본 통화 분석에서처럼 **한 턴에 LLM이 여러 번**(의도 분류 + rewrite + step_back + generate) 호출되면, **모델을 반으로 빠르게 해도 합산은 여전히 크다**.  
   - 효과가 큰 순서는 보통 **호출 횟수 감소(경로 단축) > 더 빠른 모델 > 출력 토큰 축소**이다.

### 6.3 LLM 시간을 제외한 지연 구간 (있음)

본 CDR·이전 분석에서 **LLM이 아닌** 또는 **LLM과 별도**로 잡히는 구간 예시:

| 구간 | 설명 |
|------|------|
| **STT** | `stt_final` ~ `stt_to_llm` 간격, 발화 끝·턴 병합(`stt_turn_superseded`) 대기 등 **사용자/오디오 쪽 시간**. |
| **시맨틱 캐시 (`qa_cache`)** | `semantic_cache_miss` 등에서 **`elapsed_sec` 수 초**(예: **~6s**) — **임베딩 API + 벡터 검색**. |
| **적응형 RAG** | `adaptive_rag`, `rag_search_done`의 Chroma/검색 — 보통 **수백 ms~1s대**이나 데이터량·호스트에 따라 증가 가능. |
| **TTS** | `tts_text_pushed` 이후 실제 음성 합성·전송 파이프라인. |
| **인사 TTS** | 연결 직후 `greeting_phase1` / `phase2` 순차 재생 구간(체감 “봇이 말하기 시작하기까지”). |
| **통화 종료 후 잔여 처리** | `call_ended` 이후에도 그래프가 끝까지 도는 경우 **불필요한 리소스 사용**(사용자 청각에는 없지만 서버·비용·로그 지연으로 이어짐). |

정리하면, **“LLM이 느리다”는 관측은 맞지만**, 동일 통화에서 **임베딩+캐시 검색 ~6초**, **STT/턴 정책**, **RAG I/O**도 **합산 체감**에 기여할 수 있다.

---

*월별 리포트 규칙에 따라 `sip-pbx/docs/reports/2026-03/` 에 보관한다.*
