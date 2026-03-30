"""
Greeting/Farewell 즉시 응답 노드.

ChromaDB knowledge 컬렉션에서 해당 카테고리 문서를 직접 가져와 응답.
LLM 호출 없이 0.01초 이내 처리. (최적화 4.2)

카테고리 매핑:
  greeting → greeting_phase2 문서 (greeting_phase1은 통화 시작 시 별도 TTS)
  farewell → farewell 문서
"""

import asyncio
import time
from datetime import datetime
from typing import Optional

import structlog
from src.ai_voicebot.langgraph.state import ConversationState

logger = structlog.get_logger(__name__)

DEFAULT_GREETING = "안녕하세요, 무엇을 도와드릴까요?"
DEFAULT_FAREWELL = "감사합니다. 좋은 하루 되세요."


async def greeting_farewell_kb_node(state: ConversationState) -> dict:
    """
    ChromaDB knowledge 컬렉션에서 greeting/farewell 문서 조회 → 즉시 응답.
    LLM/RAG/캐시 불필요.
    """
    _start = time.time()
    intent = state.get("intent", "")
    owner = state.get("_owner") or ""
    vector_db = state.get("_vector_db")
    user_query = state.get("user_query", "")

    if intent == "greeting":
        category = "greeting_phase2"
        default = DEFAULT_GREETING
    elif intent == "farewell":
        category = "farewell"
        default = DEFAULT_FAREWELL
    else:
        return {}

    response_text = None

    if vector_db and owner:
        try:
            from src.ai_voicebot.knowledge.knowledge_service import get_knowledge_greeting_text

            loop = asyncio.get_event_loop()
            kb_text = await loop.run_in_executor(
                None,
                lambda: get_knowledge_greeting_text(vector_db, owner, category),
            )
            if kb_text and len(kb_text.strip()) >= 2:
                response_text = kb_text.strip()
                logger.info(
                    "greeting_farewell_kb_hit",
                    intent=intent,
                    category=category,
                    owner=owner,
                    text_len=len(response_text),
                    elapsed_ms=round((time.time() - _start) * 1000, 1),
                )
        except Exception as e:
            logger.debug("greeting_farewell_kb_lookup_failed",
                         intent=intent, owner=owner, error=str(e))

    if not response_text:
        response_text = default
        logger.info(
            "greeting_farewell_kb_default",
            intent=intent,
            category=category,
            owner=owner,
            note="KB에 문서 없음 → 기본 문구",
        )

    messages = state.get("messages", [])
    updated_messages = list(messages)
    updated_messages.append({
        "role": "user",
        "content": user_query,
        "timestamp": datetime.now().isoformat(),
    })
    updated_messages.append({
        "role": "assistant",
        "content": response_text,
        "timestamp": datetime.now().isoformat(),
    })

    elapsed = time.time() - _start
    logger.info("timing_segment", segment="greeting_farewell_kb",
                elapsed_sec=round(elapsed, 3), intent=intent)

    return {
        "rag_cache_hit": True,
        "response": response_text,
        "response_chunks": [],
        "messages": updated_messages,
        "confidence": 1.0,
        "llm_rag_applied": [],
        "llm_rag_context_source": f"kb_{category}",
        "rag_search_trace": {},
    }
