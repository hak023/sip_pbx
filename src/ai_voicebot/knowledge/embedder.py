"""
Text Embedder

텍스트를 벡터 임베딩으로 변환
"""

import os
import ssl
import warnings

# ===== 1단계: 환경변수 먼저 설정 (가장 먼저!) =====
os.environ['CURL_CA_BUNDLE'] = ''
os.environ['REQUESTS_CA_BUNDLE'] = ''
os.environ['SSL_CERT_FILE'] = ''
os.environ['TOKENIZERS_PARALLELISM'] = 'false'
os.environ['PYTHONHTTPSVERIFY'] = '0'  # Python HTTPS 검증 비활성화

# HuggingFace/Transformers 진행 표시줄 및 로그 비활성화
os.environ['HF_HUB_DISABLE_PROGRESS_BARS'] = '1'
os.environ['TRANSFORMERS_VERBOSITY'] = 'error'
os.environ['TRANSFORMERS_NO_ADVISORY_WARNINGS'] = '1'
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'

# ===== 2단계: SSL 기본 컨텍스트 변경 =====
ssl._create_default_https_context = ssl._create_unverified_context

# ===== 3단계: urllib3 경고 비활성화 =====
try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except ImportError:
    pass

# ===== 4단계: requests 세션에도 SSL 검증 비활성화 =====
try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    
    # requests 기본 세션 SSL 검증 비활성화
    original_request = requests.Session.request
    def patched_request(self, *args, **kwargs):
        kwargs.setdefault('verify', False)
        return original_request(self, *args, **kwargs)
    requests.Session.request = patched_request
except ImportError:
    pass

# ===== 5단계: 로깅 설정 =====
import logging
logging.getLogger("sentence_transformers").setLevel(logging.ERROR)
logging.getLogger("transformers").setLevel(logging.ERROR)
logging.getLogger("urllib3").setLevel(logging.ERROR)
logging.getLogger("requests").setLevel(logging.ERROR)

# ===== 이제 라이브러리 import =====
from sentence_transformers import SentenceTransformer
import asyncio
from typing import List, Union
import structlog

logger = structlog.get_logger(__name__)


class TextEmbedder:
    """
    텍스트 임베딩 생성기
    
    Sentence Transformers를 사용하여 텍스트를 벡터로 변환합니다.
    GPU가 있으면 자동으로 사용합니다.
    """
    
    def __init__(
        self,
        model_name: str = "paraphrase-multilingual-mpnet-base-v2",
        dimension: int = 768,
        batch_size: int = 32,
        device: str = None  # 'cuda', 'cpu', or None (auto)
    ):
        """
        Args:
            model_name: Sentence Transformers 모델 이름
            dimension: 임베딩 차원
            batch_size: 배치 크기
            device: 사용할 디바이스 ('cuda', 'cpu', None=auto)
        """
        self.model_name = model_name
        self.dimension = dimension
        self.batch_size = batch_size
        
        # 디바이스 자동 감지
        if device is None:
            import torch
            self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
            if self.device == 'cuda':
                gpu_name = torch.cuda.get_device_name(0)
                gpu_memory = torch.cuda.get_device_properties(0).total_memory / 1024**3
                logger.info("🎮 [GPU] CUDA available! Using GPU acceleration",
                           device=self.device,
                           gpu_name=gpu_name,
                           gpu_memory_gb=f"{gpu_memory:.2f}GB")
            else:
                logger.info("💻 [CPU] CUDA not available, using CPU",
                           device=self.device)
        else:
            self.device = device
            logger.info(f"Device specified: {device}")
        
        # 모델 로드
        logger.info("Loading embedding model", model=model_name, device=self.device)
        
        # HuggingFace Hub SSL 검증 비활성화
        try:
            logger.info("🔧 [DEBUG] Disabling HuggingFace Hub transfer...")
            from huggingface_hub import constants
            constants.HF_HUB_ENABLE_HF_TRANSFER = False
            logger.info("✅ [DEBUG] HuggingFace Hub transfer disabled")
        except Exception as e:
            logger.warning("⚠️ [DEBUG] Failed to disable HF transfer", error=str(e))
        
        # 모델 로드 시작 (SSL 검증 비활성화 적용됨)
        logger.info("🔄 [DEBUG] Starting SentenceTransformer initialization...")
        logger.info("🔄 [DEBUG] Model name: {}, Device: {}, Auth: False".format(model_name, self.device))
        
        import time
        start_time = time.time()
        
        try:
            # 타임아웃 설정 (5분)
            import signal
            
            def timeout_handler(signum, frame):
                raise TimeoutError("Model loading timed out after 5 minutes")
            
            # Windows에서는 signal.SIGALRM이 없으므로 다른 방식 사용
            logger.info("🔄 [DEBUG] Calling SentenceTransformer()...")
            # ✅ use_auth_token deprecated, 제거 (v3에서 삭제 예정)
            self.model = SentenceTransformer(model_name, device=self.device)
            
            elapsed = time.time() - start_time
            logger.info("✅ [DEBUG] SentenceTransformer loaded successfully in {:.2f} seconds".format(elapsed))
            
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error("❌ [DEBUG] Model loading failed after {:.2f} seconds".format(elapsed), 
                        error=str(e), 
                        error_type=type(e).__name__)
            raise
        
        # GPU 정보 출력
        if self.device == 'cuda':
            import torch
            logger.info("✅ [GPU] Model loaded on GPU",
                       model=model_name,
                       device=self.device,
                       cuda_device=torch.cuda.current_device())
        
        # 통계
        self.total_embeddings = 0
        self.total_texts = 0
        
        logger.info("TextEmbedder initialized", 
                   model=model_name,
                   dimension=dimension,
                   device=self.device)
    
    async def embed(self, text: str) -> List[float]:
        """
        단일 텍스트 임베딩
        
        Args:
            text: 임베딩할 텍스트
            
        Returns:
            임베딩 벡터
        """
        try:
            # CPU 바운드 작업이므로 executor에서 실행
            loop = asyncio.get_event_loop()
            embedding = await loop.run_in_executor(
                None,
                lambda: self.model.encode(text, convert_to_numpy=True)
            )
            
            self.total_embeddings += 1
            self.total_texts += len(text)
            
            return embedding.tolist()
            
        except Exception as e:
            logger.error("Embedding failed", text_length=len(text), error=str(e))
            # 오류 시 제로 벡터 반환
            return [0.0] * self.dimension
    
    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        배치 텍스트 임베딩
        
        Args:
            texts: 임베딩할 텍스트 리스트
            
        Returns:
            임베딩 벡터 리스트
        """
        try:
            # 배치 처리
            loop = asyncio.get_event_loop()
            embeddings = await loop.run_in_executor(
                None,
                lambda: self.model.encode(
                    texts, 
                    batch_size=self.batch_size,
                    convert_to_numpy=True
                )
            )
            
            self.total_embeddings += len(texts)
            self.total_texts += sum(len(t) for t in texts)
            
            return [emb.tolist() for emb in embeddings]
            
        except Exception as e:
            logger.error("Batch embedding failed", 
                        batch_size=len(texts), 
                        error=str(e))
            # 오류 시 제로 벡터 리스트 반환
            return [[0.0] * self.dimension for _ in texts]
    
    def embed_sync(self, text: str) -> List[float]:
        """
        동기 임베딩 (필요한 경우)
        
        Args:
            text: 임베딩할 텍스트
            
        Returns:
            임베딩 벡터
        """
        try:
            embedding = self.model.encode(text, convert_to_numpy=True)
            self.total_embeddings += 1
            self.total_texts += len(text)
            return embedding.tolist()
        except Exception as e:
            logger.error("Sync embedding failed", error=str(e))
            return [0.0] * self.dimension
    
    def get_stats(self) -> dict:
        """임베딩 통계 반환"""
        stats = {
            "total_embeddings": self.total_embeddings,
            "total_texts": self.total_texts,
            "model_name": self.model_name,
            "dimension": self.dimension,
            "device": self.device,
            "avg_text_length": (
                self.total_texts / self.total_embeddings 
                if self.total_embeddings > 0 else 0
            ),
        }
        
        # GPU 메모리 정보 추가
        if self.device == 'cuda':
            try:
                import torch
                stats.update({
                    "gpu_name": torch.cuda.get_device_name(0),
                    "gpu_memory_allocated_mb": torch.cuda.memory_allocated(0) / 1024**2,
                    "gpu_memory_reserved_mb": torch.cuda.memory_reserved(0) / 1024**2,
                    "gpu_memory_total_gb": torch.cuda.get_device_properties(0).total_memory / 1024**3,
                })
            except Exception as e:
                logger.error("Failed to get GPU stats", error=str(e))
        
        return stats


class SimpleEmbedder:
    """
    간단한 임베더 (테스트용)
    
    실제 모델 없이 해시 기반 임베딩을 생성합니다.
    """
    
    def __init__(self, dimension: int = 768):
        """
        Args:
            dimension: 임베딩 차원
        """
        self.dimension = dimension
        logger.info("SimpleEmbedder initialized", dimension=dimension)
    
    async def embed(self, text: str) -> List[float]:
        """
        해시 기반 임베딩
        
        Args:
            text: 임베딩할 텍스트
            
        Returns:
            임베딩 벡터
        """
        import hashlib
        
        # 텍스트 해시
        hash_obj = hashlib.sha256(text.encode())
        hash_bytes = hash_obj.digest()
        
        # 해시를 벡터로 변환
        embedding = []
        for i in range(0, min(len(hash_bytes), self.dimension), 2):
            if i + 1 < len(hash_bytes):
                value = (hash_bytes[i] * 256 + hash_bytes[i + 1]) / 65535.0
            else:
                value = hash_bytes[i] / 255.0
            embedding.append(value)
        
        # 차원 맞추기
        while len(embedding) < self.dimension:
            embedding.append(0.0)
        
        return embedding[:self.dimension]
    
    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """배치 임베딩"""
        return [await self.embed(t) for t in texts]
    
    def get_stats(self) -> dict:
        """통계 반환"""
        return {
            "embedder_type": "simple",
            "dimension": self.dimension,
        }

