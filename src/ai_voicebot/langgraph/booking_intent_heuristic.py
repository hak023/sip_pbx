"""
음성 예약 레인 휴리스틱 — classify_intent 이후 intent를 booking으로 승격.

설계: docs/reports/2026-04/2026-04-20_1730_VOICE_BOOKING_AUTO_API_DESIGN.md §3.1
환경변수:
  BOOKING_VOICE_ENABLED — 기본 on (0/false/no 이면 비활성)
  BOOKING_VOICE_INTENT_STRICT — 1 이면 날짜·시각 증거 없이 '예약' 단어만으로는 승격하지 않음
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, Mapping, Tuple

from src.common.call_data_record_logger import log_call_data

# classify_intent._BOOKING_ACTION_PATTERNS 와 동기화 + 음성 STT 변형
BOOKING_ACTION_PATTERNS: tuple[str, ...] = (
    "예약하려고",
    "예약하고 싶",
    "예약해주",
    "예약해줘",
    "예약 해줘",
    "예약 좀 해",
    "예약할게",
    "예약할게요",
    "예약 부탁",
    "예약 하고 싶",
    "취소하려고",
    "취소하고 싶",
    "취소해줘",
    "취소해주",
    "예약 취소",
    "예약 변경",
    "예약 바꿔",
    "날짜 바꿔",
    "시간 바꿔",
    "예약 확인",
    "내 예약",
    "제 예약",
    "예약 조회",
    "예약번호",
    "빈 자리",
    "빈자리",
    "빈 날",
    "언제 예약",
    "예약 가능한",
    # STT·구어 변형
    "예약이요",
    "시에 예약",
    "에 예약",
)

_PROMOTABLE_FROM = frozenset(
    {"question", "chitchat", "help", "nlu_fallback", "clarification"}
)
_NO_OVERRIDE = frozenset({"farewell", "transfer", "booking"})

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_TIME_HINT = re.compile(r"\d{1,2}:\d{2}|\d{1,2}\s*시")
_REL_DAY = ("오늘", "내일", "모레", "글피", "이번 주", "다음 주", "다음주", "이번주")


def booking_voice_enabled() -> bool:
    raw = (os.environ.get("BOOKING_VOICE_ENABLED") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def booking_voice_intent_strict() -> bool:
    return (os.environ.get("BOOKING_VOICE_INTENT_STRICT") or "").strip() == "1"


def _combined_text(user_query: str, user_query_raw: str, main_clause: str) -> str:
    parts = [user_query or "", user_query_raw or "", main_clause or ""]
    return " ".join(p for p in parts if p).strip()


def _has_booking_action_pattern(text_lower: str) -> bool:
    return any(p in text_lower for p in BOOKING_ACTION_PATTERNS)


def _has_reserve_word(text: str) -> bool:
    return "예약" in text


def _has_iso_date(text: str) -> bool:
    return bool(_ISO_DATE.search(text))


def _has_relative_day(text_lower: str) -> bool:
    return any(k in text_lower for k in _REL_DAY)


def _has_date_evidence(text: str, text_lower: str) -> bool:
    return _has_iso_date(text) or _has_relative_day(text_lower)


def _has_time_evidence(text_lower: str) -> bool:
    return bool(_TIME_HINT.search(text_lower))


def _should_promote_slot_and_reserve(
    text: str,
    text_lower: str,
    strict: bool,
) -> Tuple[bool, str]:
    """예약 + 날짜 증거 + 시각 증거 (STRICT 시 액션 패턴 없을 때 필수)."""
    if not _has_reserve_word(text):
        return False, ""
    has_d = _has_date_evidence(text, text_lower)
    has_t = _has_time_evidence(text_lower)
    if strict:
        if has_d and has_t:
            return True, "reserve_word_date_and_time_strict"
        return False, ""
    if has_d and has_t:
        return True, "reserve_word_date_and_time"
    # 비 strict: 날짜만 또는 시각만 있어도 승격 (약한 신호 — 설계상 동점 booking)
    if has_d or has_t:
        return True, "reserve_word_partial_datetime"
    return False, ""


def apply_booking_intent_override(
    intent: str,
    *,
    user_query: str,
    user_query_raw: str,
    main_clause: str,
    booking_active: bool,
    call_id: str,
    classify_path: str,
) -> Tuple[str, str]:
    """
    Returns (final_intent, override_reason).
    override_reason 빈 문자열이면 변경 없음.
    """
    intent = (intent or "").strip().lower()
    if not booking_voice_enabled():
        return intent, ""
    if intent in _NO_OVERRIDE:
        return intent, ""
    if intent not in _PROMOTABLE_FROM and intent not in ("affirm", "deny"):
        return intent, ""

    combined = _combined_text(user_query, user_query_raw, main_clause)
    text_lower = combined.lower()

    strict = booking_voice_intent_strict()

    if booking_active and intent not in ("farewell", "transfer"):
        # 예약 대화 중 — 짧은 긍정/부정도 booking 레인 유지
        if intent in _PROMOTABLE_FROM or intent in ("affirm", "deny"):
            if call_id:
                log_call_data(
                    call_id,
                    "booking",
                    "booking_intent_routed",
                    from_intent=intent,
                    to_intent="booking",
                    reason="booking_context_active",
                    classify_path=classify_path,
                )
            return "booking", "booking_context_active"

    if intent not in _PROMOTABLE_FROM:
        return intent, ""

    if _has_booking_action_pattern(text_lower):
        if call_id:
            log_call_data(
                call_id,
                "booking",
                "booking_intent_routed",
                from_intent=intent,
                to_intent="booking",
                reason="booking_action_pattern",
                classify_path=classify_path,
            )
        return "booking", "booking_action_pattern"

    ok_slot, reason = _should_promote_slot_and_reserve(combined, text_lower, strict)
    if ok_slot:
        if call_id:
            log_call_data(
                call_id,
                "booking",
                "booking_intent_routed",
                from_intent=intent,
                to_intent="booking",
                reason=reason,
                classify_path=classify_path,
            )
        return "booking", reason

    return intent, ""


def merge_booking_intent_into_result(
    result: Dict[str, Any],
    state: Mapping[str, Any],
    *,
    call_id: str,
    query: str,
    main_clause: str,
    classify_path: str,
) -> Dict[str, Any]:
    """classify_intent 반환 dict에 예약 휴리스틱을 적용한다."""
    user_query_raw = (state.get("user_query_raw") or "").strip()
    bc = state.get("booking_context") or {}
    # messages 는 LangChain 객체 등으로 체크포인트 직렬화 시 비어 보일 수 있음 →
    # booking_agent 가 세팅하는 JSON 친화 플래그로 보강 (예약 멀티턴 유지)
    booking_active = bool(
        isinstance(bc, dict)
        and (
            bc.get("messages")
            or bc.get("collected_slots")
            or bc.get("booking_flow_active") is True
        )
    )
    intent = str(result.get("intent") or "")
    new_intent, reason = apply_booking_intent_override(
        intent,
        user_query=query,
        user_query_raw=user_query_raw,
        main_clause=main_clause,
        booking_active=booking_active,
        call_id=call_id,
        classify_path=classify_path,
    )
    if new_intent == intent or not reason:
        return result
    out = dict(result)
    out["intent"] = new_intent
    if "confidence" in out and out["confidence"] is not None:
        try:
            out["confidence"] = min(float(out["confidence"]), 0.95)
        except (TypeError, ValueError):
            out["confidence"] = 0.95
    return out
