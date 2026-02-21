"""
AI Insights API

통화별 AI 처리 과정 조회 (RAG, LLM, Knowledge Matching)
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime
import structlog

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/ai-insights", tags=["ai-insights"])


# Response Models
class RAGSearchResult(BaseModel):
    """RAG 검색 결과"""
    id: int
    timestamp: datetime
    user_question: str
    search_results: Optional[List[Dict[str, Any]]] = []
    top_score: Optional[float] = 0.0
    rag_context_used: Optional[str] = None
    search_latency_ms: Optional[int] = None


class LLMProcessLog(BaseModel):
    """LLM 처리 로그"""
    model_config = {"protected_namespaces": ()}
    
    id: int
    timestamp: datetime
    input_prompt: Optional[str] = None
    output_text: str
    confidence: Optional[float] = None
    latency_ms: Optional[int] = None
    tokens_used: Optional[int] = None
    model_name: Optional[str] = None
    temperature: Optional[float] = None


class KnowledgeMatchLog(BaseModel):
    """지식 매칭 로그"""
    id: int
    timestamp: datetime
    matched_knowledge_id: Optional[str] = None
    similarity_score: Optional[float] = None
    knowledge_text: Optional[str] = None
    category: Optional[str] = None


class AIInsightsResponse(BaseModel):
    """AI 처리 과정 전체"""
    call_id: str
    rag_searches: List[RAGSearchResult]
    llm_processes: List[LLMProcessLog]
    knowledge_matches: List[KnowledgeMatchLog]
    total_confidence_avg: float
    total_rag_searches: int
    total_llm_calls: int
    total_tokens_used: int
    avg_latency_ms: Optional[float] = None


class AIInsightsSummary(BaseModel):
    """AI Insights 요약"""
    call_id: str
    caller_id: str
    callee_id: str
    start_time: datetime
    end_time: Optional[datetime]
    rag_searches_count: int
    avg_rag_score: Optional[float]
    llm_calls_count: int
    avg_llm_confidence: Optional[float]
    avg_llm_latency: Optional[float]
    total_tokens_used: Optional[int]
    knowledge_matches_count: int


# Dependencies
async def get_db():
    """Database 클라이언트 가져오기"""
    # TODO: 실제 DB 클라이언트 반환
    return None


async def get_current_operator():
    """현재 운영자 정보 가져오기"""
    # TODO: JWT 토큰에서 운영자 정보 추출
    return {"id": "operator_123", "name": "Operator"}


@router.get("/{call_id}", response_model=AIInsightsResponse)
async def get_ai_insights(
    call_id: str,
    db=Depends(get_db),
    current_user=Depends(get_current_operator)
):
    """
    통화별 AI 처리 과정 조회
    
    Args:
        call_id: 통화 ID
        
    Returns:
        RAG 검색, LLM 처리, 지식 매칭 히스토리
    """
    try:
        if not db:
            # DB가 없으면 빈 데이터 반환
            logger.warning("Database not available, returning empty AI insights",
                          call_id=call_id)
            return AIInsightsResponse(
                call_id=call_id,
                rag_searches=[],
                llm_processes=[],
                knowledge_matches=[],
                total_confidence_avg=0.0,
                total_rag_searches=0,
                total_llm_calls=0,
                total_tokens_used=0
            )
        
        # RAG 검색 히스토리 조회
        rag_query = """
            SELECT 
                id, timestamp, user_question, search_results, 
                top_score, rag_context_used, search_latency_ms
            FROM rag_search_history
            WHERE call_id = :call_id
            ORDER BY timestamp ASC
        """
        rag_results = await db.fetch_all(rag_query, {"call_id": call_id})
        rag_searches = [RAGSearchResult(**dict(row)) for row in rag_results]
        
        # LLM 처리 로그 조회
        llm_query = """
            SELECT 
                id, timestamp, input_prompt, output_text, 
                confidence, latency_ms, tokens_used, 
                model_name, temperature
            FROM llm_process_logs
            WHERE call_id = :call_id
            ORDER BY timestamp ASC
        """
        llm_results = await db.fetch_all(llm_query, {"call_id": call_id})
        llm_processes = [LLMProcessLog(**dict(row)) for row in llm_results]
        
        # 지식 매칭 로그 조회
        knowledge_query = """
            SELECT 
                id, timestamp, matched_knowledge_id, 
                similarity_score, knowledge_text, category
            FROM knowledge_match_logs
            WHERE call_id = :call_id
            ORDER BY timestamp ASC
        """
        knowledge_results = await db.fetch_all(knowledge_query, {"call_id": call_id})
        knowledge_matches = [KnowledgeMatchLog(**dict(row)) for row in knowledge_results]
        
        # 통계 계산
        confidences = [log.confidence for log in llm_processes if log.confidence is not None]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        
        tokens_used = [log.tokens_used for log in llm_processes if log.tokens_used is not None]
        total_tokens = sum(tokens_used) if tokens_used else 0
        
        latencies = [log.latency_ms for log in llm_processes if log.latency_ms is not None]
        avg_latency = sum(latencies) / len(latencies) if latencies else None
        
        logger.info("AI insights retrieved",
                   call_id=call_id,
                   rag_searches=len(rag_searches),
                   llm_calls=len(llm_processes),
                   knowledge_matches=len(knowledge_matches))
        
        return AIInsightsResponse(
            call_id=call_id,
            rag_searches=rag_searches,
            llm_processes=llm_processes,
            knowledge_matches=knowledge_matches,
            total_confidence_avg=avg_confidence,
            total_rag_searches=len(rag_searches),
            total_llm_calls=len(llm_processes),
            total_tokens_used=total_tokens,
            avg_latency_ms=avg_latency
        )
        
    except Exception as e:
        logger.error("Failed to get AI insights",
                    call_id=call_id,
                    error=str(e),
                    exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get AI insights: {str(e)}"
        )


@router.get("/summary/{call_id}", response_model=AIInsightsSummary)
async def get_ai_insights_summary(
    call_id: str,
    db=Depends(get_db),
    current_user=Depends(get_current_operator)
):
    """
    통화별 AI Insights 요약 조회
    
    Args:
        call_id: 통화 ID
        
    Returns:
        AI 처리 통계 요약
    """
    try:
        if not db:
            raise HTTPException(status_code=503, detail="Database not available")
        
        # 요약 뷰에서 조회
        summary_query = """
            SELECT *
            FROM ai_insights_summary
            WHERE call_id = :call_id
        """
        summary = await db.fetch_one(summary_query, {"call_id": call_id})
        
        if not summary:
            raise HTTPException(status_code=404, detail="Call not found")
        
        logger.info("AI insights summary retrieved", call_id=call_id)
        
        return AIInsightsSummary(**dict(summary))
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get AI insights summary",
                    call_id=call_id,
                    error=str(e),
                    exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get AI insights summary: {str(e)}"
        )


@router.get("/stats/overall")
async def get_overall_ai_stats(
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    db=Depends(get_db),
    current_user=Depends(get_current_operator)
):
    """
    전체 AI 처리 통계 조회
    
    Args:
        date_from: 시작 날짜
        date_to: 종료 날짜
        
    Returns:
        전체 AI 처리 통계
    """
    try:
        if not db:
            raise HTTPException(status_code=503, detail="Database not available")
        
        # 전체 통계 쿼리
        stats_query = """
            SELECT 
                COUNT(DISTINCT call_id) as total_ai_calls,
                COUNT(*) as total_rag_searches,
                AVG(top_score) as avg_rag_score,
                AVG(search_latency_ms) as avg_search_latency
            FROM rag_search_history
            WHERE 1=1
        """
        
        params = {}
        
        if date_from:
            stats_query += " AND timestamp >= :date_from"
            params["date_from"] = date_from
        
        if date_to:
            stats_query += " AND timestamp <= :date_to"
            params["date_to"] = date_to
        
        rag_stats = await db.fetch_one(stats_query, params)
        
        # LLM 통계
        llm_stats_query = """
            SELECT 
                COUNT(*) as total_llm_calls,
                AVG(confidence) as avg_confidence,
                AVG(latency_ms) as avg_latency,
                SUM(tokens_used) as total_tokens
            FROM llm_process_logs
            WHERE 1=1
        """
        
        if date_from:
            llm_stats_query += " AND timestamp >= :date_from"
        if date_to:
            llm_stats_query += " AND timestamp <= :date_to"
        
        llm_stats = await db.fetch_one(llm_stats_query, params)
        
        logger.info("Overall AI stats retrieved",
                   date_from=date_from,
                   date_to=date_to)
        
        return {
            "rag_stats": dict(rag_stats) if rag_stats else {},
            "llm_stats": dict(llm_stats) if llm_stats else {},
            "date_range": {
                "from": date_from.isoformat() if date_from else None,
                "to": date_to.isoformat() if date_to else None
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get overall AI stats",
                    error=str(e),
                    exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get overall AI stats: {str(e)}"
        )


@router.delete("/{call_id}")
async def delete_ai_insights(
    call_id: str,
    db=Depends(get_db),
    current_user=Depends(get_current_operator)
):
    """
    통화별 AI Insights 삭제
    
    Args:
        call_id: 통화 ID
        
    Returns:
        삭제 결과
    """
    try:
        if not db:
            raise HTTPException(status_code=503, detail="Database not available")
        
        # CASCADE 설정으로 인해 call_history 삭제 시 자동 삭제됨
        # 여기서는 개별 삭제
        
        # RAG 검색 히스토리 삭제
        await db.execute(
            "DELETE FROM rag_search_history WHERE call_id = :call_id",
            {"call_id": call_id}
        )
        
        # LLM 처리 로그 삭제
        await db.execute(
            "DELETE FROM llm_process_logs WHERE call_id = :call_id",
            {"call_id": call_id}
        )
        
        # 지식 매칭 로그 삭제
        await db.execute(
            "DELETE FROM knowledge_match_logs WHERE call_id = :call_id",
            {"call_id": call_id}
        )
        
        logger.info("AI insights deleted", call_id=call_id)
        
        return {
            "call_id": call_id,
            "status": "deleted",
            "timestamp": datetime.now().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to delete AI insights",
                    call_id=call_id,
                    error=str(e),
                    exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete AI insights: {str(e)}"
        )

