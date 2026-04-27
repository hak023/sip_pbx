"""통화 종료 후 발신자 연락처 자동 생성(LLM + 끝 4자리 접미사)."""

from __future__ import annotations

import json
import re
from typing import Any, Optional

import structlog

from src.common.caller_contact_db import build_display_name, upsert_auto_llm_contact
from src.common.caller_needle import caller_match_needle, last_digit_suffix

logger = structlog.get_logger(__name__)

_CONFIDENCE_MIN = 0.55
_LLM_TIMEOUT_SEC = 25.0


def _fetch_booking_customer_name(*, owner: str, call_id: str, needle: str) -> Optional[str]:
    own = (owner or "").strip()
    cid = (call_id or "").strip()
    if not own:
        return None
    try:
        from src.booking.database import get_db

        with get_db() as conn:
            if cid:
                row = conn.execute(
                    """
                    SELECT customer_name FROM bookings
                    WHERE owner = ? AND call_id = ? AND TRIM(customer_name) != ''
                    ORDER BY updated_at DESC LIMIT 1
                    """,
                    (own, cid),
                ).fetchone()
                if row and (row["customer_name"] or "").strip():
                    return str(row["customer_name"]).strip()
            if needle:
                like = f"%{needle}%"
                row = conn.execute(
                    """
                    SELECT customer_name FROM bookings
                    WHERE owner = ? AND TRIM(customer_name) != ''
                      AND customer_phone LIKE ?
                    ORDER BY updated_at DESC LIMIT 1
                    """,
                    (own, like),
                ).fetchone()
                if row and (row["customer_name"] or "").strip():
                    return str(row["customer_name"]).strip()
    except Exception as e:
        logger.warning("booking_hint_lookup_failed", error=str(e))
    return None


def _parse_llm_json(text: str) -> Optional[dict]:
    t = (text or "").strip()
    if not t:
        return None
    t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{[^{}]*\}", t, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


async def run_caller_contact_autofill(
    *,
    llm: Any,
    owner: str,
    caller_raw: str,
    call_id: str,
    call_summary: Optional[str],
    transcript_excerpt: str = "",
) -> None:
    """백그라운드 호출: 수동 연락처 없으면 LLM으로 base_label 유추 후 저장."""
    own = (owner or "").strip()
    cr = (caller_raw or "").strip()
    if not own or not cr:
        logger.info("caller_contact_autofill_skipped", reason="missing_owner_or_caller")
        return
    needle, needle_src = caller_match_needle(cr)
    if not needle:
        logger.info(
            "caller_contact_autofill_skipped",
            reason="empty_needle",
            needle_src=needle_src,
        )
        return
    from src.common.caller_contact_db import get_caller_contact

    existing = get_caller_contact(own, needle)
    if existing and (existing.get("source") or "") == "manual":
        logger.info("caller_contact_autofill_skipped", reason="manual_row_exists", needle=needle[:12])
        return

    booking_name = _fetch_booking_customer_name(owner=own, call_id=call_id, needle=needle)
    suffix4 = last_digit_suffix(cr, 4) or last_digit_suffix(needle, 4)
    if not suffix4 and needle:
        suffix4 = needle[-4:]

    summary = (call_summary or "").strip()[:1200]
    excerpt = (transcript_excerpt or "").strip()[:2000]

    if booking_name and len(booking_name) >= 2:
        display = build_display_name(booking_name, suffix4)
        upsert_auto_llm_contact(
            owner=own,
            canonical_phone=needle,
            display_name=display,
            confidence=0.95,
            source="auto_booking_hint",
        )
        logger.info(
            "caller_contact_autofill_booking_hint",
            owner=own[:32],
            display_preview=display[:48],
        )
        return

    if not summary and not excerpt:
        logger.info("caller_contact_autofill_skipped", reason="no_summary_no_transcript")
        return

    system = (
        "통화 맥락만 보고 짧은 한국어 호칭 라벨을 제안합니다. "
        "출력은 JSON 한 객체만: {\"base_label\": \"2~12자\", \"confidence\": 0~1}.\n"
        "규칙: 실명 추정 금지. 예: 예약문의, 배송문의, 단골, 신규문의, 민원, 상담요청 등. "
        "특수문자·공백·이모지 없이 base_label만."
    )
    user_parts = [
        f"발신 식별 끝4자리(참고): {suffix4}",
        f"요약:\n{summary}" if summary else "",
        f"대화 발췌:\n{excerpt}" if excerpt else "",
    ]
    user_msg = "\n\n".join(p for p in user_parts if p)

    raw = ""
    try:
        import asyncio

        if hasattr(llm, "generate_simple"):
            raw = await asyncio.wait_for(
                llm.generate_simple(
                    f"{system}\n\n{user_msg}",
                    max_tokens=120,
                ),
                timeout=_LLM_TIMEOUT_SEC,
            )
        elif hasattr(llm, "generate_response"):
            kwargs: dict = {
                "user_text": user_msg,
                "context_docs": [],
                "system_prompt": system,
            }
            if call_id:
                kwargs["call_id"] = call_id
            raw = await asyncio.wait_for(
                llm.generate_response(**kwargs),
                timeout=_LLM_TIMEOUT_SEC,
            )
        else:
            logger.warning("caller_contact_autofill_skipped", reason="llm_no_suitable_method")
            return
    except asyncio.TimeoutError:
        logger.warning("caller_contact_autofill_llm_timeout", call_id=call_id[:24] if call_id else "")
        return
    except Exception as e:
        logger.warning("caller_contact_autofill_llm_failed", error=str(e))
        return

    parsed = _parse_llm_json(str(raw))
    if not isinstance(parsed, dict):
        logger.info("caller_contact_autofill_skipped", reason="json_parse_failed", preview=str(raw)[:80])
        return
    base = str(parsed.get("base_label") or "").strip()
    try:
        conf = float(parsed.get("confidence", 0))
    except (TypeError, ValueError):
        conf = 0.0
    if not base or conf < _CONFIDENCE_MIN:
        logger.info(
            "caller_contact_autofill_skipped",
            reason="low_confidence_or_empty_label",
            base_preview=base[:20],
            confidence=conf,
        )
        return
    display = build_display_name(base, suffix4)
    upsert_auto_llm_contact(
        owner=own,
        canonical_phone=needle,
        display_name=display,
        confidence=conf,
    )


def schedule_caller_contact_autofill(
    *,
    llm: Any,
    owner: str,
    caller_raw: str,
    call_id: str,
    call_summary: Optional[str],
    transcript_excerpt: str = "",
) -> None:
    """asyncio.create_task 용 래퍼 (동기 컨텍스트에서 호출)."""
    import asyncio

    async def _run() -> None:
        await run_caller_contact_autofill(
            llm=llm,
            owner=owner,
            caller_raw=caller_raw,
            call_id=call_id,
            call_summary=call_summary,
            transcript_excerpt=transcript_excerpt,
        )

    try:
        asyncio.create_task(_run())
    except RuntimeError:
        # 이벤트 루프 없음(단위 테스트 등)
        logger.debug("caller_contact_autofill_no_loop")
