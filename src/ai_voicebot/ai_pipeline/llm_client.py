"""
Google Gemini LLM Client

대화 생성 및 지식 유용성 판단
"""

import time

# Gemini import 추적
_import_logger_available = False
_genai_import_start: float | None = None
try:
    import structlog
    _logger = structlog.get_logger(__name__)
    _import_logger_available = True
    _logger.info("🔄 [LLM Module] Importing google.generativeai...")
    _genai_import_start = time.time()
except Exception:
    pass

import google.generativeai as genai

if _import_logger_available and _genai_import_start is not None:
    _genai_import_time = time.time() - _genai_import_start
    _logger.info(f"✅ [LLM Module] google.generativeai imported", elapsed=f"{_genai_import_time:.3f}s")

import asyncio
import re
from typing import List, Dict, Optional, Any
import json

logger = structlog.get_logger(__name__)


class LLMClient:
    """
    Google Gemini LLM Client
    
    대화 생성 및 지식 유용성 판단을 제공합니다.
    """
    
    def __init__(self, config: dict, api_key: str):
        """
        Args:
            config: LLM 설정
                - model: 기본 gemini-2.5-flash-lite
                - temperature: 0.7
                - max_tokens / max_output_tokens: 기본 512 (통화 응답·짧은 호출 공통 상한)
                - top_p: 1.0
                - top_k: 1
            api_key: Google API 키
        """
        self.config = config
        
        # Gemini 설정
        genai.configure(api_key=api_key)
        
        model_name = config.get("model", "gemini-2.5-flash-lite")
        self.model = genai.GenerativeModel(model_name=model_name)
        
        # Generation 설정 (max_output_tokens: config.yaml 키, max_tokens: 구 설정 호환)
        # thinking은 모든 호출에서 비활성화 — 통화 응대·의도분류 등 어떤 작업도 내부 추론이 불필요하며
        # thinking 활성 시 TTFT 3~6초 지연이 발생한다.
        max_tokens = config.get("max_output_tokens") or config.get("max_tokens", 512)
        _init_kw: Dict[str, Any] = {
            "temperature": config.get("temperature", 0.7),
            "top_p": config.get("top_p", 1.0),
            "top_k": config.get("top_k", 1),
            "max_output_tokens": max_tokens,
        }
        try:
            _init_kw["thinking_config"] = genai.types.ThinkingConfig(thinking_budget=0)
        except (AttributeError, TypeError):
            pass
        self.generation_config = genai.types.GenerationConfig(**_init_kw)
        
        # 대화 히스토리
        self.conversation_history: List[Dict[str, str]] = []
        self.max_history_length = config.get("max_history_length", 20)
        
        # 통계
        self.total_requests = 0
        self.total_tokens = 0
        
        logger.info("LLMClient initialized", 
                   model=model_name,
                   temperature=config.get("temperature"))
    
    @staticmethod
    def _thinking_off() -> Any:
        """Gemini 2.5 Flash/Pro thinking을 완전 비활성화하는 ThinkingConfig 객체.

        모든 LLM 호출에 적용한다. 통화 응대·의도 분류·쿼리 변환·지식 정제 등
        어떤 작업도 내부 추론(reasoning token)이 필요할 만큼 복잡하지 않으며,
        thinking이 활성화되면 짧은 응답도 TTFT 3~6초 지연이 발생한다.
        """
        try:
            return genai.types.ThinkingConfig(thinking_budget=0)
        except (AttributeError, TypeError):
            logger.debug(
                "llm_thinking_config_not_supported",
                note="google-generativeai SDK가 ThinkingConfig를 지원하지 않음 — 무시",
            )
            return None

    def _effective_generation_config(self, max_output_tokens: Optional[int] = None) -> Any:
        """호출별 GenerationConfig. thinking은 항상 비활성(thinking_budget=0)."""
        base = self.config.get("max_output_tokens") or self.config.get("max_tokens", 512)
        cap = int(max_output_tokens) if max_output_tokens is not None else int(base)
        kwargs: Dict[str, Any] = {
            "temperature": self.config.get("temperature", 0.7),
            "top_p": self.config.get("top_p", 1.0),
            "top_k": self.config.get("top_k", 1),
            "max_output_tokens": max(16, cap),
        }
        tc = self._thinking_off()
        if tc is not None:
            kwargs["thinking_config"] = tc
        return genai.types.GenerationConfig(**kwargs)
    
    async def generate_simple(self, prompt: str, max_tokens: Optional[int] = None, timeout_seconds: float = 10.0) -> str:
        """
        간단한 프롬프트로 LLM 응답 생성 (HITL 응답 다듬기 등).
        
        Args:
            prompt: 프롬프트 텍스트
            max_tokens: 최대 토큰 수 (기본값은 설정값 사용)
            timeout_seconds: API 타임아웃 (기본 10초)
            
        Returns:
            생성된 텍스트
        """
        try:
            gen_config = self._effective_generation_config(max_tokens)
            
            # ✅ 타임아웃 추가
            try:
                response = await asyncio.wait_for(
                    asyncio.to_thread(
                        self.model.generate_content,
                        prompt,
                        generation_config=gen_config,
                    ),
                    timeout=timeout_seconds
                )
            except asyncio.TimeoutError:
                logger.error("llm_generate_simple_timeout",
                           timeout_seconds=timeout_seconds,
                           note="간단한 LLM 호출 타임아웃")
                return ""
            
            self.total_requests += 1
            return response.text.strip() if response and response.text else ""
            
        except Exception as e:
            logger.error("llm_generate_simple_failed", error=str(e))
            return ""

    async def generate_help_items_json(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        timeout_seconds: float = 22.0,
    ) -> tuple[str, bool]:
        """
        help 의도 전용: JSON만 출력하도록 유도 + 가능 시 response_mime_type=application/json.

        Returns:
            (raw_text, json_mode_applied) — json_mode_applied는 API에 JSON MIME을 붙였는지 여부.
        """
        json_mode_applied = False
        try:
            tc = self._thinking_off()
            base_kw: Dict[str, Any] = {
                "temperature": 0.05,
                "top_p": 0.9,
                "top_k": 1,
                "max_output_tokens": max(128, int(max_tokens)),
            }
            if tc is not None:
                base_kw["thinking_config"] = tc
            try:
                gen_config = genai.types.GenerationConfig(
                    **base_kw,
                    response_mime_type="application/json",
                )
                json_mode_applied = True
            except TypeError:
                gen_config = genai.types.GenerationConfig(**base_kw)
                logger.info(
                    "help_llm_json_mime_unsupported",
                    note="GenerationConfig에 response_mime_type 미지원 — 저온·짧은 출력만 적용",
                )

            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self.model.generate_content,
                    prompt,
                    generation_config=gen_config,
                ),
                timeout=timeout_seconds,
            )
            self.total_requests += 1
            text = response.text.strip() if response and response.text else ""
            _fr = None
            try:
                cands = getattr(response, "candidates", None) or []
                if cands:
                    _fr = getattr(cands[0], "finish_reason", None)
            except Exception:
                pass
            logger.info(
                "help_llm_generate_done",
                json_mode_applied=json_mode_applied,
                raw_len=len(text),
                finish_reason=str(_fr) if _fr is not None else None,
                note="근본: JSON MIME+저온으로 자연어+배열 혼합·토큰 절단을 억제",
            )
            return text, json_mode_applied
        except asyncio.TimeoutError:
            logger.error(
                "help_llm_generate_timeout",
                timeout_seconds=timeout_seconds,
            )
            return "", json_mode_applied
        except Exception as e:
            logger.error("help_llm_generate_failed", error=str(e))
            return "", json_mode_applied

    async def generate_response(
        self, 
        user_text: str, 
        context_docs: List[str],
        system_prompt: Optional[str] = None,
        call_id: Optional[str] = None,  # DB 로깅용
        timeout_seconds: float = 30.0,  # ✅ API 타임아웃 설정
        max_output_tokens: Optional[int] = None,
    ) -> str:
        """
        사용자 입력에 대한 답변 생성
        
        Args:
            user_text: 사용자 질문
            context_docs: RAG 검색 결과 (관련 문서)
            system_prompt: 시스템 프롬프트 (선택)
            call_id: 통화 ID (DB 로깅용, 선택)
            timeout_seconds: Gemini API 타임아웃 (기본 30초)
            max_output_tokens: 이번 호출만 출력 토큰 상한(의도분류·쿼리변환 등은 작게). None이면 설정 기본값.
            
        Returns:
            생성된 답변 텍스트
        """
        import time
        start_time = time.time()
        
        try:
            # 프롬프트 조립
            prompt = self._build_conversation_prompt(
                user_text, 
                context_docs, 
                system_prompt
            )
            
            gen_cfg = self._effective_generation_config(max_output_tokens)
            
            # ✅ Gemini API 호출 (비동기 + 타임아웃)
            loop = asyncio.get_event_loop()
            try:
                response = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda: self.model.generate_content(
                            prompt,
                            generation_config=gen_cfg
                        )
                    ),
                    timeout=timeout_seconds
                )
            except asyncio.TimeoutError:
                logger.error("llm_api_timeout",
                           call=True,
                           call_id=call_id or "",
                           timeout_seconds=timeout_seconds,
                           note="Gemini API 타임아웃 → Fallback 응답 사용")
                # Fallback 응답
                return "죄송합니다. 일시적으로 처리가 지연되고 있습니다. 잠시 후 다시 질문해 주시거나, 담당자 연결이 필요하시면 말씀해 주세요."
            
            # 응답 텍스트 추출
            answer = (response.text or "").strip()

            # 종료 사유 로깅 (MAX_TOKENS 시 응답 잘림 원인 파악용)
            finish_reason = None
            try:
                if getattr(response, "candidates", None) and len(response.candidates) > 0:
                    finish_reason = getattr(response.candidates[0], "finish_reason", None)
            except Exception:
                pass
            if finish_reason is not None:
                fr_map = {1: "STOP", 2: "MAX_TOKENS", 3: "SAFETY", 4: "RECITATION"}
                fr_desc = fr_map.get(int(finish_reason), str(finish_reason))
                # STOP(정상)일 때는 info 로그 생략 — note의 'MAX_TOKENS=잘림'으로 오해 방지
                if fr_desc != "STOP":
                    logger.info("llm_generate_response_finish_reason",
                               call=True,
                               call_id=call_id or "",
                               finish_reason=fr_desc,
                               response_len=len(answer),
                               max_output_tokens=getattr(gen_cfg, "max_output_tokens", self.config.get("max_output_tokens")),
                               note="STOP=정상, MAX_TOKENS=해당 시 잘림")
                if fr_desc == "MAX_TOKENS":
                    logger.warning("llm_response_truncated_max_tokens",
                                  call=True,
                                  call_id=call_id or "",
                                  response_len=len(answer),
                                  max_output_tokens=getattr(gen_cfg, "max_output_tokens", self.config.get("max_output_tokens")),
                                  note="응답이 max_output_tokens에서 잘림. config max_output_tokens 상향 권장(예: 1024).")
            
            # 대화 히스토리 업데이트
            self.conversation_history.append({
                "role": "user",
                "content": user_text
            })
            self.conversation_history.append({
                "role": "assistant",
                "content": answer
            })
            
            # 히스토리 제한
            if len(self.conversation_history) > self.max_history_length:
                self.conversation_history = self.conversation_history[-self.max_history_length:]
            
            # 통계 업데이트
            self.total_requests += 1
            # 토큰 수 추정 (실제 API에서 제공하는 경우 해당 값 사용)
            tokens_used = len(prompt.split()) + len(answer.split())
            self.total_tokens += tokens_used
            
            # 처리 시간 계산
            latency_ms = int((time.time() - start_time) * 1000)
            
            # 신뢰도 계산 (간단한 휴리스틱)
            confidence = self._calculate_confidence(answer, context_docs)
            
            logger.info("LLM response generated",
                       call=True,
                       progress="llm",
                       user_text_length=len(user_text),
                       response_length=len(answer),
                       context_docs_count=len(context_docs),
                       latency_ms=latency_ms,
                       confidence=confidence)
            
            # DB 로깅 (신규)
            if call_id:
                try:
                    from ..logging.ai_logger import log_llm_process_sync
                    
                    log_llm_process_sync(
                        call_id=call_id,
                        input_prompt=prompt,
                        output_text=answer,
                        confidence=confidence,
                        latency_ms=latency_ms,
                        tokens_used=tokens_used,
                        model_name=self.config.get("model", "gemini-2.5-flash-lite"),
                        temperature=self.config.get("temperature", 0.7)
                    )
                except ImportError:
                    logger.debug("AI logger not available, skipping DB logging")
                except Exception as e:
                    logger.error("Failed to log LLM process to DB", error=str(e))
            
            return answer
            
        except Exception as e:
            logger.error("LLM generation error", error=str(e), exc_info=True)
            return "죄송합니다, 답변을 생성하는 중 오류가 발생했습니다."

    async def generate_response_streaming(
        self,
        user_text: str,
        context_docs: List[str],
        system_prompt: Optional[str] = None,
        timeout_seconds: float = 30.0,
        max_output_tokens: Optional[int] = None,
    ):
        """
        스트리밍 LLM 응답 생성. 문장 단위로 yield.

        Yields:
            str: 완성된 문장 (마침표/물음표/느낌표로 끝나는 단위)
        """
        import re as _re

        prompt = self._build_conversation_prompt(user_text, context_docs, system_prompt)
        gen_cfg = self._effective_generation_config(max_output_tokens)

        buffer = ""
        try:
            loop = asyncio.get_event_loop()
            response = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: self.model.generate_content(
                        prompt,
                        generation_config=gen_cfg,
                        stream=True,
                    )
                ),
                timeout=timeout_seconds,
            )

            for chunk in response:
                text = getattr(chunk, "text", "") or ""
                if not text:
                    continue
                buffer += text
                while True:
                    match = _re.search(r"[.?!。]\s*", buffer)
                    if not match:
                        break
                    end = match.end()
                    sentence = buffer[:end].strip()
                    buffer = buffer[end:]
                    if sentence:
                        yield sentence

            if buffer.strip():
                yield buffer.strip()

            self.total_requests += 1
        except asyncio.TimeoutError:
            logger.error("llm_streaming_timeout", timeout_seconds=timeout_seconds)
            if buffer.strip():
                yield buffer.strip()
            else:
                yield "죄송합니다. 일시적으로 처리가 지연되고 있습니다."
        except Exception as e:
            logger.error("llm_streaming_error", error=str(e))
            if buffer.strip():
                yield buffer.strip()
            else:
                yield "죄송합니다, 답변을 생성하는 중 오류가 발생했습니다."

    async def format_for_customer(self, raw_text: str) -> str:
        """
        HITL 담당자 답변을 고객에게 전달할 한 문장으로 정리 (설계 TTS_RTP_AND_HITL_DESIGN.md).
        대화 히스토리는 건드리지 않음.
        """
        if not raw_text or not raw_text.strip():
            return raw_text
        prompt = (
            "다음은 상담 담당자가 고객에게 전달할 내용입니다. "
            "고객에게 자연스럽게 말할 한 문장으로만 정리해 주세요. 다른 설명은 붙이지 마세요.\n\n"
            f"담당자 원문:\n{raw_text.strip()}"
        )
        try:
            tc = self._thinking_off()
            fmt_kw: Dict[str, Any] = {"max_output_tokens": 256, "temperature": 0.3}
            if tc is not None:
                fmt_kw["thinking_config"] = tc
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.model.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(**fmt_kw),
                ),
            )
            return (response.text or raw_text).strip()
        except Exception as e:
            logger.warning("format_for_customer_failed", error=str(e))
            return raw_text

    async def format_hitl_reply_for_customer(
        self,
        customer_question: str,
        operator_reply: str,
        timeout_seconds: float = 30.0,
    ) -> str:
        """
        HITL 운영자 답변 + 고객 질문 맥락 → 통화용 멘트 (TTS).
        고객 질문이 있으면 **짧게 짚어 준 뒤** 답을 이어 말하도록 유도한다.
        """
        op = (operator_reply or "").strip()
        if not op:
            return operator_reply or ""
        cq = (customer_question or "").strip()
        if cq:
            prompt = (
                "전화 통화 AI 비서입니다. 아래 [담당자 확인 내용]만 사실로 취급하고, "
                "고객에게 들려줄 한국어 멘트를 작성하세요.\n\n"
                "구성(필수):\n"
                "1) 고객이 물었던 내용을 한 문장(또는 짧은 두 문장)으로 자연스럽게 요약·짚어 주세요. "
                "질문을 그대로 읽기보다는 대화체로 바꿔도 됩니다.\n"
                "2) 이어서 담당자 확인 내용을 전달하세요.\n\n"
                "금지 표현(쓰지 마세요): "
                '"확인해드렸습니다", "확인해 드렸습니다", "확인되어 알려드립니다", '
                '"아까 문의 주신", "말씀하신 내용에 대해"\n'
                "불필요한 사과·형식적 접두어는 줄이고, 정보를 담담하게 전달하세요.\n"
                "전체 2~4문장 정도로, TTS로 읽기 좋게 마침표로 끊어 주세요.\n\n"
                f"고객 질문:\n{cq}\n\n"
                f"담당자 확인 내용:\n{op}\n\n"
                "고객에게 들려줄 멘트만 출력하세요."
            )
        else:
            prompt = (
                "전화 통화 AI 비서입니다. 아래 [담당자 확인 내용]만 사실로 취급하고, "
                "고객에게 말할 한국어 멘트를 1~2문장으로 작성하세요.\n\n"
                "금지 표현(쓰지 마세요): "
                '"확인해드렸습니다", "확인해 드렸습니다", "확인되어 알려드립니다", '
                '"아까 문의 주신", "말씀하신 내용에 대해"\n'
                "불필요한 사과·형식적 접두어는 줄이고, 정보를 담담하게 전달하세요.\n\n"
                f"담당자 확인 내용:\n{op}\n\n"
                "고객 멘트만 출력하세요."
            )
        # HITL 멘트는 질문+담당자 답이 길 수 있음. 상한은 넉넉히 — 잘리면 TTS가 중간에서 끊김.
        hitl_fmt_max = int(
            self.config.get("hitl_format_max_output_tokens")
            or self.config.get("hitl_format_max_tokens")
            or 2048
        )
        hitl_fmt_max = max(256, min(hitl_fmt_max, 8192))
        hitl_kw: Dict[str, Any] = {"max_output_tokens": hitl_fmt_max, "temperature": 0.35}
        tc = self._thinking_off()
        if tc is not None:
            hitl_kw["thinking_config"] = tc
        gen_config = genai.types.GenerationConfig(**hitl_kw)
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self.model.generate_content,
                    prompt,
                    generation_config=gen_config,
                ),
                timeout=timeout_seconds,
            )
            out = (response.text or "").strip() if response else ""
            if not out:
                logger.warning(
                    "format_hitl_reply_empty",
                    operator_len=len(op),
                    note="LLM 빈 응답 → 담당자 원문 사용",
                )
                return op
            finish_reason = None
            try:
                if getattr(response, "candidates", None) and len(response.candidates) > 0:
                    finish_reason = getattr(response.candidates[0], "finish_reason", None)
            except Exception:
                pass
            fr_is_max_tokens = False
            if finish_reason is not None:
                try:
                    fr_is_max_tokens = int(finish_reason) == 2
                except (TypeError, ValueError):
                    fr_is_max_tokens = str(finish_reason).endswith("MAX_TOKENS")
            if fr_is_max_tokens:
                # 말미 마침표 등 없고 짧으면 상한 도달로 중간 끊김 가능성 큼 → 담당자 원문 TTS
                looks_cut = (len(out) < 80) or (
                    not re.search(r"[.!?。…」』]\s*$", out)
                )
                if looks_cut:
                    logger.warning(
                        "format_hitl_reply_truncated_max_tokens",
                        response_len=len(out),
                        operator_len=len(op),
                        max_output_tokens=hitl_fmt_max,
                        note="출력 상한·문장 미완으로 보임 → 담당자 원문으로 TTS",
                    )
                    return op
                logger.warning(
                    "format_hitl_reply_truncated_max_tokens_tail",
                    response_len=len(out),
                    operator_len=len(op),
                    max_output_tokens=hitl_fmt_max,
                    note="MAX_TOKENS이나 문장 종결 있음 — 생성문 사용(말미만 잘렸을 수 있음)",
                )
            return out
        except asyncio.TimeoutError:
            logger.warning("format_hitl_reply_timeout", timeout_seconds=timeout_seconds)
            return op
        except Exception as e:
            logger.warning("format_hitl_reply_failed", error=str(e))
            return op

    def _calculate_confidence(self, answer: str, context_docs: List[str]) -> float:
        """
        LLM 응답의 신뢰도 계산 (간단한 휴리스틱)
        
        Args:
            answer: LLM 응답
            context_docs: 참고한 컨텍스트 문서
            
        Returns:
            신뢰도 (0.0 ~ 1.0)
        """
        confidence = 0.5  # 기본값
        
        # 컨텍스트 문서가 있으면 신뢰도 상승
        if context_docs:
            confidence += 0.3
        
        # 답변이 길면 신뢰도 상승 (구체적인 답변)
        if len(answer) > 50:
            confidence += 0.1
        
        # "모르"나 "확인"이 있으면 신뢰도 하락
        if "모르" in answer or "확인" in answer:
            confidence -= 0.2
        
        return max(0.0, min(1.0, confidence))
    
    def _build_conversation_prompt(
        self, 
        user_text: str, 
        context_docs: List[str],
        system_prompt: Optional[str] = None
    ) -> str:
        """대화 프롬프트 조립"""
        # 기본 시스템 프롬프트
        if not system_prompt:
            system_prompt = (
                "당신은 친절하고 정확한 AI 비서입니다. "
                "제공된 정보를 기반으로 답변하고, "
                "모르는 내용은 솔직히 모른다고 답변하세요. "
                "답변은 1-2문장으로 간결하게 해주세요."
            )
        
        # 컨텍스트 문서
        context_str = ""
        if context_docs:
            context_str = "\n\n**참고 정보:**\n" + "\n".join([
                f"- {doc}" for doc in context_docs[:3]  # 최대 3개
            ])
        
        # 대화 히스토리
        history_str = ""
        if self.conversation_history:
            recent_history = self.conversation_history[-10:]  # 최근 5턴 (10개 메시지)
            history_str = "\n\n**이전 대화:**\n" + "\n".join([
                f"{'사용자' if msg['role'] == 'user' else 'AI'}: {msg['content']}"
                for msg in recent_history
            ])
        
        # 전체 프롬프트
        prompt = f"""{system_prompt}
{context_str}
{history_str}

**현재 질문:**
사용자: {user_text}

AI:"""
        
        return prompt
    
    async def judge_barge_in(
        self,
        user_text: str,
        ai_current_text: str = "",
    ) -> str:
        """
        Barge-in 판단 (Phase 3): 사용자 발화가 맞장구인지 interrupt인지 LLM이 판단.
        
        Args:
            user_text: 사용자가 말한 내용
            ai_current_text: AI가 현재 말하고 있는 내용
            
        Returns:
            "맞장구" 또는 "interruption"
        """
        try:
            prompt = (
                'AI가 고객에게 설명을 하고 있는 중에 고객이 아래와 같이 말했습니다.\n\n'
                f'AI가 말하고 있는 내용: "{ai_current_text[:200]}"\n'
                f'고객이 말한 내용: "{user_text}"\n\n'
                '고객의 말이 다음 중 어디에 해당하는지 판단하세요:\n'
                '1. "맞장구" - 듣고 있다는 표시 (예: "네", "음", "그렇군요", "아~")\n'
                '2. "interruption" - 말을 끊고 새로운 요청/질문을 하려는 의도\n\n'
                '답변: "맞장구" 또는 "interruption" 중 하나만 출력하세요.'
            )

            barge_kw: Dict[str, Any] = {"temperature": 0.1, "max_output_tokens": 10}
            tc = self._thinking_off()
            if tc is not None:
                barge_kw["thinking_config"] = tc
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.model.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(**barge_kw),
                ),
            )

            result = response.text.strip().lower().replace('"', '').replace("'", "")

            if "interruption" in result:
                return "interruption"
            return "맞장구"

        except Exception as e:
            logger.warning("judge_barge_in_error", error=str(e))
            # 오류 시 안전하게 interrupt로 판단 (사용자 의도 우선)
            return "interruption"

    async def judge_usefulness(
        self,
        transcript: str,
        speaker: str = "callee",
        call_id: str = "",
    ) -> Dict[str, Any]:
        """
        통화정보 중 지식정보 정제 (지식 추출용).
        통화 전사에서 저장할 지식 단위를 추출·분류한다. (구 명칭: 유용성 판단)

        Args:
            transcript: 통화 전체 전사 (발신자+착신자). 질문자 무관하게 Q&A 쌍 전체를 추출.
            speaker: 화자 필터 (현재는 프롬프트에서 사용하지 않음 — 양측 발화에서 Q&A 추출).
            call_id: 통화 ID (로그 call 키용)

        Returns:
            {
                "is_useful": bool,
                "confidence": float,
                "reason": str,
                "extracted_info": List[Dict]
            }
        """
        result_text = ""
        json_text = ""
        # 지식 정제 전용 상한 (일반 max_tokens에 영향받지 않도록 judgment_max_output_tokens만 사용, 기본 4096)
        judgment_max_tokens = self.config.get("judgment_max_output_tokens")
        if judgment_max_tokens is None:
            judgment_max_tokens = 4096
        # 설계서 2.2a: 긴 통화 토큰/길이 처리 — 설정 가능 문자 상한 (기본 6000)
        max_input_chars = self.config.get("judgment_max_input_chars", 6000)
        transcript_for_prompt = transcript[:max_input_chars]
        if len(transcript) > max_input_chars:
            transcript_for_prompt += "\n\n[이하 생략: 통화가 길어 앞부분만 사용했습니다.]"
        try:
            prompt = f"""당신은 통화 기록에서 지식 베이스(VectorDB)에 저장할 지식 정보를 정제(추출·분류)하는 전문가입니다. 목적: AI 비서가 이후 통화에서 재사용할 수 있는 지식만 추출합니다.

**입력 형식:** 아래는 "발신자:", "착신자:"로 구분된 **전체 대화** 전사입니다.

**저장 대상:** 질문과 답변을 하나의 지식 단위로 묶어 추출하세요. 질문자가 발신자든 착신자든 관계없이, **재사용 가능한 지식(Q&A 쌍, 사실 정보 등)이 있으면 추출**합니다.
- FAQ 항목은 "Q: 질문\nA: 답변" 형식으로 text에 포함하세요.
- 개인정보(이름·전화번호·주소 등)가 없는 재사용 가능한 정보를 우선합니다.

**중요: 텍스트 정제 규칙**
- extracted_info의 text는 **STT 원문을 그대로 복사하지 마세요**
- **띄어쓰기·맞춤법을 교정**하고, **자연스러운 문장으로 정리**하세요
- **의미는 보존**하되, **읽기 쉽고 재사용하기 좋은 형태**로 작성하세요
- 예시:
  - ❌ STT 원문: "네 내일 오 전 에 방 문 하 시 면 됩 니 다"
  - ✅ 정제된 텍스트: "내일 오전에 방문하시면 됩니다."
  - ❌ FAQ 미완성: "세트 메뉴도 판매하나요?" (답변 없음)
  - ✅ FAQ 완성: "Q: 세트 메뉴도 판매하나요?\nA: 네, 파스타와 피자 세트 메뉴를 판매합니다."

**유용하다고 판단할 경우 (is_useful = true):**
- 실행 가능한 질문·답변 (구체적 사실, 절차, 조건이 포함된 경우)
- 다른 통화에서도 재사용 가능한 FAQ 성격의 대화
- 문의/이슈에 대한 해결 방법·다음 단계가 명확한 경우
- 약속·일정·연락처·업무 지시·선호도 등 재사용 가능한 정보 (개인정보는 저장 시 별도 정책 적용)

**유용하지 않다고 판단할 경우 (is_useful = false):**
- 개인을 특정할 수 있는 정보만 있는 경우 (이름, 전화번호, 주소 등)
- 인사, 맞장구, "날씨가 좋네요" 등 지식으로 쓸 내용이 없는 경우
- "확인 후 연락드리겠습니다", "잘 모르겠습니다" 등 미해결·유보만 있는 경우
- 사실·절차 없이 불만·칭찬 등 감정 표현만 있는 경우

**통화 내용 (전체 대화):**
{transcript_for_prompt}

**출력 형식 (JSON만 출력):**
{{
  "is_useful": true 또는 false,
  "confidence": 0.0~1.0,
  "reason": "판단 이유 (50자 이내)",
  "extracted_info": [
    {{
      "text": "FAQ는 'Q: 질문\\nA: 답변' 형식, 그 외는 정제된 정보 텍스트",
      "category": "FAQ|이슈해결|약속|정보|지시|선호도|기타",
      "keywords": ["키워드1", "키워드2"],
      "contains_pii": false
    }}
  ]
}}

**category 규칙 (반드시 아래 중 하나만 사용):**
- FAQ: 재사용 가능한 질문·답변 쌍 (Q&A 모두 포함)
- 이슈해결: 문의/불만에 대한 해결 방법·다음 단계가 명확한 경우
- 약속: 일시·장소·담당자 등 구체적 약속
- 정보: 영업시간, 절차, 조건 등 사실 정보
- 지시: 업무 지시, "항상 A로 해주세요" 등
- 선호도: "B는 싫어합니다" 등 재사용 가능한 선호
- 기타: 위에 해당하지 않으나 재사용 가능한 정보

**필수 지침:**
- reason은 **반드시 50자 이내**로 짧게 작성하세요. (토큰 한도 내에서 JSON이 잘리지 않도록)
- extracted_info는 **최대 5개**만 추출하고, 각 text는 **300자 이내**로 하세요.
- FAQ 항목은 질문만 저장하지 말고 반드시 **답변까지 포함**하세요. 답변이 대화에 없으면 FAQ로 추출하지 마세요.
- 한 항목은 하나의 재사용 가능한 지식 단위(예: 하나의 Q&A 쌍, 하나의 약속)로 추출하세요.
- 개인을 특정할 수 있는 정보(이름·전화번호·주소 등)가 포함되면 해당 항목에 "contains_pii": true, 없으면 false로 표시하세요.
- 반드시 유효한 JSON만 출력하세요. 마크다운 코드블록(```)이나 설명 문장 없이 **JSON 본문만** 출력하세요.

JSON:"""

            logger.info("llm_judgment_request",
                        call=True,
                        call_id=call_id or "",
                        category="llm",
                        progress="extraction",
                        transcript_length=len(transcript),
                        max_input_chars=max_input_chars,
                        transcript_truncated=len(transcript) > max_input_chars,
                        speaker=speaker,
                        max_tokens=judgment_max_tokens,
                        prompt_length=len(prompt),
                        prompt_full=prompt,
                        note="지식 정제 요청 (전체 대화 맥락, Q&A 쌍 통합 추출)")

            judge_kw: Dict[str, Any] = {"temperature": 0.3, "max_output_tokens": judgment_max_tokens}
            tc = self._thinking_off()
            if tc is not None:
                judge_kw["thinking_config"] = tc
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.model.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(**judge_kw),
                )
            )

            result_text = (response.text or "").strip()

            # Gemini 종료 사유 및 실제 토큰 사용량 로깅
            finish_reason = None
            finish_reason_desc = None
            output_token_count = None
            prompt_token_count = None
            try:
                if getattr(response, "candidates", None) and len(response.candidates) > 0:
                    finish_reason = getattr(response.candidates[0], "finish_reason", None)
                    if finish_reason is not None:
                        fr_map = {1: "STOP", 2: "MAX_TOKENS", 3: "SAFETY", 4: "RECITATION"}
                        finish_reason_desc = fr_map.get(int(finish_reason), str(finish_reason))
                if getattr(response, "usage_metadata", None):
                    um = response.usage_metadata
                    output_token_count = getattr(um, "candidates_token_count", None) or getattr(um, "output_token_count", None)
                    prompt_token_count = getattr(um, "prompt_token_count", None)
            except Exception:
                pass
            # response_full은 무조건 전체 출력 (잘림 없이). 로그 백엔드가 자르면 response_length로 원본 길이 확인 가능
            logger.info("llm_judgment_response",
                        call=True,
                        call_id=call_id or "",
                        category="llm",
                        progress="extraction",
                        judgment_max_output_tokens=judgment_max_tokens,
                        output_token_count=output_token_count,
                        prompt_token_count=prompt_token_count,
                        response_length=len(result_text),
                        finish_reason=finish_reason_desc or str(finish_reason),
                        response_full=result_text,
                        note="유용성 판단 응답 (response_full 전체, 잘림 없음)")
            if finish_reason_desc == "MAX_TOKENS":
                logger.warning("llm_judgment_truncated",
                              call=True,
                              call_id=call_id or "",
                              progress="extraction",
                              note="응답이 max_output_tokens에서 잘림, JSON 복구 시도 (judgment_max_output_tokens 상향 권장)")
            
            # 1) JSON 추출: 마크다운 코드블록 제거 후 본문만 사용
            json_text = None
            if "```json" in result_text:
                try:
                    json_text = result_text.split("```json")[1].split("```")[0].strip()
                except IndexError:
                    pass
            if not json_text and "```" in result_text:
                try:
                    json_text = result_text.split("```")[1].split("```")[0].strip()
                except IndexError:
                    pass
            if not json_text and "{" in result_text and "}" in result_text:
                try:
                    start = result_text.index("{")
                    end = result_text.rindex("}") + 1
                    json_text = result_text[start:end]
                except (ValueError, IndexError):
                    pass
            if not json_text:
                json_text = result_text

            # 2) 파싱 시도: json.loads → 실패 시 정리 후 재시도
            result = None
            try:
                result = json.loads(json_text)
            except json.JSONDecodeError as parse_error:
                # json_full은 무조건 전체 (잘림 없이). 파서에 넘긴 원본 문자열 그대로 로깅
                logger.warning("JSON parse failed, attempting cleanup",
                             call=True,
                             call_id=call_id or "",
                             judgment_max_output_tokens=judgment_max_tokens,
                             response_length=len(result_text),
                             json_length=len(json_text) if json_text else 0,
                             error=str(parse_error),
                             json_preview=json_text if json_text else "None",
                             json_full=json_text if json_text else "")
                if json_text:
                    fixed = json_text.rstrip()
                    # 주석/후행 쉼표 정리
                    lines = []
                    for line in fixed.split("\n"):
                        if "//" in line:
                            line = line.split("//")[0]
                        lines.append(line)
                    fixed = "\n".join(lines).replace(",}", "}").replace(",]", "]")

                    parse_err_str = str(parse_error).lower()
                    is_truncated = (
                        "unterminated string" in parse_err_str
                        or "expecting value" in parse_err_str
                        or "expecting" in parse_err_str
                    )

                    # 잘린 응답 복구: Unterminated string 우선, 그 다음 incomplete field (confidence:, reason: 등)
                    if fixed and is_truncated:
                        fixed_clean = fixed.rstrip()
                        if fixed_clean.endswith(","):
                            fixed_clean = fixed_clean[:-1]
                        # 1) Unterminated string: "reason": "… 에서 끊긴 경우 — 닫는 " 후 extracted_info·괄호 닫기
                        if "unterminated string" in parse_err_str:
                            nq = fixed_clean.count('"') - fixed_clean.count('\\"')
                            if nq % 2 != 0:
                                fixed_clean += '"'
                            # reason 값만 닫혀 있고 extracted_info가 없으면 보강 (MAX_TOKENS 잘림 시 흔한 패턴)
                            if '"reason"' in fixed_clean and '"extracted_info"' not in fixed_clean:
                                fixed_clean += ', "extracted_info": []'
                            open_braces = fixed_clean.count("{") - fixed_clean.count("}")
                            open_brackets = fixed_clean.count("[") - fixed_clean.count("]")
                            fixed_clean += "]" * max(0, open_brackets) + "}" * max(0, open_braces)
                            try:
                                result = json.loads(fixed_clean)
                            except json.JSONDecodeError:
                                pass
                        # 1-2) Unterminated string인데 위에서 복구 실패 시: reason 값 닫는 " 후 extracted_info·괄호 추가
                        if result is None and "unterminated string" in parse_err_str and fixed_clean:
                            match = re.search(r'"reason"\s*:\s*"', fixed_clean)
                            if match:
                                try_clean = fixed_clean.rstrip()
                                if (try_clean.count('"') - try_clean.count('\\"')) % 2 != 0:
                                    try_clean += '"'
                                try_clean += ', "extracted_info": []}'
                                open_braces = try_clean.count("{") - try_clean.count("}")
                                open_brackets = try_clean.count("[") - try_clean.count("]")
                                try_clean += "]" * max(0, open_brackets) + "}" * max(0, open_braces)
                                try:
                                    result = json.loads(try_clean)
                                except json.JSONDecodeError:
                                    pass
                        # 2) 미복구 시 값 없이 끊긴 필드 복구 (원본 fixed 기준으로 재시도)
                        if result is None:
                            fixed_clean = fixed.rstrip()
                            if fixed_clean.endswith(","):
                                fixed_clean = fixed_clean[:-1]
                            if re.search(r'"confidence"\s*$', fixed_clean):
                                fixed_clean += ': 0.0, "reason": "", "extracted_info": []}'
                            elif re.search(r'"confidence"\s*:\s*$', fixed_clean):
                                fixed_clean += '0.0, "reason": "", "extracted_info": []}'
                            elif re.search(r'"confidence"\s*:\s*$', fixed_clean, re.MULTILINE):
                                fixed_clean += '0.0, "reason": "", "extracted_info": []}'
                            elif re.search(r'"reason"\s*:\s*$', fixed_clean):
                                fixed_clean += '"", "extracted_info": []}'
                            elif re.search(r'"extracted_info"\s*:\s*$', fixed_clean):
                                fixed_clean += '[]}'
                            elif re.search(r'"is_useful"\s*:\s*$', fixed_clean):
                                fixed_clean += 'false, "confidence": 0.0, "reason": "", "extracted_info": []}'
                            else:
                                fixed_clean = re.sub(r'(:\s*)(\s*)$', r'\g<1>null\2', fixed_clean, count=1)
                            open_braces = fixed_clean.count("{") - fixed_clean.count("}")
                            open_brackets = fixed_clean.count("[") - fixed_clean.count("]")
                            fixed_clean += "]" * max(0, open_brackets) + "}" * max(0, open_braces)
                            try:
                                result = json.loads(fixed_clean)
                            except json.JSONDecodeError:
                                pass
                        fixed = fixed_clean
                    if result is None and fixed and re.search(r"\d\s*$", fixed):
                        fixed += "}"
                        open_braces = fixed.count("{") - fixed.count("}")
                        open_brackets = fixed.count("[") - fixed.count("]")
                        fixed += "]" * open_brackets + "}" * open_braces
                        try:
                            result = json.loads(fixed)
                        except json.JSONDecodeError:
                            pass
                    if result is None and fixed and not fixed.endswith("}"):
                        fixed = re.sub(r":\s*$", ": null", fixed)
                        fixed = re.sub(r",\s*$", "", fixed)
                        if (fixed.count('"') - fixed.count('\\"')) % 2 != 0:
                            fixed += '"'
                        open_braces = fixed.count("{") - fixed.count("}")
                        open_brackets = fixed.count("[") - fixed.count("]")
                        fixed += "]" * max(0, open_brackets) + "}" * max(0, open_braces)
                        try:
                            result = json.loads(fixed)
                        except json.JSONDecodeError:
                            pass
                    if result is None:
                        try:
                            result = json.loads(fixed)
                        except json.JSONDecodeError:
                            pass
                    # Final fallback: do not re-raise; return default so caller always gets valid dict
                    if result is None:
                        result = {
                            "is_useful": False,
                            "confidence": 0.0,
                            "reason": "Response truncated or invalid JSON; default applied" if is_truncated else "JSON parse failed after cleanup",
                            "extracted_info": [],
                        }
            
            if result is None:
                result = {
                    "is_useful": False,
                    "confidence": 0.0,
                    "reason": "JSON parse failed",
                    "extracted_info": [],
                }
            
            # 3) 하위 호환: confidence/is_useful 절대 None 금지 (기본값 적용)
            is_useful = result.get("is_useful")
            if is_useful is None:
                is_useful = False
            else:
                is_useful = bool(is_useful)
            confidence = result.get("confidence")
            if confidence is None:
                confidence = 0.0
            else:
                try:
                    confidence = float(confidence)
                except (TypeError, ValueError):
                    confidence = 0.0
                confidence = max(0.0, min(1.0, confidence))
            result["is_useful"] = is_useful
            result["confidence"] = confidence
            result.setdefault("reason", "")
            result.setdefault("extracted_info", [])
            # 설계서 §2.3 카테고리 Enum 정규화: 허용값 외는 "기타"로 매핑
            JUDGMENT_CATEGORIES = {"FAQ", "이슈해결", "약속", "정보", "지시", "선호도", "기타"}
            for item in result.get("extracted_info", []):
                if isinstance(item, dict):
                    cat = item.get("category") or "기타"
                    if isinstance(cat, str):
                        cat = cat.strip()
                    item["category"] = cat if cat in JUDGMENT_CATEGORIES else "기타"
            # optional keys (e.g. contains_pii) preserved for downstream

            logger.info("llm_judgment_completed",
                        call=True,
                        call_id=call_id or "",
                        category="llm",
                        progress="extraction",
                        is_useful=result["is_useful"],
                        confidence=result["confidence"],
                        extracted_info_count=len(result.get("extracted_info", [])))

            return result

        except json.JSONDecodeError as e:
            logger.error("llm_judgment_json_failed",
                        call=True,
                        call_id=call_id or "",
                        category="llm",
                        progress="extraction",
                        error=str(e),
                        raw_response_full=result_text or "N/A",
                        json_attempt_full=json_text or "N/A")
            return {
                "is_useful": False,
                "confidence": 0.0,
                "reason": f"JSON parse error: {str(e)}",
                "extracted_info": []
            }
        except Exception as e:
            logger.error("llm_judgment_error",
                        call=True,
                        call_id=call_id or "",
                        category="llm",
                        progress="extraction",
                        error=str(e),
                        exc_info=True)
            return {
                "is_useful": False,
                "confidence": 0.0,
                "reason": f"Error: {str(e)}",
                "extracted_info": []
            }
    
    def clear_history(self):
        """대화 히스토리 초기화"""
        self.conversation_history.clear()
        logger.info("LLM conversation history cleared")
    
    def get_history(self) -> List[Dict[str, str]]:
        """대화 히스토리 반환"""
        return self.conversation_history.copy()
    
    def get_stats(self) -> dict:
        """LLM 통계 반환"""
        return {
            "total_requests": self.total_requests,
            "total_tokens": self.total_tokens,
            "history_length": len(self.conversation_history),
            "avg_tokens_per_request": (
                self.total_tokens / self.total_requests 
                if self.total_requests > 0 else 0
            ),
        }

