"""구조화된 로깅 설정

structlog을 사용한 JSON 구조화 로깅
비동기 로깅 지원 (asyncio.Queue 기반)
"""

import sys
import asyncio
import structlog
from typing import Any, Dict, Optional, Callable
from pathlib import Path
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass

from src.config.models import LogLevel, LogFormat

# 한국 시간대 (UTC+9)
KST = timezone(timedelta(hours=9))

# 비동기 로그 큐 및 워커 태스크
_log_queue: Optional[asyncio.Queue] = None
_log_worker_task: Optional[asyncio.Task] = None
_sync_logger: Optional[structlog.BoundLogger] = None


def add_kst_timestamp(logger: Any, method_name: str, event_dict: Dict) -> Dict:
    """KST 타임스탬프를 추가하는 프로세서 (밀리초 3자리까지, 타임존 표시 없음)"""
    now = datetime.now(KST)
    # ISO 형식에서 마이크로초를 밀리초(3자리)로 제한
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%S")
    milliseconds = f"{now.microsecond / 1000:.0f}".zfill(3)
    # 타임존 표시 제거 (KST는 항상 UTC+9로 고정)
    event_dict["timestamp"] = f"{timestamp}.{milliseconds}"
    return event_dict


def call_event_to_key(logger: Any, method_name: str, event_dict: Dict) -> Dict:
    """통화 관련 로그: call=True인 경우 'call' 키에 이벤트 이름을 넣고 event 키 제거.
    
    원하는 출력: "call": "greeting_phase1_sent" (event 키 대신 call에 이벤트명 표시)
    """
    if event_dict.get("call") is True and "event" in event_dict:
        event_dict["call"] = event_dict.pop("event")
    return event_dict


def reorder_keys(logger: Any, method_name: str, event_dict: Dict) -> Dict:
    """로그 키 순서를 가독성 좋게 재정렬하는 프로세서
    
    순서:
    1. timestamp (시간순 정렬 가능)
    2. level (로그 레벨)
    3. call (통화 로그 시 이벤트 이름, 그 외 event)
    4. progress (주요 진행 구분: llm | stt | tts | rag | call)
    5. call_id (통화 추적)
    6. 나머지 필드들 (알파벳 순)
    """
    # 우선순위 키 (앞에 배치할 필드)
    priority_keys = [
        "timestamp",
        "level",
        "call",
        "event",
        "progress",
        "call_id",
        "transaction_id",
        "direction",
        "method",
        "status_code",
        "caller",
        "callee",
        "from_addr",
        "to_addr",
    ]
    
    # 새로운 순서로 재구성
    ordered = {}
    
    # 1. 우선순위 키 먼저 추가 (존재하는 것만)
    for key in priority_keys:
        if key in event_dict:
            ordered[key] = event_dict[key]
    
    # 2. 나머지 키들 추가 (알파벳 순)
    remaining_keys = sorted([k for k in event_dict.keys() if k not in priority_keys])
    for key in remaining_keys:
        ordered[key] = event_dict[key]
    
    return ordered


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
        call_event_to_key,  # call=True → call 키에 이벤트 이름 표시, event 제거
        reorder_keys,  # ✅ 키 순서 재정렬 (timestamp가 제일 앞으로)
    ]

    if format_type == "json":
        import json
        # 한글 등 비ASCII 문자를 \uXXXX 이스케이프하지 않고 그대로 출력
        # structlog가 serializer를 호출할 때 kwargs를 넘길 수 있으므로 **kwargs 수용
        def _json_serializer(event_dict, **kwargs):
            return json.dumps(event_dict, ensure_ascii=False, default=str)
        processors.append(structlog.processors.JSONRenderer(serializer=_json_serializer))
    else:
        # 개발용 컬러 텍스트 포맷
        processors.append(structlog.dev.ConsoleRenderer(colors=True))

    # 파일 출력 설정
    log_file_path = None
    if output == "file":
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        log_file_path = log_dir / "app.log"
        # ⭐ 즉시 쓰기: buffering=1 (라인 버퍼링)
        # ✅ write 모드로 변경 (서버 시작 시 새로 생성)
        log_stream = open(log_file_path, "w", encoding="utf-8", buffering=1)
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
    
    # ✅ Pipecat(loguru) 로그를 app.log에 통합
    # Pipecat은 loguru를 사용하므로 별도 설정 없으면 콘솔에만 출력됨
    _setup_loguru_integration(level, log_file_path)


def _setup_loguru_integration(level: str, log_file_path: Optional[Path]) -> None:
    """Pipecat(loguru) 로그를 app.log 파일에도 기록하도록 설정
    
    Pipecat 프레임워크는 내부적으로 loguru를 사용합니다.
    별도 설정 없이는 콘솔에만 출력되므로, 동일한 app.log에
    기록하여 통합 로그 분석이 가능하도록 합니다.
    
    Args:
        level: 로그 레벨 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file_path: app.log 파일 경로 (None이면 파일 출력 안함)
    """
    try:
        from loguru import logger as loguru_logger
        
        # 기존 loguru 핸들러 제거 (기본 stderr 핸들러)
        loguru_logger.remove()
        
        # 콘솔 출력 유지 (기본 포맷)
        loguru_logger.add(
            sys.stderr,
            level=level.upper(),
            format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
                   "<level>{level: <8}</level> | "
                   "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
                   "<level>{message}</level>",
            colorize=True,
        )
        
        # app.log 파일에도 기록
        if log_file_path:
            loguru_logger.add(
                str(log_file_path),
                level=level.upper(),
                format="[PIPECAT] {time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
                       "{name}:{function}:{line} - {message}",
                rotation=None,  # structlog이 관리하므로 rotation 없음
                mode="a",  # append 모드 (structlog이 먼저 write로 생성)
                encoding="utf-8",
            )
    except ImportError:
        pass  # loguru가 없으면 스킵 (Pipecat 미설치 환경)
    except Exception:
        pass  # loguru 설정 실패해도 서버 동작에는 영향 없음


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


@dataclass
class LogEntry:
    """비동기 로그 엔트리"""
    method: str  # 'info', 'error', 'warning', 'debug', 'critical'
    event: str
    kwargs: Dict[str, Any]
    logger_name: str


async def _log_worker(queue: asyncio.Queue) -> None:
    """비동기 로그 워커 태스크
    
    큐에서 로그 엔트리를 가져와서 실제로 출력합니다.
    """
    global _sync_logger
    
    if _sync_logger is None:
        _sync_logger = structlog.get_logger("async_logger")
    
    while True:
        try:
            entry = await queue.get()
            
            if entry is None:  # 종료 신호
                break
            
            # 실제 로그 출력 (동기적으로)
            logger = structlog.get_logger(entry.logger_name)
            log_method = getattr(logger, entry.method, logger.info)
            log_method(entry.event, **entry.kwargs)
            
            queue.task_done()
        except Exception as e:
            # 로그 워커 자체의 에러는 동기 로거로 출력
            try:
                if _sync_logger:
                    _sync_logger.error("async_log_worker_error", error=str(e), exc_info=True)
            except:
                # 최후의 수단: print 사용
                print(f"CRITICAL: Async log worker error: {e}", file=sys.stderr)


def start_async_logging(queue_size: int = 1000) -> None:
    """비동기 로깅 시작
    
    Args:
        queue_size: 로그 큐 크기 (기본값: 1000)
    """
    global _log_queue, _log_worker_task
    
    if _log_queue is not None:
        # 이미 시작됨
        return
    
    _log_queue = asyncio.Queue(maxsize=queue_size)
    
    # 워커 태스크 시작
    loop = asyncio.get_event_loop()
    _log_worker_task = loop.create_task(_log_worker(_log_queue))


async def stop_async_logging() -> None:
    """비동기 로깅 중지"""
    global _log_queue, _log_worker_task
    
    if _log_queue is None:
        return
    
    # 종료 신호 전송
    await _log_queue.put(None)
    
    # 워커 태스크 완료 대기
    if _log_worker_task:
        try:
            await asyncio.wait_for(_log_worker_task, timeout=5.0)
        except asyncio.TimeoutError:
            _log_worker_task.cancel()
            try:
                await _log_worker_task
            except asyncio.CancelledError:
                pass
    
    _log_queue = None
    _log_worker_task = None


def get_async_logger(name: str) -> structlog.BoundLogger:
    """비동기 로거 인스턴스 반환
    
    이 로거는 로그를 큐에 넣고 즉시 반환합니다.
    실제 출력은 별도 워커 태스크에서 처리됩니다.
    
    Args:
        name: 로거 이름 (일반적으로 __name__)
        
    Returns:
        structlog.BoundLogger: 비동기 로거 인스턴스
    """
    global _log_queue
    
    if _log_queue is None:
        # 비동기 로깅이 시작되지 않았으면 동기 로거 반환
        return structlog.get_logger(name)
    
    # 비동기 로거 래퍼 생성
    base_logger = structlog.get_logger(name)
    
    class AsyncLoggerWrapper:
        """비동기 로거 래퍼"""
        
        def __init__(self, base: structlog.BoundLogger, queue: asyncio.Queue, name: str):
            self._base = base
            self._queue = queue
            self._name = name
        
        def _log_async(self, method: str, event: str, **kwargs):
            """비동기로 로그를 큐에 추가"""
            try:
                entry = LogEntry(
                    method=method,
                    event=event,
                    kwargs=kwargs,
                    logger_name=self._name
                )
                # 큐가 가득 찬 경우 즉시 반환 (블로킹 방지)
                self._queue.put_nowait(entry)
            except asyncio.QueueFull:
                # 큐가 가득 찬 경우 동기 로거로 폴백
                log_method = getattr(self._base, method, self._base.info)
                log_method(event, **kwargs)
            except Exception:
                # 에러 발생 시 동기 로거로 폴백
                try:
                    log_method = getattr(self._base, method, self._base.info)
                    log_method(event, **kwargs)
                except:
                    pass
        
        def info(self, event: str, **kwargs):
            self._log_async("info", event, **kwargs)
        
        def error(self, event: str, **kwargs):
            self._log_async("error", event, **kwargs)
        
        def warning(self, event: str, **kwargs):
            self._log_async("warning", event, **kwargs)
        
        def debug(self, event: str, **kwargs):
            self._log_async("debug", event, **kwargs)
        
        def critical(self, event: str, **kwargs):
            self._log_async("critical", event, **kwargs)
        
        def bind(self, **new_values):
            """바인딩 지원 (기존 structlog API 호환)"""
            new_base = self._base.bind(**new_values)
            return AsyncLoggerWrapper(new_base, self._queue, self._name)
        
        def __getattr__(self, name):
            # 다른 메서드는 기본 로거로 위임
            return getattr(self._base, name)
    
    return AsyncLoggerWrapper(base_logger, _log_queue, name)

