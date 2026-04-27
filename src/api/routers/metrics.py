"""
Metrics API - 대시보드 메트릭 조회

- GET /api/metrics/dashboard - 대시보드 메트릭
"""

import json
import logging
import os
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


def _recordings_root() -> Path:
    raw = (
        os.environ.get("SIP_RECORDINGS_DIR")
        or os.environ.get("RECORDINGS_DIR")
        or "./recordings"
    )
    return Path(raw).resolve()


def _count_unresolved_calls(owner: str) -> int:
    """전체 통화이력 기준 미해결 건수.

    우선순위:
      1. DB call_records.is_unresolved = 1 (owner 필터)
      2. DB 없으면 recordings 폴더 스캔 → call_insights.json.is_unresolved=True 합산
    """
    # DB 우선
    try:
        from src.common.call_record_db import get_call_records_page
        result = get_call_records_page(owner=owner, limit=10000, offset=0)
        if result is not None and result.get("total", 0) > 0:
            items = result.get("items") or []
            db_count = sum(1 for it in items if it.get("is_unresolved"))
            # call_insights.json이 있으면 JSON 값이 우선이므로 보완
            from src.common.call_insights_buffer import load_call_insights_for_directory
            root = _recordings_root()
            if root.is_dir():
                for it in items:
                    cid = str(it.get("call_id") or "")
                    rec_dir_raw = it.get("recordings_dir") or ""
                    call_dir = Path(rec_dir_raw) if rec_dir_raw else None
                    if call_dir is None or not call_dir.is_dir():
                        # recordings root에서 call_id로 탐색
                        for sub in root.iterdir():
                            if not sub.is_dir():
                                continue
                            meta_p = sub / "metadata.json"
                            if not meta_p.is_file():
                                continue
                            try:
                                import json as _json
                                with open(meta_p, "r", encoding="utf-8") as f:
                                    meta = _json.load(f)
                                if str(meta.get("call_id") or "") == cid:
                                    call_dir = sub
                                    break
                            except Exception:
                                continue
                    if call_dir and call_dir.is_dir():
                        insights = load_call_insights_for_directory(call_dir)
                        if insights and "is_unresolved" in insights:
                            current_db = bool(it.get("is_unresolved"))
                            json_val = bool(insights["is_unresolved"])
                            if json_val != current_db:
                                db_count += (1 if json_val else -1)
            logger.debug("metrics_unresolved_count_db owner=%s count=%s", owner, db_count)
            return max(0, db_count)
    except Exception as exc:
        logger.debug("metrics_unresolved_db_skip err=%s", exc)

    # 파일 스캔 fallback
    try:
        from src.common.call_insights_buffer import load_call_insights_for_directory
        from src.common.sip_owner import normalize_owner_username
        root = _recordings_root()
        if not root.is_dir():
            return 0
        want = normalize_owner_username(owner) if owner else ""
        count = 0
        for sub in root.iterdir():
            if not sub.is_dir() or sub.name.startswith("."):
                continue
            meta_p = sub / "metadata.json"
            if not meta_p.is_file():
                continue
            try:
                import json as _json
                with open(meta_p, "r", encoding="utf-8") as f:
                    meta = _json.load(f)
            except Exception:
                continue
            if owner:
                from src.api.routers.call_history import _owner_matches_row
                if not _owner_matches_row(owner, str(meta.get("callee_id") or ""), str(meta.get("caller_id") or "")):
                    continue
            insights = load_call_insights_for_directory(sub)
            if insights and insights.get("is_unresolved"):
                count += 1
        logger.debug("metrics_unresolved_count_scan owner=%s count=%s", owner, count)
        return count
    except Exception as exc:
        logger.warning("metrics_unresolved_count_failed owner=%s err=%s", owner, exc)
        return 0


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
            "knowledge_base_size": 100,
            "unresolved_calls_count": 3
        }
    """
    return {
        "hitl_queue_size": _get_hitl_queue_size(),
        "avg_ai_confidence": _get_avg_confidence_today(owner),
        "today_calls_count": _count_today_calls(),
        "avg_response_time": 0,  # 추후 구현 가능
        "knowledge_base_size": _get_knowledge_base_size(owner),
        "unresolved_calls_count": _count_unresolved_calls(owner),
    }
