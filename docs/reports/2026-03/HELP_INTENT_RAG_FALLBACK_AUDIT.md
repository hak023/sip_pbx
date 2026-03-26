# intent=help 가 DEFAULT 멘트로 떨어지던 원인 점검

- **작성일**: 2026-03-24
- **관련 로그**: `llm_rag_context_source=help_intent_rag_llm_fallback`, `confidence=0.45`, RAG 2건·유사도 ~0.19

## 원인

1. **RAG**: `similarity_threshold`(예: 0.7) 하드 컷으로 대부분 탈락 → soft fallback으로 **2건만** 전달. “도와줄 수 있나요” 류 질의는 임베딩 유사도가 낮아 흔함.
2. **LLM**: Gemini 등이 JSON 배열 외 텍스트를 섞거나 마크다운을 쓰면 `_parse_help_items_from_llm`이 빈 리스트 → **즉시 `DEFAULT_HELP_MESSAGE`** (`help_intent_rag_llm_fallback`).

## 조치

### `rag_engine.py`

- `intent`가 **`help`**(search_intent 동일)일 때:
  - Chroma `n_results`를 **`max(80, top_k*4)`** 로 확대.
  - **`similarity_threshold` 컷을 적용하지 않고**, score 내림차순 상위 `effective_top_k`만 반환.
  - trace에 `rag_search_help_intent_rank_only` 로그.

### `response_shortcuts.py` (help_response_node)

- LLM 프롬프트에 **한 줄 JSON만** 강조, `max_tokens`/타임아웃 소폭 상향.
- JSON 파싱: 전체 배열·부분 배열·**불릿/번호 줄** 폴백 (`_parse_help_items_line_fallback`).
- LLM 파싱 실패 시 **`_help_items_from_documents`**: `display_name`(capability), contact+department, `category` 라벨 맵, 본문 첫 문장 등으로 최대 5개 구성 → `help_intent_rag_heuristic`.
- 파싱 실패 시 `help_response_llm_parse_empty`에 **`llm_raw_preview`** 로그.

## 기대 동작

- RAG 히트가 많아지고, LLM이 깨져도 **휴리스틱으로** `저는 … 할 수 있어요` 형태 응답 가능.
- 완전 실패 시에만 기존과 같이 `DEFAULT_HELP_MESSAGE`.
