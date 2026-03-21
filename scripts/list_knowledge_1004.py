"""1004 테넌트 지식베이스 내용 조회. API 우선, 없으면 ChromaDB 직접 확인."""
import sys
import json
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
CHROMA_DB = ROOT / "data" / "chroma" / "chroma.sqlite3"
CHROMA_PATH = ROOT / "data" / "chroma"


def via_api(base_url: str = "http://localhost:8000") -> None:
    try:
        req = urllib.request.Request(
            f"{base_url.rstrip('/')}/api/knowledge?tenant_id=1004&limit=100",
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            total = data.get("total", 0)
            items = data.get("items", [])
            print(f"[API] tenant_id=1004 total={total}")
            for i, item in enumerate(items, 1):
                text = (item.get("text") or "")[:80]
                print(f"  {i}. {text}...")
            if not items:
                print("  (empty)")
    except Exception as e:
        print(f"[API] Error: {e}")


def via_chroma_sqlite() -> None:
    if not CHROMA_DB.exists():
        print(f"[ChromaDB] Not found: {CHROMA_DB}")
        return
    import sqlite3
    conn = sqlite3.connect(str(CHROMA_DB))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute("SELECT id, name FROM collections WHERE name = 'knowledge'")
        coll = cur.fetchone()
        if not coll:
            print("[ChromaDB] No 'knowledge' collection")
            return
        cid = coll["id"]
        print(f"[ChromaDB] knowledge collection id: {cid}")
        cur = conn.execute("PRAGMA table_info(segments)")
        seg_cols = [r[1] for r in cur.fetchall()]
        print("  segments cols:", seg_cols)
        cur = conn.execute("SELECT * FROM segments LIMIT 5")
        for r in cur.fetchall():
            print("   ", dict(r))
        cur = conn.execute("PRAGMA table_info(segment_metadata)")
        sm_cols = [r[1] for r in cur.fetchall()]
        print("  segment_metadata cols:", sm_cols)
        cur = conn.execute("SELECT * FROM segment_metadata LIMIT 20")
        for r in cur.fetchall():
            d = dict(r)
            v = str(d.get("value", ""))[:60]
            print("   ", d.get("segment_id"), d.get("key"), v)
    finally:
        conn.close()


def via_chroma_client() -> None:
    """Chroma PersistentClient로 knowledge 컬렉션 문서 조회 (owner=1004 필터)."""
    if not CHROMA_PATH.exists():
        print(f"[Chroma] Path not found: {CHROMA_PATH}")
        return
    try:
        import chromadb
        client = chromadb.PersistentClient(path=str(CHROMA_PATH))
        try:
            coll = client.get_collection("knowledge")
        except Exception:
            colls = client.list_collections()
            print("  Available collections:", [c.name for c in colls])
            if not colls:
                return
            coll = colls[0]
        n = coll.count()
        print(f"[Chroma] knowledge collection count: {n}")
        if n == 0:
            print("  (no documents)")
            return
        data = coll.get(limit=100, include=["documents", "metadatas"])
        ids = data.get("ids") or []
        docs = data.get("documents") or []
        metas = data.get("metadatas") or ([{}] * len(ids))
        for i, (id_, doc, meta) in enumerate(zip(ids, docs, metas), 1):
            owner = (meta or {}).get("owner") or (meta or {}).get("tenant_id") or "?"
            text = (doc or "")[:100]
            print(f"  {i}. id={str(id_)[:24]}... owner={owner} | {text}...")
        try:
            data1004 = coll.get(where={"owner": "1004"}, limit=100, include=["documents", "metadatas"])
        except Exception:
            data1004 = {"ids": [], "documents": [], "metadatas": []}
        ids4 = data1004.get("ids") or []
        docs4 = data1004.get("documents") or []
        print(f"\n  owner=1004 only: {len(ids4)} docs")
        for i, (id_, doc) in enumerate(zip(ids4, docs4), 1):
            print(f"    {i}. {(doc or '')[:80]}...")
    except Exception as e:
        print(f"[Chroma] Error: {e}")


if __name__ == "__main__":
    base = (sys.argv[1] if len(sys.argv) > 1 else None) or "http://localhost:8000"
    print("=== API (tenant_id=1004) === ")
    via_api(base)
    print("\n=== ChromaDB client (knowledge collection) === ")
    via_chroma_client()
    print("\n=== ChromaDB (sqlite raw) === ")
    via_chroma_sqlite()
