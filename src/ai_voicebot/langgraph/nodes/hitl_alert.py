"""
HITL (Human-In-The-Loop) Alert 노드.

일정 조건(confidence 낮음, complaint 의도, 명시적 요청) 충족 시
운영자 개입이 필요함을 표시한다.

escalation_mode 분기:
  - "hitl"     : 기존 동작 — needs_human=True로 대시보드 알림
  - "transfer" : needs_human=True + needs_transfer=True로 SIP 호전환 트리거
  - "none"     : AI 판정 기반 HITL/호전환만 억제 (고객이 명시적으로 상담원 연결 요청한 경우는 유지)

transfer_extension: 착신 규칙(call-control)으로 해석한 내선. Persona.transfer_extension 은 폴백만.
"""

import time
import structlog
from src.ai_voicebot.langgraph.hitl_escalation_policy import (
    suppress_hitl_low_confidence,
    suppress_hitl_needs_followup,
)
from src.ai_voicebot.langgraph.state import ConversationState

logger = structlog.get_logger(__name__)

HITL_CONFIDENCE_THRESHOLD = 0.15  # RAG similarity_threshold=0.35 기준 최저 confidence ~0.16 수준에 맞춤
MAX_LOW_CONFIDENCE_TURNS = 2  # 연속 낮은 신뢰도 N회 시 HITL


async def _get_escalation_mode(state: ConversationState) -> tuple[str, str | None]:
    """Persona 설정에서 escalation_mode, (레거시) transfer_extension을 읽어 반환.

    Returns:
        (escalation_mode, transfer_extension_legacy)
        escalation_mode: "hitl" | "transfer" | "none"
    """
    owner = state.get("_owner") or state.get("_persona_owner") or ""
    if not owner:
        return "hitl", None
    try:
        from src.ai_voicebot.knowledge.persona_service import get_persona_service

        svc = get_persona_service()
        if not svc:
            return "hitl", None
        persona = await svc.get_persona(owner)
        if not persona:
            return "hitl", None
        mode = (getattr(persona, "escalation_mode", "hitl") or "hitl").strip().lower()
        if mode not in ("hitl", "transfer", "none"):
            mode = "hitl"
        ext = getattr(persona, "transfer_extension", None)
        return mode, ext
    except Exception as e:
        logger.debug("hitl_alert_escalation_mode_lookup_failed", owner=owner, error=str(e))
        return "hitl", None


def _resolve_call_control_transfer_extension(state: ConversationState) -> tuple[str | None, str]:
    """착신 규칙 기반 전환 내선. (extension, reason_code)"""
    try:
        from src.call_control.escalation_transfer import (
            build_escalation_sip_context,
            resolve_escalation_transfer_extension,
        )

        callee = (state.get("_owner") or state.get("_persona_owner") or "").strip()
        caller = (state.get("_caller_number") or "").strip() or None
        reg, busy_fn = build_escalation_sip_context()
        ext, reason = resolve_escalation_transfer_extension(
            callee,
            caller,
            registered_extensions=reg,
            is_extension_busy=busy_fn,
        )
        if ext:
            logger.info(
                "hitl_escalation_call_control_target",
                callee=callee,
                caller=caller,
                extension=ext,
                reason=reason,
            )
        else:
            logger.warning(
                "hitl_escalation_call_control_unresolved",
                callee=callee,
                caller=caller,
                reason=reason,
            )
        return ext, reason
    except Exception as e:
        logger.warning("hitl_escalation_call_control_error", error=str(e))
        return None, "resolver_exception"


async def hitl_alert_node(state: ConversationState) -> dict:
    """
    운영자 개입 판단.

    escalation_mode:
      - "hitl"     : needs_human=True (대시보드 알림, 기존 동작)
      - "transfer" : needs_human=True + needs_transfer=True (SIP 호전환 트리거)
      - "none"     : intent != "transfer" 인 한 AI 판정 HITL/호전환 억제
    """
    _start = time.time()
    intent = state.get("intent", "")
    confidence = state.get("confidence", 1.0)
    needs_follow_up = state.get("needs_follow_up", False)
    domain_signal = state.get("domain_question_signal", False)
    lane = state.get("utterance_lane", "knowledge")
    needs_human = False
    reason = ""

    # 0. 모르는 내용 응답 시 → HITL (억제 대상 제외)
    if needs_follow_up:
        if suppress_hitl_needs_followup(state):
            logger.info(
                "hitl_suppressed_needs_follow_up",
                intent=intent,
                utterance_lane=lane,
                domain_question_signal=domain_signal,
                confidence=f"{confidence:.3f}",
            )
        else:
            needs_human = True
            reason = "AI가 모르는 내용으로 응답했습니다. 확인이 필요합니다."

    # 1. 직접 요청
    elif intent == "transfer":
        needs_human = True
        reason = "고객이 상담원 연결을 요청했습니다."

    # 2. 불만 + 낮은 신뢰도
    elif intent == "complaint" and confidence < 0.5:
        needs_human = True
        reason = f"고객 불만 상태이며 답변 신뢰도가 낮습니다 (confidence={confidence:.2f})."

    # 3. 극도로 낮은 신뢰도 (잡담·소셜·비도메인 question 제외)
    elif confidence < HITL_CONFIDENCE_THRESHOLD:
        if suppress_hitl_low_confidence(state):
            logger.info(
                "hitl_suppressed_low_confidence",
                intent=intent,
                utterance_lane=lane,
                domain_question_signal=domain_signal,
                confidence=f"{confidence:.3f}",
            )
        elif intent == "question" and not domain_signal:
            logger.info(
                "hitl_suppressed_light_question_low_confidence",
                confidence=f"{confidence:.3f}",
            )
        else:
            needs_human = True
            reason = f"답변 신뢰도가 매우 낮습니다 (confidence={confidence:.2f}). 적절한 정보를 찾지 못했습니다."

    needs_transfer = False
    transfer_extension: str | None = None
    escalation_mode = "hitl"
    legacy_ext: str | None = None
    cc_reason = ""

    if needs_human:
        escalation_mode, legacy_ext = await _get_escalation_mode(state)
        cc_ext, cc_reason = _resolve_call_control_transfer_extension(state)
        transfer_extension = (cc_ext or (legacy_ext or "").strip() or None) or None

        if escalation_mode == "none" and intent != "transfer":
            logger.info(
                "hitl_suppressed_escalation_none",
                intent=intent,
                reason=reason,
                note="AI 에스컬레이션 없음 모드 — 명시적 상담원 요청(transfer) 제외",
            )
            needs_human = False
            needs_transfer = False
            transfer_extension = None
        else:
            needs_transfer = escalation_mode == "transfer"
            if needs_transfer and not transfer_extension:
                logger.warning(
                    "hitl_escalation_transfer_no_extension",
                    escalation_mode=escalation_mode,
                    call_control_reason=cc_reason,
                    legacy_ext=legacy_ext,
                    note="착신 규칙·레거시 내선 모두 없어 호전환 비활성",
                )
                needs_transfer = False
            if needs_human:
                logger.warning(
                    "hitl_alert_triggered",
                    call=True,
                    intent=intent,
                    confidence=f"{confidence:.3f}",
                    needs_follow_up=needs_follow_up,
                    utterance_lane=lane,
                    domain_question_signal=domain_signal,
                    reason=reason,
                    escalation_mode=escalation_mode,
                    needs_transfer=needs_transfer,
                    transfer_extension=transfer_extension,
                    call_control_reason=cc_reason,
                )
    else:
        logger.debug(
            "hitl_not_needed",
            intent=intent,
            confidence=f"{confidence:.3f}",
            utterance_lane=lane,
        )

    elapsed = time.time() - _start
    logger.info("timing_segment", segment="hitl_alert", elapsed_sec=round(elapsed, 3), needs_human=needs_human)
    result: dict = {
        "needs_human": needs_human,
        "hitl_reason": reason,
        "needs_transfer": needs_transfer,
    }
    if transfer_extension:
        result["transfer_extension"] = transfer_extension
    return result
