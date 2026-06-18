"""
응답 생성 노드.

RAG 컨텍스트 + 대화 기록 + 시스템 프롬프트 → LLM → 응답.
Streaming RAG: 첫 문장이 완성되면 즉시 response_chunks에 추가.
"""

import asyncio
import json as _json
import re as _re
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import structlog
from src.ai_voicebot.langgraph.hitl_escalation_policy import is_social_direct_path
from src.ai_voicebot.langgraph.state import ConversationState
from src.ai_voicebot.langgraph.call_context import get_llm_client
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

# 모르는 내용·HITL 시 고객 TTS용 고정 멘트 (담당자 확인 대기 안내 대신 명확한 한계 안내)
HITL_CUSTOMER_TTS_MESSAGE = (
    "죄송합니다. 해당 내용은 제가 알지 못하는 내용입니다. "
    "다른 도움이 필요하시면 말씀해 주세요."
)
RESPONSE_UNKNOWN_NEEDS_FOLLOWUP = HITL_CUSTOMER_TTS_MESSAGE

# 질문(intent=question) + 이번 턴 RAG 검색 결과 없음 → 동일 멘트 후 HITL
RESPONSE_QUESTION_NO_KNOWLEDGE = HITL_CUSTOMER_TTS_MESSAGE


# 최적화 4.6: 전화 상담 특성상 3턴이면 충분. 입력 토큰 절감 → 응답 속도 향상
HISTORY_MAX_TURNS = 3

RESPONSE_SYSTEM_PROMPT = """당신은 {org_name}의 AI 통화 비서입니다.
{persona_context}
기관 정보:
{org_context}

{stage_and_summary}
대화 기록:
{history}

검색된 참고 정보:
{rag_context}

응답 규칙:
1. 한국어로 자연스럽게 대화하세요 (구어체).
2. [최우선] 검색된 참고 정보가 있으면 반드시 그 내용을 바탕으로 답하세요.
   - 참고 정보에 질문과 유사한 Q&A가 있으면 그 A를 활용해 안내하세요.
   - 참고 정보가 서비스·절차 안내라면 방법·절차를 안내하세요.
   - 이전 대화에서 "안내 불가"라고 했더라도 참고 정보가 있으면 그 정보로 답하세요.
3. 참고 정보가 "(관련 정보 없음)"이거나 질문과 전혀 무관할 때만 아래 문장을 사용하세요.
   "죄송합니다. 해당 내용은 제가 알지 못하는 내용입니다. 다른 도움이 필요하시면 말씀해 주세요."
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
    llm = get_llm_client()
    user_query = state.get("user_query", "")

    if not llm or not user_query:
        return {
            "response": "죄송합니다. 잠시 후 다시 시도해 주세요.",
            "confidence": 0.0,
            **_llm_exchange_rag_fields(state, state.get("rag_results") or [], context_source="skipped_no_llm_input"),
        }

    intent = state.get("intent", "")
    rag_results = state.get("rag_results") or []
    
    # Chitchat 템플릿 응답 (Persona 기반)
    # classify_intent에서 _chitchat_template이 설정되면 LLM 없이 즉시 반환
    if intent == "chitchat" and state.get("_chitchat_template"):
        template = state["_chitchat_template"]
        messages = state.get("messages", [])
        updated_messages = list(messages)
        updated_messages.append({
            "role": "user",
            "content": user_query,
            "timestamp": datetime.now().isoformat(),
        })
        updated_messages.append({
            "role": "assistant",
            "content": template,
            "timestamp": datetime.now().isoformat(),
        })
        chunks = _split_into_chunks(template)
        logger.info(
            "generate_response_chitchat_template",
            intent="chitchat",
            response_len=len(template),
            note="Persona chitchat 템플릿 — LLM 스킵",
        )
        return {
            "response": template,
            "response_chunks": chunks,
            "messages": updated_messages,
            "confidence": 1.0,
            "needs_follow_up": False,
            **_llm_exchange_rag_fields(state, [], context_source="chitchat_template"),
        }

    # 아웃바운드 모드: RAG 없는 question 고정 멘트 경로를 건너뜀
    # (착신자의 답변이 RAG 지식과 무관해도 LLM으로 자연스럽게 응대해야 함)
    _is_outbound = bool(state.get("outbound_purpose"))

    # 질문으로 분류되었고 이번 턴 지식 검색 결과가 없으면 LLM 생략 → 고정 멘트 + HITL 후속
    # (아웃바운드는 제외: 목적/질문 기반 LLM 응대가 우선)
    if intent == "question" and not rag_results and not _is_outbound:
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

    # _social은 인바운드 경로에서만 의미 있음. 아웃바운드에서는 항상 False로 초기화해
    # 이후 코드(elif _is_llm_error_fallback, confidence 결정 등)에서 UnboundLocalError를 방지한다.
    _social = False

    try:
        # 컨텍스트 조립 (§13.2 history 8턴, §4.3 chitchat 짧은 응답)
        rag_context = _format_rag_context(rag_results)
        messages = state.get("messages", [])
        history = _format_history(messages, max_turns=HISTORY_MAX_TURNS)
        org_context = state.get("org_context", "")

        if _is_outbound:
            # ── 아웃바운드 전용 프롬프트 ──
            outbound_purpose = state.get("outbound_purpose", "")
            outbound_questions = state.get("outbound_questions") or []
            outbound_answers = state.get("outbound_answers") or {}
            answered = list(outbound_answers.keys())
            unanswered = [q for q in outbound_questions if q not in outbound_answers]

            # 진행 상황 블록
            if outbound_questions:
                answered_lines = "\n".join(
                    f"  - {q}: {outbound_answers[q]}" for q in answered
                ) or "  (없음)"
                unanswered_lines = "\n".join(
                    f"  - {q}" for q in unanswered
                ) or "  (없음)"
                progress_block = (
                    f"[진행 상황]\n"
                    f"  답변 완료({len(answered)}개):\n{answered_lines}\n"
                    f"  미수집({len(unanswered)}개):\n{unanswered_lines}"
                )
            else:
                progress_block = f"[통화 목적] {outbound_purpose}"

            next_question = unanswered[0] if unanswered else ""

            # ── JSON 응답 형식 지시 ──
            # LLM이 응대 생성과 답변 추출을 한 번에 수행한다.
            # 파싱 후 response 필드만 TTS로 출력하고,
            # answered 필드는 rag_processor에서 _outbound_answers에 직접 적용한다.
            json_format_instruction = (
                "반드시 아래 JSON 형식으로만 답하세요. JSON 외 다른 텍스트는 절대 출력하지 마세요.\n\n"
                "{\n"
                '  "response": "착신자에게 할 말 (TTS로 읽힐 텍스트)",\n'
                '  "answered": [\n'
                '    {"question": "수집된 질문 원문", "answer": "착신자 답변 요약"}\n'
                "  ],\n"
                '  "is_answer": true\n'
                "}\n\n"
                "규칙:\n"
                "- answered: 이번 발화에서 수집된 질문·답변 쌍. 수집된 것이 없으면 빈 배열 [].\n"
                "- is_answer: 이번 발화가 미수집 질문에 대한 유효한 답변이면 true, 아니면 false.\n"
                "  (욕설·거절·감탄사·무관한 말 등은 false)\n"
                "- response 작성 규칙:\n"
            )

            if next_question:
                json_format_instruction += (
                    f"  1. 착신자 발화에 자연스럽게 반응하는 1문장을 먼저 쓰세요.\n"
                    f"  2. is_answer=false이면 미수집 질문을 표현을 바꿔 다시 물어보세요: 「{next_question}」\n"
                    f"  3. is_answer=true이면 다음 미수집 질문이 있으면 이어서 물어보세요.\n"
                    "  4. 전체 2~3문장 이내, 통화이므로 짧고 자연스럽게.\n"
                    "  5. 「알지 못하는 내용입니다」 같은 한계 멘트는 절대 쓰지 마세요."
                )
            else:
                json_format_instruction += (
                    "  1. 착신자 발화에 자연스럽게 반응하는 1문장을 쓰세요.\n"
                    "  2. 모든 질문이 수집되었으므로 감사 인사와 함께 통화를 마무리하세요.\n"
                    "  3. 2~3문장 이내로 간결하게."
                )

            system_prompt = (
                "당신은 아웃바운드 AI 통화 어시스턴트입니다.\n\n"
                f"[통화 목적]\n{outbound_purpose}\n\n"
                f"{progress_block}\n\n"
                f"[대화 기록]\n{history}\n\n"
                f"{json_format_instruction}"
            )
            logger.info(
                "generate_response_outbound_prompt",
                outbound_purpose=outbound_purpose[:60],
                answered_count=len(answered),
                unanswered_count=len(unanswered),
                next_question=next_question[:60] if next_question else "",
                note="LLM JSON 단일 호출 — 응대 생성 + 답변 추출 동시 수행",
            )
        else:
            # ── 인바운드 기존 로직 ──
            org_name = _extract_org_name(org_context)
            chitchat_rule = ""
            _social = is_social_direct_path(state)
            if intent in ("chitchat", "greeting") or (_social and intent == "out_of_scope"):
                chitchat_rule = (
                    "9. [지금은 일상 말걸기·범위 밖 잡담입니다] 지식 문서에 없어도 됩니다. "
                    "1~2문장으로 짧게 공감하거나 가볍게 답하고, "
                    "업무 문의는 환영한다고 안내하세요. "
                    "「알지 못하는 내용입니다」 같은 한계 멘트는 쓰지 마세요."
                )

            # 설계 §14.2: 대화 단계·요약을 프롬프트에 주입
            stage_and_summary = _format_stage_and_summary(state)

            # 페르소나 description을 system_prompt에 주입 (업무 범위 명시 → LLM 응답 품질 향상)
            persona_context = ""
            _persona_owner_gr = state.get("_persona_owner") or state.get("_owner") or ""
            if _persona_owner_gr:
                try:
                    from src.ai_voicebot.knowledge.persona_service import get_persona_service
                    _ps = get_persona_service()
                    if _ps:
                        _p = await _ps.get_persona(_persona_owner_gr)
                        if _p and _p.enabled and _p.description:
                            persona_context = f"\n[업무 범위]\n{_p.description[:300]}\n"
                            logger.debug(
                                "generate_response_persona_injected",
                                persona_owner=_persona_owner_gr,
                                persona_name=_p.name,
                                desc_len=len(_p.description),
                            )
                except Exception as _pe:
                    logger.debug("generate_response_persona_load_skipped", error=str(_pe))

            system_prompt = RESPONSE_SYSTEM_PROMPT.format(
                org_name=org_name,
                persona_context=persona_context,
                org_context=org_context,
                stage_and_summary=stage_and_summary,
                history=history,
                rag_context=rag_context or "(관련 정보 없음)",
                chitchat_rule=chitchat_rule,
            )

        # 스트리밍 LLM 호출 (최적화 4.9: 문장 단위로 수집)
        request_sent_at = datetime.now().isoformat()
        logger.info("llm_request_sent",
                    call_site="generate_response_streaming",
                    request_sent_ts_iso=request_sent_at,
                    prompt_len=len(system_prompt) + len(user_query),
                    prompt_preview=user_query)

        chunks = []
        response = ""
        llm_first_sentence_elapsed_sec: Optional[float] = None
        llm_first_sentence_preview = ""
        llm_first_sentence_source = "none"
        try:
            has_streaming = hasattr(llm, "generate_response_streaming")
            if has_streaming:
                # async generator를 별도 태스크로 수집 — 파이프라인 CancelledError 시
                # aclose()가 executor 실행 중인 generator와 충돌하는 RuntimeError 방지
                llm_gen_t0 = time.perf_counter()

                async def _collect_streaming() -> list:
                    nonlocal llm_first_sentence_elapsed_sec, llm_first_sentence_preview, llm_first_sentence_source
                    result = []
                    async for sentence in llm.generate_response_streaming(
                        user_text=user_query,
                        context_docs=[rag_context] if rag_context else [],
                        system_prompt=system_prompt,
                    ):
                        if sentence:
                            if llm_first_sentence_elapsed_sec is None:
                                llm_first_sentence_elapsed_sec = time.perf_counter() - llm_gen_t0
                                llm_first_sentence_preview = sentence[:120]
                                llm_first_sentence_source = "streaming"
                                logger.info(
                                    "llm_first_sentence_ready",
                                    call_id=state.get("_call_id") or "",
                                    category="timing",
                                    progress="timing",
                                    elapsed_sec=round(llm_first_sentence_elapsed_sec, 3),
                                    sentence_preview=llm_first_sentence_preview,
                                    note="스트리밍 LLM 첫 문장 완성 — 조기 TTS 가정 시 이 시점부터 TTS 가능",
                                )
                            result.append(sentence)
                    return result

                collect_task = asyncio.create_task(_collect_streaming())
                try:
                    chunks = await collect_task
                except asyncio.CancelledError:
                    collect_task.cancel()
                    try:
                        await collect_task
                    except (asyncio.CancelledError, RuntimeError):
                        pass
                    raise
                response = " ".join(chunks)
            else:
                response = await llm.generate_response(
                    user_text=user_query,
                    context_docs=[rag_context] if rag_context else [],
                    system_prompt=system_prompt,
                )
                if response:
                    _first_chunks = _split_into_chunks(response)
                    if _first_chunks:
                        llm_first_sentence_preview = _first_chunks[0][:120]
                        llm_first_sentence_source = "batch_char_ratio_estimate"
                        _ratio = len(_first_chunks[0]) / max(len(response), 1)
                        llm_first_sentence_elapsed_sec = (time.time() - start) * _ratio
        except Exception as llm_err:
            elapsed_err = time.time() - start
            logger.warning("llm_request_failed",
                           call_site="generate_response_streaming",
                           request_sent_ts_iso=request_sent_at,
                           error_type=type(llm_err).__name__,
                           error_msg=str(llm_err),
                           elapsed_ms=round(elapsed_err * 1000))
            raise
        response_received_at = datetime.now().isoformat()

        # ── 아웃바운드: LLM JSON 파싱 (응대 + 답변 추출 분리) ──
        outbound_answered: List[Dict] = []   # rag_processor에서 _outbound_answers에 적용
        outbound_is_answer: bool = True      # 이번 발화가 유효한 답변인지
        if _is_outbound:
            response, outbound_answered, outbound_is_answer = _parse_outbound_llm_json(response)
            # 스트리밍으로 수집된 chunks에는 JSON 원문 파편이 들어 있으므로
            # 파싱 후 실제 response 텍스트로 chunks를 재생성한다 (TTS garbage 방지)
            chunks = _split_into_chunks(response) if response else []
            logger.info(
                "outbound_llm_answer_extracted",
                answered_count=len(outbound_answered),
                is_answer=outbound_is_answer,
                chunk_count=len(chunks),
                answered_preview=[
                    {"q": d["question"][:30], "a": d["answer"][:30]}
                    for d in outbound_answered
                ],
            )

        needs_follow_up = False

        # 인바운드: LLM이 JSON/마크다운 블록을 섞어 응답한 경우 정제
        # (아웃바운드는 _parse_outbound_llm_json에서 이미 처리됨)
        if not _is_outbound and response:
            response = _strip_json_and_markdown_for_tts(response)
            chunks = _split_into_chunks(response) if response else []

        if not response or not response.strip():
            response = "죄송합니다. 답변을 생성하지 못했습니다. 다시 말씀해 주시겠어요?"
            chunks = [response]
        elif _is_llm_error_fallback(response):
            logger.warning("generate_response_llm_error_fallback", response_preview=response,
                           is_outbound=_is_outbound)
            if _is_outbound:
                # 아웃바운드: LLM 오류 시에도 HITL 없이 재시도 유도 멘트
                response = "잠시 응답이 어려웠어요. 다시 한 번 말씀해 주시겠어요?"
                needs_follow_up = False
            elif _social or intent in ("chitchat", "out_of_scope", "greeting"):
                response = "잠시 응답이 어려웠어요. 편하게 이어서 말씀해 주세요."
                needs_follow_up = False
            else:
                response = RESPONSE_UNKNOWN_NEEDS_FOLLOWUP
                needs_follow_up = True
            chunks = [response]
        elif not _is_outbound and _is_unknown_content_response(response):
            # 아웃바운드: "알지 못하는 내용입니다" 패턴이어도 HITL 없이 그대로 출력
            # (착신자 답변 수집 중 LLM이 부자연스러운 응답을 낼 수 있음 — 미션 체크로 별도 처리)
            needs_follow_up = True
            if _social or intent in ("chitchat", "out_of_scope", "greeting"):
                needs_follow_up = False

        elapsed = time.time() - start
        if llm_first_sentence_elapsed_sec is None and response:
            _fc = _split_into_chunks(response)
            if _fc:
                llm_first_sentence_preview = _fc[0][:120]
                llm_first_sentence_source = "post_join_char_ratio_estimate"
                _ratio = len(_fc[0]) / max(len(response), 1)
                llm_first_sentence_elapsed_sec = elapsed * _ratio
        logger.info("llm_response_received",
                    call_site="generate_response_streaming",
                    request_sent_ts_iso=request_sent_at,
                    response_received_ts_iso=response_received_at,
                    elapsed_ms=round(elapsed * 1000),
                    response_len=len(response),
                    chunk_count=len(chunks))

        logger.info("timing_segment", segment="generate_response", elapsed_sec=round(elapsed, 3))
        logger.info("⏱️ [TIMING] generate_response (LLM 호출)",
                   query=user_query,
                   response_len=len(response),
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

        # Confidence 결정:
        # - 잡담/social → 0.9 (HITL 억제)
        # - LLM이 정상 답변 + needs_follow_up=False → 최소 0.5 보장
        #   (RAG score가 낮아도 LLM이 적절한 답변을 생성한 경우 불필요한 HITL 방지)
        # - 그 외 → RAG confidence 그대로
        if intent in ("greeting", "chitchat", "out_of_scope") or _social:
            confidence = 0.9
        else:
            rag_confidence = state.get("confidence", 0.0)
            if not needs_follow_up and response and len(response.strip()) > 10:
                confidence = max(rag_confidence, 0.5)
            else:
                confidence = rag_confidence

        # llm_exchange는 rag_processor에서 통화 단위로 기록 (중복 방지)
        _rag_src = "vector_knowledge" if rag_results else "llm_prompt_no_reference"

        return {
            "response": response,
            "response_chunks": chunks,
            "messages": updated_messages,
            "confidence": confidence,
            "needs_follow_up": needs_follow_up,
            "follow_up_user_query": user_query if needs_follow_up else "",
            # 아웃바운드 전용: LLM이 추출한 답변 목록 + 유효 답변 여부
            # rag_processor._process_with_agent에서 읽어 _outbound_answers에 직접 적용
            "outbound_answered": outbound_answered,
            "outbound_is_answer": outbound_is_answer,
            "llm_gen_elapsed_sec": round(elapsed, 4),
            "llm_first_sentence_elapsed_sec": (
                round(llm_first_sentence_elapsed_sec, 4)
                if llm_first_sentence_elapsed_sec is not None
                else None
            ),
            "llm_first_sentence_preview": llm_first_sentence_preview,
            "llm_first_sentence_source": llm_first_sentence_source,
            **_llm_exchange_rag_fields(state, rag_results, context_source=_rag_src),
        }

    except Exception as e:
        elapsed = time.time() - start
        logger.info("timing_segment", segment="generate_response", elapsed_sec=round(elapsed, 3), error=str(e))
        logger.error("response_generation_error", error=str(e), exc_info=True)
        _sd = is_social_direct_path(state)
        _intent = state.get("intent", "")
        if _sd or _intent in ("chitchat", "out_of_scope", "greeting"):
            _resp = "잠시 응답이 어려웠어요. 편하게 이어서 말씀해 주세요."
            _nfu = False
            _conf = 0.85
        else:
            _resp = RESPONSE_UNKNOWN_NEEDS_FOLLOWUP
            _nfu = True
            _conf = 0.0
        return {
            "response": _resp,
            "confidence": _conf,
            "needs_follow_up": _nfu,
            "follow_up_user_query": user_query if _nfu and user_query else "",
            **_llm_exchange_rag_fields(state, rag_results, context_source="llm_generation_error"),
        }


def _strip_json_and_markdown_for_tts(text: str) -> str:
    """LLM 응답에서 TTS에 부적합한 JSON/마크다운 블록을 제거한다.

    인바운드 generate_response 경로에서 LLM이 의도치 않게 JSON이나 코드블록을
    응답 앞에 붙이는 경우를 방지한다. (로그 line 64: ```json{...}``` 포함 TTS 송출 사례)

    처리 순서:
    1. ```json ... ``` 또는 ``` ... ``` 마크다운 코드블록 제거
    2. 응답 전체가 { } JSON 구조이면 → 내부 'response' 키 추출, 없으면 raw 반환
    3. 응답 앞부분에만 JSON 블록이 붙은 경우 → 블록 이후 텍스트만 사용
    """
    if not text:
        return text

    # 1. 마크다운 코드블록 제거
    cleaned = _re.sub(r"```(?:json)?\s*", "", text).replace("```", "").strip()

    # 2. JSON 블록이 앞에 있고 뒤에 일반 텍스트가 있는 경우 (ex: JSON\n실제응답)
    brace_start = cleaned.find("{")
    if brace_start != -1:
        depth = 0
        brace_end = -1
        for i, ch in enumerate(cleaned[brace_start:], brace_start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    brace_end = i
                    break

        if brace_end != -1:
            json_block = cleaned[brace_start: brace_end + 1]
            after_json = cleaned[brace_end + 1:].strip()

            # JSON 블록이 전체 텍스트인 경우 → 'response' 필드 추출 시도
            if brace_start == 0 and not after_json:
                try:
                    data = _json.loads(json_block)
                    if isinstance(data, dict):
                        if data.get("response"):
                            extracted = data["response"].strip()
                            logger.info(
                                "tts_response_json_extracted",
                                original_len=len(text),
                                extracted_len=len(extracted),
                                note="LLM이 JSON 형식으로 응답 — response 필드 추출 후 TTS 사용",
                            )
                            return extracted
                        # 'response' 키 없이 intent/search_query 등 메타 필드만 있는 JSON
                        # (ex: {"intent":"chitchat","search_query":"..."}) → TTS 송출 차단
                        _META_ONLY_KEYS = frozenset({
                            "intent", "search_query", "query", "action",
                            "category", "confidence", "slots", "rewritten_query",
                        })
                        data_keys = set(data.keys())
                        if data_keys and data_keys.issubset(_META_ONLY_KEYS):
                            logger.warning(
                                "tts_response_meta_json_blocked",
                                keys=sorted(data_keys),
                                note="분류/검색용 메타 JSON이 응답으로 나옴 — TTS 차단, 빈 문자열 반환",
                            )
                            return ""  # 상위에서 fallback 멘트 처리
                except (_json.JSONDecodeError, ValueError):
                    pass
                # JSON 파싱 실패 or 알 수 없는 구조 → 마크다운 제거 텍스트 그대로
                return cleaned

            # JSON 블록 앞에 텍스트 있거나, JSON 뒤에 실제 응답 있는 경우
            if after_json:
                logger.info(
                    "tts_response_json_prefix_stripped",
                    json_block_len=len(json_block),
                    after_text_len=len(after_json),
                    note="LLM 응답 앞 JSON 블록 제거 — 뒤 텍스트만 TTS 사용",
                )
                return after_json

    return cleaned


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
    """모르는 내용/한계 안내 문구인지 여부 (후처리·HITL 유도)."""
    if not text or len(text) < 10:
        return False
    t = text.strip()
    if HITL_CUSTOMER_TTS_MESSAGE in t:
        return True
    if RESPONSE_QUESTION_NO_KNOWLEDGE in t or (
        "알지 못하는 내용" in t and "죄송" in t
    ):
        return True
    # 구버전 LLM/캐시 호환
    if "잠시만 기다려" in t and "확인" in t:
        return True
    return (
        "모르는 내용" in t
        and ("확인이 필요" in t or "확인 후" in t or "연락드리면" in t)
    )


MAX_RAG_CONTEXT_FOR_LLM = 3

# [B] 인사말/안내 카테고리 문서는 질문 응답 컨텍스트에 포함하면 LLM이 혼란을 일으킴
# (예: "저는 날씨/태풍정보/기상감정서 발급…" 같은 greeting_phase2 문서가 섞이면
#  LLM이 "날씨만 안내 가능" 패턴을 강화하여 실제 관련 지식을 무시하는 경향)
_RAG_CONTEXT_EXCLUDED_CATEGORIES = frozenset({
    "greeting_phase1",
    "greeting_phase2",
    "farewell",
})


def _format_rag_context(results: list) -> str:
    if not results:
        return ""
    lines = []
    excluded = 0
    for doc in results:
        if len(lines) >= MAX_RAG_CONTEXT_FOR_LLM:
            break
        if isinstance(doc, dict):
            cat = doc.get("category", "") or ""
            text = doc.get("text", "")
        else:
            cat = getattr(doc, "category", "") or ""
            text = str(doc)
        if cat in _RAG_CONTEXT_EXCLUDED_CATEGORIES:
            excluded += 1
            logger.debug(
                "rag_context_category_excluded",
                category=cat,
                text_preview=(text or "")[:60],
                note="인사말/작별 카테고리는 질문 응답 컨텍스트에서 제외",
            )
            continue
        if text:
            lines.append(f"[{len(lines)+1}] {text}")
    if excluded:
        logger.info(
            "rag_context_excluded_count",
            excluded=excluded,
            kept=len(lines),
            note="greeting/farewell 카테고리 문서 LLM 컨텍스트 제외",
        )
    return "\n".join(lines)


# [D] AI 히스토리에서 제외할 fallback/오류 응답 패턴
# 이런 메시지가 히스토리에 남으면 LLM이 같은 방향으로 응답을 고수하는 경향 발생
_HISTORY_FALLBACK_PATTERNS = (
    "알지 못하는 내용",
    "해당 내용은 제가",
    "자세한 정보는 드리기 어렵",
    "안내드리기 어렵",
    "도움을 드리기 어렵",
    "답변을 생성하지 못했",
    "잠시 후 다시 시도",
)


def _is_ai_fallback_message(content: str) -> bool:
    """AI 응답이 fallback/거부 멘트인지 판단."""
    return any(p in content for p in _HISTORY_FALLBACK_PATTERNS)


def _format_history(messages: list, max_turns: int = 6) -> str:
    recent = messages[-(max_turns * 2):]
    lines = []
    fallback_filtered = 0
    for msg in recent:
        role_raw = msg.get("role", "")
        content = msg.get("content", "")
        role = "사용자" if role_raw == "user" else "AI"
        # [D] AI의 fallback 멘트는 히스토리에서 제외 → LLM이 이전 거부 패턴을 반복하는 현상 방지
        if role == "AI" and _is_ai_fallback_message(content):
            fallback_filtered += 1
            logger.debug(
                "history_fallback_filtered",
                content_preview=content[:60],
                note="AI fallback 멘트 히스토리 제외 — LLM 거부 패턴 반복 방지",
            )
            continue
        lines.append(f"{role}: {content}")
    if fallback_filtered:
        logger.info(
            "history_fallback_filtered_count",
            count=fallback_filtered,
            note="이전 AI fallback 응답을 LLM 히스토리에서 제거",
        )
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
    [DEPRECATED] 문장 단위 청크 분리 (Streaming RAG TTS용).
    
    Google TTS는 streaming 미지원 → 청크 분할 시 각 청크마다 별도 API 호출로
    레이턴시 누적 및 재생 버퍼 고갈 발생. 인사말처럼 전체 텍스트를 한 번에 전송해야 함.
    """
    if not text:
        return []
    # 마침표, 물음표, 느낌표, 쉼표+공백으로 분리
    import re
    sentences = re.split(r'(?<=[.?!])\s+', text)
    return [s.strip() for s in sentences if s.strip()]


# ── 아웃바운드 LLM JSON 응답 파싱 ──

def _parse_outbound_llm_json(raw: str) -> Tuple[str, List[Dict], bool]:
    """아웃바운드 LLM 응답(JSON)에서 response/answered/is_answer를 추출한다.

    LLM이 JSON 외 텍스트를 섞거나 마크다운 코드 블록으로 감싼 경우도 처리한다.

    Returns:
        (response_text, answered_list, is_answer)
        파싱 실패 시 (raw 전체, [], True) — 안전하게 TTS 출력은 보장
    """
    if not raw:
        return ("", [], True)

    # 마크다운 코드 블록 제거 (```json ... ``` 또는 ``` ... ```)
    cleaned = _re.sub(r"```(?:json)?\s*", "", raw).replace("```", "").strip()

    # { } 범위 추출 (중첩 깊이 추적)
    start = cleaned.find("{")
    if start == -1:
        # JSON 없음 → raw 전체를 response로 사용
        logger.warning("outbound_llm_json_no_brace", raw_preview=raw[:120])
        return (raw.strip(), [], True)

    depth = 0
    end = -1
    for i, ch in enumerate(cleaned[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break

    if end == -1:
        logger.warning("outbound_llm_json_unclosed", raw_preview=raw[:120])
        return (raw.strip(), [], True)

    try:
        data = _json.loads(cleaned[start : end + 1])
    except (_json.JSONDecodeError, ValueError) as e:
        logger.warning("outbound_llm_json_parse_error", error=str(e), raw_preview=raw[:120])
        return (raw.strip(), [], True)

    response_text = (data.get("response") or "").strip()
    answered_raw = data.get("answered") or []
    is_answer = bool(data.get("is_answer", True))

    # answered 형식 검증: [{"question": ..., "answer": ...}]
    answered: List[Dict] = []
    if isinstance(answered_raw, list):
        for item in answered_raw:
            if isinstance(item, dict):
                q = (item.get("question") or "").strip()
                a = (item.get("answer") or "").strip()
                if q and a:
                    answered.append({"question": q, "answer": a})

    if not response_text:
        # response 필드가 비었으면 raw 전체를 fallback으로 사용
        logger.warning(
            "outbound_llm_json_empty_response",
            answered_count=len(answered),
            raw_preview=raw[:120],
        )
        response_text = raw.strip()

    logger.info(
        "outbound_llm_json_parsed",
        response_len=len(response_text),
        answered_count=len(answered),
        is_answer=is_answer,
    )
    return (response_text, answered, is_answer)
