"""
ChromaDB knowledge (및 qa_cache) 메타데이터 마이그레이션

정책:
- metadata.owner → normalize_owner_username (sip:user@host → user)
- metadata.category → VALID_CATEGORIES 밖이면 "question" (RAG·목록 정합)

사용 (sip-pbx 디렉터리에서):
  python -m scripts.migrate_chroma_knowledge_metadata
  python -m scripts.migrate_chroma_knowledge_metadata --dry-run
  python -m scripts.migrate_chroma_knowledge_metadata --collections knowledge
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# sip-pbx 루트를 path에 추가 (직접 실행 호환)
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("chroma_migrate")

from src.ai_voicebot.knowledge.chromadb_client import (  # noqa: E402
    KNOWLEDGE_COLLECTION,
    QA_CACHE_COLLECTION,
    get_chroma_persist_path,
)
from src.ai_voicebot.knowledge.knowledge_service import VALID_CATEGORIES  # noqa: E402
from src.common.sip_owner import normalize_owner_username  # noqa: E402


def _sanitize_metadata(meta: Dict[str, Any]) -> Dict[str, Any]:
    """Chroma 메타데이터: None 제거, 값은 str/int/float/bool만."""
    out: Dict[str, Any] = {}
    for k, v in meta.items():
        if v is None:
            continue
        if isinstance(v, (str, int, float, bool)):
            out[k] = v
        elif isinstance(v, list):
            out[k] = ",".join(str(x) for x in v)
        else:
            out[k] = str(v)
    return out


def _migrate_category_for_knowledge(raw: Any) -> str:
    """knowledge 컬렉션: 비어 있거나 VALID 밖이면 question."""
    c = (str(raw) if raw is not None else "").strip()
    if c in VALID_CATEGORIES:
        return c
    return "question"


def _plan_changes(
    meta: Optional[Dict[str, Any]],
    collection_name: str,
) -> Tuple[Dict[str, Any], bool]:
    """단일 문서 메타데이터 갱신안. 변경 없으면 changed=False."""
    base = dict(meta) if isinstance(meta, dict) else {}
    new_meta = dict(base)
    changed = False

    raw_owner = new_meta.get("owner", "")
    old_owner_s = str(raw_owner).strip() if raw_owner is not None else ""
    new_own = normalize_owner_username(
        raw_owner if isinstance(raw_owner, str) else (str(raw_owner) if raw_owner is not None else "")
    )
    if new_own != old_owner_s:
        new_meta["owner"] = new_own
        changed = True

    if collection_name == KNOWLEDGE_COLLECTION:
        raw_cat = new_meta.get("category", "")
        old_cat_s = str(raw_cat).strip() if raw_cat is not None else ""
        new_cat = _migrate_category_for_knowledge(raw_cat)
        if new_cat != old_cat_s:
            new_meta["category"] = new_cat
            changed = True
    elif collection_name == QA_CACHE_COLLECTION and "category" in new_meta:
        raw_cat = new_meta.get("category", "")
        old_cat_s = str(raw_cat).strip() if raw_cat is not None else ""
        if old_cat_s and old_cat_s not in VALID_CATEGORIES:
            new_meta["category"] = "question"
            changed = True

    new_meta = _sanitize_metadata(new_meta)
    return new_meta, changed


def migrate_collection(
    collection_name: str,
    *,
    dry_run: bool,
) -> Tuple[int, int, int]:
    """
    Returns:
        (total_docs, updated, skipped_no_change)
    """
    import chromadb
    from chromadb.config import Settings

    path = get_chroma_persist_path()
    logger.info("chroma_path=%s collection=%s dry_run=%s", path, collection_name, dry_run)

    client = chromadb.PersistentClient(path=path, settings=Settings(anonymized_telemetry=False))
    try:
        coll = client.get_collection(name=collection_name)
    except Exception as e:
        logger.warning("collection_skip missing_or_error name=%s err=%s", collection_name, e)
        return 0, 0, 0

    # 대량 문서: limit 상한
    batch = coll.get(include=["embeddings", "documents", "metadatas"], limit=100_000)
    ids = list(batch.get("ids") or [])
    embeddings = batch.get("embeddings")
    documents = batch.get("documents")
    metadatas = batch.get("metadatas")

    if not ids:
        logger.info("collection_empty name=%s", collection_name)
        return 0, 0, 0

    total = len(ids)
    updated = 0
    skipped = 0

    for i, doc_id in enumerate(ids):
        meta = metadatas[i] if metadatas and i < len(metadatas) else {}
        if not isinstance(meta, dict):
            meta = {}
        emb = embeddings[i] if embeddings is not None and i < len(embeddings) else None
        doc_text = documents[i] if documents is not None and i < len(documents) else ""

        new_meta, changed = _plan_changes(meta if isinstance(meta, dict) else {}, collection_name)
        if not changed:
            skipped += 1
            continue

        if dry_run:
            parts = []
            o0, o1 = meta.get("owner"), new_meta.get("owner")
            if str(o0 if o0 is not None else "") != str(o1 if o1 is not None else ""):
                parts.append(f"owner {o0!r} -> {o1!r}")
            c0, c1 = meta.get("category"), new_meta.get("category")
            if str(c0 if c0 is not None else "") != str(c1 if c1 is not None else ""):
                parts.append(f"category {c0!r} -> {c1!r}")
            logger.info(
                "dry_run would_update id=%s %s",
                doc_id,
                "; ".join(parts) if parts else "(sanitize only)",
            )
            updated += 1
            continue

        if emb is None:
            logger.warning("skip_no_embedding id=%s", doc_id)
            skipped += 1
            continue

        try:
            coll.upsert(
                ids=[doc_id],
                embeddings=[emb],
                documents=[doc_text if isinstance(doc_text, str) else str(doc_text)],
                metadatas=[new_meta],
            )
            updated += 1
        except Exception as e:
            logger.error("upsert_failed id=%s err=%s", doc_id, e)

    return total, updated, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description="Chroma knowledge/qa_cache metadata migration")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="변경 없이 갱신될 문서만 로그",
    )
    parser.add_argument(
        "--collections",
        nargs="*",
        default=[KNOWLEDGE_COLLECTION, QA_CACHE_COLLECTION],
        help=f"기본: {KNOWLEDGE_COLLECTION} {QA_CACHE_COLLECTION}",
    )
    args = parser.parse_args()

    grand_total = 0
    grand_updated = 0
    grand_skipped = 0

    for name in args.collections:
        t, u, s = migrate_collection(name, dry_run=args.dry_run)
        grand_total += t
        grand_updated += u
        grand_skipped += s
        logger.info(
            "collection_done name=%s total=%s updated_or_would=%s unchanged=%s",
            name,
            t,
            u,
            s,
        )

    logger.info(
        "migration_summary dry_run=%s total_docs=%s updated_or_would=%s unchanged=%s",
        args.dry_run,
        grand_total,
        grand_updated,
        grand_skipped,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
