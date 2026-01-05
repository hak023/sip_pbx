"""구조화된 로깅 설정

structlog을 사용한 JSON 구조화 로깅
"""

import sys
import structlog
from typing import Any, Dict
from pathlib import Path
from datetime import datetime, timezone, timedelta

from src.config.models import LogLevel, LogFormat

# 한국 시간대 (UTC+9)
KST = timezone(timedelta(hours=9))


def add_kst_timestamp(logger: Any, method_name: str, event_dict: Dict) -> Dict:
    """KST 타임스탬프를 추가하는 프로세서"""
    event_dict["timestamp"] = datetime.now(KST).isoformat()
    return event_dict


def setup_logging(level: str = "INFO", format_type: str = "json", output: str = "stdout") -> None:
    """로깅 설정 초기화
    
    Args:
        level: 로그 레벨 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        format_type: 로그 포맷 (json, text)
        output: 로그 출력 (stdout, file)
    """
    # 프로세서 체인 구성
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        add_kst_timestamp,  # KST 타임스탬프 (UTC+9)
    ]

    if format_type == "json":
        # JSON 포맷
        processors.append(structlog.processors.JSONRenderer())
    else:
        # 개발용 컬러 텍스트 포맷
        processors.append(structlog.dev.ConsoleRenderer(colors=True))

    # 파일 출력 설정
    if output == "file":
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / "app.log"
        log_stream = open(log_file, "a", encoding="utf-8")
    else:
        log_stream = sys.stdout
    
    # structlog 설정
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            _log_level_to_int(level)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=log_stream),
        cache_logger_on_first_use=True,
    )


def _log_level_to_int(level: str) -> int:
    """로그 레벨 문자열을 정수로 변환"""
    levels = {
        "DEBUG": 10,
        "INFO": 20,
        "WARNING": 30,
        "ERROR": 40,
        "CRITICAL": 50,
    }
    return levels.get(level.upper(), 20)  # 기본값: INFO


def get_logger(name: str) -> structlog.BoundLogger:
    """로거 인스턴스 반환
    
    Args:
        name: 로거 이름 (일반적으로 __name__)
        
    Returns:
        structlog.BoundLogger: 바운드 로거 인스턴스
        
    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("server_started", port=5060, ip="0.0.0.0")
    """
    return structlog.get_logger(name)


def log_with_context(**context: Any) -> structlog.BoundLogger:
    """컨텍스트가 바인딩된 로거 반환
    
    Args:
        **context: 로그에 포함할 컨텍스트 정보
        
    Returns:
        structlog.BoundLogger: 컨텍스트가 바인딩된 로거
        
    Example:
        >>> logger = log_with_context(call_id="abc-123", caller="alice")
        >>> logger.info("call_started")
        # {"event": "call_started", "call_id": "abc-123", "caller": "alice", ...}
    """
    return structlog.get_logger().bind(**context)

