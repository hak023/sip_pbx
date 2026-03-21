"""
ChromaDB 클라이언트 — 지식 API 및 RAG와 동일한 벡터 DB 접근.

- get_chromadb_client(): lazy 초기화용 클라이언트 (initialize() 지원)
- get_vector_db(): .get(where=..., limit=...), .query(...) 인터페이스

텔레메트리: PostHog 6.x와 Chroma 호환 문제로 "capture() takes 1 positional argument but 3 were given"
오류가 발생할 수 있음. anonymized_telemetry=False 사용 + 로거 억제로 콘솔 오류를 막음.
해결: pip install 'posthog<6.0.0' 로 구버전 고정 권장.
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.ai_voicebot.knowledge.vector_db import Document

# Chroma 텔레메트리 오류 로그 억제 (PostHog 6.x API 호환 이슈 시 "Failed to send telemetry event" 방지)
for _name in ("chromadb.telemetry", "chromadb.telemetry.product.posthog"):
    logging.getLogger(_name).setLevel(logging.CRITICAL)

logger = logging.getLogger(__name__)

# 싱글톤
_client: Any = None
_vector_db: Any = None

# RAG/지식 저장용 컬렉션 이름 (파이프라인과 동일하게 맞출 것)
KNOWLEDGE_COLLECTION = "knowledge"
# 시맨틱 캐시 컬렉션 (LangGraph semantic_cache 노드에서 사용)
QA_CACHE_COLLECTION = "qa_cache"


def _should_clear_qa_cache_on_start() -> bool:
    """서버 기동 시 qa_cache 초기화 여부. True면 기동 시 qa_cache 컬렉션 삭제."""
    v = os.environ.get("CLEAR_QA_CACHE_ON_START", "1").strip().lower()
    return v in ("1", "true", "yes")


def _clear_qa_cache_on_start(client: Any) -> None:
    """설정이 켜져 있으면 qa_cache 컬렉션만 삭제. knowledge 컬렉션은 건드리지 않음."""
    if not _should_clear_qa_cache_on_start():
        return
    try:
        client.delete_collection(QA_CACHE_COLLECTION)
        logger.info("qa_cache cleared on startup (CLEAR_QA_CACHE_ON_START=true)")
    except Exception as e:
        # 컬렉션이 없으면 일부 클라이언트에서 예외 발생 가능
        if "does not exist" in str(e).lower() or "not found" in str(e).lower():
            logger.debug("qa_cache did not exist on startup: %s", e)
        else:
            logger.warning("qa_cache clear on startup failed: %s", e)

# 기본 저장 경로 (환경변수 CHROMA_DB_PATH 또는 프로젝트 루트 data/chroma)
def _chroma_path() -> str:
    if os.environ.get("CHROMA_DB_PATH"):
        return os.environ.get("CHROMA_DB_PATH", "")
    # src/ai_voicebot/knowledge/chromadb_client.py -> 프로젝트 루트 = parents[3]
    root = Path(__file__).resolve().parents[3]
    return str(root / "data" / "chroma")


def get_chroma_persist_path() -> str:
    """ChromaDB 저장 경로 (시드/마이그레이션 스크립트 등에서 동일 경로 사용)."""
    return _chroma_path()


# 시드/메인에서 'from ...chromadb_client import DEFAULT_PERSIST_DIRECTORY' 사용 시 호환
DEFAULT_PERSIST_DIRECTORY = get_chroma_persist_path()


def _normalize_where(where: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """ChromaDB 1.x 호환: 단순 value를 $eq로 감쌈. $and/$or 리스트는 재귀 정규화."""
    if not where:
        return None
    out: Dict[str, Any] = {}
    for k, v in where.items():
        if k in ("$and", "$or") and isinstance(v, list):
            out[k] = [_normalize_where(x) if isinstance(x, dict) else x for x in v]
        elif isinstance(v, dict) and (k.startswith("$") or any(str(x).startswith("$") for x in (v.keys() or []))):
            out[k] = v
        elif isinstance(v, dict):
            out[k] = _normalize_where(v)
        else:
            out[k] = {"$eq": v}
    return out


def _distance_to_score(distance: float, metric: str = "cosine") -> float:
    """Chroma 거리 → 유사도 점수 [0,1]. cosine: 거리 0~2 → 1 - (d/2)."""
    if metric == "cosine":
        return max(0.0, min(1.0, 1.0 - (float(distance) / 2.0)))
    return max(0.0, 1.0 / (1.0 + float(distance)))


class _VectorDbWrapper:
    """ChromaDB Collection을 RAG/API가 기대하는 get/query 시그니처로 감쌈.
    LangGraph semantic_cache용 search_collection / upsert_to_collection 지원."""

    def __init__(self, collection: Any, client: Any = None):
        self._collection = collection
        self._client = client or getattr(collection, "_client", None)

    @property
    def collection(self) -> Any:
        """KnowledgeService 등에서 vector_db.collection.get() 호출 호환용."""
        return self._collection

    def get(
        self,
        where: Optional[Dict[str, Any]] = None,
        limit: int = 1000,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        # collection.get(where=..., limit=...) → ids, documents, metadatas (리스트)
        try:
            w = _normalize_where(where)
            res = self._collection.get(
                where=w,
                limit=limit,
                include=["documents", "metadatas"],
                **kwargs,
            )
            return {
                "ids": list(res.get("ids") or []),
                "documents": list(res.get("documents") or []),
                "metadatas": list(res.get("metadatas") or []),
            }
        except Exception as e:
            logger.warning("ChromaDB get failed: %s", e)
            return {"ids": [], "documents": [], "metadatas": []}

    def query(
        self,
        query_embeddings: List[List[float]],
        n_results: int = 10,
        where: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        # collection.query() → ids, documents, metadatas, distances (리스트의 리스트)
        try:
            w = _normalize_where(where)
            res = self._collection.query(
                query_embeddings=query_embeddings,
                n_results=n_results,
                where=w,
                include=["documents", "metadatas", "distances"],
                **kwargs,
            )
            return {
                "ids": res.get("ids") or [[]],
                "documents": res.get("documents") or [[]],
                "metadatas": res.get("metadatas") or [[]],
                "distances": res.get("distances") or [[]],
            }
        except Exception as e:
            logger.warning("ChromaDB query failed: %s", e)
            return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

    async def upsert(
        self,
        doc_id: str,
        embedding: List[float],
        text: str,
        metadata: Dict[str, Any],
    ) -> None:
        """
        지식 컬렉션 단건 upsert. KnowledgeExtractor / ExtractionPipeline v2 호환.
        (동기 Chroma I/O는 to_thread로 이벤트 루프 블로킹 완화)
        """
        if not doc_id or not embedding:
            raise ValueError("upsert requires doc_id and non-empty embedding")

        def _run() -> None:
            try:
                self._collection.upsert(
                    ids=[doc_id],
                    embeddings=[embedding],
                    documents=[text],
                    metadatas=[metadata],
                )
            except Exception as first_err:
                try:
                    self._collection.add(
                        ids=[doc_id],
                        embeddings=[embedding],
                        documents=[text],
                        metadatas=[metadata],
                    )
                except Exception:
                    logger.warning("ChromaDB upsert failed: %s", first_err)
                    raise first_err

        await asyncio.to_thread(_run)

    async def search(
        self,
        vector: List[float],
        top_k: int = 5,
        filter: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        """
        벡터 유사 검색. SemanticDeduplicator 호환.

        Returns:
            Document 목록. score는 RAG와 동일하게 1/(1+distance) 유사도 [0,1] 근사.
        """
        if not vector:
            return []

        def _run() -> List[Document]:
            w = _normalize_where(filter) if filter else None
            try:
                res = self._collection.query(
                    query_embeddings=[vector],
                    n_results=top_k,
                    where=w,
                    include=["documents", "metadatas", "distances"],
                )
            except Exception as e:
                logger.warning("ChromaDB search (wrapper) failed: %s", e)
                return []
            ids = (res.get("ids") or [[]])[0]
            docs_list = (res.get("documents") or [[]])[0]
            metas = (res.get("metadatas") or [[]])[0]
            dists = (res.get("distances") or [[]])[0]
            out: List[Document] = []
            for i, did in enumerate(ids):
                dist = float(dists[i]) if i < len(dists) else 1.0
                score = 1.0 / (1.0 + dist)
                doc_text = docs_list[i] if i < len(docs_list) else ""
                meta = metas[i] if i < len(metas) else {}
                if not isinstance(meta, dict):
                    meta = {}
                out.append(
                    Document(
                        id=did or "",
                        text=doc_text if isinstance(doc_text, str) else "",
                        score=score,
                        metadata=meta,
                    )
                )
            return out

        return await asyncio.to_thread(_run)

    def add(
        self,
        ids: List[str],
        embeddings: List[List[float]],
        documents: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> None:
        """기본(지식) 컬렉션에 문서 추가. API 시드/지식 추가용."""
        if metadatas is None or len(metadatas) != len(ids):
            metadatas = (metadatas or [])[: len(ids)]
            metadatas = metadatas + [{}] * (len(ids) - len(metadatas))
        try:
            self._collection.add(
                ids=ids,
                embeddings=embeddings,
                documents=documents,
                metadatas=metadatas,
                **kwargs,
            )
        except Exception as e:
            logger.warning("ChromaDB add failed: %s", e)
            raise

    def delete(self, ids: Optional[List[str]] = None, where: Optional[Dict[str, Any]] = None, **kwargs: Any) -> None:
        """지식 컬렉션에서 문서 삭제. ids 또는 where 중 하나 지정."""
        if not ids and not where:
            return
        try:
            if ids:
                self._collection.delete(ids=ids, **kwargs)
            else:
                w = _normalize_where(where)
                self._collection.delete(where=w, **kwargs)
        except Exception as e:
            logger.warning("ChromaDB delete failed: %s", e)
            raise

    def _get_collection(self, collection_name: str, use_cosine: bool = False) -> Any:
        """컬렉션명으로 컬렉션 반환. semantic cache(qa_cache)는 cosine 사용."""
        if not self._client:
            return self._collection
        metadata = {"description": "semantic cache" if use_cosine else "collection"}
        if use_cosine:
            metadata["hnsw:space"] = "cosine"
        return self._client.get_or_create_collection(name=collection_name, metadata=metadata)

    async def search_collection(
        self,
        collection_name: str,
        vector: List[float],
        top_k: int = 1,
        where: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """LangGraph semantic_cache 호환: 벡터 유사 검색 → [{score, metadata}, ...]. where로 intent/category 필터 가능."""
        use_cosine = collection_name == "qa_cache"
        coll = self._get_collection(collection_name, use_cosine=use_cosine)
        w = _normalize_where(where) if where else None
        try:
            res = coll.query(
                query_embeddings=[vector],
                n_results=top_k,
                where=w,
                include=["metadatas", "distances"],
            )
            ids = (res.get("ids") or [[]])[0]
            metadatas = (res.get("metadatas") or [[]])[0]
            distances = (res.get("distances") or [[]])[0]
            metric = "cosine" if use_cosine else "l2"
            return [
                {
                    "score": _distance_to_score(d, metric),
                    "metadata": (metadatas[i] if i < len(metadatas) else {}),
                }
                for i, d in enumerate(distances)
            ]
        except Exception as e:
            logger.warning("ChromaDB search_collection failed: %s", e)
            return []

    async def upsert_to_collection(
        self,
        collection_name: str,
        doc_id: str,
        embedding: List[float],
        text: str,
        metadata: Dict[str, Any],
        **kwargs: Any,
    ) -> None:
        """LangGraph semantic_cache 호환: 단일 문서 추가/갱신."""
        use_cosine = collection_name == "qa_cache"
        coll = self._get_collection(collection_name, use_cosine=use_cosine)
        try:
            coll.upsert(
                ids=[doc_id],
                embeddings=[embedding],
                documents=[text],
                metadatas=[metadata],
            )
        except Exception as e:
            # Chroma 구버전은 add만 지원할 수 있음
            try:
                coll.add(
                    ids=[doc_id],
                    embeddings=[embedding],
                    documents=[text],
                    metadatas=[metadata],
                )
            except Exception as e2:
                logger.warning("ChromaDB upsert_to_collection failed: %s", e2)
                raise


class _ChromaClientWrapper:
    """async initialize() 지원 래퍼 — API에서 lazy init 시 사용."""

    def __init__(self) -> None:
        self._client = None

    async def initialize(self) -> None:
        global _client, _vector_db
        if _vector_db is not None:
            return
        try:
            import chromadb
            from chromadb.config import Settings
            path = _chroma_path()
            Path(path).mkdir(parents=True, exist_ok=True)
            _client = chromadb.PersistentClient(path=path, settings=Settings(anonymized_telemetry=False))
            _clear_qa_cache_on_start(_client)
            coll = _client.get_or_create_collection(name=KNOWLEDGE_COLLECTION, metadata={"description": "call knowledge"})
            _vector_db = _VectorDbWrapper(coll, client=_client)
            logger.info("ChromaDB initialized: path=%s, collection=%s", path, KNOWLEDGE_COLLECTION)
        except Exception as e:
            err_msg = str(e)
            if "collections.topic" in err_msg:
                logger.warning(
                    "ChromaDB initialize failed (schema mismatch): %s | fix: pip install 'chromadb>=0.5.0' 또는 data/chroma 삭제 후 재시작. docs/reports/CHROMA_COLLECTIONS_TOPIC_ERROR.md",
                    err_msg,
                )
            else:
                logger.warning("ChromaDB initialize failed: %s", e)
            raise


def get_chromadb_client(**kwargs) -> _ChromaClientWrapper:
    """Lazy 초기화용 클라이언트. await client.initialize() 후 get_vector_db() 사용.
    kwargs(persist_directory, collection_name 등)는 호환성 위해 무시. 경로는 CHROMA_DB_PATH 또는 data/chroma 사용."""
    return _ChromaClientWrapper()


def get_vector_db() -> Optional[Any]:
    """
    이미 초기화된 벡터 DB 래퍼 반환.
    .get(where=..., limit=...), .query(query_embeddings=..., n_results=..., where=...) 지원.
    """
    global _client, _vector_db
    if _vector_db is not None:
        return _vector_db
    # 동기 1회 초기화 시도 (API 단독 실행 시)
    try:
        import chromadb
        from chromadb.config import Settings
        path = _chroma_path()
        Path(path).mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=path, settings=Settings(anonymized_telemetry=False))
        _clear_qa_cache_on_start(_client)
        coll = _client.get_or_create_collection(name=KNOWLEDGE_COLLECTION, metadata={"description": "call knowledge"})
        _vector_db = _VectorDbWrapper(coll, client=_client)
        logger.info("ChromaDB sync init: path=%s", path)
        return _vector_db
    except Exception as e:
        err_msg = str(e)
        if "collections.topic" in err_msg:
            logger.warning(
                "ChromaDB sync init failed (schema mismatch): %s | fix: pip install 'chromadb>=0.5.0' 또는 data/chroma 삭제. docs/reports/CHROMA_COLLECTIONS_TOPIC_ERROR.md",
                err_msg,
            )
        else:
            logger.warning("ChromaDB sync init failed: %s", e, exc_info=False)
        return None
