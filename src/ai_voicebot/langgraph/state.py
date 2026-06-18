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
    user_query_raw: str           # STT 원문(시간 정규화 전). RAG 이중 검색·로그용
    turn_count: int               # 대화 턴 수

    # ── 의도 및 슬롯 ──
    intent: str                   # 분류된 의도 (greeting, question, complaint, transfer, farewell)
    slots: dict                   # 추출된 슬롯 (예: {product: "A", date: "내일"})

    # ── 발화 레인 (검색 전 라우팅 · HITL 완화) ──
    utterance_lane: str           # knowledge | social_direct
    rag_mode: str                 # full | skip (skip 시 RAG·캐시 경로 생략)
    domain_question_signal: bool  # True면 업무형 question → 엄격한 step_back/HITL

    # ── RAG 결과 ──
    rewritten_query: str          # Query Rewriting 결과
    rag_results: list             # RAG 검색 결과 문서들
    rag_cache_hit: bool           # Semantic Cache 히트 여부
    rag_search_trace: dict        # 벡터 검색 필터·컬렉션 등 (adaptive_rag)
    confidence: float             # 응답 신뢰도 (0.0 ~ 1.0)

    # ── llm_exchange / 디버깅 (프롬프트에 실제 반영된 RAG 스니펫) ──
    llm_rag_applied: list         # build_rag_hits_llm_context 형태
    llm_rag_context_source: str  # vector_knowledge | semantic_cache | …

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
    needs_transfer: bool          # True면 HITL 대신 SIP 호전환 트리거 (escalation_mode=transfer)
    transfer_extension: str       # 호전환 대상 내선번호 (escalation_mode=transfer 시 Persona에서 읽음)

    # ── 후처리(확인 필요) ──
    needs_follow_up: bool         # 모르는 내용 응답 시, 나중에 확인·연락 필요
    follow_up_user_query: str     # 사용자가 물어본 내용 (확인할 사항)

    # ── 아웃바운드 미션 추적 ──
    outbound_questions: List[str]          # 확인해야 할 질문 목록 (아웃바운드 전용)
    outbound_answers: dict                 # {질문: 답변} 수집된 응답 (아웃바운드 전용)
    outbound_mission_done: bool            # 모든 질문 답변 완료 여부
    outbound_purpose: str                  # 통화 목적 (아웃바운드 전용)
    outbound_non_answer: bool              # 이번 발화가 유효한 답변이 아님 (욕설·감탄사·거절 등)
    outbound_answered: list                # LLM이 추출한 {question, answer} 목록 (generate_response_node 출력)
    outbound_is_answer: bool               # 이번 발화가 유효한 답변인지 (LLM 판단)

    # ── 예약 에이전트 ──
    booking_context: dict         # 예약 진행 중 수집된 슬롯 정보 (날짜, 시간, 인원 등)

    # ── 내부 참조 (직렬화 가능 값만 — 객체 참조는 call_context.py ContextVar 사용) ──
    # 직렬화 불가 객체(_llm_client, _rag_engine, _embedder, _vector_db, _org_manager,
    # _hangup_callback)는 call_context.py의 ContextVar로 이동.
    # checkpointer(SqliteSaver/MemorySaver)의 msgpack 직렬화 오류 방지.
    _owner: str                    # 테넌트 ID (inbound=callee, outbound=caller)
    _caller_number: str            # 발신자 전화번호 (inbound=caller 번호, SMS 수신·예약 검색용)
    _persona_owner: str            # 페르소나 조회용 owner: inbound=callee(_owner), outbound=callee(상대방번호)
    _persona_scope_matched: bool   # classify_intent에서 페르소나 scope_keywords 매칭된 경우 True (domain_question_signal 산출용)
    _kb_gate_hit: bool              # 페르소나 비관련이나 VectorDB strict 유사도로 question 승격된 경우 True
    _call_id: Optional[str]        # 통화 ID (로그/DB 연계용)
    _chitchat_template: str        # chitchat 즉시응답 템플릿 (classify_intent → generate_response)
