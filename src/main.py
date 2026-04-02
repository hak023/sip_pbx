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


def _apply_env_file(path: Path) -> None:
    """프로젝트 루트 .env → os.environ (이미 설정된 키는 유지). python-dotenv 없이 최소 파싱."""
    try:
        if not path.is_file():
            return
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if not key:
            continue
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("\"", "'"):
            val = val[1:-1]
        if key not in os.environ:
            os.environ[key] = val


_apply_env_file(project_root / ".env")

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

    # AI Voicebot 활성 시 초기화(오케스트레이터·STT/TTS 워밍업 등)가 끝나야 SIP·부가 서비스를 띄움
    AI_STARTUP_TIMEOUT_SEC = 120.0

    # ✅ 비동기 로그 워커 시작 (이벤트 루프 내에서만 create_task 가능)
    # initialize_logging()은 동기 컨텍스트에서 호출되므로 여기서 시작합니다.
    start_async_logging(queue_size=1000)

    start_time = time.time()
    
    sip_endpoint = None
    ai_orchestrator = None
    pipecat_builder = None  # Pipecat Pipeline Builder (Phase 1)
    ai_ready = False  # AI 준비 상태
    ai_voicebot_config = getattr(config, 'ai_voicebot', None)  # ⭐ 외부 스코프로 이동
    ai_voicebot_enabled = False  # SIP 바인딩 전에 AI 필수 초기화 여부 (배너·종료 코드용)
    
    # 백그라운드 AI Voicebot 초기화
    async def initialize_ai_in_background():
        """AI Voicebot을 백그라운드에서 초기화하고 완료 알림"""
        nonlocal ai_orchestrator, pipecat_builder, ai_ready
        ai_start = time.time()
        try:
            print_immediate("🔄 [AI Background] AI Voicebot 백그라운드 초기화 시작...")
            logger.info(
                "ai_voicebot_background_init_starting",
                message="AI Voicebot 초기화 시작",
                note="enabled=True일 때 이 단계가 끝나야 SIP·API·WS가 시작됩니다.",
            )

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
                
                # ✅ CallManager에 AI Orchestrator 동적 주입 (없으면 AI 통화 불가 → 기동 중단)
                if sip_endpoint and sip_endpoint.call_manager:
                    sip_endpoint.call_manager.set_ai_orchestrator(ai_orchestrator)
                    logger.info("ai_orchestrator_connected_to_call_manager")
                    print_immediate(f"✅ [AI Background] AI Orchestrator → CallManager 주입 완료 ({ai_elapsed:.1f}s)")
                else:
                    logger.error(
                        "startup_fatal_ai_orchestrator_no_call_manager",
                        has_sip_endpoint=sip_endpoint is not None,
                        has_call_manager=hasattr(sip_endpoint, "call_manager") if sip_endpoint else False,
                        message="AI는 켜져 있으나 CallManager에 주입할 수 없음. 준비 실패로 종료합니다.",
                    )
                    print_immediate(
                        "❌ [AI Background] CallManager 없음 — AI Voicebot을 켠 상태에서는 기동할 수 없습니다.",
                        file=sys.stderr,
                    )
                    raise RuntimeError("AI orchestrator ready but CallManager missing for injection")

                # 🔥 Google STT/TTS 사전 초기화 — AI 활성 시 필수 (실패 시 반쯤 떠 있는 상태 방지)
                from src.ai_voicebot.factory import get_or_create_google_stt_service, get_or_create_google_tts_service

                stt_warmup_start = time.time()
                print_immediate("🔥 [AI Background] Google STT/TTS Service 사전 초기화 중...")
                stt_cfg = (ai_config_dict or {}).get("google_cloud", {}).get("stt", {}) or {}
                if isinstance(stt_cfg, dict) and "language_code" not in stt_cfg:
                    stt_cfg = {**stt_cfg, "language_code": "ko-KR"}
                stt_task = asyncio.create_task(get_or_create_google_stt_service(stt_cfg))
                tts_task = asyncio.create_task(get_or_create_google_tts_service())
                try:
                    await asyncio.gather(stt_task, tts_task)
                except Exception as stt_err:
                    logger.error(
                        "startup_fatal_google_stt_tts_warmup",
                        error=str(stt_err),
                        error_type=type(stt_err).__name__,
                        message="Google STT/TTS 준비 실패 — 통화 AI가 동작하지 않습니다. 기동 중단.",
                        exc_info=True,
                    )
                    print_immediate(
                        f"❌ [AI Background] Google STT/TTS 초기화 실패: {stt_err}",
                        file=sys.stderr,
                    )
                    raise

                warmup_elapsed = time.time() - stt_warmup_start
                logger.info(
                    "google_services_warmup_complete",
                    elapsed=f"{warmup_elapsed:.2f}s",
                    note="통화 시 즉시 사용 가능 (지연 없음)",
                )
                print_immediate(f"✅ [AI Background] Google STT/TTS Service 준비 완료 ({warmup_elapsed:.1f}s)")

                # ✅ Pipecat Pipeline Builder — 선택 (실패해도 레거시 오케스트레이터 유지)
                try:
                    from src.ai_voicebot.factory import create_pipecat_pipeline_builder

                    pipecat_builder = await create_pipecat_pipeline_builder(ai_config_dict)
                    if pipecat_builder and sip_endpoint and sip_endpoint.call_manager:
                        sip_endpoint.call_manager.set_pipecat_builder(pipecat_builder)
                        logger.info("pipecat_builder_connected_to_call_manager", engine="pipecat")
                        print_immediate("✅ [AI Background] Pipecat Pipeline Builder 연결 완료")
                except Exception as pipecat_err:
                    logger.info(
                        "pipecat_builder_not_available",
                        reason=str(pipecat_err),
                        message="Falling back to legacy orchestrator",
                    )
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
                logger.error(
                    "startup_fatal_ai_orchestrator_none",
                    elapsed=f"{ai_elapsed:.2f}s",
                    message="create_ai_orchestrator가 None 반환 (enabled=True인데 팩토리 실패). 기동 중단.",
                )
                print_immediate(
                    f"❌ [AI Background] AI Voicebot 팩토리가 None을 반환했습니다 ({ai_elapsed:.1f}s).",
                    file=sys.stderr,
                )
                raise RuntimeError("create_ai_orchestrator returned None while AI Voicebot is enabled")
        except Exception as e:
            ai_elapsed = time.time() - ai_start
            logger.error(
                "ai_voicebot_background_init_error",
                error=str(e),
                error_type=type(e).__name__,
                elapsed=f"{ai_elapsed:.2f}s",
                message="AI Voicebot 초기화 실패 — 프로세스를 종료합니다",
                exc_info=True,
            )
            print_immediate(f"❌ [AI Background] AI Voicebot 초기화 예외: {type(e).__name__}: {e}", file=sys.stderr)
            raise
    
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
        
        # ⭐ AI Voicebot 초기화 (enabled=True일 때만 필수 성공)
        ai_voicebot_enabled = bool(
            ai_voicebot_config and getattr(ai_voicebot_config, "enabled", False)
        )
        if ai_voicebot_enabled:
            logger.info("🚀 [MAIN] Starting AI Voicebot initialization (required for startup)...")
            print_immediate(
                f"🚀 [MAIN] AI Voicebot 초기화 중... (최대 {int(AI_STARTUP_TIMEOUT_SEC)}초, 실패 시 프로세스 종료)"
            )
            ai_bg_task = asyncio.create_task(initialize_ai_in_background())

            try:
                await asyncio.wait_for(ai_bg_task, timeout=AI_STARTUP_TIMEOUT_SEC)
            except asyncio.TimeoutError:
                logger.error(
                    "startup_fatal_ai_init_timeout",
                    timeout_sec=AI_STARTUP_TIMEOUT_SEC,
                    message="AI Voicebot 초기화 시간 초과. SIP를 띄우지 않고 종료합니다.",
                    note="타임아웃을 늘리려면 src/main.py 의 AI_STARTUP_TIMEOUT_SEC 를 조정하세요.",
                )
                print_immediate(
                    f"❌ [MAIN] AI 초기화 {int(AI_STARTUP_TIMEOUT_SEC)}초 타임아웃 — 기동을 중단합니다.",
                    file=sys.stderr,
                )
                ai_bg_task.cancel()
                try:
                    await ai_bg_task
                except (asyncio.CancelledError, Exception):
                    pass
                return 1
            except Exception as e:
                logger.error(
                    "startup_fatal_ai_init_failed",
                    error=str(e),
                    error_type=type(e).__name__,
                    message="AI Voicebot 초기화 실패. SIP를 띄우지 않고 종료합니다.",
                    exc_info=True,
                )
                print_immediate(f"❌ [MAIN] AI 초기화 실패로 기동 중단: {e}", file=sys.stderr)
                return 1

            if not ai_orchestrator:
                logger.error(
                    "startup_fatal_ai_orchestrator_missing_after_init",
                    message="초기화 태스크는 끝났으나 ai_orchestrator 가 없습니다.",
                )
                print_immediate("❌ [MAIN] AI 오케스트레이터가 준비되지 않았습니다. 기동 중단.", file=sys.stderr)
                return 1

            logger.info("✅ [MAIN] AI Voicebot 준비 완료, SIP 서버 시작")
            print_immediate("✅ [MAIN] AI Voicebot 준비 완료!")
        elif ai_voicebot_config:
            logger.info(
                "ai_voicebot_config_present_but_disabled",
                message="config.ai_voicebot 있음, enabled=False — AI 초기화 생략",
            )
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
            logger.error(
                "startup_fatal_call_manager_inject_failed",
                error=str(e),
                error_type=type(e).__name__,
                message="CallManager API/WS 주입 실패 — 대시보드·활성 통화 연동 불가. 기동 중단.",
                exc_info=True,
            )
            print_immediate(f"❌ CallManager 주입 실패: {e} — SIP를 중지하고 종료합니다.", file=sys.stderr)
            try:
                sip_endpoint.stop()
            except Exception:
                pass
            return 1

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
                if ai_voicebot_enabled:
                    logger.error(
                        "startup_fatal_knowledge_embedder_failed",
                        error=str(emb_err),
                        error_type=type(emb_err).__name__,
                        message="AI 활성 시 Knowledge API용 embedder 필수. 기동 중단.",
                        exc_info=True,
                    )
                    print_immediate(f"❌ Knowledge embedder 설정 실패: {emb_err}", file=sys.stderr)
                    try:
                        sip_endpoint.stop()
                    except Exception:
                        pass
                    return 1
                logger.warning(
                    "knowledge_embedder_config_failed",
                    error=str(emb_err),
                    message="AI 비활성 — embedder 없이 계속. 지식 API는 동작하지 않을 수 있음.",
                )

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
            logger.error(
                "startup_fatal_api_server_thread_failed",
                error=str(e),
                error_type=type(e).__name__,
                port=_api_port,
                message="인프로세스 API 스레드 기동 실패. 기동 중단.",
                exc_info=True,
            )
            print_immediate(f"❌ API Gateway 스레드 시작 실패 ({e}) — SIP를 중지하고 종료합니다.", file=sys.stderr)
            try:
                sip_endpoint.stop()
            except Exception:
                pass
            return 1

        # help 캐시 자동 구성 — 서버 기동 직후 비동기 태스크로 스케줄
        # CLEAR_QA_CACHE_ON_START=1(기본값)로 인해 qa_cache가 이미 초기화된 후 실행되어야 함
        if ai_voicebot_enabled:
            try:
                from src.ai_voicebot.knowledge.knowledge_service import build_help_cache_on_startup
                from src.ai_voicebot.knowledge.chromadb_client import get_vector_db
                from src.ai_voicebot.knowledge.embedder import get_text_embedder as _get_embedder

                _help_vector_db = get_vector_db()
                _help_embedder = _get_embedder()

                # LLM 클라이언트 — question KB 자동 추출용 (없으면 help KB 직접 입력만 사용)
                _help_llm = None
                try:
                    from src.ai_voicebot.ai_pipeline.llm_client import LLMClient
                    _help_llm = LLMClient()
                except Exception:
                    pass

                # 등록된 모든 owner(테넌트)에 대해 help 캐시 구성
                # owner 목록: config에 명시된 내선번호 또는 ChromaDB에서 조회
                _help_owners: list = []
                try:
                    _cfg_extensions = getattr(getattr(config, "sip", None), "extensions", None) or []
                    _help_owners = [str(ext) for ext in _cfg_extensions if ext]
                except Exception:
                    pass

                if _help_owners and _help_vector_db and _help_embedder:
                    import asyncio as _asyncio

                    async def _run_help_cache_startup():
                        import asyncio
                        for _owner in _help_owners:
                            try:
                                await build_help_cache_on_startup(
                                    vector_db=_help_vector_db,
                                    embedder=_help_embedder,
                                    llm=_help_llm,
                                    owner=_owner,
                                )
                            except Exception as _e:
                                logger.warning(
                                    "help_cache_startup_owner_failed",
                                    owner=_owner,
                                    error=str(_e),
                                )
                        logger.info("help_cache_startup_all_done", owners=_help_owners)

                    # 메인 이벤트 루프에 태스크 등록 (2초 딜레이 — qa_cache 초기화 완료 후 실행)
                    async def _delayed_help_cache():
                        await _asyncio.sleep(2.0)
                        await _run_help_cache_startup()

                    _asyncio.ensure_future(_delayed_help_cache())
                    logger.info(
                        "help_cache_startup_scheduled",
                        owners=_help_owners,
                        note="2초 후 help 캐시 자동 구성 예정",
                    )
                else:
                    logger.info(
                        "help_cache_startup_skipped",
                        has_owners=bool(_help_owners),
                        has_vector_db=bool(_help_vector_db),
                        has_embedder=bool(_help_embedder),
                    )
            except Exception as _he:
                logger.warning("help_cache_startup_schedule_failed", error=str(_he))

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
            logger.error(
                "startup_fatal_websocket_thread_failed",
                error=str(e),
                error_type=type(e).__name__,
                port=_ws_port,
                message="WebSocket 서버 스레드 기동 실패. 기동 중단.",
                exc_info=True,
            )
            print_immediate(
                f"❌ WebSocket 서버 시작 실패 ({e}) — SIP/API를 중지하고 종료합니다.",
                file=sys.stderr,
            )
            try:
                sip_endpoint.stop()
            except Exception:
                pass
            return 1

        total_elapsed = time.time() - start_time
        
        # ✅ 즉시 출력
        print_immediate(f"\n{'='*70}")
        print_immediate(f"⏱️  [{time.strftime('%H:%M:%S')}] ⭐ 서버 시작 완료!")
        print_immediate(f"{'='*70}")
        print_immediate(f"  • 전체 시작 시간: {total_elapsed:.3f}초")
        if ai_voicebot_enabled:
            print_immediate("  • AI Voicebot: ✅ 활성화 (기동 시점에 준비 완료)")
        elif ai_voicebot_config:
            print_immediate("  • AI Voicebot: 설정만 있음 (enabled=False)")
        else:
            print_immediate("  • AI Voicebot: 비활성화")
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
                   ai_voicebot_enabled=ai_voicebot_enabled,
                   ai_orchestrator_ready=ai_orchestrator is not None,
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
        # 서버 종료 후 잔류 태스크가 이미 닫힌 로그 파일에 write를 시도할 때
        # "I/O operation on closed file" ValueError가 여기까지 전파될 수 있다.
        # 이는 정상 종료 시퀀스의 일부이므로 조용히 처리한다.
        err_msg = str(e)
        if "I/O operation on closed file" in err_msg or "closed file" in err_msg:
            return 0
        print_immediate(f"\n❌ Fatal Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

