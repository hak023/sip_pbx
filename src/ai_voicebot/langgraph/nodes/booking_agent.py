"""
예약 에이전트 노드.

LLM + BOOKING_TOOLS를 bind하여 function calling 루프 실행.

개선 사항 (2026-04-09):
  - P1-1: booking_context.messages 로 발화 간 대화 히스토리 유지
  - P1-2: SystemMessage에 오늘 날짜(요일) 명시 주입 → 자연어 날짜 파싱 정확도 향상
  - P2-1: create_booking_tool 호출 시 call_id 자동 주입
  - P2-2: LLM 호출 전 발신자 전화번호로 미래 예약 사전 검색 → 컨텍스트로 제공
  - P2-3: update_booking_tool / search_my_bookings 추가
  - P3-1: send_booking_sms Tool 추가 (예약 변동 시 LLM이 자동 호출)
  - C-3: 발신번호·현재시각·과거 통화 이력 요약 시스템 컨텍스트 자동 주입
         create_booking_tool 호출 시 customer_phone 자동 적용 (되묻지 않음)

상태 I/O:
  입력: user_query, _llm_client, _owner, _call_id, _caller_number, booking_context
  출력: response, intent="booking", business_state, booking_context(업데이트)
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import structlog

from src.ai_voicebot.langgraph.state import ConversationState
from src.ai_voicebot.langgraph.call_context import get_llm_client, get_rag_engine
from src.common.call_data_record_logger import log_call_data

logger = structlog.get_logger(__name__)


def _booking_tool_result_ok(tool_result: str) -> bool:
    try:
        parsed = json.loads(tool_result)
        return "error" not in parsed
    except Exception:
        return "error" not in (tool_result or "").lower()[:120]


# 발화 간 히스토리 최대 보관 메시지 수 (시스템 메시지 제외)
_MAX_HISTORY_MESSAGES = 20

# 최대 tool call 반복 횟수 (무한루프 방지) — 복잡한 tool 체인 대비 8로 확장
_MAX_TOOL_ROUNDS = 8

# owner 파라미터가 필요한 Tool 이름
_OWNER_TOOLS = {
    "check_available_slots", "_check_available_slots",
    "check_multi_date_slots", "_check_multi_date_slots",
    "create_booking_tool", "_create_booking",
    "get_booking_settings", "_get_booking_settings",
    "get_business_hours_tool", "_get_business_hours",
    "search_my_bookings", "_search_my_bookings",
    "get_call_context_tool", "_get_call_context",
    "search_knowledge_tool", "_search_knowledge",
}

# bind_tools 미지원 시 텍스트 폴백 전용 — 길이 제한 내 JSON·도구 형식 출력 유도 방지
_BOOKING_TEXT_FALLBACK_SYSTEM = """당신은 전화 음성 AI 예약 안내원입니다.
반드시 고객이 들을 자연스러운 한국어 문장만 말하세요.
JSON, 마크다운(```), 코드, tool_calls, 키-값 나열 형식은 사용하지 마세요."""

_BOOKING_SYSTEM_PROMPT = """당신은 AI 예약 도우미입니다.
사용자의 예약 요청을 처리하기 위해 제공된 도구(tool)를 사용하세요.

## 예약 신규 생성 절차

기본 수집 필드: slot_date(날짜), slot_time(시각), customer_name(이름), customer_phone(전화번호), party_size(인원).

### 정보 수집 규칙 (중요)
- 고객이 한 발화에서 여러 정보를 동시에 제공하면 **모두 한꺼번에 파악**하여 저장하세요.
  예) "홍길동 010-1111-2222입니다" → customer_name="홍길동", customer_phone="010-1111-2222" 동시 수집
- **이미 수집된 필드는 다시 묻지 마세요.** 대화 히스토리에서 확인하세요.
- **누락된 필드가 있으면 한 번에 한 가지만 질문**하세요. 여러 개를 한꺼번에 묻지 마세요.
- **발신자 전화번호가 시스템에 제공되어 있으면 customer_phone을 되묻지 말고 바로 그 번호를 사용하세요.**

### get_booking_settings 결과 반영 규칙 (중요)
get_booking_settings를 호출하면 아래 필드가 반환됩니다. 반드시 따르세요.
- `require_phone: false` → customer_phone을 묻지 마세요 (발신자 번호도 불필요).
- `require_name: false` → customer_name을 묻지 마세요.
- `domain_extra_fields` 배열: 도메인별 추가 수집 필드 목록.
  - `required: true`인 항목은 create_booking_tool 호출 전 **반드시** 고객에게 확인하세요.
  - `required: false`인 항목은 선택 사항이므로 자연스럽게 물어볼 수 있습니다.
  - 수집한 값은 create_booking_tool의 `extra_data` 파라미터에 `{"field_key": 값}` 형태로 전달하세요.
  - `field_type: select`인 항목은 `options` 목록을 고객에게 안내하세요.
- `schema_extra_fields` 배열: 테넌트 공통 추가 필드 (`required: true`이면 필수 수집).

### 수집 순서 (권장)
1. 날짜/시간 → 2. 인원 → 3. (도메인 추가 필드 required 항목) → 4. 이름 → 5. 예약 생성

### 처리 절차
1. get_booking_settings로 서비스 설정 확인 (최초 1회)
2. 날짜/시간 언급 시 check_available_slots로 가용 슬롯 확인
3. 모든 필수 필드가 수집되면 **예약 생성 전 반드시 확인 발화** (아래 STT 오류 방지 규칙 참고)
4. 고객이 확인하면 create_booking_tool로 예약 생성

### STT 오류 방지 — 예약 생성 전 필수 확인 절차 (중요)
전화 음성인식(STT)은 날짜·시간·이름·인원을 잘못 인식할 수 있습니다.
create_booking_tool을 호출하기 **직전에 반드시** 아래 형식으로 수집 정보를 읽어주고 고객의 확인을 받으세요.

**확인 발화 형식 (예시):**
> "확인해 드리겠습니다. [날짜] [시간], [인원]명, 성함은 [이름]으로 예약 진행할까요?"

**규칙:**
- 고객이 "네", "맞아요", "그렇게 해 주세요" 등 긍정 답변 → 즉시 create_booking_tool 호출
- 고객이 "아니요", "틀렸어요", "날짜가 달라요" 등 정정 요청 → 해당 필드만 다시 수집 후 재확인
- 예약 변경(reschedule), 취소(cancel), 인원 변경(update)도 동일하게 실행 전 확인 발화 필수
- 확인 발화는 1회만 하세요. 이미 확인한 후에는 재확인하지 마세요.

### 영업시간 안내 규칙 (2단계 조회)
고객이 영업시간·운영시간·휴무일을 물어보면 다음 순서로 처리하세요.

1단계: get_business_hours_tool 호출
  - `found: true` → 반환된 시간 정보로 안내
  - `linked_to_slots: false` → "참고용 정보입니다. 실제 예약 가능 시간은 슬롯을 확인해 드릴게요"
  - `found: false` → 2단계로 진행

2단계: get_business_hours_tool이 `found: false`이면 search_knowledge_tool(query="영업시간") 호출
  - KB 검색 결과가 있으면 그 내용으로 안내
  - KB 검색 결과도 없으면 "정확한 영업시간은 매장에 직접 문의 부탁드립니다"로 안내

## 일정 변경(reschedule) 절차
**날짜·시간 변경은 반드시 reschedule_booking_tool을 사용하세요. update_booking_tool로 날짜·시간을 변경하면 슬롯 정원 데이터가 깨집니다.**

1. [발신자 미래 예약 목록]에서 booking_id 확인
2. 변경할 날짜/시간 수집 → check_available_slots로 가용 여부 확인
3. **실행 전 확인 발화**: "예약번호 [ID]를 [새날짜] [새시간]으로 변경할까요?"
4. 고객 확인 후 reschedule_booking_tool(booking_id, new_slot_date, new_slot_time) 호출 (원자적 처리)

## 취소 절차
1. 발신자 번호 기준 기존 예약이 [발신자 미래 예약 목록]에 있으면 booking_id 확인
2. booking_id가 없으면 search_my_bookings 호출
3. 예약이 여러 건이면 어느 예약을 취소할지 고객에게 명확히 확인 후 진행
4. **실행 전 확인 발화**: "[날짜] [시간] 예약을 취소할까요?"
5. 고객 확인 후 cancel_booking_tool 호출

## 수정 절차 (인원·메모 변경 전용)
**update_booking_tool은 인원(party_size)과 메모(memo) 변경 전용입니다.**
**날짜·시간 변경은 반드시 위 "일정 변경(reschedule) 절차"를 따르세요.**

1. [발신자 미래 예약 목록]에서 booking_id 확인
2. 변경할 인원 또는 메모 확인
3. **실행 전 확인 발화**: "인원을 [N]명으로 변경할까요?" (정정 허용)
4. 고객 확인 후 update_booking_tool 호출

## 조회 절차
- [발신자 미래 예약 목록]에 이미 제공됨 → Tool 호출 없이 바로 안내 가능
- 과거 예약 조회 요청("지난 예약", "이전 예약") → search_my_bookings(include_past=true) 호출

## 복수 날짜 조회
- "이번 주 언제 가능해요?" → check_multi_date_slots(start_date, end_date) 1회 호출

## 슬롯 없는 날짜 처리 (중요)
고객이 요청한 날짜에 가용 슬롯이 없으면 다음 절차를 따르세요.
1. check_multi_date_slots(start_date=요청날짜, end_date=요청날짜+7일) 로 인접 1주일 가용 날짜 즉시 조회
2. 가용 날짜가 있으면: "해당 날짜는 예약이 어렵습니다. [가용 날짜]는 가능합니다. 어느 날짜가 좋으세요?" 로 안내
3. 인접 1주일도 없으면: "현재 해당 날짜 전후로 예약 가능한 시간이 없습니다. 다른 날짜를 알려주시면 확인해 드리겠습니다."

## 혼합 질문 처리
- 예약 외 서비스 정보 질문 → search_knowledge_tool 호출

## 응답 원칙
- 자연스러운 한국어로 응답하세요.
- 날짜는 YYYY-MM-DD, 시각은 HH:MM 형식을 사용하세요.
- 예약 완료 후 예약번호를 명확히 안내하세요.
- create_booking_tool 성공 응답의 ``confirmation_message``는 서버가 동시에 보낸 SIP 확인 문자(동일 문구)입니다. 음성 안내 시 그 내용을 빠짐없이 또는 자연스럽게 포함하세요.
- 한 번의 응답에서 **한 가지 질문만** 하세요.
- 이미 알고 있는 정보(히스토리에 있는 정보)는 재확인하지 마세요.
"""


async def booking_agent_node(state: ConversationState) -> dict:
    """
    예약 의도 처리 에이전트 노드.

    LLM + BOOKING_TOOLS function calling 루프:
      0. 발신자 전화번호로 미래 예약 사전 검색 → 컨텍스트 구성
      1. 이전 발화 히스토리 + 오늘 날짜 포함 SystemMessage 구성
      2. LLM tool_call 루프 (최대 _MAX_TOOL_ROUNDS 회)
      3. booking_context.messages 업데이트 → 다음 발화에 전달
    """
    node_start = time.time()

    user_query = state.get("user_query", "").strip()
    owner = state.get("_owner", "")
    call_id = state.get("_call_id", "")
    caller_number = state.get("_caller_number", "")  # 발신자 전화번호
    llm_client = get_llm_client()

    # booking_context에서 이전 히스토리 복원
    booking_context: Dict[str, Any] = dict(state.get("booking_context") or {})
    prev_messages: List[Any] = booking_context.get("messages", [])

    # 라우팅 검증: booking_agent_node에 올바르게 도달했는지 확인
    utterance_lane = state.get("utterance_lane", "")
    intent = state.get("intent", "")
    logger.info(
        "booking_agent_node_enter",
        call_id=call_id,
        owner=owner,
        caller_number=caller_number,
        query_preview=user_query[:60],
        history_count=len(prev_messages),
        routing_check_utterance_lane=utterance_lane,
        routing_check_intent=intent,
        routing_ok=(utterance_lane == "booking" and intent == "booking"),
    )

    # langchain_core 가용성 확인
    try:
        from langchain_core.messages import (
            HumanMessage, AIMessage, ToolMessage, SystemMessage
        )
        _langchain_ok = True
    except ImportError:
        _langchain_ok = False

    if not _langchain_ok or llm_client is None:
        logger.warning(
            "booking_agent_fallback",
            reason="langchain_core_unavailable" if not _langchain_ok else "no_llm_client",
        )
        return {
            "response": "예약 서비스에 연결할 수 없습니다. 잠시 후 다시 시도해주세요.",
            "intent": "booking",
            "business_state": "booking_error",
            "booking_context": booking_context,
        }

    from src.ai_voicebot.langgraph.tools.booking_tools import BOOKING_TOOLS, _RAG_ENGINE_CONTEXT

    raw_llm = getattr(llm_client, "_chat_model", None) or getattr(llm_client, "chat_model", None)
    llm_with_tools = None
    if raw_llm is not None:
        try:
            llm_with_tools = raw_llm.bind_tools(BOOKING_TOOLS)
        except Exception as e:
            logger.warning("booking_agent_bind_tools_failed", call_id=call_id, error=str(e))
            llm_with_tools = None

    gemini_fc_model = None
    if llm_with_tools is None:
        try:
            from src.ai_voicebot.langgraph.booking_gemini_fc import (
                build_booking_generative_model,
                _langchain_tools_to_glm_tool,
            )

            gemini_fc_model = build_booking_generative_model(
                llm_client, _langchain_tools_to_glm_tool(BOOKING_TOOLS)
            )
            logger.info(
                "booking_agent_gemini_native_fc",
                call_id=call_id,
                note="LangChain bind_tools 없음 또는 실패 시 Gemini 네이티브 function calling",
            )
        except Exception as e:
            logger.warning(
                "booking_agent_gemini_fc_init_failed",
                call_id=call_id,
                error=str(e),
            )
            gemini_fc_model = None

    if llm_with_tools is None and gemini_fc_model is None:
        logger.warning(
            "booking_agent_no_tool_model",
            call_id=call_id,
            llm_client_type=type(llm_client).__name__ if llm_client is not None else "None",
            message="도구 바인딩·Gemini FC 초기화 모두 실패 — 텍스트 폴백",
        )
        return await _fallback_text_booking(
            llm_client, user_query, owner, call_id, booking_context, node_start
        )

    # ── RAG 엔진 컨텍스트 주입: search_knowledge_tool이 파이프라인 인스턴스 재사용 ──
    # ContextVar는 asyncio Task 단위로 격리되므로 동시 통화 간 간섭 없음.
    rag_engine = get_rag_engine()
    _rag_ctx_token = _RAG_ENGINE_CONTEXT.set(rag_engine)

    # ── 오늘 날짜 및 현재 시각 구성 ──
    now_dt = datetime.now()
    today_str = now_dt.strftime("%Y-%m-%d")
    weekday_kr = ["월", "화", "수", "목", "금", "토", "일"][now_dt.weekday()]
    now_time_str = now_dt.strftime("%H:%M")

    # ── 발신자 미래 예약 사전 검색 (컨텍스트 주입용) ──
    caller_bookings_context = ""
    if caller_number:
        try:
            from src.services.booking_service import search_bookings_by_phone
            future_bookings = search_bookings_by_phone(owner, caller_number, include_past=False, limit=5)
            if future_bookings:
                lines = []
                for b in future_bookings:
                    lines.append(
                        f"  - 예약번호:{b['booking_id']} / {b['slot_date']} {b['slot_time']} / "
                        f"{b['customer_name']} {b['party_size']}명 / 상태:{b['status']}"
                    )
                caller_bookings_context = (
                    f"\n[발신자({caller_number}) 미래 예약 목록]\n" + "\n".join(lines)
                )
                logger.info(
                    "booking_agent_preloaded_bookings",
                    call_id=call_id,
                    caller=caller_number,
                    count=len(future_bookings),
                )
            else:
                caller_bookings_context = f"\n[발신자({caller_number}) 미래 예약 없음]"
        except Exception as e:
            logger.warning("booking_agent_preload_failed", error=str(e))

    # ── 과거 통화 이력 요약 (C-3: 이전 통화 맥락 주입) ──
    call_history_context = ""
    if caller_number and call_id:
        try:
            from src.common.call_history_reader import read_call_history_from_logs
            histories = read_call_history_from_logs(limit=200)
            # 현재 call_id 제외, 같은 발신자 통화 이력 최대 3건
            past_calls = [
                h for h in histories
                if h.get("call_id") != call_id and (
                    h.get("callee") == owner or
                    any(
                        turn.get("stt", {}).get("text", "")
                        for turn in h.get("detail", {}).get("turns", [])
                    )
                )
            ][:3]
            if past_calls:
                lines = []
                for h in past_calls:
                    started = (h.get("started_at") or "")[:16]
                    summary = h.get("content", "")[:150].replace("\n", " ")
                    lines.append(f"  - [{started}] {summary}")
                call_history_context = "\n[이전 통화 이력 요약]\n" + "\n".join(lines)
                logger.info(
                    "booking_agent_call_history_injected",
                    call_id=call_id,
                    caller=caller_number,
                    history_count=len(past_calls),
                )
        except Exception as e:
            logger.warning("booking_agent_call_history_failed", error=str(e))

    # ── 수집된 슬롯 필드 현황 구성 (LLM에게 "이미 알고 있는 것" 명시) ──
    collected_slots = booking_context.get("collected_slots", {})

    # ── 서비스 설정 캐시 로드 (get_booking_settings 결과를 booking_context에 보존) ──
    # 동일 통화 내에서 반복 DB 조회를 피하기 위해 첫 번째 조회 결과를 캐싱한다.
    settings_cache: dict = booking_context.get("settings_cache") or {}
    settings_hint = _format_settings_hint(settings_cache)
    collected_summary = _format_collected_slots(collected_slots, caller_number, settings_cache)

    # ── SystemMessage 구성 ──
    caller_phone_note = (
        f"\n발신자 전화번호: {caller_number} ← 이 번호를 customer_phone으로 자동 사용하세요. 되묻지 마세요."
        if caller_number
        else "\n발신자 전화번호: 미확인 (고객에게 직접 확인 필요)"
    )
    system_content = (
        f"{_BOOKING_SYSTEM_PROMPT}"
        f"\n---\n오늘 날짜: {today_str} ({weekday_kr}요일), 현재 시각: {now_time_str}"
        f"{caller_phone_note}"
        f"\nowner: {owner}"
        f"{settings_hint}"
        f"{caller_bookings_context}"
        f"{call_history_context}"
        f"{collected_summary}"
    )

    # ── 메시지 구성: 시스템 + 이전 히스토리 + 현재 발화 ──
    # 이전 히스토리는 SystemMessage 제외하고 최대 _MAX_HISTORY_MESSAGES개만 유지
    trimmed_prev = prev_messages[-_MAX_HISTORY_MESSAGES:] if len(prev_messages) > _MAX_HISTORY_MESSAGES else prev_messages

    messages: List[Any] = [
        SystemMessage(content=system_content),
        *trimmed_prev,
        HumanMessage(content=user_query),
    ]

    final_response = ""
    sms_sent_this_turn = False
    _fc_gen_cfg = llm_client._effective_generation_config(2048)

    for round_idx in range(_MAX_TOOL_ROUNDS):
        try:
            if llm_with_tools is not None:
                ai_msg = await llm_with_tools.ainvoke(messages)
            else:
                from src.ai_voicebot.langgraph.booking_gemini_fc import (
                    _candidate_function_calls,
                    _candidate_text,
                    invoke_booking_model_with_gemini_fc,
                )

                assert gemini_fc_model is not None
                resp = await invoke_booking_model_with_gemini_fc(
                    gen_model=gemini_fc_model,
                    lc_messages=messages,
                    generation_config=_fc_gen_cfg,
                )
                pf = getattr(resp, "prompt_feedback", None)
                br = getattr(pf, "block_reason", None) if pf else None
                if br:
                    logger.warning(
                        "booking_gemini_fc_prompt_blocked",
                        call_id=call_id,
                        block_reason=str(br),
                    )
                    ai_msg = AIMessage(
                        content="예약 안내를 이어가기 어렵습니다. 잠시 후 다시 말씀해 주세요."
                    )
                else:
                    calls = _candidate_function_calls(resp)
                    extra_text = _candidate_text(resp)
                    if calls:
                        ai_msg = AIMessage(
                            content=extra_text or "",
                            tool_calls=[
                                {"name": n, "args": a, "id": cid}
                                for n, a, cid in calls
                            ],
                        )
                    else:
                        ai_msg = AIMessage(content=extra_text or "")
        except Exception as e:
            _tail = messages[-4:] if len(messages) >= 4 else messages
            _roles = [type(m).__name__ for m in _tail]
            logger.error(
                "booking_agent_llm_invoke_error",
                call_id=call_id,
                round=round_idx,
                error=str(e),
                error_type=type(e).__name__,
                recent_message_types=_roles,
                note=(
                    "Gemini FC generate_content 실패 — Struct 직렬화·HTTP/gRPC 등. "
                    "recent_message_types로 ToolMessage 직후 재호출 여부 상관."
                ),
            )
            break

        messages.append(ai_msg)

        tool_calls = getattr(ai_msg, "tool_calls", None) or []
        if not tool_calls:
            final_response = getattr(ai_msg, "content", "") or ""
            logger.info(
                "booking_agent_final_response",
                call_id=call_id,
                round=round_idx,
                response_len=len(final_response),
            )
            break

        logger.info(
            "booking_agent_tool_calls",
            call_id=call_id,
            round=round_idx,
            tools=[tc["name"] for tc in tool_calls],
        )

        for tc in tool_calls:
            tool_name = tc.get("name", "")
            tool_args = dict(tc.get("args", {}))
            tool_call_id = tc.get("id", f"call_{round_idx}")

            # owner 자동 주입
            if tool_name in _OWNER_TOOLS and "owner" not in tool_args:
                tool_args["owner"] = owner

            # call_id / customer_phone 자동 주입 (create_booking_tool)
            if tool_name in {"create_booking_tool", "_create_booking"}:
                if not tool_args.get("call_id") and call_id:
                    tool_args["call_id"] = call_id
                # 발신자 번호를 customer_phone으로 자동 주입 (되묻지 않음)
                if not tool_args.get("customer_phone") and caller_number:
                    tool_args["customer_phone"] = caller_number
                    logger.info(
                        "booking_agent_auto_phone",
                        call_id=call_id,
                        caller_number=caller_number,
                        note="customer_phone 자동 주입",
                    )

            # get_call_context_tool: call_id 자동 주입
            if tool_name in {"get_call_context_tool", "_get_call_context"}:
                if not tool_args.get("call_id") and call_id:
                    tool_args["call_id"] = call_id

            if call_id:
                log_call_data(
                    call_id,
                    "booking",
                    "booking_tool_start",
                    tool=tool_name,
                    arg_keys=list(tool_args.keys()),
                    round_idx=round_idx,
                )
            _t_tool = time.perf_counter()
            tool_result = _execute_tool(tool_name, tool_args)
            _dur_ms = int((time.perf_counter() - _t_tool) * 1000)
            _ok = _booking_tool_result_ok(str(tool_result))
            _summary = (str(tool_result) or "")[:240]
            if call_id:
                log_call_data(
                    call_id,
                    "booking",
                    "booking_tool_done",
                    tool=tool_name,
                    duration_ms=_dur_ms,
                    ok=_ok,
                    result_summary=_summary,
                    round_idx=round_idx,
                )
            logger.info(
                "booking_tool_executed",
                call_id=call_id,
                tool_name=tool_name,
                args_keys=list(tool_args.keys()),
                result_preview=str(tool_result)[:120],
            )

            # get_booking_settings 결과를 settings_cache에 보존 (동일 통화 내 재사용)
            if tool_name in {"get_booking_settings", "_get_booking_settings"}:
                try:
                    parsed = json.loads(tool_result)
                    if "error" not in parsed:
                        settings_cache = parsed
                        booking_context["settings_cache"] = settings_cache
                        logger.info(
                            "booking_agent_settings_cached",
                            call_id=call_id,
                            require_phone=parsed.get("require_phone"),
                            require_name=parsed.get("require_name"),
                            domain_extra_count=len(parsed.get("domain_extra_fields", [])),
                            schema_extra_count=len(parsed.get("schema_extra_fields", [])),
                        )
                except Exception:
                    pass

            # 예약 액션 결과를 booking_context에 기록 (통화 종료 SMS·프롬프트는 last_booking_api 우선)
            _BOOKING_ACTION_MAP = {
                "create_booking_tool": "create",
                "_create_booking": "create",
                "cancel_booking_tool": "cancel",
                "_cancel_booking": "cancel",
                "update_booking_tool": "update",
                "_update_booking": "update",
                "reschedule_booking_tool": "update",
                "_reschedule_booking": "update",
            }
            if tool_name in _BOOKING_ACTION_MAP:
                action = _BOOKING_ACTION_MAP[tool_name]
                try:
                    result_data = json.loads(tool_result)
                except Exception as parse_err:
                    booking_context["last_booking_api"] = {
                        "action": action,
                        "ok": False,
                        "detail": f"도구 결과 파싱 실패: {parse_err}"[:300],
                        "booking_id": None,
                    }
                    logger.warning(
                        "booking_action_api_parse_failed",
                        call_id=call_id,
                        tool_name=tool_name,
                        error=str(parse_err),
                    )
                else:
                    api_ok = bool(result_data.get("success"))
                    detail = ""
                    for k in ("message", "error", "detail", "reason", "code"):
                        v = result_data.get(k)
                        if v is not None and str(v).strip():
                            detail = str(v).strip()[:400]
                            break
                    booking_context["last_booking_api"] = {
                        "action": action,
                        "ok": api_ok,
                        "detail": detail,
                        "booking_id": result_data.get("booking_id"),
                    }
                    if api_ok:
                        booking_context["last_action"] = action
                        booking_context["last_booking"] = result_data
                        logger.info(
                            "booking_action_recorded",
                            call_id=call_id,
                            action=booking_context["last_action"],
                            booking_id=result_data.get("booking_id"),
                        )
                    else:
                        logger.info(
                            "booking_action_api_failed",
                            call_id=call_id,
                            action=action,
                            detail_preview=detail[:120] if detail else "",
                        )

            messages.append(
                ToolMessage(
                    content=str(tool_result),
                    tool_call_id=tool_call_id,
                    name=tool_name or "",
                )
            )
    else:
        logger.warning("booking_agent_max_rounds_exceeded", call_id=call_id)
        if call_id:
            log_call_data(
                call_id,
                "booking",
                "booking_rejected",
                reason_code="max_tool_rounds",
                detail="LLM tool loop exceeded max rounds without final text",
            )

    if not final_response:
        final_response = "예약 처리 중 문제가 발생했습니다. 담당자에게 연결하겠습니다."

    # ── 히스토리 업데이트 (SystemMessage 제외하고 저장) ──
    history_to_save = [m for m in messages if not isinstance(m, SystemMessage)]
    if len(history_to_save) > _MAX_HISTORY_MESSAGES:
        history_to_save = history_to_save[-_MAX_HISTORY_MESSAGES:]
    booking_context["messages"] = history_to_save

    # ── 수집된 슬롯 필드 업데이트 (Tool 호출 args에서 추출) ──
    updated_slots = _extract_collected_slots_from_messages(messages, collected_slots)
    if updated_slots:
        booking_context["collected_slots"] = updated_slots

    # 멀턴 예약 유지: 체크포인트에 LangChain message 직렬화가 불완전해도 classify·휴리스틱이
    # booking_active 를 판별할 수 있도록 JSON 친화 플래그를 둔다.
    if booking_context.get("last_action") in ("create", "cancel"):
        booking_context["booking_flow_active"] = False
    else:
        booking_context["booking_flow_active"] = True

    elapsed = time.time() - node_start
    logger.info(
        "booking_agent_node_complete",
        call_id=call_id,
        elapsed_sec=round(elapsed, 3),
        response_len=len(final_response),
        sms_sent=sms_sent_this_turn,
        rag_engine_injected=rag_engine is not None,
    )

    # ContextVar 정리 (다음 노드/태스크로의 누수 방지)
    _RAG_ENGINE_CONTEXT.reset(_rag_ctx_token)

    return {
        "response": final_response,
        "intent": "booking",
        "business_state": "booking_handled",
        "confidence": 1.0,
        "booking_context": booking_context,
    }


def _format_settings_hint(settings_cache: dict) -> str:
    """
    settings_cache(get_booking_settings 결과)를 SystemMessage용 수집 정책 텍스트로 포맷.

    require_phone/require_name 설정과 도메인·스키마 추가 필드를 LLM에 명시한다.
    settings_cache가 비어 있으면(아직 미조회) 빈 문자열 반환.
    """
    if not settings_cache:
        return ""

    lines = ["\n[서비스 설정 기반 수집 정책]"]

    require_phone = settings_cache.get("require_phone", True)
    require_name = settings_cache.get("require_name", True)
    lines.append(f"  - 전화번호 수집 필요: {'예' if require_phone else '아니오 (묻지 마세요)'}")
    lines.append(f"  - 이름 수집 필요: {'예' if require_name else '아니오 (묻지 마세요)'}")

    domain_extras: list = settings_cache.get("domain_extra_fields", [])
    schema_extras: list = settings_cache.get("schema_extra_fields", [])
    all_extras = domain_extras + schema_extras
    required_extras = [f for f in all_extras if f.get("required")]
    optional_extras = [f for f in all_extras if not f.get("required")]

    if required_extras:
        lines.append("  - 추가 필수 수집 필드:")
        for f in required_extras:
            opts_str = f" (선택지: {', '.join(f['options'])})" if f.get("options") else ""
            dom_label = f" [{f['domain_name']}]" if f.get("domain_name") else ""
            lines.append(f"    * {f['field_label']}{dom_label} (key={f['field_key']}, type={f['field_type']}){opts_str}")
    if optional_extras:
        lines.append("  - 추가 선택 수집 필드:")
        for f in optional_extras:
            opts_str = f" (선택지: {', '.join(f['options'])})" if f.get("options") else ""
            dom_label = f" [{f['domain_name']}]" if f.get("domain_name") else ""
            lines.append(f"    * {f['field_label']}{dom_label} (key={f['field_key']}, type={f['field_type']}){opts_str}")

    if not all_extras:
        lines.append("  - 도메인 추가 수집 필드: 없음")

    return "\n".join(lines)


def _format_collected_slots(collected: dict, caller_number: str, settings_cache: Optional[dict] = None) -> str:
    """
    현재까지 수집된 예약 필드를 SystemMessage용 텍스트로 포맷.

    settings_cache가 있으면 require_phone/require_name 설정을 반영하여
    LLM이 "이미 알고 있는 정보"와 "아직 모르는 정보"를 명확히 파악하도록 돕는다.
    """
    if not collected and not caller_number:
        return ""

    sc = settings_cache or {}
    require_phone = sc.get("require_phone", True)
    require_name = sc.get("require_name", True)

    lines = ["\n[현재까지 수집된 예약 정보]"]
    field_labels = {
        "slot_date": "날짜",
        "slot_time": "시각",
        "customer_name": "이름",
        "customer_phone": "전화번호",
        "party_size": "인원",
        "service_type": "서비스 종류",
    }

    # 설정에 따라 실제 수집해야 할 기본 필드 목록 결정
    base_required = ["slot_date", "slot_time", "party_size"]
    if require_name:
        base_required.append("customer_name")
    if require_phone:
        base_required.append("customer_phone")

    for field in base_required:
        label = field_labels.get(field, field)
        val = collected.get(field)
        if field == "customer_phone" and not val and caller_number and require_phone:
            val = f"{caller_number} (발신자 번호 자동 적용)"
        if val:
            lines.append(f"  ✓ {label}: {val}")
        else:
            lines.append(f"  ✗ {label}: 미수집")

    # 도메인·스키마 추가 필드 수집 현황
    all_extras: list = (sc.get("domain_extra_fields") or []) + (sc.get("schema_extra_fields") or [])
    extra_data: dict = collected.get("extra_data") or {}
    for f in all_extras:
        if not f.get("required"):
            continue
        key = f.get("field_key", "")
        label = f.get("field_label", key)
        val = extra_data.get(key)
        if val:
            lines.append(f"  ✓ {label}: {val}")
        else:
            lines.append(f"  ✗ {label}: 미수집 (필수)")

    # 미수집 필드 요약
    missing = [
        field_labels.get(f, f) for f in base_required
        if not collected.get(f) and not (f == "customer_phone" and caller_number and require_phone)
    ]
    missing += [
        f.get("field_label", f.get("field_key", ""))
        for f in all_extras
        if f.get("required") and not (collected.get("extra_data") or {}).get(f.get("field_key", ""))
    ]
    if missing:
        lines.append(f"  → 아직 필요한 정보: {', '.join(missing)}")
    else:
        lines.append("  → 모든 필수 정보 수집 완료 (create_booking_tool 호출 가능)")

    return "\n".join(lines)


def _extract_collected_slots_from_messages(messages: list, current: dict) -> dict:
    """
    Tool 호출 args(AIMessage.tool_calls)에서 수집된 예약 필드를 추출.

    LLM이 create_booking_tool을 호출했다면 해당 args에서 필드를 가져온다.
    부분 수집된 경우 이전 current와 병합한다.
    extra_data(도메인 추가 필드)도 병합한다.
    """
    updated = dict(current)
    target_fields = {"slot_date", "slot_time", "customer_name", "customer_phone", "party_size", "service_type"}

    for msg in messages:
        tool_calls = getattr(msg, "tool_calls", None) or []
        for tc in tool_calls:
            name = tc.get("name", "")
            args = tc.get("args", {})
            if name in {"create_booking_tool", "_create_booking"}:
                for field in target_fields:
                    if args.get(field):
                        updated[field] = args[field]
                # extra_data(도메인 추가 필드) 병합
                extra = args.get("extra_data")
                if isinstance(extra, dict) and extra:
                    existing_extra = dict(updated.get("extra_data") or {})
                    existing_extra.update(extra)
                    updated["extra_data"] = existing_extra

    return updated


def _execute_tool(tool_name: str, args: dict) -> str:
    """도구 이름으로 BOOKING_TOOLS에서 찾아 동기 실행."""
    from src.ai_voicebot.langgraph.tools.booking_tools import BOOKING_TOOLS

    for t in BOOKING_TOOLS:
        name = getattr(t, "name", None) or getattr(t, "__name__", "")
        if name == tool_name:
            try:
                return t.invoke(args) if hasattr(t, "invoke") else t(**args)
            except Exception as e:
                return json.dumps({"error": str(e)}, ensure_ascii=False)

    return json.dumps({"error": f"알 수 없는 도구: {tool_name}"}, ensure_ascii=False)


async def _fallback_text_booking(
    llm_client,
    user_query: str,
    owner: str,
    call_id: str,
    booking_context: Dict[str, Any],
    node_start: float,
) -> dict:
    """LangChain bind_tools 미지원 시 단순 LLM 텍스트 응답 폴백."""
    import time
    from src.services.booking_service import get_settings, list_slots

    settings = get_settings(owner) or {}
    service_name = settings.get("service_name", "예약 서비스")

    today = date.today().strftime("%Y-%m-%d")
    slots = list_slots(owner, slot_date=today, include_full=False)
    slot_text = "\n".join(
        f"- {s['slot_time']} (잔여: {s['available']}석)" for s in slots
    ) if slots else "오늘 예약 가능한 슬롯 없음"

    prompt = (
        f"당신은 {service_name} AI 예약 도우미입니다.\n"
        f"오늘 날짜: {today}\n"
        f"[오늘 예약 가능 시간대]\n{slot_text}\n\n"
        f"고객: {user_query}\n\n"
        "자연스러운 한국어로 예약 관련 안내 또는 처리 안내를 해주세요."
    )
    try:
        response = await llm_client.generate_response(
            prompt,
            context_docs=[],
            system_prompt=_BOOKING_TEXT_FALLBACK_SYSTEM,
            max_output_tokens=1024,
        )
    except Exception as e:
        logger.error("booking_fallback_llm_error", error=str(e))
        response = "예약 서비스 처리 중 오류가 발생했습니다."

    elapsed = time.time() - node_start
    logger.info("booking_agent_fallback_complete", call_id=call_id, elapsed_sec=round(elapsed, 3))
    booking_context = dict(booking_context or {})
    booking_context["booking_flow_active"] = True
    return {
        "response": response or "예약 처리 중 문제가 발생했습니다.",
        "intent": "booking",
        "business_state": "booking_handled",
        "confidence": 0.8,
        "booking_context": booking_context,
    }
