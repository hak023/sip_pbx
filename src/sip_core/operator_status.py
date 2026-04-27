"""
Operator Status Manager

운영자 부재중 상태 관리.

상태는 JSON 파일로 영속화하여 서버 재시작 후에도 유지된다.
저장 경로: 환경변수 OPERATOR_STATUS_FILE (기본 ./data/operator_status.json)
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, Optional

import structlog

logger = structlog.get_logger(__name__)

# 상태 파일 경로 — 환경변수로 재정의 가능
_DEFAULT_STATUS_FILE = Path(
    os.environ.get("OPERATOR_STATUS_FILE", "./data/operator_status.json")
)


class OperatorStatus(str, Enum):
    """운영자 상태"""
    AVAILABLE = "available"
    AWAY = "away"  # 부재중 (AI 응대 모드)
    BUSY = "busy"
    OFFLINE = "offline"


class OperatorStatusManager:
    """운영자 상태 관리자.

    인메모리 딕셔너리를 유지하면서 변경 시마다 JSON 파일에 저장한다.
    서버 재시작 후에도 이전 상태가 복원된다.
    파일 I/O는 스레드 락으로 보호한다.
    """

    def __init__(self, status_file: Path = _DEFAULT_STATUS_FILE) -> None:
        self._status_file = status_file
        self._lock = threading.Lock()
        self._status: Dict[str, OperatorStatus] = {}
        self._away_messages: Dict[str, str] = {}
        self._status_changed_at: Dict[str, datetime] = {}
        self._fallback_modes: Dict[str, str] = {}  # "hitl" | "transfer"
        self._load()
        logger.info(
            "operator_status_manager_initialized",
            status_file=str(self._status_file),
            loaded_tenants=list(self._status.keys()),
        )

    # ------------------------------------------------------------------
    # 내부 영속화 헬퍼
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """파일에서 상태 복원. 파일이 없거나 손상된 경우 빈 상태로 시작."""
        try:
            if not self._status_file.exists():
                return
            raw = self._status_file.read_text(encoding="utf-8")
            data: dict = json.loads(raw)
            for uid, entry in data.items():
                try:
                    self._status[uid] = OperatorStatus(entry["status"])
                    if entry.get("away_message"):
                        self._away_messages[uid] = entry["away_message"]
                    if entry.get("status_changed_at"):
                        self._status_changed_at[uid] = datetime.fromisoformat(
                            entry["status_changed_at"]
                        )
                    if entry.get("ai_fallback_mode") in ("hitl", "transfer"):
                        self._fallback_modes[uid] = entry["ai_fallback_mode"]
                except (KeyError, ValueError):
                    logger.warning(
                        "operator_status_load_entry_skipped",
                        uid=uid,
                        note="잘못된 항목 — 건너뜀",
                    )
        except Exception as exc:
            logger.warning(
                "operator_status_load_failed",
                error=str(exc),
                note="상태 파일 로드 실패 — 빈 상태로 시작",
            )

    def _save(self) -> None:
        """현재 상태를 JSON 파일에 저장. 파일 디렉토리가 없으면 생성."""
        try:
            self._status_file.parent.mkdir(parents=True, exist_ok=True)
            data: dict = {}
            for uid, st in self._status.items():
                entry: dict = {"status": st.value}
                if uid in self._away_messages:
                    entry["away_message"] = self._away_messages[uid]
                if uid in self._status_changed_at:
                    entry["status_changed_at"] = self._status_changed_at[uid].isoformat()
                if uid in self._fallback_modes:
                    entry["ai_fallback_mode"] = self._fallback_modes[uid]
                data[uid] = entry
            tmp = self._status_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self._status_file)
        except Exception as exc:
            logger.error(
                "operator_status_save_failed",
                error=str(exc),
                note="상태 파일 저장 실패 — 인메모리 상태는 유지됨",
            )

    # ------------------------------------------------------------------
    # 공개 API
    # ------------------------------------------------------------------

    def set_status(
        self,
        user_id: str,
        status: OperatorStatus,
        away_message: Optional[str] = None,
    ) -> None:
        """운영자 상태 설정 후 파일에 저장."""
        with self._lock:
            self._status[user_id] = status
            self._status_changed_at[user_id] = datetime.now()
            if status == OperatorStatus.AWAY and away_message:
                self._away_messages[user_id] = away_message
            elif status != OperatorStatus.AWAY:
                self._away_messages.pop(user_id, None)
            self._save()
        logger.info(
            "operator_status_updated",
            user_id=user_id,
            status=status.value,
            has_away_message=bool(away_message),
        )

    def get_status(self, user_id: str) -> OperatorStatus:
        """운영자 상태 조회 (기본값: AVAILABLE)."""
        return self._status.get(user_id, OperatorStatus.AVAILABLE)

    def is_away(self, user_id: str) -> bool:
        """부재중 상태 확인."""
        return self.get_status(user_id) == OperatorStatus.AWAY

    def get_away_message(self, user_id: str) -> str:
        """부재중 메시지 조회 (기본 메시지 반환)."""
        return self._away_messages.get(
            user_id,
            "죄송합니다. 현재 자리를 비웠습니다. AI 비서가 도와드리겠습니다.",
        )

    def set_fallback_mode(self, user_id: str, mode: str) -> None:
        """AI 폴백 모드 설정 (hitl | transfer)."""
        with self._lock:
            self._fallback_modes[user_id] = mode
            self._save()
        logger.info("operator_fallback_mode_updated", user_id=user_id, mode=mode)

    def get_fallback_mode(self, user_id: str) -> str:
        """AI 폴백 모드 조회 (기본값: hitl)."""
        return self._fallback_modes.get(user_id, "hitl")

    def get_status_info(self, user_id: str) -> dict:
        """운영자 상태 상세 정보 조회."""
        status = self.get_status(user_id)
        return {
            "user_id": user_id,
            "status": status.value,
            "is_away": status == OperatorStatus.AWAY,
            "away_message": self.get_away_message(user_id) if status == OperatorStatus.AWAY else None,
            "status_changed_at": (
                self._status_changed_at[user_id].isoformat()
                if user_id in self._status_changed_at
                else None
            ),
            "ai_fallback_mode": self.get_fallback_mode(user_id),
        }

    def clear_status(self, user_id: str) -> None:
        """운영자 상태 초기화 후 파일에 반영."""
        with self._lock:
            self._status.pop(user_id, None)
            self._away_messages.pop(user_id, None)
            self._status_changed_at.pop(user_id, None)
            self._save()
        logger.info("operator_status_cleared", user_id=user_id)


# 싱글톤 인스턴스
_operator_status_manager: Optional[OperatorStatusManager] = None


def get_operator_status_manager() -> OperatorStatusManager:
    """운영자 상태 관리자 싱글톤 인스턴스 가져오기."""
    global _operator_status_manager
    if _operator_status_manager is None:
        _operator_status_manager = OperatorStatusManager()
    return _operator_status_manager
