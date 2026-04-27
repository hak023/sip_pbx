"""
Call-scoped 런타임 객체 레지스트리.

LangGraph ConversationState는 checkpointer가 직렬화(msgpack/pickle)하므로,
직렬화 불가 객체(LLMClient, RAGEngine 등)를 state에 넣으면
"Type is not msgpack serializable" 에러가 발생한다.

이 모듈은 ContextVar를 사용해 asyncio Task 단위로 격리된 레지스트리를 제공한다.
동시 통화 간 간섭 없이 각 통화의 런타임 참조를 안전하게 공유한다.

사용 방법:
    # agent.py (invoke 시작 전)
    from src.ai_voicebot.langgraph.call_context import set_call_context, clear_call_context
    set_call_context(
        llm_client=...,
        rag_engine=...,
        ...
    )

    # 노드 (state 대신 이 모듈에서 직접 조회)
    from src.ai_voicebot.langgraph.call_context import get_llm_client, get_rag_engine
    llm = get_llm_client()
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Optional

# ── 레지스트리 ContextVar ────────────────────────────────────────────────────
_ctx_llm_client: ContextVar[Optional[Any]] = ContextVar("llm_client", default=None)
_ctx_rag_engine: ContextVar[Optional[Any]] = ContextVar("rag_engine", default=None)
_ctx_embedder: ContextVar[Optional[Any]] = ContextVar("embedder", default=None)
_ctx_vector_db: ContextVar[Optional[Any]] = ContextVar("vector_db", default=None)
_ctx_org_manager: ContextVar[Optional[Any]] = ContextVar("org_manager", default=None)
_ctx_hangup_callback: ContextVar[Optional[Any]] = ContextVar("hangup_callback", default=None)


def set_call_context(
    llm_client=None,
    rag_engine=None,
    embedder=None,
    vector_db=None,
    org_manager=None,
    hangup_callback=None,
) -> None:
    """invoke 직전에 호출해 Task 스코프 레지스트리를 채운다."""
    _ctx_llm_client.set(llm_client)
    _ctx_rag_engine.set(rag_engine)
    _ctx_embedder.set(embedder)
    _ctx_vector_db.set(vector_db)
    _ctx_org_manager.set(org_manager)
    _ctx_hangup_callback.set(hangup_callback)


def clear_call_context() -> None:
    """invoke 완료 후 명시적으로 참조를 해제한다 (선택 사항, GC 보조용)."""
    _ctx_llm_client.set(None)
    _ctx_rag_engine.set(None)
    _ctx_embedder.set(None)
    _ctx_vector_db.set(None)
    _ctx_org_manager.set(None)
    _ctx_hangup_callback.set(None)


def get_llm_client() -> Optional[Any]:
    return _ctx_llm_client.get()


def get_rag_engine() -> Optional[Any]:
    return _ctx_rag_engine.get()


def get_embedder() -> Optional[Any]:
    return _ctx_embedder.get()


def get_vector_db() -> Optional[Any]:
    return _ctx_vector_db.get()


def get_org_manager() -> Optional[Any]:
    return _ctx_org_manager.get()


def get_hangup_callback() -> Optional[Any]:
    return _ctx_hangup_callback.get()
