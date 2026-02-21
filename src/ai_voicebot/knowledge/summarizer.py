"""
Conversation Summarizer

통화 대화를 3~5문장으로 요약합니다.
"""

import asyncio
import json
import structlog
from typing import Dict, Optional

logger = structlog.get_logger(__name__)


class ConversationSummarizer:
    """통화 대화 요약 생성기"""

    def __init__(self, llm_client):
        """
        Args:
            llm_client: LLMClient 인스턴스 (Gemini)
        """
        self.llm = llm_client

    async def summarize(self, transcript: str, call_id: str = "") -> Dict:
        """
        대화 전체를 3~5문장으로 요약

        Args:
            transcript: 전사 텍스트
            call_id: 통화 ID (로깅용)

        Returns:
            {
                "summary": str,
                "main_topics": List[str],
                "call_purpose": str,
                "outcome": str
            }
        """
        try:
            prompt = f"""다음 전화 통화 내용을 분석하여 요약하세요.

**통화 내용:**
{transcript[:2000]}

**출력 형식 (JSON):**
{{
  "summary": "3~5문장 요약",
  "main_topics": ["토픽1", "토픽2"],
  "call_purpose": "통화 목적 (1문장)",
  "outcome": "통화 결과 (1문장)"
}}

JSON:"""

            import google.generativeai as genai

            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.llm.model.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=0.3,
                        max_output_tokens=500,
                    ),
                ),
            )

            result = self._parse_json(response.text.strip())
            logger.info(
                "conversation_summarized",
                call_id=call_id,
                topics=result.get("main_topics", []),
            )
            return result

        except Exception as e:
            logger.error("summarization_failed", call_id=call_id, error=str(e))
            return {
                "summary": "",
                "main_topics": [],
                "call_purpose": "",
                "outcome": "",
            }

    @staticmethod
    def _parse_json(text: str) -> Dict:
        """LLM 응답에서 JSON 추출"""
        # ```json ... ```
        if "```json" in text:
            try:
                return json.loads(text.split("```json")[1].split("```")[0].strip())
            except (json.JSONDecodeError, IndexError):
                pass
        # ``` ... ```
        if "```" in text:
            try:
                return json.loads(text.split("```")[1].split("```")[0].strip())
            except (json.JSONDecodeError, IndexError):
                pass
        # { ... }
        if "{" in text:
            try:
                start = text.index("{")
                end = text.rindex("}") + 1
                return json.loads(text[start:end])
            except (ValueError, json.JSONDecodeError):
                pass
        return {"summary": text, "main_topics": [], "call_purpose": "", "outcome": ""}
