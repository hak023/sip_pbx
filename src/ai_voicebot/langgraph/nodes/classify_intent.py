"""
의도 분류 노드.

사용자 발화에서 의도(intent)를 분류한다.
설계: docs/design/AI_RESPONSE_HUMANLIKE_DESIGN.md — 확장 Intent 택소노미.
가능한 의도: greeting, farewell, affirm, deny, gratitude, doubt, positive_reaction,
negative_reaction, chitchat, repeat, clarification, help, question, complaint,
transfer, out_of_scope, nlu_fallback
"""

from datetime import datetime

import structlog
from src.ai_voicebot.langgraph.state import ConversationState
from src.ai_voicebot.ai_pipeline.query_hints import should_treat_as_question_not_transfer
from src.common.call_data_record_logger import log_call_data

logger = structlog.get_logger(__name__)


def _log_intent_classify_timing(
    call_id: str,
    *,
    elapsed_sec: float,
    path: str,
    intent: str,
    query_preview: str = "",
) -> None:
    if not call_id:
        return
    log_call_data(
        call_id,
        "timing",
        "intent_classify",
        elapsed_sec=round(elapsed_sec, 3),
        path=path,
        intent=intent,
        query_preview=(query_preview or ""),
    )

# 키워드 기반 빠른 분류 (LLM 호출 없이). 설계 §8.2 키워드 예시 반영
INTENT_KEYWORDS = {
    "greeting": ["안녕", "여보세요", "반갑", "처음"],
    "farewell": ["감사합니다", "고마워", "끊을게", "그만", "종료", "바이바이", "끊을게요"],
    "complaint": ["불만", "화나", "짜증", "항의", "문제가", "왜 이래"],
    "transfer": ["사람", "담당자", "직원", "연결해", "상담원", "전화 돌려", "연결해 줘"],
    # B. 반응/피드백
    "affirm": ["네", "예", "넹", "응", "좋아요", "좋습니다", "됐어요", "됐습니다", "알겠어요", "알겠습니다", "그럴게요"],
    "deny": ["아니요", "아니에요", "아니", "필요 없어요", "취소할게요", "그만할게요"],
    "gratitude": ["감사해요", "고마워요", "감사합니다", "고맙습니다"],
    "doubt": ["글쎄요", "아마", "잘 모르겠어요", "몰라요"],
    "positive_reaction": ["좋아요", "맘에 들어요", "좋네요"],
    "negative_reaction": ["별로예요", "안 좋아요", "그냥요"],
    # C. 일상/제어
    "repeat": ["다시", "다시 말해", "뭐라고", "한번 더", "못 들었어요", "다시 말해줘"],
    "clarification": ["무슨 뜻이에요", "뭔 소리야", "이해가 안 가요", "어느 부분이요"],
    "help": [
        "도와줘",
        "도움",
        "어떻게 해요",
        "어떻게 하죠",
        "뭘 할 수 있어요",
        "어떤 일",
        "할 수 있어",
        "할수있어",
        "무엇을 할",
        "뭐 할 수",
    ],
}

# 인사말과 함께 나올 수 있는 질문/요청 패턴. 이 패턴이 있으면 greeting보다 question 우선.
QUESTION_PATTERNS = [
    "어떻게", "문의", "알려", "되나요", "인가요", "뭐", "무엇", "있어요",
    "해요", "해주", "하고 싶", "알고 싶", "궁금", "주차", "예약", "영업",
    "시간", "가격", "비용", "위치", "연락처", "예약", "취소",
]

def _format_recent_for_intent(messages: list, max_turns: int = 2) -> str:
    """의도 분류용: 최근 max_turns턴( user+assistant )을 텍스트로. 설계 §13.2."""
    if not messages:
        return ""
    recent = messages[-(max_turns * 2) :]
    lines = []
    for m in recent:
        role = "고객" if m.get("role") == "user" else "AI"
        lines.append(f"{role}: {m.get('content', '')}")
    return "\n".join(lines)


# 설계 §2.2 확장 valid_intents (라우팅·LLM 분류용)
VALID_INTENTS = {
    "greeting", "farewell",
    "affirm", "deny", "gratitude", "doubt", "positive_reaction", "negative_reaction",
    "chitchat", "repeat", "clarification", "help",
    "question", "complaint", "transfer",
    "out_of_scope", "nlu_fallback",
}


async def classify_intent_node(state: ConversationState) -> dict:
    """
    사용자 발화의 의도를 분류.
    
    1차: 키워드 기반 빠른 매칭 (<1ms)
    2차: 인사+질문 동시 존재 시 question 우선 (짧은 인사만 greeting)
    3차: LLM 기반 분류 (키워드 매칭 실패 시)
    """
    import time
    node_start = time.time()
    
    call_id = state.get("_call_id") or ""

    query = state.get("user_query", "").strip()
    if not query:
        elapsed = time.time() - node_start
        _log_intent_classify_timing(
            call_id, elapsed_sec=elapsed, path="empty_query", intent="nlu_fallback"
        )
        return {"intent": "nlu_fallback", "slots": {}, "confidence": 0.0}

    query_lower = query.lower()

    # 1차: 키워드 기반 빠른 분류 (farewell 우선: "감사합니다" 등 → farewell)
    for intent, keywords in INTENT_KEYWORDS.items():
        if any(kw in query_lower for kw in keywords):
            # 인사(greeting)인데 질문/요청 패턴도 있으면 → question으로 처리 (RAG 경로 타서 본문 답변)
            if intent == "greeting" and any(p in query_lower for p in QUESTION_PATTERNS):
                elapsed = time.time() - node_start
                logger.info("timing_segment", segment="classify_intent", elapsed_sec=round(elapsed, 3), path="keyword")
                logger.info("⏱️ [TIMING] classify_intent (keyword, greeting+question→question)",
                           intent="question", query=query, elapsed=f"{elapsed:.3f}s")
                _log_intent_classify_timing(
                    call_id, elapsed_sec=elapsed, path="keyword_greeting_to_question", intent="question", query_preview=query
                )
                return {"intent": "question", "slots": {}, "confidence": 1.0}
            elapsed = time.time() - node_start
            logger.info("timing_segment", segment="classify_intent", elapsed_sec=round(elapsed, 3), path="keyword")
            logger.info("⏱️ [TIMING] classify_intent (keyword)",
                       intent=intent, query=query, elapsed=f"{elapsed:.3f}s")
            _log_intent_classify_timing(
                call_id, elapsed_sec=elapsed, path="keyword", intent=intent, query_preview=query
            )
            return {"intent": intent, "slots": {}, "confidence": 1.0}

    # 1.5차: 방문·찾아가기·교통 안내 vs transfer 오분류 완화 (LLM 전에 적용)
    # 예: "기상청에 찾아가려고 하는데요" → transfer 아님 question
    if should_treat_as_question_not_transfer(query):
        elapsed = time.time() - node_start
        logger.info(
            "timing_segment",
            segment="classify_intent",
            elapsed_sec=round(elapsed, 3),
            path="visit_direction_override",
        )
        logger.info(
            "classify_intent_visit_direction_to_question",
            intent="question",
            query=query,
            note="방문/오시는 길/교통 문의로 보이며 명시적 연결 요청 없음 → question",
        )
        _log_intent_classify_timing(
            call_id,
            elapsed_sec=elapsed,
            path="visit_direction_override",
            intent="question",
            query_preview=query,
        )
        return {"intent": "question", "slots": {}, "confidence": 0.95}

    # 2차: 짧은 발화는 question으로 간주 (LLM 없을 때)
    llm = state.get("_llm_client")
    if not llm:
        elapsed = time.time() - node_start
        _log_intent_classify_timing(
            call_id, elapsed_sec=elapsed, path="no_llm_default_question", intent="question", query_preview=query
        )
        return {"intent": "question", "slots": {}, "confidence": 0.7}

    # 3차: LLM 기반 분류 (키워드 미매칭 발화). 설계 §7 Phase 1, §13.2 의도 분류에 맥락
    try:
        messages = state.get("messages", [])
        history_snippet = _format_recent_for_intent(messages, max_turns=2)
        classify_prompt = (
            "다음 고객 발화의 의도를 분류하세요. 한 단어만 답하세요.\n"
            "가능한 의도: greeting, farewell, affirm, deny, gratitude, doubt, "
            "positive_reaction, negative_reaction, chitchat, repeat, clarification, help, "
            "question, complaint, transfer, out_of_scope\n"
            "예: 네 → affirm, 감사해요 → gratitude, 다시 말해줘 → repeat, "
            "뭘 할 수 있어요 → help, 오늘 날씨 좋다 → chitchat\n"
            "중요: transfer는 '담당자/상담원/직원에게 연결', '사람 바꿔줘'처럼 "
            "상담 인력 연결을 요청할 때만 사용하세요.\n"
            "기관에 '찾아가다', '방문', '오시는 길', '어떻게 가나요', '위치/주소/교통' 등 "
            "안내를 묻는 말은 정보 질문이므로 question입니다 (transfer 아님).\n"
        )
        if history_snippet:
            classify_prompt += f"최근 대화:\n{history_snippet}\n\n"
        classify_prompt += f'현재 고객 발화: "{query}"\n의도:'
        request_sent_at = datetime.now().isoformat()
        logger.info("llm_request_sent",
                    call_site="classify_intent",
                    request_sent_ts_iso=request_sent_at,
                    prompt_len=len(classify_prompt),
                    prompt_preview=classify_prompt.replace("\n", " "))
        try:
            result = await llm.generate_response(
                classify_prompt, context_docs=[], system_prompt="의도 분류기"
            )
        except Exception as llm_err:
            elapsed = time.time() - node_start
            logger.warning("llm_request_failed",
                           call_site="classify_intent",
                           request_sent_ts_iso=request_sent_at,
                           error_type=type(llm_err).__name__,
                           error_msg=str(llm_err),
                           elapsed_ms=round(elapsed * 1000))
            raise
        response_received_at = datetime.now().isoformat()
        raw = (result or "").strip().lower().replace('"', '').replace("'", "")
        parts = raw.split()
        intent = parts[0] if parts else ""
        if intent == "out" and len(parts) >= 3 and parts[1] == "of" and parts[2] == "scope":
            intent = "out_of_scope"
        elif intent in ("positive", "negative") and (len(parts) < 2 or parts[1] != "reaction"):
            intent = intent + "_reaction"

        if intent not in VALID_INTENTS:
            intent = "nlu_fallback"
            confidence = 0.0
        else:
            confidence = 0.9

        elapsed = time.time() - node_start
        logger.info("llm_response_received",
                    call_site="classify_intent",
                    request_sent_ts_iso=request_sent_at,
                    response_received_ts_iso=response_received_at,
                    elapsed_ms=round(elapsed * 1000),
                    intent=intent)
        logger.info("timing_segment", segment="classify_intent", elapsed_sec=round(elapsed, 3), path="llm")
        logger.info("⏱️ [TIMING] classify_intent (LLM)",
                   intent=intent, query=query, elapsed=f"{elapsed:.3f}s")
        _log_intent_classify_timing(
            call_id, elapsed_sec=elapsed, path="llm", intent=intent, query_preview=query
        )
        return {"intent": intent, "slots": {}, "confidence": confidence}
    except Exception as e:
        elapsed = time.time() - node_start
        logger.info("timing_segment", segment="classify_intent", elapsed_sec=round(elapsed, 3), path="error", error=str(e))
        logger.warning("intent_classification_error", error=str(e))
        _log_intent_classify_timing(
            call_id, elapsed_sec=elapsed, path="error", intent="nlu_fallback", query_preview=query
        )
        return {"intent": "nlu_fallback", "slots": {}, "confidence": 0.0}
