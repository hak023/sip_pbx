"""
Query Transformation 노드.

짧은 쿼리(<5단어) 또는 대명사 포함 시 LLM으로 구어체 -> 검색 쿼리 변환.
"""

from datetime import datetime
import time

import structlog
from src.ai_voicebot.langgraph.state import ConversationState
from src.common.call_data_record_logger import log_call_data

logger = structlog.get_logger(__name__)


def _log_rewrite_timing(
    call_id: str,
    *,
    elapsed_sec: float,
    path: str,
    query_preview: str = "",
    rewritten_preview: str = "",
) -> None:
    if not call_id:
        return
    log_call_data(
        call_id,
        "timing",
        "rewrite_query",
        elapsed_sec=round(elapsed_sec, 3),
        path=path,
        query_preview=(query_preview or ""),
        rewritten_preview=(rewritten_preview or ""),
    )

# 대명사 및 모호 표현 패턴
AMBIGUOUS_PATTERNS = [
    "이거", "그거", "저거", "뭐", "아까", "그때", "거기",
    "때 ",  # '기상청에 갈 때 어떻게' → STT가 '때 어떻게…'만 넘기는 경우
]

REWRITE_PROMPT = """다음 고객의 구어체 발화를 검색에 적합한 문장으로 변환하세요.

대화 기록:
{history}

현재 발화: "{query}"

변환 규칙:
1. 대명사를 구체적인 명사로 대체
2. 구어체를 문어체로 변환
3. 핵심 의도를 명확하게 표현
4. 한 문장으로만 출력

변환된 검색 쿼리:"""


async def rewrite_query_node(state: ConversationState) -> dict:
    """
    사용자 발화를 검색에 적합한 쿼리로 변환.
    
    필요 조건 (OR):
    - 5단어 미만의 짧은 쿼리
    - 대명사/모호 표현 포함
    
    불필요 시 원본 쿼리 그대로 사용.
    """
    _start = time.time()
    call_id = state.get("_call_id") or ""

    query = state.get("user_query", "").strip()
    if not query:
        elapsed = time.time() - _start
        logger.info("timing_segment", segment="rewrite_query", elapsed_sec=round(elapsed, 3), skip="no_query")
        _log_rewrite_timing(call_id, elapsed_sec=elapsed, path="skip_no_query", query_preview=query)
        return {"rewritten_query": query}

    # classify_intent에서 이미 rewritten_query가 세팅되었으면 LLM 재호출 스킵 (최적화 4.4)
    # existing_rewrite가 원본과 동일해도 의미 있는 변환이 없다는 뜻이므로 스킵 처리.
    existing_rewrite = state.get("rewritten_query", "").strip()
    if existing_rewrite:
        elapsed = time.time() - _start
        logger.info("timing_segment", segment="rewrite_query", elapsed_sec=round(elapsed, 3), skip="already_rewritten")
        logger.info("rewrite_query_skip_merged",
                    original=query, rewritten=existing_rewrite,
                    same_as_original=(existing_rewrite == query),
                    note="classify_intent LLM 병합 호출 결과 재사용 — rewrite LLM 스킵")
        _log_rewrite_timing(call_id, elapsed_sec=elapsed, path="skip_merged",
                           query_preview=query, rewritten_preview=existing_rewrite)
        return {"rewritten_query": existing_rewrite}

    words = query.split()
    needs_rewrite = (
        len(words) < 5
        or any(p in query for p in AMBIGUOUS_PATTERNS)
    )

    if not needs_rewrite:
        elapsed = time.time() - _start
        logger.info("timing_segment", segment="rewrite_query", elapsed_sec=round(elapsed, 3), skip=True)
        logger.debug("query_rewrite_skipped", query=query)
        _log_rewrite_timing(call_id, elapsed_sec=elapsed, path="skip_not_needed", query_preview=query)
        return {"rewritten_query": query}

    llm = state.get("_llm_client")
    if not llm:
        elapsed = time.time() - _start
        logger.info("timing_segment", segment="rewrite_query", elapsed_sec=round(elapsed, 3), skip="no_llm")
        _log_rewrite_timing(call_id, elapsed_sec=elapsed, path="skip_no_llm", query_preview=query)
        return {"rewritten_query": query}

    try:
        # 최근 대화 3턴 포맷
        messages = state.get("messages", [])
        history = _format_recent(messages, max_turns=3)

        prompt = REWRITE_PROMPT.format(history=history, query=query)
        request_sent_at = datetime.now().isoformat()
        logger.info("llm_request_sent",
                    call_site="rewrite_query",
                    request_sent_ts_iso=request_sent_at,
                    prompt_len=len(prompt),
                    prompt_preview=prompt.replace("\n", " "))
        try:
            # update_history=False: 쿼리 재작성은 사용자에게 들려주지 않는 내부 호출 —
            # conversation_history 오염 방지(2026-07-29, classify_intent와 동일 근본 원인 수정).
            rewritten = await llm.generate_response(
                prompt,
                context_docs=[],
                system_prompt="쿼리 변환기",
                max_output_tokens=256,
                update_history=False,
            )
        except Exception as llm_err:
            elapsed_err = time.time() - _start
            logger.warning("llm_request_failed",
                           call_site="rewrite_query",
                           request_sent_ts_iso=request_sent_at,
                           error_type=type(llm_err).__name__,
                           error_msg=str(llm_err),
                           elapsed_ms=round(elapsed_err * 1000))
            raise  # outer except가 원본 쿼리로 폴백 처리
        response_received_at = datetime.now().isoformat()
        rewritten = (rewritten or "").strip().strip('"').strip("'")
        elapsed = time.time() - _start
        logger.info("llm_response_received",
                    call_site="rewrite_query",
                    request_sent_ts_iso=request_sent_at,
                    response_received_ts_iso=response_received_at,
                    elapsed_ms=round(elapsed * 1000))

        # LLM이 API 오류 시 에러 문구를 반환한 경우 → 원본 쿼리 유지 (검색에 쓰면 안 됨)
        if _is_error_message(rewritten):
            logger.info("timing_segment", segment="rewrite_query", elapsed_sec=round(elapsed, 3), path="llm_error_msg")
            logger.warning("query_rewrite_llm_error_used_original", original=query)
            _log_rewrite_timing(
                call_id, elapsed_sec=elapsed, path="llm_error_msg", query_preview=query
            )
            return {"rewritten_query": query}

        if rewritten and len(rewritten) > 2:
            logger.info("timing_segment", segment="rewrite_query", elapsed_sec=round(elapsed, 3), path="llm")
            logger.info("⏱️ [TIMING] rewrite_query (LLM)",
                       original=query, rewritten=rewritten,
                       elapsed=f"{elapsed:.3f}s")
            _log_rewrite_timing(
                call_id,
                elapsed_sec=elapsed,
                path="llm",
                query_preview=query,
                rewritten_preview=rewritten,
            )
            return {"rewritten_query": rewritten}
    except Exception as e:
        elapsed = time.time() - _start
        logger.info("timing_segment", segment="rewrite_query", elapsed_sec=round(elapsed, 3), path="error", error=str(e))
        logger.warning("query_rewrite_error", error=str(e))
        _log_rewrite_timing(call_id, elapsed_sec=elapsed, path="error", query_preview=query)

    elapsed = time.time() - _start
    logger.info("timing_segment", segment="rewrite_query", elapsed_sec=round(elapsed, 3), path="fallback")
    _log_rewrite_timing(call_id, elapsed_sec=elapsed, path="fallback", query_preview=query)
    return {"rewritten_query": query}


def _is_error_message(text: str) -> bool:
    """LLM이 반환한 문자열이 오류 메시지인지 (검색 쿼리로 쓰면 안 됨)."""
    if not text or len(text) > 200:
        return False
    t = text.strip()
    return (
        "오류가 발생했습니다" in t
        or "답변을 생성하는 중 오류" in t
        or (t.startswith("죄송합니다") and "오류" in t)
    )


def _format_recent(messages: list, max_turns: int = 3) -> str:
    recent = messages[-(max_turns * 2):]
    lines = []
    for msg in recent:
        role = "사용자" if msg.get("role") == "user" else "AI"
        lines.append(f"{role}: {msg.get('content', '')}")
    return "\n".join(lines) if lines else "(첫 대화)"
