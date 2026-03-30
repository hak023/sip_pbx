"""
Intent 관련 유틸리티 함수

호 전환, HITL 등 intent 처리에 필요한 프롬프트 생성 함수 제공
"""

from __future__ import annotations

import re
from enum import Enum
from typing import ClassVar


class Intent(str, Enum):
    """
    빠른 의도 분류 결과 (LLM 없이 휴리스틱).
    RAG `IntentClassifier.classify_quick` 와 동일 값 사용.
    """

    GENERAL = "general"
    TRANSFER_REQUEST = "transfer_request"


class IntentClassifier:
    """
    사용자 발화에서 호 전환 의도만 1차로 걸러낸다.
    LLM 호출 전 빠른 경로용 — 과도한 매칭은 일반 질의 오인 방지.
    """

    # 한국어 호전환/상담원 연결 표현 (부분 문자열)
    _TRANSFER_SUBSTRINGS: ClassVar[tuple[str, ...]] = (
        "연결해 주",
        "연결해주",
        "바로 연결",
        "전환",
        "상담원",
        "상담사",
        "담당자",
        "직원",
        "사람이랑",
        "사람과 통화",
        "사람한테",
        "다른 사람",
        "옮겨",
        "돌려줘",
        "데스크",
        "operator",
        "transfer",
    )

    # 질문 패턴 (transfer 키워드가 있어도 질문이면 제외)
    _QUESTION_PATTERNS: ClassVar[tuple[re.Pattern[str], ...]] = (
        re.compile(r"(몇|얼마나|어떤|무엇|누구|언제|어디|왜|어떻게)\s*(명|개|분|시|곳)?.*\?"),  # 의문사 + 물음표
        re.compile(r"(몇|얼마나|어떤|무엇|누구|언제|어디|왜|어떻게)\s*(명|개|분|시|곳)?.*\s*(있나요|인가요|일까요|가요|나요)"),  # 의문사 + 종결어미
        re.compile(r".*\s*(있나요|인가요|일까요|하나요|되나요)\??\s*$"),  # 질문 종결어미
    )

    _TRANSFER_REGEX: ClassVar[tuple[re.Pattern[str], ...]] = (
        # '마케팅팀에 연결' / '영업으로 바꿔'
        re.compile(r"(?:으로|로|에게|에)\s*(?:연결|바꿔|전환)"),
        re.compile(r"(?:연결|전환|바꿔)\s*(?:해\s*줘|해주세요|부탁)"),
    )

    @classmethod
    def classify_quick(cls, user_text: str) -> Intent:
        if not user_text or not str(user_text).strip():
            return Intent.GENERAL

        t = str(user_text).strip().lower()

        # 1. 질문 패턴 먼저 확인 (질문이면 transfer 아님)
        for qp in cls._QUESTION_PATTERNS:
            if qp.search(t):
                return Intent.GENERAL

        # 2. Transfer 키워드 확인
        for sub in cls._TRANSFER_SUBSTRINGS:
            if sub.lower() in t:
                return Intent.TRANSFER_REQUEST

        for rx in cls._TRANSFER_REGEX:
            if rx.search(t):
                return Intent.TRANSFER_REQUEST

        return Intent.GENERAL


def default_transfer_announcement(department: str) -> str:
    """
    LLM 실패·불충분 응답 시 사용하는 고정 안내 (부서명 없어도 자연스러운 한 문장 이상).
    """
    d = (department or "").strip()
    if d:
        return f"{d} 담당자에게 연결해 드리겠습니다. 잠시만 기다려 주세요."
    return "지금 바로 연결해 드리겠습니다. 잠시만 기다려 주세요."


def choose_transfer_announcement(llm_text: str | None, department: str) -> str:
    """
    LLM 출력이 인사만·과도하게 짧으면 `default_transfer_announcement`로 대체.

    - 최소 글자 수 + '연결/전환/대기' 의미가 있어야 채택 (예: '네, 고객님.' 제외).
    """
    fb = default_transfer_announcement(department)
    if not llm_text:
        return fb
    t = str(llm_text).strip()
    if len(t) < 12:
        return fb
    # 연결·전환·대기 안내가 없으면 인사/잡담으로 보고 폴백
    if not any(k in t for k in ("연결", "전환", "잠시", "기다려", "바로")):
        return fb
    return t


def build_transfer_announcement_prompt(department: str, phone_number: str) -> str:
    """
    호 전환 안내 멘트 생성용 LLM 프롬프트
    
    Args:
        department: 부서명 (예: "영업팀", "고객지원팀")
        phone_number: 전화번호 (예: "010-1234-5678")
    
    Returns:
        LLM에게 전달할 프롬프트 문자열
    
    Example:
        >>> prompt = build_transfer_announcement_prompt("영업팀", "02-1234-5678")
        >>> announcement = await llm.generate_simple(prompt)
        >>> print(announcement)
        "영업팀으로 바로 연결해 드리겠습니다. 잠시만 기다려 주세요."
    """
    return f"""다음 정보를 바탕으로 호 전환 안내 멘트를 작성해주세요:

**부서**: {department}
**전화번호**: {phone_number}

**요구사항**:
1. 친절하고 자연스러운 한국어 톤
2. 반드시 **한 문장 이상**의 안내 멘트 (인사만으로 끝내지 말 것)
3. **금지**: "네, 고객님." / "네." / "알겠습니다" 처럼 연결 안내 없이 끝내기
4. "연결해 드리겠습니다" 또는 "전환해 드리겠습니다" 등 **연결 의도**를 포함
5. "잠시만 기다려 주세요" 등 **대기 안내** 포함
6. 부서명을 문장에 넣어도 되고, 생략해도 되나 위 2~5는 반드시 지킬 것
7. 전화번호는 언급하지 말 것 (보안)

**안내 멘트** (멘트만 출력, 다른 설명 없이):"""


def build_transfer_fallback_prompt(user_query: str) -> str:
    """
    연락처를 찾지 못한 경우 대안 안내 멘트 생성용 프롬프트
    
    Args:
        user_query: 사용자 질문 (예: "마케팅팀 연결해줘")
    
    Returns:
        LLM에게 전달할 프롬프트 문자열
    """
    return f"""사용자가 다음과 같이 요청했으나 해당 부서/담당자의 연락처를 찾지 못했습니다:

**사용자 요청**: {user_query}

**상황**: 지식베이스에 해당 연락처가 등록되지 않음

**요구사항**:
1. 죄송하다는 표현으로 시작
2. 일반 상담원으로 연결해드리겠다고 안내
3. 친절하고 공손한 톤
4. 1-2문장으로 간결하게

**안내 멘트**:"""


def build_hitl_request_message() -> str:
    """
    HITL (Human-In-The-Loop) 요청 시 사용자에게 전달할 고정 메시지
    
    Returns:
        HITL 요청 안내 메시지
    
    Note:
        이 함수는 고정 문자열을 반환합니다.
        HITL_DEFERRED_RESPONSE_DESIGN.md 참고
    """
    return (
        "죄송합니다. 해당 내용은 제가 알지 못하는 내용입니다. "
        "다른 도움이 필요하시면 말씀해 주세요."
    )


def build_context_transition_message(original_question: str, operator_response: str) -> str:
    """
    HITL 응답 시 문맥 전환 문구 생성
    
    Args:
        original_question: 사용자의 원래 질문
        operator_response: 운영자가 작성한 답변
    
    Returns:
        문맥 전환 + 답변이 결합된 메시지
    
    Example:
        >>> msg = build_context_transition_message(
        ...     "환불은 어떻게 하나요?",
        ...     "고객센터로 연락주세요"
        ... )
        >>> print(msg)
        "아까 문의주신 '환불은 어떻게 하나요?' 내용에 대해 확인되어 알려드리겠습니다. 고객센터로 연락주세요."
    """
    # 질문 요약 (너무 길면 앞부분만)
    question_summary = original_question[:30] + "..." if len(original_question) > 30 else original_question
    
    # 문맥 전환 문구 템플릿
    return f"아까 문의주신 '{question_summary}' 내용에 대해 확인되어 알려드리겠습니다. {operator_response}"
