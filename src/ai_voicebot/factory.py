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

# 🔥 Google STT/TTS Service Singleton (통화마다 재생성 방지 → 19초 지연 제거)
_global_google_stt_service = None
_global_google_tts_service = None

# 🔥 LLM Client Singleton (API 엔드포인트에서 재사용)
_global_llm_client = None

# 🔥 AI Orchestrator Singleton (rag/embedder/vector_db 재사용 — QA 테스트 엔드포인트 등)
_global_ai_orchestrator = None


def _build_google_stt_service(config: Dict[str, Any] = None):
    """GoogleSTTService 인스턴스 생성 (Singleton·파이프라인 전용 공통)."""
    from pipecat.services.google.stt import GoogleSTTService
    from pipecat.transcriptions.language import Language

    # Pipecat 공식: ko-KR은 params.InputParams(languages=[Language.KO_KR])로 설정.
    _cfg = config or {}
    _params = GoogleSTTService.InputParams(
        languages=[Language.KO_KR],
        model=_cfg.get("model", "telephony"),
        enable_automatic_punctuation=_cfg.get("enable_automatic_punctuation", True),
        enable_interim_results=_cfg.get("enable_interim_results", True),
    )
    _kwargs: Dict[str, Any] = {
        "sample_rate": _cfg.get("sample_rate", 16000),
        "params": _params,
    }
    if _cfg.get("credentials_path"):
        _kwargs["credentials_path"] = _cfg["credentials_path"]
    if _cfg.get("credentials") is not None:
        _kwargs["credentials"] = _cfg["credentials"]
    if _cfg.get("location"):
        _kwargs["location"] = _cfg["location"]
    return GoogleSTTService(**_kwargs)


async def create_google_stt_service_per_pipeline(config: Dict[str, Any] = None):
    """
    Pipecat 파이프라인(통화)마다 전용 Google STT.

    Singleton STT를 두 파이프라인이 동시에 쓰면 각각 start(StartFrame)에서
    _connect()가 내부 _streaming_task / _request_queue를 덮어써 스트림이 꼬이고,
    파이프라인 순서상 STT 앞단에서 막히면 RAG에 StartFrame이 늦게 가거나
    인사·TTS가 전혀 나가지 않을 수 있음 (ai_enabled_calls > 1 재현).
    """
    try:
        svc = _build_google_stt_service(config)
        logger.info(
            "google_stt_service_per_pipeline_created",
            languages="ko-KR (Language.KO_KR)",
            note="통화별 STT — 동시 Pipecat 호 Singleton 공유 방지",
        )
        return svc
    except Exception as e:
        logger.error("google_stt_per_pipeline_creation_failed", error=str(e), exc_info=True)
        raise


async def get_or_create_google_stt_service(config: Dict[str, Any] = None):
    """
    Google STT Service Singleton (워밍/레거시·테스트용).

    Pipecat 다중 동시 통화는 create_google_stt_service_per_pipeline 사용.
    """
    global _global_google_stt_service
    if _global_google_stt_service is None:
        try:
            _global_google_stt_service = _build_google_stt_service(config)
            logger.info("✅ [Singleton] Global Google STT Service created",
                       languages="ko-KR (Language.KO_KR)")
        except Exception as e:
            logger.error("google_stt_singleton_creation_failed", error=str(e), exc_info=True)
            raise  # 에러 전파
    return _global_google_stt_service


def _is_gemini_tts_voice(voice_name: str) -> bool:
    """voice_name이 Gemini TTS 보이스인지 판별.

    Gemini TTS 보이스는 'ko-KR-' 등 언어 접두사 없이 단순 이름(Kore, Aoede, Charon …)으로 지정.
    Chirp 3 HD는 'ko-KR-Chirp3-HD-Kore' 형태.
    config.yaml의 gemini_tts.model 키가 있으면 명시적 Gemini 경로.
    """
    if not voice_name:
        return False
    # 언어 코드 접두사(예: ko-KR-, en-US-)가 없으면 Gemini 보이스로 간주
    return "-" not in voice_name


def _build_google_tts_service(config: Dict[str, Any] = None, call_id: str = ""):
    """TTS 서비스 인스턴스 생성 (Singleton·파이프라인 전용 공통).

    voice_name 또는 gemini_tts.model 설정에 따라 자동으로 Gemini TTS / Chirp 3 HD를 선택한다.

    Gemini TTS 선택 조건 (OR):
      - config['gemini_tts']['model'] 키가 존재
      - voice_name 이 단순 이름 (예: 'Kore', 'Aoede') — 언어 접두사 없음

    그 외(기본): Chirp 3 HD (DebugGoogleTTSService)

    Args:
        config: TTS 설정 dict (sample_rate, voice_name, gemini_tts 등)
        call_id: 로깅용 call_id (선택)
    """
    from src.ai_voicebot.pipecat.services.debug_google_tts import (
        DebugGoogleTTSService,
        DebugGeminiTTSService,
    )

    _tts_config = dict(config or {
        "sample_rate": 16000,
        "voice_name": "ko-KR-Chirp3-HD-Kore",
        "language_code": "ko-KR",
    })

    # aggregate_sentences=False: 문장 자동 분할 비활성화 (RAG 응답 전체를 1회 전송)
    _tts_config["aggregate_sentences"] = False

    # Gemini TTS 설정 블록 (config.yaml의 tts.gemini_tts 하위 키)
    gemini_cfg = _tts_config.pop("gemini_tts", None) or {}
    gemini_model = gemini_cfg.get("model", "")
    gemini_prompt = gemini_cfg.get("style_prompt", "")

    voice_name = _tts_config.get("voice_name", "")
    use_gemini = bool(gemini_model) or _is_gemini_tts_voice(voice_name)

    if use_gemini:
        # Gemini TTS: GeminiTTSService는 voice_id / model 파라미터를 사용
        # DebugGeminiTTSService(GeminiTTSService) 생성자 시그니처:
        #   voice_id, model, sample_rate, params(language, prompt), ...
        effective_model = gemini_model or "gemini-2.5-flash-tts"
        effective_voice = voice_name or "Kore"
        # language_code 처리: Gemini는 'ko-KR' 형식 사용
        lang_code = _tts_config.get("language_code", "ko")
        if len(lang_code) == 2:
            lang_code = f"{lang_code}-KR" if lang_code == "ko" else f"{lang_code}-US"

        from pipecat.services.google.tts import GeminiTTSService
        from pipecat.transcriptions.language import Language

        # speaking_rate는 Gemini TTS에서 streaming_audio_config에 직접 지원 안 함(2026-04 기준)
        # → AudioConfig 레벨 파라미터로 전달되지 않아 무시됨, 로그로 안내
        speaking_rate = _tts_config.get("speaking_rate")
        if speaking_rate and speaking_rate != 1.0:
            logger.info(
                "gemini_tts_speaking_rate_not_supported",
                speaking_rate=speaking_rate,
                note="Gemini TTS Streaming API는 speaking_rate 미지원 — style_prompt로 속도 제어 가능",
            )

        # Gemini TTS에 불필요한 키 제거 후 생성
        gemini_kwargs = {
            "call_id": call_id,
            "model": effective_model,
            "voice_id": effective_voice,
            "sample_rate": _tts_config.get("sample_rate", 24000),
        }
        if gemini_prompt:
            gemini_kwargs["params"] = GeminiTTSService.InputParams(
                language=Language.KO_KR,
                prompt=gemini_prompt,
            )
        else:
            gemini_kwargs["params"] = GeminiTTSService.InputParams(language=Language.KO_KR)

        logger.info(
            "gemini_tts_service_created",
            model=effective_model,
            voice_id=effective_voice,
            sample_rate=gemini_kwargs["sample_rate"],
            style_prompt=gemini_prompt or "(없음)",
            call_id=call_id or "",
            note="Gemini TTS 선택 — 24kHz 출력, RTPPacketBuilder에서 8kHz 리샘플링",
        )
        return DebugGeminiTTSService(**gemini_kwargs)

    # Chirp 3 HD (기본 경로)
    # DebugGoogleTTSService(GoogleTTSService) 생성자: voice_id, sample_rate, params(language, speaking_rate)
    from pipecat.services.google.tts import GoogleTTSService
    from pipecat.transcriptions.language import Language

    speaking_rate = _tts_config.get("speaking_rate")
    lang_code = _tts_config.get("language_code", "ko-KR")

    chirp_kwargs = {
        "call_id": call_id,
        "voice_id": voice_name or "ko-KR-Chirp3-HD-Kore",
        "sample_rate": _tts_config.get("sample_rate", 16000),
        "params": GoogleTTSService.InputParams(
            language=Language.KO_KR,
            speaking_rate=float(speaking_rate) if speaking_rate is not None else None,
        ),
        "aggregate_sentences": False,
    }

    logger.info(
        "chirp3hd_tts_service_created",
        voice_id=chirp_kwargs["voice_id"],
        sample_rate=chirp_kwargs["sample_rate"],
        speaking_rate=speaking_rate,
        call_id=call_id or "",
        note="Chirp 3 HD TTS 선택 — 스트리밍 API, aggregate_sentences=False",
    )
    return DebugGoogleTTSService(**chirp_kwargs)


async def create_google_tts_service_per_pipeline(config: Dict[str, Any] = None, call_id: str = ""):
    """
    Pipecat 파이프라인(통화)마다 전용 Google TTS.

    Singleton TTS를 여러 파이프라인이 공유하거나, 이전 파이프라인 취소 직후 동일 인스턴스를
    재사용할 때 내부 태스크/큐가 꼬여 합성·PCM이 멈출 수 있음 (RTP_NO_TTS_CALL 분석).
    STT와 동일하게 통화별 인스턴스로 분리한다.
    
    Args:
        config: TTS 설정
        call_id: 로깅/디버깅용 call_id
    """
    try:
        svc = _build_google_tts_service(config, call_id=call_id)
        _cfg = config or {}
        logger.info(
            "google_tts_service_per_pipeline_created",
            call_id=call_id,
            voice_model=_cfg.get("voice_name", "ko-KR-Standard-A"),
            note="통화별 TTS — 동시 Pipecat 호·파이프라인 취소 후 Singleton 잔류 방지",
        )
        return svc
    except Exception as e:
        logger.error("google_tts_per_pipeline_creation_failed", error=str(e), exc_info=True)
        raise


async def get_or_create_google_tts_service(config: Dict[str, Any] = None):
    """
    Google TTS Service Singleton.
    서버 시작 시 한 번만 생성하여 통화마다 19초 지연 방지.

    Pipecat 다중·연속 통화는 create_google_tts_service_per_pipeline 사용.
    """
    global _global_google_tts_service
    if _global_google_tts_service is None:
        try:
            _global_google_tts_service = _build_google_tts_service(config)
            _tts_config = config or {
                "sample_rate": 16000,
                "voice_name": "ko-KR-Standard-A",
                "language_code": "ko-KR",
            }
            logger.info("✅ [Singleton] Global Google TTS Service created",
                       voice_model=_tts_config.get("voice_name"))
        except Exception as e:
            logger.error("google_tts_singleton_creation_failed", error=str(e), exc_info=True)
            raise  # 에러 전파
    return _global_google_tts_service


async def create_ai_orchestrator(config: Dict[str, Any]) -> Optional[AIOrchestrator]:
    """
    AI Orchestrator 및 모든 하위 컴포넌트 생성 (Legacy 경로).

    config.pipeline_engine != "pipecat" (예: "legacy") 일 때만 호출부에서 사용합니다.
    기본값은 pipeline_engine="pipecat" 이므로, 실제 AI 응대는 create_pipecat_pipeline_builder
    및 PipelineBuilder.build_and_run 에서 수행됩니다.

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
                mode=vad_config.get("aggressiveness", 2),  # 3→2: 음성 탐지 민감도 향상 (STT 개선)
                sample_rate=16000,
                frame_duration_ms=vad_config.get("frame_duration_ms", 30),
                trigger_threshold=0.5,
                speech_frame_count=3
            )
            logger.info("VAD Detector initialized (WebRTC)", mode=vad_config.get("aggressiveness", 2))
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
        
        _gemini_raw = google_config.get("gemini") or {}
        gemini_config = dict(_gemini_raw) if isinstance(_gemini_raw, dict) else {}
        # 파일 기반 키는 사용하지 않음 — 환경 변수만 (링백·지식 추출과 동일)
        gemini_config.pop("api_key", None)

        from src.common.gemini_api_key import resolve_gemini_api_key

        api_key = resolve_gemini_api_key()

        if not api_key:
            logger.error("Gemini API key not found")
            logger.info("Set GEMINI_API_KEY or GOOGLE_API_KEY in the environment (not in config.yaml)")
            return None

        masked_key = f"{api_key[:10]}...{api_key[-4:]}" if len(api_key) > 14 else "***"
        logger.debug("gemini_api_key_loaded", source="env", key=masked_key)
        
        llm = LLMClient(gemini_config, api_key)
        llm_elapsed = time.time() - llm_start
        logger.info(f"LLM Client initialized ({llm_elapsed:.3f}s)")
        
        # ✅ LLM Singleton 저장 (API 엔드포인트에서 재사용)
        global _global_llm_client
        _global_llm_client = llm
        
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
            from .knowledge.chromadb_client import get_chroma_persist_path, get_vector_db
            persist_dir = get_chroma_persist_path()
            logger.info("🔄 [ChromaDB] Using single ChromaDB client (get_chromadb_client)...",
                       persist_directory=persist_dir)
            vector_db_client = get_chromadb_client()
            await vector_db_client.initialize()
            vector_db = get_vector_db()
            if not vector_db:
                logger.error("ChromaDB initialize() completed but get_vector_db() is None")
                return None
            logger.info("✅ [FACTORY] ChromaDB initialized successfully")
        else:
            logger.error("Unsupported Vector DB provider", provider=vector_db_provider)
            return None
        
        # 9. RAG Engine
        rag_config = config.get("rag", {})
        _dt_allow = rag_config.get("doc_type_allowlist")
        if isinstance(_dt_allow, str):
            _dt_allow = [x.strip() for x in _dt_allow.split(",") if x.strip()]
        elif isinstance(_dt_allow, (list, tuple)):
            _dt_allow = [str(x).strip() for x in _dt_allow if str(x).strip()]
        else:
            _dt_allow = None
        rag = RAGEngine(
            vector_db=vector_db,
            embedder=embedder,
            top_k=rag_config.get("top_k", 8),
            similarity_threshold=rag_config.get("similarity_threshold", 0.35),
            reranking_enabled=rag_config.get("reranking_enabled", False),
            doc_type_allowlist=_dt_allow,
        )
        logger.info("RAG Engine initialized")
        
        # 9-1. Persona Service (Chitchat vs Question 분류용)
        try:
            from .knowledge.persona_service import initialize_persona_service
            from .knowledge.chromadb_client import get_raw_chroma_client
            # PersonaService는 실제 ChromaDB 클라이언트가 필요함
            chroma_raw_client = get_raw_chroma_client()
            if chroma_raw_client is None:
                logger.warning("persona_service_init_skipped",
                              note="ChromaDB 클라이언트가 초기화되지 않음 — Persona 없이 계속")
            else:
                persona_service = await initialize_persona_service(chroma_raw_client, embedder)
                logger.info("✅ [FACTORY] PersonaService initialized (Chitchat classification)")
        except Exception as e:
            logger.warning("persona_service_init_failed", error=str(e),
                          note="Persona 없이 계속 — 기본 intent 분류 사용")
        
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
        
        # 11.5. Knowledge Service (API 엔드포인트용)
        from ..services.knowledge_service import initialize_knowledge_service
        knowledge_service = await initialize_knowledge_service(
            vector_db=vector_db,
            embedder=embedder,
            extraction_pending_file=knowledge_config.get("extraction_pending_file") or "data/extraction_pending_review.jsonl",
        )
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

        # ✅ Orchestrator Singleton 저장 (QA 테스트 엔드포인트 등에서 rag/embedder/vector_db 재사용)
        global _global_ai_orchestrator
        _global_ai_orchestrator = orchestrator

        factory_total = time.time() - factory_start
        logger.info(f"🔧 [FACTORY] ⭐ TOTAL FACTORY TIME: {factory_total:.2f}s")
        
        logger.info("AI Orchestrator initialized successfully")
        logger.info("✅ AI Voicebot initialization completed")
        return orchestrator
        
    except Exception as e:
        err_msg = str(e)
        logger.error("AI Voicebot initialization failed",
                    error=err_msg,
                    exc_info=True)
        if "collections.topic" in err_msg:
            logger.warning(
                "chromadb_schema_fix_hint",
                hint="pip install 'chromadb>=0.5.0' 또는 data/chroma 폴더 삭제 후 재시작. docs/reports/CHROMA_COLLECTIONS_TOPIC_ERROR.md",
            )
        return None


async def ensure_knowledge_service_singleton_for_hitl(config: Dict[str, Any]) -> bool:
    """
    Pipecat-only 기동 시에도 HITL→Chroma가 RAG와 동일 Chroma·임베더를 쓰도록 싱글톤을 설정한다.
    create_ai_orchestrator를 거치지 않으면 get_knowledge_service()가 기본 생성자만 타 임베딩 불일치가 날 수 있음.
    """
    if not config.get("enabled", False):
        return False
    try:
        from ..services.knowledge_service import KnowledgeService, set_knowledge_service
        from .knowledge.embedder import TextEmbedder
        from .knowledge.chromadb_client import get_chromadb_client, get_vector_db

        embedding_config = config.get("embedding", {})
        embedder = TextEmbedder(
            model_name=embedding_config.get("model", "paraphrase-multilingual-mpnet-base-v2"),
            dimension=embedding_config.get("dimension", 768),
            batch_size=embedding_config.get("batch_size", 32),
        )
        vector_db_config = config.get("vector_db", {})
        if vector_db_config.get("provider", "chromadb") != "chromadb":
            logger.error(
                "ensure_knowledge_service_singleton_unsupported_provider",
                provider=vector_db_config.get("provider"),
            )
            return False
        vector_db_client = get_chromadb_client()
        await vector_db_client.initialize()
        vector_db = get_vector_db()
        if not vector_db:
            logger.error("ensure_knowledge_service_singleton_no_vector_db")
            return False
        knowledge_config = config.get("knowledge_extractor", {})
        ks = KnowledgeService(
            vector_db=vector_db,
            embedder=embedder,
            extraction_pending_file=knowledge_config.get("extraction_pending_file")
            or "data/extraction_pending_review.jsonl",
        )
        set_knowledge_service(ks)
        logger.info(
            "knowledge_service_singleton_ready_for_hitl",
            note="Pipecat_경로_RAG와_동일_chroma_embedder",
        )
        return True
    except Exception as e:
        logger.warning("ensure_knowledge_service_singleton_failed", error=str(e), exc_info=True)
        return False


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
    
    pipeline_engine = config.get("pipeline_engine", "pipecat")
    if pipeline_engine != "pipecat":
        logger.info("pipeline_engine_not_pipecat",
                    engine=pipeline_engine,
                    message="Using legacy orchestrator")
        return None
    
    try:
        await ensure_knowledge_service_singleton_for_hitl(config)
        from src.ai_voicebot.pipecat.pipeline_builder import VoiceAIPipelineBuilder
        from src.websocket import manager as ws_manager
        
        builder = VoiceAIPipelineBuilder(on_call_ended=ws_manager.emit_call_ended)
        
        # ✅ LangGraph 그래프를 서버 시작 시 미리 컴파일 (통화 중 7초 지연 방지)
        import time
        graph_start = time.time()
        try:
            from src.ai_voicebot.langgraph.agent import get_or_build_compiled_graph_async

            graph = await get_or_build_compiled_graph_async()
            graph_elapsed = time.time() - graph_start
            if graph:
                logger.info(
                    "[Pipecat] LangGraph pre-compiled",
                    elapsed=f"{graph_elapsed:.3f}s",
                )
            else:
                logger.warning(
                    "[Pipecat] LangGraph pre-compilation failed",
                    elapsed=f"{graph_elapsed:.3f}s",
                )
        except Exception as e:
            logger.warning("langgraph_pre_compile_failed", error=str(e))
        
        logger.info("Pipecat Pipeline Builder created successfully")
        return builder
        
    except ImportError as e:
        logger.error(
            "pipecat_import_error",
            error=str(e),
            message=(
                "Pipecat 모듈 import 실패(버전 불일치 가능). "
                "예: StartInterruptionFrame 제거 → src/ai_voicebot/pipecat/interruption_compat.py 참고. "
                "또는 pip install -U 'pipecat-ai[google,silero]' 로 버전 맞춤."
            ),
        )
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


def get_llm_client():
    """
    전역 LLM Client 반환 (API 엔드포인트용)
    
    Returns:
        LLMClient 인스턴스 또는 None
    """
    global _global_llm_client
    return _global_llm_client


def get_ai_orchestrator():
    """
    전역 AIOrchestrator 반환(`create_ai_orchestrator()` 성공 후 채워짐).

    `.rag`(RAGEngine, `.embedder`/`.vector_db` 포함)·`.llm`·`.org_manager` 등을 그대로
    재사용하려는 코드(예: 셀프서비스 QA 테스트 엔드포인트)에서 사용한다.

    Returns:
        AIOrchestrator 인스턴스 또는 None(아직 초기화 전)
    """
    global _global_ai_orchestrator
    return _global_ai_orchestrator

