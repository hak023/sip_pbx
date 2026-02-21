"""
Entity Extractor

통화 대화에서 정형 엔티티(전화번호, 날짜, 주소 등)를 추출합니다.
(LingVarBench 2025 참조)
"""

import asyncio
import json
import structlog
from typing import List, Dict

logger = structlog.get_logger(__name__)

# 지원 엔티티 타입
ENTITY_TYPES = [
    "phone_number",   # 전화번호
    "date",           # 날짜/시간
    "address",        # 주소
    "person_name",    # 인명
    "amount",         # 금액
    "organization",   # 기관/회사명
    "appointment",    # 약속 (날짜+장소+참석자)
    "instruction",    # 업무 지시
    "preference",     # 개인 선호도
]


class EntityExtractor:
    """대화에서 정형 엔티티 추출"""

    def __init__(self, llm_client):
        self.llm = llm_client

    async def extract(self, transcript: str, call_id: str = "") -> List[Dict]:
        """
        대화에서 정형 엔티티 추출

        Returns:
            [
                {
                    "entity_type": "phone_number",
                    "value": "02-1234-5678",
                    "normalized": "0212345678",
                    "context": "원문 맥락",
                    "confidence": 0.95,
                    "speaker": "callee"
                }
            ]
        """
        try:
            types_str = ", ".join(ENTITY_TYPES)
            prompt = f"""다음 전화 통화에서 구조화된 정보(엔티티)를 추출하세요.

**추출 대상 엔티티 유형:** {types_str}

**규칙:**
1. 원문에 명시적으로 언급된 정보만 추출 (추측 금지)
2. 전화번호는 숫자만 정규화 (normalized 필드)
3. 날짜는 ISO 형식으로 정규화 (예: 2026-01-30T15:00)
4. 금액은 숫자로 정규화 (예: 50000)
5. 약속은 날짜+장소+참석자를 합쳐서 하나의 엔티티로
6. confidence는 원문에 명확히 있으면 0.9+, 문맥 추론이면 0.7~0.9

**통화 내용:**
{transcript[:2000]}

**출력 형식 (JSON 배열):**
[
  {{
    "entity_type": "엔티티 유형",
    "value": "원문 그대로의 값",
    "normalized": "정규화된 값 (해당 시)",
    "context": "해당 값이 나온 문장",
    "confidence": 0.0-1.0,
    "speaker": "caller 또는 callee"
  }}
]

엔티티가 없으면 빈 배열 []을 반환하세요.

JSON:"""

            import google.generativeai as genai

            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.llm.model.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=0.1,
                        max_output_tokens=600,
                    ),
                ),
            )

            entities = self._parse_json_array(response.text.strip())

            # 유효한 entity_type만 필터
            valid = [
                e for e in entities if e.get("entity_type") in ENTITY_TYPES
            ]

            logger.info(
                "entities_extracted",
                call_id=call_id,
                total=len(entities),
                valid=len(valid),
            )
            return valid

        except Exception as e:
            logger.error("entity_extraction_failed", call_id=call_id, error=str(e))
            return []

    @staticmethod
    def _parse_json_array(text: str) -> List[Dict]:
        if "```json" in text:
            try:
                return json.loads(text.split("```json")[1].split("```")[0].strip())
            except (json.JSONDecodeError, IndexError):
                pass
        if "```" in text:
            try:
                return json.loads(text.split("```")[1].split("```")[0].strip())
            except (json.JSONDecodeError, IndexError):
                pass
        if "[" in text:
            try:
                start = text.index("[")
                end = text.rindex("]") + 1
                return json.loads(text[start:end])
            except (ValueError, json.JSONDecodeError):
                pass
        return []
