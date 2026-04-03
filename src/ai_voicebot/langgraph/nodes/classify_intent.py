"""
의도 분류 노드.

사용자 발화에서 의도(intent)를 분류한다.
설계: docs/design/AI_RESPONSE_HUMANLIKE_DESIGN.md — 확장 Intent 택소노미.
가능한 의도: greeting, farewell, affirm, deny, gratitude, doubt, positive_reaction,
negative_reaction, chitchat, repeat, clarification, help, question, complaint,
transfer, out_of_scope, nlu_fallback
"""

from datetime import datetime
import re

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

def _is_hangul_syllable(ch: str) -> bool:
    """완성형 한글 음절 1자 (가~힣)."""
    return len(ch) == 1 and "가" <= ch <= "힣"


def _keyword_matches_intent(query_lower: str, intent: str, kw: str) -> bool:
    """
    짧은 긍정 토큰 '네'·'예'는 '네가'·'예를'·'예보'·'예절' 등에 부분 문자열로 걸려 오분류되므로 제외 규칙 적용.

    '예'는 **뒤에 다른 한글 음절이 바로 붙으면** 단어 내부(예보, 예절, 예약 …)로 보고 affirm 제외.
    예외: '예요'(긍정)만 허용. 끝·공백·구두점 뒤의 '예'는 긍정으로 본다 (화이트리스트 불필요).
    """
    if kw not in query_lower:
        return False
    if intent != "affirm" or kw not in ("네", "예"):
        return True
    if kw == "네":
        for m in re.finditer("네", query_lower):
            pos = m.start()
            end = m.end()
            # 앞에 한글 음절이 붙으면 단어 내부 → 제외 ("이네", "거네" 등 문장 끝 서술어는 허용 필요하므로 앞 체크는 생략)
            # 뒤에 한글 음절이 바로 붙으면 합성어 → 제외 (네임, 네이버, 네가, 네는, 네도 모두 포함)
            if end < len(query_lower) and _is_hangul_syllable(query_lower[end]):
                continue
            return True
        return False
    for m in re.finditer("예", query_lower):
        end = m.end()
        if end < len(query_lower) and query_lower[end] == "를":
            continue  # 예를 들어
        if end >= len(query_lower):
            return True
        nxt = query_lower[end]
        
        # ✅ "예요" 처리: 앞에 다른 한글이 붙으면 서술격 조사 (거예요, 이예요 등)
        if nxt == "요":
            start = m.start()
            # 앞에 한글 음절이 있으면 서술격 조사로 판단 (affirm 제외)
            if start > 0 and _is_hangul_syllable(query_lower[start - 1]):
                continue  # 거예요, 이예요, 해주는 거예요 등
            return True  # 독립적인 "예요"만 긍정
        
        if not _is_hangul_syllable(nxt):
            return True  # 예. 예! 예 … 공백·구두점·비한글
        # 한글 음절이 이어짐 → 예보, 예절, 예약 … (합성어 열거 없이 제외)
        continue
    return False


# 키워드 기반 빠른 분류 (LLM 호출 없이). 설계 §8.2 키워드 예시 반영
# 순서 중요: repeat/clarification을 affirm보다 먼저 — "방금 네가 … 다시 얘기해"에서 '네'보다 '다시'·'뭐라고' 우선
INTENT_KEYWORDS = {
    "greeting": ["안녕", "여보세요", "반갑", "처음"],
    "farewell": ["감사합니다", "고마워", "끊을게", "그만", "종료", "바이바이", "끊을게요"],
    "complaint": ["불만", "화나", "짜증", "항의", "문제가", "왜 이래"],
    "transfer": ["사람", "담당자", "직원", "연결해", "상담원", "전화 돌려", "연결해 줘"],
    # C. 일상/제어 (affirm 짧은 토큰보다 먼저)
    "repeat": [
        "다시",
        "다시 말해",
        "뭐라고",
        "한번 더",
        "못 들었어요",
        "다시 말해줘",
        "다시 얘기",
        "기억나",
        "기억 안 나",
        "뭐라 그랬",
    ],
    "clarification": ["무슨 뜻이에요", "뭔 소리야", "이해가 안 가요", "어느 부분이요"],
    # 잡담 (AI에게 개인적 질문, 일상 감상 등)
    # 계절/날씨 감상 같은 미묘한 경계는 키워드가 너무 제한적이어서 오분류 위험 높음
    # → LLM 분류에 위임 (3차: classify_prompt의 chitchat 정의로 판단)
    "chitchat": [
        "너도", "너는", "ai는", "ai도", "당신은", "좋아하니", "좋아해?",
        "기분이 어때", "행복해?", "슬퍼?", "재미있어?", "심심해?",
        "날씨 좋네", "날씨가 좋", "기분 좋", "오늘 좋",
    ],
    # B. 반응/피드백
    "affirm": ["네", "예", "넹", "응", "좋아요", "좋습니다", "됐어요", "됐습니다", "알겠어요", "알겠습니다", "그럴게요"],
    "deny": ["아니요", "아니에요", "아니", "필요 없어요", "취소할게요", "그만할게요"],
    "gratitude": ["감사해요", "고마워요", "감사합니다", "고맙습니다"],
    "doubt": ["글쎄요", "아마", "잘 모르겠어요", "몰라요"],
    "positive_reaction": ["좋아요", "맘에 들어요", "좋네요"],
    "negative_reaction": ["별로예요", "안 좋아요", "그냥요"],
    "help": [
        "도와줘",
        "도움",
        "어떻게 해요",
        "어떻게 하죠",
        "뭘 할 수 있어요",
        # "어떤 일" 제거: "기상청은 어떤 일을 하는 곳인가요?" 등 기관 설명 질문이 help로 오분류됨
        "할 수 있어",
        "할수있어",
        "무엇을 할",
        "뭐 할 수",
    ],
    # 정보 질문 직행 패턴: 자주 나오는 질문 유형 → LLM classify 없이 question으로 직행
    # 도메인 무관 범용 패턴만 유지 (기상청 전용 키워드 제거 — 페르소나 scope_keywords로 동적 적용)
    "question": [
        # 범용 정보 문의 패턴
        "알려줘", "알려주세요", "알 수 있", "알고 싶", "궁금", "문의",
        "영업시간", "운영시간", "몇 시", "언제까지", "언제부터",
        "어디", "어디서", "어디에서", "위치", "주소", "찾아오", "오시는 길",
        "전화번호", "연락처",
        "방법", "어떻게", "어떻게 하면", "어떻게 신청", "신청 방법",
        "얼마", "비용", "가격", "요금",
        "발급", "신청", "접수", "등록",
        # 수신 방법 문의 (SMS, 앱 등)
        "받을 수", "받아볼", "받아볼 수", "받는 방법", "문자로", "앱으로",
        "휴대폰으로",
    ],
}

# question 키워드 매칭 시 다른 intent 키워드가 이미 매칭된 경우를 피하기 위해
# INTENT_KEYWORDS 순서상 "question"은 마지막에 위치 (위 다른 intent 우선 처리)
_QUESTION_KEYWORDS = set(INTENT_KEYWORDS.get("question", []))


def _organization_role_question_not_help(query_lower: str, org_name: str = "") -> bool:
    """
    기관·조직이 '무슨 일을 하는 곳'인지 묻는 질문은 정보 질문(question)이지,
    AI 능력 나열(help)이 아니다. help 키워드 오탐 시 question으로 보낸다.

    org_name: 페르소나/org_context에서 가져온 기관명 (동적). 미전달 시 범용 패턴만 체크.
    """
    if "하는 곳" in query_lower or "하는 기관" in query_lower:
        return True
    if "무슨 일을 하는" in query_lower or "뭐하는 곳" in query_lower or "뭐 하는 곳" in query_lower:
        return True
    if "기관" in query_lower and ("어떤" in query_lower or "무슨" in query_lower):
        return True
    # 페르소나 기관명 기반 동적 체크 (하드코딩 기관 유형 제거)
    if org_name:
        org_lower = org_name.lower()
        if org_lower in query_lower and (
            "어떤 일" in query_lower or "무슨 일" in query_lower or "뭐하는" in query_lower
        ):
            return True
    return False


def _build_persona_question_keywords(scope_keywords: list[str]) -> set[str]:
    """페르소나 scope_keywords를 question 1차 키워드로 변환 (소문자화)."""
    return {kw.lower() for kw in (scope_keywords or []) if kw.strip()}

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

    아웃바운드 모드(outbound_purpose 존재): LLM 분류 완전 스킵.
    착신자 발화는 intent 무관하게 generate_response_node에서 처리하므로
    keyword 분류만 수행하거나 "outbound_answer"로 고정한다.
    """
    import time
    node_start = time.time()
    
    call_id = state.get("_call_id") or ""

    # 아웃바운드 모드: LLM classify 완전 스킵 — 어차피 _route_after_classify에서
    # generate_response로 직행하므로 intent는 의미 없음. 최소 비용으로 통과.
    if state.get("outbound_purpose"):
        elapsed = time.time() - node_start
        logger.info(
            "classify_intent_outbound_skip",
            call_id=call_id,
            elapsed_sec=round(elapsed, 4),
            note="아웃바운드 모드 — LLM classify 스킵, generate_response 직행",
        )
        _log_intent_classify_timing(
            call_id, elapsed_sec=elapsed, path="outbound_skip", intent="outbound_answer"
        )
        return {"intent": "outbound_answer", "slots": {}, "confidence": 1.0}

    query = state.get("user_query", "").strip()
    if not query:
        elapsed = time.time() - node_start
        _log_intent_classify_timing(
            call_id, elapsed_sec=elapsed, path="empty_query", intent="nlu_fallback"
        )
        return {"intent": "nlu_fallback", "slots": {}, "confidence": 0.0}

    query_lower = query.lower()
    _loaded_persona = None  # 1.6차에서 페르소나 로드 후 저장 (1차 루프에서 재사용)

    # 0.5차: 명확한 question 지시어 선행 체크 (affirm 등 짧은 토큰보다 우선)
    # "알려 주세요", "알려줘" 등이 INTENT_KEYWORDS에 있어도 순서상 affirm보다 늦게 처리되므로
    # 오분류를 방지하기 위해 먼저 체크한다. (ex: "네임에 서울 날씨 알려 주세요" → question)
    _STRONG_QUESTION_INDICATORS = (
        "알려 주세요", "알려주세요", "알려 줘", "알려줘",
        "가르쳐 주세요", "가르쳐주세요", "설명해 주세요", "설명해주세요",
        "알 수 있을까요", "알 수 있나요", "알 수 있어요",
        "어떻게 되나요", "어떻게 되요", "어떻게 되죠",
    )
    if any(ind in query_lower for ind in _STRONG_QUESTION_INDICATORS):
        elapsed = time.time() - node_start
        logger.info(
            "classify_intent_strong_question_indicator",
            intent="question",
            query_preview=query[:60],
            note="강한 question 지시어 선행 매칭 — affirm/기타 키워드보다 우선",
        )
        _log_intent_classify_timing(
            call_id, elapsed_sec=elapsed, path="keyword_strong_question", intent="question", query_preview=query
        )
        return {"intent": "question", "slots": {}, "confidence": 1.0}

    # 1차: 키워드 기반 빠른 분류 (farewell 우선: "감사합니다" 등 → farewell)
    for intent, keywords in INTENT_KEYWORDS.items():
        if any(_keyword_matches_intent(query_lower, intent, kw) for kw in keywords):
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
            _org_name_for_help = (_loaded_persona.name if _loaded_persona else "") or ""
            if intent == "help" and _organization_role_question_not_help(query_lower, _org_name_for_help):
                elapsed = time.time() - node_start
                logger.info("timing_segment", segment="classify_intent", elapsed_sec=round(elapsed, 3), path="keyword")
                logger.info(
                    "classify_intent_help_keyword_to_question",
                    intent="question",
                    query=query,
                    note="기관/조직 역할 질문 패턴 → question (help 능력 나열 경로 회피)",
                )
                _log_intent_classify_timing(
                    call_id,
                    elapsed_sec=elapsed,
                    path="keyword_help_institution_to_question",
                    intent="question",
                    query_preview=query,
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
    
    # 1.6차: Persona 기반 Chitchat vs Question 분류 (LLM 전, 최종 휴리스틱 필터)
    # _persona_owner: inbound=callee(착신번호), outbound=kwargs["callee"](상대방번호)
    # agent.py에서 주입. 미설정 시 _owner(테넌트ID) 폴백.
    persona_owner = state.get("_persona_owner") or state.get("_owner") or ""
    _loaded_persona = None  # LLM 프롬프트 동적화를 위해 페르소나 참조 보관

    if persona_owner:
        try:
            from src.ai_voicebot.knowledge.persona_service import get_persona_service
            persona_svc = get_persona_service()
            if persona_svc:
                # 페르소나 객체 캐싱 (scope_keywords 재사용)
                _loaded_persona = await persona_svc.get_persona(persona_owner)

                # 1.6.1차: scope_keywords 1차 키워드 매칭 (question 직행)
                if _loaded_persona and _loaded_persona.enabled and _loaded_persona.scope_keywords:
                    dyn_kws = _build_persona_question_keywords(_loaded_persona.scope_keywords)
                    matched_kw = next((kw for kw in dyn_kws if kw in query_lower), None)
                    if matched_kw:
                        elapsed = time.time() - node_start
                        logger.info(
                            "classify_intent_persona_scope_keyword",
                            intent="question",
                            query_preview=query[:50],
                            matched_keyword=matched_kw,
                            persona_owner=persona_owner,
                            note="페르소나 scope_keyword 매칭 → question 직행 (LLM 스킵)",
                        )
                        _log_intent_classify_timing(
                            call_id, elapsed_sec=elapsed,
                            path="persona_scope_keyword", intent="question", query_preview=query,
                        )
                        # _persona_scope_matched=True: route_utterance에서 domain_question_signal 산출 시 재사용
                        return {"intent": "question", "slots": {}, "confidence": 1.0,
                                "rewritten_query": query, "_persona_scope_matched": True}

                # 1.6.2차: 유사도 기반 chitchat vs question 분류
                relevance = await persona_svc.check_query_relevance(
                    query=query,
                    owner=persona_owner,
                    similarity_threshold=0.6,
                )

                if relevance["persona_found"] and not relevance["is_relevant"]:
                    # Persona가 설정되어 있고, Query가 업무와 무관 → chitchat
                    elapsed = time.time() - node_start
                    logger.info(
                        "classify_intent_persona_chitchat",
                        intent="chitchat",
                        query_preview=query[:50],
                        similarity=relevance["similarity"],
                        threshold=0.6,
                        persona_owner=persona_owner,
                        note="Query가 조직 페르소나와 무관 — chitchat 템플릿 응답",
                    )
                    _log_intent_classify_timing(
                        call_id, elapsed_sec=elapsed,
                        path="persona_chitchat", intent="chitchat", query_preview=query,
                    )
                    return {
                        "intent": "chitchat",
                        "slots": {},
                        "confidence": 1.0,
                        "_chitchat_template": relevance.get("chitchat_template"),
                    }
                elif relevance["persona_found"] and relevance["is_relevant"]:
                    # Persona 설정되어 있고, Query가 업무 관련 → question으로 처리
                    elapsed = time.time() - node_start
                    logger.info(
                        "classify_intent_persona_question",
                        intent="question",
                        query_preview=query[:50],
                        similarity=relevance["similarity"],
                        threshold=0.6,
                        persona_owner=persona_owner,
                        note="Query가 조직 페르소나와 관련 — question (RAG/LLM)",
                    )
                    _log_intent_classify_timing(
                        call_id, elapsed_sec=elapsed,
                        path="persona_question", intent="question", query_preview=query,
                    )
                    # _persona_scope_matched=True: domain_question_signal 산출에 사용 (HITL 억제 방지)
                    return {"intent": "question", "slots": {}, "confidence": 1.0,
                            "_persona_scope_matched": True}
        except Exception as e:
            logger.warning("persona_relevance_check_skipped",
                          persona_owner=persona_owner,
                          error=str(e),
                          note="Persona 서비스 에러 — 기존 분류 로직 계속")

    # 2차: 짧은 발화는 question으로 간주 (LLM 없을 때)
    llm = state.get("_llm_client")
    if not llm:
        elapsed = time.time() - node_start
        _log_intent_classify_timing(
            call_id, elapsed_sec=elapsed, path="no_llm_default_question", intent="question", query_preview=query
        )
        return {"intent": "question", "slots": {}, "confidence": 0.7}

    # 3차: LLM 기반 분류+검색쿼리 합침 (최적화 4.4: 1회 호출로 intent + search_query)
    try:
        import json as _json
        messages = state.get("messages", [])
        history_snippet = _format_recent_for_intent(messages, max_turns=2)

        # 페르소나 기반 동적 프롬프트 구성 (_loaded_persona는 1.6차에서 조회됨)
        _persona_name = (_loaded_persona.name if _loaded_persona else "") or "AI 서비스"
        _persona_scope = ""
        if _loaded_persona and _loaded_persona.scope_keywords:
            _persona_scope = ", ".join(_loaded_persona.scope_keywords[:6])
        _persona_desc = ""
        if _loaded_persona and _loaded_persona.description:
            _persona_desc = _loaded_persona.description[:180]

        _question_scope_hint = (
            f" ({_persona_scope})" if _persona_scope else " (위치, 운영시간, 연락처, 비용, 신청 방법 등)"
        )
        _question_desc_hint = (
            f"\n  [{_persona_name} 업무 범위: {_persona_desc}]" if _persona_desc else ""
        )

        classify_prompt = (
            "다음 고객 발화를 분석하세요.\n"
            "1) intent: 의도를 분류 (아래 목록 중 하나)\n"
            "2) search_query: 핵심 키워드로 변환한 검색용 쿼리 (원문이 충분하면 그대로)\n\n"
            "가능한 의도: greeting, farewell, affirm, deny, gratitude, doubt, "
            "positive_reaction, negative_reaction, chitchat, repeat, clarification, help, "
            "question, complaint, transfer, out_of_scope\n\n"
            "규칙:\n"
            "- transfer: '담당자/상담원/직원에게 연결' 요청만. 방문/위치/교통 안내는 question.\n"
            f"- chitchat: {_persona_name}의 업무와 무관한 잡담. AI에게 개인 질문, 일상·계절 감상, 감탄, 소감.\n"
            "  예) '꽃이 많이 폈더라고요', '오늘 날씨 참 좋네요', '기분이 좋네요', '춥네요' → 모두 chitchat\n"
            f"- question: {_persona_name}의 업무 관련 정보 질문{_question_scope_hint}."
            f"{_question_desc_hint}\n"
            "- search_query: 대명사를 구체 명사로, 구어체를 검색 적합 문장으로 변환\n\n"
            'JSON만 출력: {"intent": "...", "search_query": "..."}\n'
        )
        if history_snippet:
            classify_prompt += f"최근 대화:\n{history_snippet}\n\n"
        classify_prompt += f'현재 고객 발화: "{query}"'
        request_sent_at = datetime.now().isoformat()
        logger.info("llm_request_sent",
                    call_site="classify_intent_merged",
                    request_sent_ts_iso=request_sent_at,
                    prompt_len=len(classify_prompt),
                    prompt_preview=classify_prompt.replace("\n", " ")[:200])
        try:
            result = await llm.generate_response(
                classify_prompt,
                context_docs=[],
                system_prompt="의도 분류 및 쿼리 변환기",
                max_output_tokens=128,
            )
        except Exception as llm_err:
            elapsed = time.time() - node_start
            logger.warning("llm_request_failed",
                           call_site="classify_intent_merged",
                           request_sent_ts_iso=request_sent_at,
                           error_type=type(llm_err).__name__,
                           error_msg=str(llm_err),
                           elapsed_ms=round(elapsed * 1000))
            raise
        response_received_at = datetime.now().isoformat()
        raw = (result or "").strip()

        logger.debug("classify_intent_llm_raw",
                     call_id=call_id,
                     raw_response=raw[:300],
                     raw_len=len(raw))

        # JSON 파싱 시도
        intent = "nlu_fallback"
        search_query = query
        confidence = 0.0
        try:
            json_str = raw.strip()
            # 마크다운 코드블록 제거: ```json ... ``` 또는 ``` ... ```
            if "```" in json_str:
                # ```json\n{...}\n``` 형태에서 { ... } 부분만 추출
                # re 모듈은 파일 상단에 이미 import 됨
                fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", json_str, re.DOTALL)
                if fence_match:
                    json_str = fence_match.group(1)
                else:
                    # fallback: ``` 제거 후 { } 범위로 추출
                    json_str = re.sub(r"```(?:json)?", "", json_str).replace("```", "").strip()
            # { } 범위 추출 (코드블록이 없어도 앞뒤 텍스트가 붙은 경우 대비)
            if "{" in json_str and "}" in json_str:
                json_str = json_str[json_str.index("{"):json_str.rindex("}") + 1]
            parsed = _json.loads(json_str)
            intent = (parsed.get("intent") or "nlu_fallback").strip().lower()
            search_query = (parsed.get("search_query") or query).strip()
        except (_json.JSONDecodeError, ValueError, Exception):
            raw_lower = raw.lower().replace('"', '').replace("'", "")
            parts = raw_lower.split()
            intent = parts[0] if parts else "nlu_fallback"
            logger.info("classify_intent_json_parse_failed",
                        call_id=call_id,
                        raw_preview=raw[:100],
                        fallback_intent=intent)

        if intent == "out_of_scope" or (intent == "out" and "scope" in raw.lower()):
            intent = "out_of_scope"
        elif intent in ("positive", "negative"):
            intent = intent + "_reaction"

        if intent not in VALID_INTENTS:
            # nlu_fallback → question 폴백: 정보를 묻는 발화일 가능성이 높으면 question으로 처리
            logger.info("classify_intent_nlu_fallback_to_question",
                        call_id=call_id,
                        original_intent=intent,
                        query_preview=query[:50],
                        note="VALID_INTENTS에 없는 intent → question 폴백")
            intent = "question"
            confidence = 0.7
        else:
            confidence = 0.9

        elapsed = time.time() - node_start
        logger.info("llm_response_received",
                    call_site="classify_intent_merged",
                    request_sent_ts_iso=request_sent_at,
                    response_received_ts_iso=response_received_at,
                    elapsed_ms=round(elapsed * 1000),
                    intent=intent,
                    search_query_preview=search_query[:50])
        logger.info("timing_segment", segment="classify_intent", elapsed_sec=round(elapsed, 3), path="llm_merged")
        _log_intent_classify_timing(
            call_id, elapsed_sec=elapsed, path="llm_merged", intent=intent, query_preview=query
        )
        return {
            "intent": intent,
            "slots": {},
            "confidence": confidence,
            "rewritten_query": search_query,
        }
    except Exception as e:
        elapsed = time.time() - node_start
        logger.info("timing_segment", segment="classify_intent", elapsed_sec=round(elapsed, 3), path="error", error=str(e))
        logger.warning("intent_classification_error", error=str(e))
        _log_intent_classify_timing(
            call_id, elapsed_sec=elapsed, path="error", intent="nlu_fallback", query_preview=query
        )
        return {"intent": "nlu_fallback", "slots": {}, "confidence": 0.0}
