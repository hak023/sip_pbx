"""
Adaptive RAG 노드.

Small-to-Big Retrieval + Contextual Compression:
  1. Sentence-level 검색 (빠른 유사도 매칭)
  2. Parent Document(Paragraph) 확장 → LLM에 풍부한 맥락 전달
  3. Contextual Compression: 질문 관련 부분만 추출
"""

import structlog
from typing import List, Dict
from src.ai_voicebot.langgraph.state import ConversationState

logger = structlog.get_logger(__name__)

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
    node_start = time.time()

    query = state.get("rewritten_query") or state.get("user_query", "")
    rag_engine = state.get("_rag_engine")
    owner = state.get("_owner")  # 착신번호 기반 테넌트 격리
    call_id = state.get("_call_id") or ""

    if not rag_engine or not query:
        return {"rag_results": [], "confidence": 0.0}

    try:
        # 1단계: Small (Sentence) Retrieval (owner_filter로 테넌트 격리)
        search_start = time.time()
        search_results = await rag_engine.search(
            query,
            owner_filter=owner,
            call_id=call_id or None,
            top_k_override=SENTENCE_TOP_K,
        )
        search_elapsed = time.time() - search_start

        if not search_results:
            elapsed = time.time() - node_start
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
            return {"rag_results": [], "confidence": 0.0}

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

        elapsed = time.time() - node_start
        top_doc_preview = ""
        if compressed:
            first_text = compressed[0].get("text", "") if isinstance(compressed[0], dict) else getattr(compressed[0], "text", "")
            top_doc_preview = (first_text[:200] + "...") if len(first_text) > 200 else first_text

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
                   query=query[:80],
                   raw_count=len(search_results),
                   expanded_count=len(expanded_docs),
                   compressed_count=len(compressed),
                   confidence=f"{confidence:.3f}",
                   search_elapsed=f"{search_elapsed:.3f}s",
                   total_elapsed=f"{elapsed:.3f}s")

        return {
            "rag_results": compressed,
            "confidence": confidence,
        }

    except Exception as e:
        logger.error("adaptive_rag_error", call=True, progress="rag", error=str(e), exc_info=True)
        return {"rag_results": [], "confidence": 0.0}


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
