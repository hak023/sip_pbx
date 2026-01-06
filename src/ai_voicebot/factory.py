"""
AI Voicebot Factory

AI 보이스봇 시스템의 모든 컴포넌트를 초기화하는 팩토리
"""

import os
from typing import Optional, Dict, Any
import structlog

from .orchestrator import AIOrchestrator
from .audio_buffer import AudioBuffer
from .vad_detector import VADDetector
from .ai_pipeline.stt_client import STTClient
from .ai_pipeline.tts_client import TTSClient
from .ai_pipeline.llm_client import LLMClient
from .ai_pipeline.rag_engine import RAGEngine
from .knowledge.embedder import TextEmbedder
from .knowledge.chromadb_client import ChromaDBClient
from .knowledge.knowledge_extractor import KnowledgeExtractor
from .recording.recorder import CallRecorder

logger = structlog.get_logger(__name__)


async def create_ai_orchestrator(config: Dict[str, Any]) -> Optional[AIOrchestrator]:
    """
    AI Orchestrator 및 모든 하위 컴포넌트 생성
    
    Args:
        config: AI 보이스봇 설정
        
    Returns:
        초기화된 AIOrchestrator 또는 None (비활성화 시)
    """
    # AI 보이스봇 비활성화 체크
    if not config.get("enabled", False):
        logger.info("AI Voicebot is disabled")
        return None
    
    try:
        logger.info("Initializing AI Voicebot components...")
        
        # 1. Audio Buffer
        audio_buffer_config = config.get("audio_buffer", {})
        audio_buffer = AudioBuffer(
            jitter_buffer_ms=audio_buffer_config.get("jitter_buffer_ms", 60),
            max_buffer_size=audio_buffer_config.get("max_buffer_size", 100),
            target_sample_rate=16000
        )
        logger.info("Audio Buffer initialized")
        
        # 2. VAD Detector
        vad_config = config.get("vad", {})
        try:
            vad = VADDetector(
                mode=vad_config.get("aggressiveness", 3),
                sample_rate=16000,
                frame_duration_ms=vad_config.get("frame_duration_ms", 30),
                trigger_threshold=0.5,
                speech_frame_count=3
            )
            logger.info("VAD Detector initialized (WebRTC)")
        except Exception as e:
            logger.warning("WebRTC VAD initialization failed, using SimpleVAD",
                         error=str(e))
            from .vad_detector import SimpleVAD
            vad = SimpleVAD(sample_rate=16000)
        
        # 3. Google Cloud 설정 확인
        google_config = config.get("google_cloud", {})
        credentials_path = google_config.get("credentials_path")
        project_id = google_config.get("project_id")
        
        # 환경 변수 설정
        if credentials_path and os.path.exists(credentials_path):
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path
            logger.info("Google Cloud credentials set", path=credentials_path)
        else:
            logger.warning("Google Cloud credentials not found",
                         path=credentials_path)
        
        # 4. STT Client
        stt_config = google_config.get("stt", {})
        stt = STTClient(stt_config)
        logger.info("STT Client initialized")
        
        # 5. TTS Client
        tts_config = google_config.get("tts", {})
        tts = TTSClient(tts_config)
        logger.info("TTS Client initialized")
        
        # 6. LLM Client (Gemini)
        gemini_config = google_config.get("gemini", {})
        
        # Gemini API 키 확인 (우선순위: config.yaml > 환경 변수)
        api_key = (
            gemini_config.get("api_key") or  # 1순위: config.yaml
            os.getenv("GEMINI_API_KEY") or    # 2순위: GEMINI_API_KEY 환경 변수
            os.getenv("GOOGLE_API_KEY")       # 3순위: GOOGLE_API_KEY 환경 변수
        )
        
        if not api_key:
            logger.error("Gemini API key not found")
            logger.info("Please set api_key in config.yaml or GEMINI_API_KEY environment variable")
            return None
        
        # API 키 일부 마스킹하여 로깅
        masked_key = f"{api_key[:10]}...{api_key[-4:]}" if len(api_key) > 14 else "***"
        logger.info("Gemini API key loaded", source="config" if gemini_config.get("api_key") else "env", key=masked_key)
        
        llm = LLMClient(gemini_config, api_key)
        logger.info("LLM Client initialized")
        
        # 7. Text Embedder
        embedding_config = config.get("embedding", {})
        embedder = TextEmbedder(
            model_name=embedding_config.get("model", "paraphrase-multilingual-mpnet-base-v2"),
            dimension=embedding_config.get("dimension", 768),
            batch_size=embedding_config.get("batch_size", 32)
        )
        logger.info("Text Embedder initialized")
        
        # 8. Vector DB (ChromaDB)
        vector_db_config = config.get("vector_db", {})
        vector_db_provider = vector_db_config.get("provider", "chromadb")
        
        if vector_db_provider == "chromadb":
            chromadb_config = vector_db_config.get("chromadb", {})
            vector_db = ChromaDBClient(
                collection_name="knowledge_base",
                persist_directory=chromadb_config.get("persist_directory", "./data/chromadb"),
                client_mode="local"
            )
            await vector_db.initialize()
            logger.info("ChromaDB initialized")
        else:
            logger.error("Unsupported Vector DB provider", provider=vector_db_provider)
            return None
        
        # 9. RAG Engine
        rag_config = config.get("rag", {})
        rag = RAGEngine(
            vector_db=vector_db,
            embedder=embedder,
            top_k=rag_config.get("top_k", 3),
            similarity_threshold=rag_config.get("similarity_threshold", 0.7),
            reranking_enabled=rag_config.get("reranking_enabled", False)
        )
        logger.info("RAG Engine initialized")
        
        # 10. Call Recorder
        recording_config = config.get("recording", {})
        recorder = CallRecorder(
            output_dir=recording_config.get("output_dir", "./recordings"),
            sample_rate=16000,
            channels=1,
            sample_width=2
        )
        logger.info("Call Recorder initialized")
        
        # 11. Knowledge Extractor
        knowledge_config = config.get("knowledge_extractor", {})
        extractor = KnowledgeExtractor(
            llm_client=llm,
            embedder=embedder,
            vector_db=vector_db,
            min_confidence=0.7,
            chunk_size=500,
            chunk_overlap=50,
            min_text_length=knowledge_config.get("min_text_length", 50)
        )
        logger.info("Knowledge Extractor initialized")
        
        # 12. AI Orchestrator
        orchestrator = AIOrchestrator(config)
        await orchestrator.initialize(
            audio_buffer=audio_buffer,
            vad=vad,
            stt=stt,
            tts=tts,
            llm=llm,
            rag=rag,
            recorder=recorder,
            extractor=extractor
        )
        logger.info("AI Orchestrator initialized successfully")
        
        logger.info("✅ AI Voicebot initialization completed")
        return orchestrator
        
    except Exception as e:
        logger.error("AI Voicebot initialization failed",
                    error=str(e),
                    exc_info=True)
        return None


def get_ai_status(orchestrator: Optional[AIOrchestrator]) -> Dict[str, Any]:
    """
    AI 보이스봇 상태 반환
    
    Args:
        orchestrator: AI Orchestrator
        
    Returns:
        상태 딕셔너리
    """
    if not orchestrator:
        return {
            "enabled": False,
            "status": "disabled"
        }
    
    return {
        "enabled": True,
        "status": "ready",
        "stats": orchestrator.get_stats()
    }

