"""SIP Endpoint 구현

Python 기반 SIP B2BUA 서버
"""

import signal
import sys
import asyncio
import random
import re
from typing import Optional, Dict, Tuple

from src.common.logger import get_async_logger
from src.common.exceptions import SIPEndpointError, SIPTransportError
from src.config.models import Config
from src.sip_core.call_manager import CallManager
from src.media.session_manager import MediaSessionManager
from src.media.media_session import MediaMode
from src.media.port_pool import PortPoolManager
from src.media.sdp_parser import SDPParser, SDPManipulator
from src.media.rtp_relay import RTPRelayWorker, RTPEndpoint
from src.repositories.call_state_repository import CallStateRepository
from src.sip_core.session_timer import SessionTimer
from src.sip_core.transaction_timer import TransactionTimer
from src.events.cdr import CDR, CDRWriter, TerminationReason
from datetime import datetime

logger = get_async_logger(__name__)

class SIPEndpoint:
    """Mock SIP Endpoint (개발/테스트용)
    
    실제 UDP 소켓을 열고 기본적인 SIP 메시지를 수신합니다.
    완전한 B2BUA 기능 포함 (시그널링 + 미디어 릴레이)
    """
    
    def __init__(self, config: Config):
        """초기화
        
        Args:
            config: 설정 객체
        """
        self.config = config
        self._running = False
        self._socket = None
        self._listen_task = None
        self._sip_log_file = None
        
        # 등록된 사용자 저장소: {username: {'ip', 'port', 'contact', 'from'}}
        self._registered_users: Dict[str, Dict] = {}
        
        # 활성 통화 저장소: {call_id: {'caller_addr', 'callee_addr', 'caller_tag', 'callee_tag', ...}}
        self._active_calls: Dict[str, Dict] = {}
        
        # B2BUA Call Mapping: {original_call_id: new_call_id}
        self._call_mapping: Dict[str, str] = {}
        
        # B2BUA IP 캐싱 (SDP c= 라인용)
        self._cached_b2bua_ip = None
        
        # Call Manager 및 Media Session Manager 초기화
        self._port_pool = PortPoolManager(config=config.media.port_pool)
        
        # MediaMode 변환 (config.models.MediaMode → media_session.MediaMode)
        mode_value = config.media.mode.value.lower()
        if mode_value == "direct":
            media_mode = MediaMode.DIRECT
        elif mode_value == "bypass":
            media_mode = MediaMode.BYPASS
        else:
            media_mode = MediaMode.REFLECTING
        
        self._media_session_manager = MediaSessionManager(
            port_pool=self._port_pool,
            default_mode=media_mode
        )
        self._call_repository = CallStateRepository()
        
        # 녹음 설정 (config.yaml에서 가져오기)
        # recording 설정은 ai_voicebot 하위에 있음
        ai_voicebot_config = getattr(config, 'ai_voicebot', None)
        logger.info("config_debug_step1", has_ai_voicebot=ai_voicebot_config is not None)
        
        recording_config = None
        gcp_credentials_path = None
        enable_post_stt = False
        stt_language = "ko-KR"
        
        if ai_voicebot_config:
            recording_config = getattr(ai_voicebot_config, 'recording', None)
            logger.info("config_debug_step2", has_recording=recording_config is not None)
            
            # GCP 인증 파일 경로
            google_cloud_config = getattr(ai_voicebot_config, 'google_cloud', None)
            if google_cloud_config:
                gcp_credentials_path = getattr(google_cloud_config, 'credentials_path', None)
                logger.info("config_debug_step3", gcp_path=gcp_credentials_path)
        
        # STT 설정
        if recording_config:
            post_stt_config = getattr(recording_config, 'post_processing_stt', None)
            logger.info("config_debug_step4", has_post_stt=post_stt_config is not None)
            
            if post_stt_config:
                enable_post_stt = getattr(post_stt_config, 'enabled', False)
                stt_language = getattr(post_stt_config, 'language', "ko-KR")
                
                logger.info("stt_config_loaded",
                           enable_post_stt=enable_post_stt,
                           stt_language=stt_language,
                           has_gcp_credentials=gcp_credentials_path is not None)
        else:
            logger.warning("config_debug_no_recording", 
                          has_ai_voicebot=ai_voicebot_config is not None)
        
        # ⭐ Knowledge Extractor 초기화 (지식 추출 활성화)
        knowledge_extractor = None
        if recording_config:
            knowledge_extraction_config = getattr(recording_config, 'knowledge_extraction', None)
            logger.info("🔧 [Knowledge Extraction] Config check",
                       has_config=knowledge_extraction_config is not None,
                       enabled=getattr(knowledge_extraction_config, 'enabled', None) if knowledge_extraction_config else None)
            
            if knowledge_extraction_config and getattr(knowledge_extraction_config, 'enabled', False):
                try:
                    logger.info("🔧 [Knowledge Extraction] Starting initialization...")
                    
                    import time
                    import_start = time.time()
                    
                    logger.info("🔄 [Knowledge Import] Step 1/4: Importing KnowledgeExtractor...")
                    from src.ai_voicebot.knowledge.knowledge_extractor import KnowledgeExtractor
                    step1_time = time.time() - import_start
                    logger.info(f"✅ [Knowledge Import] Step 1/4 completed ({step1_time:.3f}s)")
                    
                    logger.info("🔄 [Knowledge Import] Step 2/4: Importing LLMClient...")
                    from src.ai_voicebot.ai_pipeline.llm_client import LLMClient
                    step2_time = time.time() - import_start - step1_time
                    logger.info(f"✅ [Knowledge Import] Step 2/4 completed ({step2_time:.3f}s)")
                    
                    logger.info("🔄 [Knowledge Import] Step 3/4: Importing TextEmbedder...")
                    from src.ai_voicebot.knowledge.embedder import TextEmbedder
                    step3_time = time.time() - import_start - step1_time - step2_time
                    logger.info(f"✅ [Knowledge Import] Step 3/4 completed ({step3_time:.3f}s)")
                    
                    logger.info("🔄 [Knowledge Import] Step 4/4: Importing get_chromadb_client...")
                    from src.ai_voicebot.knowledge.chromadb_client import get_chromadb_client
                    step4_time = time.time() - import_start - step1_time - step2_time - step3_time
                    logger.info(f"✅ [Knowledge Import] Step 4/4 completed ({step4_time:.3f}s)")
                    
                    total_import_time = time.time() - import_start
                    logger.info("🔧 [Knowledge Extraction] Modules imported successfully", 
                               total_time=f"{total_import_time:.3f}s")
                    
                    # LLM 클라이언트 초기화
                    logger.info("🔧 [Knowledge Extraction] Initializing LLM client...")
                    
                    # Gemini 설정 가져오기 (dict로 정의되어 있음)
                    gemini_config = getattr(config.ai_voicebot.google_cloud, 'gemini', None)
                    if not gemini_config:
                        raise ValueError("Gemini configuration not found in config.ai_voicebot.google_cloud.gemini")
                    
                    # API 키 추출 (dict이므로 .get() 사용)
                    api_key = gemini_config.get('api_key') if isinstance(gemini_config, dict) else None
                    if not api_key:
                        raise ValueError("Gemini API key not found in config")
                    
                    # Gemini config dict 구성 (지식 정제 입력/출력 길이 포함)
                    _get = gemini_config.get if isinstance(gemini_config, dict) else lambda k, d=None: getattr(gemini_config, k, d)
                    gemini_config_dict = {
                        "model": _get('model', 'gemini-2.5-flash'),
                        "temperature": _get('temperature', 0.5),
                        "max_tokens": _get('max_output_tokens', 150),
                        "max_output_tokens": _get('max_output_tokens', 150),
                        "judgment_max_output_tokens": _get('judgment_max_output_tokens', 1024),
                        "judgment_max_input_chars": _get('judgment_max_input_chars', 6000),
                        "top_p": _get('top_p', 1.0),
                        "top_k": _get('top_k', 1),
                    }
                    llm_client = LLMClient(config=gemini_config_dict, api_key=api_key)
                    logger.info("🔧 [Knowledge Extraction] LLM client initialized",
                               model=gemini_config_dict.get("model"))
                    
                    # Embedder 초기화
                    logger.info("🔧 [Knowledge Extraction] Initializing Embedder...")
                    embedding_config = getattr(config.ai_voicebot, 'embedding', None)
                    # embedding도 dict일 수 있음
                    if isinstance(embedding_config, dict):
                        embedder = TextEmbedder(
                            model_name=embedding_config.get('model', 'paraphrase-multilingual-mpnet-base-v2'),
                            dimension=embedding_config.get('dimension', 768),
                            batch_size=embedding_config.get('batch_size', 32)
                        )
                    else:
                        embedder = TextEmbedder(
                            model_name=getattr(embedding_config, 'model', 'paraphrase-multilingual-mpnet-base-v2') if embedding_config else 'paraphrase-multilingual-mpnet-base-v2',
                            dimension=getattr(embedding_config, 'dimension', 768) if embedding_config else 768,
                            batch_size=getattr(embedding_config, 'batch_size', 32) if embedding_config else 32
                        )
                    logger.info("🔧 [Knowledge Extraction] Embedder initialized")
                    
                    # VectorDB 초기화
                    logger.info("🔧 [Knowledge Extraction] Initializing ChromaDB...")
                    chromadb_init_start = time.time()
                    
                    vector_db_config = getattr(config.ai_voicebot, 'vector_db', None)
                    # vector_db도 dict일 수 있음
                    if isinstance(vector_db_config, dict):
                        chromadb_config = vector_db_config.get('chromadb', {})
                        persist_dir = chromadb_config.get('persist_directory', './data/chromadb')
                    else:
                        chromadb_config = getattr(vector_db_config, 'chromadb', None) if vector_db_config else None
                        persist_dir = getattr(chromadb_config, 'persist_directory', './data/chromadb') if chromadb_config else './data/chromadb'
                    
                    logger.info("🔄 [ChromaDB Init] Using single ChromaDB client (get_chromadb_client)...",
                               persist_directory=persist_dir)
                    
                    vector_db = get_chromadb_client(
                        persist_directory=persist_dir,
                        collection_name="knowledge_base",
                        client_mode="local",
                    )
                    
                    chromadb_elapsed = time.time() - chromadb_init_start
                    logger.info("✅ [Knowledge Extraction] ChromaDB initialized",
                               elapsed=f"{chromadb_elapsed:.3f}s")
                    
                    # Knowledge Extractor 생성 (v1 또는 v2)
                    # knowledge_extraction_config를 dict로 변환
                    if isinstance(knowledge_extraction_config, dict):
                        ke_config_dict = knowledge_extraction_config
                    else:
                        ke_config_dict = {}
                        for attr in ['min_confidence', 'chunk_size', 'chunk_overlap', 'version',
                                     'steps', 'quality', 'auto_approve', 'min_text_length',
                                     'max_llm_calls_per_extraction', 'skip_short_calls_seconds']:
                            val = getattr(knowledge_extraction_config, attr, None)
                            if val is not None:
                                ke_config_dict[attr] = val
                    
                    pipeline_version = ke_config_dict.get('version', 'v1')
                    
                    if pipeline_version == 'v2':
                        logger.info("🔧 [Knowledge Extraction] Creating Pipeline v2...")
                        from src.ai_voicebot.knowledge.extraction_pipeline import ExtractionPipeline
                        knowledge_extractor = ExtractionPipeline(
                            llm_client=llm_client,
                            embedder=embedder,
                            vector_db=vector_db,
                            config=ke_config_dict,
                        )
                        logger.info("✅ Knowledge Extraction Pipeline v2 initialized")
                    else:
                        min_confidence = ke_config_dict.get('min_confidence', 0.7)
                        chunk_size = ke_config_dict.get('chunk_size', 500)
                        chunk_overlap = ke_config_dict.get('chunk_overlap', 50)
                        
                        logger.info("🔧 [Knowledge Extraction] Creating KnowledgeExtractor v1...",
                                   min_confidence=min_confidence,
                                   chunk_size=chunk_size,
                                   chunk_overlap=chunk_overlap)
                        
                        knowledge_extractor = KnowledgeExtractor(
                            llm_client=llm_client,
                            embedder=embedder,
                            vector_db=vector_db,
                            min_confidence=min_confidence,
                            chunk_size=chunk_size,
                            chunk_overlap=chunk_overlap,
                            min_text_length=ke_config_dict.get("min_text_length", 10),
                            pii_review_queue_enabled=ke_config_dict.get("pii_review_queue_enabled", False),
                            extraction_pending_file=ke_config_dict.get("extraction_pending_file") or "data/extraction_pending_review.jsonl",
                        )
                        logger.info("✅ Knowledge Extractor v1 initialized")
                except Exception as e:
                    logger.error("❌ Knowledge Extractor initialization failed", 
                               error=str(e),
                               error_type=type(e).__name__,
                               exc_info=True)
                    # 실패해도 서버는 계속 실행
                    knowledge_extractor = None
            else:
                logger.warning("⚠️ Knowledge Extraction disabled or config missing",
                             has_config=knowledge_extraction_config is not None,
                             enabled=getattr(knowledge_extraction_config, 'enabled', None) if knowledge_extraction_config else None)
        
        self._call_manager = CallManager(
            call_repository=self._call_repository,
            media_session_manager=self._media_session_manager,
            b2bua_ip=config.sip.listen_ip,
            no_answer_timeout=config.sip.timers.no_answer_timeout,
            knowledge_extractor=knowledge_extractor,  # ⭐ Knowledge Extractor 전달
            gcp_credentials_path=gcp_credentials_path,
            enable_post_stt=enable_post_stt,
            stt_language=stt_language
        )
        
        # CallManager에 SIP Endpoint 참조 설정 (Pipecat RTP Worker 접근용)
        self._call_manager.set_sip_endpoint(self)
        
        # RTP Relay Workers: {call_id: RTPRelayWorker}
        self._rtp_workers: Dict[str, RTPRelayWorker] = {}
        
        # ★ Transfer Manager 초기화
        self._transfer_manager = None
        transfer_config = {}
        if ai_voicebot_config:
            transfer_config_raw = getattr(ai_voicebot_config, 'transfer', None)
            if transfer_config_raw:
                if isinstance(transfer_config_raw, dict):
                    transfer_config = transfer_config_raw
                else:
                    # Pydantic model → dict
                    transfer_config = transfer_config_raw.model_dump() if hasattr(transfer_config_raw, 'model_dump') else {}
            
            if not transfer_config:
                # extra fields에서 가져오기
                try:
                    raw_dict = ai_voicebot_config.model_dump() if hasattr(ai_voicebot_config, 'model_dump') else {}
                    transfer_config = raw_dict.get('transfer', {}) or {}
                except Exception:
                    transfer_config = {}
        
        transfer_enabled = transfer_config.get('enabled', True) if transfer_config else True
        if transfer_enabled:
            from src.sip_core.transfer_manager import TransferManager
            self._transfer_manager = TransferManager(config=transfer_config)
            self._transfer_manager.set_callbacks(
                send_invite=self.send_transfer_invite,
                send_cancel=self.send_transfer_cancel,
                send_bye=self.send_transfer_bye,
                switch_to_bridge=self.switch_to_bridge_mode,
                emit_event=self._emit_transfer_event,
            )
            logger.info("transfer_manager_initialized")
        
        # ★ Outbound Manager 초기화
        self._outbound_manager = None
        outbound_config = {}
        if ai_voicebot_config:
            outbound_config_raw = getattr(ai_voicebot_config, 'outbound', None)
            if outbound_config_raw:
                if isinstance(outbound_config_raw, dict):
                    outbound_config = outbound_config_raw
                else:
                    outbound_config = outbound_config_raw.model_dump() if hasattr(outbound_config_raw, 'model_dump') else {}
            
            if not outbound_config:
                try:
                    raw_dict = ai_voicebot_config.model_dump() if hasattr(ai_voicebot_config, 'model_dump') else {}
                    outbound_config = raw_dict.get('outbound', {}) or {}
                except Exception:
                    outbound_config = {}
        
        outbound_enabled = outbound_config.get('enabled', True) if outbound_config else False
        if outbound_enabled:
            from src.sip_core.outbound_manager import OutboundCallManager
            self._outbound_manager = OutboundCallManager(config=outbound_config)
            self._outbound_manager.set_callbacks(
                send_invite=self.send_outbound_invite,
                send_cancel=self.send_outbound_cancel,
                send_bye=self.send_outbound_bye,
                emit_event=self._emit_outbound_event,
            )
            logger.info("outbound_manager_initialized")
        
        # SIP 타이머 초기화
        self._session_timer = SessionTimer(
            session_expires=config.sip.timers.session_expires,
            min_se=config.sip.timers.min_se,
            default_refresher=config.sip.timers.session_refresher
        )
        self._transaction_timer = TransactionTimer(
            t1=config.sip.timers.t1,
            t2=config.sip.timers.t2,
            t4=config.sip.timers.t4
        )
        
        # CDR Writer 초기화 (통화 이력 기록)
        self._cdr_writer = CDRWriter(output_dir="./cdr")
        logger.info("CDR writer initialized for SIP Endpoint", output_dir="./cdr")
        
        # SIP 트래픽 로그 파일 설정
        self._setup_sip_traffic_log()
        
        logger.info("sip_endpoint_created",
                      message="SIP B2BUA endpoint initialized (signaling + media relay)",
                      timers={
                          "session_expires": config.sip.timers.session_expires,
                          "t1": config.sip.timers.t1,
                          "bye_timeout": config.sip.timers.bye_timeout
                      })
    
    @property
    def media_session_manager(self) -> MediaSessionManager:
        """MediaSessionManager 접근자"""
        return self._media_session_manager
    
    @property
    def port_pool(self) -> PortPoolManager:
        """PortPoolManager 접근자"""
        return self._port_pool
    
    @property
    def call_manager(self) -> CallManager:
        """CallManager 접근자"""
        return self._call_manager
    
    @property
    def transfer_manager(self):
        """TransferManager 접근자"""
        return self._transfer_manager
    
    @property
    def outbound_manager(self):
        """OutboundCallManager 접근자"""
        return self._outbound_manager
    
    async def _emit_outbound_event(self, event_type: str, data: dict):
        """Outbound 이벤트 발행 (WebSocket)"""
        try:
            try:
                from src.websocket import manager as ws_manager
                if ws_manager:
                    await ws_manager.broadcast({
                        "type": event_type,
                        "data": data,
                    })
            except ImportError:
                pass
        except Exception as e:
            logger.error("outbound_event_emit_error",
                        event=event_type, error=str(e))
    
    async def _emit_transfer_event(self, event_type: str, data: dict):
        """Transfer 이벤트 발행 (WebSocket)"""
        try:
            # WebSocket manager가 있으면 broadcast
            try:
                from src.websocket import manager as ws_manager
                if ws_manager:
                    await ws_manager.broadcast_json({
                        "event": event_type,
                        "data": data,
                    })
            except ImportError:
                pass
        except Exception as e:
            logger.error("transfer_event_broadcast_error",
                        event=event_type, error=str(e))
    
    def _setup_sip_traffic_log(self) -> None:
        """SIP 트래픽 로그 파일 설정"""
        from pathlib import Path
        from datetime import datetime
        
        # 로그 디렉토리 생성
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        
        # 로그 파일 경로 (날짜별)
        timestamp = datetime.now().strftime("%Y%m%d")
        log_file_path = log_dir / f"sip_traffic_{timestamp}.log"
        
        try:
            self._sip_log_file = open(log_file_path, 'a', encoding='utf-8', buffering=1)
            logger.info("sip_traffic_log_opened", log_file=str(log_file_path))
        except Exception as e:
            logger.error("sip_traffic_log_open_failed", error=str(e))
            self._sip_log_file = None
    
    def _get_b2bua_ip(self) -> str:
        """B2BUA IP 가져오기 (SDP c= 라인용)
        
        Returns:
            str: B2BUA가 사용할 IP 주소
        """
        if self._cached_b2bua_ip:
            return self._cached_b2bua_ip
            
        # 1. 설정에 advertised_ip가 있으면 사용
        b2bua_ip = getattr(self.config.sip, 'advertised_ip', None)
        
        if b2bua_ip:
            logger.info("b2bua_ip_from_config", ip=b2bua_ip)
            self._cached_b2bua_ip = b2bua_ip
            return b2bua_ip
        
        # 2. listen_ip가 0.0.0.0이 아니면 사용
        b2bua_ip = self.config.sip.listen_ip
        if b2bua_ip != "0.0.0.0":
            self._cached_b2bua_ip = b2bua_ip
            return b2bua_ip
        
        # 3. 자동 감지: 외부로 연결 시도하여 실제 사용되는 로컬 IP 가져오기
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            b2bua_ip = s.getsockname()[0]
            s.close()
            logger.info("b2bua_ip_auto_detected", ip=b2bua_ip, method="udp_connect")
        except:
            # Fallback: hostname 사용
            try:
                b2bua_ip = socket.gethostbyname(socket.gethostname())
                logger.info("b2bua_ip_auto_detected", ip=b2bua_ip, method="hostname")
            except:
                b2bua_ip = "127.0.0.1"
                logger.warning("b2bua_ip_fallback", ip=b2bua_ip)
        
        self._cached_b2bua_ip = b2bua_ip
        return b2bua_ip
    
    def _log_sip_message(self, direction: str, message: str, addr: tuple) -> None:
        """SIP 메시지를 파일에 로깅
        
        Args:
            direction: 'RECV' 또는 'SEND'
            message: SIP 메시지
            addr: 주소 (ip, port)
        """
        from datetime import datetime
        
        if not self._sip_log_file:
            return
        
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            emoji = "📥" if direction == "RECV" else "📤"
            
            log_entry = (
                f"\n{'='*70}\n"
                f"{emoji} SIP {direction} [{timestamp}] {addr[0]}:{addr[1]}\n"
                f"{'='*70}\n"
                f"{message}\n"
                f"{'='*70}\n"
            )
            
            # 파일 핸들이 유효한지 확인
            if self._sip_log_file.closed:
                logger.error("sip_log_file_closed", direction=direction, addr=f"{addr[0]}:{addr[1]}")
                return
            
            self._sip_log_file.write(log_entry)
            # ⚠️ flush()는 동기 I/O로 이벤트 루프를 블로킹할 수 있으므로 제거
            # line-buffered 모드(buffering=1)로 open하여 줄 단위 자동 플러시
            
        except OSError as e:
            # 파일 I/O 에러 (Errno 22 등)
            logger.error("sip_traffic_log_write_failed", 
                        error=str(e),
                        error_type=type(e).__name__,
                        errno=e.errno if hasattr(e, 'errno') else 'N/A',
                        direction=direction,
                        addr=f"{addr[0]}:{addr[1]}")
        except Exception as e:
            # 기타 에러
            logger.error("sip_traffic_log_unexpected_error", 
                        error=str(e),
                        error_type=type(e).__name__,
                        direction=direction,
                        addr=f"{addr[0]}:{addr[1]}")
    
    async def _handle_sip_message(self, data: bytes, addr: tuple) -> None:
        """SIP 메시지 처리
        
        Args:
            data: 수신한 데이터
            addr: 송신자 주소 (ip, port)
        """
        try:
            # 빈 패킷 무시
            if len(data) == 0:
                logger.debug("empty_packet_received", from_addr=f"{addr[0]}:{addr[1]}")
                return
            
            # UTF-8 디코딩 시도
            try:
                message = data.decode('utf-8')
            except UnicodeDecodeError:
                # 디코딩 실패 시 Latin-1로 시도 (SIP는 ASCII 기반)
                try:
                    message = data.decode('latin-1')
                    logger.warning("decode_fallback_to_latin1", from_addr=f"{addr[0]}:{addr[1]}")
                except Exception as e:
                    logger.error("decode_failed", error=str(e), 
                               raw_bytes=data[:100].hex(), from_addr=f"{addr[0]}:{addr[1]}")
                    return
            
            # 빈 메시지 또는 너무 짧은 메시지 무시
            message_stripped = message.strip()
            if len(message_stripped) < 10:
                logger.debug("message_too_short", 
                           size=len(data),
                           raw_bytes=data.hex(),
                           from_addr=f"{addr[0]}:{addr[1]}")
                return
            
            # SIP 메서드 파싱
            lines = message.split('\r\n')
            if not lines or not lines[0]:
                logger.warning("no_request_line", from_addr=f"{addr[0]}:{addr[1]}")
                return
                
            request_line = lines[0].strip()
            parts = request_line.split()
            if len(parts) < 2:
                logger.warning("invalid_request_line", 
                             request_line=request_line,
                             from_addr=f"{addr[0]}:{addr[1]}")
                return
            
            method = parts[0]
            
            # 📥 RECV 로그 (비동기 logger 사용, DEBUG 레벨)
            logger.debug("sip_recv_raw",
                        direction="RECV",
                        from_addr=f"{addr[0]}:{addr[1]}",
                        size=len(data),
                        message=message[:500] if len(message) > 500 else message)  # 메시지가 너무 길면 잘라서 로깅
            
            # 파일에 로깅 (try-except로 보호)
            try:
                self._log_sip_message("RECV", message, addr)
            except Exception as log_err:
                # 파일 로그 실패해도 서버는 계속 동작
                logger.warning("sip_file_log_failed_on_recv", 
                             error=str(log_err),
                             error_type=type(log_err).__name__,
                             from_addr=f"{addr[0]}:{addr[1]}")
            
            # 로그: 요청인지 응답인지 구분
            if message.startswith('SIP/2.0'):
                # SIP 응답 메시지 (200 OK, 180 Ringing 등)
                status_code = parts[1] if len(parts) > 1 else 'UNKNOWN'
                
                # CSeq에서 method 추출 (예: "CSeq: 1 INVITE" → "INVITE")
                cseq_method = "UNKNOWN"
                for line in lines:
                    if line.lower().startswith('cseq:'):
                        cseq_parts = line.split()
                        if len(cseq_parts) >= 3:
                            cseq_method = cseq_parts[2]  # CSeq: 1 INVITE
                        break
                
                logger.info("sip_recv",
                           direction="RECV",
                           status_code=status_code,
                           method=cseq_method,  # 어떤 메소드의 응답인지
                           from_addr=f"{addr[0]}:{addr[1]}",
                           size=len(data))
            else:
                # SIP 요청 메시지 (INVITE, REGISTER 등)
                logger.info("sip_recv",
                           direction="RECV",
                           method=method,
                           from_addr=f"{addr[0]}:{addr[1]}",
                           size=len(data))
            
            # 응답 생성 및 전송
            response = None
            if method == 'OPTIONS':
                response = self._create_options_response(message, addr)
                if response:
                    self._send_response(response, addr)
            elif method == 'REGISTER':
                response = self._handle_register(message, addr)
                if response:
                    self._send_response(response, addr)
            elif method == 'INVITE':
                # B2BUA INVITE 처리 (비동기)
                asyncio.create_task(self._handle_invite_b2bua(message, addr))
            elif method == 'ACK':
                # ACK 처리 (SIP Dialog 완료, RTP는 200 OK 시점에 이미 시작됨)
                self._handle_ack(message, addr)
            elif method == 'BYE':
                # BYE 처리 (세션 종료)
                asyncio.create_task(self._handle_bye(message, addr))
            elif method == 'CANCEL':
                # CANCEL 처리
                asyncio.create_task(self._handle_cancel(message, addr))
            else:
                # SIP 응답 메시지 (180, 200 OK 등)
                if message.startswith('SIP/2.0'):
                    asyncio.create_task(self._handle_sip_response(message, addr))
                else:
                    logger.warning("sip_method_not_implemented", method=method)
                    response = self._create_not_implemented_response(message, addr)
                    if response:
                        self._send_response(response, addr)
                    
        except Exception as e:
            logger.error("sip_message_handling_error", 
                        error=str(e), 
                        error_type=type(e).__name__,
                        from_addr=f"{addr[0]}:{addr[1]}" if isinstance(addr, tuple) and len(addr) == 2 else str(addr),
                        exc_info=True)
    
    def _send_response(self, response: str, addr: tuple) -> None:
        """응답 전송 및 로깅
        
        Args:
            response: SIP 응답 메시지
            addr: 대상 주소 (ip, port)
        """
        try:
            # addr가 tuple인지 확인
            if not isinstance(addr, tuple) or len(addr) != 2:
                logger.error("invalid_addr_format_for_sendto", 
                           addr=str(addr), 
                           addr_type=type(addr).__name__,
                           expected="tuple (ip, port)")
                return
            
            # 소켓 전송
            self._socket.sendto(response.encode('utf-8'), addr)
            
        except OSError as e:
            # 소켓 에러 (Errno 22 등)
            logger.error("socket_sendto_failed", 
                        error=str(e), 
                        errno=e.errno if hasattr(e, 'errno') else 'N/A',
                        to_addr=f"{addr[0]}:{addr[1]}" if isinstance(addr, tuple) and len(addr) == 2 else str(addr),
                        exc_info=True)
            return
        except Exception as e:
            # 기타 에러
            logger.error("sendto_unexpected_error", 
                        error=str(e), 
                        error_type=type(e).__name__,
                        to_addr=f"{addr[0]}:{addr[1]}" if isinstance(addr, tuple) and len(addr) == 2 else str(addr),
                        exc_info=True)
            return
        
        # 📤 SEND 로그 (비동기 logger 사용, DEBUG 레벨)
        logger.debug("sip_send_raw",
                    direction="SEND",
                    to_addr=f"{addr[0]}:{addr[1]}",
                    size=len(response),
                    message=response[:500] if len(response) > 500 else response)  # 메시지가 너무 길면 잘라서 로깅
        
        # 파일에 로깅 (try-except로 보호)
        try:
            self._log_sip_message("SEND", response, addr)
        except Exception as log_err:
            # 파일 로그 실패해도 서버는 계속 동작
            logger.warning("sip_file_log_failed_on_send", 
                         error=str(log_err),
                         error_type=type(log_err).__name__,
                         to_addr=f"{addr[0]}:{addr[1]}")
        
        # 로그: 요청인지 응답인지 구분
        lines = response.split('\r\n')
        if lines and ' ' in lines[0]:
            parts = lines[0].split()
            if response.startswith('SIP/2.0'):
                # SIP 응답 메시지 (200 OK, 180 Ringing 등)
                status_code = parts[1] if len(parts) > 1 else 'UNKNOWN'
                
                # CSeq에서 method 추출 (예: "CSeq: 1 INVITE" → "INVITE")
                cseq_method = "UNKNOWN"
                for line in lines:
                    if line.lower().startswith('cseq:'):
                        cseq_parts = line.split()
                        if len(cseq_parts) >= 3:
                            cseq_method = cseq_parts[2]  # CSeq: 1 INVITE
                        break
                
                logger.info("sip_send",
                           direction="SEND",
                           status_code=status_code,
                           method=cseq_method,  # 어떤 메소드의 응답인지
                           to_addr=f"{addr[0]}:{addr[1]}",
                           size=len(response))
            else:
                # SIP 요청 메시지 (BYE, INVITE 등)
                method = parts[0] if len(parts) > 0 else 'UNKNOWN'
                logger.info("sip_send",
                           direction="SEND",
                           method=method,
                           to_addr=f"{addr[0]}:{addr[1]}",
                           size=len(response))
        else:
            logger.info("sip_send",
                       direction="SEND",
                       method="UNKNOWN",
                       to_addr=f"{addr[0]}:{addr[1]}",
                       size=len(response))
    
    def _extract_username(self, sip_uri: str) -> str:
        """SIP URI에서 username 추출
        
        Args:
            sip_uri: SIP URI (예: <sip:1004@10.62.164.233>)
            
        Returns:
            str: username (없으면 빈 문자열)
        """
        import re
        # <sip:username@domain> 또는 sip:username@domain 형식
        match = re.search(r'sip:([^@;>]+)@', sip_uri)
        if match:
            return match.group(1)
        return ''
    
    def _extract_tag(self, header: str) -> Optional[str]:
        """헤더에서 tag 파라미터 추출
        
        Args:
            header: SIP 헤더 (From, To 등)
            
        Returns:
            str: tag 값 (없으면 None)
        """
        match = re.search(r';tag=([^;>\s]+)', header)
        if match:
            return match.group(1)
        return None
    
    def _extract_sdp_body(self, message: str) -> Optional[str]:
        """SIP 메시지에서 SDP body 추출
        
        Args:
            message: 전체 SIP 메시지
            
        Returns:
            str: SDP body (없으면 None)
        """
        # 헤더와 body는 \r\n\r\n으로 구분
        parts = message.split('\r\n\r\n', 1)
        if len(parts) > 1 and parts[1].strip():
            return parts[1].strip()
        return None
    
    async def _handle_sip_response(self, response: str, addr: tuple) -> None:
        """SIP 응답 메시지 처리 (180, 200 OK 등)
        
        Args:
            response: SIP 응답 메시지
            addr: 송신자 주소
        """
        try:
            # 응답 코드 추출
            lines = response.split('\r\n')
            if not lines:
                return
            
            status_line = lines[0]
            parts = status_line.split()
            if len(parts) < 3:
                return
            
            status_code = parts[1]
            call_id = self._extract_header(response, 'Call-ID')
            cseq = self._extract_header(response, 'CSeq')
            
            logger.debug("sip_response_received", status_code=status_code, call_id=call_id)
            
            # ★ Outbound 콜 응답 처리
            outbound_call_info = self._active_calls.get(call_id)
            if outbound_call_info and outbound_call_info.get('is_outbound'):
                await self.handle_outbound_response(response, addr, outbound_call_info)
                return
            
            # ★ Transfer 레그 응답 처리
            transfer_call_info = self._active_calls.get(call_id)
            if transfer_call_info and transfer_call_info.get('is_transfer'):
                await self.handle_transfer_response(response, addr, transfer_call_info)
                return
            
            # B2BUA Call-ID 매핑 확인
            original_call_id = self._call_mapping.get(call_id)
            if not original_call_id or original_call_id not in self._active_calls:
                # ✅ 예외: 487 Request Terminated는 call cleanup 후에도 ACK를 보내야 함
                # (CANCEL 전송 후 call이 cleanup된 경우)
                if status_code == '487' and 'INVITE' in cseq:
                    logger.info("487_after_cleanup_sending_ack",
                               call_id=call_id,
                               original_call_id=original_call_id)
                    
                    # Call-ID mapping이 없으면 call_id를 직접 사용 (B2BUA → UAS leg)
                    await self._send_ack_for_487_without_call_info(response, addr)
                    return
                
                logger.debug("response_for_unknown_call", call_id=call_id)
                return
            
            call_info = self._active_calls[original_call_id]
            
            # 응답 릴레이
            if status_code in ['180', '183']:  # Ringing, Session Progress
                logger.debug("relaying_response", status_code=status_code, call_id=original_call_id)
                # ⚠️ 중요: 180 Ringing에서도 To tag를 추출해야 함!
                # RFC 3261: Early Dialog 생성을 위해 180부터 tag가 있어야 함
                to_hdr = self._extract_header(response, 'To')
                callee_tag = self._extract_tag(to_hdr)
                if callee_tag and not call_info.get('callee_tag'):
                    call_info['callee_tag'] = callee_tag
                    logger.info("callee_tag_from_180", 
                               call_id=original_call_id, 
                               callee_tag=callee_tag)
                
                # Transaction Timer: 1xx 응답 수신 (PROCEEDING 상태로 변경)
                transaction_id = call_info.get('transaction_id')
                if transaction_id:
                    await self._transaction_timer.response_received(
                        transaction_id=transaction_id,
                        status_code=int(status_code)
                    )
                
                await self._relay_response_to_caller(response, call_info)
            
            elif status_code == '200' and 'INVITE' in cseq:  # 200 OK for INVITE
                logger.info("relaying_200ok", call_id=original_call_id)
                
                # no_answer_timeout 타이머 취소 (착신자가 응답함)
                no_answer_timer = call_info.get('no_answer_timer')
                if no_answer_timer and not no_answer_timer.done():
                    no_answer_timer.cancel()
                    call_info.pop('no_answer_timer', None)
                    logger.info("no_answer_timer_cancelled_on_200ok",
                               call_id=original_call_id)
                
                # Callee tag 저장 (180에서 이미 저장되었을 수 있음)
                to_hdr = self._extract_header(response, 'To')
                callee_tag = self._extract_tag(to_hdr)
                if callee_tag:
                    # 180의 tag와 일치하는지 확인
                    existing_tag = call_info.get('callee_tag')
                    if existing_tag and existing_tag != callee_tag:
                        logger.warning("callee_tag_mismatch",
                                     call_id=original_call_id,
                                     tag_180=existing_tag,
                                     tag_200=callee_tag)
                    call_info['callee_tag'] = callee_tag
                call_info['state'] = 'answered'
                call_info['answer_time'] = datetime.now()  # CDR용 통화 응답 시간

                # 대시보드 실시간 통화: Repository 세션을 ESTABLISHED로 갱신
                if self.call_manager:
                    self.call_manager.mark_b2bua_established(original_call_id)
                # WebSocket: B2BUA 경로는 CallManager ACK를 타지 않으므로 여기서 call_started 발송
                try:
                    from src.websocket import manager as ws_manager
                    caller_uri = f"sip:{call_info.get('caller_username', '')}@{call_info.get('caller_addr', ('', 0))[0]}"
                    callee_uri = f"sip:{call_info.get('callee_username', '')}@{call_info.get('callee_addr', ('', 0))[0]}"
                    asyncio.create_task(ws_manager.emit_call_started(
                        original_call_id,
                        {
                            "caller": caller_uri,
                            "callee": callee_uri,
                            "is_ai_handled": call_info.get("ai_mode_activated", False),
                        },
                    ))
                except Exception as e:
                    logger.warning("b2bua_call_started_ws_failed", call_id=original_call_id, error=str(e))
                
                # Transaction Timer: 200 OK 수신 (COMPLETED 상태로 변경 및 종료)
                transaction_id = call_info.get('transaction_id')
                if transaction_id:
                    await self._transaction_timer.response_received(
                        transaction_id=transaction_id,
                        status_code=int(status_code)
                    )
                    logger.info("invite_transaction_completed",
                               transaction_id=transaction_id,
                               call_id=original_call_id)
                
                # Session Timer 시작 (장시간 통화 유지)
                await self._session_timer.start_timer(
                    call_id=original_call_id,
                    expires=self.config.sip.timers.session_expires,
                    refresher=self.config.sip.timers.session_refresher,
                    refresh_callback=lambda cid: asyncio.create_task(self._send_session_update(cid))
                )
                logger.info("session_timer_started",
                           call_id=original_call_id,
                           expires=self.config.sip.timers.session_expires)
                
                await self._relay_response_to_caller(response, call_info)
                logger.info("call_answered_waiting_ack",
                           call_id=original_call_id,
                           session_refresh_interval=f"{self.config.sip.timers.session_expires / 2}s")
            
            elif status_code == '200' and 'BYE' in cseq:  # 200 OK for BYE
                logger.info("call_terminated", call_id=original_call_id)
                
                # BYE Transaction Timer 종료
                bye_transaction_id = call_info.get('bye_transaction_id')
                if bye_transaction_id:
                    await self._transaction_timer.terminate_transaction(bye_transaction_id)
                    logger.info("bye_transaction_completed",
                               transaction_id=bye_transaction_id,
                               call_id=original_call_id)
                
                # 세션 정리 (Session Timer 포함)
                await self._cleanup_call(original_call_id)
            
            # 에러 응답 처리 (3xx, 4xx, 5xx, 6xx)
            # RFC 3261: 모든 최종 응답(2xx 제외)에 대해 ACK가 필요함
            elif status_code.startswith(('3', '4', '5', '6')):
                # ✅ AI 모드 체크: 487은 CANCEL의 결과이므로 AI 모드에서는 caller에게 relay하지 않음
                is_ai_mode = call_info.get('ai_mode_activated', False)
                
                if status_code == '487' and is_ai_mode:
                    logger.info("487_not_relayed_ai_mode",
                               call_id=original_call_id,
                               ai_mode=True)
                    
                    # RFC 3261: Non-2xx 최종 응답(3xx-6xx)에 대해 ACK를 Callee에게 전송
                    await self._send_ack_for_error_response(response, call_info)
                    
                    # ⚠️ caller에게는 relay하지 않음 (이미 200 OK를 보냈음)
                    # call cleanup도 하지 않음 (AI 세션 진행 중)
                    return
                
                logger.info("relaying_final_response", status_code=status_code, call_id=original_call_id)
                logger.info("final_response_received",
                           call_id=original_call_id,
                           status_code=status_code,
                           reason=parts[2] if len(parts) > 2 else "Unknown")
                
                # RFC 3261: Non-2xx 최종 응답(3xx-6xx)에 대해 ACK를 Callee에게 전송
                # INVITE Transaction을 완료하기 위해 필요
                await self._send_ack_for_error_response(response, call_info)
                
                # 에러 응답을 caller에게 릴레이
                await self._relay_response_to_caller(response, call_info)
                
                # 통화 종료 처리
                await self._cleanup_call(original_call_id)
            
        except Exception as e:
            logger.error("response_handling_error", error=str(e))
    
    async def _relay_response_to_caller(self, callee_response: str, call_info: Dict) -> None:
        """Callee의 응답을 Caller에게 릴레이
        
        Args:
            callee_response: Callee로부터 받은 응답
            call_info: 통화 정보
        """
        try:
            # 원본 INVITE의 헤더를 사용해서 응답 생성
            lines = callee_response.split('\r\n')
            if not lines:
                return
                
            status_line = lines[0]  # SIP/2.0 200 OK 등
            
            # 원본 Call-ID 찾기
            original_call_id = None
            for orig_id, new_id in self._call_mapping.items():
                if new_id == call_info['b2bua_call_id']:
                    original_call_id = orig_id
                    break
            
            if not original_call_id:
                logger.error("original_call_id_not_found", b2bua_call_id=call_info['b2bua_call_id'])
                return
            
            # 원본 INVITE에서 Via, From, To, CSeq를 저장해야 함
            # 지금은 call_info에서 복원
            from_hdr = call_info['original_from']
            to_hdr = call_info['original_to']
            if call_info.get('callee_tag'):
                to_hdr += f";tag={call_info['callee_tag']}"
            
            # 원본 Via와 branch를 저장해야 함 - call_info에 추가 필요
            via_branch = call_info.get('original_via_branch', 'z9hG4bK-unknown')
            via = f"SIP/2.0/UDP {call_info['caller_addr'][0]}:{call_info['caller_addr'][1]};branch={via_branch};rport"
            
            # Callee 응답에서 추가 헤더 복사 (Contact, Allow 등)
            allow_hdr = self._extract_header(callee_response, 'Allow')
            
            # SDP 추출 (있으면)
            callee_sdp = self._extract_sdp_body(callee_response)
            
            # B2BUA IP 가져오기 (SDP c= 라인용)
            b2bua_ip = self._get_b2bua_ip()
            
            # Contact 헤더를 B2BUA 주소로 rewrite (RFC 3261)
            # 200 OK의 Contact가 ACK의 Request-URI가 되므로 항상 B2BUA 주소여야 함!
            # (Direct 모드에서도 SIP 시그널링은 B2BUA 경유)
            contact_hdr = f"<sip:{call_info['callee_username']}@{b2bua_ip}:{self.config.sip.listen_port}>"
            
            # 📝 Callee SDP Rewrite (200 OK 응답)
            rewritten_sdp = None
            if callee_sdp:
                logger.debug("rewriting_callee_sdp", call_id=original_call_id)
                
                # MediaSession에 Callee SDP 업데이트
                try:
                    self.media_session_manager.update_callee_sdp(original_call_id, callee_sdp)
                    media_session = self.media_session_manager.get_session(original_call_id)
                    
                    if media_session:
                        # Direct 모드 확인
                        if media_session.mode == MediaMode.DIRECT:
                            # Direct 모드: SDP만 수정하지 않고 그대로 전달
                            # (Contact는 B2BUA 주소 - SIP 시그널링은 B2BUA 경유!)
                            rewritten_sdp = callee_sdp
                            logger.info("direct_media_mode_enabled",
                                       call_id=original_call_id,
                                       message="SDP not modified (direct RTP), Contact=B2BUA (signaling via B2BUA)")
                        else:
                            # Bypass/Reflecting 모드: B2BUA가 중계
                            # 1. 벤더 특정 속성 제거 (a=X-nat:0 등)
                            rewritten_sdp = SDPManipulator.remove_vendor_attributes(callee_sdp)
                            
                            # 2. Origin IP를 B2BUA IP로 교체 (o= 라인)
                            rewritten_sdp = SDPManipulator.replace_origin_ip(rewritten_sdp, b2bua_ip)
                            
                            # 3. Connection IP를 B2BUA IP로 교체 (c= 라인)
                            rewritten_sdp = SDPManipulator.replace_connection_ip(rewritten_sdp, b2bua_ip)
                            
                            # 4. Audio 포트를 Caller Leg 할당 포트로 교체
                            caller_audio_port = media_session.caller_leg.get_audio_rtp_port()
                            caller_audio_rtcp_port = media_session.caller_leg.get_audio_rtcp_port()
                            
                            if caller_audio_port:
                                rewritten_sdp = SDPManipulator.replace_media_port(rewritten_sdp, "audio", caller_audio_port)
                                logger.debug("sdp_rewritten",
                                           call_id=original_call_id,
                                           o=b2bua_ip,
                                           c=b2bua_ip,
                                           m_audio=caller_audio_port)
                            
                            # 5. RTCP 포트를 SHORT FORMAT으로 변경 (원본 SDP에 a=rtcp:가 있는 경우만)
                            # 클라이언트 호환성을 위해 항상 short format (a=rtcp:PORT) 사용
                            if caller_audio_rtcp_port and SDPManipulator.has_rtcp_attribute(callee_sdp, "audio"):
                                rewritten_sdp = SDPManipulator.replace_rtcp_attribute(rewritten_sdp, "audio", caller_audio_rtcp_port, b2bua_ip)
                                logger.debug("rtcp_port_rewritten",
                                           call_id=original_call_id,
                                           rtcp_port=caller_audio_rtcp_port)
                        
                            # 🎵 7. RTP Relay 업데이트 (200 OK 시점에 Callee endpoint 정보 반영)
                        # Early Bind로 이미 소켓은 bind되었으므로, Callee endpoint만 업데이트
                        logger.debug("updating_rtp_relay_callee_endpoint", call_id=original_call_id)
                        
                        # 이미 RTP Worker가 시작되었는지 확인
                        if original_call_id in self._rtp_workers:
                            # Callee endpoint 업데이트
                            rtp_worker = self._rtp_workers[original_call_id]
                            callee_ip = media_session.callee_leg.original_ip
                            callee_rtp_port = media_session.callee_leg.original_audio_port
                            callee_rtcp_port = media_session.callee_leg.original_audio_rtcp_port
                            
                            if callee_ip and callee_rtp_port and callee_rtcp_port:
                                rtp_worker.update_callee_endpoint(callee_ip, callee_rtp_port, callee_rtcp_port)
                                logger.info("callee_endpoint_updated",
                                           call_id=original_call_id,
                                           callee_ip=callee_ip,
                                           callee_rtp_port=callee_rtp_port,
                                           callee_rtcp_port=callee_rtcp_port)
                            else:
                                logger.error("callee_endpoint_info_missing",
                                           call_id=original_call_id,
                                           callee_ip=callee_ip,
                                           callee_rtp_port=callee_rtp_port,
                                           callee_rtcp_port=callee_rtcp_port)
                        else:
                            # Early Bind가 실패했거나 아직 안 됨 (fallback)
                            logger.warning("rtp_worker_not_found_fallback", call_id=original_call_id)
                            rtp_success = await self._start_rtp_relay(original_call_id)
                            
                            if not rtp_success:
                                logger.error("rtp_relay_start_failed_at_200ok", call_id=original_call_id)
                            else:
                                logger.info("rtp_relay_started_fallback", call_id=original_call_id)
                        
                        # TODO: Video 지원 시 video 포트도 교체
                    else:
                        logger.warning("media_session_not_found_for_sdp_rewrite", call_id=original_call_id)
                        rewritten_sdp = callee_sdp  # Fallback: SDP 그대로
                        
                except Exception as sdp_err:
                    logger.error("callee_sdp_rewrite_error", error=str(sdp_err), exc_info=True)
                    rewritten_sdp = callee_sdp  # Fallback: SDP 그대로
            
            # 응답 구성
            response_to_caller = f"{status_line}\r\n"
            response_to_caller += f"Via: {via}\r\n"
            response_to_caller += f"From: {from_hdr}\r\n"
            response_to_caller += f"To: {to_hdr}\r\n"
            response_to_caller += f"Call-ID: {original_call_id}\r\n"
            
            # ✅ 원본 INVITE의 CSeq 사용 (RFC 3261: Response의 CSeq = Request의 CSeq)
            original_cseq = call_info.get('original_cseq', '1 INVITE')
            response_to_caller += f"CSeq: {original_cseq}\r\n"
            
            response_to_caller += f"Contact: {contact_hdr}\r\n"
            if allow_hdr:
                response_to_caller += f"Allow: {allow_hdr}\r\n"
            
            # SDP가 있으면 추가 (Rewritten SDP 사용)
            if rewritten_sdp:
                response_to_caller += "Content-Type: application/sdp\r\n"
                response_to_caller += f"Content-Length: {len(rewritten_sdp)}\r\n"
                response_to_caller += "\r\n"
                response_to_caller += rewritten_sdp
            else:
                response_to_caller += "Content-Length: 0\r\n"
                response_to_caller += "\r\n"
            
            self._send_response(response_to_caller, call_info['caller_addr'])
            
        except Exception as e:
            logger.error("relay_response_error", error=str(e), exc_info=True)
    
    async def _send_ack_for_error_response(self, error_response: str, call_info: Dict) -> None:
        """Non-2xx 최종 응답(3xx-6xx)에 대한 ACK를 Callee에게 전송
        
        RFC 3261: Non-2xx final response에 대해서는 UAC(B2BUA)가 ACK를 보내야 함.
        이 ACK는 INVITE transaction을 완료하기 위한 것이며, 별도의 transaction이 아님.
        
        Args:
            error_response: Callee로부터 받은 최종 응답 (3xx-6xx)
            call_info: 통화 정보
        """
        try:
            # Callee 주소 가져오기
            callee_addr = call_info.get('callee_addr')
            callee_username = call_info.get('callee_username')
            caller_username = call_info.get('caller_username')
            
            if not callee_addr or not callee_username:
                logger.error("ack_for_error_missing_info",
                           call_id=call_info.get('original_call_id'),
                           has_callee_addr=bool(callee_addr),
                           has_callee_username=bool(callee_username))
                return
            
            # 응답에서 상태 코드 추출
            lines = error_response.split('\r\n')
            status_line = lines[0] if lines else ""
            status_parts = status_line.split()
            status_code = status_parts[1] if len(status_parts) > 1 else "Unknown"
            
            # 에러 응답에서 To 태그 추출
            to_hdr = self._extract_header(error_response, 'To')
            callee_tag = self._extract_tag(to_hdr)
            
            # 응답에서 CSeq 추출 (원본 INVITE의 CSeq 번호 사용)
            cseq_header = self._extract_header(error_response, 'CSeq')
            if not cseq_header:
                logger.error("ack_cseq_missing",
                           call_id=call_info.get('original_call_id'),
                           response_preview=error_response[:200])
                return
            
            # CSeq 헤더 파싱 (예: "CSeq: 1 INVITE" → "1")
            cseq_parts = cseq_header.split()
            if len(cseq_parts) < 1:
                logger.error("ack_cseq_invalid",
                           call_id=call_info.get('original_call_id'),
                           cseq_header=cseq_header)
                return
            
            cseq_number = cseq_parts[0]  # CSeq 번호 추출
            
            # ACK 구성
            # Request-URI: RFC 3261에 따라 응답의 Contact 헤더가 있으면 사용, 없으면 To URI 사용
            contact_header = self._extract_header(error_response, 'Contact')
            if contact_header:
                # Contact 헤더에서 URI 추출 (예: "<sip:user@host:port>" 또는 "sip:user@host:port")
                contact_uri = contact_header.strip()
                # 꺾쇠 괄호 제거
                if contact_uri.startswith('<') and contact_uri.endswith('>'):
                    contact_uri = contact_uri[1:-1]
                # 파라미터 제거 (예: ";expires=3600")
                if ';' in contact_uri:
                    contact_uri = contact_uri.split(';')[0].strip()
                request_uri = contact_uri
                logger.debug("ack_using_contact_header",
                           call_id=call_info.get('original_call_id'),
                           contact_uri=contact_uri)
            else:
                # Contact 헤더가 없으면 To URI 사용
                request_uri = f"sip:{callee_username}@{callee_addr[0]}:{callee_addr[1]}"
                logger.debug("ack_using_to_uri",
                           call_id=call_info.get('original_call_id'),
                           request_uri=request_uri)
            
            # Via, From, To, Call-ID, CSeq
            b2bua_call_id = call_info.get('b2bua_call_id')
            from_tag = call_info.get('b2bua_from_tag')  # B2BUA가 callee에게 보낸 From tag
            
            # ✅ B2BUA IP 가져오기 (0.0.0.0이나 None 방지)
            b2bua_ip = self._get_b2bua_ip()
            listen_port = self.config.sip.listen_port
            
            # ✅ Via는 응답의 Via 헤더를 그대로 사용 (RFC 3261: Non-2xx ACK)
            # 응답에서 Via 추출
            via_from_response = self._extract_header(error_response, 'Via')
            if via_from_response:
                via = via_from_response.strip()
            else:
                # Via가 없으면 fallback (정상적인 상황에서는 발생하지 않음)
                via_branch = f"z9hG4bK{random.randint(100000, 999999)}"
                via = f"SIP/2.0/UDP {b2bua_ip}:{listen_port};branch={via_branch}"
                logger.warning("ack_via_not_found_in_response",
                             call_id=call_info.get('original_call_id'),
                             using_fallback=True)
            
            # From, To
            from_hdr = f"<sip:{caller_username}@{b2bua_ip}>;tag={from_tag}"
            to_hdr_ack = f"<sip:{callee_username}@{b2bua_ip}>"
            if callee_tag:
                to_hdr_ack += f";tag={callee_tag}"
            
            # CSeq: 원본 INVITE의 CSeq 번호 사용 (method만 ACK로 변경)
            cseq = f"{cseq_number} ACK"
            
            # ACK 메시지 생성
            ack_message = (
                f"ACK {request_uri} SIP/2.0\r\n"
                f"Via: {via}\r\n"
                f"From: {from_hdr}\r\n"
                f"To: {to_hdr_ack}\r\n"
                f"Call-ID: {b2bua_call_id}\r\n"
                f"CSeq: {cseq}\r\n"
                f"Max-Forwards: 70\r\n"
                f"Content-Length: 0\r\n"
                f"\r\n"
            )
            
            # Callee에게 ACK 전송
            self._send_response(ack_message, callee_addr)
            
            logger.info("ack_sent_for_final_response",
                       call_id=b2bua_call_id,
                       callee_addr=f"{callee_addr[0]}:{callee_addr[1]}",
                       status_code=status_code,
                       cseq_number=cseq_number)
            
        except Exception as e:
            logger.error("send_ack_for_error_response_failed", 
                        error=str(e), 
                        exc_info=True)
    
    async def _send_ack_for_487_without_call_info(self, error_response: str, addr: tuple) -> None:
        """Call cleanup 후 도착한 487에 대한 ACK 전송 (call_info 없이)
        
        Args:
            error_response: UAS로부터 받은 487 응답
            addr: UAS 주소 (응답을 보낸 주소)
        """
        try:
            # 응답에서 Call-ID, To, From, CSeq, Via 추출
            call_id = self._extract_header(error_response, 'Call-ID')
            to_hdr = self._extract_header(error_response, 'To')
            from_hdr = self._extract_header(error_response, 'From')
            cseq_header = self._extract_header(error_response, 'CSeq')
            via_from_response = self._extract_header(error_response, 'Via')
            
            if not all([call_id, to_hdr, from_hdr, cseq_header, via_from_response]):
                logger.error("ack_487_missing_headers",
                           call_id=call_id,
                           has_to=bool(to_hdr),
                           has_from=bool(from_hdr),
                           has_cseq=bool(cseq_header),
                           has_via=bool(via_from_response))
                return
            
            # To tag 추출
            callee_tag = self._extract_tag(to_hdr)
            
            # CSeq 번호 추출
            cseq_parts = cseq_header.split()
            if len(cseq_parts) < 1:
                logger.error("ack_487_invalid_cseq", cseq_header=cseq_header)
                return
            cseq_number = cseq_parts[0]
            
            # Request-URI: Contact 헤더 우선, 없으면 To URI 사용
            contact_header = self._extract_header(error_response, 'Contact')
            if contact_header:
                request_uri = contact_header.strip()
                if request_uri.startswith('<') and request_uri.endswith('>'):
                    request_uri = request_uri[1:-1]
                if ';' in request_uri:
                    request_uri = request_uri.split(';')[0].strip()
            else:
                # To URI에서 추출
                request_uri = to_hdr.strip()
                if request_uri.startswith('<') and request_uri.endswith('>'):
                    request_uri = request_uri[1:-1]
                if ';' in request_uri:
                    request_uri = request_uri.split(';')[0].strip()
            
            # ACK 메시지 생성 (Via, From, To, Call-ID, CSeq를 응답에서 가져옴)
            via = via_from_response.strip()
            
            # To 헤더 (tag 포함)
            to_hdr_ack = to_hdr.strip()
            
            # From 헤더 (응답의 From을 그대로 사용)
            from_hdr_ack = from_hdr.strip()
            
            # CSeq: ACK로 변경
            cseq = f"{cseq_number} ACK"
            
            # ACK 메시지
            ack_message = (
                f"ACK {request_uri} SIP/2.0\r\n"
                f"Via: {via}\r\n"
                f"From: {from_hdr_ack}\r\n"
                f"To: {to_hdr_ack}\r\n"
                f"Call-ID: {call_id}\r\n"
                f"CSeq: {cseq}\r\n"
                f"Max-Forwards: 70\r\n"
                f"Content-Length: 0\r\n"
                f"\r\n"
            )
            
            # UAS에게 ACK 전송
            self._send_response(ack_message, addr)
            
            logger.info("ack_sent_for_487_after_cleanup",
                       call_id=call_id,
                       uas_addr=f"{addr[0]}:{addr[1]}",
                       cseq_number=cseq_number)
            logger.debug("ack_sent_for_487_after_cleanup", cseq_number=cseq_number, call_id=call_id)
            
        except Exception as e:
            logger.error("send_ack_for_487_without_call_info_failed",
                        error=str(e),
                        exc_info=True)
    
    def _handle_ack(self, request: str, addr: tuple) -> None:
        """ACK 처리 (SIP Dialog 완료)
        
        RTP Relay는 이미 200 OK 시점에 시작되었으므로,
        ACK는 단순히 Callee에게 전달하고 호를 active 상태로 표시합니다.
        
        Args:
            request: ACK 요청
            addr: 송신자 주소
        """
        try:
            call_id = self._extract_header(request, 'Call-ID')
            
            logger.info("ack_received_debug",
                       call_id=call_id,
                       from_addr=f"{addr[0]}:{addr[1]}",
                       active_calls=list(self._active_calls.keys()))
            
            if call_id not in self._active_calls:
                logger.warning("ack_ignored_no_active_call",
                             call_id=call_id,
                             active_calls=list(self._active_calls.keys()))
                return
        except Exception as e:
            logger.error("ack_handling_error_early",
                        error=str(e),
                        exc_info=True)
            return
        
        try:
            call_info = self._active_calls[call_id]
            logger.debug("ack_received_debug", call_id=call_id)
        
            # ✅ AI 모드 체크: AI가 응답한 경우 ACK를 callee에게 relay하지 않음
            is_ai_mode = call_info.get('ai_mode_activated', False)
            
            if is_ai_mode:
                logger.info("ack_received_ai_mode",
                           call_id=call_id,
                           ai_mode=True)
                
                # AI 모드에서는 RTP가 이미 설정되었는지 확인
                # Call state를 established로 변경
                call_info['state'] = 'established'
                logger.info("call_established",
                           call_id=call_id,
                           caller=call_info.get('caller_username'),
                           callee='AI')
                
                return  # callee에게 ACK를 relay하지 않음
            
            # call_info 내용 확인
            logger.info("ack_call_info",
                       call_id=call_id,
                       has_b2bua_call_id='b2bua_call_id' in call_info,
                       has_callee_addr='callee_addr' in call_info,
                       call_info_keys=list(call_info.keys()))
            
            # Callee에게 ACK 전달
            new_call_id = call_info.get('b2bua_call_id')
            callee_addr = call_info.get('callee_addr')
            
            if not new_call_id or not callee_addr:
                logger.error("ack_missing_call_info",
                            call_id=call_id,
                            has_b2bua_call_id=bool(new_call_id),
                            has_callee_addr=bool(callee_addr),
                            call_info_keys=list(call_info.keys()))
                return
            
            logger.info("ack_relay_start",
                       call_id=call_id,
                       new_call_id=new_call_id,
                       callee_addr=f"{callee_addr[0]}:{callee_addr[1]}")
            
            # B2BUA IP 가져오기 (SDP c= 라인용)
            b2bua_ip = self._get_b2bua_ip()
        
            # B2BUA가 INVITE에서 사용한 From tag와 동일하게 설정
            b2bua_from_tag = call_info.get('b2bua_from_tag', 'b2bua')
            
            # ACK에 SDP가 있는지 확인 (일부 클라이언트는 ACK에 SDP 포함)
            sdp_body = self._extract_sdp_body(request)
            rewritten_sdp = ""
            
            logger.info("ack_sdp_check",
                       call_id=call_id,
                       has_sdp=bool(sdp_body))
            
            if sdp_body:
                # SDP가 있으면 B2BUA IP/Port로 수정
                media_session = self._media_session_manager.get_session(call_id)
                logger.info("ack_media_session_check",
                           call_id=call_id,
                           has_media_session=media_session is not None)
                
                if media_session:
                    # Direct 모드가 아니면 SDP 수정
                    if media_session.mode != MediaMode.DIRECT:
                        # Callee 쪽 RTP 포트 가져오기
                        callee_audio_port = media_session.callee_leg.get_audio_rtp_port()
                        callee_audio_rtcp_port = media_session.callee_leg.get_audio_rtcp_port()
                        
                        # SDP 수정: c= 필드를 B2BUA IP로, m= 포트를 서버 포트로
                        rewritten_sdp = SDPManipulator.replace_connection_ip(sdp_body, b2bua_ip)
                        rewritten_sdp = SDPManipulator.replace_origin_ip(rewritten_sdp, b2bua_ip)
                        rewritten_sdp = SDPManipulator.replace_media_port(rewritten_sdp, "audio", callee_audio_port)
                        
                        # RTCP 포트를 SHORT FORMAT으로 변경 (원본 SDP에 a=rtcp:가 있는 경우만)
                        if callee_audio_rtcp_port and SDPManipulator.has_rtcp_attribute(sdp_body, "audio"):
                            rewritten_sdp = SDPManipulator.replace_rtcp_attribute(rewritten_sdp, "audio", callee_audio_rtcp_port, b2bua_ip)
                        
                        logger.info("ack_sdp_rewritten",
                                   call_id=call_id,
                                   b2bua_ip=b2bua_ip,
                                   b2bua_port=callee_audio_port)
                    else:
                        # Direct 모드: SDP 그대로 전달
                        rewritten_sdp = sdp_body
                        logger.info("ack_sdp_direct_mode", call_id=call_id)
            
            # ACK 메시지 생성
            ack_to_callee = (
                f"ACK sip:{call_info['callee_username']}@{callee_addr[0]}:{callee_addr[1]} SIP/2.0\r\n"
                f"Via: SIP/2.0/UDP {b2bua_ip}:{self.config.sip.listen_port};branch=z9hG4bK{random.randint(100000, 999999)}\r\n"
                f"From: <sip:{call_info['caller_username']}@{b2bua_ip}>;tag={b2bua_from_tag}\r\n"
                f"To: <sip:{call_info['callee_username']}@{b2bua_ip}>;tag={call_info.get('callee_tag', 'unknown')}\r\n"
                f"Call-ID: {new_call_id}\r\n"
                "CSeq: 1 ACK\r\n"
                "Max-Forwards: 70\r\n"
            )
            
            # SDP 추가 (있는 경우)
            if rewritten_sdp:
                ack_to_callee += "Content-Type: application/sdp\r\n"
                ack_to_callee += f"Content-Length: {len(rewritten_sdp)}\r\n"
                ack_to_callee += "\r\n"
                ack_to_callee += rewritten_sdp
            else:
                ack_to_callee += "Content-Length: 0\r\n"
                ack_to_callee += "\r\n"
            
            logger.info("ack_sending",
                       call_id=call_id,
                       to_addr=f"{callee_addr[0]}:{callee_addr[1]}",
                       has_sdp=bool(rewritten_sdp))
            
            self._send_response(ack_to_callee, callee_addr)
            
            logger.info("ack_sent",
                       call_id=call_id,
                       to_addr=f"{callee_addr[0]}:{callee_addr[1]}")
            
            call_info['state'] = 'active'
            
            logger.info("call_established",
                       caller=call_info['caller_username'],
                       callee=call_info['callee_username'],
                       call_id=call_id)
        except Exception as e:
            logger.error("ack_handling_error",
                        call_id=call_id if 'call_id' in locals() else "unknown",
                        error=str(e),
                        exc_info=True)
    
    async def _start_rtp_relay(self, call_id: str) -> bool:
        """RTP Relay 시작 (비동기)
        
        Args:
            call_id: Call-ID
            
        Returns:
            성공 여부 (True: 성공, False: 실패)
        """
        try:
            # ✅ 이미 RTP Relay가 실행 중인지 체크 (200 OK 재전송 대응)
            if call_id in self._rtp_workers:
                logger.info("rtp_relay_already_running", call_id=call_id)
                return True
            
            logger.debug("starting_rtp_relay", call_id=call_id)
            media_session = self.media_session_manager.get_session(call_id)
            logger.debug("media_session_check", call_id=call_id, found=media_session is not None)
            
            if not media_session:
                logger.error("media_session_not_found_for_rtp", call_id=call_id)
                return False
            
            # Caller/Callee SDP 정보 확인
            logger.debug("sdp_info_check",
                        call_id=call_id,
                        caller_ip=media_session.caller_leg.original_ip,
                        caller_port=media_session.caller_leg.original_audio_port,
                        callee_ip=media_session.callee_leg.original_ip,
                        callee_port=media_session.callee_leg.original_audio_port)
            
            # Caller SDP 체크 (필수)
            if not media_session.caller_leg.original_ip or not media_session.caller_leg.original_audio_port:
                logger.error("caller_sdp_info_missing", call_id=call_id)
                return False
            
            # Caller Endpoint 정보 (SDP에서 가져온 원본 IP/Port)
            caller_rtp_endpoint = RTPEndpoint(
                ip=media_session.caller_leg.original_ip,
                port=media_session.caller_leg.original_audio_port
            )
            
            # Callee Endpoint: 200 OK 이전이면 Dummy 사용 (Early Bind)
            # Callee SDP가 없어도 진행 가능 (Early Bind 지원)
            if media_session.callee_leg.original_ip and media_session.callee_leg.original_audio_port:
                callee_rtp_endpoint = RTPEndpoint(
                    ip=media_session.callee_leg.original_ip,
                    port=media_session.callee_leg.original_audio_port
                )
                is_early_bind = False
                logger.debug("callee_sdp_available",
                           call_id=call_id,
                           callee_ip=media_session.callee_leg.original_ip,
                           callee_port=media_session.callee_leg.original_audio_port)
            else:
                # Dummy endpoint (나중에 update_callee_endpoint로 업데이트)
                callee_rtp_endpoint = RTPEndpoint(ip="0.0.0.0", port=0)
                is_early_bind = True
                logger.info("early_bind_mode_using_dummy_callee", call_id=call_id)
            
            logger.debug("creating_rtp_worker", call_id=call_id)
            
            # 🎙️ 녹음 활성화: CallManager의 sip_recorder 사용
            sip_recorder = self._call_manager.sip_recorder if self._call_manager else None
            
            # RTP 소켓 bind IP 가져오기
            # 1. config.yaml의 media.rtp_bind_ip 우선
            # 2. 없으면 advertised_ip 사용
            rtp_bind_ip = getattr(self.config.media, 'rtp_bind_ip', None)
            source = "config"
            if not rtp_bind_ip or rtp_bind_ip == "":
                rtp_bind_ip = self._get_b2bua_ip()
                source = "advertised_ip"
            
            logger.info("rtp_bind_ip_selected", 
                       bind_ip=rtp_bind_ip,
                       source=source,
                       call_id=call_id)
            
            # RTP Relay Worker 생성 (녹음 포함)
            rtp_worker = RTPRelayWorker(
                media_session=media_session,
                caller_endpoint=caller_rtp_endpoint,
                callee_endpoint=callee_rtp_endpoint,
                bind_ip=rtp_bind_ip,  # ✅ 설정 가능한 bind IP
                ai_orchestrator=None,  # 사용자간 통화는 AI 미사용
                sip_recorder=sip_recorder  # ✅ 녹음 활성화!
            )
            
            logger.debug("starting_rtp_worker", call_id=call_id)
            # RTP Worker 시작
            try:
                await rtp_worker.start()
                logger.info("rtp_worker_started_successfully", call_id=call_id)
                
                # 🎙️ 녹음 시작 (sip_recorder가 있으면)
                if sip_recorder:
                    call_info = self._active_calls.get(call_id)
                    if call_info:
                        caller_username = call_info.get('caller_username', 'unknown')
                        callee_username = call_info.get('callee_username', 'unknown')
                        await sip_recorder.start_recording(
                            call_id=call_id,
                            caller_id=caller_username,
                            callee_id=callee_username
                        )
                        logger.info("recording_started",
                                   call_id=call_id,
                                   caller=caller_username,
                                   callee=callee_username)
                
            except Exception as e:
                logger.error("rtp_worker_start_failed", call_id=call_id, error=str(e), exc_info=True)
                return False
            
            # Worker 저장 (종료 시 cleanup)
            self._rtp_workers[call_id] = rtp_worker
            
            logger.info("rtp_relay_started",
                       call_id=call_id,
                       caller_endpoint=str(caller_rtp_endpoint),
                       callee_endpoint=str(callee_rtp_endpoint),
                       b2bua_ports_caller=media_session.caller_leg.allocated_ports[:2],
                       b2bua_ports_callee=media_session.callee_leg.allocated_ports[:2])
            
            return True
                
        except Exception as rtp_err:
            logger.error("rtp_relay_start_error", call_id=call_id, error=str(rtp_err), exc_info=True)
            import traceback
            traceback.print_exc()
            return False
    
    async def _handle_bye(self, request: str, addr: tuple) -> None:
        """BYE 처리 (세션 종료)
        
        Args:
            request: BYE 요청
            addr: 송신자 주소
        """
        try:
            call_id = self._extract_header(request, 'Call-ID')
            
            logger.info("bye_received", call_id=call_id, from_addr=f"{addr[0]}:{addr[1]}")
            
            # ⭐ B2BUA Call-ID 매핑 확인 (착신→서버 BYE 처리를 위해)
            # call_id가 _active_calls에 없으면 call_mapping을 통해 원본 call_id 찾기
            if call_id not in self._active_calls:
                # Call mapping 확인 (B2BUA call_id → original call_id)
                mapped_call_id = None
                for orig_id, mapped_id in self._call_mapping.items():
                    if mapped_id == call_id:
                        mapped_call_id = orig_id
                        logger.info("bye_call_id_mapped", 
                                   received_call_id=call_id,
                                   mapped_to=orig_id)
                        call_id = orig_id  # ⭐ 원본 call_id로 변경
                        break
                
                # 여전히 없으면 unknown call
                if call_id not in self._active_calls:
                    logger.warning("bye_unknown_call", 
                                  call_id=call_id,
                                  active_calls=list(self._active_calls.keys()),
                                  call_mapping=dict(self._call_mapping))
                    # 그래도 200 OK는 보내줘야 함
                via = self._extract_header(request, 'Via')
                from_hdr = self._extract_header(request, 'From')
                to_hdr = self._extract_header(request, 'To')
                cseq = self._extract_header(request, 'CSeq')
                
                bye_response = (
                    "SIP/2.0 200 OK\r\n"
                    f"Via: {via}\r\n"
                    f"From: {from_hdr}\r\n"
                    f"To: {to_hdr}\r\n"
                    f"Call-ID: {call_id}\r\n"
                    f"CSeq: {cseq}\r\n"
                    "Content-Length: 0\r\n"
                    "\r\n"
                )
                self._send_response(bye_response, addr)
                return
            
            call_info = self._active_calls[call_id]
            logger.info("bye_received", call_id=call_id)
            
            # ★ Outbound 콜 BYE 처리 - 착신자가 끊음
            if call_info.get('is_outbound') and hasattr(self, '_outbound_manager') and self._outbound_manager:
                logger.info("outbound_callee_bye", call_id=call_id)
                # 200 OK 응답
                via = self._extract_header(request, 'Via')
                from_hdr_bye = self._extract_header(request, 'From')
                to_hdr_bye = self._extract_header(request, 'To')
                cseq_bye = self._extract_header(request, 'CSeq')
                bye_resp = (
                    "SIP/2.0 200 OK\r\n"
                    f"Via: {via}\r\n"
                    f"From: {from_hdr_bye}\r\n"
                    f"To: {to_hdr_bye}\r\n"
                    f"Call-ID: {call_id}\r\n"
                    f"CSeq: {cseq_bye}\r\n"
                    "Content-Length: 0\r\n"
                    "\r\n"
                )
                self._send_response(bye_resp, addr)
                await self._outbound_manager.on_bye_received(call_id)
                # 정리
                self._active_calls.pop(call_id, None)
                self._call_mapping.pop(call_id, None)
                return
            
            # ★ Transfer 상태 체크 - 전환 중이면 TransferManager에 위임
            if self._transfer_manager:
                is_transfer_leg = call_info.get('is_transfer', False)
                
                if is_transfer_leg:
                    # Transfer 레그에서 BYE (착신자가 끊음)
                    logger.info("transfer_leg_bye", call_id=call_id)
                    await self._transfer_manager.on_bye_received(call_id, initiator="callee")
                elif self._transfer_manager.is_transfer_active(call_id):
                    # 원래 호에서 BYE (발신자가 전환 중 끊음)
                    logger.info("transfer_caller_bye", call_id=call_id)
                    # 200 OK 먼저 보내기
                    via = self._extract_header(request, 'Via')
                    from_hdr_bye = self._extract_header(request, 'From')
                    to_hdr_bye = self._extract_header(request, 'To')
                    cseq_bye = self._extract_header(request, 'CSeq')
                    bye_resp = (
                        "SIP/2.0 200 OK\r\n"
                        f"Via: {via}\r\n"
                        f"From: {from_hdr_bye}\r\n"
                        f"To: {to_hdr_bye}\r\n"
                        f"Call-ID: {call_id}\r\n"
                        f"CSeq: {cseq_bye}\r\n"
                        "Content-Length: 0\r\n"
                        "\r\n"
                    )
                    self._send_response(bye_resp, addr)
                    await self._transfer_manager.on_bye_received(call_id, initiator="caller")
                    await self._cleanup_call(call_id)
                    return
            
            # ✅ AI 모드 체크
            is_ai_mode = call_info.get('ai_mode_activated', False)
            
            # 200 OK 응답
            via = self._extract_header(request, 'Via')
            from_hdr = self._extract_header(request, 'From')
            to_hdr = self._extract_header(request, 'To')
            cseq = self._extract_header(request, 'CSeq')
            
            bye_response = (
                "SIP/2.0 200 OK\r\n"
                f"Via: {via}\r\n"
                f"From: {from_hdr}\r\n"
                f"To: {to_hdr}\r\n"
                f"Call-ID: {call_id}\r\n"
                f"CSeq: {cseq}\r\n"
                "Content-Length: 0\r\n"
                "\r\n"
            )
            self._send_response(bye_response, addr)
            logger.info("bye_response_sent", call_id=call_id)
            
            # 원본 Call-ID 가져오기 (MediaSession cleanup용)
            original_call_id = call_info.get('original_call_id', call_id)
            
            # ✅ AI 모드일 때는 상대방에게 BYE를 relay하지 않음
            if is_ai_mode:
                logger.info("bye_not_relayed_ai_mode",
                           call_id=call_id,
                           ai_mode=True)
                
                # AI 세션 정리만 수행
                logger.info("bye_cleanup_triggered", 
                           call_id=original_call_id,
                           reason="BYE received in AI mode")
                await self._cleanup_call(original_call_id)
                return
            
            # 상대방을 결정 (From tag를 기반으로)
            from_tag = self._extract_tag(from_hdr)
            is_from_caller = (from_tag == call_info.get('caller_tag'))
            
            logger.debug("bye_source_check",
                        call_id=call_id,
                        is_from_caller=is_from_caller,
                        caller_tag=call_info.get('caller_tag'),
                        from_tag=from_tag)
            
            # 상대방에게 BYE 전달
            if is_from_caller:
                logger.debug("forwarding_bye", direction="caller_to_callee", callee=call_info['callee_username'])
                # Caller가 BYE를 보냈으므로 Callee에게 전달
                other_call_id = call_info['b2bua_call_id'] if call_id == original_call_id else original_call_id
                other_addr = call_info['callee_addr']
                other_username = call_info['callee_username']
                # B2BUA가 Callee에게 보낸 INVITE의 From tag 사용
                from_username = call_info['caller_username']
                from_tag = call_info.get('b2bua_from_tag', 'b2bua')
                to_tag = call_info.get('callee_tag', '')
            else:
                logger.debug("forwarding_bye", direction="callee_to_caller", caller=call_info['caller_username'])
                # Callee가 BYE를 보냈으므로 Caller에게 전달
                other_call_id = original_call_id if call_id == call_info['b2bua_call_id'] else call_info['b2bua_call_id']
                other_addr = call_info['caller_addr']
                other_username = call_info['caller_username']
                # B2BUA가 Caller에게 보낸 응답의 To tag 사용 (원본 INVITE의 From tag)
                from_username = call_info['callee_username']
                from_tag = call_info.get('callee_tag', 'b2bua')
                to_tag = call_info.get('caller_tag', '')
            
            # B2BUA IP 가져오기 (SDP c= 라인용)
            b2bua_ip = self._get_b2bua_ip()
            
            to_tag_str = f";tag={to_tag}" if to_tag else ""
            
            bye_to_other = (
                f"BYE sip:{other_username}@{other_addr[0]}:{other_addr[1]} SIP/2.0\r\n"
                f"Via: SIP/2.0/UDP {b2bua_ip}:{self.config.sip.listen_port};branch=z9hG4bK{random.randint(100000, 999999)}\r\n"
                f"From: <sip:{from_username}@{b2bua_ip}>;tag={from_tag}\r\n"
                f"To: <sip:{other_username}@{b2bua_ip}>{to_tag_str}\r\n"
                f"Call-ID: {other_call_id}\r\n"
                "CSeq: 2 BYE\r\n"
                "Max-Forwards: 70\r\n"
                "Content-Length: 0\r\n"
                "\r\n"
            )
            self._send_response(bye_to_other, other_addr)
            logger.info("bye_forwarded",
                       to=other_username,
                       to_addr=f"{other_addr[0]}:{other_addr[1]}",
                       other_call_id=other_call_id)
            
            # BYE Transaction Timer 시작
            bye_transaction_id = f"bye-{other_call_id}"
            call_info['bye_transaction_id'] = bye_transaction_id
            
            await self._transaction_timer.start_bye_transaction(
                transaction_id=bye_transaction_id,
                timeout_callback=lambda tid: asyncio.create_task(self._handle_bye_timeout(tid)),
                timeout_seconds=self.config.sip.timers.bye_timeout
            )
            logger.info("bye_transaction_started",
                       transaction_id=bye_transaction_id,
                       timeout=self.config.sip.timers.bye_timeout)
            
            # ⭐ BYE 수신 측 cleanup (즉시 실행)
            # BYE를 보낸 쪽은 이미 통화를 종료했으므로, 
            # 우리도 즉시 세션을 정리해야 recording이 저장됨
            logger.info("bye_cleanup_triggered", 
                       call_id=original_call_id,
                       reason="BYE received, initiating cleanup")
            await self._cleanup_call(original_call_id)
            
        except Exception as e:
            logger.error("bye_handling_error", error=str(e), exc_info=True)

    async def send_bye_to_caller(self, call_id: str) -> bool:
        """
        서버에서 발신자(caller)에게 BYE를 보내 통화를 종료한다.
        HITL timeout 등으로 AI가 통화를 끝낼 때 사용.
        """
        call_info = self._active_calls.get(call_id)
        if not call_info:
            logger.warning("send_bye_to_caller_no_call", call_id=call_id)
            return False
        caller_addr = call_info.get('caller_addr')
        caller_username = call_info.get('caller_username')
        caller_tag = call_info.get('caller_tag', '')
        callee_tag = call_info.get('callee_tag', 'b2bua')
        if not caller_addr or not caller_username:
            logger.warning("send_bye_to_caller_missing_info", call_id=call_id)
            return False
        b2bua_ip = self._get_b2bua_ip()
        to_tag_str = f";tag={caller_tag}" if caller_tag else ""
        bye_msg = (
            f"BYE sip:{caller_username}@{caller_addr[0]}:{caller_addr[1]} SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP {b2bua_ip}:{self.config.sip.listen_port};branch=z9hG4bK{random.randint(100000, 999999)}\r\n"
            f"From: <sip:{call_info.get('callee_username', '')}@{b2bua_ip}>;tag={callee_tag}\r\n"
            f"To: <sip:{caller_username}@{b2bua_ip}>{to_tag_str}\r\n"
            f"Call-ID: {call_id}\r\n"
            "CSeq: 2 BYE\r\n"
            "Max-Forwards: 70\r\n"
            "Content-Length: 0\r\n"
            "\r\n"
        )
        self._send_response(bye_msg, caller_addr)
        logger.info("bye_sent_to_caller", call_id=call_id, reason="server_initiated")
        await self._cleanup_call(call_id)
        return True
    
    async def _handle_cancel(self, request: str, addr: tuple) -> None:
        """CANCEL 처리
        
        Args:
            request: CANCEL 요청
            addr: 송신자 주소
        """
        call_id = self._extract_header(request, 'Call-ID')
        
        logger.info("cancel_received", call_id=call_id)
        
        # 200 OK 응답
        via = self._extract_header(request, 'Via')
        from_hdr = self._extract_header(request, 'From')
        to_hdr = self._extract_header(request, 'To')
        cseq = self._extract_header(request, 'CSeq')
        
        cancel_response = (
            "SIP/2.0 200 OK\r\n"
            f"Via: {via}\r\n"
            f"From: {from_hdr}\r\n"
            f"To: {to_hdr}\r\n"
            f"Call-ID: {call_id}\r\n"
            f"CSeq: {cseq}\r\n"
            "Content-Length: 0\r\n"
            "\r\n"
        )
        self._send_response(cancel_response, addr)
        
        # 세션 정리
        if call_id in self._active_calls:
            call_info = self._active_calls[call_id]
            original_call_id = call_info.get('original_call_id', call_id)
            asyncio.create_task(self._cleanup_call(original_call_id))
    
    async def _cleanup_call(self, call_id: str) -> None:
        """통화 세션 정리
        
        Args:
            call_id: 통화 ID (원본 Call-ID)
        """
        if call_id not in self._active_calls:
            logger.debug("cleanup_call_already_cleaned", call_id=call_id)
            return
        
        # ⭐ Race condition 방지: 즉시 _active_calls에서 제거
        call_info = self._active_calls.pop(call_id)
        new_call_id = call_info.get('b2bua_call_id')
        
        # ✅ B2BUA Call-ID도 제거
        if new_call_id:
            self._active_calls.pop(new_call_id, None)
        
        # ✅ 원본 Call-ID 확인 (RTP Worker, 녹음은 원본 Call-ID로 저장됨)
        original_call_id = call_info.get('original_call_id', call_id)
        
        logger.info("cleanup_call_start", call_id=call_id, original_call_id=original_call_id, b2bua_call_id=new_call_id)

        # 대시보드 실시간 통화: Repository에서 제거 (활성 목록에서 사라지도록)
        if self.call_manager:
            self.call_manager.remove_b2bua_call(original_call_id)
        # WebSocket: B2BUA 통화 종료 이벤트 (대시보드에서 카드 제거)
        try:
            from src.websocket import manager as ws_manager
            asyncio.create_task(ws_manager.emit_call_ended(original_call_id))
        except Exception as e:
            logger.warning("b2bua_call_ended_ws_failed", call_id=original_call_id, error=str(e))
        
        # 🎙️ 녹음 중지 (CDR 작성 전에 먼저 중지)
        recording_metadata = None
        sip_recorder = self._call_manager.sip_recorder if self._call_manager else None
        if sip_recorder:
            try:
                # ✅ 원본 Call-ID로 녹음 중지
                recording_metadata = await sip_recorder.stop_recording(original_call_id)
                if recording_metadata:
                    logger.info("recording_stopped",
                               call_id=original_call_id,
                               recording_file=recording_metadata.get('files', {}).get('mixed'),
                               duration=recording_metadata.get('duration'))
            except Exception as e:
                logger.error("recording_stop_error", call_id=original_call_id, error=str(e))
        
        # Session Timer 취소 (✅ 원본 Call-ID로 취소)
        session_cancelled = await self._session_timer.cancel_timer(original_call_id)
        if session_cancelled:
            logger.info("session_timer_cancelled", call_id=original_call_id)
        else:
            # AI 모드 등에서 session timer가 시작되지 않은 경우 정상적으로 없을 수 있음
            logger.debug("session_timer_not_found", call_id=original_call_id)
        
        # Transaction Timers 취소
        transaction_id = call_info.get('transaction_id')
        bye_transaction_id = call_info.get('bye_transaction_id')
        if transaction_id:
            try:
                await self._transaction_timer.terminate_transaction(transaction_id)
            except Exception as e:
                logger.warning("transaction_cleanup_error", 
                             transaction_id=transaction_id,
                             error=str(e))
        if bye_transaction_id:
            try:
                await self._transaction_timer.terminate_transaction(bye_transaction_id)
            except Exception as e:
                logger.warning("bye_transaction_cleanup_error", 
                             transaction_id=bye_transaction_id,
                             error=str(e))
        
        # CDR 작성 (통화 이력 기록)
        try:
            # 통화 시작/종료 시간 계산
            start_time = call_info.get('start_time', datetime.now())
            end_time = datetime.now()
            
            # start_time이 문자열인 경우 처리
            if isinstance(start_time, str):
                try:
                    start_time = datetime.fromisoformat(start_time)
                except:
                    start_time = datetime.now()
            
            duration_seconds = (end_time - start_time).total_seconds()
            
            caller_uri = f"sip:{call_info.get('caller_username', 'unknown')}@{call_info.get('caller_addr', ['unknown'])[0]}"
            callee_uri = f"sip:{call_info.get('callee_username', 'unknown')}@{call_info.get('callee_addr', ['unknown'])[0]}"
            
            logger.info("cdr_flow_step_1_writing_cdr",
                       call_id=call_id,
                       caller=caller_uri,
                       callee=callee_uri,
                       duration=duration_seconds,
                       message="[CDR Flow] Writing CDR from SIP Endpoint")
            
            cdr = CDR(
                call_id=call_id,
                caller=caller_uri,  # ✅ caller_uri → caller
                callee=callee_uri,  # ✅ callee_uri → callee
                start_time=start_time,
                answer_time=call_info.get('answer_time'),
                end_time=end_time,
                duration=duration_seconds,  # ✅ duration_seconds → duration
                termination_reason=TerminationReason.NORMAL,  # ✅ 문자열 → Enum
                # 🎙️ 녹음 정보 추가
                has_recording=recording_metadata is not None,
                recording_path=recording_metadata.get('files', {}).get('mixed') if recording_metadata else None,
                recording_duration=recording_metadata.get('duration') if recording_metadata else None,
                recording_type=recording_metadata.get('type') if recording_metadata else None,
            )
            
            self._cdr_writer.write_cdr(cdr)
            
            logger.info("cdr_flow_step_2_cdr_written_successfully",
                       call_id=call_id,
                       cdr_file=f"./cdr/cdr-{datetime.now().strftime('%Y-%m-%d')}.jsonl",
                       duration=duration_seconds,
                       message="[CDR Flow] CDR written successfully")
            
        except Exception as e:
            logger.error("cdr_flow_error_cdr_write_failed",
                        call_id=call_id,
                        error=str(e),
                        message="[CDR Flow] CDR write error from SIP Endpoint",
                        exc_info=True)
        
        # RTP Worker 정리 (✅ 원본 Call-ID로 찾기)
        if original_call_id in self._rtp_workers:
            rtp_worker = self._rtp_workers[original_call_id]
            try:
                # RTP Worker 중지 (async)
                await rtp_worker.stop()
                logger.debug("rtp_relay_stopped", call_id=original_call_id)
            except Exception as e:
                logger.error("rtp_worker_stop_error", call_id=original_call_id, error=str(e))
            finally:
                del self._rtp_workers[original_call_id]
        
        # Call mapping 삭제
        if new_call_id:
            self._call_mapping.pop(call_id, None)
            self._call_mapping.pop(new_call_id, None)
        
        # ⭐ Active call은 이미 위에서 삭제됨 (중복 방지)
        
        # ✅ Knowledge Extraction 트리거 (CallManager에 위임)
        # Human-to-human calls only; AI-to-caller calls are excluded.
        if self._call_manager and recording_metadata:
            try:
                recording_dir_name = recording_metadata.get('directory')  # ✅ 'dir_name' → 'directory'
                has_transcript = recording_metadata.get('has_transcript', False)  # ✅ transcript 존재 여부
                # Authoritative: CallManager.ai_enabled_calls, then call_info flags (set on AI takeover / no-answer)
                is_ai_call = (
                    self._call_manager.is_ai_call(original_call_id)
                    or call_info.get('ai_mode_activated', False)
                    or call_info.get('is_ai_call', False)
                )
                
                logger.debug("knowledge_extraction_check",
                            call_id=original_call_id,
                            has_recording_dir=bool(recording_dir_name),
                            has_transcript=has_transcript,
                            is_ai_call=is_ai_call,
                            recording_dir=recording_dir_name)
                
                if recording_dir_name and has_transcript and not is_ai_call:
                    # 일반 SIP 통화 + transcript 존재 시에만 Knowledge Extraction 수행
                    await self._call_manager.trigger_knowledge_extraction(
                        call_id=original_call_id,
                        recording_dir_name=recording_dir_name,
                        callee_username=call_info.get('callee_username', 'unknown')
                    )
                    logger.info("knowledge_extraction_triggered",
                               call_id=original_call_id,
                               recording_dir=recording_dir_name)
                else:
                    skip_reason = "no_recording_dir"
                    if not recording_dir_name:
                        skip_reason = "no_recording_dir"
                    elif not has_transcript:
                        skip_reason = "empty_transcript"
                    elif is_ai_call:
                        skip_reason = "ai_call"
                    
                    logger.info("knowledge_extraction_skipped",
                               call_id=original_call_id,
                               reason=skip_reason)
            except Exception as e:
                logger.error("knowledge_extraction_trigger_error",
                            call_id=original_call_id,
                            error=str(e),
                            exc_info=True)
        
        logger.info("call_cleaned_up", call_id=call_id)
    
    def _extract_header(self, request: str, header_name: str) -> str:
        """SIP 헤더 추출
        
        Args:
            request: SIP 메시지
            header_name: 헤더 이름
            
        Returns:
            str: 헤더 값 (없으면 빈 문자열)
        """
        lines = request.split('\r\n')
        header_lower = header_name.lower()
        
        for line in lines:
            line_stripped = line.strip()
            if not line_stripped:
                continue
            
            # "Header-Name: value" 형식 체크
            if ':' in line_stripped:
                header_part, _, value_part = line_stripped.partition(':')
                if header_part.strip().lower() == header_lower:
                    return value_part.strip()
        
        # 헤더를 찾지 못한 경우 디버그 로그
        logger.debug("header_not_found", header=header_name)
        return ''
    
    def _create_options_response(self, request: str, addr: tuple) -> str:
        """OPTIONS 응답 생성
        
        Args:
            request: 요청 메시지
            addr: 송신자 주소
            
        Returns:
            str: 응답 메시지
        """
        via = self._extract_header(request, 'Via')
        from_hdr = self._extract_header(request, 'From')
        to_hdr = self._extract_header(request, 'To')
        call_id = self._extract_header(request, 'Call-ID')
        cseq = self._extract_header(request, 'CSeq')
        
        return (
            "SIP/2.0 200 OK\r\n"
            f"Via: {via}\r\n"
            f"From: {from_hdr}\r\n"
            f"To: {to_hdr}\r\n"
            f"Call-ID: {call_id}\r\n"
            f"CSeq: {cseq}\r\n"
            "Allow: INVITE, ACK, CANCEL, OPTIONS, BYE, REGISTER\r\n"
            "Accept: application/sdp\r\n"
            "Content-Length: 0\r\n"
            "\r\n"
        )
    
    def _handle_register(self, request: str, addr: tuple) -> str:
        """REGISTER 처리 및 사용자 등록
        
        Args:
            request: 요청 메시지
            addr: 송신자 주소
            
        Returns:
            str: 응답 메시지
        """
        via = self._extract_header(request, 'Via')
        from_hdr = self._extract_header(request, 'From')
        to_hdr = self._extract_header(request, 'To')
        call_id = self._extract_header(request, 'Call-ID')
        cseq = self._extract_header(request, 'CSeq')
        contact = self._extract_header(request, 'Contact')
        expires = self._extract_header(request, 'Expires')
        
        # username 추출
        username = self._extract_username(from_hdr)
        
        # 등록/해제 처리
        if expires == '0':
            # 등록 해제
            if username in self._registered_users:
                del self._registered_users[username]
                logger.info("user_unregistered", username=username, addr=f"{addr[0]}:{addr[1]}")
        else:
            # 등록
            self._registered_users[username] = {
                'ip': addr[0],
                'port': addr[1],
                'contact': contact,
                'from': from_hdr
            }
            logger.info("user_registered",
                       username=username,
                       addr=f"{addr[0]}:{addr[1]}",
                       total_users=len(self._registered_users),
                       registered_users=list(self._registered_users.keys()))
        
        # To 헤더에 tag가 없으면 추가
        if 'tag=' not in to_hdr:
            to_hdr += ';tag=mock-' + call_id[:8]
        
        return (
            "SIP/2.0 200 OK\r\n"
            f"Via: {via}\r\n"
            f"From: {from_hdr}\r\n"
            f"To: {to_hdr}\r\n"
            f"Call-ID: {call_id}\r\n"
            f"CSeq: {cseq}\r\n"
            f"Contact: {contact}\r\n"
            "Expires: 3600\r\n"
            "Content-Length: 0\r\n"
            "\r\n"
        )
    
    async def _handle_invite_b2bua(self, request: str, caller_addr: tuple) -> None:
        """B2BUA INVITE 처리 (완전한 구현)
        
        Args:
            request: INVITE 요청 메시지
            caller_addr: 발신자 주소
        """
        try:
            # 헤더 추출
            via = self._extract_header(request, 'Via')
            from_hdr = self._extract_header(request, 'From')
            to_hdr = self._extract_header(request, 'To')
            call_id = self._extract_header(request, 'Call-ID')
            cseq = self._extract_header(request, 'CSeq')
            contact = self._extract_header(request, 'Contact')
            content_type = self._extract_header(request, 'Content-Type')
            
            # SDP 추출
            sdp = self._extract_sdp_body(request)
            
            # 발신자와 수신자 username 추출
            caller_username = self._extract_username(from_hdr)
            callee_username = self._extract_username(to_hdr)
            
            # From tag 추출
            caller_tag = self._extract_tag(from_hdr)
            
            logger.info("b2bua_invite_received",
                       caller=caller_username,
                       callee=callee_username,
                       call_id=call_id)
            
            # ✅ 중복 INVITE 체크 (재전송 방지)
            if call_id in self._active_calls:
                existing_call = self._active_calls[call_id]
                state = existing_call.get('state', 'unknown')
                
                logger.info("invite_retransmission_detected",
                           call_id=call_id,
                           state=state,
                           caller=caller_username,
                           callee=callee_username)
                
                # 이미 처리 중이면 100 Trying 재전송 (멱등성)
                if state == 'inviting':
                    trying_response = (
                        "SIP/2.0 100 Trying\r\n"
                        f"Via: {via}\r\n"
                        f"From: {from_hdr}\r\n"
                        f"To: {to_hdr}\r\n"
                        f"Call-ID: {call_id}\r\n"
                        f"CSeq: {cseq}\r\n"
                        "Content-Length: 0\r\n"
                        "\r\n"
                    )
                    self._send_response(trying_response, caller_addr)
                
                # 중복 요청은 더 이상 처리하지 않음
                return
            
            # 수신자가 등록되어 있는지 확인
            if callee_username not in self._registered_users:
                logger.warning("callee_not_found", callee=callee_username, caller=caller_username)
                
                response = (
                    "SIP/2.0 404 Not Found\r\n"
                    f"Via: {via}\r\n"
                    f"From: {from_hdr}\r\n"
                    f"To: {to_hdr};tag=b2bua-{random.randint(1000, 9999)}\r\n"
                    f"Call-ID: {call_id}\r\n"
                    f"CSeq: {cseq}\r\n"
                    "Content-Length: 0\r\n"
                    "\r\n"
                )
                self._send_response(response, caller_addr)
                return
            
            # 수신자 정보 가져오기
            callee_info = self._registered_users[callee_username]
            callee_addr = (callee_info['ip'], callee_info['port'])
            
            logger.debug("callee_found",
                        callee=callee_username,
                        addr=f"{callee_addr[0]}:{callee_addr[1]}",
                        call_id=call_id)
            
            # 부재중 상태 체크 (웹에서 수동 설정)
            from src.sip_core.operator_status import get_operator_status_manager
            status_manager = get_operator_status_manager()
            
            if status_manager.is_away(callee_username):
                away_message = status_manager.get_away_message(callee_username)
                logger.info("callee_is_away_activating_ai",
                           call_id=call_id,
                           callee=callee_username,
                           away_message=away_message)
                
                # 즉시 AI 모드 활성화
                if self.call_manager:
                    await self.call_manager.handle_no_answer_timeout(call_id, callee_username)
                    # Mark call as AI-handled so knowledge extraction is skipped
                    if call_id in self._active_calls:
                        self._active_calls[call_id]['is_ai_call'] = True
                        self._active_calls[call_id]['ai_mode_activated'] = True
                    logger.info("ai_mode_activated_by_away_status",
                               call_id=call_id,
                               callee=callee_username)
                
                # TODO: AI Voicebot이 응답하도록 처리
                # 현재는 정상 호 처리를 계속 진행 (추후 분기 처리 필요)
            
            # 새로운 Call-ID 생성 (B2BUA leg)
            new_call_id = f"b2bua-{random.randint(100000, 999999)}-{call_id[:8]}"
            new_tag = f"b2bua-{random.randint(1000, 9999)}"
            
            # Extract original Via branch (매우 중요 - ACK를 받기 위해 필요!)
            via_branch = None
            via_match = re.search(r'branch=([^;,\s]+)', via)
            if via_match:
                via_branch = via_match.group(1)
            
            # ✅ Via 헤더 전체도 저장 (200 OK 응답용)
            original_via = via.strip()
            
            # Call mapping 저장
            self._call_mapping[call_id] = new_call_id
            self._call_mapping[new_call_id] = call_id  # 양방향
            
            # Active call 정보 저장
            call_info = {
                'original_call_id': call_id,  # 원본 Call-ID (cleanup용)
                'caller_username': caller_username,
                'callee_username': callee_username,
                'caller_addr': caller_addr,
                'callee_addr': callee_addr,
                'caller_tag': caller_tag,
                'callee_tag': None,  # 나중에 200 OK에서 설정
                'b2bua_from_tag': new_tag,  # B2BUA가 callee에게 보낸 INVITE의 From tag
                'b2bua_call_id': new_call_id,
                'original_from': from_hdr,
                'original_to': to_hdr,
                'original_via': original_via,  # ✅ Via 헤더 전체 (200 OK 응답용)
                'original_via_branch': via_branch,  # ACK 수신을 위해 필수!
                'original_cseq': cseq,  # ✅ 원본 INVITE의 CSeq 저장 (RFC 3261 준수)
                'sdp': sdp,
                'state': 'inviting',
                'start_time': datetime.now(),  # CDR용 통화 시작 시간
                'answer_time': None,  # 200 OK 시점에 설정
            }
            self._active_calls[call_id] = call_info
            # B2BUA Call-ID로도 접근 가능하도록
            self._active_calls[new_call_id] = call_info

            # 대시보드 실시간 통화 목록: CallManager Repository에 등록 (GET /api/calls/active)
            if self.call_manager:
                from_uri = f"sip:{caller_username}@{caller_addr[0]}"
                to_uri = f"sip:{callee_username}@{callee_addr[0]}"
                self.call_manager.register_b2bua_call(call_id, from_uri, to_uri)
            
            logger.info("b2bua_call_setup",
                       caller=caller_username,
                       callee=callee_username,
                       original_call_id=call_id,
                       new_call_id=new_call_id)
            
            logger.debug("creating_b2bua_leg", new_call_id=new_call_id, original_call_id=call_id)
            
            # 📡 MediaSession 생성 및 포트 할당
            logger.debug("creating_media_session", call_id=call_id, sdp_exists=sdp is not None)
            if sdp:
                logger.debug("sdp_info",
                           call_id=call_id,
                           sdp_length=len(sdp),
                           sdp_preview=sdp[:200] if len(sdp) > 200 else sdp)
            
            media_session = self.media_session_manager.create_session(
                call_id=call_id,
                caller_sdp=sdp,
                mode=None  # 기본 모드 사용
            )
            
            logger.info("media_session_created",
                       call_id=call_id,
                       caller_audio_port=media_session.caller_leg.get_audio_rtp_port(),
                       callee_audio_port=media_session.callee_leg.get_audio_rtp_port(),
                       caller_original_ip=media_session.caller_leg.original_ip,
                       caller_original_port=media_session.caller_leg.original_audio_port,
                       caller_allocated_ports=media_session.caller_leg.allocated_ports,
                       callee_allocated_ports=media_session.callee_leg.allocated_ports)
            
            # 발신자에게 100 Trying 전송
            trying_response = (
                "SIP/2.0 100 Trying\r\n"
                f"Via: {via}\r\n"
                f"From: {from_hdr}\r\n"
                f"To: {to_hdr}\r\n"
                f"Call-ID: {call_id}\r\n"
                f"CSeq: {cseq}\r\n"
                "Content-Length: 0\r\n"
                "\r\n"
            )
            self._send_response(trying_response, caller_addr)
            
            # 수신자에게 INVITE 전달
            # 실제 IP 가져오기 (0.0.0.0이면 네트워크 인터페이스 IP 사용)
            b2bua_ip = self.config.sip.listen_ip
            if b2bua_ip == "0.0.0.0":
                # Callee 주소로부터 적절한 IP 추론
                b2bua_ip = callee_addr[0].split('.')[0:3]  # 같은 네트워크 추정
                b2bua_ip = '.'.join(b2bua_ip) + '.233'  # 임시로 .233 사용
                # 더 나은 방법: socket.gethostbyname(socket.gethostname())
                import socket
                try:
                    b2bua_ip = socket.gethostbyname(socket.gethostname())
                except:
                    b2bua_ip = "127.0.0.1"
            
            new_via = f"SIP/2.0/UDP {b2bua_ip}:{self.config.sip.listen_port};branch=z9hG4bK{random.randint(100000, 999999)}"
            new_from = f"<sip:{caller_username}@{b2bua_ip}>;tag={new_tag}"
            new_to = f"<sip:{callee_username}@{b2bua_ip}>"
            new_contact = f"<sip:{caller_username}@{b2bua_ip}:{self.config.sip.listen_port}>"
            
            # ✅ B2BUA가 callee에게 보내는 INVITE 정보를 call_info에 저장 (CANCEL용)
            call_info['b2bua_via'] = new_via
            call_info['b2bua_from'] = new_from
            call_info['b2bua_to'] = new_to
            call_info['b2bua_cseq'] = "1 INVITE"  # B2BUA → Callee INVITE의 CSeq
            
            # 📝 SDP Rewrite - B2BUA IP/Port로 교체
            content_type_header = ""
            content_length_header = ""
            invite_body = ""
            
            if sdp:
                # Direct 모드: SDP 그대로 전달 (단말간 직접 RTP 통신)
                if media_session.mode == MediaMode.DIRECT:
                    rewritten_sdp = sdp
                    logger.info("invite_sdp_direct_mode", call_id=call_id)
                else:
                    # Bypass/Reflecting 모드: SDP 수정 (B2BUA가 RTP 중계)
                    logger.debug("rewriting_sdp",
                               call_id=call_id,
                               b2bua_ip=b2bua_ip,
                               callee_audio_port=media_session.callee_leg.get_audio_rtp_port())
                    
                    # 🐛 DEBUG: 원본 SDP 확인
                    logger.info("sdp_rewrite_original", 
                               call_id=call_id,
                               original_length=len(sdp),
                               original_lines=len(sdp.split('\n')),
                               has_rtcp_fb=("rtcp-fb" in sdp))
                    
                    # 1. 벤더 특정 속성 제거 (a=X-* 등)
                    rewritten_sdp = SDPManipulator.remove_vendor_attributes(sdp)
                    logger.info("sdp_after_vendor_removal",
                               call_id=call_id,
                               length=len(rewritten_sdp),
                               has_rtcp_fb=("rtcp-fb" in rewritten_sdp))
                    
                    # 2. Origin IP를 B2BUA IP로 교체 (o= 라인)
                    rewritten_sdp = SDPManipulator.replace_origin_ip(rewritten_sdp, b2bua_ip)
                    logger.info("sdp_after_origin_replacement",
                               call_id=call_id,
                               length=len(rewritten_sdp),
                               has_rtcp_fb=("rtcp-fb" in rewritten_sdp))
                    
                    # 3. Connection IP를 B2BUA IP로 교체 (c= 라인)
                    rewritten_sdp = SDPManipulator.replace_connection_ip(rewritten_sdp, b2bua_ip)
                    logger.info("sdp_after_connection_replacement",
                               call_id=call_id,
                               length=len(rewritten_sdp),
                               has_rtcp_fb=("rtcp-fb" in rewritten_sdp))
                    
                    # 4. Audio 포트를 Callee Leg 할당 포트로 교체
                    callee_audio_port = media_session.callee_leg.get_audio_rtp_port()
                    callee_audio_rtcp_port = media_session.callee_leg.get_audio_rtcp_port()
                    
                    if callee_audio_port:
                        rewritten_sdp = SDPManipulator.replace_media_port(rewritten_sdp, "audio", callee_audio_port)
                        logger.info("sdp_after_media_port_replacement",
                                   call_id=call_id,
                                   length=len(rewritten_sdp),
                                   has_rtcp_fb=("rtcp-fb" in rewritten_sdp),
                                   o=b2bua_ip,
                                   c=b2bua_ip,
                                   m_audio=callee_audio_port)
                    
                    # 5. RTCP 포트를 SHORT FORMAT으로 변경 (원본 SDP에 a=rtcp:가 있는 경우만)
                    if callee_audio_rtcp_port and SDPManipulator.has_rtcp_attribute(sdp, "audio"):
                        rewritten_sdp = SDPManipulator.replace_rtcp_attribute(rewritten_sdp, "audio", callee_audio_rtcp_port, b2bua_ip)
                        logger.info("sdp_after_rtcp_replacement",
                                   call_id=call_id,
                                   length=len(rewritten_sdp),
                                   has_rtcp_fb=("rtcp-fb" in rewritten_sdp),
                                   rtcp_port=callee_audio_rtcp_port)
                    
                    # TODO: Video 지원 시 video 포트도 교체
                
                content_type_header = f"Content-Type: application/sdp\r\n"
                content_length_header = f"Content-Length: {len(rewritten_sdp)}\r\n"
                invite_body = f"\r\n{rewritten_sdp}"
            else:
                content_length_header = "Content-Length: 0\r\n"
            
            invite_to_callee = (
                f"INVITE sip:{callee_username}@{callee_addr[0]}:{callee_addr[1]} SIP/2.0\r\n"
                f"Via: {new_via}\r\n"
                f"From: {new_from}\r\n"
                f"To: {new_to}\r\n"
                f"Call-ID: {new_call_id}\r\n"
                f"CSeq: 1 INVITE\r\n"
                f"Contact: {new_contact}\r\n"
                "Max-Forwards: 70\r\n"
                "User-Agent: SIP-PBX-B2BUA/1.0\r\n"
                f"{content_type_header}"
                f"{content_length_header}"
                f"{invite_body}"
            )
            
            logger.debug("forwarding_invite_to_callee",
                        call_id=call_id,
                        callee=callee_username,
                        callee_addr=f"{callee_addr[0]}:{callee_addr[1]}")
            self._send_response(invite_to_callee, callee_addr)
            
            # 🚀 Early Bind: INVITE 전송 직후 RTP 소켓 bind (타이밍 문제 해결)
            logger.info("early_bind_starting", call_id=call_id, action="before_200_ok")
            rtp_bind_success = await self._start_rtp_relay(call_id)
            if rtp_bind_success:
                logger.info("early_bind_success", call_id=call_id)
            else:
                logger.warning("early_bind_failed", call_id=call_id)
            
            # Transaction Timer 시작 (INVITE 재전송 및 타임아웃)
            transaction_id = f"invite-{new_call_id}"
            call_info['transaction_id'] = transaction_id
            call_info['invite_message'] = invite_to_callee  # 재전송용
            call_info['callee_addr_for_retransmit'] = callee_addr  # 재전송 대상
            
            await self._transaction_timer.start_invite_transaction(
                transaction_id=transaction_id,
                retransmit_callback=lambda tid: self._retransmit_invite(tid),
                timeout_callback=lambda tid: asyncio.create_task(self._handle_invite_timeout(tid))
            )
            
            logger.info("invite_transaction_started",
                       transaction_id=transaction_id,
                       call_id=call_id,
                       new_call_id=new_call_id)
            
            # no_answer_timeout 타이머 시작 (AI 응대 모드용)
            no_answer_timeout = self.config.sip.timers.no_answer_timeout
            if no_answer_timeout > 0:
                async def delayed_no_answer_check():
                    await asyncio.sleep(no_answer_timeout)
                    await self._handle_no_answer_timeout(call_id)
                
                no_answer_task = asyncio.create_task(delayed_no_answer_check())
                call_info['no_answer_timer'] = no_answer_task
                
                logger.info("no_answer_timer_started",
                           call_id=call_id,
                           timeout=no_answer_timeout)
            
            logger.info("b2bua_call_setup_in_progress",
                       call_id=call_id,
                       transaction_timeout=f"{64 * self.config.sip.timers.t1}s",
                       no_answer_timeout=f"{no_answer_timeout}s" if no_answer_timeout > 0 else None)
            
        except Exception as e:
            logger.error("b2bua_invite_error", error=str(e), exc_info=True)
    
    def _create_not_implemented_response(self, request: str, addr: tuple) -> str:
        """501 Not Implemented 응답 생성
        
        Args:
            request: 요청 메시지
            addr: 송신자 주소
            
        Returns:
            str: 응답 메시지
        """
        via = self._extract_header(request, 'Via')
        from_hdr = self._extract_header(request, 'From')
        to_hdr = self._extract_header(request, 'To')
        call_id = self._extract_header(request, 'Call-ID')
        cseq = self._extract_header(request, 'CSeq')
        
        return (
            "SIP/2.0 501 Not Implemented\r\n"
            f"Via: {via}\r\n"
            f"From: {from_hdr}\r\n"
            f"To: {to_hdr}\r\n"
            f"Call-ID: {call_id}\r\n"
            f"CSeq: {cseq}\r\n"
            "Content-Length: 0\r\n"
            "\r\n"
        )
    
    async def _listen_loop(self) -> None:
        """UDP 소켓 리스닝 루프"""
        import asyncio
        import socket
        import time
        
        try:
            # UDP 소켓 생성
            bind_start = time.time()
            logger.debug("udp_socket_binding",
                        listen_ip=self.config.sip.listen_ip,
                        listen_port=self.config.sip.listen_port)
            
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._socket.bind((self.config.sip.listen_ip, self.config.sip.listen_port))
            self._socket.setblocking(False)
            
            bind_elapsed = time.time() - bind_start
            logger.info("udp_socket_bound",
                       listen_ip=self.config.sip.listen_ip,
                       listen_port=self.config.sip.listen_port,
                       bind_time=f"{bind_elapsed:.3f}s")
            
            loop = asyncio.get_event_loop()
            
            while self._running:
                try:
                    # Non-blocking receive
                    data, addr = await loop.sock_recvfrom(self._socket, 65535)
                    asyncio.create_task(self._handle_sip_message(data, addr))
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error("socket_receive_error", error=str(e))
                    await asyncio.sleep(0.1)
                    
        except Exception as e:
            logger.error("sip_listen_error", error=str(e))
        finally:
            if self._socket:
                self._socket.close()
    
    def start(self) -> None:
        """SIP B2BUA 서버 시작"""
        import asyncio
        
        self._running = True
        
        # asyncio 이벤트 루프 가져오기
        try:
            loop = asyncio.get_running_loop()
            self._listen_task = loop.create_task(self._listen_loop())
        except RuntimeError:
            # 이벤트 루프가 없으면 나중에 시작될 것임
            logger.warning("no_event_loop", 
                          message="Event loop not running, socket will not bind")
        
        logger.info("sip_server_started",
                   listen_ip=self.config.sip.listen_ip,
                   listen_port=self.config.sip.listen_port)
    
    def _retransmit_invite(self, transaction_id: str) -> None:
        """INVITE 재전송 (Transaction Timer 콜백)
        
        Args:
            transaction_id: 트랜잭션 ID
        """
        try:
            # transaction_id로 call_info 찾기
            call_info = None
            for cid, info in self._active_calls.items():
                if info.get('transaction_id') == transaction_id:
                    call_info = info
                    break
            
            if not call_info:
                logger.warning("retransmit_invite_no_call", transaction_id=transaction_id)
                return
            
            invite_message = call_info.get('invite_message')
            callee_addr = call_info.get('callee_addr_for_retransmit')
            
            if invite_message and callee_addr:
                self._send_response(invite_message, callee_addr)
                logger.info("invite_retransmitted",
                           transaction_id=transaction_id,
                           call_id=call_info.get('original_call_id'))
            
        except Exception as e:
            logger.error("retransmit_invite_error",
                        transaction_id=transaction_id,
                        error=str(e))
    
    async def _handle_bye_timeout(self, transaction_id: str) -> None:
        """BYE 타임아웃 처리 (Transaction Timer 콜백)
        
        Args:
            transaction_id: 트랜잭션 ID
        """
        try:
            # transaction_id로 call_info 찾기
            call_info = None
            original_call_id = None
            for cid, info in self._active_calls.items():
                if info.get('bye_transaction_id') == transaction_id:
                    call_info = info
                    original_call_id = info.get('original_call_id')
                    break
            
            if not call_info:
                logger.warning("bye_timeout_no_call", transaction_id=transaction_id)
                return
            
            logger.warning("bye_timeout",
                          transaction_id=transaction_id,
                          call_id=original_call_id,
                          timeout=self.config.sip.timers.bye_timeout)
            
            # 강제 세션 정리
            if original_call_id:
                await self._cleanup_call(original_call_id)
            
        except Exception as e:
            logger.error("bye_timeout_error",
                        transaction_id=transaction_id,
                        error=str(e),
                        exc_info=True)
    
    async def _send_session_update(self, call_id: str) -> None:
        """세션 갱신 UPDATE 메시지 전송 (Session Timer 콜백)
        
        Args:
            call_id: Call-ID
        """
        try:
            if call_id not in self._active_calls:
                logger.warning("session_update_no_call", call_id=call_id)
                return
            
            call_info = self._active_calls[call_id]
            
            # B2BUA IP 가져오기 (SDP c= 라인용)
            b2bua_ip = self._get_b2bua_ip()
            
            # Caller와 Callee에게 UPDATE 전송 (세션 유지)
            # 실제로는 한쪽(refresher)만 보내면 되지만, 양쪽 모두에게 보내는 것이 안전
            
            # Caller에게 UPDATE
            caller_addr = call_info.get('caller_addr')
            if caller_addr:
                update_to_caller = (
                    f"UPDATE sip:{call_info['caller_username']}@{caller_addr[0]}:{caller_addr[1]} SIP/2.0\r\n"
                    f"Via: SIP/2.0/UDP {b2bua_ip}:{self.config.sip.listen_port};branch=z9hG4bK{random.randint(100000, 999999)}\r\n"
                    f"From: <sip:{call_info['callee_username']}@{b2bua_ip}>;tag={call_info.get('callee_tag', 'b2bua')}\r\n"
                    f"To: <sip:{call_info['caller_username']}@{b2bua_ip}>;tag={call_info.get('caller_tag', '')}\r\n"
                    f"Call-ID: {call_id}\r\n"
                    "CSeq: 3 UPDATE\r\n"
                    f"Session-Expires: {self.config.sip.timers.session_expires};refresher={self.config.sip.timers.session_refresher}\r\n"
                    "Max-Forwards: 70\r\n"
                    "Content-Length: 0\r\n"
                    "\r\n"
                )
                self._send_response(update_to_caller, caller_addr)
                logger.info("session_update_sent",
                           call_id=call_id,
                           to="caller",
                           expires=self.config.sip.timers.session_expires)
            
            logger.debug("session_update_sent", call_id=call_id)
            
        except Exception as e:
            logger.error("session_update_error",
                        call_id=call_id,
                        error=str(e),
                        exc_info=True)
    
    async def _handle_no_answer_timeout(self, call_id: str) -> None:
        """부재중 타임아웃 처리 (AI 응대 모드 전환)
        
        Args:
            call_id: 호 ID
        """
        try:
            call_info = self._active_calls.get(call_id)
            if not call_info:
                logger.warning("no_answer_timeout_no_call", call_id=call_id)
                return
            
            # 이미 통화 수립됨 (200 OK 받음)
            if call_info.get('state') == 'established':
                logger.info("no_answer_timeout_already_established", call_id=call_id)
                return
            
            # 이미 AI 모드로 전환됨
            if call_info.get('ai_mode_activated'):
                logger.info("no_answer_timeout_already_ai_mode", call_id=call_id)
                return
            
            caller_username = call_info.get('caller_username')
            callee_username = call_info.get('callee_username')
            
            logger.warning("no_answer_timeout_activating_ai",
                          call_id=call_id,
                          callee=callee_username,
                          timeout=self.config.sip.timers.no_answer_timeout)
            
            # B2BUA IP 가져오기
            b2bua_ip = self._get_b2bua_ip()
            listen_port = self.config.sip.listen_port
            
            # 🔄 Step 1: 피착신자에게 CANCEL 전송
            b2bua_call_id = call_info.get('b2bua_call_id')
            callee_addr = call_info.get('callee_addr_for_retransmit')
            
            if b2bua_call_id and callee_addr:
                logger.info("🔄 [AI Takeover] Sending CANCEL to callee",
                           call_id=call_id,
                           b2bua_call_id=b2bua_call_id,
                           callee=callee_username)
                
                # ✅ B2BUA가 callee에게 보낸 INVITE의 정보로 CANCEL 생성
                b2bua_cseq = call_info.get('b2bua_cseq', '1 INVITE')
                cseq_number = b2bua_cseq.split()[0] if ' ' in b2bua_cseq else '1'
                
                b2bua_via = call_info.get('b2bua_via', f"SIP/2.0/UDP {b2bua_ip}:{listen_port};branch=z9hG4bK-cancel")
                b2bua_from = call_info.get('b2bua_from', f"<sip:{caller_username}@{b2bua_ip}>;tag=b2bua")
                b2bua_to = call_info.get('b2bua_to', f"<sip:{callee_username}@{b2bua_ip}>")
                
                # CANCEL 메시지 생성
                cancel_msg = (
                    f"CANCEL sip:{callee_username}@{callee_addr[0]}:{callee_addr[1]} SIP/2.0\r\n"
                    f"Via: {b2bua_via}\r\n"
                    f"From: {b2bua_from}\r\n"
                    f"To: {b2bua_to}\r\n"
                    f"Call-ID: {b2bua_call_id}\r\n"
                    f"CSeq: {cseq_number} CANCEL\r\n"
                    f"Max-Forwards: 70\r\n"
                    f"Content-Length: 0\r\n"
                    "\r\n"
                )
                
                self._send_response(cancel_msg, callee_addr)
                logger.info("✅ [AI Takeover] CANCEL sent to callee",
                           call_id=call_id,
                           callee=callee_username)
            
            # 🔄 Step 2: 발신자에게 200 OK 응답 준비 (AI와 연결)
            caller_addr = call_info.get('caller_addr')
            caller_rtp_port = None
            caller_rtcp_port = None
            
            if caller_addr:
                # Media Session에서 RTP 포트 가져오기
                media_session = self.media_session_manager.get_session(call_id)
                if media_session:
                    caller_rtp_port = media_session.caller_leg.get_audio_rtp_port()
                    caller_rtcp_port = media_session.caller_leg.get_audio_rtcp_port()
                    logger.info("🔄 [AI Takeover] Using allocated RTP ports",
                               call_id=call_id,
                               caller_rtp_port=caller_rtp_port,
                               caller_rtcp_port=caller_rtcp_port)
                    
                    # ✅ 포트 범위 검증 (10000-10100)
                    if caller_rtp_port < 10000 or caller_rtp_port > 10100:
                        logger.warning("🔄 [AI Takeover] RTP port out of firewall range, adjusting",
                                     call_id=call_id,
                                     original_port=caller_rtp_port,
                                     new_port=10000)
                        caller_rtp_port = 10000
                        caller_rtcp_port = 10001
                else:
                    # Fallback: 기본 포트 사용
                    caller_rtp_port = 10000
                    caller_rtcp_port = 10001
                    logger.warning("🔄 [AI Takeover] No media session found, using default port",
                                 call_id=call_id,
                                 default_port=caller_rtp_port)
            
            # ✅ AI 모드 플래그를 먼저 설정 (에러가 발생해도 487 relay 방지)
            call_info['ai_mode_activated'] = True
            call_info['is_ai_call'] = True  # Knowledge extraction must skip this call
            call_info['state'] = 'answering'  # AI 응답 준비 중
            logger.info("ai_mode_activated", 
                       call_id=call_id,
                       callee=callee_username)
            
            # 🔄 Step 3: RTP를 AI 모드로 전환
            rtp_worker = self._rtp_workers.get(call_id)
            if rtp_worker:
                logger.info("🔄 [AI Takeover] Enabling AI mode on RTP Worker",
                           call_id=call_id)
                
                # RTP Worker에 AI 모드 연결
                if self.call_manager and self.call_manager.ai_orchestrator:
                    # Pipecat Pipeline Builder가 있으면 Pipecat 모드
                    if self.call_manager.pipecat_builder:
                        # Pipecat은 call_manager.handle_no_answer_timeout에서
                        # rtp_worker.enable_pipecat_mode()를 호출하므로
                        # 여기서는 기본 ai_mode만 활성화
                        rtp_worker.ai_mode = True
                        logger.info("✅ [AI Takeover] Pipecat mode - RTP Worker ready",
                                   call_id=call_id)
                    else:
                        # Legacy orchestrator 모드
                        rtp_worker.enable_ai_mode(
                            self.call_manager.ai_orchestrator
                        )
                        
                        # AI Orchestrator에 RTP 전송 콜백 연결
                        async def _rtp_send_wrapper(audio_data: bytes):
                            rtp_worker.send_ai_audio(audio_data)
                        
                        self.call_manager.ai_orchestrator.set_rtp_callback(_rtp_send_wrapper)
                        
                        logger.info("✅ [AI Takeover] Legacy mode - RTP Worker + callback connected",
                                   call_id=call_id)
                else:
                    logger.warning("🔄 [AI Takeover] AI Orchestrator not available",
                                 call_id=call_id)
                
                # 🎯 Step 3.5-A: 200 OK 전송 **직전**에 STUN Binding Request를 UAC에게 전송
                # UAC가 미디어 경로를 미리 확인하도록 함
                try:
                    rtp_worker.send_stun_binding_request_to_caller()
                    logger.info("🎯 [AI Takeover] STUN Binding Request sent to caller (BEFORE 200 OK)",
                               call_id=call_id)
                except Exception as stun_err:
                    logger.warning("stun_request_before_200ok_failed",
                                 call_id=call_id,
                                 error=str(stun_err))
            else:
                logger.warning("🔄 [AI Takeover] No RTP worker found",
                             call_id=call_id)
            
            # 🔄 Step 4: 200 OK 전송
            if caller_addr and caller_rtp_port and caller_rtcp_port:
                logger.info("🔄 [AI Takeover] Sending 200 OK to caller (connecting to AI)",
                           call_id=call_id)
                
                # 원본 INVITE의 SDP에서 속성 및 session 정보 추출
                original_sdp = call_info.get('sdp', '')
                original_attributes = []
                session_id = "3059"
                session_version = "3909"
                
                if original_sdp:
                    # 원본 SDP에서 o= 라인의 session-id와 version 추출
                    lines = original_sdp.split('\r\n') if '\r\n' in original_sdp else original_sdp.split('\n')
                    for line in lines:
                        line_stripped = line.strip()
                        if line_stripped.startswith('o='):
                            # o=username session-id version nettype addrtype address
                            parts = line_stripped.split()
                            if len(parts) >= 3:
                                session_id = parts[1]
                                session_version = parts[2]
                            break
                    
                    # 원본 SDP에서 audio 미디어 블록의 속성 추출
                    in_audio_media = False
                    for line in lines:
                        line_stripped = line.strip()
                        if line_stripped.startswith('m=audio'):
                            in_audio_media = True
                        elif line_stripped.startswith('m=') and not line_stripped.startswith('m=audio'):
                            in_audio_media = False
                        elif in_audio_media and line_stripped.startswith('a='):
                            attr = line_stripped[2:]  # 'a=' 제거
                            # 필요한 속성만 유지 (rtcp-xr, rtcp-fb:* trr-int, record)
                            if attr.startswith('rtcp-xr:'):
                                original_attributes.append(f"a={attr}\r\n")
                            elif attr.startswith('record:'):
                                original_attributes.append(f"a={attr}\r\n")
                            elif attr.startswith('rtcp-fb:') and 'trr-int' in attr:
                                # a=rtcp-fb:* trr-int 1000만 포함 (ccm tmmbr 제외)
                                original_attributes.append(f"a={attr}\r\n")
                
                # SDP 생성 (정상 릴레이 케이스와 동일한 형식)
                # RTCP 포트는 명시적으로 추가 (RFC 3605 준수)
                sdp_lines = [
                    f"v=0\r\n",
                    f"o={callee_username} {session_id} {session_version} IN IP4 {b2bua_ip}\r\n",
                    f"s=Talk\r\n",
                    f"c=IN IP4 {b2bua_ip}\r\n",
                    f"t=0 0\r\n",
                ]
                # 원본 SDP의 속성 추가 (rtcp-xr, record 등)
                sdp_lines.extend(original_attributes)
                # 미디어 라인
                sdp_lines.append(f"m=audio {caller_rtp_port} RTP/AVP 0 8 101\r\n")
                # 필수 rtpmap만 추가 (101만 명시, 0과 8은 표준이므로 생략)
                sdp_lines.append(f"a=rtpmap:101 telephone-event/8000\r\n")
                # RTCP 포트 명시
                sdp_lines.append(f"a=rtcp:{caller_rtcp_port}\r\n")
                # rtcp-fb:* trr-int만 추가 (이미 original_attributes에 포함됨)
                
                sdp = ''.join(sdp_lines)
                
                # ✅ Via 헤더는 원본 INVITE의 것을 그대로 사용
                original_via = call_info.get('original_via', 
                    f"SIP/2.0/UDP {caller_addr[0]}:{caller_addr[1]};branch={call_info.get('original_via_branch', 'z9hG4bK000000')};rport")
                
                # ✅ To 헤더: 180 Ringing에서 받은 callee_tag를 사용 (RFC 3261 Dialog 유지)
                original_to = call_info.get('original_to', f'sip:{callee_username}@{b2bua_ip}')
                # angle brackets가 없으면 추가
                if not original_to.strip().startswith('<'):
                    to_uri = f"<{original_to}>"
                else:
                    to_uri = original_to
                
                # ✅ 180 Ringing에서 받은 callee_tag 사용 (Dialog 일관성 유지)
                callee_tag = call_info.get('callee_tag')
                if callee_tag:
                    # 180 Ringing에서 이미 받은 tag 사용
                    to_header = f"{to_uri};tag={callee_tag}"
                    logger.info("🔄 [AI Takeover] Using callee_tag from 180 Ringing",
                               call_id=call_id,
                               callee_tag=callee_tag)
                else:
                    # Fallback: callee_tag가 없으면 새로 생성 (정상적인 상황에서는 발생하지 않음)
                    to_header = f"{to_uri};tag=ai-{call_id[:8]}"
                    logger.warning("🔄 [AI Takeover] No callee_tag found, generating new tag",
                                 call_id=call_id,
                                 generated_tag=f"ai-{call_id[:8]}")
                
                # ✅ Contact 헤더: 정상 통화와 동일한 형식 (transport 제거)
                contact_uri = f"<sip:{callee_username}@{b2bua_ip}:{listen_port}>"
                
                # ✅ 정상 릴레이 케이스와 동일하게 Allow 헤더만 포함
                allow = "INVITE, ACK, CANCEL, OPTIONS, BYE, REFER, NOTIFY, MESSAGE, SUBSCRIBE, INFO, PRACK, UPDATE"
                
                ok_response = (
                    "SIP/2.0 200 OK\r\n"
                    f"Via: {original_via}\r\n"
                    f"From: {call_info.get('original_from')}\r\n"
                    f"To: {to_header}\r\n"
                    f"Call-ID: {call_id}\r\n"
                    f"CSeq: {call_info.get('original_cseq', '1 INVITE')}\r\n"
                    f"Contact: {contact_uri}\r\n"
                    f"Allow: {allow}\r\n"
                    f"Content-Type: application/sdp\r\n"
                    f"Content-Length: {len(sdp)}\r\n"
                    "\r\n"
                    f"{sdp}"
                )
                
                self._send_response(ok_response, caller_addr)
                logger.info("✅ [AI Takeover] 200 OK sent to caller",
                           call_id=call_id)
            
            # 🎯 Step 4.5: 200 OK 전송 **직후**에도 STUN Binding Request를 UAC에게 전송
            # UAC가 ACK+BYE를 동시에 보내는 문제를 방지하기 위해 미디어 경로를 재확인
            if rtp_worker:
                try:
                    rtp_worker.send_stun_binding_request_to_caller()
                    logger.info("🎯 [AI Takeover] STUN Binding Request sent to caller (AFTER 200 OK)",
                               call_id=call_id)
                except Exception as stun_err:
                    logger.warning("stun_request_after_200ok_failed",
                                 call_id=call_id,
                                 error=str(stun_err))
            
            # 🔄 Step 5: AI 모드 전환 (CallManager를 통해 - 백그라운드로 실행)
            if self.call_manager:
                # ✅ AI Orchestrator 호출을 백그라운드 태스크로 실행 (블로킹하지 않음)
                asyncio.create_task(
                    self.call_manager.handle_no_answer_timeout(call_id, callee_username)
                )
                call_info['is_ai_call'] = True  # Knowledge extraction must skip this call
                call_info['ai_mode_activated'] = True
                call_info['state'] = 'established'  # AI와 연결됨
            else:
                logger.error("no_answer_timeout_no_call_manager", call_id=call_id)
                
        except Exception as e:
            logger.error("no_answer_timeout_error",
                        call_id=call_id,
                        error=str(e),
                        exc_info=True)
    
    async def _handle_invite_timeout(self, transaction_id: str) -> None:
        """INVITE 타임아웃 처리 (Transaction Timer 콜백)
        
        Args:
            transaction_id: 트랜잭션 ID
        """
        try:
            # transaction_id로 call_info 찾기
            call_info = None
            original_call_id = None
            for cid, info in self._active_calls.items():
                if info.get('transaction_id') == transaction_id:
                    call_info = info
                    original_call_id = info.get('original_call_id')
                    break
            
            if not call_info:
                logger.warning("invite_timeout_no_call", transaction_id=transaction_id)
                return
            
            logger.warning("invite_timeout",
                          transaction_id=transaction_id,
                          call_id=original_call_id,
                          timeout=64 * self.config.sip.timers.t1)
            
            # 발신자에게 408 Request Timeout 전송
            caller_addr = call_info.get('caller_addr')
            if caller_addr:
                from_hdr = call_info.get('original_from')
                to_hdr = call_info.get('original_to')
                
                timeout_response = (
                    "SIP/2.0 408 Request Timeout\r\n"
                    f"Via: SIP/2.0/UDP {caller_addr[0]}:{caller_addr[1]};branch={call_info.get('original_via_branch', 'z9hG4bK000000')}\r\n"
                    f"From: {from_hdr}\r\n"
                    f"To: {to_hdr};tag=b2bua-timeout\r\n"
                    f"Call-ID: {original_call_id}\r\n"
                    "CSeq: 1 INVITE\r\n"
                    "Content-Length: 0\r\n"
                    "\r\n"
                )
                self._send_response(timeout_response, caller_addr)
            
            # 통화 정리
            await self._cleanup_call(original_call_id)
            
        except Exception as e:
            logger.error("invite_timeout_error",
                        transaction_id=transaction_id,
                        error=str(e),
                        exc_info=True)
    
    def stop(self) -> None:
        """Mock 서버 종료"""
        self._running = False
        if self._listen_task:
            self._listen_task.cancel()
        
        # SIP 트래픽 로그 파일 닫기
        if self._sip_log_file:
            try:
                self._sip_log_file.close()
                logger.info("sip_traffic_log_closed")
            except Exception as e:
                logger.error("sip_traffic_log_close_failed", error=str(e))
        
        logger.info("sip_server_stopped")
    
    # =========================================================================
    # Transfer (호 전환) 관련 메서드
    # =========================================================================
    
    async def send_transfer_invite(
        self,
        call_id: str,
        transfer_leg_call_id: str,
        transfer_to: str,
        caller_display: str = "",
    ):
        """Transfer INVITE 발신
        
        B2BUA에서 전환 대상에게 새로운 INVITE를 발신합니다.
        SDP에는 서버의 미디어 포트를 넣어 미디어가 서버를 경유하도록 합니다.
        
        Args:
            call_id: 원래 호 ID
            transfer_leg_call_id: 전환 레그 Call-ID
            transfer_to: 전환 대상 (SIP URI 또는 내선번호)
            caller_display: 발신자 표시명
        """
        try:
            # 1. 전환 대상 주소 해석
            target_user, target_addr = self._resolve_transfer_target(transfer_to)
            if not target_addr:
                raise ValueError(f"Cannot resolve transfer target: {transfer_to}")
            
            # 2. 미디어 포트 할당 (Bridge용)
            bridge_ports = self._port_pool.allocate(2)  # [rtp, rtcp]
            
            # 3. B2BUA IP 가져오기
            b2bua_ip = self._get_b2bua_ip()
            
            # 4. SDP 구성 (서버의 미디어 정보)
            # ✅ AI 200 OK SDP (검증 완료)와 동일한 형식 사용
            # - s=Talk (단말 호환성 검증 완료)
            # - PT 0/8은 well-known static type이므로 rtpmap 생략 (RFC 3551)
            # - sendrecv는 기본값이므로 생략 (RFC 3264)
            # - fmtp:101 생략 (검증된 형식과 일치)
            import time as _time
            session_id = str(int(_time.time()))
            session_version = str(int(_time.time()))
            
            # 원래 호의 SDP에서 session 정보 추출 (가능하면)
            original_call_info = self._active_calls.get(call_id)
            if original_call_info:
                original_sdp = original_call_info.get('sdp', '')
                if original_sdp:
                    sdp_lines_orig = original_sdp.split('\r\n') if '\r\n' in original_sdp else original_sdp.split('\n')
                    for line in sdp_lines_orig:
                        if line.strip().startswith('o='):
                            parts = line.strip().split()
                            if len(parts) >= 3:
                                session_id = parts[1]
                                session_version = parts[2]
                            break
            
            transfer_sdp = (
                f"v=0\r\n"
                f"o=- {session_id} {session_version} IN IP4 {b2bua_ip}\r\n"
                f"s=Talk\r\n"
                f"c=IN IP4 {b2bua_ip}\r\n"
                f"t=0 0\r\n"
                f"m=audio {bridge_ports[0]} RTP/AVP 0 8 101\r\n"
                f"a=rtpmap:101 telephone-event/8000\r\n"
                f"a=rtcp:{bridge_ports[1]}\r\n"
            )
            
            # 5. From tag 생성
            import random
            from_tag = f"xfer-{random.randint(100000, 999999)}"
            
            # 6. INVITE 메시지 구성
            via_branch = f"z9hG4bK-xfer-{random.randint(10000000, 99999999)}"
            
            invite_msg = (
                f"INVITE sip:{target_user}@{target_addr[0]}:{target_addr[1]} SIP/2.0\r\n"
                f"Via: SIP/2.0/UDP {b2bua_ip}:{self.config.sip.listen_port};branch={via_branch}\r\n"
                f"Max-Forwards: 70\r\n"
                f'From: "{caller_display}" <sip:{caller_display}@{b2bua_ip}>;tag={from_tag}\r\n'
                f"To: <sip:{target_user}@{target_addr[0]}>\r\n"
                f"Call-ID: {transfer_leg_call_id}\r\n"
                f"CSeq: 1 INVITE\r\n"
                f"Contact: <sip:{b2bua_ip}:{self.config.sip.listen_port}>\r\n"
                f"Content-Type: application/sdp\r\n"
                f"Content-Length: {len(transfer_sdp)}\r\n"
                f"\r\n"
                f"{transfer_sdp}"
            )
            
            # 7. 전환 호 정보 저장
            self._active_calls[transfer_leg_call_id] = {
                'is_transfer': True,
                'original_call_id': call_id,
                'transfer_leg_call_id': transfer_leg_call_id,
                'target_user': target_user,
                'target_addr': target_addr,
                'from_tag': from_tag,
                'state': 'inviting',
                'bridge_ports': bridge_ports,
                'b2bua_call_id': transfer_leg_call_id,
                'start_time': datetime.now(),
            }
            
            # call_mapping에 추가 (응답 처리용)
            self._call_mapping[transfer_leg_call_id] = transfer_leg_call_id
            
            # 8. INVITE 전송
            self._socket.sendto(invite_msg.encode(), target_addr)
            
            logger.info("transfer_invite_sent",
                       call_id=call_id,
                       transfer_leg=transfer_leg_call_id,
                       target=f"{target_user}@{target_addr[0]}:{target_addr[1]}",
                       bridge_rtp_port=bridge_ports[0])
            
        except Exception as e:
            logger.error("transfer_invite_send_error",
                        call_id=call_id,
                        transfer_to=transfer_to,
                        error=str(e))
            # TransferManager에 실패 통보
            if hasattr(self, '_transfer_manager') and self._transfer_manager:
                await self._transfer_manager.on_transfer_rejected(
                    transfer_leg_call_id, 500, str(e))
    
    def _resolve_transfer_target(self, transfer_to: str):
        """전환 대상 주소 해석
        
        Returns:
            (username, (ip, port)) tuple
        """
        # SIP URI 형식
        if transfer_to.startswith("sip:"):
            # sip:user@host:port 또는 sip:user@host
            uri_part = transfer_to[4:]  # "sip:" 제거
            if '@' in uri_part:
                user, host_part = uri_part.split('@', 1)
                if ':' in host_part:
                    host, port = host_part.split(':', 1)
                    return (user, (host, int(port)))
                else:
                    # 등록된 사용자 확인
                    if user in self._registered_users:
                        reg = self._registered_users[user]
                        return (user, (reg['ip'], reg['port']))
                    return (user, (host_part, 5060))
        
        # 내선번호 (숫자만)
        if transfer_to.isdigit() or transfer_to.replace('-', '').isdigit():
            clean_number = transfer_to.replace('-', '')
            if clean_number in self._registered_users:
                reg = self._registered_users[clean_number]
                return (clean_number, (reg['ip'], reg['port']))
            
            logger.warning("transfer_target_not_registered",
                          extension=clean_number)
            return (clean_number, None)
        
        # 기타 형식
        logger.warning("transfer_target_unknown_format", transfer_to=transfer_to)
        return (transfer_to, None)
    
    async def send_transfer_cancel(self, transfer_leg_call_id: str):
        """Transfer CANCEL 전송"""
        try:
            call_info = self._active_calls.get(transfer_leg_call_id)
            if not call_info or not call_info.get('is_transfer'):
                return
            
            target_addr = call_info.get('target_addr')
            if not target_addr:
                return
            
            b2bua_ip = self._get_b2bua_ip()
            from_tag = call_info.get('from_tag', '')
            target_user = call_info.get('target_user', '')
            
            cancel_msg = (
                f"CANCEL sip:{target_user}@{target_addr[0]}:{target_addr[1]} SIP/2.0\r\n"
                f"Via: SIP/2.0/UDP {b2bua_ip}:{self.config.sip.listen_port};branch=z9hG4bK-xfer-cancel\r\n"
                f"Max-Forwards: 70\r\n"
                f"From: <sip:{b2bua_ip}>;tag={from_tag}\r\n"
                f"To: <sip:{target_user}@{target_addr[0]}>\r\n"
                f"Call-ID: {transfer_leg_call_id}\r\n"
                f"CSeq: 1 CANCEL\r\n"
                f"Content-Length: 0\r\n"
                f"\r\n"
            )
            
            self._socket.sendto(cancel_msg.encode(), target_addr)
            logger.info("transfer_cancel_sent", transfer_leg=transfer_leg_call_id)
            
        except Exception as e:
            logger.error("transfer_cancel_error",
                        transfer_leg=transfer_leg_call_id, error=str(e))
    
    async def send_transfer_bye(self, leg_call_id: str):
        """Transfer BYE 전송"""
        try:
            call_info = self._active_calls.get(leg_call_id)
            if not call_info:
                return
            
            target_addr = call_info.get('target_addr')
            if not target_addr:
                return
            
            b2bua_ip = self._get_b2bua_ip()
            from_tag = call_info.get('from_tag', '')
            callee_tag = call_info.get('callee_tag', '')
            target_user = call_info.get('target_user', '')
            
            bye_msg = (
                f"BYE sip:{target_user}@{target_addr[0]}:{target_addr[1]} SIP/2.0\r\n"
                f"Via: SIP/2.0/UDP {b2bua_ip}:{self.config.sip.listen_port};branch=z9hG4bK-xfer-bye\r\n"
                f"Max-Forwards: 70\r\n"
                f"From: <sip:{b2bua_ip}>;tag={from_tag}\r\n"
                f"To: <sip:{target_user}@{target_addr[0]}>"
                f"{';tag=' + callee_tag if callee_tag else ''}\r\n"
                f"Call-ID: {leg_call_id}\r\n"
                f"CSeq: 2 BYE\r\n"
                f"Content-Length: 0\r\n"
                f"\r\n"
            )
            
            self._socket.sendto(bye_msg.encode(), target_addr)
            logger.info("transfer_bye_sent", leg_call_id=leg_call_id)
            
            # 정리
            self._active_calls.pop(leg_call_id, None)
            self._call_mapping.pop(leg_call_id, None)
            
        except Exception as e:
            logger.error("transfer_bye_error",
                        leg_call_id=leg_call_id, error=str(e))
    
    async def handle_transfer_response(self, response: str, addr: tuple, call_info: dict):
        """Transfer 레그의 SIP 응답 처리
        
        _handle_sip_response에서 transfer 레그로 판별된 경우 호출됩니다.
        """
        lines = response.split('\r\n')
        status_line = lines[0]
        parts = status_line.split()
        status_code = int(parts[1])
        transfer_leg_call_id = call_info['transfer_leg_call_id']
        
        if not hasattr(self, '_transfer_manager') or not self._transfer_manager:
            logger.warning("transfer_manager_not_set")
            return
        
        if status_code in (180, 183):
            # Provisional
            to_hdr = self._extract_header(response, 'To')
            callee_tag = self._extract_tag(to_hdr)
            if callee_tag:
                call_info['callee_tag'] = callee_tag
            
            await self._transfer_manager.on_transfer_provisional(
                transfer_leg_call_id, status_code)
        
        elif status_code == 200:
            # 200 OK → 착신자 응답
            to_hdr = self._extract_header(response, 'To')
            callee_tag = self._extract_tag(to_hdr)
            if callee_tag:
                call_info['callee_tag'] = callee_tag
            call_info['state'] = 'answered'
            
            # SDP 추출
            callee_sdp = self._extract_sdp_body(response)
            
            # ACK 전송
            await self._send_transfer_ack(call_info, addr)
            
            # TransferManager에 통보
            await self._transfer_manager.on_transfer_answered(
                transfer_leg_call_id, callee_sdp or "")
        
        elif status_code >= 300:
            # Error/Reject
            reason = parts[2] if len(parts) > 2 else "Unknown"
            
            # ACK for non-2xx
            await self._send_transfer_ack(call_info, addr)
            
            await self._transfer_manager.on_transfer_rejected(
                transfer_leg_call_id, status_code, reason)
            
            # 정리
            self._active_calls.pop(transfer_leg_call_id, None)
            self._call_mapping.pop(transfer_leg_call_id, None)
    
    async def _send_transfer_ack(self, call_info: dict, addr: tuple):
        """Transfer 레그에 ACK 전송"""
        try:
            transfer_leg_call_id = call_info['transfer_leg_call_id']
            target_user = call_info.get('target_user', '')
            target_addr = call_info.get('target_addr', addr)
            from_tag = call_info.get('from_tag', '')
            callee_tag = call_info.get('callee_tag', '')
            b2bua_ip = self._get_b2bua_ip()
            
            ack_msg = (
                f"ACK sip:{target_user}@{target_addr[0]}:{target_addr[1]} SIP/2.0\r\n"
                f"Via: SIP/2.0/UDP {b2bua_ip}:{self.config.sip.listen_port};branch=z9hG4bK-xfer-ack\r\n"
                f"Max-Forwards: 70\r\n"
                f"From: <sip:{b2bua_ip}>;tag={from_tag}\r\n"
                f"To: <sip:{target_user}@{target_addr[0]}>"
                f"{';tag=' + callee_tag if callee_tag else ''}\r\n"
                f"Call-ID: {transfer_leg_call_id}\r\n"
                f"CSeq: 1 ACK\r\n"
                f"Content-Length: 0\r\n"
                f"\r\n"
            )
            
            self._socket.sendto(ack_msg.encode(), target_addr)
            logger.info("transfer_ack_sent", transfer_leg=transfer_leg_call_id)
            
        except Exception as e:
            logger.error("transfer_ack_error", error=str(e))
    
    async def switch_to_bridge_mode(
        self, call_id: str, transfer_leg_call_id: str, callee_sdp: str
    ):
        """RTP Relay를 Bridge 모드로 전환
        
        AI 모드에서 Bridge 모드로 전환하여 발신자↔서버↔착신자 미디어 경로를 구성합니다.
        """
        try:
            from src.media.sdp_parser import SDPParser
            
            # 착신자 SDP 파싱 → 미디어 엔드포인트 확인
            callee_ip = None
            callee_rtp_port = None
            
            if callee_sdp:
                parsed_sdp = SDPParser.parse(callee_sdp)
                if parsed_sdp:
                    callee_ip = parsed_sdp.connection_ip
                    if parsed_sdp.media_descriptions:
                        for md in parsed_sdp.media_descriptions:
                            if md.media_type == "audio":
                                callee_rtp_port = md.port
                                break
            
            # Transfer call_info에서 bridge 포트 가져오기
            xfer_info = self._active_calls.get(transfer_leg_call_id)
            if not xfer_info:
                logger.error("transfer_call_info_not_found",
                            transfer_leg=transfer_leg_call_id)
                return
            
            bridge_ports = xfer_info.get('bridge_ports', [])
            if not bridge_ports:
                logger.error("bridge_ports_not_found",
                            transfer_leg=transfer_leg_call_id)
                return
            
            bridge_rtp_port = bridge_ports[0]
            
            if not callee_ip or not callee_rtp_port:
                # SDP 파싱 실패 시 전환 대상 주소 사용
                target_addr = xfer_info.get('target_addr')
                if target_addr:
                    callee_ip = target_addr[0]
                    callee_rtp_port = bridge_rtp_port  # 기본값
            
            # RTP Worker에서 Bridge 모드 활성화
            rtp_worker = self._rtp_workers.get(call_id)
            if rtp_worker:
                await rtp_worker.set_bridge_mode(
                    callee_ip=callee_ip,
                    callee_rtp_port=callee_rtp_port,
                    bridge_rtp_port=bridge_rtp_port,
                )
                
                logger.info("bridge_mode_established",
                           call_id=call_id,
                           callee=f"{callee_ip}:{callee_rtp_port}",
                           bridge_port=bridge_rtp_port)
            else:
                logger.error("rtp_worker_not_found_for_bridge",
                            call_id=call_id)
            
        except Exception as e:
            logger.error("switch_to_bridge_error",
                        call_id=call_id, error=str(e))
    
    # =========================================================================
    # Outbound Call 관련 메서드
    # =========================================================================
    
    async def send_outbound_invite(
        self,
        to_number: str,
        from_number: str,
        from_display: str = "",
        outbound_id: str = "",
    ) -> str:
        """아웃바운드 콜 SIP INVITE 발신
        
        B2BUA에서 외부 번호로 직접 INVITE를 발신합니다.
        SDP에는 서버의 미디어 포트를 넣어 AI 모드로 통화합니다.
        
        Args:
            to_number: 착신번호
            from_number: 발신번호
            from_display: 발신자 표시명
            outbound_id: 아웃바운드 콜 ID
            
        Returns:
            생성된 Call-ID
        """
        try:
            # 1. 대상 주소 해석
            target_user, target_addr = self._resolve_outbound_target(to_number)
            if not target_addr:
                raise ValueError(f"Cannot resolve outbound target: {to_number}")
            
            # 2. 미디어 포트 할당 (AI 모드용)
            media_ports = self._port_pool.allocate(2)  # [rtp, rtcp]
            
            # 3. B2BUA IP
            b2bua_ip = self._get_b2bua_ip()
            
            # 4. Call-ID 생성
            import random
            call_id = f"outbound-{outbound_id}-{random.randint(10000000, 99999999)}"
            
            # 5. SDP 구성 (검증된 AI 200 OK / Transfer INVITE와 동일한 형식)
            import time as _time
            session_id = str(int(_time.time()))
            
            outbound_sdp = (
                f"v=0\r\n"
                f"o=- {session_id} {session_id} IN IP4 {b2bua_ip}\r\n"
                f"s=Talk\r\n"
                f"c=IN IP4 {b2bua_ip}\r\n"
                f"t=0 0\r\n"
                f"m=audio {media_ports[0]} RTP/AVP 0 8 101\r\n"
                f"a=rtpmap:101 telephone-event/8000\r\n"
                f"a=rtcp:{media_ports[1]}\r\n"
            )
            
            # 6. From tag
            from_tag = f"ob-{random.randint(100000, 999999)}"
            
            # 7. INVITE 메시지 구성
            via_branch = f"z9hG4bK-ob-{random.randint(10000000, 99999999)}"
            display_name = from_display or from_number
            
            invite_msg = (
                f"INVITE sip:{target_user}@{target_addr[0]}:{target_addr[1]} SIP/2.0\r\n"
                f"Via: SIP/2.0/UDP {b2bua_ip}:{self.config.sip.listen_port};branch={via_branch}\r\n"
                f"Max-Forwards: 70\r\n"
                f'From: "{display_name}" <sip:{from_number}@{b2bua_ip}>;tag={from_tag}\r\n'
                f"To: <sip:{target_user}@{target_addr[0]}>\r\n"
                f"Call-ID: {call_id}\r\n"
                f"CSeq: 1 INVITE\r\n"
                f"Contact: <sip:{from_number}@{b2bua_ip}:{self.config.sip.listen_port}>\r\n"
                f"Content-Type: application/sdp\r\n"
                f"Content-Length: {len(outbound_sdp)}\r\n"
                f"X-Outbound-Call-ID: {outbound_id}\r\n"
                f"\r\n"
                f"{outbound_sdp}"
            )
            
            # 8. 호 정보 저장
            self._active_calls[call_id] = {
                'is_outbound': True,
                'outbound_id': outbound_id,
                'call_id': call_id,
                'target_user': target_user,
                'target_addr': target_addr,
                'from_tag': from_tag,
                'from_number': from_number,
                'to_number': to_number,
                'state': 'inviting',
                'media_ports': media_ports,
                'b2bua_call_id': call_id,
                'start_time': datetime.now(),
                'sdp': outbound_sdp,
            }
            
            # call_mapping에 추가
            self._call_mapping[call_id] = call_id
            
            # 9. 전송
            self._socket.sendto(invite_msg.encode(), target_addr)
            
            logger.info("outbound_invite_sent",
                       call_id=call_id,
                       outbound_id=outbound_id,
                       target=f"{target_user}@{target_addr[0]}:{target_addr[1]}",
                       media_rtp_port=media_ports[0])
            
            return call_id
            
        except Exception as e:
            logger.error("outbound_invite_send_error",
                        to_number=to_number,
                        outbound_id=outbound_id,
                        error=str(e))
            raise
    
    def _resolve_outbound_target(self, number: str):
        """아웃바운드 대상 주소 해석
        
        Returns:
            (username, (ip, port)) tuple
        """
        # 1. 등록된 유저 확인 (내선번호)
        clean_number = number.replace('-', '').replace(' ', '')
        if clean_number in self._registered_users:
            reg = self._registered_users[clean_number]
            return (clean_number, (reg['ip'], reg['port']))
        
        # 2. SIP URI 형식
        if number.startswith("sip:"):
            uri_part = number[4:]
            if '@' in uri_part:
                user, host_part = uri_part.split('@', 1)
                if ':' in host_part:
                    host, port = host_part.split(':', 1)
                    return (user, (host, int(port)))
                return (user, (host_part, 5060))
        
        # 3. SIP Gateway 사용 (외부 번호)
        outbound_config = {}
        if hasattr(self.config, 'ai_voicebot') and self.config.ai_voicebot:
            ob = getattr(self.config.ai_voicebot, 'outbound', None)
            if ob:
                outbound_config = ob if isinstance(ob, dict) else ob.model_dump() if hasattr(ob, 'model_dump') else {}
        
        gateway = outbound_config.get('default_gateway')
        if gateway:
            if gateway.startswith("sip:"):
                gateway = gateway[4:]
            if ':' in gateway:
                host, port = gateway.rsplit(':', 1)
                return (clean_number, (host, int(port)))
            return (clean_number, (gateway, 5060))
        
        logger.warning("outbound_target_unresolved",
                       number=number,
                       hint="Set default_gateway in config or register the number")
        return (clean_number, None)
    
    async def send_outbound_cancel(self, call_id: str):
        """아웃바운드 콜 CANCEL 전송"""
        try:
            call_info = self._active_calls.get(call_id)
            if not call_info or not call_info.get('is_outbound'):
                return
            
            target_addr = call_info.get('target_addr')
            if not target_addr:
                return
            
            b2bua_ip = self._get_b2bua_ip()
            from_tag = call_info.get('from_tag', '')
            target_user = call_info.get('target_user', '')
            from_number = call_info.get('from_number', '')
            
            import random
            via_branch = f"z9hG4bK-ob-cancel-{random.randint(10000000, 99999999)}"
            
            cancel_msg = (
                f"CANCEL sip:{target_user}@{target_addr[0]}:{target_addr[1]} SIP/2.0\r\n"
                f"Via: SIP/2.0/UDP {b2bua_ip}:{self.config.sip.listen_port};branch={via_branch}\r\n"
                f"Max-Forwards: 70\r\n"
                f"From: <sip:{from_number}@{b2bua_ip}>;tag={from_tag}\r\n"
                f"To: <sip:{target_user}@{target_addr[0]}>\r\n"
                f"Call-ID: {call_id}\r\n"
                f"CSeq: 1 CANCEL\r\n"
                f"Content-Length: 0\r\n"
                f"\r\n"
            )
            
            self._socket.sendto(cancel_msg.encode(), target_addr)
            logger.info("outbound_cancel_sent", call_id=call_id)
            
        except Exception as e:
            logger.error("outbound_cancel_error", call_id=call_id, error=str(e))
    
    async def send_outbound_bye(self, call_id: str):
        """아웃바운드 콜 BYE 전송"""
        try:
            call_info = self._active_calls.get(call_id)
            if not call_info:
                return
            
            target_addr = call_info.get('target_addr')
            if not target_addr:
                return
            
            b2bua_ip = self._get_b2bua_ip()
            from_tag = call_info.get('from_tag', '')
            callee_tag = call_info.get('callee_tag', '')
            target_user = call_info.get('target_user', '')
            from_number = call_info.get('from_number', '')
            
            import random
            via_branch = f"z9hG4bK-ob-bye-{random.randint(10000000, 99999999)}"
            
            bye_msg = (
                f"BYE sip:{target_user}@{target_addr[0]}:{target_addr[1]} SIP/2.0\r\n"
                f"Via: SIP/2.0/UDP {b2bua_ip}:{self.config.sip.listen_port};branch={via_branch}\r\n"
                f"Max-Forwards: 70\r\n"
                f"From: <sip:{from_number}@{b2bua_ip}>;tag={from_tag}\r\n"
                f"To: <sip:{target_user}@{target_addr[0]}>"
                f"{';tag=' + callee_tag if callee_tag else ''}\r\n"
                f"Call-ID: {call_id}\r\n"
                f"CSeq: 2 BYE\r\n"
                f"Content-Length: 0\r\n"
                f"\r\n"
            )
            
            self._socket.sendto(bye_msg.encode(), target_addr)
            logger.info("outbound_bye_sent", call_id=call_id)
            
            # 정리
            self._active_calls.pop(call_id, None)
            self._call_mapping.pop(call_id, None)
            
        except Exception as e:
            logger.error("outbound_bye_error", call_id=call_id, error=str(e))
    
    async def handle_outbound_response(self, response: str, addr: tuple, call_info: dict):
        """아웃바운드 콜의 SIP 응답 처리"""
        lines = response.split('\r\n')
        status_line = lines[0]
        parts = status_line.split()
        status_code = int(parts[1])
        call_id = call_info['call_id']
        
        if not hasattr(self, '_outbound_manager') or not self._outbound_manager:
            logger.warning("outbound_manager_not_set")
            return
        
        if status_code in (100,):
            # 100 Trying - ignore
            return
        
        elif status_code in (180, 183):
            # Provisional
            to_hdr = self._extract_header(response, 'To')
            callee_tag = self._extract_tag(to_hdr)
            if callee_tag:
                call_info['callee_tag'] = callee_tag
            
            await self._outbound_manager.on_provisional(call_id, status_code)
        
        elif status_code == 200:
            # 200 OK → 착신자 응답
            to_hdr = self._extract_header(response, 'To')
            callee_tag = self._extract_tag(to_hdr)
            if callee_tag:
                call_info['callee_tag'] = callee_tag
            call_info['state'] = 'answered'
            
            # SDP 추출
            callee_sdp = self._extract_sdp_body(response)
            
            # ACK 전송
            await self._send_outbound_ack(call_info, addr)
            
            # OutboundCallManager에 통보
            await self._outbound_manager.on_answered(call_id, callee_sdp or "")
        
        elif status_code >= 300:
            # Error/Reject
            reason = ' '.join(parts[2:]) if len(parts) > 2 else "Unknown"
            
            # ACK for non-2xx
            await self._send_outbound_ack(call_info, addr)
            
            await self._outbound_manager.on_rejected(call_id, status_code, reason)
            
            # 정리
            self._active_calls.pop(call_id, None)
            self._call_mapping.pop(call_id, None)
    
    async def _send_outbound_ack(self, call_info: dict, addr: tuple):
        """아웃바운드 콜에 ACK 전송"""
        try:
            call_id = call_info['call_id']
            target_user = call_info.get('target_user', '')
            target_addr = call_info.get('target_addr', addr)
            from_tag = call_info.get('from_tag', '')
            callee_tag = call_info.get('callee_tag', '')
            from_number = call_info.get('from_number', '')
            b2bua_ip = self._get_b2bua_ip()
            
            import random
            via_branch = f"z9hG4bK-ob-ack-{random.randint(10000000, 99999999)}"
            
            ack_msg = (
                f"ACK sip:{target_user}@{target_addr[0]}:{target_addr[1]} SIP/2.0\r\n"
                f"Via: SIP/2.0/UDP {b2bua_ip}:{self.config.sip.listen_port};branch={via_branch}\r\n"
                f"Max-Forwards: 70\r\n"
                f"From: <sip:{from_number}@{b2bua_ip}>;tag={from_tag}\r\n"
                f"To: <sip:{target_user}@{target_addr[0]}>"
                f"{';tag=' + callee_tag if callee_tag else ''}\r\n"
                f"Call-ID: {call_id}\r\n"
                f"CSeq: 1 ACK\r\n"
                f"Content-Length: 0\r\n"
                f"\r\n"
            )
            
            self._socket.sendto(ack_msg.encode(), target_addr)
            logger.info("outbound_ack_sent", call_id=call_id)
            
        except Exception as e:
            logger.error("outbound_ack_error", error=str(e))
    
    def is_running(self) -> bool:
        """서버 실행 중 여부"""
        return self._running



def create_sip_endpoint(config: Config) -> SIPEndpoint:
    """SIP Endpoint 팩토리 함수
    
    Args:
        config: 설정 객체
        
    Returns:
        SIPEndpoint: SIP Endpoint 인스턴스
    """
    return SIPEndpoint(config)
