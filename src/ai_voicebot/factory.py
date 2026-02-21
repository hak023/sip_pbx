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
# ✅ Lazy import: Google Cloud 라이브러리를 필요할 때만 import (3분 타임아웃 방지)
# from .ai_pipeline.stt_client import STTClient
# from .ai_pipeline.tts_client import TTSClient
# from .ai_pipeline.llm_client import LLMClient
from .ai_pipeline.rag_engine import RAGEngine
from .knowledge.embedder import TextEmbedder
from .knowledge.chromadb_client import get_chromadb_client
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
    import time
    
    # AI 보이스봇 비활성화 체크
    if not config.get("enabled", False):
        logger.info("AI Voicebot is disabled")
        return None
    
    try:
        factory_start = time.time()
        logger.info("🔧 [FACTORY] Initializing AI Voicebot components...")
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
        gcp_start = time.time()
        logger.info("🔧 [FACTORY] Setting up Google Cloud credentials...")
        
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
        
        gcp_elapsed = time.time() - gcp_start
        logger.info(f"🔧 [FACTORY] Credentials setup: {gcp_elapsed:.3f}s")
        
        # 4. STT Client (✅ Lazy import)
        stt_start = time.time()
        logger.info("🔧 [FACTORY] Importing STT Client...")
        from .ai_pipeline.stt_client import STTClient
        stt_import_elapsed = time.time() - stt_start
        logger.info(f"🔧 [FACTORY] STT import: {stt_import_elapsed:.3f}s")
        
        stt_config = google_config.get("stt", {})
        stt = STTClient(stt_config)
        stt_elapsed = time.time() - stt_start
        logger.info(f"STT Client initialized ({stt_elapsed:.3f}s)")
        
        # 5. TTS Client (✅ Lazy import)
        tts_start = time.time()
        logger.info("🔧 [FACTORY] Importing TTS Client...")
        from .ai_pipeline.tts_client import TTSClient
        tts_import_elapsed = time.time() - tts_start
        logger.info(f"🔧 [FACTORY] TTS import: {tts_import_elapsed:.3f}s")
        
        tts_config = google_config.get("tts", {})
        tts = TTSClient(tts_config)
        tts_elapsed = time.time() - tts_start
        logger.info(f"TTS Client initialized ({tts_elapsed:.3f}s)")
        
        # 6. LLM Client (Gemini) (✅ Lazy import)
        llm_start = time.time()
        logger.info("🔧 [FACTORY] Importing LLM Client...")
        from .ai_pipeline.llm_client import LLMClient
        llm_import_elapsed = time.time() - llm_start
        logger.info(f"🔧 [FACTORY] LLM import: {llm_import_elapsed:.3f}s")
        
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
        llm_elapsed = time.time() - llm_start
        logger.info(f"LLM Client initialized ({llm_elapsed:.3f}s)")
        
        # 7. Text Embedder
        embedding_config = config.get("embedding", {})
        embedder = TextEmbedder(
            model_name=embedding_config.get("model", "paraphrase-multilingual-mpnet-base-v2"),
            dimension=embedding_config.get("dimension", 768),
            batch_size=embedding_config.get("batch_size", 32)
        )
        logger.info("Text Embedder initialized")
        
        # 8. Vector DB (ChromaDB)
        logger.info("🔄 [FACTORY] Step 8/12: Initializing Vector DB...")
        vector_db_config = config.get("vector_db", {})
        vector_db_provider = vector_db_config.get("provider", "chromadb")
        
        if vector_db_provider == "chromadb":
            chromadb_config = vector_db_config.get("chromadb", {})
            persist_dir = chromadb_config.get("persist_directory", "./data/chromadb")
            
            logger.info("🔄 [ChromaDB] Using single ChromaDB client (get_chromadb_client)...",
                       persist_directory=persist_dir)
            
            vector_db = get_chromadb_client(
                persist_directory=persist_dir,
                collection_name="knowledge_base",
                client_mode="local",
            )
            
            logger.info("🔄 [ChromaDB] Calling initialize()...")
            await vector_db.initialize()
            
            logger.info("✅ [FACTORY] ChromaDB initialized successfully")
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
            min_confidence=knowledge_config.get("min_confidence", 0.7),
            chunk_size=knowledge_config.get("chunk_size", 500),
            chunk_overlap=knowledge_config.get("chunk_overlap", 50),
            min_text_length=knowledge_config.get("min_text_length", 10),
            pii_review_queue_enabled=knowledge_config.get("pii_review_queue_enabled", False),
            extraction_pending_file=knowledge_config.get("extraction_pending_file") or "data/extraction_pending_review.jsonl",
        )
        logger.info("Knowledge Extractor initialized")
        
        # 11.5. Knowledge Service (HITL용 + §7 검토 대기열)
        from ..services.knowledge_service import KnowledgeService, set_knowledge_service
        knowledge_service = KnowledgeService(
            vector_db=vector_db,
            embedder=embedder,
            extraction_pending_file=knowledge_config.get("extraction_pending_file") or "data/extraction_pending_review.jsonl",
        )
        set_knowledge_service(knowledge_service)
        logger.info("Knowledge Service initialized and set globally")
        
        # 12. AI Orchestrator
        orch_start = time.time()
        logger.info("🔧 [FACTORY] Creating AI Orchestrator...")
        
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
        orch_elapsed = time.time() - orch_start
        logger.info(f"🔧 [FACTORY] Orchestrator created: {orch_elapsed:.3f}s")
        
        factory_total = time.time() - factory_start
        logger.info(f"🔧 [FACTORY] ⭐ TOTAL FACTORY TIME: {factory_total:.2f}s")
        
        logger.info("AI Orchestrator initialized successfully")
        logger.info("✅ AI Voicebot initialization completed")
        return orchestrator
        
    except Exception as e:
        logger.error("AI Voicebot initialization failed",
                    error=str(e),
                    exc_info=True)
        return None


async def create_pipecat_pipeline_builder(config: Dict[str, Any]) -> Optional[Any]:
    """
    Pipecat Pipeline Builder 생성 (Phase 1).
    
    기존 create_ai_orchestrator와 병행하여 사용.
    config에 'pipeline_engine: pipecat' 설정 시 Pipecat 파이프라인 사용.
    
    Args:
        config: AI 보이스봇 설정
    
    Returns:
        VoiceAIPipelineBuilder 인스턴스 또는 None
    """
    if not config.get("enabled", False):
        return None
    
    pipeline_engine = config.get("pipeline_engine", "legacy")
    if pipeline_engine != "pipecat":
        logger.info("pipeline_engine_not_pipecat",
                    engine=pipeline_engine,
                    message="Using legacy orchestrator")
        return None
    
    try:
        from src.ai_voicebot.pipecat.pipeline_builder import VoiceAIPipelineBuilder
        
        builder = VoiceAIPipelineBuilder(config)
        
        # ✅ LangGraph 그래프를 서버 시작 시 미리 컴파일 (통화 중 7초 지연 방지)
        import time
        graph_start = time.time()
        try:
            from src.ai_voicebot.langgraph.agent import build_conversation_graph
            graph = build_conversation_graph()
            graph_elapsed = time.time() - graph_start
            if graph:
                logger.info("✅ [Pipecat] LangGraph pre-compiled",
                           elapsed=f"{graph_elapsed:.3f}s")
            else:
                logger.warning("⚠️ [Pipecat] LangGraph pre-compilation failed",
                             elapsed=f"{graph_elapsed:.3f}s")
        except Exception as e:
            logger.warning("langgraph_pre_compile_failed", error=str(e))
        
        logger.info("✅ Pipecat Pipeline Builder created successfully")
        return builder
        
    except ImportError as e:
        logger.error("pipecat_import_error",
                    error=str(e),
                    message="pipecat-ai 패키지가 설치되지 않았습니다. "
                            "pip install pipecat-ai[google,silero] 를 실행하세요.")
        return None
    except Exception as e:
        logger.error("pipecat_builder_creation_error",
                    error=str(e), exc_info=True)
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

