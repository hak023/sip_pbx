"""
짧은 STT·의도·RAG 필터 공통 힌트.

- 방문/오시는 길/교통 문의 vs 상담원 연결(transfer) 혼동 완화
- RAG: transfer로 오분류돼도 '찾아가다/방문'류는 전체 지식 검색(question과 동일 필터)
"""

from __future__ import annotations


# 상담원·전환 의사가 명시된 경우 (이게 있으면 transfer 후보 유지)
_OPERATOR_TRANSFER_MARKERS = (
    "연결해",
    "연결 해",
    "연결주",
    "연결 주",
    "바꿔",
    "바꿔주",
    "담당자",
    "상담원",
    "직원",
    "사람이",
    "사람과",
    "사람한테",
    "직원한테",
    "상담사",
    "전화 돌려",
    "돌려주",
)

# 물리적 방문·위치·교통 안내 문의 (question / 전체 카테고리 RAG)
_VISIT_DIRECTION_MARKERS = (
    "찾아가",
    "찾아 오",
    "찾아와",
    "찾아와요",
    "방문",
    "오시는 길",
    "오시는길",
    "가는 길",
    "가는법",
    "가는 방법",
    "어떻게 가",
    "가려고",
    "가려구",
    "위치",
    "주소",
    "교통",
    "지하철",
    "버스",
    "택시",
    "주차",
    "건물",
    "약도",
)


def looks_like_operator_transfer_request(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    return any(m in t for m in _OPERATOR_TRANSFER_MARKERS)


def looks_like_visit_or_direction_info_query(text: str) -> bool:
    """기관 방문·찾아가기·교통 등 정보 질의로 보이면 True."""
    t = (text or "").strip().lower()
    if not t:
        return False
    return any(m in t for m in _VISIT_DIRECTION_MARKERS)


def should_treat_as_question_not_transfer(text: str) -> bool:
    """
    방문/길 안내로 보이면서, 동시에 명시적 연결 요청이 없으면 question으로 본다.
    (LLM이 transfer로 오분류하는 경우 RAG·라우팅 완화에도 사용)
    """
    if not looks_like_visit_or_direction_info_query(text):
        return False
    if looks_like_operator_transfer_request(text):
        return False
    return True
