"""
Metrics API - 대시보드 메트릭 조회

- GET /api/metrics/dashboard - 대시보드 메트릭
"""

from fastapi import APIRouter, Query
from typing import Dict, Any

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@router.get("/dashboard")
async def get_dashboard_metrics(
    owner: str = Query(..., description="착신번호 (tenant ID)")
) -> Dict[str, Any]:
    """
    대시보드 메트릭 반환
    
    Args:
        owner: 착신번호 (예: "1004")
    
    Returns:
        {
            "hitl_queue_size": 0,
            "avg_ai_confidence": 0.85,
            "today_calls_count": 10,
            "avg_response_time": 2.5,
            "knowledge_base_size": 100
        }
    """
    # TODO: 실제 메트릭 수집 로직 구현
    # 현재는 더미 데이터 반환
    
    return {
        "hitl_queue_size": 0,
        "avg_ai_confidence": 0,
        "today_calls_count": 0,
        "avg_response_time": 0,
        "knowledge_base_size": 0
    }
