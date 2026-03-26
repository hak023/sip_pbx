"""
응답 생성 노드.

RAG 컨텍스트 + 대화 기록 + 시스템 프롬프트 → LLM → 응답.
Streaming RAG: 첫 문장이 완성되면 즉시 response_chunks에 추가.
"""

import time
from datetime import datetime

import structlog
from src.ai_voicebot.langgraph.state import ConversationState
from src.common.rag_hit_serializer import build_rag_hits_llm_context
from src.common.call_data_record_logger import log_call_data

logger = structlog.get_logger(__name__)


def _llm_exchange_rag_fields(
    state: ConversationState,
    rag_results: list,
    *,
    context_source: str,
) -> dict:
    """llm_exchange / call_data_record용: 프롬프트에 넣은 압축 RAG 스니펫 + 검색 trace."""
    trace = state.get("rag_search_trace") or {}
    return {
        "llm_rag_applied": build_rag_hits_llm_context(rag_results or [], max_items=8),
        "llm_rag_context_source": context_source,
        "rag_search_trace": trace,
    }

# 모르는 내용일 때 사용할 고정 멘트 (설계: TTS_RTP_AND_HITL_DESIGN.md — "잠시만 기다려 주세요" 후 HITL)
RESPONSE_UNKNOWN_NEEDS_FOLLOWUP = "해당 내용은 확인이 필요합니다. 잠시만 기다려 주세요."

# 질문(intent=question) + 이번 턴 RAG 검색 결과 없음 → 고정 멘트 후 HITL
RESPONSE_QUESTION_NO_KNOWLEDGE = "죄송합니다. 해당 내용은 제가 알지 못하는 내용입니다."


# 설계 §13.2: 장문 대화 맥락 유지를 위해 8턴
HISTORY_MAX_TURNS = 8

RESPONSE_SYSTEM_PROMPT = """당신은 {org_name}의 AI 통화 비서입니다.

기관 정보:
{org_context}

{stage_and_summary}
대화 기록:
{history}

검색된 참고 정보:
{rag_context}

응답 규칙:
1. 한국어로 자연스럽게 대화하세요 (구어체).
2. 검색된 정보를 바탕으로 정확하게 답하세요.
3. 모르는 내용일 때는 반드시 아래 문장만 사용하세요. 지어내지 마세요.
   "해당 내용은 확인이 필요합니다. 잠시만 기다려 주세요."
4. 2~3문장 이내로 간결하게 답하세요 (통화이므로 길면 안 됩니다).
5. 문장은 반드시 마침표(.) 또는 물음표(?)로 끝내세요. 중간에 끊기지 마세요.
6. 고객이 불편을 호소하면 공감하고 해결 방안을 제시하세요.
7. "더 도움이 필요하시면 말씀해 주세요" 같은 안내로 마무리하세요.
8. 사용자 질문을 그대로 반복하거나 인용하지 마세요. "○○ 말씀하셨죠" 같은 확인 멘트 없이 바로 답변으로 들어가세요.
{chitchat_rule}
"""


async def generate_response_node(state: ConversationState) -> dict:
    """
    LLM 응답 생성.
    
    입력:
      - user_query, rewritten_query
      - rag_results (Adaptive RAG 결과)
      - messages (대화 기록)
      - org_context, system_prompt
      
    출력:
      - response: 전체 응답 텍스트
      - response_chunks: 스트리밍용 청크 리스트
    """
    llm = state.get("_llm_client")
    user_query = state.get("user_query", "")

    if not llm or not user_query:
        return {
            "response": "죄송합니다. 잠시 후 다시 시도해 주세요.",
            "confidence": 0.0,
            **_llm_exchange_rag_fields(state, state.get("rag_results") or [], context_source="skipped_no_llm_input"),
        }

    intent = state.get("intent", "")
    rag_results = state.get("rag_results") or []

    # 질문으로 분류되었고 이번 턴 지식 검색 결과가 없으면 LLM 생략 → 고정 멘트 + HITL 후속
    if intent == "question" and not rag_results:
        response = RESPONSE_QUESTION_NO_KNOWLEDGE
        messages = state.get("messages", [])
        updated_messages = list(messages)
        updated_messages.append({
            "role": "user",
            "content": user_query,
            "timestamp": datetime.now().isoformat(),
        })
        updated_messages.append({
            "role": "assistant",
            "content": response,
            "timestamp": datetime.now().isoformat(),
        })
        chunks = _split_into_chunks(response)
        logger.info(
            "generate_response_question_no_rag",
            intent=intent,
            response_len=len(response),
            note="RAG 0건 → 고정 멘트, needs_follow_up",
        )
        return {
            "response": response,
            "response_chunks": chunks,
            "messages": updated_messages,
            "confidence": 0.0,
            "needs_follow_up": True,
            "follow_up_user_query": user_query,
            **_llm_exchange_rag_fields(state, [], context_source="question_no_knowledge"),
        }

    start = time.time()

    try:
        # 컨텍스트 조립 (§13.2 history 8턴, §4.3 chitchat 짧은 응답)
        rag_context = _format_rag_context(rag_results)
        messages = state.get("messages", [])
        history = _format_history(messages, max_turns=HISTORY_MAX_TURNS)
        org_context = state.get("org_context", "")
        org_name = _extract_org_name(org_context)
        chitchat_rule = ""
        if intent in ("chitchat", "greeting"):
            chitchat_rule = "9. [지금은 일상 말걸기/인사입니다] 1~2문장으로 짧게 공감·안내만 하세요. 길게 설명하지 마세요."

        # 설계 §14.2: 대화 단계·요약을 프롬프트에 주입
        stage_and_summary = _format_stage_and_summary(state)

        system_prompt = RESPONSE_SYSTEM_PROMPT.format(
            org_name=org_name,
            org_context=org_context,
            stage_and_summary=stage_and_summary,
            history=history,
            rag_context=rag_context or "(관련 정보 없음)",
            chitchat_rule=chitchat_rule,
        )

        # LLM 호출 (요청/응답 시각 로그 — 지연·재시도 원인 추적용)
        request_sent_at = datetime.now().isoformat()
        logger.info("llm_request_sent",
                    call_site="generate_response",
                    request_sent_ts_iso=request_sent_at,
                    prompt_len=len(system_prompt) + len(user_query),
                    prompt_preview=user_query)
        try:
            response = await llm.generate_response(
                user_text=user_query,
                context_docs=[rag_context] if rag_context else [],
                system_prompt=system_prompt,
            )
        except Exception as llm_err:
            elapsed_err = time.time() - start
            logger.warning("llm_request_failed",
                           call_site="generate_response",
                           request_sent_ts_iso=request_sent_at,
                           error_type=type(llm_err).__name__,
                           error_msg=str(llm_err),
                           elapsed_ms=round(elapsed_err * 1000))
            raise
        response_received_at = datetime.now().isoformat()

        needs_follow_up = False
        if not response or not response.strip():
            response = "죄송합니다. 답변을 생성하지 못했습니다. 다시 말씀해 주시겠어요?"
        # API 오류 등으로 LLM이 에러 문구를 반환한 경우 → 모르는 내용 고정 응답 + 후처리 플래그
        elif _is_llm_error_fallback(response):
            logger.warning("generate_response_llm_error_fallback", response_preview=response)
            response = RESPONSE_UNKNOWN_NEEDS_FOLLOWUP
            needs_follow_up = True
        # 응답이 모르는 내용 유도 문구와 유사하면 후처리 플래그 (LLM이 규칙 3을 따른 경우)
        elif _is_unknown_content_response(response):
            needs_follow_up = True

        elapsed = time.time() - start
        logger.info("llm_response_received",
                    call_site="generate_response",
                    request_sent_ts_iso=request_sent_at,
                    response_received_ts_iso=response_received_at,
                    elapsed_ms=round(elapsed * 1000),
                    response_len=len(response))

        # Streaming: 문장 단위 청크 분리
        chunks = _split_into_chunks(response)

        logger.info("timing_segment", segment="generate_response", elapsed_sec=round(elapsed, 3))
        logger.info("⏱️ [TIMING] generate_response (LLM 호출)",
                   query=user_query,
                   response_len=len(response),
                   chunks=len(chunks),
                   llm_elapsed=f"{elapsed:.3f}s")

        call_id = state.get("_call_id") or ""
        if call_id:
            log_call_data(
                call_id,
                "timing",
                "llm_generate_response",
                elapsed_sec=round(elapsed, 3),
                intent=intent,
                rag_hit_count=len(rag_results or []),
                response_len=len(response),
            )

        # 대화 기록 업데이트
        updated_messages = list(messages)
        updated_messages.append({
            "role": "user",
            "content": user_query,
            "timestamp": datetime.now().isoformat(),
        })
        updated_messages.append({
            "role": "assistant",
            "content": response,
            "timestamp": datetime.now().isoformat(),
        })

        # Confidence: greeting/chitchat 경로는 adaptive_rag를 타지 않으므로 0.9 고정 (§4.3)
        if intent in ("greeting", "chitchat"):
            confidence = 0.9
        else:
            confidence = state.get("confidence", 0.0)  # From adaptive_rag or step_back

        # llm_exchange는 rag_processor에서 통화 단위로 기록 (중복 방지)
        _rag_src = "vector_knowledge" if rag_results else "llm_prompt_no_reference"

        return {
            "response": response,
            "response_chunks": chunks,
            "messages": updated_messages,
            "confidence": confidence,
            "needs_follow_up": needs_follow_up,
            "follow_up_user_query": user_query if needs_follow_up else "",
            **_llm_exchange_rag_fields(state, rag_results, context_source=_rag_src),
        }

    except Exception as e:
        elapsed = time.time() - start
        logger.info("timing_segment", segment="generate_response", elapsed_sec=round(elapsed, 3), error=str(e))
        logger.error("response_generation_error", error=str(e), exc_info=True)
        return {
            "response": RESPONSE_UNKNOWN_NEEDS_FOLLOWUP,
            "confidence": 0.0,
            "needs_follow_up": True,
            "follow_up_user_query": user_query if user_query else "",
            **_llm_exchange_rag_fields(state, rag_results, context_source="llm_generation_error"),
        }


def _is_llm_error_fallback(text: str) -> bool:
    """LLM/API 오류로 반환된 문구인지 여부 (쿼리/응답으로 쓰면 안 되는 문자열)."""
    if not text or len(text) > 200:
        return False
    t = text.strip()
    return (
        "오류가 발생했습니다" in t
        or "답변을 생성하는 중 오류" in t
        or (t.startswith("죄송합니다") and "오류" in t)
    )


def _is_unknown_content_response(text: str) -> bool:
    """모르는 내용/확인 필요 문구인지 여부 (후처리·HITL 유도). 설계: 잠시만 기다려 주세요 + HITL."""
    if not text or len(text) < 10:
        return False
    t = text.strip()
    if RESPONSE_QUESTION_NO_KNOWLEDGE in t or (
        "알지 못하는 내용" in t and "죄송" in t
    ):
        return True
    if "잠시만 기다려" in t and "확인" in t:
        return True
    return (
        "모르는 내용" in t
        and ("확인이 필요" in t or "확인 후" in t or "연락드리면" in t)
    )


def _format_rag_context(results: list) -> str:
    if not results:
        return ""
    lines = []
    for i, doc in enumerate(results, 1):
        text = doc.get("text", "") if isinstance(doc, dict) else str(doc)
        if text:
            lines.append(f"[{i}] {text}")
    return "\n".join(lines)


def _format_history(messages: list, max_turns: int = 6) -> str:
    recent = messages[-(max_turns * 2):]
    lines = []
    for msg in recent:
        role = "사용자" if msg.get("role") == "user" else "AI"
        lines.append(f"{role}: {msg.get('content', '')}")
    return "\n".join(lines) if lines else "(첫 대화)"


def _extract_org_name(org_context: str) -> str:
    """기관 이름 추출"""
    for line in org_context.split("\n"):
        if "기관명" in line or "이름" in line:
            parts = line.split(":")
            if len(parts) >= 2:
                return parts[1].strip()
    return "AI 비서"


# 설계 §14.2: 대화 단계 레이블 (intent + business_state 기반)
CONVERSATION_STAGE_MAP = {
    "initial": {"greeting": "상담 시작", "question": "질문 응답 중", "complaint": "불만 접수", "transfer": "전환 요청", "farewell": "마무리 인사"},
    "inquiry": {"greeting": "상담 재개", "question": "질문 응답 중", "complaint": "불만 대응 중", "transfer": "전환 요청", "farewell": "마무리 인사"},
    "resolution": {"greeting": "상담 재개", "question": "추가 질문 응답", "complaint": "불만 대응 중", "transfer": "전환 요청", "farewell": "마무리 인사"},
    "closing": {"greeting": "상담 재개", "question": "질문 응답 중", "complaint": "불만 대응 중", "transfer": "전환 진행", "farewell": "마무리 인사"},
}
DEFAULT_STAGE = "상담 중"


def _get_conversation_stage(state: dict) -> str:
    """비즈니스 상태 + intent로 대화 단계 레이블 반환. 설계 §14.2."""
    business = state.get("business_state", "initial")
    intent = state.get("intent", "question")
    by_state = CONVERSATION_STAGE_MAP.get(business, CONVERSATION_STAGE_MAP["inquiry"])
    stage = by_state.get(intent)
    if stage:
        return stage
    if intent in ("affirm", "deny", "gratitude", "doubt", "positive_reaction", "negative_reaction"):
        return "반응/피드백 처리"
    if intent in ("repeat", "clarification", "help"):
        return "제어(반복·명확화·도움)"
    if intent in ("chitchat",):
        return "일상 대화"
    if intent in ("out_of_scope", "nlu_fallback"):
        return "범위 외 발화"
    return DEFAULT_STAGE


def _get_conversation_summary(messages: list, current_query: str, max_chars: int = 180) -> str:
    """최근 고객 발화 2건 요약 (규칙 기반). 설계 §14.2."""
    if not messages and not current_query:
        return "(첫 발화)"
    user_texts = [m.get("content", "") for m in messages if m.get("role") == "user"]
    if current_query and (not user_texts or user_texts[-1] != current_query):
        user_texts.append(current_query)
    recent = user_texts[-2:] if len(user_texts) >= 2 else user_texts
    combined = " / ".join(s.strip() for s in recent if s.strip())
    if len(combined) > max_chars:
        combined = combined[: max_chars - 3] + "..."
    return combined or "(첫 발화)"


def _format_stage_and_summary(state: dict) -> str:
    """프롬프트용 '현재 대화 단계' + '대화 요약' 블록."""
    stage = _get_conversation_stage(state)
    messages = state.get("messages", [])
    query = state.get("user_query", "")
    summary = _get_conversation_summary(messages, query)
    return f"현재 대화 단계: {stage}\n최근 화제(요약): {summary}\n\n"


def _split_into_chunks(text: str) -> list:
    """
    문장 단위 청크 분리 (Streaming RAG TTS용).
    """
    if not text:
        return []
    # 마침표, 물음표, 느낌표, 쉼표+공백으로 분리
    import re
    sentences = re.split(r'(?<=[.?!])\s+', text)
    return [s.strip() for s in sentences if s.strip()]
