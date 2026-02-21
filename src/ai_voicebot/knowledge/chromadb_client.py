"""
ChromaDB Client

ChromaDB를 사용한 Vector DB 구현
"""

import gc
import os
import time

# ✅ ChromaDB telemetry 비활성화 (chromadb import 전에 설정해야 함!)
os.environ['ANONYMIZED_TELEMETRY'] = 'False'
os.environ['CHROMA_TELEMETRY'] = 'False'

# ✅ PostHog 완전 비활성화 (capture() 호환성 오류 방지)
# ChromaDB의 telemetry가 PostHog 신버전과 호환되지 않아
# "capture() takes 1 positional argument but 3 were given" 에러 발생
# posthog를 미리 import하여 capture를 no-op으로 교체
try:
    import posthog
    posthog.project_api_key = ""
    posthog.disabled = True  # PostHog 전체 비활성화
    
    # capture를 no-op으로 교체 (혹시 disabled 플래그를 무시하는 경우 대비)
    def _noop_capture(*args, **kwargs):
        return None
    posthog.capture = _noop_capture
except ImportError:
    pass  # posthog가 설치되지 않은 경우 무시

# ChromaDB import 추적
_import_logger_available = False
try:
    import structlog
    _logger = structlog.get_logger(__name__)
    _import_logger_available = True
    _logger.info("🔄 [ChromaDB Module] Importing chromadb package...")
    _chromadb_import_start = time.time()
except:
    pass

import chromadb
from chromadb.config import Settings

if _import_logger_available:
    _chromadb_import_time = time.time() - _chromadb_import_start
    _logger.info(f"✅ [ChromaDB Module] chromadb package imported", elapsed=f"{_chromadb_import_time:.3f}s")

from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Optional
import asyncio

from .vector_db import VectorDB

import structlog
logger = structlog.get_logger(__name__)

# Single canonical persist directory for the whole process (avoids multiple clients, file-in-use, fallback dirs)
DEFAULT_PERSIST_DIRECTORY = "./data/chromadb"

# PersistentClient(path=...) can block indefinitely if another process holds the DB lock (e.g. Windows).
INIT_TIMEOUT_SECONDS = 30

# Process-wide singleton: only one ChromaDB client per process to avoid "file in use" and schema/fallback issues
_chroma_singleton: Optional["ChromaDBClient"] = None


def get_chromadb_client(
    persist_directory: str = DEFAULT_PERSIST_DIRECTORY,
    collection_name: str = "knowledge_base",
    client_mode: str = "local",
) -> "ChromaDBClient":
    """Return the process-wide ChromaDB client (single DB, no concurrent in-process clients)."""
    global _chroma_singleton
    if _chroma_singleton is None:
        _chroma_singleton = ChromaDBClient(
            collection_name=collection_name,
            persist_directory=persist_directory,
            client_mode=client_mode,
        )
    return _chroma_singleton


class ChromaDBClient(VectorDB):
    """
    ChromaDB Vector Database 클라이언트
    
    로컬 또는 클라이언트/서버 모드로 ChromaDB를 사용합니다.
    단일 DB 보장: get_chromadb_client()로 한 프로세스당 하나의 클라이언트만 사용하세요.
    """
    
    def __init__(
        self,
        collection_name: str = "knowledge_base",
        persist_directory: str = DEFAULT_PERSIST_DIRECTORY,
        client_mode: str = "local"  # "local" or "http"
    ):
        """
        Args:
            collection_name: 컬렉션 이름
            persist_directory: 로컬 저장 디렉토리 (전 프로세스에서 동일 경로 사용 권장)
            client_mode: 클라이언트 모드
        """
        self.collection_name = collection_name
        self.persist_directory = os.path.normpath(persist_directory)
        self.client_mode = client_mode
        
        # 통계
        self.total_upserts = 0
        self.total_searches = 0
        self.total_deletes = 0
        
        # 즉시 초기화 (ChromaDB는 동기 작업)
        self._init_chromadb(auto_recover=True)
    
    # -----------------------------------------------------------------
    # 내부: 초기화 & 스키마 오류 자동 복구
    # -----------------------------------------------------------------

    _SCHEMA_ERROR_KEYWORDS = [
        "no such column",
        "no such table",
        "database disk image is malformed",
        "OperationalError",
    ]

    def _init_chromadb(self, auto_recover: bool = True) -> None:
        """ChromaDB 클라이언트 + 컬렉션 초기화.

        스키마 오류(버전 불일치) 발생 시 기존 데이터를 백업 후
        DB를 재생성하여 서버가 정상 기동되도록 한다.
        """
        try:
            self._create_client_and_collection()
        except Exception as first_err:
            err_msg = str(first_err)
            is_schema_error = any(kw in err_msg for kw in self._SCHEMA_ERROR_KEYWORDS)

            if is_schema_error and auto_recover and self.client_mode == "local":
                logger.warning(
                    "chromadb_schema_error_detected",
                    error=err_msg,
                    persist_directory=self.persist_directory,
                    action="auto_recover",
                    message="ChromaDB 스키마 불일치 감지 → 자동 복구 시도",
                )
                self._recover_from_schema_error()
            else:
                logger.error("ChromaDBClient initialization failed",
                             error=err_msg, exc_info=True)
                self.client = None
                self.collection = None
                raise

    def _create_client_and_collection(self) -> None:
        """PersistentClient 생성 → 컬렉션 획득."""
        logger.info("🔄 [ChromaDB] Starting ChromaDB client initialization...",
                     client_mode=self.client_mode,
                     persist_directory=self.persist_directory)

        if self.client_mode == "local":
            logger.info("🔄 [ChromaDB] Creating Settings...", telemetry=False)
            settings_start = time.time()
            settings = Settings(
                anonymized_telemetry=False,
                allow_reset=True,
            )
            logger.info("✅ [ChromaDB] Settings created",
                         elapsed=f"{time.time() - settings_start:.3f}s")

            logger.info("🔄 [ChromaDB] Creating PersistentClient...",
                         path=self.persist_directory)
            client_start = time.time()
            with ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(
                    chromadb.PersistentClient,
                    path=self.persist_directory,
                    settings=settings,
                )
                try:
                    self.client = fut.result(timeout=INIT_TIMEOUT_SECONDS)
                except Exception as e:
                    elapsed = time.time() - client_start
                    logger.error("chromadb_persistent_client_timeout",
                                 path=self.persist_directory,
                                 timeout_sec=INIT_TIMEOUT_SECONDS,
                                 elapsed=f"{elapsed:.1f}s",
                                 error=str(e))
                    raise RuntimeError(
                        f"ChromaDB 연결이 {INIT_TIMEOUT_SECONDS}초 내에 완료되지 않았습니다. "
                        "다른 프로세스가 data/chromadb를 사용 중이면 모두 종료한 뒤, ./data/chromadb 를 삭제하고 재시작하세요."
                    ) from e
            logger.info("✅ [ChromaDB] PersistentClient created",
                         elapsed=f"{time.time() - client_start:.3f}s")
        else:
            logger.info("🔄 [ChromaDB] Creating HttpClient...")
            self.client = chromadb.HttpClient()
            logger.info("✅ [ChromaDB] HttpClient created")

        # 컬렉션 생성 또는 가져오기
        logger.info("🔄 [ChromaDB] Getting or creating collection...",
                     collection_name=self.collection_name)
        collection_start = time.time()
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        collection_time = time.time() - collection_start

        collection_count = self.collection.count()
        logger.info("✅ [ChromaDB] Collection ready",
                     collection=self.collection_name,
                     document_count=collection_count,
                     elapsed=f"{collection_time:.3f}s")
        logger.info("ChromaDBClient initialized",
                     collection=self.collection_name,
                     mode=self.client_mode,
                     count=collection_count)

    def _recover_from_schema_error(self) -> None:
        """스키마 오류 복구: 동일 경로에서 기존 DB 제거 후 새로 초기화. 폴백 디렉터리 생성 없음.
        이 프로세스가 방금 연 PersistentClient가 chroma.sqlite3을 잡고 있으면
        Windows에서 같은 프로세스가 연 파일을 삭제할 수 없음(WinError 32).
        ChromaDB에 close()가 없어 핸들 해제가 보장되지 않으므로, 자동 rmtree는 시도하지 않고
        사용자에게 수동 삭제 후 재시작하도록 안내한다.
        """
        original_dir = self.persist_directory
        self.client = None
        self.collection = None
        gc.collect()
        # 이 프로세스가 파일을 연 상태에서 rmtree 시도 시 WinError 32 발생하므로 자동 삭제 생략
        logger.error(
            "chromadb_schema_recovery_requires_restart",
            path=original_dir,
            message="ChromaDB 스키마 불일치. 이 프로세스가 DB를 사용 중이라 자동 삭제할 수 없습니다. "
                    "서버를 종료한 뒤 아래 폴더를 수동 삭제하고 재시작하세요: ./data/chromadb",
        )
        raise RuntimeError(
            "ChromaDB 스키마 오류 복구 실패: 이 프로세스가 data/chromadb를 사용 중이라 삭제할 수 없습니다. "
            "서버를 종료한 뒤 ./data/chromadb 폴더를 수동 삭제하고 재시작하세요."
        )

    async def initialize(self) -> None:
        """DB 초기화 (이미 __init__에서 완료됨, 호환성을 위해 유지)"""
        if self.client is None or self.collection is None:
            logger.warning("ChromaDB was not initialized in __init__, attempting re-initialization")
            self._init_chromadb(auto_recover=True)
        else:
            logger.debug("ChromaDB already initialized, skipping")
    
    async def upsert(
        self,
        doc_id: str,
        embedding: List[float],
        text: str,
        metadata: Dict
    ) -> None:
        """문서 저장 또는 업데이트"""
        try:
            # ChromaDB는 동기 API이므로 executor에서 실행
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.collection.upsert(
                    ids=[doc_id],
                    embeddings=[embedding],
                    documents=[text],
                    metadatas=[metadata]
                )
            )
            
            self.total_upserts += 1
            logger.debug("chromadb_document_upserted", category="rag", doc_id=doc_id)
            
        except Exception as e:
            logger.error("chromadb_upsert_failed", category="rag", doc_id=doc_id, error=str(e))
            raise
    
    async def search(
        self,
        vector: List[float],
        top_k: int = 5,
        filter: Optional[Dict] = None
    ) -> List[Dict]:
        """유사도 검색"""
        try:
            # ✅ n_results가 컬렉션 크기를 초과하지 않도록 캡핑
            # (초과 시 ChromaDB가 "Number of requested results N is greater than..." 경고 출력)
            collection_count = self.collection.count()
            effective_top_k = min(top_k, collection_count) if collection_count > 0 else top_k
            
            # ChromaDB 쿼리
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None,
                lambda: self.collection.query(
                    query_embeddings=[vector],
                    n_results=effective_top_k,
                    where=filter,
                    include=["documents", "metadatas", "distances"]
                )
            )
            
            self.total_searches += 1
            
            # 결과 변환
            documents = []
            if results['ids'] and results['ids'][0]:
                for i, doc_id in enumerate(results['ids'][0]):
                    # ChromaDB는 거리를 반환하므로 유사도로 변환
                    distance = results['distances'][0][i]
                    score = 1.0 / (1.0 + distance)  # 거리 → 유사도
                    
                    documents.append({
                        "id": doc_id,
                        "text": results['documents'][0][i],
                        "score": score,
                        "metadata": results['metadatas'][0][i] if results['metadatas'] else {}
                    })
            
            logger.debug("chromadb_search_completed",
                        category="rag",
                        top_k=top_k,
                        results_count=len(documents))
            
            return documents
            
        except Exception as e:
            logger.error("chromadb_search_failed", category="rag", error=str(e))
            return []
    
    async def delete(self, doc_id: str) -> None:
        """문서 삭제"""
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.collection.delete(ids=[doc_id])
            )
            
            self.total_deletes += 1
            logger.debug("Document deleted", doc_id=doc_id)
            
        except Exception as e:
            logger.error("Delete failed", doc_id=doc_id, error=str(e))
    
    async def delete_by_filter(self, filter: Dict) -> int:
        """필터 조건으로 문서 삭제"""
        try:
            # ChromaDB에서 필터로 삭제
            loop = asyncio.get_event_loop()
            
            # 먼저 해당 문서들을 찾기
            results = await loop.run_in_executor(
                None,
                lambda: self.collection.get(where=filter)
            )
            
            if results['ids']:
                # 찾은 문서들 삭제
                await loop.run_in_executor(
                    None,
                    lambda: self.collection.delete(ids=results['ids'])
                )
                
                deleted_count = len(results['ids'])
                self.total_deletes += deleted_count
                
                logger.info("chromadb_deleted_by_filter",
                          category="rag",
                          count=deleted_count,
                          filter=filter)
                
                return deleted_count
            
            return 0
            
        except Exception as e:
            logger.error("Delete by filter failed", filter=filter, error=str(e))
            return 0
    
    async def count(self, filter: Optional[Dict] = None) -> int:
        """문서 수 조회"""
        try:
            loop = asyncio.get_event_loop()
            
            if filter:
                # 필터가 있으면 get으로 조회
                results = await loop.run_in_executor(
                    None,
                    lambda: self.collection.get(where=filter)
                )
                return len(results['ids']) if results['ids'] else 0
            else:
                # 전체 수
                count = await loop.run_in_executor(
                    None,
                    lambda: self.collection.count()
                )
                return count
                
        except Exception as e:
            logger.error("Count failed", error=str(e))
            return 0
    
    def get_stats(self) -> Dict:
        """통계 반환 (초기화 실패 시 client/collection이 None일 수 있음)"""
        try:
            total_docs = self.collection.count() if self.collection else 0
        except Exception:
            total_docs = 0
        return {
            "type": "chromadb",
            "collection_name": self.collection_name,
            "total_documents": total_docs,
            "total_upserts": self.total_upserts,
            "total_searches": self.total_searches,
            "total_deletes": self.total_deletes,
        }

    # =========================================================================
    # 다중 컬렉션 지원 (Phase 2: Semantic Cache, Parent Documents 등)
    # =========================================================================

    def _get_collection(self, collection_name: Optional[str] = None):
        """
        컬렉션 가져오기 (없으면 생성).
        collection_name이 None이면 기본 컬렉션 반환.
        """
        if not collection_name or collection_name == self.collection_name:
            return self.collection
        try:
            return self.client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"},
            )
        except Exception as e:
            logger.error("get_collection_failed",
                        collection=collection_name, error=str(e))
            return None

    async def search_collection(
        self,
        collection_name: str,
        vector: List[float],
        top_k: int = 5,
        filter: Optional[Dict] = None,
    ) -> List[Dict]:
        """특정 컬렉션에서 유사도 검색"""
        try:
            col = self._get_collection(collection_name)
            if not col:
                return []
            
            # ✅ n_results 캡핑
            col_count = col.count()
            effective_top_k = min(top_k, col_count) if col_count > 0 else top_k
            
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None,
                lambda: col.query(
                    query_embeddings=[vector],
                    n_results=effective_top_k,
                    where=filter,
                    include=["documents", "metadatas", "distances"],
                ),
            )
            documents = []
            if results["ids"] and results["ids"][0]:
                for i, doc_id in enumerate(results["ids"][0]):
                    distance = results["distances"][0][i]
                    score = 1.0 / (1.0 + distance)
                    documents.append({
                        "id": doc_id,
                        "text": results["documents"][0][i],
                        "score": score,
                        "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                    })
            logger.debug("search_collection_complete",
                        collection=collection_name, count=len(documents))
            return documents
        except Exception as e:
            logger.error("search_collection_failed",
                        collection=collection_name, error=str(e))
            return []

    async def upsert_to_collection(
        self,
        collection_name: str,
        doc_id: str,
        embedding: List[float],
        text: str,
        metadata: Dict,
    ) -> None:
        """특정 컬렉션에 문서 저장"""
        try:
            col = self._get_collection(collection_name)
            if not col:
                raise RuntimeError(f"Collection '{collection_name}' not available")
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: col.upsert(
                    ids=[doc_id],
                    embeddings=[embedding],
                    documents=[text],
                    metadatas=[metadata],
                ),
            )
            logger.debug("upsert_to_collection_complete",
                        collection=collection_name, doc_id=doc_id)
        except Exception as e:
            logger.error("upsert_to_collection_failed",
                        collection=collection_name, error=str(e))
            raise

