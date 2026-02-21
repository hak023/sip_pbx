"""
유용성 판단 추출 결과의 검토 대기열 (PII 파이프라인·검토 워크플로).

설계서 §7: contains_pii인 항목 또는 검토 대상 항목을 VectorDB에 바로 넣지 않고
이 스토어에 적재한 뒤, 승인/편집/거절 후 VectorDB 반영.
"""

from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime
import json
import uuid
import asyncio
import structlog

logger = structlog.get_logger(__name__)

DEFAULT_PENDING_FILE = "data/extraction_pending_review.jsonl"
VALID_STATUSES = {"pending", "approved", "rejected", "edited"}
VALID_CATEGORIES = {"FAQ", "이슈해결", "약속", "정보", "지시", "선호도", "기타"}


def _ensure_dir(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def _next_id() -> str:
    return f"pending_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


class ExtractionReviewStore:
    """검토 대기열 저장소 (JSONL 파일)."""

    def __init__(self, filepath: str = DEFAULT_PENDING_FILE):
        self._filepath = Path(filepath)
        self._lock = asyncio.Lock()

    def _read_all(self) -> List[Dict]:
        if not self._filepath.exists():
            return []
        out = []
        with open(self._filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out

    def _write_all(self, items: List[Dict]) -> None:
        _ensure_dir(str(self._filepath))
        with open(self._filepath, "w", encoding="utf-8") as f:
            for item in items:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

    async def add(
        self,
        call_id: str,
        owner: str,
        speaker: str,
        text: str,
        category: str,
        keywords: List[str],
        contains_pii: bool,
        confidence: float,
        chunk_index: int = 0,
    ) -> str:
        """검토 대기열에 항목 추가. id 반환."""
        pid = _next_id()
        cat = category if category in VALID_CATEGORIES else "기타"
        record = {
            "id": pid,
            "call_id": call_id,
            "owner": owner,
            "speaker": speaker,
            "text": text,
            "category": cat,
            "keywords": keywords,
            "contains_pii": contains_pii,
            "confidence": confidence,
            "chunk_index": chunk_index,
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            "reviewed_by": None,
            "reviewed_at": None,
        }
        async with self._lock:
            items = self._read_all()
            items.append(record)
            self._write_all(items)
        logger.info("extraction_pending_added", id=pid, call_id=call_id, contains_pii=contains_pii)
        return pid

    async def list_pending(
        self,
        owner: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict]:
        """대기열 목록 (기본: status=pending)."""
        async with self._lock:
            items = self._read_all()
        if owner:
            items = [i for i in items if i.get("owner") == owner]
        if status:
            items = [i for i in items if i.get("status") == status]
        items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return items[:limit]

    async def get(self, id: str) -> Optional[Dict]:
        """id로 단일 항목 조회."""
        async with self._lock:
            items = self._read_all()
        for item in items:
            if item.get("id") == id:
                return item
        return None

    async def update_status(
        self,
        id: str,
        status: str,
        reviewer: str = "operator",
        edited_text: Optional[str] = None,
        edited_category: Optional[str] = None,
    ) -> Optional[Dict]:
        """상태 업데이트 (approved/rejected/edit). 편집 시 text/category 반영."""
        if status not in VALID_STATUSES:
            return None
        async with self._lock:
            items = self._read_all()
            for i, item in enumerate(items):
                if item.get("id") != id:
                    continue
                item["status"] = status
                item["reviewed_by"] = reviewer
                item["reviewed_at"] = datetime.now().isoformat()
                if edited_text is not None:
                    item["text"] = edited_text
                if edited_category is not None and edited_category in VALID_CATEGORIES:
                    item["category"] = edited_category
                self._write_all(items)
                return item
        return None


# 싱글톤
_store: Optional[ExtractionReviewStore] = None


def get_extraction_review_store(filepath: Optional[str] = None) -> ExtractionReviewStore:
    global _store
    if _store is None:
        _store = ExtractionReviewStore(filepath or DEFAULT_PENDING_FILE)
    return _store
