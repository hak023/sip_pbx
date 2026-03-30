# RAG 검색 범위·유사도 임계값 가이드

- **작성일:** 2026-03-26
- **상태:** 구현 반영 (`rag_engine.py`, `factory.py`, `adaptive_rag.py`)
- **관련:** `src/ai_voicebot/ai_pipeline/rag_engine.py`, `src/ai_voicebot/factory.py`, `src/ai_voicebot/langgraph/nodes/adaptive_rag.py`

## 점수 정의

Chroma 거리 `d`에 대해 코드에서 사용하는 유사도는:

`score = 1 / (1 + d)`

- `d`가 작을수록(가깝다) `score`는 1에 가깝다.
- 임계값 `similarity_threshold`는 **이 `score` 기준**이다.

### 거리 ↔ score 대략 예시 (참고용)

| Chroma 거리 d (대략) | score | 기본 임계값 0.38 통과? | 비고 |
|---------------------|-------|------------------------|------|
| 0.2 | ~0.83 | 예 | 거의 동의어·동일 주제 |
| 0.5 | ~0.67 | 예 | 표현만 다른 FAQ |
| 0.8 | ~0.56 | 예 | 관련 있으나 문장 구성 다름 |
| 1.0 | 0.50 | 예 | 약한 연관 |
| 1.2 | ~0.45 | 예 | 주제만 겹침 |
| 1.6 | ~0.38 | 경계 | 임계값과 비슷 |
| 2.0 | ~0.33 | 단독으론 컷 | **recall backfill**로 풀 안에 있으면 top_k 채울 때 포함 가능 |

실제 `d` 분포는 임베딩 모델·청크 길이·KB 품질에 따라 달라진다.

## 어떤 질의가 “검색되기 쉬운가”

- **검색되기 쉬움:** KB 문장과 **어휘·표현이 비슷**하거나, 질문이 **짧고 핵심 키워드가 KB와 겹침** (예: “영업 시간이 언제예요?” vs KB “영업시간은 9시~18시…”).
- **검색되기 어려움:** KB에는 없는 고유명사만 있음, **STT 오인식**으로 임베딩이 엇나감, **의도별 category 필터**에 걸려 Chroma `where` 단계에서 후보 자체가 없음 (complaint/transfer 등은 일부 카테고리만 허용).

## 이번에 넓힌 동작 요약

1. **Chroma `n_results`:** `effective_top_k * 5` 이상, 최소 32 (후보 풀 확대).
2. **기본 임계값:** factory 기본 `similarity_threshold` **0.38**, `top_k` **8**.
3. **Adaptive RAG:** `SENTENCE_TOP_K` **10**, 압축 상한 **1200** 문자.
4. **Recall backfill:** 임계값을 넘는 문서만으로 `top_k`가 안 차면, 같은 Chroma 풀에서 **점수 순으로 부족분 보충** (낮은 score도 LLM에 전달 가능).
5. **0건 soft fallback:** 바닥·상위 N개 보강을 약간 완화 (상위 4개까지).

설정에서 `ai_voicebot.rag.top_k`, `ai_voicebot.rag.similarity_threshold`로 덮어쓸 수 있다.
