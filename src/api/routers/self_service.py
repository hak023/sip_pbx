"""
셀프서비스 자동설정 변경 이력 조회 REST API (Story 1.9).

Story 1.8에서 쌓이는 `self_service_config_changes` 테이블을 프론트엔드가 표시하기
위한 유일한 신규 엔드포인트다(Architecture 문서의 "이 Epic은 신규 REST 엔드포인트가
필요 없다" 원칙의 유일한 예외 — 다른 모든 Story는 LangGraph Tool이 서비스 레이어를
직접 호출해 별도 API가 필요 없었다).

읽기 전용이며 `src/common/self_service_config_change_db.py::list_config_changes()`만
호출한다(새 조회 로직을 만들지 않음).
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Query

from src.common.self_service_config_change_db import list_config_changes

router = APIRouter(prefix="/api/self-service", tags=["self-service"])


@router.get("/config-changes")
def get_config_changes(
    owner: str = Query(..., description="테넌트 owner"),
    limit: int = Query(50, ge=1, le=500, description="최대 조회 건수"),
) -> Dict[str, Any]:
    """owner의 최근 자동설정 변경 이력을 changed_at DESC 순으로 반환한다."""
    items = list_config_changes(owner, limit=limit)
    return {"items": items, "total": len(items)}
