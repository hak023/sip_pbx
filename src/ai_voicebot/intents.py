"""
AI 대화 의도 분류 (Intent Classification)

호 전환 요청을 포함한 다양한 의도 분류
"""

from enum import Enum
from typing import Optional, Dict, List
from dataclasses import dataclass


class Intent(str, Enum):
    """AI 대화 의도 분류"""
    
    # 기존
    WEATHER_QUERY = "weather_query"
    GENERAL_QUERY = "general_query"
    GREETING = "greeting"
    FAREWELL = "farewell"
    
    # 신규 - 호 전환 관련
    TRANSFER_REQUEST = "transfer_request"  # ✅ 담당자 연결 요청
    TRANSFER_OPERATOR = "transfer_operator"  # 일반 상담원
    TRANSFER_DEPARTMENT = "transfer_department"  # 특정 부서


@dataclass
class TransferRequest:
    """호 전환 요청 정보"""
    
    intent: Intent
    department: Optional[str] = None
    keywords: Optional[List[str]] = None
    urgency: str = "normal"
    confidence: float = 0.0
    
    def to_dict(self) -> Dict:
        return {
            "intent": self.intent.value,
            "department": self.department,
            "keywords": self.keywords or [],
            "urgency": self.urgency,
            "confidence": self.confidence,
        }


class IntentClassifier:
    """
    의도 분류기
    
    사용자 발화에서 호 전환 요청을 감지하고 분류
    """
    
    # 호 전환 요청 키워드
    TRANSFER_KEYWORDS = [
        "연결", "상담원", "담당자", "직원", "사람",
        "전문가", "통화", "바꿔", "연결해",
        "전화", "말씀", "통화하고", "연결하고"
    ]
    
    # 부서 관련 키워드
    DEPARTMENT_KEYWORDS = [
        "부서", "담당부서", "팀", "센터", "과"
    ]
    
    @classmethod
    def is_transfer_request(cls, text: str) -> bool:
        """
        호 전환 요청 여부 판단
        
        Args:
            text: 사용자 발화
        
        Returns:
            호 전환 요청이면 True
        """
        text_lower = text.lower()
        return any(keyword in text_lower for keyword in cls.TRANSFER_KEYWORDS)
    
    @classmethod
    def extract_department_from_query(cls, text: str) -> Optional[str]:
        """
        질의에서 부서명 추출 (간단한 패턴 매칭)
        
        Args:
            text: 사용자 발화
        
        Returns:
            부서명 또는 None
        """
        # TODO: 더 정교한 NER (Named Entity Recognition) 필요
        # 현재는 간단한 패턴 매칭
        
        text_lower = text.lower()
        
        # "기상청 담당부서" 같은 패턴 찾기
        for keyword in cls.DEPARTMENT_KEYWORDS:
            if keyword in text_lower:
                # 앞에 있는 단어 추출 시도
                parts = text.split(keyword)
                if parts[0].strip():
                    return parts[0].strip() + keyword
        
        return None
    
    @classmethod
    def classify_quick(cls, text: str) -> Intent:
        """
        빠른 의도 분류 (LLM 없이 키워드 기반)
        
        Args:
            text: 사용자 발화
        
        Returns:
            Intent
        """
        text_lower = text.lower()
        
        # 호 전환 요청
        if cls.is_transfer_request(text):
            return Intent.TRANSFER_REQUEST
        
        # 인사
        if any(word in text_lower for word in ["안녕", "여보세요", "hello"]):
            return Intent.GREETING
        
        # 종료
        if any(word in text_lower for word in ["감사", "끊을게", "종료", "bye"]):
            return Intent.FAREWELL
        
        # 날씨 질의
        if any(word in text_lower for word in ["날씨", "기온", "예보", "비", "눈"]):
            return Intent.WEATHER_QUERY
        
        # 일반 질의
        return Intent.GENERAL_QUERY


# Intent Classification Prompt for LLM
INTENT_CLASSIFICATION_PROMPT = """
당신은 고객 의도를 분석하는 AI입니다.

사용자 발화를 분석하여 다음 중 하나의 의도로 분류하세요:

1. transfer_request: 담당자/부서 연결 요청
   - 예시: "상담원 연결해줘", "담당자와 통화하고 싶어요", "기상청 담당부서 연결"
   - 키워드: 연결, 상담원, 담당자, 직원, 사람, 전문가

2. weather_query: 날씨 정보 질의
   - 예시: "오늘 날씨", "내일 비 오나요"

3. general_query: 일반 질의
   - 예시: "영업시간이 어떻게 되나요", "주소가 어디인가요"

4. greeting: 인사
   - 예시: "안녕하세요", "여보세요"

5. farewell: 종료
   - 예시: "감사합니다", "끊을게요"

사용자 발화: "{user_query}"

의도 분류 결과를 JSON 형식으로 반환하세요:
{{
  "intent": "transfer_request",
  "confidence": 0.95,
  "entities": {{
    "department": "기상청 담당부서",
    "keywords": ["기상청", "담당부서"]
  }}
}}
"""


def build_transfer_announcement_prompt(department: str, phone_number: str) -> str:
    """
    호 전환 안내 멘트 생성 프롬프트
    
    Args:
        department: 부서명
        phone_number: 전화번호
    
    Returns:
        LLM 프롬프트
    """
    return f"""
다음 정보를 바탕으로 고객에게 전달할 호 전환 안내 멘트를 작성하세요:

부서: {department}
전화번호: {phone_number}

요구사항:
1. 친절하고 자연스러운 톤
2. 1-2문장으로 간결하게
3. 부서명과 함께 "바로 연결해 드리겠습니다" 포함
4. 전화번호는 언급하지 않음 (시스템이 자동 연결)

안내 멘트:
"""
