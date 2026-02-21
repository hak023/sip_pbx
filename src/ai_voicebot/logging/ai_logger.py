"""
AI Processing Logger

RAG, LLM 처리 과정을 DB에 로깅.
DB 클라이언트가 없으면 로깅을 스킵하며, 경고는 타입별 1회만 출력합니다.

사용 방법:
  - 수동: 앱 초기화 시 ai_logger.set_db_client(your_async_db_client) 호출.
  - config 연동: ai_logger.try_init_db_from_config(config) 호출.
    config.ai_voicebot.logging.db_url 이 있으면 asyncpg로 연결 시도 후 set_db_client.
  상세: docs/guides/AI_DB_LOGGING_SETUP.md
"""

from typing import List, Dict, Optional, Any
from datetime import datetime
import asyncio
import re
import structlog

logger = structlog.get_logger(__name__)

# 전역 DB 클라이언트 (의존성 주입)
_db_client = None
# 경고 중복 방지: 타입별 1회만 "DB client not configured" 로그
_db_skip_warned: set = set()


def set_db_client(db_client):
    """DB 클라이언트 설정 (앱 초기화 시 호출). 미설정 시 RAG/LLM/지식매칭 로깅은 스킵됨."""
    global _db_client
    _db_client = db_client
    logger.info("AI Logger DB client configured")


async def try_init_db_from_config(config) -> bool:
    """
    config에 ai_voicebot.logging.db_url 이 있으면 DB 클라이언트 생성 후 set_db_client.
    asyncpg 필요. 실패 시 False 반환, 로깅만 하고 예외 전파하지 않음.
    호출: await ai_logger.try_init_db_from_config(config) (async 컨텍스트에서).
    """
    try:
        ai = getattr(config, "ai_voicebot", None)
        logging = getattr(ai, "logging", None) if ai else None
        if not logging:
            return False
        db_url = logging.get("db_url") if isinstance(logging, dict) else getattr(logging, "db_url", None)
        if not db_url or not isinstance(db_url, str):
            return False
    except Exception:
        return False

    try:
        import asyncpg
    except ImportError:
        logger.warning("AI DB logging: asyncpg not installed. pip install asyncpg and set ai_voicebot.logging.db_url")
        return False

    class _AsyncpgWrapper:
        def __init__(self, conn):
            self._conn = conn

        async def execute(self, query: str, params: Dict[str, Any]):
            names = list(dict.fromkeys(re.findall(r":(\w+)", query)))
            args = [params.get(n) for n in names]
            q = query
            for i, n in enumerate(names, 1):
                q = q.replace(":" + n, "$" + str(i))  # 동일 이름 여러 번 써도 모두 치환
            await self._conn.execute(q, *args)

    try:
        conn = await asyncpg.connect(db_url)
    except Exception as e:
        logger.warning("AI DB logging: failed to connect", db_url=db_url[:50] + "...", error=str(e))
        return False

    set_db_client(_AsyncpgWrapper(conn))
    return True


async def log_rag_search(
    call_id: str,
    user_question: str,
    search_results: List[Dict[str, Any]],
    top_score: float,
    rag_context_used: str,
    search_latency_ms: int
):
    """
    RAG 검색 히스토리 로깅
    
    Args:
        call_id: 통화 ID
        user_question: 사용자 질문
        search_results: 검색 결과 [{id, text, score}, ...]
        top_score: 최고 유사도 점수
        rag_context_used: RAG 컨텍스트 (실제 사용된 문서)
        search_latency_ms: 검색 지연 시간 (밀리초)
    """
    if not _db_client:
        if "rag" not in _db_skip_warned:
            _db_skip_warned.add("rag")
            logger.warning("DB client not configured, skipping RAG logging", hint="ai_logger.set_db_client(db) to enable")
        return
    
    try:
        query = """
            INSERT INTO rag_search_history (
                call_id, timestamp, user_question, search_results,
                top_score, rag_context_used, search_latency_ms
            )
            VALUES (:call_id, :timestamp, :user_question, :search_results,
                    :top_score, :rag_context_used, :search_latency_ms)
        """
        
        import json
        
        await _db_client.execute(query, {
            "call_id": call_id,
            "timestamp": datetime.now(),
            "user_question": user_question,
            "search_results": json.dumps(search_results),
            "top_score": top_score,
            "rag_context_used": rag_context_used,
            "search_latency_ms": search_latency_ms
        })
        
        logger.debug("RAG search logged",
                    call_id=call_id,
                    results_count=len(search_results))
        
    except Exception as e:
        logger.error("Failed to log RAG search",
                    call_id=call_id,
                    error=str(e))


async def log_llm_process(
    call_id: str,
    input_prompt: Optional[str],
    output_text: str,
    confidence: Optional[float],
    latency_ms: int,
    tokens_used: int,
    model_name: str,
    temperature: float
):
    """
    LLM 처리 로그
    
    Args:
        call_id: 통화 ID
        input_prompt: 입력 프롬프트 (선택)
        output_text: 출력 텍스트
        confidence: 신뢰도 (선택)
        latency_ms: 지연 시간 (밀리초)
        tokens_used: 사용된 토큰 수
        model_name: 모델 이름
        temperature: Temperature 설정
    """
    if not _db_client:
        if "llm" not in _db_skip_warned:
            _db_skip_warned.add("llm")
            logger.warning("DB client not configured, skipping LLM logging", hint="ai_logger.set_db_client(db) to enable")
        return
    
    try:
        query = """
            INSERT INTO llm_process_logs (
                call_id, timestamp, input_prompt, output_text,
                confidence, latency_ms, tokens_used,
                model_name, temperature
            )
            VALUES (:call_id, :timestamp, :input_prompt, :output_text,
                    :confidence, :latency_ms, :tokens_used,
                    :model_name, :temperature)
        """
        
        await _db_client.execute(query, {
            "call_id": call_id,
            "timestamp": datetime.now(),
            "input_prompt": input_prompt[:1000] if input_prompt else None,  # 최대 1000자
            "output_text": output_text,
            "confidence": confidence,
            "latency_ms": latency_ms,
            "tokens_used": tokens_used,
            "model_name": model_name,
            "temperature": temperature
        })
        
        logger.debug("LLM process logged",
                    call_id=call_id,
                    tokens=tokens_used)
        
    except Exception as e:
        logger.error("Failed to log LLM process",
                    call_id=call_id,
                    error=str(e))


async def log_knowledge_match(
    call_id: str,
    matched_knowledge_id: str,
    similarity_score: float,
    knowledge_text: str,
    category: str
):
    """
    지식 매칭 로그
    
    Args:
        call_id: 통화 ID
        matched_knowledge_id: 매칭된 지식 ID
        similarity_score: 유사도 점수
        knowledge_text: 지식 텍스트
        category: 카테고리
    """
    if not _db_client:
        if "knowledge_match" not in _db_skip_warned:
            _db_skip_warned.add("knowledge_match")
            logger.warning("DB client not configured, skipping knowledge match logging", hint="ai_logger.set_db_client(db) to enable")
        return
    
    try:
        query = """
            INSERT INTO knowledge_match_logs (
                call_id, timestamp, matched_knowledge_id,
                similarity_score, knowledge_text, category
            )
            VALUES (:call_id, :timestamp, :matched_knowledge_id,
                    :similarity_score, :knowledge_text, :category)
        """
        
        await _db_client.execute(query, {
            "call_id": call_id,
            "timestamp": datetime.now(),
            "matched_knowledge_id": matched_knowledge_id,
            "similarity_score": similarity_score,
            "knowledge_text": knowledge_text[:500],  # 최대 500자
            "category": category
        })
        
        logger.debug("Knowledge match logged",
                    call_id=call_id,
                    knowledge_id=matched_knowledge_id)
        
    except Exception as e:
        logger.error("Failed to log knowledge match",
                    call_id=call_id,
                    error=str(e))


def log_rag_search_sync(*args, **kwargs):
    """동기 버전 (asyncio.create_task 사용)"""
    asyncio.create_task(log_rag_search(*args, **kwargs))


def log_llm_process_sync(*args, **kwargs):
    """동기 버전 (asyncio.create_task 사용)"""
    asyncio.create_task(log_llm_process(*args, **kwargs))


def log_knowledge_match_sync(*args, **kwargs):
    """동기 버전 (asyncio.create_task 사용)"""
    asyncio.create_task(log_knowledge_match(*args, **kwargs))

