"""
Metrics API - 대시보드 메트릭 조회

- GET /api/metrics/dashboard - 대시보드 메트릭
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Query

from src.ai_voicebot.knowledge.chromadb_client import get_vector_db
from src.services.hitl import get_hitl_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


def _count_today_calls() -> int:
    """오늘 발생한 통화 수 (recordings 디렉터리의 YYYYMMDD_* 폴더 기준)."""
    try:
        base_dir = Path("recordings")
        if not base_dir.exists():
            return 0
        today_prefix = datetime.now().strftime("%Y%m%d")
        count = sum(
            1
            for item in base_dir.iterdir()
            if item.is_dir() and item.name.startswith(today_prefix)
        )
        return count
    except Exception as e:
        logger.warning("metrics_today_calls_count_error error=%s", e)
        return 0


def _get_hitl_queue_size() -> int:
    """현재 HITL 대기 중인 요청 수."""
    try:
        hitl_service = get_hitl_service()
        # HITLService._hitl_request_fifo의 총 요청 수 집계
        total_pending = sum(
            len(dq) for dq in hitl_service._hitl_request_fifo.values()
        )
        return total_pending
    except Exception as e:
        logger.warning("metrics_hitl_queue_size_error error=%s", e)
        return 0


def _get_avg_confidence_today(owner: str) -> float:
    """오늘 통화의 평균 AI 신뢰도 (logs/call_data_record_*.log 분석)."""
    try:
        today_str = datetime.now().strftime("%Y%m%d")
        log_path = Path("logs") / f"call_data_record_{today_str}.log"
        if not log_path.exists():
            return 0.0

        confidences = []
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    # llm_response_generated 이벤트에서 confidence 추출
                    if obj.get("event") == "llm_response_generated" and "confidence" in obj:
                        conf = float(obj["confidence"])
                        if 0 <= conf <= 1:
                            confidences.append(conf)
                except (json.JSONDecodeError, ValueError, KeyError):
                    continue

        if not confidences:
            return 0.0
        return sum(confidences) / len(confidences)
    except Exception as e:
        logger.warning("metrics_avg_confidence_error error=%s", e)
        return 0.0


def _get_knowledge_base_size(owner: Optional[str] = None) -> int:
    """지식베이스 총 문서 수 (ChromaDB knowledge 컬렉션)."""
    try:
        vdb = get_vector_db()
        if vdb is None:
            return 0
        # ChromaDB collection.count() 호출
        collection = getattr(vdb, "_collection", None)
        if collection is None:
            return 0
        
        # owner가 지정된 경우 필터링, 아니면 전체
        if owner:
            try:
                results = collection.get(where={"owner": owner}, limit=10000)
                if results and "ids" in results:
                    return len(results["ids"])
            except Exception:
                pass
        
        # owner 미지정이거나 필터링 실패 시 전체
        count = collection.count()
        return count if count else 0
    except Exception as e:
        logger.warning("metrics_knowledge_base_size_error error=%s", e)
        return 0


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
    return {
        "hitl_queue_size": _get_hitl_queue_size(),
        "avg_ai_confidence": _get_avg_confidence_today(owner),
        "today_calls_count": _count_today_calls(),
        "avg_response_time": 0,  # 추후 구현 가능
        "knowledge_base_size": _get_knowledge_base_size(owner),
    }
