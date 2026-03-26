"""
후처리(확인 필요) 서비스.

AI가 "모르는 내용"으로 응답한 건을 pending_follow_ups 테이블에 저장하고,
운영자가 목록 조회·메모·상태 변경할 수 있도록 한다.
설계: docs/design/UNKNOWN_ANSWER_AND_FOLLOW_UP_DESIGN.md
"""

import structlog
from typing import Optional, Dict, Any, List
from datetime import datetime
from uuid import uuid4

logger = structlog.get_logger(__name__)

_follow_up_service_instance: Optional["FollowUpService"] = None


class FollowUpService:
    """확인 필요(후처리) 저장·조회 서비스."""

    def __init__(self, db=None):
        self.db = db

    def _get_db(self):
        """HITL 서비스와 동일한 DB 사용 (있을 경우)."""
        if self.db is not None:
            return self.db
        try:
            from src.services.hitl import get_hitl_service
            return getattr(get_hitl_service(), "db", None)
        except Exception:
            return None

    async def save_pending_follow_up(
        self,
        call_id: str,
        user_question: str,
        ai_response: str,
        caller_id: Optional[str] = None,
        callee_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        모르는 내용 응답 건을 후처리 목록에 저장.

        Returns:
            request_id (UUID) 또는 None (DB 미사용 시)
        """
        request_id = str(uuid4())
        db = self._get_db()
        if not db:
            logger.debug("follow_up_save_skipped_no_db",
                         call_id=call_id,
                         request_id=request_id,
                         user_question_preview=user_question)
            return None
        try:
            await db.execute(
                """
                INSERT INTO pending_follow_ups
                (id, call_id, caller_id, callee_id, user_question, ai_response, status)
                VALUES (:id, :call_id, :caller_id, :callee_id, :user_question, :ai_response, 'pending')
                """,
                {
                    "id": request_id,
                    "call_id": call_id,
                    "caller_id": caller_id,
                    "callee_id": callee_id or "",
                    "user_question": user_question,
                    "ai_response": ai_response,
                },
            )
            logger.info("pending_follow_up_saved",
                        request_id=request_id,
                        call_id=call_id,
                        user_question_preview=user_question)
            return request_id
        except Exception as e:
            logger.error("pending_follow_up_save_failed",
                         request_id=request_id,
                         call_id=call_id,
                         error=str(e),
                         exc_info=True)
            return None

    async def list_pending_follow_ups(
        self,
        callee_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """목록 조회. callee_id로 테넌트 격리."""
        db = self._get_db()
        if not db:
            return {"items": [], "total": 0}
        try:
            where = "1=1"
            params: Dict[str, Any] = {}
            if callee_id:
                where += " AND callee_id = :callee_id"
                params["callee_id"] = callee_id
            if status:
                where += " AND status = :status"
                params["status"] = status

            count_params = {k: v for k, v in params.items()}
            count_row = await db.fetch_one(
                f"SELECT COUNT(*) AS cnt FROM pending_follow_ups WHERE {where}",
                count_params,
            )
            total = (count_row["cnt"] or 0) if count_row else 0
            params["limit"] = limit
            params["offset"] = offset
            rows = await db.fetch_all(
                f"""
                SELECT id, call_id, caller_id, callee_id, user_question, ai_response,
                       status, operator_note, created_at, updated_at, resolved_at
                FROM pending_follow_ups
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
                """,
                params,
            )
            items = []
            for r in rows:
                items.append({
                    "id": str(r["id"]),
                    "call_id": r["call_id"],
                    "caller_id": r["caller_id"],
                    "callee_id": r["callee_id"],
                    "user_question": r["user_question"],
                    "ai_response": r["ai_response"],
                    "status": r["status"],
                    "operator_note": r["operator_note"],
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
                    "resolved_at": r["resolved_at"].isoformat() if r.get("resolved_at") else None,
                })
            return {"items": items, "total": total or 0}
        except Exception as e:
            logger.error("pending_follow_ups_list_failed", error=str(e), exc_info=True)
            return {"items": [], "total": 0}

    async def update_follow_up(
        self,
        follow_up_id: str,
        status: Optional[str] = None,
        operator_note: Optional[str] = None,
    ) -> bool:
        """상태·메모 업데이트. status가 resolved면 resolved_at 설정."""
        db = self._get_db()
        if not db:
            return False
        try:
            updates = []
            params: Dict[str, Any] = {"id": follow_up_id}
            if status is not None:
                updates.append("status = :status")
                params["status"] = status
            if operator_note is not None:
                updates.append("operator_note = :operator_note")
                params["operator_note"] = operator_note
            if status == "resolved":
                updates.append("resolved_at = NOW()")
            if not updates:
                return True
            await db.execute(
                f"UPDATE pending_follow_ups SET {', '.join(updates)} WHERE id = :id",
                params,
            )
            logger.info("pending_follow_up_updated", id=follow_up_id, status=status)
            return True
        except Exception as e:
            logger.error("pending_follow_up_update_failed", id=follow_up_id, error=str(e))
            return False


def get_follow_up_service(db=None) -> FollowUpService:
    global _follow_up_service_instance
    if _follow_up_service_instance is None:
        _follow_up_service_instance = FollowUpService(db=db)
    elif db is not None and _follow_up_service_instance.db is None:
        _follow_up_service_instance.db = db
    return _follow_up_service_instance
