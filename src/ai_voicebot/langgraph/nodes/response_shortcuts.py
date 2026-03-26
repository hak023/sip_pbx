"""
단축 응답 노드 (대부분 캐시·LLM 스킵; intent=help 만 테넌트 RAG+LLM).

설계: docs/design/AI_RESPONSE_HUMANLIKE_DESIGN.md §4
- template_response: B 그룹 반응/피드백 (affirm, deny, gratitude 등)
- repeat_response: 다시 말해줘
- clarification_response: 무슨 뜻이에요
- help_response: 뭘 할 수 있어요 → 테넌트 지식 RAG + LLM으로 안내 항목 5개 선정
- fallback_response: out_of_scope, nlu_fallback (고정 멘트, 선택적 HITL)
"""

import json
import random
import re
import structlog
from typing import List

from src.ai_voicebot.langgraph.state import ConversationState
from src.common.call_data_record_logger import log_call_data
from src.common.rag_hit_serializer import build_rag_hits_llm_context

logger = structlog.get_logger(__name__)

HELP_RAG_TOP_K = 20
HELP_RAG_CONTEXT_MAX_DOCS = 14
HELP_RAG_SNIPPET_CHARS = 450
HELP_LLM_MAX_TOKENS = 512
HELP_ITEM_MAX_LEN = 48

# help 휴리스틱: category → 음성 안내용 짧은 라벨 (비어 있으면 doc 본문/메타로 폴백)
_CATEGORY_HELP_LABELS: dict = {
    "weather_warning": "기상특보 안내",
    "weather_forecast": "날씨 안내",
    "complaint": "불만 접수·안내",
    "transfer": "상담원 연결",
    "chitchat": "일반 대화",
    "farewell": "종료 인사",
    "greeting_phase1": "인사",
    "greeting_phase2": "서비스 안내",
}

# 설계 §4.1 그룹 B 템플릿 (intent별 랜덤 1문장)
INTENT_RESPONSE_TEMPLATES = {
    "affirm": [
        "네, 알겠습니다. 더 필요하시면 말씀해 주세요.",
        "좋습니다. 다른 궁금한 점 있으시면 말씀해 주세요.",
    ],
    "deny": [
        "알겠습니다. 다른 건 도와드릴까요?",
        "네, 그럼 필요하실 때 말씀해 주세요.",
    ],
    "gratitude": [
        "천만에요. 더 필요하시면 말씀해 주세요.",
        "도움이 되었다니 다행이에요. 좋은 하루 되세요.",
    ],
    "doubt": [
        "괜찮아요. 정하시면 말씀해 주세요.",
        "네, 필요하실 때 다시 말씀해 주세요.",
    ],
    "positive_reaction": [
        "감사합니다. 더 궁금하신 점 있으시면 편하게 말씀해 주세요.",
        "도움이 되셨다니 좋겠어요. 다른 문의 있으시면 말씀해 주세요.",
    ],
    "negative_reaction": [
        "불편을 드려 죄송합니다. 다른 방법으로 안내해 드릴까요?",
        "그렇군요. 담당자 연결이 필요하시면 말씀해 주세요.",
    ],
}

# repeat/clarification 기본 문장
DEFAULT_REPEAT_MESSAGE = "방금 말씀드린 내용을 다시 안내드릴게요."
DEFAULT_CLARIFICATION_MESSAGE = "어떤 점이 궁금하신지 조금만 더 말씀해 주시면 안내해 드릴게요."
DEFAULT_HELP_MESSAGE = "어떤 내용이 궁금하신지 말씀해 주시면 안내해 드릴게요."
# HITL 요청 시 발신자에게 먼저 재생 (이후 관리자에게 HITL 요청)
DEFAULT_FALLBACK_MESSAGE = "확인해보겠습니다. 잠시만 기다려 주세요."

# 관리자 미응답 시 발신자에게 재생 후, 긍정(affirm) 시 frontend에 fallback 가능 표시 (설계 §5.5)
HITL_FALLBACK_OFFER_MESSAGE = "해당 내용 확인 후 별도 연락을 드릴까요?"

# fallback 시 HITL 사용 여부 (설정으로 오버라이드 가능)
FALLBACK_NEEDS_HITL_DEFAULT = True
FALLBACK_HITL_REASON = "의도 분류 불명 또는 업무 범위 외 발화. 확인이 필요합니다."


def _last_assistant_content(messages: list) -> str:
    """messages에서 마지막 assistant 발화 content 반환. 없으면 빈 문자열."""
    if not messages:
        return ""
    for m in reversed(messages):
        if m.get("role") == "assistant":
            return m.get("content", "") or ""
    return ""


async def template_response_node(state: ConversationState) -> dict:
    """
    B 그룹 반응/피드백: intent별 공용 템플릿(INTENT_RESPONSE_TEMPLATES)에서 랜덤 1문장 선택.
    설계 §4.1, §8.2. (테넌트별 오버라이드 §8.1은 미구현.)
    """
    intent = state.get("intent", "question")
    templates = INTENT_RESPONSE_TEMPLATES.get(intent)
    if not templates:
        response = "더 필요하시면 말씀해 주세요."
    else:
        response = random.choice(templates)
    return {
        "response": response,
        "response_chunks": [response],
        "confidence": 0.9,
        "llm_rag_applied": [],
        "llm_rag_context_source": "shortcut_template_b_group",
        "rag_search_trace": {},
    }


async def repeat_response_node(state: ConversationState) -> dict:
    """
    다시 말해줘: 마지막 assistant 발화를 그대로 반환. 없으면 기본 문장.
    설계 §4.2
    """
    messages = state.get("messages", [])
    last = _last_assistant_content(messages)
    if last:
        response = last
    else:
        response = DEFAULT_REPEAT_MESSAGE
    return {
        "response": response,
        "response_chunks": [response],
        "confidence": 0.9,
        "llm_rag_applied": [],
        "llm_rag_context_source": "shortcut_repeat",
        "rag_search_trace": {},
    }


async def clarification_response_node(state: ConversationState) -> dict:
    """
    무슨 뜻이에요: 직전 assistant 발화 요약 + 명확화 문장. 없으면 기본 문장.
    설계 §4.2 (요약은 단순화로 직전 발화 앞부분 재사용)
    """
    messages = state.get("messages", [])
    last = _last_assistant_content(messages)
    if last:
        preview = last[:80] + "..." if len(last) > 80 else last
        response = f"제가 {preview} 말씀드렸는데, 더 알고 싶으신 게 있으신가요?"
    else:
        response = DEFAULT_CLARIFICATION_MESSAGE
    return {
        "response": response,
        "response_chunks": [response],
        "confidence": 0.9,
        "llm_rag_applied": [],
        "llm_rag_context_source": "shortcut_clarification",
        "rag_search_trace": {},
    }


HELP_CAPABILITY_TEMPLATE = (
    "저는 {items}을 할 수 있어요. 어떤 것을 도와드릴까요?"
)

HELP_RAG_QUERY_FALLBACK = (
    "서비스 안내 제공 가능한 업무 도움 주제 상담 문의"
)

HELP_LLM_SYSTEM_HINT = """역할: 콜센터 AI가 전화로 고객에게 말할 "할 수 있는 일" 목록을 고릅니다.
입력: 아래 지식 조각은 해당 테넌트(기관) 지식베이스에서 검색된 내용입니다.
출력 규칙(반드시 준수):
- 출력은 오직 한 줄짜리 JSON 배열 하나뿐입니다. 앞뒤 설명·인사·마크다운·코드펜스(```) 금지.
- 배열 길이는 1~5개. 가능하면 정확히 5개.
- 각 원소는 짧은 한국어 구(명사구 또는 짧은 동사구). 음성 안내용이므로 각 30자 이내.
- 지식 조각에 근거가 없는 항목은 넣지 마세요. 추측 금지.
- 올바른 출력 예시 한 가지:
["내일 날씨 안내","태풍 정보","기상 감정서 발급","찾아오는 길","상담원 연결"]
"""


def _build_help_knowledge_block(docs: List[object]) -> str:
    parts: List[str] = []
    for i, d in enumerate(docs[:HELP_RAG_CONTEXT_MAX_DOCS], 1):
        text = (getattr(d, "text", None) or "").strip().replace("\n", " ")
        if len(text) > HELP_RAG_SNIPPET_CHARS:
            text = text[: HELP_RAG_SNIPPET_CHARS - 1] + "…"
        meta = getattr(d, "metadata", None) or {}
        cat = meta.get("category", "") if isinstance(meta, dict) else ""
        parts.append(f"[{i}] category={cat}\n{text}")
    return "\n\n---\n\n".join(parts)


def _normalize_help_item_strings(arr: list) -> List[str]:
    out: List[str] = []
    for x in arr:
        s = str(x).strip()
        if not s:
            continue
        if len(s) > HELP_ITEM_MAX_LEN:
            s = s[: HELP_ITEM_MAX_LEN - 1] + "…"
        out.append(s)
        if len(out) >= 5:
            break
    return out


def _parse_help_items_line_fallback(raw: str) -> List[str]:
    """JSON이 아닐 때 불릿/번호 목록에서 항목 추출."""
    out: List[str] = []
    for line in raw.replace("•", "-").splitlines():
        line = line.strip()
        if len(line) < 2:
            continue
        line = re.sub(r"^[`\s]+|[`\s]+$", "", line)
        line = re.sub(r"^[-*•]\s*", "", line)
        line = re.sub(r"^\d+[\.)]\s*", "", line)
        if (line.startswith('"') and line.endswith('"')) or (line.startswith("'") and line.endswith("'")):
            line = line[1:-1].strip()
        if len(line) < 2:
            continue
        if len(line) > HELP_ITEM_MAX_LEN:
            line = line[: HELP_ITEM_MAX_LEN - 1] + "…"
        out.append(line)
        if len(out) >= 5:
            break
    return out


def _parse_help_items_from_llm(raw: str) -> List[str]:
    t = (raw or "").strip()
    if not t:
        return []
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", t, re.IGNORECASE)
    if fence:
        t = fence.group(1).strip()
    # 전체가 배열 JSON인 경우
    if t.startswith("[") and t.endswith("]"):
        try:
            arr = json.loads(t)
            if isinstance(arr, list):
                return _normalize_help_item_strings(arr)
        except json.JSONDecodeError:
            pass
    start, end = t.find("["), t.rfind("]")
    if start >= 0 and end > start:
        try:
            arr = json.loads(t[start : end + 1])
            if isinstance(arr, list):
                got = _normalize_help_item_strings(arr)
                if got:
                    return got
        except json.JSONDecodeError:
            pass
    return _parse_help_items_line_fallback(t)


def _help_items_from_documents(docs: list) -> List[str]:
    """LLM 파싱 실패 시 RAG 문서 메타·본문으로 짧은 항목 구성 (최대 5)."""
    seen: set[str] = set()
    out: List[str] = []

    def add(label: str) -> None:
        s = (label or "").strip()
        if len(s) < 2:
            return
        key = s.lower()
        if key in seen:
            return
        seen.add(key)
        if len(s) > HELP_ITEM_MAX_LEN:
            s = s[: HELP_ITEM_MAX_LEN - 1] + "…"
        out.append(s)

    for d in docs:
        if len(out) >= 5:
            break
        meta = getattr(d, "metadata", None) or {}
        if not isinstance(meta, dict):
            meta = {}
        text = (getattr(d, "text", None) or "").strip()
        dt = str(meta.get("doc_type") or "").lower()
        cat = str(meta.get("category") or "").strip()
        if dt == "capability":
            dn = (meta.get("display_name") or "").strip()
            if dn:
                add(dn)
                continue
        if cat == "contact" or dt == "contact":
            dept = (meta.get("department") or "").strip()
            if dept:
                add(f"{dept} 안내")
            elif text:
                add(text.split("\n")[0].strip()[:HELP_ITEM_MAX_LEN])
            else:
                add("연락처 안내")
            continue
        mapped = _CATEGORY_HELP_LABELS.get(cat)
        if mapped:
            add(mapped)
            continue
        if cat:
            add(cat.replace("_", " ") + " 안내")
            continue
        if text:
            frag = re.split(r"[.!?\n]", text, maxsplit=1)[0].strip() or text
            add(frag[:HELP_ITEM_MAX_LEN])
    return out[:5]


async def help_response_node(state: ConversationState) -> dict:
    """
    intent=help: 테넌트(owner) 지식베이스 전체를 RAG 검색한 뒤 LLM이 안내 항목 최대 5개 선정.
    RAG 0건 또는 LLM 실패 시 DEFAULT_HELP_MESSAGE.
    """
    owner = (state.get("_owner") or "").strip()
    call_id = (state.get("_call_id") or "").strip()
    user_q = (state.get("user_query") or "").strip()
    rag_engine = state.get("_rag_engine")
    llm = state.get("_llm_client")

    rag_query = user_q if user_q else HELP_RAG_QUERY_FALLBACK
    docs: list = []
    trace: dict = {}

    if rag_engine and owner:
        try:
            search_out = await rag_engine.search(
                rag_query,
                owner_filter=owner,
                call_id=call_id or None,
                top_k_override=HELP_RAG_TOP_K,
                intent="help",
            )
            docs = list(search_out.documents or [])
            trace = search_out.trace or {}
        except Exception as e:
            logger.warning(
                "help_response_rag_failed",
                owner=owner,
                call_id=call_id or None,
                error=str(e),
            )
            trace = {"error": str(e), "path": "help_response_rag"}

    if not docs:
        logger.info(
            "help_response_no_rag_hits",
            owner=owner or None,
            call_id=call_id or None,
            note="RAG 0건 — DEFAULT_HELP_MESSAGE",
        )
        if call_id:
            log_call_data(
                call_id,
                "rag",
                "help_response_no_rag",
                owner=owner,
                query=rag_query,
            )
        return {
            "response": DEFAULT_HELP_MESSAGE,
            "response_chunks": [DEFAULT_HELP_MESSAGE],
            "confidence": 0.35,
            "llm_rag_applied": [],
            "llm_rag_context_source": "help_intent_rag_empty",
            "rag_search_trace": trace,
            "rag_results": [],
        }

    knowledge_block = _build_help_knowledge_block(docs)
    prompt = (
        f"{HELP_LLM_SYSTEM_HINT}\n\n"
        f"사용자 발화(참고): {user_q or '(없음)'}\n\n"
        f"지식 조각:\n{knowledge_block}\n\n"
        "위만 보고 JSON 배열을 출력하세요."
    )

    items: List[str] = []
    llm_raw = ""
    llm_parse_ok = False
    if llm:
        try:
            llm_raw = await llm.generate_simple(
                prompt, max_tokens=HELP_LLM_MAX_TOKENS, timeout_seconds=22.0
            )
            items = _parse_help_items_from_llm(llm_raw or "")
            llm_parse_ok = bool(items)
            if not items and (llm_raw or "").strip():
                logger.warning(
                    "help_response_llm_parse_empty",
                    call_id=call_id or None,
                    owner=owner,
                    llm_raw_len=len(llm_raw),
                    llm_raw_preview=(llm_raw or "")[:800],
                    note="JSON/목록 파싱 실패 — RAG 메타 휴리스틱 시도",
                )
            logger.info(
                "help_response_llm_items",
                call_id=call_id or None,
                owner=owner,
                item_count=len(items),
                parse_ok=llm_parse_ok,
                note="RAG 후 LLM 5항목 선정",
            )
        except Exception as e:
            logger.warning(
                "help_response_llm_failed",
                call_id=call_id or None,
                owner=owner,
                error=str(e),
            )

    source = "help_intent_rag_llm"
    if not items:
        items = _help_items_from_documents(docs)
        if items:
            source = "help_intent_rag_heuristic"
            logger.info(
                "help_response_heuristic_items",
                call_id=call_id or None,
                owner=owner,
                item_count=len(items),
                items_preview=items,
                note="LLM 미사용/파싱 실패 후 문서 메타·본문으로 항목 구성",
            )

    if not items:
        logger.info(
            "help_response_no_items_total_fallback",
            call_id=call_id or None,
            owner=owner,
            note="RAG는 있으나 LLM·휴리스틱 모두 항목 없음 — DEFAULT_HELP_MESSAGE",
        )
        if call_id:
            log_call_data(
                call_id,
                "rag",
                "help_response_total_fallback",
                owner=owner,
                rag_hit_count=len(docs),
                had_llm_raw=bool((llm_raw or "").strip()),
            )
        return {
            "response": DEFAULT_HELP_MESSAGE,
            "response_chunks": [DEFAULT_HELP_MESSAGE],
            "confidence": 0.45,
            "llm_rag_applied": build_rag_hits_llm_context(docs, max_items=12),
            "llm_rag_context_source": "help_intent_rag_llm_fallback",
            "rag_search_trace": trace,
            "rag_results": docs,
        }

    items_joined = ", ".join(items)
    response = HELP_CAPABILITY_TEMPLATE.format(items=items_joined)
    top_score = float(getattr(docs[0], "score", 0.0) or 0.0)
    if source == "help_intent_rag_heuristic":
        conf = min(0.82, 0.48 + 0.28 * top_score)
    else:
        conf = min(0.92, 0.55 + 0.37 * top_score)

    if call_id:
        log_call_data(
            call_id,
            "rag",
            "help_response_ok",
            owner=owner,
            rag_hit_count=len(docs),
            item_count=len(items),
            items=items,
            source=source,
        )

    return {
        "response": response,
        "response_chunks": [response],
        "confidence": conf,
        "llm_rag_applied": build_rag_hits_llm_context(docs, max_items=12),
        "llm_rag_context_source": source,
        "rag_search_trace": trace,
        "rag_results": docs,
    }


async def fallback_response_node(state: ConversationState) -> dict:
    """
    out_of_scope / nlu_fallback: 고정 멘트 + 설정에 따라 needs_human 설정.
    설계 §4.4, §5.3
    """
    response = DEFAULT_FALLBACK_MESSAGE
    needs_human = FALLBACK_NEEDS_HITL_DEFAULT
    hitl_reason = FALLBACK_HITL_REASON if needs_human else ""
    return {
        "response": response,
        "response_chunks": [response],
        "confidence": 0.0,
        "needs_human": needs_human,
        "hitl_reason": hitl_reason,
        "llm_rag_applied": [],
        "llm_rag_context_source": "shortcut_fallback",
        "rag_search_trace": {},
    }
