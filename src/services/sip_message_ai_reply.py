"""
SIP MESSAGE(채팅)·RCS 등 텍스트 수신 시 LangGraph ConversationAgent로 자동 텍스트 응답.

- 통화 파이프라인과 동일한 에이전트(RAG·의도·캐시)를 사용하되, STT/TTS/RTP 없이 텍스트만 처리한다.
- PBX가 발송하는 자동 답변 MESSAGE에는 ``X-PBX-Skip-AI-Reply`` 를 붙여 재귀 트리거를 막는다.
- 활성화 여부·접두어: **설정 페이지** ``chat_relay_settings`` 의 ``message_ai_reply_enabled`` /
  ``message_ai_reply_prefix`` 만 사용한다. (페르소나 레거시 플래그는 사용하지 않음.)
"""

from __future__ import annotations

import asyncio
import re
from collections import OrderedDict
from typing import Any, Dict, Optional

import structlog

logger = structlog.get_logger(__name__)

DEFAULT_AI_PREFIX = "[AI 자동응답] "
_MAX_CACHED_AGENTS = 96

# structlog/JSON 직렬화는 U+D800–U+DFFF(예: surrogateescape SIP 본문)를 허용하지 않음
_SURROGATE_RANGE_RE = re.compile(r"[\uD800-\uDFFF]")


def _sanitize_for_log(text: str) -> str:
    if not text:
        return text
    return _SURROGATE_RANGE_RE.sub("\ufffd", text)


_agent_cache: "OrderedDict[str, Any]" = OrderedDict()
_agent_locks: Dict[str, asyncio.Lock] = {}


def _cache_key(kb_owner: str, from_peer: str) -> str:
    return f"{(kb_owner or '').strip()}:{(from_peer or '').strip().lower()}"


def _graph_call_id(kb_owner: str, from_peer: str) -> str:
    """LangGraph checkpointer 스레드 ID — 내선·상대 조합으로 대화 맥락 유지."""
    safe_o = re.sub(r"[^\w\-]+", "_", kb_owner)[:32]
    safe_f = re.sub(r"[^\w\-]+", "_", from_peer)[:32]
    return f"sipchat-{safe_o}-{safe_f}"


def _lock_for(key: str) -> asyncio.Lock:
    if key not in _agent_locks:
        _agent_locks[key] = asyncio.Lock()
    return _agent_locks[key]


async def schedule_sip_message_ai_reply(
    *,
    sip_endpoint: Any,
    body_display: str,
    chat_owner: str,
    from_peer: str,
    to_peer: str,
    sip_call_id: str,
) -> None:
    """비동기 태스크에서 호출 — SIP 수신 처리와 분리."""
    text = (body_display or "").strip()
    if not text or not to_peer or not from_peer:
        logger.debug("sip_message_ai_reply_skip", reason="empty_or_peer")
        return

    logger.info(
        "sip_message_ai_reply_task_start",
        sip_ai_ctx="sip_message_ai_reply",
        chat_owner=chat_owner,
        from_peer=from_peer,
        to_peer=to_peer,
        sip_call_id=sip_call_id,
        inbound_preview=_sanitize_for_log(text[:160]),
        inbound_len=len(text),
    )

    try:
        from src.services.chat_relay_service import get_chat_relay_settings

        kb_owner_for_settings = (to_peer or "").strip()
        try:
            from src.common.sip_owner import normalize_owner_username

            n = normalize_owner_username(kb_owner_for_settings)
            if n:
                kb_owner_for_settings = n
        except Exception:
            pass

        relay = get_chat_relay_settings(kb_owner_for_settings)
        if not int(relay.get("message_ai_reply_enabled") or 0):
            logger.info(
                "sip_message_ai_reply_skipped",
                sip_ai_ctx="sip_message_ai_reply",
                reason="message_ai_disabled_in_settings",
                owner=kb_owner_for_settings,
                note="채팅 설정에서 «SIP MESSAGE 수신 시 AI 자동응답»을 켜야 합니다.",
            )
            return

        reply_prefix = (relay.get("message_ai_reply_prefix") or "").strip() or DEFAULT_AI_PREFIX

        cm = getattr(sip_endpoint, "call_manager", None)
        orch = getattr(cm, "ai_orchestrator", None) if cm else None
        llm = getattr(orch, "llm", None) if orch else None
        rag = getattr(orch, "rag", None) if orch else None
        if not llm:
            try:
                from src.ai_voicebot.factory import get_llm_client

                llm = get_llm_client()
            except Exception:
                llm = None
        if not llm or not rag:
            logger.warning(
                "sip_message_ai_reply_skipped",
                sip_ai_ctx="sip_message_ai_reply",
                reason="no_llm_or_rag",
                has_llm=bool(llm),
                has_rag=bool(rag),
            )
            return

        embedder = getattr(rag, "embedder", None)
        vector_db = getattr(rag, "vector_db", None)

        from src.services.knowledge_service import get_knowledge_service
        from src.ai_voicebot.knowledge.organization_info import OrganizationInfoManager

        ks = get_knowledge_service()
        org_manager = None
        if ks:
            org_manager = OrganizationInfoManager(owner=kb_owner_for_settings, knowledge_service=ks)
            try:
                await org_manager.load()
            except Exception as e:
                logger.warning("sip_message_ai_org_manager_load_failed", error=str(e))
                org_manager = None

        kb_owner = kb_owner_for_settings

        key = _cache_key(kb_owner, from_peer)
        lock = _lock_for(key)

        async with lock:
            agent = _agent_cache.get(key)
            if agent is None:
                from src.ai_voicebot.langgraph.agent import ConversationAgent

                agent = ConversationAgent(
                    llm,
                    rag_engine=rag,
                    embedder=embedder,
                    vector_db=vector_db,
                    org_manager=org_manager,
                    owner=kb_owner,
                )
                _agent_cache[key] = agent
                _agent_cache.move_to_end(key)
                while len(_agent_cache) > _MAX_CACHED_AGENTS:
                    old_k, _ = _agent_cache.popitem(last=False)
                    _agent_locks.pop(old_k, None)

            graph_cid = _graph_call_id(kb_owner, from_peer)
            logger.info(
                "sip_message_ai_reply_llm_start",
                sip_ai_ctx="sip_message_ai_reply",
                kb_owner=kb_owner,
                from_peer=from_peer,
                to_peer=to_peer,
                graph_call_id=graph_cid,
                user_preview=_sanitize_for_log(text[:120]),
            )

            result = await agent.process_utterance(
                text,
                call_id=graph_cid,
                caller_number=from_peer.strip(),
            )
            raw = (result.get("response") or "").strip()
            if not raw:
                raw = (
                    "지금은 자동으로 답변하기 어렵습니다. "
                    "잠시 후 다시 보내 주시거나 전화로 문의해 주세요."
                )

            prefix = (reply_prefix or DEFAULT_AI_PREFIX).strip()
            if prefix and not prefix.endswith((" ", "]", ")", ">", ":", "|", "-", "。")):
                prefix = f"{prefix} "
            if prefix and (raw.startswith(prefix.strip()) or raw.startswith(DEFAULT_AI_PREFIX.strip())):
                full_body = raw
            elif prefix:
                full_body = f"{prefix.strip()}\n{raw}"
            else:
                full_body = raw

        from src.services.chat_sip_delivery import deliver_chat_sip_message
        from src.services.chat_service import save_chat_message
        from src.services.chat_relay_service import resolve_chat_owner_for_inbound
        from src.websocket.server import emit_sip_message_received

        sip_r = deliver_chat_sip_message(
            to_peer.strip(),
            from_peer.strip(),
            full_body,
            suppress_ai_loop=True,
            wait_for_final_response=False,
        )
        ok = bool(sip_r.get("success"))
        _code = str(sip_r.get("code") or "")
        if ok and _code == "sip_pending":
            st = "pending_sip"
            err_c = "sip_pending"
        elif ok:
            st = "sent"
            err_c = ""
        else:
            st = "failed"
            err_c = _code or "failed"

        co = (chat_owner or "").strip() or kb_owner
        save_chat_message(
            thread_id=from_peer.strip(),
            owner=co,
            direction="outbound",
            from_phone=to_peer.strip(),
            to_phone=from_peer.strip(),
            body=full_body,
            call_id=(f"ai-{sip_call_id}")[:120],
            status=st,
            error_code=err_c or "",
        )
        if from_peer.strip().lower() != to_peer.strip().lower():
            try:
                sender_owner = resolve_chat_owner_for_inbound(from_peer.strip())
                save_chat_message(
                    thread_id=to_peer.strip(),
                    owner=sender_owner,
                    direction="inbound",
                    from_phone=to_peer.strip(),
                    to_phone=from_peer.strip(),
                    body=full_body,
                    call_id=(f"ai-{sip_call_id}")[:120],
                    status=st,
                    error_code=err_c or "",
                )
            except Exception as mir_e:
                logger.warning("sip_message_ai_reply_mirror_db_failed", error=str(mir_e))

        try:
            # 도크 스레드는 tenant_owner|상대내선(from_peer). from_uri=to_peer(착신/AI측)이면 1003|1003 으로 잘못 열림.
            await emit_sip_message_received(
                from_uri=from_peer.strip(),
                from_addr="sip-ai-auto",
                body=full_body,
                content_type="text/plain; charset=UTF-8",
                call_id=(f"ai-{sip_call_id}")[:120],
                to_user=to_peer.strip(),
                tenant_owner=(co or kb_owner or "").strip(),
                thread_peer=from_peer.strip(),
                dock_as_outbound=True,
            )
        except Exception as ws_e:
            logger.warning("sip_message_ai_reply_ws_emit_failed", error=str(ws_e))

        logger.info(
            "sip_message_ai_reply_done",
            sip_ai_ctx="sip_message_ai_reply",
            sip_ok=ok,
            sip_code=sip_r.get("code"),
            response_len=len(full_body),
            response_preview=_sanitize_for_log((full_body or "")[:220]),
            kb_owner=kb_owner,
            from_peer=from_peer,
            to_peer=to_peer,
            intent=result.get("intent"),
        )
    except Exception as e:
        logger.error(
            "sip_message_ai_reply_error",
            sip_ai_ctx="sip_message_ai_reply",
            error=str(e),
            exc_info=True,
        )
