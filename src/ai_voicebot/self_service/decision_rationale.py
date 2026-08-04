"""
IntelliDecision 판단 근거 투명성 — 비동기 캡처 (Story 1.21, FR30/NFR6).

Story 1.20 스파이크(docs/reports/2026-07/2026-07-29_story_1.20_intellidecision_rationale_capture_spike.md)
검증 결과에 따라 채택된 방식: **사용자 응답 전송 후 비동기 백그라운드로 별도 경량 분류 호출**.

- 구조화 출력(response_schema)+FunctionCall 동시 요청은 Gemini API가 명시적으로 거부함(400).
- 센티널 태그 후행 파싱은 15회 중 성공 0회(0%)로 신뢰성 부족.
- 별도 분류 호출은 유일하게 동작하나 동기 호출 시 0.7~0.9초 추가 지연 — 따라서 사용자 응답
  경로를 전혀 기다리지 않는 `asyncio.create_task()` 백그라운드 실행으로 변형해 채택했다.

이 모듈은 **판단 로직(self_service_agent.py의 응답 생성)에는 절대 관여하지 않는다** — 순수
관측·로깅 전용이며, 실패해도 예외를 이 안에서 완전히 흡수해 호출부(백그라운드 태스크)에
전파하지 않는다(Story 7.1의 Smart Turn 관측 로깅과 동일한 안전 패턴).
"""

from __future__ import annotations

import asyncio
import re
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

# 근거 요약 프롬프트에 노출할 유형 요약 문자열(코드+이름). 지연 최소화를 위해 상세 트리거
# 예시는 생략한다(intellidecision_policy.py의 전체 메타데이터가 아니라 코드/이름만 필요).
_CLASSIFY_MAX_OUTPUT_TOKENS = 120

_RESULT_LINE_PATTERN = re.compile(
    r"유형\s*[:：]?\s*([A-I])\s*[\r\n]+\s*요약\s*[:：]?\s*(.+)", re.IGNORECASE | re.DOTALL
)


def _build_classification_prompt(user_query: str, ai_response: str) -> str:
    from src.ai_voicebot.self_service.intellidecision_policy import list_intent_types

    type_lines = "\n".join(f"- {spec.code}: {spec.name}" for spec in list_intent_types())
    return (
        "아래는 셀프서비스 AI 도우미의 한 턴(사용자 발화 + AI 응답)이다. "
        "이 상호작용이 IntelliDecision 유형 중 어디에 해당하는지 판단하라.\n\n"
        f"[유형 목록]\n{type_lines}\n\n"
        f"[사용자 발화]\n{user_query}\n\n"
        f"[AI 응답]\n{ai_response}\n\n"
        "반드시 아래 형식 그대로 정확히 두 줄로만 답하라(다른 설명 금지):\n"
        "유형: <A~I 중 정확히 1글자>\n"
        "요약: <이 판단의 근거를 10~30자 한국어로 요약>"
    )


def _parse_classification_result(text: str) -> tuple[str, str]:
    """분류 응답 텍스트에서 (matched_type, reasoning_summary)를 파싱한다.

    파싱 실패 시 ("unknown", "")를 반환한다 — 절대 예외를 던지지 않는다.
    """
    if not text:
        return "unknown", ""
    m = _RESULT_LINE_PATTERN.search(text)
    if not m:
        return "unknown", ""
    code = m.group(1).strip().upper()
    summary = m.group(2).strip().splitlines()[0].strip() if m.group(2) else ""
    if code not in "ABCDEFGHI":
        return "unknown", summary
    return code, summary


async def _capture_and_log(
    *,
    user_query: str,
    ai_response: str,
    owner: str,
    call_id: str,
) -> tuple[str, str]:
    """실제 캡처 로직. 반드시 이 함수 내에서 모든 예외를 흡수해야 한다.

    `(matched_type, reasoning_summary)`를 반환한다 — `schedule_rationale_capture()`의
    fire-and-forget 호출부는 이 반환값을 무시하고, Story 1.27 응답 시뮬레이터는 이 함수를
    직접 `await`해 반환값을 그대로 API 응답에 싣는다(판정 로직 자체는 무변경, 호출 방식만 분기).
    """
    matched_type = "unknown"
    reasoning_summary = ""
    try:
        from src.ai_voicebot.langgraph.call_context import get_llm_client

        llm_client = get_llm_client()
        prompt = _build_classification_prompt(user_query, ai_response)
        raw = await llm_client.generate_response(
            user_text=prompt,
            context_docs=[],
            system_prompt=None,
            call_id=call_id or None,
            max_output_tokens=_CLASSIFY_MAX_OUTPUT_TOKENS,
            update_history=False,  # 내부 전용 호출 — conversation_history 오염 방지(2026-07-29 교훈)
        )
        matched_type, reasoning_summary = _parse_classification_result(raw or "")
    except Exception as exc:  # noqa: BLE001 - 백그라운드 관측 태스크는 어떤 예외도 흡수해야 한다
        logger.warning(
            "self_service_intellidecision_rationale_capture_failed",
            call_id=call_id, owner=owner, error=str(exc),
        )
        matched_type, reasoning_summary = "unknown", ""

    try:
        from src.common.self_service_decision_log_db import record_decision_rationale

        record_decision_rationale(
            owner=owner,
            call_id=call_id,
            matched_type=matched_type,
            reasoning_summary=reasoning_summary,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "self_service_intellidecision_rationale_db_write_failed",
            call_id=call_id, owner=owner, error=str(exc),
        )

    try:
        from src.common.call_data_record_logger import log_call_data

        if call_id:
            log_call_data(
                call_id, "self_service", "self_service_intellidecision_rationale",
                owner=owner, matched_type=matched_type, reasoning_summary=reasoning_summary,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "self_service_intellidecision_rationale_call_data_log_failed",
            call_id=call_id, owner=owner, error=str(exc),
        )

    return matched_type, reasoning_summary


def schedule_rationale_capture(
    *,
    user_query: str,
    ai_response: str,
    owner: str,
    call_id: str,
) -> Optional[asyncio.Task]:
    """판단 근거 캡처를 비동기 백그라운드 태스크로 예약한다(호출부는 절대 await하지 않는다).

    이 함수 자체도 태스크 생성 실패(예: 실행 중인 이벤트 루프가 없는 극히 예외적인 상황)를
    흡수해 None을 반환한다 — 셀프서비스 응답 경로가 이 기능으로 인해 예외를 겪는 일은 없다.
    """
    if not owner:
        return None
    try:
        task = asyncio.create_task(
            _capture_and_log(
                user_query=user_query, ai_response=ai_response, owner=owner, call_id=call_id,
            )
        )
        return task
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "self_service_intellidecision_rationale_schedule_failed",
            call_id=call_id, owner=owner, error=str(exc),
        )
        return None
