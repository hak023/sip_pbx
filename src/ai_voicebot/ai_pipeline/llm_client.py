"""
Google Gemini LLM Client

대화 생성 및 지식 유용성 판단
"""

import google.generativeai as genai
import asyncio
from typing import List, Dict, Optional
import json
import structlog

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
                - model: "gemini-pro"
                - temperature: 0.7
                - max_tokens: 200
                - top_p: 1.0
                - top_k: 1
            api_key: Google API 키
        """
        self.config = config
        
        # Gemini 설정
        genai.configure(api_key=api_key)
        
        model_name = config.get("model", "gemini-pro")
        self.model = genai.GenerativeModel(model_name=model_name)
        
        # Generation 설정
        self.generation_config = genai.types.GenerationConfig(
            temperature=config.get("temperature", 0.7),
            top_p=config.get("top_p", 1.0),
            top_k=config.get("top_k", 1),
            max_output_tokens=config.get("max_tokens", 200),
        )
        
        # 대화 히스토리
        self.conversation_history: List[Dict[str, str]] = []
        self.max_history_length = config.get("max_history_length", 20)
        
        # 통계
        self.total_requests = 0
        self.total_tokens = 0
        
        logger.info("LLMClient initialized", 
                   model=model_name,
                   temperature=config.get("temperature"))
    
    async def generate_response(
        self, 
        user_text: str, 
        context_docs: List[str],
        system_prompt: Optional[str] = None
    ) -> str:
        """
        사용자 입력에 대한 답변 생성
        
        Args:
            user_text: 사용자 질문
            context_docs: RAG 검색 결과 (관련 문서)
            system_prompt: 시스템 프롬프트 (선택)
            
        Returns:
            생성된 답변 텍스트
        """
        try:
            # 프롬프트 조립
            prompt = self._build_conversation_prompt(
                user_text, 
                context_docs, 
                system_prompt
            )
            
            # Gemini API 호출 (비동기)
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.model.generate_content(
                    prompt,
                    generation_config=self.generation_config
                )
            )
            
            # 응답 텍스트 추출
            answer = response.text.strip()
            
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
            self.total_tokens += len(user_text) + len(answer)
            
            logger.info("LLM response generated",
                       user_text_length=len(user_text),
                       response_length=len(answer),
                       context_docs_count=len(context_docs))
            
            return answer
            
        except Exception as e:
            logger.error("LLM generation error", error=str(e), exc_info=True)
            return "죄송합니다, 답변을 생성하는 중 오류가 발생했습니다."
    
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
    
    async def judge_usefulness(
        self, 
        transcript: str, 
        speaker: str = "callee"
    ) -> Dict[str, any]:
        """
        통화 내용의 유용성 판단 (지식 추출용)
        
        Args:
            transcript: 통화 전체 텍스트
            speaker: 화자 (caller/callee)
            
        Returns:
            {
                "is_useful": bool,
                "confidence": float,
                "reason": str,
                "extracted_info": List[Dict]
            }
        """
        try:
            prompt = f"""다음 통화 내용을 분석하여 향후 AI 비서가 활용할 수 있는 
유용한 정보가 있는지 판단하세요.

**유용한 정보 예시:**
- 약속 일정 (시간, 장소)
- 연락처 정보
- 업무 지시사항
- 자주 묻는 질문에 대한 답변
- 개인 선호도 (좋아하는 음식, 취미 등)

**통화 내용 ({speaker}):**
{transcript[:1000]}

**출력 형식 (JSON):**
{{
  "is_useful": true/false,
  "confidence": 0.0-1.0,
  "reason": "판단 이유",
  "extracted_info": [
    {{
      "text": "추출할 텍스트",
      "category": "약속|정보|지시|선호도|기타",
      "keywords": ["키워드1", "키워드2"]
    }}
  ]
}}

JSON:"""
            
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.model.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=0.3,  # 더 결정론적
                        max_output_tokens=500
                    )
                )
            )
            
            # JSON 파싱
            result_text = response.text.strip()
            
            # JSON 추출 (```json ... ``` 제거)
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0].strip()
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0].strip()
            
            result = json.loads(result_text)
            
            logger.info("Usefulness judgment completed",
                       is_useful=result.get("is_useful"),
                       confidence=result.get("confidence"))
            
            return result
            
        except json.JSONDecodeError as e:
            logger.error("Failed to parse LLM JSON response", error=str(e))
            return {
                "is_useful": False,
                "confidence": 0.0,
                "reason": f"JSON parse error: {str(e)}",
                "extracted_info": []
            }
        except Exception as e:
            logger.error("Usefulness judgment error", error=str(e), exc_info=True)
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

