"""테넌트(owner) 없는 잔여 데이터 점검 스크립트 (NFR11, 2026-08-07).

이 시스템은 "테넌트가 업로드한 정보만으로 임의의 원격 REST-API를 조작·안내"하는 도메인
비종속 플랫폼으로 방향이 전환되었으므로(FR34), owner가 비어있는 데이터는 원칙적으로 로컬호스트
종속 개발 시절의 잔여물로 간주한다. `self_service_catalog_config`의 owner=''는 "전역 기본값
(폴백)"으로 의도된 것이라 예외이며, 그 외 테이블/컬렉션에서 owner 누락 행이 발견되면 경고한다.

실행: python scripts/check_ownerless_residue.py
종료 코드: 발견되면 1, 없으면 0(CI/정기 점검에서 그대로 사용 가능).
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DB_PATH = _REPO_ROOT / "data" / "booking.db"
_CHROMA_PATH = _REPO_ROOT / "data" / "chroma"


def _check_sqlite() -> list[str]:
    problems: list[str] = []
    if not _DB_PATH.exists():
        return problems
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        for table in ("knowledge_documents", "tool_execution_log", "self_service_decision_log"):
            try:
                rows = conn.execute(
                    f"SELECT COUNT(*) AS c FROM {table} WHERE owner IS NULL OR TRIM(owner) = ''"
                ).fetchone()
            except sqlite3.OperationalError:
                continue  # 테이블 자체가 없으면(구버전 DB) 건너뜀
            if rows and rows["c"]:
                problems.append(f"{table}: ownerless {rows['c']}건")
    finally:
        conn.close()
    return problems


def _check_chroma() -> list[str]:
    problems: list[str] = []
    try:
        import chromadb
    except ImportError:
        return problems
    if not _CHROMA_PATH.exists():
        return problems
    client = chromadb.PersistentClient(path=str(_CHROMA_PATH))
    for name in client.list_collections():
        col = client.get_collection(name)
        total = col.count()
        if not total:
            continue
        got = col.get(limit=min(total, 20000), include=["metadatas"])
        no_owner = sum(1 for m in (got.get("metadatas") or []) if not (m or {}).get("owner"))
        if no_owner:
            problems.append(f"chroma:{name}: ownerless {no_owner}/{total}건")
    return problems


def main() -> int:
    problems = _check_sqlite() + _check_chroma()
    if not problems:
        print("[OK] ownerless 잔여 데이터 없음")
        return 0
    print("[WARN] ownerless 잔여 데이터 발견:")
    for p in problems:
        print(f"  - {p}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
