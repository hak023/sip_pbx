"""통화 종료 후 SIP MESSAGE(문서상 RCS) 요약 문자 — Pipecat·레거시 공통."""

from __future__ import annotations

import os
from typing import Any, Mapping, Optional, Sequence

import structlog

logger = structlog.get_logger(__name__)

# 통화 핵심 요약 문장 길이 (한국어 기준 문자 수, 공백 포함)
_END_CALL_CONVERSATION_SUMMARY_MAX_CHARS = 60


def _booking_api_system_section(booking_context: Optional[Mapping[str, Any]]) -> str:
    """LLM·SMS에 넣을 ‘시스템 기록(예약 API)’ — 성공/실패를 명시해 환각 완료 문구 방지."""
    if not booking_context:
        return ""
    api = booking_context.get("last_booking_api")
    if not isinstance(api, dict) or not (api.get("action") or "").strip():
        return ""
    action = str(api.get("action") or "").strip()
    ok = bool(api.get("ok"))
    detail = str(api.get("detail") or "").strip()[:400]
    bid = api.get("booking_id")
    labels = {
        "create": "예약 생성",
        "cancel": "예약 취소",
        "update": "예약 변경",
    }
    label = labels.get(action, action)
    lines: list[str] = [f"[시스템 기록(예약 API)] 액션: {label}"]
    if ok:
        lines.append("결과: 성공 (아래 [예약·변경 내용]과 요약이 일치해야 함).")
        if bid:
            lines.append(f"예약번호: {bid}")
    else:
        lines.append("결과: 실패 또는 미완료.")
        if detail:
            lines.append(f"사유: {detail}")
        lines.append(
            "중요: 위 결과가 실패/미완료이면 SMS·요약에 '예약이 완료되었습니다' "
            "등 확정 표현을 쓰지 말고, 확인 필요·재문의 유도로 작성하세요."
        )
    return "\n".join(lines)


def _booking_section_from_context(booking_context: Optional[Mapping[str, Any]]) -> str:
    """성공 시에만 DB형 상세(일시·고객명) 블록 — 실패 시 빈 문자열."""
    if not booking_context:
        return ""
    api = booking_context.get("last_booking_api")
    if isinstance(api, dict) and api.get("action") and not api.get("ok"):
        return ""
    action = (booking_context.get("last_action") or "").strip()
    info = booking_context.get("last_booking") or {}
    if not action or not isinstance(info, dict):
        return ""
    action_label = {
        "create": "예약 생성",
        "cancel": "예약 취소",
        "update": "예약 변경",
    }.get(action, "")
    if not action_label:
        return ""
    parts = [f"액션: {action_label}"]
    if info.get("booking_id"):
        parts.append(f"예약번호: {info['booking_id']}")
    date_str = str(info.get("date") or info.get("slot_date") or "")
    time_str = str(info.get("time") or info.get("slot_time") or "")
    if date_str or time_str:
        parts.append(f"일시: {date_str} {time_str}".strip())
    if info.get("customer_name"):
        party = info.get("party_size") or ""
        name_part = str(info["customer_name"])
        if party:
            name_part += f" ({party}명)"
        parts.append(f"고객명: {name_part}")
    return "\n".join(parts)


async def send_end_call_summary_sms(
    *,
    call_id: str,
    caller: str,
    owner: str,
    llm_client: Any,
    assistant_snippets: Sequence[str],
    booking_context: Optional[Mapping[str, Any]] = None,
) -> None:
    """KB 인사 + AI 응대 요약(LLM) + 예약 블록 + SIP MESSAGE 발송."""
    import httpx

    caller = (caller or "").strip()
    if not caller:
        logger.debug("end_call_sms_skip_no_caller", call_id=call_id or "")
        return

    snippets = [s for s in assistant_snippets if (s or "").strip()]
    if not snippets:
        logger.debug("end_call_sms_skip_no_ai_responses", call_id=call_id or "")
        return

    api_base = f"http://127.0.0.1:{os.environ.get('API_PORT', '8000')}"
    own = (owner or "").strip()

    greeting_text = "안녕하세요. 전화주셔서 감사합니다."
    try:
        kb_url = f"{api_base}/api/knowledge?owner={own}&category=greeting_phase1&limit=1"
        async with httpx.AsyncClient(timeout=3.0) as client:
            kb_resp = await client.get(kb_url)
        if kb_resp.status_code == 200:
            kb_data = kb_resp.json()
            items = kb_data.get("items") or []
            if items and items[0].get("text"):
                greeting_text = str(items[0]["text"]).strip()
        logger.debug("end_call_sms_greeting_fetched", greeting=greeting_text[:40])
    except Exception as kb_err:
        logger.warning("end_call_sms_kb_error", error=str(kb_err))

    booking_section = _booking_section_from_context(booking_context)
    api_facts = _booking_api_system_section(booking_context)
    last_ai = list(snippets)[-5:]

    system_prompt = (
        "당신은 통화 종료 후 고객에게 보낼 SMS 문자를 작성하는 어시스턴트입니다.\n"
        "아래 규칙을 반드시 따르세요:\n"
        "- 반말 없이 공손한 한국어로 작성\n"
        f"- 이번 통화의 핵심 내용을 담은 **요약 문장은 반드시 한 문장만**, "
        f"줄바꿈 없이, **공백 포함 최대 {_END_CALL_CONVERSATION_SUMMARY_MAX_CHARS}자** 이내로 작성\n"
        "  (예약·변경 블록은 요약 글자 수에 포함하지 않아도 됨)\n"
        "- 총 SMS 본문은 300자 이하(고정 마무리 문장 포함)\n"
        "- 이모지, 마크다운, 특수문자 사용 금지\n"
        "- 섹션 구분은 빈 줄(줄바꿈 2회) 사용\n"
        "- 출력은 SMS 본문 텍스트만 (설명 없이)\n"
        "- **[시스템 기록(예약 API)]** 블록이 있으면 그 ‘결과’가 최우선이다. "
        "실패/미완료인데 [AI 응대 내용]에 예약 완료처럼 적혀 있어도 **완료로 쓰지 말 것**.\n"
        "- [시스템 기록]이 없을 때만 [AI 응대 내용]을 참고하되, "
        "예약 확정 여부는 단정하지 말고 ‘문의·확인’ 톤을 유지할 것."
    )
    user_prompt_parts = [
        f"[인사말]\n{greeting_text}",
        f"[AI 응대 내용 (마지막 {len(last_ai)}개 응답)]\n"
        + "\n".join(f"- {r[:120]}" for r in last_ai),
    ]
    if api_facts:
        user_prompt_parts.append(api_facts)
    if booking_section:
        user_prompt_parts.append(f"[예약·변경 내용]\n{booking_section}")
    user_prompt_parts.append(
        "위 정보를 바탕으로 SMS 문자 본문을 작성하세요.\n"
        f"구성: (1) 첫 블록에 [인사말]과 비슷한 인사 한두 문장 "
        f"(2) 빈 줄 (3) **통화 요약: 한 문장만, 공백 포함 {_END_CALL_CONVERSATION_SUMMARY_MAX_CHARS}자 이하** "
        "(4) [예약·변경 내용]이 있으면 빈 줄 뒤에 그대로 붙임 "
        "(5) 빈 줄 후 마지막에 아래 문장을 반드시 한 줄로 넣음.\n"
        "반드시 마지막 줄에 '추가 문의사항은 전화 또는 문자로 남겨주시면 감사하겠습니다.' 를 포함하세요."
    )
    user_prompt = "\n\n".join(user_prompt_parts)

    sms_body = ""
    if llm_client:
        logger.info("end_call_sms_llm_invoke", call_id=call_id or "")
        try:
            gen = getattr(llm_client, "generate_response", None)
            if callable(gen):
                sms_body = await gen(
                    user_text=user_prompt,
                    context_docs=[],
                    system_prompt=system_prompt,
                    call_id=call_id or None,
                )
                if (sms_body or "").strip():
                    logger.info(
                        "end_call_sms_llm_response",
                        call_id=call_id or "",
                        response_preview=(sms_body or "").strip()[:220],
                    )
        except Exception as e:
            logger.warning("end_call_sms_llm_invoke_failed", error=str(e))
    if not (sms_body or "").strip():
        api = (booking_context or {}).get("last_booking_api") if isinstance(booking_context, dict) else None
        api_failed = isinstance(api, dict) and api.get("action") and not api.get("ok")
        lines = [greeting_text, "", "오늘 통화 내용을 안내해 드립니다.", ""]
        if api_failed:
            ad = str(api.get("detail") or "").strip()
            lines.append(
                "예약 시스템에서는 최종 처리가 완료되지 않았을 수 있습니다. "
                + (f"({ad[:80]}…)" if len(ad) > 80 else (f"({ad})" if ad else ""))
            )
            lines.append("")
        elif last_ai:
            _fb = (last_ai[-1] or "").strip().replace("\n", " ")
            if len(_fb) > _END_CALL_CONVERSATION_SUMMARY_MAX_CHARS:
                _fb = _fb[: _END_CALL_CONVERSATION_SUMMARY_MAX_CHARS - 1].rstrip() + "…"
            lines.append(_fb)
            lines.append("")
        if booking_section and not api_failed:
            lines.append(booking_section)
            lines.append("")
        lines.append("추가 문의사항은 전화 또는 문자로 남겨주시면 감사하겠습니다.")
        sms_body = "\n".join(lines)

    sms_body = (sms_body or "").strip()
    if not sms_body:
        logger.warning("end_call_sms_empty_body", call_id=call_id or "")
        return
    if len(sms_body) > 300:
        sms_body = sms_body[:297] + "..."

    sip_ip = os.environ.get("SIP_SERVER_IP", "127.0.0.1")
    sip_port = int(os.environ.get("SIP_SERVER_PORT", "5060"))
    from_phone = own or "ai-pbx"

    _api_ok_log: Optional[bool] = None
    if isinstance(booking_context, dict):
        _la = booking_context.get("last_booking_api")
        if isinstance(_la, dict) and "ok" in _la:
            _api_ok_log = bool(_la.get("ok"))

    logger.info(
        "end_call_sms_sending",
        call_id=call_id or "",
        to=caller,
        body_len=len(sms_body),
        body_preview=(sms_body or "")[:200],
        has_booking_section=bool(booking_section),
        has_booking_api_facts=bool(api_facts),
        booking_api_ok=_api_ok_log,
    )
    from src.services.sip_sms_service import send_sip_sms_sync

    result = send_sip_sms_sync(
        to_phone=caller,
        message=sms_body,
        from_phone=from_phone,
        sip_server_ip=sip_ip,
        sip_server_port=sip_port,
    )
    logger.info(
        "end_call_sms_result",
        call_id=call_id or "",
        success=result.get("success"),
        to=caller,
        body_preview=(sms_body or "")[:200],
    )
    try:
        from src.services.chat_service import save_chat_message

        save_chat_message(
            thread_id=caller,
            owner=own or "pbx",
            direction="outbound",
            from_phone=from_phone,
            to_phone=caller,
            body=sms_body,
            call_id=call_id or "",
            status="sent" if result.get("success") else "failed",
            error_code="" if result.get("success") else "end_call_sms",
        )
    except Exception as db_err:
        logger.warning("end_call_sms_db_save_failed", error=str(db_err))
