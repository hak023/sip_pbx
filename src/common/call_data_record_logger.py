"""
통화 데이터 기록 로그 (call_data_record_yyyymmdd.log)

- 로그 경로: logs/call_data_record_YYYYMMDD.log (일 단위 파일)
- 실시간 한 줄 단위 기록 (JSON Lines)
- call_id, category, event 및 추가 필드 포함
- 동일 페이로드를 WebSocket 이벤트 `call_debug_trace`로 브로드캐스트 (대시보드 실시간 디버그)
"""

import copy
import json
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

# 한국 시간
KST = timezone(timedelta(hours=9))

_lock = threading.Lock()
_current_date: Optional[str] = None
_file_handle: Optional[Any] = None
_log_dir: Optional[Path] = None


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _get_log_dir() -> Path:
    global _log_dir
    if _log_dir is None:
        _log_dir = _project_root() / "logs"
        _log_dir.mkdir(parents=True, exist_ok=True)
    return _log_dir


def _today_str() -> str:
    return datetime.now(KST).strftime("%Y%m%d")


# WebSocket 브로드캐스트용 — 과대 페이로드 방지 (파일 로그는 전체 유지)
_WS_MAX_STR = 6000
_WS_MAX_LIST = 80


def _truncate_for_ws(obj: Any, depth: int = 0) -> Any:
    """call_debug_trace 페이로드용: 긴 문자열·깊은 구조 축소."""
    if depth > 8:
        return "<max_depth>"
    if isinstance(obj, str):
        if len(obj) > _WS_MAX_STR:
            return obj[:_WS_MAX_STR] + f"... (truncated, len={len(obj)})"
        return obj
    if isinstance(obj, dict):
        return {str(k): _truncate_for_ws(v, depth + 1) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        lst = list(obj[:_WS_MAX_LIST])
        out = [_truncate_for_ws(x, depth + 1) for x in lst]
        if len(obj) > _WS_MAX_LIST:
            out.append(f"... ({len(obj) - _WS_MAX_LIST} more items)")
        return out
    if isinstance(obj, (int, float, bool)) or obj is None:
        return obj
    return str(obj)


def _broadcast_call_debug_trace(payload: Dict[str, Any]) -> None:
    """call_data_record와 동일 한 줄을 대시보드 Socket.IO로 실시간 전송."""
    cid = payload.get("call_id") or ""
    if not cid:
        return
    try:
        from src.websocket.server import schedule_socket_emit

        safe = _truncate_for_ws(copy.deepcopy(payload))
        schedule_socket_emit("call_debug_trace", safe)
    except Exception:
        pass


def _ensure_file() -> Optional[Any]:
    """날짜에 해당하는 오늘자 로그 파일 핸들 반환 (날짜 바뀌면 새 파일).

    파일을 처음 열 때 마지막 바이트를 확인한다.
    이전 서버 비정상 종료로 마지막 라인이 개행 없이 끝났을 경우
    새 개행을 삽입하여 다음 JSON 라인이 이전 라인에 붙지 않도록 한다.
    """
    global _current_date, _file_handle
    today = _today_str()
    with _lock:
        if _current_date != today:
            if _file_handle is not None:
                try:
                    _file_handle.close()
                except Exception:
                    pass
                _file_handle = None
            _current_date = today
        if _file_handle is None:
            log_dir = _get_log_dir()
            path = log_dir / f"call_data_record_{today}.log"
            try:
                # 기존 파일이 있으면 마지막 바이트 확인 — 개행 없이 끝난 경우 복구
                if path.exists() and path.stat().st_size > 0:
                    with open(path, "rb") as _rb:
                        _rb.seek(-1, 2)
                        last_byte = _rb.read(1)
                    if last_byte != b"\n":
                        # 잘린 라인 뒤에 개행 추가 → 다음 JSON이 새 줄에 기록됨
                        with open(path, "ab") as _ab:
                            _ab.write(b"\n")
                _file_handle = open(path, "a", encoding="utf-8", buffering=1)
            except Exception:
                return None
        return _file_handle


def log_call_data(
    call_id: str,
    category: str,
    event: str,
    **kwargs: Any,
) -> None:
    """
    통화 데이터 기록 로그에 한 줄 추가.

    Args:
        call_id: 통화 ID
        category: 구분 (llm | stt | tts | rag | knowledge | call_event | hitl)
        event: 이벤트 이름 (예: llm_request, llm_response, stt_final, tts_started)
        **kwargs: 추가 키/값 (문자열·숫자·리스트 등, JSON 직렬화 가능해야 함)
            rag_search_done 시: rag_hits_retrieval, rag_hits_llm_context (지식베이스 상위·LLM전달분, src.common.rag_hit_serializer),
                rag_search_trace (Chroma knowledge 컬렉션·where·intent·카테고리 제한·히트 요약, RAGEngine.search)
            llm_exchange: user_text_full·response_full(파일 로그 전체), WebSocket은 길이 제한으로 축소될 수 있음.
            semantic_cache_miss: miss_reason, miss_detail, criteria(임계값·필터·hit_rules), top_candidate, query_full.
            유저 간 통화: call_event call_connected(human_human)·human_human_call_ended·post_call_extraction_* .
            knowledge_judgement(llm): 사후 추출 LLM judge_usefulness 요약(judgement 필드).
            chroma_knowledge_upsert(knowledge): doc_id·owner·category·embedding_dims·text_preview·chromadb_* .
    """
    try:
        f = _ensure_file()
        if f is None:
            return
        now = datetime.now(KST).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
        payload = {
            "ts": now,
            "call_id": call_id,
            "category": category,
            "event": event,
            **kwargs,
        }
        # JSON 직렬화 시 ensure_ascii=False, default=str
        line = json.dumps(payload, ensure_ascii=False, default=str) + "\n"
        with _lock:
            # 서버 종료 시 close_call_data_record_log()가 먼저 호출된 뒤
            # 이미 스케줄된 코루틴이 뒤늦게 log_call_data를 부르면 ValueError("I/O on closed file")가
            # 발생해 main.py의 최상위 except에서 "Fatal Error"로 출력된다.
            # f.closed를 명시적으로 확인해 조용히 스킵한다.
            if f.closed:
                return
            f.write(line)
            f.flush()
        # 대시보드 실시간 디버그 (logs/call_data_record_*.log 와 동일 필드)
        _broadcast_call_debug_trace(payload)
    except Exception:
        pass  # 로그 실패가 비즈니스 로직에 영향 주지 않도록


def close_call_data_record_log() -> None:
    """현재 열린 call_data_record 로그 파일 핸들 닫기 (서버 종료 시 호출)."""
    global _file_handle
    with _lock:
        if _file_handle is not None:
            try:
                _file_handle.close()
            except Exception:
                pass
            _file_handle = None
