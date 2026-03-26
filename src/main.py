"""SIP PBX with Real-time Voice Analysis - Main Entry Point

애플리케이션 시작점
"""

import sys
import argparse
import asyncio
from pathlib import Path
import io
import os
import ssl
import warnings

# ✅ Python stdout/stderr 버퍼링 완전 비활성화 (Windows 콘솔 버퍼링 방지)
os.environ['PYTHONUNBUFFERED'] = '1'
os.environ['PYTHONIOENCODING'] = 'utf-8'

# ✅ Windows 콘솔 모드 설정 (VT100 활성화 + QuickEdit 비활성화)
# ⚠️ QuickEdit이 활성화되면 콘솔 클릭 시 프로세스가 멈추고
#    이벤트 루프가 완전히 블로킹됩니다. 반드시 비활성화해야 합니다.
if sys.platform == "win32":
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        
        STD_INPUT_HANDLE = -10
        STD_OUTPUT_HANDLE = -11
        STD_ERROR_HANDLE = -12
        
        # ★ QuickEdit 모드 비활성화 (핵심 수정)
        # ENABLE_QUICK_EDIT_MODE = 0x0040
        # ENABLE_EXTENDED_FLAGS = 0x0080 (QUICK_EDIT 변경 시 필수)
        stdin_handle = kernel32.GetStdHandle(STD_INPUT_HANDLE)
        input_mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(stdin_handle, ctypes.byref(input_mode)):
            # Quick Edit 비활성화 + Extended Flags 활성화
            new_mode = (input_mode.value | 0x0080) & ~0x0040
            kernel32.SetConsoleMode(stdin_handle, new_mode)
        
        # stdout VT100 활성화
        stdout_handle = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
        stderr_handle = kernel32.GetStdHandle(STD_ERROR_HANDLE)
        
        mode = ctypes.c_ulong()
        kernel32.GetConsoleMode(stdout_handle, ctypes.byref(mode))
        kernel32.SetConsoleMode(stdout_handle, mode.value | 0x0004)
        kernel32.GetConsoleMode(stderr_handle, ctypes.byref(mode))
        kernel32.SetConsoleMode(stderr_handle, mode.value | 0x0004)
        
        # ✅ SelectorEventLoop 설정 (UDP Datagram Transport 안정화)
        # ProactorEventLoop는 UDP에서 'Fatal write error on datagram transport' 발생
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        print("[32mINFO[0m: Windows SelectorEventLoop 설정 완료 (UDP 안정화)")
    except Exception:
        pass  # 실패해도 계속 진행

# SSL 검증 비활성화 (개발 환경용)
os.environ['CURL_CA_BUNDLE'] = ''
os.environ['REQUESTS_CA_BUNDLE'] = ''
os.environ['SSL_CERT_FILE'] = ''
os.environ['TOKENIZERS_PARALLELISM'] = 'false'
ssl._create_default_https_context = ssl._create_unverified_context

# requests 라이브러리 SSL 검증 비활성화
try:
    import requests
    from requests.adapters import HTTPAdapter
    
    # requests 기본 세션 SSL 검증 비활성화
    original_request = requests.Session.request
    def patched_request(self, *args, **kwargs):
        kwargs.setdefault('verify', False)
        return original_request(self, *args, **kwargs)
    requests.Session.request = patched_request
except ImportError:
    pass

# ChromaDB 텔레메트리 비활성화 (통계 전송 비활성화)
os.environ['ANONYMIZED_TELEMETRY'] = 'False'

# 경고 메시지 숨기기
warnings.filterwarnings('ignore', message='Unverified HTTPS request')
warnings.filterwarnings('ignore', category=FutureWarning, module='huggingface_hub')
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# UTF-8 인코딩 설정 + 바이너리 데이터 필터링
class FilteredTextIO(io.TextIOWrapper):
    """바이너리 데이터와 NULL 바이트를 필터링하는 TextIOWrapper"""
    def write(self, s):
        if not s:
            return 0
        # NULL 바이트와 제어 문자 제거 (개행/탭 제외)
        filtered = ''.join(c for c in s if c == '\n' or c == '\t' or ord(c) >= 32)
        if filtered:
            return super().write(filtered)
        return len(s)  # 필터링되어 버려진 문자 수 반환

if sys.platform == "win32":
    # ✅ Windows 콘솔 버퍼링 완전 비활성화
    # - line_buffering=True: 줄 단위 버퍼링
    # - write_through=True: 즉시 쓰기 (Windows 10+)
    sys.stdout = FilteredTextIO(sys.stdout.buffer, encoding='utf-8', errors='replace', 
                                line_buffering=True, write_through=True)
    sys.stderr = FilteredTextIO(sys.stderr.buffer, encoding='utf-8', errors='replace', 
                                line_buffering=True, write_through=True)
    
    # ✅ 명시적 플러시 (추가 보험)
    sys.stdout.flush()
    sys.stderr.flush()
else:
    # Unix/Linux는 기본적으로 잘 작동
    pass

from src.config.config_loader import load_config
from src.config.models import Config
from src.common.logger import setup_logging, get_logger, start_async_logging, stop_async_logging
from src.common.exceptions import SIPPBXError, ConfigurationError
from src.sip_core.sip_endpoint import create_sip_endpoint
# AI Voicebot은 필요할 때만 import (lazy import)
# from src.ai_voicebot.factory import create_ai_orchestrator

# 전역 로거 (setup_logging 후에 사용)
logger = None


def print_immediate(*args, **kwargs):
    """즉시 출력되는 print 함수 (Windows 콘솔 버퍼링 방지)"""
    kwargs['flush'] = True
    print(*args, **kwargs)
    sys.stdout.flush()
    # Windows에서 추가 플러시
    if sys.platform == "win32":
        try:
            import msvcrt
            msvcrt.get_osfhandle(sys.stdout.fileno())
        except Exception:
            pass


def parse_args() -> argparse.Namespace:
    """명령줄 인자 파싱"""
    parser = argparse.ArgumentParser(
        description="SIP PBX with Real-time Voice Analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 기본 설정 파일로 시작
  python src/main.py
  
  # 커스텀 설정 파일 지정
  python src/main.py --config /path/to/config.yaml
  
  # 특정 포트로 시작
  python src/main.py --port 5061
"""
    )
    
    parser.add_argument(
        '--config',
        type=str,
        default=None,
        help='설정 파일 경로 (기본: config/config.yaml)'
    )
    
    parser.add_argument(
        '--port',
        type=int,
        default=None,
        help='SIP 서버 포트 (설정 파일 오버라이드)'
    )
    
    parser.add_argument(
        '--log-level',
        type=str,
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        default=None,
        help='로그 레벨 (설정 파일 오버라이드)'
    )
    
    parser.add_argument(
        '--version',
        action='version',
        version='%(prog)s 0.1.0'
    )
    
    return parser.parse_args()


def load_configuration(config_path: str = None) -> Config:
    """설정 로드
    
    Args:
        config_path: 설정 파일 경로
        
    Returns:
        Config: 로드된 설정
        
    Raises:
        ConfigurationError: 설정 로드 실패 시
    """
    try:
        config = load_config(config_path)
        return config
    except FileNotFoundError as e:
        print_immediate(f"❌ 설정 파일을 찾을 수 없습니다: {e}", file=sys.stderr)
        print_immediate("💡 config/config.example.yaml을 config/config.yaml로 복사하세요.", 
              file=sys.stderr)
        raise ConfigurationError(str(e)) from e
    except Exception as e:
        print_immediate(f"❌ 설정 로드 실패: {e}", file=sys.stderr)
        raise ConfigurationError(str(e)) from e


def apply_cli_overrides(config: Config, args: argparse.Namespace) -> Config:
    """CLI 인자로 설정 오버라이드
    
    Args:
        config: 기본 설정
        args: CLI 인자
        
    Returns:
        Config: 오버라이드된 설정
    """
    if args.port:
        config.sip.listen_port = args.port
    
    if args.log_level:
        config.logging.level = args.log_level
    
    return config


def initialize_logging(config: Config) -> None:
    """로깅 초기화 (동기 컨텍스트에서 호출).

    structlog를 app.log(또는 stdout)로 설정합니다.
    비동기 로그 워커(start_async_logging)는 이벤트 루프가 시작된 후
    run_server() 내에서 별도로 시작합니다.
    """
    setup_logging(
        level=config.logging.level,
        format_type=config.logging.format,
        output=config.logging.output,
        file_path=getattr(config.logging, "file_path", None),
    )

    global logger
    # ✅ 동기 로거 사용 (get_async_logger는 이벤트 루프 블로킹 시 로그 누락됨)
    logger = get_logger(__name__)


def print_banner(config: Config, ai_voicebot_enabled: bool = False) -> None:
    """시작 배너 출력 (Windows 버퍼링 방지)"""
    import time
    banner = f"""
╔═══════════════════════════════════════════════════════════════════════╗
║                                                                       ║
║   SIP PBX with Real-time Voice Analysis & AI Voicebot               ║
║   Version: 0.2.0                                                      ║
║                                                                       ║
╚═══════════════════════════════════════════════════════════════════════╝

⏱️  [{time.strftime('%H:%M:%S')}] 서버 시작 중...

Configuration:
  • SIP Server: {config.sip.listen_ip}:{config.sip.listen_port} ({config.sip.transport.upper()})
  • Media Mode: {config.media.mode.upper()}
  • Port Pool: {config.media.port_pool.start}-{config.media.port_pool.end}
  • AI Analysis: {'ENABLED' if config.ai.enabled else 'DISABLED'}
  • AI Voicebot: {'✅ ENABLED' if ai_voicebot_enabled else 'DISABLED'}
  • Log Level: {config.logging.level}
"""
    # ✅ Windows 버퍼링 방지: 즉시 출력
    print_immediate(banner)


async def run_server(config: Config) -> int:
    """서버 실행
    
    Args:
        config: 설정
        
    Returns:
        int: 종료 코드 (0 = 성공, 1 = 실패)
    """
    import time

    # ✅ 비동기 로그 워커 시작 (이벤트 루프 내에서만 create_task 가능)
    # initialize_logging()은 동기 컨텍스트에서 호출되므로 여기서 시작합니다.
    start_async_logging(queue_size=1000)

    start_time = time.time()
    
    sip_endpoint = None
    ai_orchestrator = None
    pipecat_builder = None  # Pipecat Pipeline Builder (Phase 1)
    ai_ready = False  # AI 준비 상태
    ai_voicebot_config = getattr(config, 'ai_voicebot', None)  # ⭐ 외부 스코프로 이동
    
    # 백그라운드 AI Voicebot 초기화
    async def initialize_ai_in_background():
        """AI Voicebot을 백그라운드에서 초기화하고 완료 알림"""
        nonlocal ai_orchestrator, pipecat_builder, ai_ready
        ai_start = time.time()
        try:
            print_immediate("🔄 [AI Background] AI Voicebot 백그라운드 초기화 시작...")
            logger.info("ai_voicebot_background_init_starting",
                       message="AI Voicebot 백그라운드 초기화 시작",
                       note="서버는 즉시 시작되며, AI는 백그라운드에서 로딩됩니다")

            # DB 로깅 (config.ai_voicebot.logging.db_url 있으면 asyncpg로 연결 후 RAG/LLM 로깅 활성화)
            try:
                from src.ai_voicebot.logging import ai_logger
                await ai_logger.try_init_db_from_config(config)
            except Exception as db_log_err:
                logger.warning("ai_db_logging_init_skipped", error=str(db_log_err))

            from src.ai_voicebot.factory import create_ai_orchestrator
            
            # Pydantic 모델을 dict로 변환
            # ai_voicebot_config는 이미 외부 스코프에 정의됨
            if hasattr(ai_voicebot_config, 'model_dump'):
                ai_config_dict = ai_voicebot_config.model_dump()
            elif hasattr(ai_voicebot_config, 'dict'):
                ai_config_dict = ai_voicebot_config.dict()
            else:
                ai_config_dict = dict(ai_voicebot_config)
            
            logger.info("ai_background_factory_calling",
                       config_keys=list(ai_config_dict.keys()) if isinstance(ai_config_dict, dict) else "non-dict")
            
            ai_orchestrator = await create_ai_orchestrator(ai_config_dict)
            
            ai_elapsed = time.time() - ai_start
            
            if ai_orchestrator:
                ai_ready = True
                
                # ✅ CallManager에 AI Orchestrator 동적 주입
                if sip_endpoint and sip_endpoint.call_manager:
                    sip_endpoint.call_manager.set_ai_orchestrator(ai_orchestrator)
                    logger.info("ai_orchestrator_connected_to_call_manager")
                    print_immediate(f"✅ [AI Background] AI Orchestrator → CallManager 주입 완료 ({ai_elapsed:.1f}s)")
                else:
                    logger.warning("ai_orchestrator_ready_but_no_call_manager",
                                 has_sip_endpoint=sip_endpoint is not None,
                                 has_call_manager=hasattr(sip_endpoint, 'call_manager') if sip_endpoint else False)
                    print_immediate(f"⚠️  [AI Background] AI Orchestrator 생성됨, 하지만 CallManager를 찾을 수 없음")
                
                # ✅ Pipecat Pipeline Builder 초기화 (Phase 1)
                try:
                    # 🔥 Google STT/TTS Service 사전 초기화 (통화 시 19초 지연 제거)
                    from src.ai_voicebot.factory import get_or_create_google_stt_service, get_or_create_google_tts_service
                    
                    stt_warmup_start = time.time()
                    print_immediate("🔥 [AI Background] Google STT/TTS Service 사전 초기화 중... (19초 예상)")
                    
                    # STT/TTS를 병렬로 초기화 (설정에서 language_code 등 반영 — 한글 인식 정확도)
                    stt_cfg = (ai_config_dict or {}).get("google_cloud", {}).get("stt", {}) or {}
                    if isinstance(stt_cfg, dict) and "language_code" not in stt_cfg:
                        stt_cfg = {**stt_cfg, "language_code": "ko-KR"}
                    stt_task = asyncio.create_task(get_or_create_google_stt_service(stt_cfg))
                    tts_task = asyncio.create_task(get_or_create_google_tts_service())
                    await asyncio.gather(stt_task, tts_task)
                    
                    warmup_elapsed = time.time() - stt_warmup_start
                    logger.info("google_services_warmup_complete",
                               elapsed=f"{warmup_elapsed:.2f}s",
                               note="통화 시 즉시 사용 가능 (지연 없음)")
                    print_immediate(f"✅ [AI Background] Google STT/TTS Service 준비 완료 ({warmup_elapsed:.1f}s)")
                    
                    from src.ai_voicebot.factory import create_pipecat_pipeline_builder
                    pipecat_builder = await create_pipecat_pipeline_builder(ai_config_dict)
                    if pipecat_builder and sip_endpoint and sip_endpoint.call_manager:
                        sip_endpoint.call_manager.set_pipecat_builder(pipecat_builder)
                        logger.info("pipecat_builder_connected_to_call_manager",
                                   engine="pipecat")
                        print_immediate("✅ [AI Background] Pipecat Pipeline Builder 연결 완료")
                except Exception as pipecat_err:
                    logger.info("pipecat_builder_not_available",
                               reason=str(pipecat_err),
                               message="Falling back to legacy orchestrator")
                    print_immediate(f"ℹ️  [AI Background] Pipecat 미사용: {pipecat_err}")
                
                logger.info("ai_voicebot_ready",
                           elapsed=f"{ai_elapsed:.2f}s",
                           ai_ready=True,
                           pipeline_engine="pipecat" if pipecat_builder else "legacy",
                           features=["AI 통화 기능", "VectorDB 지식 베이스", "실시간 STT/TTS"])
                # 부재중 터크오버 시 ai_orchestrator_not_available 원인 점검용: "AI 준비 완료" 명시 로그
                if sip_endpoint and sip_endpoint.call_manager:
                    cm = sip_endpoint.call_manager
                    logger.info("ai_readiness_after_background_init",
                               ai_orchestrator_set=cm.ai_orchestrator is not None,
                               pipecat_builder_set=cm.pipecat_builder is not None,
                               note="이 로그가 있으면 부재중 시 AI 터크오버 가능. 없으면 초기화 타임아웃/실패.")
                print_immediate(f"🎉 [AI Background] AI Voicebot 준비 완료! ({ai_elapsed:.1f}s)")
            else:
                logger.warning("ai_voicebot_init_failed",
                             message="AI Voicebot initialization failed or disabled",
                             elapsed=f"{ai_elapsed:.2f}s")
                print_immediate(f"❌ [AI Background] AI Voicebot 초기화 실패 (factory returned None, {ai_elapsed:.1f}s)")
        except Exception as e:
            ai_elapsed = time.time() - ai_start
            logger.error("ai_voicebot_background_init_error",
                       error=str(e),
                       error_type=type(e).__name__,
                       elapsed=f"{ai_elapsed:.2f}s",
                       message="AI Voicebot 초기화 실패, 서버는 AI Voicebot 없이 계속 작동합니다",
                       exc_info=True)
            print_immediate(f"❌ [AI Background] AI Voicebot 초기화 예외: {type(e).__name__}: {e}")
    
    try:
        # SIP Endpoint 생성 (AI Orchestrator 전달)
        logger.info("sip_endpoint_creation_starting", message="SIP Endpoint 생성 시작")
        sip_start = time.time()
        
        logger.info("creating_sip_endpoint", message="Creating SIP endpoint")
        
        # config에 ai_orchestrator 추가 (아직 None일 수 있음)
        if ai_orchestrator:
            config._ai_orchestrator = ai_orchestrator
        
        sip_endpoint = create_sip_endpoint(config)
        
        sip_elapsed = time.time() - sip_start
        logger.info("sip_endpoint_created",
                   elapsed=f"{sip_elapsed:.3f}s",
                   message="SIP Endpoint 생성 완료")
        
        # ⭐ AI Voicebot 백그라운드 초기화 (대기)
        if ai_voicebot_config:
            logger.info("🚀 [MAIN] Starting AI Voicebot initialization...")
            print_immediate("🚀 [MAIN] AI Voicebot 초기화 중... (최대 60초 대기)")
            ai_bg_task = asyncio.create_task(initialize_ai_in_background())
            
            try:
                # ⭐ AI 준비 대기 (최대 60초)
                await asyncio.wait_for(ai_bg_task, timeout=60.0)
                logger.info("✅ [MAIN] AI Voicebot 준비 완료, SIP 서버 시작")
                print_immediate("✅ [MAIN] AI Voicebot 준비 완료!")
            except asyncio.TimeoutError:
                logger.warning("ai_init_timeout_60s",
                             message="AI Voicebot 초기화 60초 타임아웃, SIP 서버 강제 시작",
                             note="부재중 터크오버 시 ai_orchestrator_not_available 원인. AI 초기화가 60초 초과 시 발생.")
                print_immediate("⚠️ [MAIN] AI 초기화 타임아웃, 서버는 AI 없이 시작됩니다")
            except Exception as e:
                logger.error("❌ [MAIN] AI Voicebot 초기화 실패", error=str(e), exc_info=True)
                print_immediate(f"❌ [MAIN] AI 초기화 실패: {e}")
        else:
            logger.info("ai_voicebot_disabled", message="AI Voicebot 비활성화됨 (config.ai_voicebot is None)")
        
        # ✅ AI 준비 여부 명시 로그 (no_answer 시 ai_orchestrator_not_available 원인 점검용)
        if sip_endpoint and sip_endpoint.call_manager:
            cm = sip_endpoint.call_manager
            logger.info("ai_readiness_at_startup",
                       ai_orchestrator_set=cm.ai_orchestrator is not None,
                       pipecat_builder_set=cm.pipecat_builder is not None,
                       note="둘 다 False면 부재중 타임아웃 시 ai_orchestrator_not_available 발생. docs/reports/AI_ORCHESTRATOR_NONE_ROOT_CAUSE.md 참고.")
        
        # SIP 서버 시작 (UDP 소켓 바인딩) - AI 준비 완료 후
        logger.info("sip_server_starting", message="UDP 소켓 바인딩 시작")
        server_start = time.time()
        
        logger.info("starting_sip_server", message="Starting SIP server")
        sip_endpoint.start()
        
        server_elapsed = time.time() - server_start
        logger.info("sip_server_started",
                   elapsed=f"{server_elapsed:.3f}s",
                   message="UDP 소켓 바인딩 완료")
        
        # API/WebSocket에서 활성 통화 조회 가능하도록 CallManager 주입 (대시보드 실시간 통화 목록용)
        try:
            from src.api.routers import calls as api_calls_router
            from src.websocket import server as ws_server
            api_calls_router.set_call_manager(sip_endpoint.call_manager)
            ws_server.set_call_manager(sip_endpoint.call_manager)
            logger.info("call_manager_injected_for_api_and_ws")
        except Exception as e:
            logger.warning("call_manager_inject_failed", error=str(e), message="대시보드 활성 통화 목록이 동작하지 않을 수 있음")

        # HITL: timeout 시 AI가 다시 연결받아 안내 메시지 전달 (통화 종료하지 않음)
        async def handle_hitl_timeout(call_id: str):
            """HITL 타임아웃 시 AI가 다시 연결받아 안내 메시지 전달"""
            try:
                import structlog
                timeout_logger = structlog.get_logger(__name__)
                timeout_logger.warning("hitl_timeout_ai_reconnect", call_id=call_id,
                                      message="운영자 미응답 - AI가 다시 연결받아 안내")
                
                # 응답 큐에 timeout 메시지 전달 (RAGProcessor가 소비)
                from src.services.hitl import get_hitl_service
                response_queue = get_hitl_service().get_response_queue(call_id)
                
                if response_queue:
                    # LLM에게 상황 설명 요청하여 자연스러운 안내 메시지 생성
                    timeout_message = {
                        "type": "hitl_timeout",
                        "text": "담당자 연결을 시도했으나 현재 확인이 어려운 상황입니다. 확인 후 다시 연락드리도록 하겠습니다.",
                        "call_id": call_id,
                        "needs_llm_refinement": True,  # LLM으로 다듬기 필요
                    }
                    await response_queue.put(timeout_message)
                    timeout_logger.info("hitl_timeout_message_queued", call_id=call_id)
                else:
                    timeout_logger.warning("hitl_timeout_no_queue", call_id=call_id)
            except Exception as e:
                import structlog
                timeout_logger = structlog.get_logger(__name__)
                timeout_logger.error("hitl_timeout_handler_failed", call_id=call_id, error=str(e))
        
        try:
            from src.services.hitl import get_hitl_service
            hitl_svc = get_hitl_service()
            hitl_svc.register_on_hitl_timeout(handle_hitl_timeout)
            ai_cfg = getattr(config, "ai_voicebot", None)
            hitl_cfg = getattr(ai_cfg, "hitl", None) if ai_cfg else None
            if isinstance(hitl_cfg, dict):
                ts = hitl_cfg.get("timeout_seconds")
                msg = hitl_cfg.get("timeout_message") or hitl_cfg.get("away_message")
                hitl_svc.set_config(timeout_seconds=ts, timeout_message=msg)
            logger.info("hitl_timeout_callback_registered", behavior="ai_reconnect")
        except Exception as e:
            logger.warning("hitl_timeout_register_failed", error=str(e))
        
        # Chroma 초기 데이터는 scripts/seed_data.py·수동 API 등으로만 적재 (기동 시 자동 시드 없음)

        # 같은 프로세스에서 API 서버 기동 (GET /api/calls/active가 CallManager를 사용하려면 필요)
        _api_port = getattr(config, 'api_port', None) or getattr(getattr(config, 'api', None), 'port', None) or 8000
        try:
            # 🔥 Knowledge API용 embedder 설정
            try:
                from src.api.knowledge_router import set_knowledge_embedder
                from src.ai_voicebot.knowledge.embedder import get_text_embedder
                _embedder = get_text_embedder()
                set_knowledge_embedder(_embedder)
                logger.info("knowledge_embedder_configured_for_api")
            except Exception as emb_err:
                logger.warning("knowledge_embedder_config_failed", error=str(emb_err))
            
            import threading
            def _run_api_server():
                import uvicorn
                from src.api.main import app
                uvicorn.run(app, host="0.0.0.0", port=_api_port, log_level="info")
            _api_thread = threading.Thread(target=_run_api_server, daemon=True)
            _api_thread.start()
            logger.info("api_server_started_in_process", port=_api_port)
            print_immediate(f"  • API Gateway: http://0.0.0.0:{_api_port} (대시보드 활성 통화 연동)")
        except Exception as e:
            logger.warning("api_server_start_failed", error=str(e), port=_api_port)
            print_immediate(f"  • API Gateway: 시작 실패 ({e}) — 별도로 python -m src.api.main 실행 시 포트 충돌 가능")

        # WebSocket 서버 기동 (실시간 대화 STT/TTS 표시용) — 별도 스레드에서 실행해 메인 루프와 태스크 생명주기 분리 (destroyed but pending 방지)
        _ws_port = 8001
        try:
            import threading
            def _run_websocket_server():
                import asyncio
                from src.websocket.server import start_server
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(start_server())
                finally:
                    loop.close()
            _ws_thread = threading.Thread(target=_run_websocket_server, daemon=True)
            _ws_thread.start()
            logger.info("websocket_server_started_in_process", port=_ws_port)
            print_immediate(f"  • WebSocket: http://0.0.0.0:{_ws_port} (실시간 대화 연동)")
        except Exception as e:
            logger.warning("websocket_server_start_failed", error=str(e), port=_ws_port)
            print_immediate(f"  • WebSocket: 시작 실패 ({e}) — 실시간 대화가 표시되지 않을 수 있음")

        total_elapsed = time.time() - start_time
        
        # ✅ 즉시 출력
        print_immediate(f"\n{'='*70}")
        print_immediate(f"⏱️  [{time.strftime('%H:%M:%S')}] ⭐ 서버 시작 완료!")
        print_immediate(f"{'='*70}")
        print_immediate(f"  • 전체 시작 시간: {total_elapsed:.3f}초")
        if ai_orchestrator:
            print_immediate(f"  • AI Voicebot: ✅ 활성화")
        else:
            print_immediate(f"  • AI Voicebot: ⏳ 백그라운드 로딩 중... (수십 초 소요)")
        print_immediate(f"  • SIP 서버: {config.sip.listen_ip}:{config.sip.listen_port}")
        print_immediate(f"  • 미디어 모드: {config.media.mode.upper()}")
        print_immediate(f"  • Health Check: http://localhost:{config.monitoring.health_check_port}/health")
        print_immediate(f"{'='*70}\n")
        
        # ✅ sys.stdout 명시적 플러시 (Windows 호환성)
        sys.stdout.flush()
        
        logger.info(f"🔧 [TIMING] ⭐ TOTAL STARTUP TIME: {total_elapsed:.2f}s")
        
        logger.info("server_ready", 
                   message="SIP PBX is ready to accept calls",
                   sip_port=config.sip.listen_port,
                   health_check_port=config.monitoring.health_check_port,
                   ai_voicebot_enabled=ai_orchestrator is not None,
                   startup_time=f"{total_elapsed:.2f}s")
        
        print_immediate(f"Press Ctrl+C to stop the server.\n")
        
        # 메인 루프 (서버가 실행 중인 동안 대기)
        while sip_endpoint.is_running():
            await asyncio.sleep(1)
        
        return 0
        
    except KeyboardInterrupt:
        logger.info("keyboard_interrupt", message="Received Ctrl+C, shutting down")
        print_immediate("\n\n🛑 Shutting down...")
        return 0
    
    except SIPPBXError as e:
        logger.error("sip_pbx_error", error=str(e), exc_info=True)
        print_immediate(f"\n❌ SIP PBX Error: {e}", file=sys.stderr)
        return 1
    
    except Exception as e:
        logger.critical("unexpected_error", error=str(e), exc_info=True)
        print_immediate(f"\n❌ Unexpected Error: {e}", file=sys.stderr)
        return 1
        
    finally:
        # 정리
        if sip_endpoint and sip_endpoint.is_running():
            logger.info("stopping_server", message="Stopping SIP server")
            try:
                sip_endpoint.stop()
            except Exception as e:
                logger.error("stop_failed", error=str(e))
        
        # 비동기 로깅 중지
        try:
            await stop_async_logging()
        except Exception as e:
            print_immediate(f"Warning: Failed to stop async logging: {e}", file=sys.stderr)
        
        logger.info("server_stopped", message="SIP PBX stopped")
        print_immediate("\n✅ Server stopped successfully.\n")


def main() -> int:
    """메인 함수
    
    Returns:
        int: 종료 코드
    """
    try:
        # CLI 인자 파싱
        args = parse_args()
        
        # 설정 로드
        config = load_configuration(args.config)
        
        # CLI 오버라이드 적용
        config = apply_cli_overrides(config, args)
        
        # 로깅 초기화
        initialize_logging(config)
        
        # AI Voicebot 활성화 체크
        ai_voicebot_enabled = False
        ai_voicebot_config = getattr(config, 'ai_voicebot', None)
        if ai_voicebot_config:
            ai_voicebot_enabled = getattr(ai_voicebot_config, 'enabled', False)
        
        # 배너 출력
        print_banner(config, ai_voicebot_enabled)
        
        # 서버 실행 (asyncio)
        return asyncio.run(run_server(config))
        
    except ConfigurationError:
        return 1
    except Exception as e:
        print_immediate(f"\n❌ Fatal Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

