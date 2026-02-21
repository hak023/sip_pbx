"""
QA Pair Extractor

통화 대화에서 질문-답변(QA) 쌍을 추출합니다.
(AI Knowledge Assist, EMNLP 2025 참조)
"""

import asyncio
import json
import structlog
from typing import List, Dict

logger = structlog.get_logger(__name__)


class QAPairExtractor:
    """대화에서 QA 쌍 추출"""

    def __init__(self, llm_client):
        self.llm = llm_client

    async def extract(self, transcript: str, call_id: str = "") -> List[Dict]:
        """
        대화에서 질문-답변 쌍 추출

        Args:
            transcript: 전사 텍스트
            call_id: 통화 ID

        Returns:
            [
                {
                    "question": "자연어 질문",
                    "answer": "자연어 답변",
                    "context": "질문이 나온 맥락",
                    "source_speaker": "caller|callee",
                    "category": "카테고리"
                }
            ]
        """
        try:
            prompt = f"""다음 전화 통화에서 질문-답변(QA) 쌍을 추출하세요.

**규칙:**
1. 정보를 요청하는 발화 → 질문(Q)
2. 해당 정보를 제공하는 발화 → 답변(A)
3. 암묵적 질문도 포함 (예: "거기 주차장 있어?" → Q)
4. 동일 토픽의 여러 교환은 하나의 QA로 합산
5. 인사말이나 무의미한 대화는 제외
6. 답변은 완전한 문장으로 재구성

**통화 내용:**
{transcript[:2000]}

**출력 형식 (JSON 배열):**
[
  {{
    "question": "자연어 질문 (완전한 문장으로)",
    "answer": "자연어 답변 (완전한 문장으로)",
    "context": "질문이 나온 맥락 (1문장)",
    "source_speaker": "caller 또는 callee",
    "category": "약속|위치|시간|가격|절차|정보|기타"
  }}
]

QA 쌍이 없으면 빈 배열 []을 반환하세요.

JSON:"""

            import google.generativeai as genai

            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.llm.model.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=0.2,
                        max_output_tokens=800,
                    ),
                ),
            )

            qa_pairs = self._parse_json_array(response.text.strip())
            logger.info(
                "qa_pairs_extracted",
                call_id=call_id,
                count=len(qa_pairs),
            )
            return qa_pairs

        except Exception as e:
            logger.error("qa_extraction_failed", call_id=call_id, error=str(e))
            return []

    @staticmethod
    def _parse_json_array(text: str) -> List[Dict]:
        """LLM 응답에서 JSON 배열 추출"""
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
        # [ ... ]
        if "[" in text:
            try:
                start = text.index("[")
                end = text.rindex("]") + 1
                return json.loads(text[start:end])
            except (ValueError, json.JSONDecodeError):
                pass
        return []
