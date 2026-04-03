# Call Analysis: YOZBfV2s1y — 응대 타이밍 및 RAG 미응답 분석

| 항목 | 내용 |
|---|---|
| 작성일 | 2026-04-03 18:30 |
| 상태 | 분석 완료 |
| call_id | YOZBfV2s1y |
| callee | 1004 (기상청) |
| 통화 시간 | 11:43:41 ~ 11:46:02 (약 2분 21초) |
| 총 seq | 3 |

---

## 1. 전체 타임라인

```
11:43:41.700  call_connected
11:43:42.226  TTS phase1 전송 시작 (안녕하세요...)
11:43:43.381  TTS 첫 RTP 발송 [greeting TTF: 1.68s]
11:43:45.808  TTS phase2 전송 완료 (인사 전체 완료: 3.58s)

11:44:13.367  [SEQ 1] STT final: "방금 질이 났는데 이거 뭐예요?"
              → classify: chitchat (0.020s, persona_chitchat)
11:44:29.360  [SEQ 1] TTS push  → 응답지연: 15.991s ⚠️ 위험

11:44:39.089  [SEQ 2] STT final: "방금 지진이 일어났는데 혹시 이거 뭘까요?"
              → classify: chitchat (0.073s, persona_chitchat)
11:44:53.339  [SEQ 2] TTS push  → 응답지연: 14.240s ⚠️ 위험

11:45:11.106  [SEQ 3] STT final: "방금 지진이 일어났는데 지진 정보에 대해서 알려주세요."
              → classify: question (0.002s, keyword_strong_question)
              → check_cache: miss (0.069s)
              → adaptive_rag: 5건 반환 (0.069s) ← RAG 히트
11:45:21.986  [SEQ 3] TTS push  → 응답지연: 10.862s ⚠️ 위험
11:46:02.401  call_ended
```

---

## 2. Seq별 소요 시간 상세

### Seq 1 — "방금 질이 났는데 이거 뭐예요?" (chitchat)

| 노드 | 소요 시간 | 판정 |
|---|---|---|
| classify_intent | 0.020s | ✅ 정상 |
| generate_response | **15.891s** | 🔴 심각 |
| update_cache | 0.074s | ✅ 정상 |
| **agent_graph_total** | **15.991s** | 🔴 심각 |

- `rag_hit_count: 0` → RAG 없이 LLM 단독 생성
- `path: persona_chitchat` → 페르소나 chitchat 경로
- generate_response **15.9초** 전부 LLM 대기

### Seq 2 — "방금 지진이 일어났는데 혹시 이거 뭘까요?" (chitchat)

| 노드 | 소요 시간 | 판정 |
|---|---|---|
| classify_intent | 0.073s | ✅ 정상 |
| generate_response | **14.086s** | 🔴 심각 |
| update_cache | 0.074s | ✅ 정상 |
| **agent_graph_total** | **14.240s** | 🔴 심각 |

- Seq 1과 동일 패턴, 약간 개선됐으나 여전히 14초 이상

### Seq 3 — "방금 지진이 일어났는데 지진 정보에 대해서 알려주세요." (question)

| 노드 | 소요 시간 | 판정 |
|---|---|---|
| classify_intent | 0.002s | ✅ 정상 (keyword 직결) |
| rewrite_query | 0.001s | ✅ skip |
| check_cache | 0.069s | ✅ 정상 |
| adaptive_rag | 0.069s | ✅ 정상 |
| generate_response | **10.718s** | 🔴 심각 |
| update_cache | 0.001s | ✅ 정상 |
| **agent_graph_total** | **10.862s** | 🔴 심각 |

- RAG 5건 전달됐음에도 LLM이 10.7초 소요
- RAG 1위 문서 (score 0.3355): `"방금 지진이 있었는데, 지진 정보와 규모를 알 수 있을까요?"` 정확 매칭
- 그러나 **최종 응답: "지진 정보는 드리기 어렵습니다"** → RAG 무시 (별도 분석 이슈)

---

## 3. 핵심 문제: generate_response LLM 지연 (10~16초)

### 3-1. Gemini thinking 미적용 의심

thinking 비활성화(`thinking_budget=0`) 패치가 적용됐음에도 10~16초가 발생하고 있다.
이는 **chitchat 경로와 question 경로 모두에서** 발생하며, RAG 유무와 무관하게 LLM 자체가 느린 상태.

가능한 원인:
- SDK가 `ThinkingConfig`를 지원하지 않아 `_thinking_off()` 리턴이 `None` → 내부에서 기본 thinking 적용
- Gemini API 서버 측 부하 (외부 원인)
- 프롬프트 길이 과다: `messages`(대화 히스토리) + `org_context` + `rag_context` 누적

### 3-2. chitchat 경로에서 LLM 호출 (15~16초)

chitchat 의도임에도 LLM을 full 호출하고 있다.
`_chitchat_template` 체크가 있지만 페르소나 템플릿이 설정되지 않으면 LLM으로 폴백.

```
"path": "persona_chitchat"  → 페르소나 분기 chitchat
"rag_hit_count": 0          → RAG 없음
"response_len": 80~89       → 짧은 응답임에도 15초 소요
```

chitchat에 대해 LLM 응답 자체를 줄이거나, 고정 템플릿으로 처리하면 절감 가능.

---

## 4. RAG 관련 문제 (Seq 3)

### 4-1. Strict threshold 미달로 soft_fallback 적용

```
similarity_threshold_config: 0.35  (strict 기준)
top1 score: 0.3355  → 0.35 기준에서 0.005 미달
→ soft_fallback(soft_floor=0.175) 적용
→ rank 2~5 문서: score 0.12~0.16 (저품질 노이즈)
→ greeting_phase2 카테고리 문서도 컨텍스트에 포함됨
```

### 4-2. LLM이 RAG 컨텍스트 무시

RAG 1위 문서: `"기상청에서 공식 통보된 지진의 규모와 진앙지를 신속하게 안내해 드릴 수 있습니다."`
→ 지진 정보 안내 가능함이 명확히 기재

그러나 LLM 최종 응답: `"지진에 대한 자세한 정보는 드리기 어렵습니다."`

복합 원인:
1. **대화 히스토리 오염**: seq 1, 2에서 AI가 이미 "지진은 안내 못 한다"는 응답 2회 발신 → LLM이 같은 패턴 추종
2. **저품질 컨텍스트 노이즈**: rank 2~5 문서들이 지진과 무관한 내용 (날씨, 특보, 인사말) → 1위 문서의 신뢰도 희석
3. **시스템 프롬프트 응답 규칙 2번**: "검색된 참고 정보가 있으면 최대한 활용해서 답하세요"가 히스토리 영향에 의해 무력화

### 4-3. Seq 1, 2 오분류의 연쇄 영향

```
seq 1: "방금 질이 났는데 이거 뭐예요?" → chitchat (오분류)
         ↓ AI 응답: "날씨/기상특보만 안내 가능"
seq 2: "방금 지진이 일어났는데 혹시 이거 뭘까요?" → chitchat (오분류)
         ↓ AI 응답: "날씨/기상특보만 안내 가능" (반복)
seq 3: "방금 지진이 일어났는데 지진 정보에 대해서 알려주세요." → question (정분류)
         ↓ RAG 히트 → 그러나 히스토리에 "못 한다" 2회 → LLM이 같은 방향으로 응답
```

seq 1의 "질이 났는데" (STT 오인식: 지진 → 질)가 chitchat 오분류의 직접 원인.
seq 2는 "혹시 이거 뭘까요?" 라는 구어체 표현이 질문보다 잡담처럼 분류됨.

---

## 5. 개선 포인트 정리

### [P1] LLM generate_response 지연 단축 — 최우선

| 방안 | 기대 효과 | 복잡도 |
|---|---|---|
| `ThinkingConfig` 실제 적용 여부 로그 추가 | 원인 확인 | 낮음 |
| chitchat 고정 응답 템플릿 확대 | 15s → 0.1s | 중간 |
| LLM 프롬프트 토큰 수 축소 (히스토리 트리밍) | 10~20% 단축 | 중간 |
| `max_output_tokens` 줄이기 (chitchat 경로) | 응답 속도 향상 | 낮음 |

### [P2] RAG strict threshold 조정

```python
# 현재
SIMILARITY_THRESHOLD = 0.35

# 제안
SIMILARITY_THRESHOLD = 0.30   # 0.005 미달로 soft_fallback 발동하는 케이스 방지
```

기대 효과:
- rank 1 문서 strict 통과 → soft_fallback 불필요 → 노이즈 문서 자동 제거
- 지진 정보 문서가 단독으로 LLM에 전달 → 올바른 응답 유도

### [P3] greeting_phase2 카테고리 RAG 컨텍스트 제외

```python
# adaptive_rag.py 또는 generate_response.py
RAG_EXCLUDED_CATEGORIES = {"greeting_phase2", "greeting_phase1"}
```

인사말 문서가 질문 응답 컨텍스트에 포함되면 LLM 혼란 유발.

### [P4] 대화 히스토리 오염 방지

```python
# generate_response.py: 히스토리 내 AI 응답이 fallback 멘트인 경우 제거
# → "죄송합니다. 해당 내용은..." 류의 fallback 히스토리를 다음 LLM 프롬프트에서 제외
```

히스토리에 fallback 응답이 누적되면 LLM이 같은 방향으로 응답을 고수하는 경향.

### [P5] STT 오인식 보정 (chitchat 오분류 근본 원인)

```
"방금 질이 났는데"  →  실제 발화: "방금 지진이 났는데"
```

STT 오인식으로 `질`이 `지진`으로 인식되지 않아 chitchat 분류.
`latest_long` 모델에서도 이 오인식이 발생 — STT 후처리 사전 보정(지진/지역/자연재해 단어 보정)을 검토할 수 있으나 우선순위 낮음.

---

## 6. 우선순위별 개선 로드맵

| 순위 | 작업 | 예상 효과 | 파일 |
|---|---|---|---|
| 1 | `ThinkingConfig` 실제 적용 여부 디버그 로그 추가 | LLM 지연 원인 확인 | `llm_client.py` |
| 2 | RAG strict threshold 0.35 → 0.30 | 지진 문서 strict 통과 | `adaptive_rag.py` 또는 `config.yaml` |
| 3 | `greeting_phase2` RAG 컨텍스트 제외 | LLM 노이즈 제거 | `generate_response.py` |
| 4 | chitchat LLM 프롬프트 `max_output_tokens` 축소 | 응답 속도 개선 | `llm_client.py` |
| 5 | RAG 1위 문서 강조 프롬프트 추가 | RAG 활용률 개선 | `generate_response.py` |
| 6 | 히스토리 fallback 멘트 필터링 | 오응답 연쇄 방지 | `generate_response.py` |
