"""메트릭 관련 API

대시보드에 표시할 실시간 메트릭을 제공한다.
owner(착신번호) 기반으로 테넌트별 메트릭을 분리한다.
"""
from fastapi import APIRouter, Query
from typing import Optional
from datetime import datetime, date
from pathlib import Path
import json
import structlog

from ..models import DashboardMetrics
from src.services.knowledge_service import get_knowledge_service
from src.sip_core.utils import extract_extension_from_uri
from .calls import _get_call_manager_optional

logger = structlog.get_logger(__name__)

router = APIRouter()

knowledge_service = get_knowledge_service()


@router.get("/dashboard", response_model=DashboardMetrics)
async def get_dashboard_metrics(
    owner: Optional[str] = Query(None, description="착신번호(테넌트 ID)로 필터링"),
):
    """
    대시보드 메트릭 조회

    VectorDB 및 CDR 데이터 기반 실시간 메트릭 반환.
    """
    active_calls = 0
    hitl_queue_size = 0
    avg_ai_confidence = 0.0
    today_calls_count = 0
    avg_response_time = 0.0
    knowledge_base_size = 0

    try:
        # 1. 지식 베이스 크기 (owner별)
        if not knowledge_service._initialized:
            await knowledge_service.initialize()

        import asyncio
        loop = asyncio.get_event_loop()

        if owner:
            # owner가 있는 knowledge 문서 수 (capability, tenant_config 제외)
            # ChromaDB: $and는 최소 2개 식 필요 → 단일 조건은 그냥 where={"owner": owner}
            results = await loop.run_in_executor(
                None,
                lambda: knowledge_service.vector_db.collection.get(
                    where={"owner": owner},
                    limit=10000,
                    include=["metadatas"],
                ),
            )
            if results["ids"]:
                # doc_type이 capability나 tenant_config가 아닌 것만 카운트
                knowledge_base_size = sum(
                    1 for meta in results["metadatas"]
                    if meta.get("doc_type", "") not in ("capability", "tenant_config")
                )
        else:
            stats = await knowledge_service.get_stats()
            knowledge_base_size = stats.get("total_documents", 0)

        # 2. 오늘 통화 수 (CDR 기반)
        today_str = date.today().strftime("%Y-%m-%d")
        cdr_file = Path(f"./cdr/cdr-{today_str}.jsonl")
        if cdr_file.exists():
            try:
                with open(cdr_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                if owner:
                    # callee가 owner인 통화만 카운트
                    for line in lines:
                        try:
                            cdr = json.loads(line.strip())
                            callee = cdr.get("callee_number", "")
                            if owner in callee:
                                today_calls_count += 1
                        except json.JSONDecodeError:
                            continue
                else:
                    today_calls_count = len(lines)
            except Exception:
                pass

        # 3. 활성 통화 수 (CallManager 연동 — owner별 필터)
        call_manager = _get_call_manager_optional()
        if call_manager and owner:
            active_sessions = call_manager.call_repository.get_active_sessions()
            for session in active_sessions:
                callee_uri = session.get_callee_uri()
                callee_ext = extract_extension_from_uri(callee_uri) if callee_uri else ""
                if callee_ext == owner:
                    active_calls += 1
        elif call_manager and not owner:
            active_sessions = call_manager.call_repository.get_active_sessions()
            active_calls = len(active_sessions)

    except Exception as e:
        logger.error("dashboard_metrics_error", error=str(e))

    return DashboardMetrics(
        active_calls=active_calls,
        hitl_queue_size=hitl_queue_size,
        avg_ai_confidence=avg_ai_confidence,
        today_calls_count=today_calls_count,
        avg_response_time=avg_response_time,
        knowledge_base_size=knowledge_base_size,
    )
