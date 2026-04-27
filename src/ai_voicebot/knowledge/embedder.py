"""
TextEmbedder — SentenceTransformer 기반 텍스트 임베딩.

- model_name으로 모델 로드. SentenceTransformer(model_name_or_path)만 사용하며,
  dimension 인자는 사용하지 않음 (모델이 정한 차원 사용).
- embed_text() 동기, embed() 비동기(내부적으로 to_thread→embed_text). 지식 API·RAG·추출 파이프라인에서 사용.
"""

import asyncio
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

# SentenceTransformer는 __init__에 dimension 인자를 지원하지 않음 (모델별 고정 차원)
_DEFAULT_MODEL = "paraphrase-multilingual-mpnet-base-v2"
_embedder_instance: Optional["TextEmbedder"] = None


class TextEmbedder:
    """SentenceTransformer 기반 텍스트 임베딩. dimension 인자는 SentenceTransformer에 전달하지 않음."""

    def __init__(
        self,
        model_name: Optional[str] = None,
        model: Optional[object] = None,
        **kwargs,
    ):
        """
        model_name 또는 model 중 하나로 초기화.
        kwargs의 dimension 등은 SentenceTransformer에 전달하지 않음 (API 미지원).
        """
        self._model = None
        self._dimension: Optional[int] = None
        name = model_name or getattr(model, "model_name", None) if model else None
        if model is not None:
            self._model = model
            try:
                self._dimension = getattr(model, "get_sentence_embedding_dimension", lambda: None)()
            except Exception:
                pass
            logger.info("TextEmbedder initialized with provided model")
            return
        name = name or _DEFAULT_MODEL
        try:
            from sentence_transformers import SentenceTransformer

            # 로컬 캐시 우선 로드: HuggingFace에 버전 확인 요청(HEAD)을 보내지 않음.
            # 캐시에 없을 때만 온라인으로 fallback하여 불필요한 503 재시도를 방지.
            try:
                self._model = SentenceTransformer(name, local_files_only=True)
                logger.info(
                    "TextEmbedder model loaded from local cache",
                    extra={"model_name": name},
                )
            except Exception:
                logger.info(
                    "TextEmbedder local cache miss — downloading from HuggingFace",
                    extra={"model_name": name},
                )
                self._model = SentenceTransformer(name)

            self._dimension = getattr(
                self._model,
                "get_sentence_embedding_dimension",
                lambda: None,
            )()
            if self._dimension is None and hasattr(self._model, "dimension"):
                self._dimension = getattr(self._model, "dimension", None)
            logger.info(
                "TextEmbedder model_name load ok",
                extra={"model_name": name, "embedding_dim": self._dimension},
            )
        except Exception as e:
            logger.warning(
                "TextEmbedder model_name load failed: %s",
                e,
                extra={"model_name": name},
            )
            raise

    def embed_text(self, text: str) -> List[float]:
        """단일 텍스트 임베딩. 빈 문자열이면 제로 벡터(차원은 get_dimension 기준)."""
        if not self._model:
            return []
        if not (text or "").strip():
            dim = self.get_dimension()
            return [0.0] * dim if dim else []
        try:
            emb = self._model.encode(text, convert_to_numpy=True)
            return emb.tolist()
        except Exception as e:
            logger.warning("TextEmbedder embed_text error: %s", e)
            return []

    async def embed(self, text: str) -> List[float]:
        """
        비동기 컨텍스트용 임베딩.

        지식 추출 v2(hallucination_checker, extraction_pipeline, semantic_deduplicator 등)가
        ``await embedder.embed(text)`` 형태로 호출함. SentenceTransformer.encode는 동기 블로킹이므로
        이벤트 루프를 막지 않도록 스레드에서 embed_text를 실행한다.

        동기 코드에서는 ``embed_text()``를 직접 사용할 것(``embed()``를 await 없이 호출하면 코루틴만 반환됨).
        """
        return await asyncio.to_thread(self.embed_text, text)

    def get_dimension(self) -> int:
        """임베딩 차원. 모델에서 조회하며, 알 수 없으면 768 반환."""
        if self._dimension is not None:
            return int(self._dimension)
        if self._model and hasattr(self._model, "get_sentence_embedding_dimension"):
            try:
                self._dimension = self._model.get_sentence_embedding_dimension()
                return int(self._dimension)
            except Exception:
                pass
        return 768


def get_text_embedder(
    model_name: Optional[str] = None,
    force_new: bool = False,
) -> TextEmbedder:
    """TextEmbedder 싱글톤. model_name 없으면 기본 모델 사용."""
    global _embedder_instance
    if _embedder_instance is not None and not force_new:
        return _embedder_instance
    _embedder_instance = TextEmbedder(model_name=model_name or _DEFAULT_MODEL)
    return _embedder_instance
