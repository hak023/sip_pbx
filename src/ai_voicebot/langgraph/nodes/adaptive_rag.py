"""
Adaptive RAG 노드.

Small-to-Big Retrieval + Contextual Compression:
  1. Sentence-level 검색 (빠른 유사도 매칭)
  2. Parent Document(Paragraph) 확장 → LLM에 풍부한 맥락 전달
  3. Contextual Compression: 질문 관련 부분만 추출
"""

import structlog
from typing import Dict, List
from src.ai_voicebot.langgraph.state import ConversationState
from src.common.call_data_record_logger import log_call_data
from src.common.rag_hit_serializer import build_rag_hits_llm_context, build_rag_hits_retrieval
from src.common.sip_owner import normalize_owner_username

logger = structlog.get_logger(__name__)


def _is_assistant_message(msg: Dict) -> bool:
    r = (msg.get("role") or "").strip().lower()
    return r in ("assistant", "ai", "착신자")


def _merge_dialog_context_for_rag(state: ConversationState, base_query: str) -> str:
    """
    RAG 검색 쿼리만 선별적으로 보강한다 (LLM 프롬프트의 대화 history와 분리).

    - 직전 히스토리가 AI(assistant) 응답으로 끝남 → 이전 턴은 이미 응답이 나간 상태이므로
      **이전 사용자 발화를 검색어에 붙이지 않는다** (짧은 현재 발화만으로 검색).
    - 히스토리가 사용자 발화로 끝남 → STT 분할 등 **연속 사용자 발화** 가능성.
      이 때만 짧은 조각/접속 패턴이면 **마지막 user 메시지**를 접두로 붙인다.

    문맥 전체는 generate_response_node가 HISTORY_MAX_TURNS 대화 기록으로 LLM에 주입한다.
    """
    q = (base_query or "").strip()
    if not q:
        return q

    messages: List[Dict] = list(state.get("messages") or [])
    if not messages:
        return q

    last = messages[-1]
    if _is_assistant_message(last):
        logger.debug(
            "adaptive_rag_query_context_merge_skipped",
            call_id=state.get("_call_id") or "",
            query_preview=q,
            note="직전 메시지가 AI 응답 → RAG 검색어에 이전 사용자 발화 미병합",
        )
        return q

    if (last.get("role") or "").strip() != "user":
        return q

    prev_user = (last.get("content") or "").strip()
    if not prev_user or prev_user == q:
        return q

    words = q.split()
    needs_context = (
        len(words) < 7
        or q.startswith("때 ")
        or q.startswith("그래서 ")
        or q.startswith("거기 ")
        or ("어떻게" in q and len(q) < 24)
    )
    if not needs_context:
        return q

    merged = f"{prev_user} {q}".strip()[:450]
    if merged != q:
        logger.info(
            "adaptive_rag_query_context_merged",
            call_id=state.get("_call_id") or "",
            query_preview=q,
            merged_preview=merged,
            note="연속 사용자 발화 가정: RAG 검색어에 직전 user 턴 접두 병합",
        )
    return merged


# 검색 파라미터
SENTENCE_TOP_K = 6      # 문장 레벨 검색 수
PARENT_EXPAND_LINES = 5  # 상위 문맥 확장 줄 수
COMPRESSION_MAX_CHARS = 800  # 압축 후 최대 문자 수


async def adaptive_rag_node(state: ConversationState) -> dict:
    """
    Adaptive RAG 검색 수행.
    
    1. rewritten_query로 VectorDB 검색
    2. Small-to-Big: 검색 결과의 parent 문서로 확장
    3. Contextual Compression: 질문과 관련된 핵심만 추출
    4. confidence 점수 산출
    """
    import time
    _start = time.time()

    base_q = state.get("rewritten_query") or state.get("user_query", "")
    query = _merge_dialog_context_for_rag(state, base_q)
    rag_engine = state.get("_rag_engine")
    owner = state.get("_owner")  # 착신번호 기반 테넌트 격리
    call_id = state.get("_call_id") or ""
    intent = state.get("intent")  # intent별 category 필터 (CHROMADB_CATEGORY_DESIGN)

    if not rag_engine or not query:
        elapsed = time.time() - _start
        logger.info("timing_segment", segment="adaptive_rag", elapsed_sec=round(elapsed, 3), skip=True)
        return {"rag_results": [], "confidence": 0.0, "rag_search_trace": {}}

    try:
        # 1단계: Small (Sentence) Retrieval (owner + intent→category 필터)
        search_start = time.time()
        search_out = await rag_engine.search(
            query,
            owner_filter=owner,
            call_id=call_id or None,
            top_k_override=SENTENCE_TOP_K,
            intent=intent,
        )
        search_results = search_out.documents
        rag_search_trace = getattr(search_out, "trace", None) or {}
        search_elapsed = time.time() - search_start

        if not search_results:
            elapsed = time.time() - _start
            owner_norm = normalize_owner_username(owner or "")
            logger.info("timing_segment", segment="adaptive_rag", elapsed_sec=round(elapsed, 3), path="no_results")
            logger.info("adaptive_rag_no_results",
                        call=True,
                        call_id=call_id,
                        progress="rag",
                        category="rag",
                        query=query,
                        query_len=len(query),
                        search_elapsed=f"{search_elapsed:.3f}s",
                        total_elapsed=f"{elapsed:.3f}s",
                        note="Vector 검색 결과 없음")
            logger.info(
                "adaptive_rag_empty_debug",
                call_id=call_id or "",
                owner_state=owner or "",
                owner_normalized=owner_norm,
                intent=intent or "",
                note="Chroma metadata.owner·의도별 category 필터·임계값 점검",
            )
            log_call_data(
                call_id or "",
                "rag",
                "rag_search_done",
                query=query,
                result_count=0,
                owner_filter=owner,
                confidence=0.0,
                search_elapsed_sec=round(search_elapsed, 3),
                rag_hits_retrieval=[],
                rag_hits_llm_context=[],
                rag_search_trace=rag_search_trace,
            )
            return {"rag_results": [], "confidence": 0.0, "rag_search_trace": rag_search_trace}

        # 2단계: Small-to-Big Expansion
        expanded_docs = _expand_to_parent(search_results)

        # 3단계: Contextual Compression
        compressed = _contextual_compress(expanded_docs, query)

        # 4단계: Confidence 산출
        scores = [
            doc.score if hasattr(doc, "score") else doc.get("score", 0)
            for doc in search_results
        ]
        scores = [s for s in scores if s and s > 0]
        avg_score = sum(scores) / len(scores) if scores else 0.0
        confidence = min(1.0, avg_score * 1.1)

        elapsed = time.time() - _start
        logger.info("timing_segment", segment="adaptive_rag", elapsed_sec=round(elapsed, 3), search_elapsed_sec=round(search_elapsed, 3))
        top_doc_preview = ""
        if compressed:
            first_text = compressed[0].get("text", "") if isinstance(compressed[0], dict) else getattr(compressed[0], "text", "")
            top_doc_preview = first_text

        logger.info("adaptive_rag_detail",
                    call=True,
                    call_id=call_id,
                    category="rag",
                    progress="rag",
                    query=query,
                    query_len=len(query),
                    step1_raw_count=len(search_results),
                    step2_expanded_count=len(expanded_docs),
                    step3_compressed_count=len(compressed),
                    confidence=f"{confidence:.3f}",
                    search_elapsed=f"{search_elapsed:.3f}s",
                    total_elapsed=f"{elapsed:.3f}s",
                    top_doc_preview=top_doc_preview,
                    note="Small→Big→Compression 로직 상세")

        logger.info("⏱️ [TIMING] adaptive_rag 완료",
                   call=True,
                   call_id=call_id,
                   progress="rag",
                   category="rag",
                   query=query,
                   raw_count=len(search_results),
                   expanded_count=len(expanded_docs),
                   compressed_count=len(compressed),
                   confidence=f"{confidence:.3f}",
                   search_elapsed=f"{search_elapsed:.3f}s",
                   total_elapsed=f"{elapsed:.3f}s")
        log_call_data(
            call_id or "",
            "rag",
            "rag_search_done",
            query=query,
            result_count=len(search_results),
            expanded_count=len(expanded_docs),
            compressed_count=len(compressed),
            owner_filter=owner,
            confidence=round(confidence, 3),
            search_elapsed_sec=round(search_elapsed, 3),
            total_elapsed_sec=round(elapsed, 3),
            rag_hits_retrieval=build_rag_hits_retrieval(search_results, max_items=8),
            rag_hits_llm_context=build_rag_hits_llm_context(compressed, max_items=8),
            rag_search_trace=rag_search_trace,
        )

        return {
            "rag_results": compressed,
            "confidence": confidence,
            "rag_search_trace": rag_search_trace,
        }

    except Exception as e:
        elapsed = time.time() - _start
        logger.info("timing_segment", segment="adaptive_rag", elapsed_sec=round(elapsed, 3), error=str(e))
        logger.error("adaptive_rag_error", call=True, progress="rag", error=str(e), exc_info=True)
        return {"rag_results": [], "confidence": 0.0, "rag_search_trace": {}}


def _expand_to_parent(docs: list) -> List[Dict]:
    """
    Small-to-Big Retrieval:
    문장 레벨 결과를 parent paragraph로 확장.
    metadata에 parent_text가 있으면 사용, 없으면 원본 그대로.
    """
    expanded = []
    seen_parents = set()

    for doc in docs:
        metadata = doc.metadata if hasattr(doc, "metadata") else doc.get("metadata", {})
        parent_id = metadata.get("parent_id", "")
        parent_text = metadata.get("parent_text", "")

        if parent_id and parent_id in seen_parents:
            continue

        if parent_text:
            expanded.append({
                "text": parent_text,
                "score": doc.score if hasattr(doc, "score") else doc.get("score", 0),
                "metadata": metadata,
                "source": "parent",
            })
            if parent_id:
                seen_parents.add(parent_id)
        else:
            # parent가 없으면 원본 사용
            text = doc.text if hasattr(doc, "text") else doc.get("text", "")
            expanded.append({
                "text": text,
                "score": doc.score if hasattr(doc, "score") else doc.get("score", 0),
                "metadata": metadata,
                "source": "sentence",
            })

    return expanded


def _contextual_compress(docs: List[Dict], query: str) -> List[Dict]:
    """
    Contextual Compression: 질문과 관련된 핵심 문장만 추출.
    간단한 키워드 매칭 기반 (LLM 호출 없이 빠르게).
    """
    query_words = set(query.lower().split())
    compressed = []
    total_chars = 0

    for doc in docs:
        text = doc.get("text", "")
        if not text:
            continue

        # 문장 분리
        sentences = text.replace("\n", ". ").split(". ")
        relevant_sentences = []

        for sent in sentences:
            sent = sent.strip()
            if not sent:
                continue
            # 키워드 겹침 점수
            sent_words = set(sent.lower().split())
            overlap = len(query_words & sent_words)
            if overlap > 0 or len(sentences) <= 3:
                relevant_sentences.append(sent)

        compressed_text = ". ".join(relevant_sentences)

        if total_chars + len(compressed_text) > COMPRESSION_MAX_CHARS:
            remaining = COMPRESSION_MAX_CHARS - total_chars
            if remaining > 50:
                compressed_text = compressed_text[:remaining] + "..."
            else:
                break

        total_chars += len(compressed_text)
        compressed.append({
            **doc,
            "text": compressed_text,
        })

    return compressed
