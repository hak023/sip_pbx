"""
응답 생성 노드.

RAG 컨텍스트 + 대화 기록 + 시스템 프롬프트 → LLM → 응답.
Streaming RAG: 첫 문장이 완성되면 즉시 response_chunks에 추가.
"""

import time
from datetime import datetime

import structlog
from src.ai_voicebot.langgraph.state import ConversationState

logger = structlog.get_logger(__name__)


RESPONSE_SYSTEM_PROMPT = """당신은 {org_name}의 AI 통화 비서입니다.

기관 정보:
{org_context}

대화 기록:
{history}

검색된 참고 정보:
{rag_context}

응답 규칙:
1. 한국어로 자연스럽게 대화하세요 (구어체).
2. 검색된 정보를 바탕으로 정확하게 답하세요.
3. 모르는 내용은 솔직히 "확인 후 안내 드리겠습니다"로 답하세요.
4. 2~3문장 이내로 간결하게 답하세요 (통화이므로 길면 안 됩니다).
5. 고객이 불편을 호소하면 공감하고 해결 방안을 제시하세요.
6. "더 도움이 필요하시면 말씀해 주세요" 같은 안내로 마무리하세요.
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
        return {"response": "죄송합니다. 잠시 후 다시 시도해 주세요.", "confidence": 0.0}

    start = time.time()

    try:
        # 컨텍스트 조립
        rag_results = state.get("rag_results", [])
        rag_context = _format_rag_context(rag_results)
        messages = state.get("messages", [])
        history = _format_history(messages, max_turns=6)
        org_context = state.get("org_context", "")
        org_name = _extract_org_name(org_context)

        system_prompt = RESPONSE_SYSTEM_PROMPT.format(
            org_name=org_name,
            org_context=org_context,
            history=history,
            rag_context=rag_context or "(관련 정보 없음)",
        )

        # LLM 호출
        response = await llm.generate_response(
            user_text=user_query,
            context_docs=[rag_context] if rag_context else [],
            system_prompt=system_prompt,
        )

        if not response or not response.strip():
            response = "죄송합니다. 답변을 생성하지 못했습니다. 다시 말씀해 주시겠어요?"

        elapsed = time.time() - start

        # Streaming: 문장 단위 청크 분리
        chunks = _split_into_chunks(response)

        logger.info("⏱️ [TIMING] generate_response (LLM 호출)",
                   query=user_query[:50],
                   response_len=len(response),
                   chunks=len(chunks),
                   llm_elapsed=f"{elapsed:.3f}s")

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

        # Confidence: greeting path skips adaptive_rag so state never gets confidence.
        # Without this, hitl_alert sees confidence=0 and triggers HITL unnecessarily.
        intent = state.get("intent", "")
        if intent == "greeting":
            confidence = 0.9  # Template/LLM greeting is appropriate; no RAG needed
        else:
            confidence = state.get("confidence", 0.0)  # From adaptive_rag or step_back

        return {
            "response": response,
            "response_chunks": chunks,
            "messages": updated_messages,
            "confidence": confidence,
        }

    except Exception as e:
        logger.error("response_generation_error", error=str(e), exc_info=True)
        return {
            "response": "죄송합니다. 일시적인 문제가 발생했습니다.",
            "confidence": 0.0,
        }


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
