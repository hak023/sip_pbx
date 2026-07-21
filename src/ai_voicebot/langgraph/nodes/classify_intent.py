"""
의도 분류 노드.

사용자 발화에서 의도(intent)를 분류한다.
설계: docs/design/AI_RESPONSE_HUMANLIKE_DESIGN.md — 확장 Intent 택소노미.
가능한 의도: greeting, farewell, affirm, deny, gratitude, doubt, positive_reaction,
negative_reaction, chitchat, repeat, clarification, help, question, complaint,
transfer, out_of_scope, nlu_fallback

분류 흐름:
  0차: 복합 발화가 아니고 순수 짧은 인사만 → greeting (LLM·페르소나 임베딩 생략)
  1차: 전환 접속사로 발화의 '핵심 절' 추출 (_extract_main_clause)
  2차: 페르소나 scope_keywords 매칭 → question 직행
  3차: 페르소나 유사도 → chitchat / question 조기 분기 (페르소나 비관련이어도 RAG VectorDB strict 유사도 통과 시 question)
  4차: LLM 분류 (복합발화 규칙 포함 프롬프트)
  fallback: LLM 없을 때 question 기본값
"""

from datetime import datetime
import re
from typing import Optional, Tuple

import structlog
from src.ai_voicebot.langgraph.state import ConversationState
from src.ai_voicebot.langgraph.call_context import get_llm_client, get_rag_engine
from src.ai_voicebot.langgraph.booking_intent_heuristic import merge_booking_intent_into_result
from src.ai_voicebot.knowledge.persona_service import DEFAULT_PERSONA_SIMILARITY_THRESHOLD
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


# ---------------------------------------------------------------------------
# 접근 A: 복합 발화 전처리 — 핵심 절 추출
# ---------------------------------------------------------------------------
# 전환 접속사 이후가 실제 요청인 경우가 대부분.
# "예. 감사합니다. 그런데 어린이 의자 있나요?" → "어린이 의자 있나요?"
# 원문과 main_clause 모두 LLM에 전달해 문맥 손실 없이 처리.
_TURN_CONNECTORS = (
    "그런데", "근데", "그리고", "혹시", "그나저나",
    "아 그리고", "참", "그러면", "그럼", "그럼에도",
    "그렇다면", "다름이 아니라", "그런데요",
)


def _extract_main_clause(query: str) -> str:
    """
    전환 접속사 이후 마지막 절을 반환.

    접속사가 없거나 나머지가 너무 짧으면 원문 반환.
    복수의 접속사가 있을 때는 가장 마지막 접속사 기준으로 분리.

    예:
      "예. 감사합니다. 그런데 어린이 의자 있나요?" → "어린이 의자 있나요?"
      "네, 혹시 어떤걸 도와줄수있나요?"           → "어떤걸 도와줄수있나요?"
      "안녕하세요. 영업시간이 어떻게 되나요?"     → 원문 (접속사 없음)
    """
    best_tail = ""
    best_pos = -1
    for conn in _TURN_CONNECTORS:
        idx = query.rfind(conn)
        if idx > best_pos:
            tail = query[idx + len(conn):].strip()
            if len(tail) >= 5:
                best_pos = idx
                best_tail = tail
    return best_tail if best_tail else query


# ---------------------------------------------------------------------------
# 외부 참조용 상수 (route_utterance.py 등에서 import)
# ---------------------------------------------------------------------------
# 키워드 매칭 제거 후 빈 set 유지 (외부 참조 깨짐 방지)
_QUESTION_KEYWORDS: set = set()

# greeting 뒤에 질문 패턴이 있으면 question 우선 처리용
QUESTION_PATTERNS = [
    "어떻게", "문의", "알려", "되나요", "인가요", "뭐", "무엇", "있어요",
    "해요", "해주", "하고 싶", "알고 싶", "궁금", "주차", "예약", "영업",
    "시간", "가격", "비용", "위치", "연락처", "예약", "취소",
]


def _build_persona_question_keywords(scope_keywords: list[str]) -> set[str]:
    """페르소나 scope_keywords를 question 1차 키워드로 변환 (소문자화)."""
    return {kw.lower() for kw in (scope_keywords or []) if kw.strip()}


def _format_recent_for_intent(messages: list, max_turns: int = 2) -> str:
    """의도 분류용: 최근 max_turns턴( user+assistant )을 텍스트로. 설계 §13.2."""
    if not messages:
        return ""
    recent = messages[-(max_turns * 2):]
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
    "booking",  # 예약/취소/조회 의도 (booking_agent_node 라우팅)
    "out_of_scope", "nlu_fallback",
}

# 예약 동작 패턴 — 정보 질문("예약 어떻게 해요?")과 구별되는 명확한 booking 의도
# "예약하려고", "예약하고 싶어", "예약해줘" 등 동사 결합 패턴만 포함 (명사 "예약"만은 제외)
# 페르소나 유사도 단락에서 question 조기 분류 전에 이 패턴이 있으면 LLM 3차로 위임한다.
_BOOKING_ACTION_PATTERNS: tuple = (
    "예약하려고", "예약하고 싶", "예약해주", "예약해줘", "예약 해줘", "예약 좀 해",
    "예약할게", "예약할게요", "예약 부탁", "예약 하고 싶",
    "취소하려고", "취소하고 싶", "취소해줘", "취소해주", "예약 취소",
    "예약 변경", "예약 바꿔", "날짜 바꿔", "시간 바꿔",
    "예약 확인", "내 예약", "제 예약", "예약 조회", "예약번호",
    "빈 자리", "빈자리", "빈 날", "언제 예약", "예약 가능한",
    "예약이요", "시에 예약", "에 예약",
)

# 인사/감사/작별 패턴 — 페르소나 유사도가 낮아도 chitchat 처리하지 않고 LLM 3차로 위임
# "감사합니다", "안녕하세요", "수고하세요" 등 사회적 발화는 LLM이 farewell/gratitude/greeting 등으로 분류해야 함
_SOCIAL_PHRASE_PATTERNS: tuple = (
    "감사합니다", "감사해요", "감사해", "고맙습니다", "고마워요", "고마워",
    "수고하세요", "수고하십시오", "수고했어요",
    "안녕하세요", "안녕히", "안녕", "빠이", "bye",
    "잘 있어요", "잘 있어", "그럼", "네 알겠습니다", "네 알겠어요",
    "네 감사", "아 감사", "어 감사", "아 고마", "네 고마",
    "끊을게요", "끊겠습니다", "전화 끊",
)

# 순수 인사만 있는 짧은 발화 → classify_intent_merged(LLM) 생략
_STANDALONE_GREETING_STRIP = ".。!！?？…~～ \t\r\n"
_STANDALONE_GREETING_MAX_LEN = 18
_STANDALONE_GREETING_NORMALIZED: frozenset[str] = frozenset(
    {
        "안녕",
        "안녕하세요",
        "안녕하세요요",
        "안녕하셔요",
        "하이",
        "hi",
        "hello",
        "헬로",
        "헬로우",
        "굿모닝",
        "goodmorning",
        "good morning",
        "반가워",
        "반가워요",
        "반갑습니다",
        "yo",
        "hey",
    }
)


def _is_standalone_social_greeting(text: str) -> bool:
    """복합 발화가 아닐 때, 본문이 인사만으로 구성되면 True (임베딩·LLM 분류 생략용)."""
    t = (text or "").strip().lower()
    t = t.rstrip(_STANDALONE_GREETING_STRIP)
    if not t or len(t) > _STANDALONE_GREETING_MAX_LEN:
        return False
    # 공백·구두점만으로 나뉜 토큰이 전부 인사어인 경우 (예: '안녕 하세요')
    parts = [p for p in re.split(r"[\s,，]+", t) if p]
    if not parts:
        return False
    for p in parts:
        p2 = p.rstrip(_STANDALONE_GREETING_STRIP)
        if not p2:
            continue
        if p2 not in _STANDALONE_GREETING_NORMALIZED:
            return False
    return True


def _recover_intent_from_partial_llm_json(raw: str, main_clause: str) -> Optional[Tuple[str, str]]:
    """
    MAX_TOKENS·마크다운 등으로 JSON이 잘리면 json.loads가 실패한다.
    이미 출력된 부분에서 intent / search_query 만 부분 추출한다.
    """
    text = (raw or "").strip()
    if not text:
        return None
    intent_m = re.search(r'"intent"\s*:\s*"([^"\\]*)', text, re.IGNORECASE)
    if not intent_m:
        intent_m = re.search(r"'intent'\s*:\s*'([^'\\]*)", text, re.IGNORECASE)
    if not intent_m:
        return None
    intent_val = (intent_m.group(1) or "").strip().lower()
    if not intent_val:
        return None
    # 닫는 따옴표 없이 잘린 경우까지 포착
    sq_m = re.search(r'"search_query"\s*:\s*"([^"]*)', text, re.IGNORECASE)
    if not sq_m:
        sq_m = re.search(r"'search_query'\s*:\s*'([^']*)", text, re.IGNORECASE)
    search_q = (sq_m.group(1).strip() if sq_m else "") or (main_clause or "").strip()
    return intent_val, search_q


async def classify_intent_node(state: ConversationState) -> dict:
    """
    사용자 발화의 의도를 분류.

    1차: 핵심 절 추출 (_extract_main_clause) — 복합 발화 전처리
    2차: 페르소나 scope_keywords 매칭 → question 직행 (LLM 스킵)
    3차: 페르소나 유사도 → chitchat / question 조기 분기 (비관련 + 지식 strict 유사도면 question)
    4차: LLM 분류 (복합발화 규칙 포함)
    fallback: LLM 없을 때 question 기본값

    아웃바운드 모드(outbound_purpose 존재): LLM 분류 완전 스킵.
    """
    import time
    node_start = time.time()

    call_id = state.get("_call_id") or ""

    # 아웃바운드 모드: LLM classify 완전 스킵
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

    # 셀프서비스 모드: 발신측=착신측(자기 자신에게 연락) — LLM classify 완전 스킵
    # 설계: docs/architecture/self-service-ai-assistant-architecture.md
    # outbound_purpose와 상호 배타적이어야 하나(발신/수신 시나리오가 다름), 방어적으로
    # outbound 체크를 먼저 수행하므로 두 플래그가 동시에 참이어도 기존 outbound 동작이
    # 우선되어 안전하다(CR1 — 기존 경로 무영향).
    if state.get("is_self_service_session"):
        elapsed = time.time() - node_start
        logger.info(
            "classify_intent_self_service_skip",
            call_id=call_id,
            elapsed_sec=round(elapsed, 4),
            note="셀프서비스 모드 — LLM classify 스킵, self_service_agent 직행",
        )
        _log_intent_classify_timing(
            call_id, elapsed_sec=elapsed, path="self_service_skip", intent="self_service"
        )
        return {"intent": "self_service", "slots": {}, "confidence": 1.0}

    query = state.get("user_query", "").strip()
    if not query:
        elapsed = time.time() - node_start
        _log_intent_classify_timing(
            call_id, elapsed_sec=elapsed, path="empty_query", intent="nlu_fallback"
        )
        return {"intent": "nlu_fallback", "slots": {}, "confidence": 0.0}

    _query_lower = query.lower()

    # ---------------------------------------------------------------------------
    # 0.5차: booking_context 활성 여부를 LLM 프롬프트 힌트로 전달
    # ---------------------------------------------------------------------------
    # 키워드 감지 방식을 제거하고, 활성 상태 여부만 플래그로 기록한다.
    # LLM 3차 분류 시 프롬프트에 힌트로 주입하여 정확한 흐름 판단을 위임한다.
    _booking_ctx = state.get("booking_context") or {}
    _booking_active = bool(
        _booking_ctx.get("messages")
        or _booking_ctx.get("collected_slots")
        or _booking_ctx.get("booking_flow_active") is True
    )
    if _booking_active:
        logger.info(
            "classify_intent_booking_context_hint",
            call_id=call_id,
            query_preview=query[:60],
            note="예약 대화 진행 중 — LLM 3차 분류 시 booking_context 힌트 주입 예정",
        )

    # 접근 A: 복합 발화에서 핵심 절 추출
    # 페르소나 유사도 체크 및 LLM 분류 모두 main_clause 기준으로 동작
    main_clause = _extract_main_clause(query)
    main_clause_lower = main_clause.lower()
    _is_compound = (main_clause != query)

    if _is_compound:
        logger.info(
            "classify_intent_main_clause_extracted",
            original_preview=query[:60],
            main_clause_preview=main_clause[:60],
            note="전환 접속사 기준 핵심 절 추출 — 이 절로 분류 수행",
        )

    # ---------------------------------------------------------------------------
    # 0차: 순수 짧은 인사 → greeting (페르소나 임베딩·classify_intent_merged LLM 생략)
    # ---------------------------------------------------------------------------
    if not _is_compound and _is_standalone_social_greeting(main_clause):
        elapsed = time.time() - node_start
        logger.info(
            "classify_intent_standalone_greeting",
            intent="greeting",
            query_preview=query[:50],
            main_clause_preview=main_clause[:50],
            elapsed_sec=round(elapsed, 4),
            note="짧은 인사 전용 휴리스틱 — LLM 분류 생략",
        )
        _log_intent_classify_timing(
            call_id,
            elapsed_sec=elapsed,
            path="standalone_greeting",
            intent="greeting",
            query_preview=query,
        )
        return merge_booking_intent_into_result(
            {
                "intent": "greeting",
                "slots": {},
                "confidence": 0.95,
                "rewritten_query": main_clause,
            },
            state,
            call_id=call_id,
            query=query,
            main_clause=main_clause,
            classify_path="standalone_greeting",
        )

    # ---------------------------------------------------------------------------
    # 1차: 페르소나 scope_keywords 매칭 → question 직행
    # ---------------------------------------------------------------------------
    persona_owner = state.get("_persona_owner") or state.get("_owner") or ""
    _loaded_persona = None

    if persona_owner:
        try:
            from src.ai_voicebot.knowledge.persona_service import get_persona_service
            persona_svc = get_persona_service()
            if persona_svc:
                _loaded_persona = await persona_svc.get_persona(persona_owner)

                # scope_keywords 매칭: main_clause 기준
                if _loaded_persona and _loaded_persona.enabled and _loaded_persona.scope_keywords:
                    dyn_kws = _build_persona_question_keywords(_loaded_persona.scope_keywords)
                    matched_kw = next((kw for kw in dyn_kws if kw in main_clause_lower), None)
                    if matched_kw:
                        # scope_keyword 매칭이라도 booking 동작 패턴이 있으면 LLM 3차로 위임
                        _booking_action_hit_scope = next(
                            (p for p in _BOOKING_ACTION_PATTERNS if p in main_clause_lower),
                            None,
                        )
                        if _booking_action_hit_scope:
                            logger.info(
                                "classify_intent_scope_keyword_booking_action_skip",
                                query_preview=query[:50],
                                matched_keyword=matched_kw,
                                matched_pattern=_booking_action_hit_scope,
                                note="scope_keyword 매칭이나 booking 동작 패턴 감지 → LLM 3차로 위임",
                            )
                            # LLM 3차 분류로 fall-through
                        elif _booking_active:
                            # booking_context 활성 상태: scope_keyword fast-path 우회, LLM 3차 강제
                            logger.info(
                                "classify_intent_booking_active_skip_scope_keyword",
                                query_preview=query[:50],
                                main_clause_preview=main_clause[:50],
                                matched_keyword=matched_kw,
                                persona_owner=persona_owner,
                                note="booking_context 활성 → scope_keyword fast-path 스킵, LLM 3차 강제",
                            )
                            # LLM 3차 분류로 fall-through
                        else:
                            elapsed = time.time() - node_start
                            logger.info(
                                "classify_intent_persona_scope_keyword",
                                intent="question",
                                query_preview=query[:50],
                                main_clause_preview=main_clause[:50],
                                matched_keyword=matched_kw,
                                persona_owner=persona_owner,
                                note="페르소나 scope_keyword 매칭 → question 직행 (LLM 스킵)",
                            )
                            _log_intent_classify_timing(
                                call_id, elapsed_sec=elapsed,
                                path="persona_scope_keyword", intent="question", query_preview=query,
                            )
                            return merge_booking_intent_into_result(
                                {
                                    "intent": "question",
                                    "slots": {},
                                    "confidence": 1.0,
                                    "rewritten_query": main_clause,
                                    "_persona_scope_matched": True,
                                },
                                state,
                                call_id=call_id,
                                query=query,
                                main_clause=main_clause,
                                classify_path="persona_scope_keyword",
                            )

                # ---------------------------------------------------------------------------
                # 2차: 페르소나 유사도 → chitchat / question 조기 분기 (main_clause 기준)
                # ---------------------------------------------------------------------------
                relevance = await persona_svc.check_query_relevance(
                    query=main_clause,
                    owner=persona_owner,
                    similarity_threshold=DEFAULT_PERSONA_SIMILARITY_THRESHOLD,
                )

                if relevance["persona_found"] and not relevance["is_relevant"]:
                    # booking 동작 패턴이 있으면 LLM 3차로 위임 (예: "예약하려고 합니다.")
                    _booking_action_hit_irrel = next(
                        (p for p in _BOOKING_ACTION_PATTERNS if p in main_clause_lower),
                        None,
                    )
                    if _booking_action_hit_irrel:
                        logger.info(
                            "classify_intent_irrelevant_booking_action_skip",
                            query_preview=query[:50],
                            main_clause_preview=main_clause[:50],
                            matched_pattern=_booking_action_hit_irrel,
                            similarity=relevance["similarity"],
                            persona_owner=persona_owner,
                            note="페르소나 유사도 낮지만 booking 동작 패턴 감지 → LLM 3차로 위임",
                        )
                        # LLM 3차 분류로 fall-through
                    else:
                        # 인사/감사/작별 패턴이 있으면 LLM 3차로 위임 (예: "감사합니다.", "안녕하세요.")
                        _social_hit = next(
                            (p for p in _SOCIAL_PHRASE_PATTERNS if p in main_clause_lower),
                            None,
                        )
                        if _social_hit:
                            logger.info(
                                "classify_intent_irrelevant_social_skip",
                                query_preview=query[:50],
                                main_clause_preview=main_clause[:50],
                                matched_pattern=_social_hit,
                                similarity=relevance["similarity"],
                                persona_owner=persona_owner,
                                note="페르소나 유사도 낮지만 인사/감사/작별 패턴 감지 → LLM 3차로 위임",
                            )
                            # LLM 3차 분류로 fall-through
                        elif _booking_active:
                            # 예약 진행 중 인원·성명 등은 페르소나와 무관해도 잡담이 아님 (STT: "저희는네 명이고요 …")
                            logger.info(
                                "classify_intent_irrelevant_booking_session_skip",
                                query_preview=query[:50],
                                main_clause_preview=main_clause[:50],
                                similarity=relevance["similarity"],
                                persona_owner=persona_owner,
                                note="예약 대화 진행 중 — persona_chitchat 조기 분기 생략 → LLM·booking 휴리스틱",
                            )
                            # LLM 3차 분류로 fall-through
                        else:
                            # 페르소나 임베딩과는 멀어도, 지식 VectorDB 상위 hit가 RAG similarity_threshold
                            # 이상이면 question 으로 승격 → 기존 check_cache·RAG·generate_response 경로 사용
                            kb_strict_hits = 0
                            kb_top_score = 0.0
                            rag_threshold: Optional[float] = None
                            try:
                                rag = get_rag_engine()
                                if rag is not None:
                                    rag_threshold = float(rag.similarity_threshold)
                                    kb_res = await rag.search(
                                        main_clause,
                                        owner_filter=persona_owner,
                                        call_id=call_id or None,
                                        intent="question",
                                        top_k_override=5,
                                    )
                                    tr = kb_res.trace or {}
                                    kb_strict_hits = int(
                                        tr.get("after_strict_similarity_threshold_count") or 0
                                    )
                                    if kb_res.documents:
                                        kb_top_score = float(kb_res.documents[0].score or 0.0)
                            except Exception as kb_exc:
                                logger.warning(
                                    "classify_intent_kb_gate_error",
                                    error=str(kb_exc),
                                    query_preview=query[:50],
                                    persona_owner=persona_owner,
                                )

                            if kb_strict_hits > 0:
                                elapsed = time.time() - node_start
                                logger.info(
                                    "classify_intent_persona_irrelevant_kb_question_override",
                                    intent="question",
                                    query_preview=query[:50],
                                    main_clause_preview=main_clause[:50],
                                    persona_similarity=relevance["similarity"],
                                    persona_threshold=DEFAULT_PERSONA_SIMILARITY_THRESHOLD,
                                    kb_strict_hits=kb_strict_hits,
                                    kb_top_score=round(kb_top_score, 4),
                                    rag_similarity_threshold=rag_threshold,
                                    persona_owner=persona_owner,
                                    note="페르소나 비관련이나 지식 VectorDB strict 임계 이상 → question",
                                )
                                _log_intent_classify_timing(
                                    call_id,
                                    elapsed_sec=elapsed,
                                    path="persona_irrelevant_kb_override",
                                    intent="question",
                                    query_preview=query,
                                )
                                return merge_booking_intent_into_result(
                                    {
                                        "intent": "question",
                                        "slots": {},
                                        "confidence": 1.0,
                                        "_persona_scope_matched": False,
                                        "_kb_gate_hit": True,
                                    },
                                    state,
                                    call_id=call_id,
                                    query=query,
                                    main_clause=main_clause,
                                    classify_path="persona_irrelevant_kb_override",
                                )

                            elapsed = time.time() - node_start
                            logger.info(
                                "classify_intent_persona_chitchat",
                                intent="chitchat",
                                query_preview=query[:50],
                                main_clause_preview=main_clause[:50],
                                similarity=relevance["similarity"],
                                threshold=DEFAULT_PERSONA_SIMILARITY_THRESHOLD,
                                persona_owner=persona_owner,
                                kb_strict_hits=kb_strict_hits,
                                kb_top_score=round(kb_top_score, 4),
                                note="핵심 절이 페르소나와 무관 — chitchat",
                            )
                            _log_intent_classify_timing(
                                call_id, elapsed_sec=elapsed,
                                path="persona_chitchat", intent="chitchat", query_preview=query,
                            )
                            return merge_booking_intent_into_result(
                                {
                                    "intent": "chitchat",
                                    "slots": {},
                                    "confidence": 1.0,
                                    # 지식베이스 chitchat_template 고정문 대신 LLM 일반 응대
                                    # (generate_response의 템플릿 단축 경로 미사용)
                                    "_chitchat_template": None,
                                },
                                state,
                                call_id=call_id,
                                query=query,
                                main_clause=main_clause,
                                classify_path="persona_chitchat",
                            )
                elif relevance["persona_found"] and relevance["is_relevant"]:
                    # 페르소나와 관련된 발화라도 예약 동작 패턴이 있으면 LLM 3차로 위임
                    # (예: "예약하려고 합니다" → question이 아닌 booking)
                    _booking_action_hit = next(
                        (p for p in _BOOKING_ACTION_PATTERNS if p in main_clause_lower),
                        None,
                    )
                    if _booking_action_hit:
                        logger.info(
                            "classify_intent_persona_booking_action_skip",
                            query_preview=query[:50],
                            main_clause_preview=main_clause[:50],
                            matched_pattern=_booking_action_hit,
                            persona_owner=persona_owner,
                            note="페르소나 관련 발화이나 booking 동작 패턴 감지 → LLM 3차 분류로 위임",
                        )
                        # LLM 3차 분류로 fall-through (return 없이 계속)
                    elif _booking_active:
                        # booking_context 활성: 페르소나 관련 발화여도 LLM이 판단하게 함
                        logger.info(
                            "classify_intent_booking_active_skip_persona_question",
                            query_preview=query[:50],
                            main_clause_preview=main_clause[:50],
                            similarity=relevance["similarity"],
                            persona_owner=persona_owner,
                            note="booking_context 활성 → persona_question fast-path 스킵, LLM 3차 강제",
                        )
                        # LLM 3차 분류로 fall-through
                    else:
                        elapsed = time.time() - node_start
                        logger.info(
                            "classify_intent_persona_question",
                            intent="question",
                            query_preview=query[:50],
                            main_clause_preview=main_clause[:50],
                            similarity=relevance["similarity"],
                            threshold=DEFAULT_PERSONA_SIMILARITY_THRESHOLD,
                            persona_owner=persona_owner,
                            note="핵심 절이 페르소나와 관련 — question (RAG/LLM)",
                        )
                        _log_intent_classify_timing(
                            call_id, elapsed_sec=elapsed,
                            path="persona_question", intent="question", query_preview=query,
                        )
                        return merge_booking_intent_into_result(
                            {
                                "intent": "question",
                                "slots": {},
                                "confidence": 1.0,
                                "_persona_scope_matched": True,
                            },
                            state,
                            call_id=call_id,
                            query=query,
                            main_clause=main_clause,
                            classify_path="persona_question",
                        )
        except Exception as e:
            logger.warning("persona_relevance_check_skipped",
                           persona_owner=persona_owner,
                           error=str(e),
                           note="Persona 서비스 에러 — LLM 분류로 계속")

    # ---------------------------------------------------------------------------
    # fallback: LLM 없을 때 기본값
    # ---------------------------------------------------------------------------
    llm = get_llm_client()
    if not llm:
        elapsed = time.time() - node_start
        _log_intent_classify_timing(
            call_id, elapsed_sec=elapsed, path="no_llm_default_question", intent="question", query_preview=query
        )
        return merge_booking_intent_into_result(
            {"intent": "question", "slots": {}, "confidence": 0.7},
            state,
            call_id=call_id,
            query=query,
            main_clause=main_clause,
            classify_path="no_llm_default_question",
        )

    # ---------------------------------------------------------------------------
    # 3차: LLM 분류 (접근 B: 복합발화 규칙 포함 프롬프트)
    # ---------------------------------------------------------------------------
    try:
        import json as _json
        messages = state.get("messages", [])
        history_snippet = _format_recent_for_intent(messages, max_turns=2)

        # 페르소나 기반 동적 프롬프트 구성
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

        # 접근 B: 복합 발화 처리 규칙 명시
        _compound_note = ""
        if _is_compound:
            _compound_note = (
                f"\n참고: 위 발화는 복합 발화입니다. 핵심 요청은 \"{main_clause}\" 입니다.\n"
            )

        # 0.5차: booking_context 활성 힌트
        # fast-path(scope_keyword·유사도)를 건너뛰었으므로 LLM이 최종 판단자임.
        # "예약 연속 vs 별개 질문"을 명확히 구분하도록 지시한다.
        if _booking_active:
            _compound_note += (
                "\n⚠️ 현재 예약 대화가 진행 중입니다. "
                "발화가 예약 흐름의 연장선(날짜·시간·인원 확인, 수정 요청, 확인 응답 등)이면 booking으로 분류하세요. "
                "반면, 예약과 무관한 정보 질문(예: 주차, 메뉴, 위치, 가격 등)이면 question으로 분류하세요. "
                "통화 종료·상담원 연결 의도가 명확할 때만 farewell/transfer로 분류하세요.\n"
            )

        classify_prompt = (
            "다음 고객 발화를 분석하세요.\n"
            "1) intent: 의도를 분류 (아래 목록 중 하나)\n"
            "2) search_query: 핵심 키워드로 변환한 검색용 쿼리 (원문이 충분하면 그대로)\n\n"
            "가능한 의도: greeting, farewell, affirm, deny, gratitude, doubt, "
            "positive_reaction, negative_reaction, chitchat, repeat, clarification, help, "
            "question, complaint, transfer, booking, out_of_scope\n\n"
            "규칙:\n"
            "- 복합 발화 (예: '감사합니다. 그런데 ~', '네. 혹시 ~'): "
            "  맨 마지막 요청·질문의 intent를 반환하세요. 앞의 인사·감사·긍정은 무시합니다.\n"
            "  예) '예. 감사합니다. 그런데 어린이 의자 있나요?' → question\n"
            "  예) '네, 혹시 어떤걸 도와줄수있나요?' → help\n"
            "- affirm: 단순 긍정만('네', '예', '맞아요') 있는 발화. 뒤에 질문·요청이 있으면 해당 intent로 분류.\n"
            "- help: AI가 무엇을 할 수 있는지 묻거나 안내를 요청하는 발화.\n"
            "  예) '뭘 도와드릴 수 있나요?', '어떤 걸 해줄 수 있어요?' → help\n"
            "- booking: 예약 시스템과 직접 상호작용하는 요청, 또는 영업시간·운영시간 관련 질문.\n"
            "  · 예약 생성: '예약하고 싶어요', '예약해주세요', '자리 잡아주세요', '예약 부탁드려요'\n"
            "  · 예약 취소: '예약 취소해주세요', '취소하고 싶어요', '예약 없애주세요'\n"
            "  · 예약 변경·일정 조정: '예약 날짜 바꿔주세요', '다른 날로 변경해주세요', '시간 바꿀 수 있나요'\n"
            "  · 예약 조회: '제 예약 확인해주세요', '예약번호 알려주세요', '제 예약이 언제예요'\n"
            "  · 가용 슬롯 확인: '언제 예약 가능한가요', '빈 자리 있나요', '이번 주 예약 가능한 날 알려주세요'\n"
            "  · 영업시간·운영시간: '영업시간이 어떻게 되나요', '몇 시까지 운영해요', '언제 열어요', '휴무일이 언제예요'\n"
            "  ※ 메뉴·위치·주차·가격 등 영업시간 외 정보 질문은 question으로 분류합니다.\n"
            "- transfer: '담당자/상담원/직원에게 연결' 요청만. 방문/위치/교통 안내는 question.\n"
            f"- chitchat: {_persona_name}의 업무와 무관한 잡담. AI에게 개인 질문, 일상·계절 감상, 감탄, 소감.\n"
            "  예) '꽃이 많이 폈더라고요', '오늘 날씨 참 좋네요' → chitchat\n"
            f"- question: {_persona_name}의 업무 관련 정보 질문{_question_scope_hint}."
            f"{_question_desc_hint}\n"
            "  예) '메뉴가 뭐가 있나요', '주차 가능한가요', '위치가 어디예요', '가격이 얼마예요' → question\n"
            "- search_query: 핵심 요청 절만 검색에 적합한 명사구로 변환\n\n"
            "출력 형식(필수): 마크다운·코드펜스(```) 없이, 첫 문자부터 { 로 시작하는 JSON만 출력하세요. "
            "설명 문장·백틱·json 레이블을 붙이지 마세요.\n"
            '형식: {"intent": "...", "search_query": "..."}\n'
        )
        if history_snippet:
            classify_prompt += f"최근 대화:\n{history_snippet}\n\n"
        classify_prompt += f'현재 고객 발화: "{query}"'
        if _compound_note:
            classify_prompt += _compound_note

        request_sent_at = datetime.now().isoformat()
        logger.info("llm_request_sent",
                    call_site="classify_intent_merged",
                    request_sent_ts_iso=request_sent_at,
                    prompt_len=len(classify_prompt),
                    prompt_preview=classify_prompt.replace("\n", " ")[:200])
        try:
            # 짧은 JSON만 필요하나 Gemini MAX_TOKENS 잘림·thinking 예산 등으로 불완전 JSON이 나올 수 있어 여유 상한.
            result = await llm.generate_response(
                classify_prompt,
                context_docs=[],
                system_prompt="의도 분류 및 쿼리 변환기",
                max_output_tokens=1024,
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

        # JSON 파싱
        intent = "nlu_fallback"
        search_query = main_clause  # 기본값을 main_clause로 (복합 발화 search_query 품질 향상)
        confidence = 0.0
        try:
            json_str = raw.strip()
            if "```" in json_str:
                fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", json_str, re.DOTALL)
                if fence_match:
                    json_str = fence_match.group(1)
                else:
                    json_str = re.sub(r"```(?:json)?", "", json_str).replace("```", "").strip()
            if "{" in json_str and "}" in json_str:
                json_str = json_str[json_str.index("{"):json_str.rindex("}") + 1]
            parsed = _json.loads(json_str)
            intent = (parsed.get("intent") or "nlu_fallback").strip().lower()
            search_query = (parsed.get("search_query") or main_clause).strip()
        except (_json.JSONDecodeError, ValueError, Exception) as parse_err:
            recovered = _recover_intent_from_partial_llm_json(raw, main_clause)
            if recovered:
                intent, search_query = recovered
                logger.info(
                    "classify_intent_json_recovered_partial",
                    call_id=call_id,
                    intent=intent,
                    search_query_preview=(search_query or "")[:80],
                    note="JSON 파싱 실패 → 잘린 응답에서 intent/search_query 정규식 복구",
                )
            else:
                intent = "question"
                search_query = (main_clause or "").strip()
                logger.warning(
                    "classify_intent_json_parse_failed",
                    call_id=call_id,
                    raw_preview=raw[:100],
                    fallback_intent=intent,
                    parse_error=str(parse_err)[:160],
                )

        if intent == "out_of_scope" or (intent == "out" and "scope" in raw.lower()):
            intent = "out_of_scope"
        elif intent in ("positive", "negative"):
            intent = intent + "_reaction"

        if intent not in VALID_INTENTS:
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
                    is_compound=_is_compound,
                    search_query_preview=search_query[:50])
        logger.info("timing_segment", segment="classify_intent", elapsed_sec=round(elapsed, 3), path="llm_merged")
        _log_intent_classify_timing(
            call_id, elapsed_sec=elapsed, path="llm_merged", intent=intent, query_preview=query
        )

        # call_data_record: LLM 의사결정 전체 기록
        # - prompt_full: LLM에 보낸 분류 프롬프트 전체
        # - raw_response: LLM이 돌려준 원문
        # - intent_decided: 최종 결정 intent (VALID_INTENTS 폴백 포함)
        # - booking_active: booking_context 활성 상태 (fast-path 스킵 여부 판단 근거)
        if call_id:
            log_call_data(
                call_id,
                "llm",
                "classify_intent_llm",
                prompt_full=classify_prompt,
                raw_response=raw,
                intent_decided=intent,
                search_query=search_query,
                booking_active=_booking_active,
                is_compound=_is_compound,
                elapsed_sec=round(elapsed, 3),
                request_sent_at=request_sent_at,
                response_received_at=response_received_at,
            )

        return merge_booking_intent_into_result(
            {
                "intent": intent,
                "slots": {},
                "confidence": confidence,
                "rewritten_query": search_query,
                # LLM이 직접 분류: booking_intent_heuristic이 booking_context_active로
                # 강제 승격하지 않도록 차단 플래그를 설정한다.
                "_llm_classified": True,
            },
            state,
            call_id=call_id,
            query=query,
            main_clause=main_clause,
            classify_path="llm_merged",
        )
    except Exception as e:
        elapsed = time.time() - node_start
        logger.info("timing_segment", segment="classify_intent", elapsed_sec=round(elapsed, 3), path="error", error=str(e))
        logger.warning("intent_classification_error", error=str(e))
        _log_intent_classify_timing(
            call_id, elapsed_sec=elapsed, path="error", intent="nlu_fallback", query_preview=query
        )
        return merge_booking_intent_into_result(
            {"intent": "nlu_fallback", "slots": {}, "confidence": 0.0},
            state,
            call_id=call_id,
            query=query,
            main_clause=main_clause,
            classify_path="error",
        )
