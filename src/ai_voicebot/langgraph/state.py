"""
LangGraph Conversation State 정의.

모든 노드가 공유하는 상태 객체. LangGraph StateGraph의 상태 스키마.
"""

from typing import TypedDict, Optional, List


class ConversationState(TypedDict, total=False):
    """LangGraph 대화 상태 (모든 노드가 읽고 쓰는 공유 상태)"""

    # ── 대화 컨텍스트 ──
    messages: List[dict]          # 전체 대화 기록 [{role, content, timestamp}]
    user_query: str               # 현재 사용자 발화
    turn_count: int               # 대화 턴 수

    # ── 의도 및 슬롯 ──
    intent: str                   # 분류된 의도 (greeting, question, complaint, transfer, farewell)
    slots: dict                   # 추출된 슬롯 (예: {product: "A", date: "내일"})

    # ── RAG 결과 ──
    rewritten_query: str          # Query Rewriting 결과
    rag_results: list             # RAG 검색 결과 문서들
    rag_cache_hit: bool           # Semantic Cache 히트 여부
    confidence: float             # 응답 신뢰도 (0.0 ~ 1.0)

    # ── 응답 ──
    response: str                 # 생성된 응답 텍스트
    response_chunks: list         # Streaming 응답 청크

    # ── 비즈니스 상태 ──
    business_state: str           # 현재 비즈니스 상태 (initial, inquiry, resolution, closing)
    org_context: str              # 기관 정보 컨텍스트
    system_prompt: str            # 시스템 프롬프트

    # ── HITL ──
    needs_human: bool             # 운영자 개입 필요 여부
    hitl_reason: str              # HITL 사유

    # ── 내부 참조 (노드 간 공유) ──
    _llm_client: object           # LLM 클라이언트 참조
    _rag_engine: object           # RAG 엔진 참조
    _embedder: object             # Embedder 참조
    _vector_db: object            # VectorDB 참조
    _org_manager: object          # 기관 정보 관리자 참조
    _owner: str                    # 착신번호 (테넌트 ID, 예: "1004")
    _call_id: Optional[str]        # 통화 ID (로그/DB 연계용)
