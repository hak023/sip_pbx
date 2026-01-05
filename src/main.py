"""SIP PBX with Real-time Voice Analysis - Main Entry Point

애플리케이션 시작점
"""

import sys
import argparse
import asyncio
from pathlib import Path
import io

# UTF-8 인코딩 설정 (Windows에서 특수 문자 출력 지원)
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from src.config.config_loader import load_config
from src.config.models import Config
from src.common.logger import setup_logging, get_logger
from src.common.exceptions import SIPPBXError, ConfigurationError
from src.sip_core.sip_endpoint import create_sip_endpoint

# 전역 로거 (setup_logging 후에 사용)
logger = None


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
        print(f"❌ 설정 파일을 찾을 수 없습니다: {e}", file=sys.stderr)
        print("💡 config/config.example.yaml을 config/config.yaml로 복사하세요.", 
              file=sys.stderr)
        raise ConfigurationError(str(e)) from e
    except Exception as e:
        print(f"❌ 설정 로드 실패: {e}", file=sys.stderr)
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
    """로깅 초기화"""
    setup_logging(
        level=config.logging.level,
        format_type=config.logging.format,
        output=config.logging.output
    )
    
    global logger
    logger = get_logger(__name__)


def print_banner(config: Config) -> None:
    """시작 배너 출력"""
    banner = f"""
╔═══════════════════════════════════════════════════════════════════════╗
║                                                                       ║
║   SIP PBX with Real-time Voice Analysis                              ║
║   Version: 0.1.0                                                      ║
║                                                                       ║
╚═══════════════════════════════════════════════════════════════════════╝

Configuration:
  • SIP Server: {config.sip.listen_ip}:{config.sip.listen_port} ({config.sip.transport.upper()})
  • Media Mode: {config.media.mode.upper()}
  • Port Pool: {config.media.port_pool.start}-{config.media.port_pool.end}
  • AI Analysis: {'ENABLED' if config.ai.enabled else 'DISABLED'}
  • Log Level: {config.logging.level}

Starting server...
"""
    print(banner)


async def run_server(config: Config) -> int:
    """서버 실행
    
    Args:
        config: 설정
        
    Returns:
        int: 종료 코드 (0 = 성공, 1 = 실패)
    """
    sip_endpoint = None
    
    try:
        # SIP Endpoint 생성
        logger.info("creating_sip_endpoint", message="Creating SIP endpoint")
        sip_endpoint = create_sip_endpoint(config)
        
        # SIP 서버 시작
        logger.info("starting_sip_server", message="Starting SIP server")
        sip_endpoint.start()
        
        logger.info("server_ready", 
                   message="SIP PBX is ready to accept calls",
                   sip_port=config.sip.listen_port,
                   health_check_port=config.monitoring.health_check_port)
        
        print(f"\n✅ Server is running!")
        print(f"   SIP: {config.sip.listen_ip}:{config.sip.listen_port}")
        print(f"   Health Check: http://localhost:{config.monitoring.health_check_port}/health")
        print(f"\nPress Ctrl+C to stop the server.\n")
        
        # 메인 루프 (서버가 실행 중인 동안 대기)
        while sip_endpoint.is_running():
            await asyncio.sleep(1)
        
        return 0
        
    except KeyboardInterrupt:
        logger.info("keyboard_interrupt", message="Received Ctrl+C, shutting down")
        print("\n\n🛑 Shutting down...")
        return 0
        
    except SIPPBXError as e:
        logger.error("sip_pbx_error", error=str(e), exc_info=True)
        print(f"\n❌ SIP PBX Error: {e}", file=sys.stderr)
        return 1
        
    except Exception as e:
        logger.critical("unexpected_error", error=str(e), exc_info=True)
        print(f"\n❌ Unexpected Error: {e}", file=sys.stderr)
        return 1
        
    finally:
        # 정리
        if sip_endpoint and sip_endpoint.is_running():
            logger.info("stopping_server", message="Stopping SIP server")
            try:
                sip_endpoint.stop()
            except Exception as e:
                logger.error("stop_failed", error=str(e))
        
        logger.info("server_stopped", message="SIP PBX stopped")
        print("\n✅ Server stopped successfully.\n")


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
        
        # 배너 출력
        print_banner(config)
        
        # 서버 실행 (asyncio)
        return asyncio.run(run_server(config))
        
    except ConfigurationError:
        return 1
    except Exception as e:
        print(f"\n❌ Fatal Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

