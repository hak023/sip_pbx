"""
업로드된 OpenAPI 스펙 기반 동적 HTTP Tool 실행기 (Story 1.35, FR34-A).

설계 원칙(Story 1.34 스파이크 결론):
  - GET은 기본 능동, 쓰기 메서드는 `approved_methods_json`에 등록된 경우만 실행 허용(NFR9).
  - 실행 전 현재 상태를 GET으로 스냅샷 → `tool_execution_log.pre_state_json`에 저장.
  - 실패(4xx/5xx/타임아웃) 시 상세 사유를 사용자에게 명확히 전달(묵살 금지).
  - 인증 정보(API 키 등)는 절대 평문 로그에 남기지 않는다(OWASP).
  - 기존 SIP PBX 하드코딩 카탈로그(Epic 1/2)는 이 경로와 완전히 분리 — 영향 없음(AC5).

사용 방법:
  1. OpenAPI 스펙을 업로드하고 Story 1.34의 PATCH /approve-methods 로 쓰기 메서드를 승인한다.
  2. `build_dynamic_tool(endpoint_meta, document_id, owner)`로 LangChain Tool을 생성한다.
  3. 생성된 Tool을 기존 `booking_gemini_fc.py::_langchain_tools_to_glm_tool()` 경로로 Gemini FC에 연결한다.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Story 1.35 실행 정책 상수(tool_execution_policy.py 재사용)
from src.ai_voicebot.self_service.tool_execution_policy import (
    DEFAULT_TIMEOUT_SEC,
    FAILURE_HINT_CLIENT_ERROR,
    FAILURE_HINT_SERVER_ERROR,
    FAILURE_HINT_TIMEOUT,
    MAX_RETRIES_ON_5XX,
    RETRY_DELAY_SEC,
    validate_execution_request,
)


def _redact_headers(headers: Dict[str, str]) -> Dict[str, str]:
    """인증 헤더를 로그에 남기지 않도록 마스킹한다(OWASP)."""
    sensitive = frozenset({"authorization", "x-api-key", "api-key", "token"})
    return {k: ("***" if k.lower() in sensitive else v) for k, v in headers.items()}


def build_execution_context(document_id: str, *, owner: str) -> Optional[Dict[str, Any]]:
    """문서의 base_url/인증/승인 상태를 한 번에 조립한다(Story 1.35 재개, FR34-A).

    LangGraph Tool이 실행을 준비할 때 이 함수 하나만 호출하면 `execute_api_endpoint()`에
    필요한 `base_url`/`headers`/`approved_methods`를 모두 얻을 수 있다. 문서가 없거나
    base_url이 비어있으면(목적지를 모르므로) None을 반환한다.
    """
    from src.common.knowledge_documents_db import get_document

    doc = get_document(document_id, owner=owner)
    if doc is None:
        return None
    base_url = doc.get("base_url") or ""
    if not base_url:
        return None

    headers: Dict[str, str] = {}
    header_name = doc.get("auth_header_name") or ""
    header_value = doc.get("auth_header_value") or ""
    if header_name and header_value:
        headers[header_name] = header_value

    return {
        "base_url": base_url,
        "headers": headers,
        "approved_methods": doc.get("approved_methods") or ["GET"],
    }


async def _do_http_request(
    *,
    method: str,
    url: str,
    headers: Dict[str, str],
    params: Optional[Dict[str, Any]],
    json_body: Optional[Dict[str, Any]],
    timeout: float,
) -> tuple[int, Any]:
    """실제 HTTP 요청을 수행한다. (status_code, response_data)를 반환한다."""
    try:
        import httpx
    except ImportError:
        return 503, {"error": "httpx 패키지가 설치되어 있지 않습니다. pip install httpx"}

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json_body,
            )
        try:
            data = resp.json()
        except Exception:
            data = resp.text
        return resp.status_code, data
    except httpx.TimeoutException:
        return 408, {"error": "timeout"}


async def execute_api_endpoint(
    *,
    base_url: str,
    endpoint_path: str,
    method: str,
    headers: Dict[str, str],
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    approved_methods: List[str],
    document_id: str,
    owner: str,
    timeout: float = DEFAULT_TIMEOUT_SEC,
) -> Dict[str, Any]:
    """승인 검사 → (쓰기 시) GET 스냅샷 → 실제 HTTP 호출 → 로그 기록 → 결과 반환.

    반환 형식: {"ok": bool, "status": int, "data": Any, "pre_state": Any, "error": str | None}
    """
    # 1. 승인 검사
    ok, reason = validate_execution_request(method=method, approved_methods=approved_methods)
    if not ok:
        return {"ok": False, "status": 403, "data": None, "pre_state": None, "error": reason}

    url = base_url.rstrip("/") + "/" + endpoint_path.lstrip("/")
    pre_state = None

    # 2. 쓰기 시 현재 상태 스냅샷(GET, best-effort — 실패해도 실행 차단 안 함)
    if method.upper() != "GET":
        try:
            snap_status, snap_data = await _do_http_request(
                method="GET", url=url, headers=headers, params=None, json_body=None, timeout=timeout,
            )
            if snap_status == 200:
                pre_state = snap_data
        except Exception as exc:
            logger.debug("dynamic_api_pre_state_snapshot_failed document_id=%s err=%s", document_id, exc)

    # 3. 실제 실행 (5xx에 한해 1회 재시도)
    retries_left = MAX_RETRIES_ON_5XX
    status, data = 0, None
    last_error: Optional[str] = None

    while True:
        if status == 408:
            last_error = FAILURE_HINT_TIMEOUT
            break
        status, data = await _do_http_request(
            method=method, url=url, headers=headers, params=params, json_body=json_body, timeout=timeout,
        )
        if status == 408:
            last_error = FAILURE_HINT_TIMEOUT
            break
        if 200 <= status < 300:
            last_error = None
            break
        if 400 <= status < 500:
            detail = str(data) if isinstance(data, str) else json.dumps(data, ensure_ascii=False)[:200]
            last_error = FAILURE_HINT_CLIENT_ERROR.format(status=status, detail=detail)
            break
        # 5xx — 재시도
        if retries_left > 0:
            retries_left -= 1
            await asyncio.sleep(RETRY_DELAY_SEC)
        else:
            last_error = FAILURE_HINT_SERVER_ERROR.format(status=status)
            break

    success = last_error is None

    # 4. 실행 로그 기록(best-effort, 실패해도 결과에 영향 없음)
    try:
        from src.booking.database import get_db

        with get_db() as conn:
            conn.execute(
                "INSERT INTO tool_execution_log"
                " (owner, document_id, method, endpoint_path, request_json,"
                "  pre_state_json, response_status, response_json)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    owner,
                    document_id,
                    method.upper(),
                    endpoint_path,
                    json.dumps({"params": params, "body": json_body}, ensure_ascii=False),
                    json.dumps(pre_state, ensure_ascii=False) if pre_state is not None else "null",
                    status,
                    json.dumps(data, ensure_ascii=False) if data is not None else "null",
                ),
            )
    except Exception as exc:
        logger.warning(
            "dynamic_api_execution_log_failed document_id=%s err=%s",
            document_id, exc,
        )
        logger.debug("redacted_headers=%s", _redact_headers(headers))

    return {
        "ok": success,
        "status": status,
        "data": data,
        "pre_state": pre_state,
        "error": last_error,
    }


async def undo_last_execution(*, owner: str, document_id: str) -> Dict[str, Any]:
    """가장 최근 쓰기 실행의 pre_state로 역호출해 되돌린다(Story 1.34 Undo 메커니즘).

    역호출이 불가능하거나 실패하면 `ok=False, error=안내문구`를 반환하고 로그에 `undo_ok=0`을 남긴다.
    """
    from src.ai_voicebot.self_service.tool_execution_policy import FAILURE_HINT_UNDO_UNAVAILABLE

    try:
        from src.booking.database import get_db

        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM tool_execution_log"
                " WHERE owner = ? AND document_id = ? AND method != 'GET' AND undo_attempted = 0"
                " ORDER BY created_at DESC LIMIT 1",
                (owner, document_id),
            ).fetchone()
    except Exception as exc:
        logger.warning("dynamic_api_undo_lookup_failed owner=%s err=%s", owner, exc)
        return {"ok": False, "error": FAILURE_HINT_UNDO_UNAVAILABLE}

    if row is None:
        return {"ok": False, "error": "되돌릴 실행 이력이 없습니다."}

    row = dict(row)
    log_id = row["id"]
    pre_state = json.loads(row.get("pre_state_json") or "null")
    endpoint_path = row.get("endpoint_path") or ""

    if pre_state is None:
        _mark_undo(log_id, ok=False)
        return {"ok": False, "error": FAILURE_HINT_UNDO_UNAVAILABLE}

    # Story 1.35 재개(FR34-A): build_execution_context()로 base_url/인증/승인 상태를 조립해
    # 실제 PUT 역호출을 시도한다 — PUT이 승인 목록에 없으면 안전하게 미실행으로 남긴다.
    # base_url 미설정/PUT 미승인은 사용자가 이후 조치(승인 등)로 해결 가능하므로 undo_attempted를
    # 마킹하지 않는다(재시도 가능하게 남겨둠) — 실제 HTTP 실행을 시도한 경우에만 마킹한다.
    ctx = build_execution_context(document_id, owner=owner)
    if ctx is None:
        return {"ok": False, "error": FAILURE_HINT_UNDO_UNAVAILABLE}
    if "PUT" not in {m.upper() for m in ctx["approved_methods"]}:
        return {
            "ok": False,
            "error": "되돌리려면 PUT 메서드 승인이 필요합니다. 지식 업로드 화면에서 PUT을 승인한 뒤 다시 시도해 주세요.",
        }

    undo_result = await execute_api_endpoint(
        base_url=ctx["base_url"], endpoint_path=endpoint_path, method="PUT",
        headers=ctx["headers"], json_body=pre_state,
        approved_methods=ctx["approved_methods"], document_id=document_id, owner=owner,
    )
    _mark_undo(log_id, ok=undo_result["ok"])
    if not undo_result["ok"]:
        return {"ok": False, "error": undo_result["error"] or FAILURE_HINT_UNDO_UNAVAILABLE}
    return {
        "ok": True,
        "pre_state": pre_state,
        "message": f"이전 상태로 복원했습니다(endpoint={endpoint_path}).",
    }


def _mark_undo(log_id: int, ok: Optional[bool]) -> None:
    try:
        from src.booking.database import get_db

        with get_db() as conn:
            conn.execute(
                "UPDATE tool_execution_log SET undo_attempted = 1, undo_ok = ? WHERE id = ?",
                (1 if ok else (0 if ok is False else None), log_id),
            )
    except Exception as exc:
        logger.warning("dynamic_api_undo_mark_failed id=%d err=%s", log_id, exc)


# ---------------------------------------------------------------------------
# Story 1.48 — LangChain Tool 래핑(self_service_agent.py의 Tool-calling 루프에 연결)
# self_service/tools.py::_make_tool 패턴을 그대로 복제한다(langchain_core 미설치 환경에서도
# import가 깨지지 않도록 원본 함수를 그대로 반환).
# ---------------------------------------------------------------------------

try:
    from langchain_core.tools import tool as _langchain_tool
    _LANGCHAIN_AVAILABLE = True
except ImportError:
    _LANGCHAIN_AVAILABLE = False
    _langchain_tool = None  # type: ignore


def _make_tool(fn):
    if _LANGCHAIN_AVAILABLE and _langchain_tool is not None:
        return _langchain_tool(fn)
    return fn


async def find_last_undoable_document_id(owner: str) -> Optional[str]:
    """owner의 되돌리지 않은 최근 쓰기 실행 이력에서 document_id를 찾는다(문서 무관 조회).

    `undo_last_execution()`은 document_id를 알아야 호출 가능한데, 사용자는 "방금 한 거
    취소해줘"처럼 document_id를 말하지 않으므로 이 헬퍼로 먼저 대상을 특정한다.
    """
    try:
        from src.booking.database import get_db

        with get_db() as conn:
            row = conn.execute(
                "SELECT document_id FROM tool_execution_log"
                " WHERE owner = ? AND method != 'GET' AND undo_attempted = 0"
                " ORDER BY created_at DESC LIMIT 1",
                (owner,),
            ).fetchone()
    except Exception as exc:
        logger.warning("dynamic_api_find_undoable_failed owner=%s err=%s", owner, exc)
        return None
    return dict(row)["document_id"] if row is not None else None


def _sanitize_tool_name(document_id: str, method: str, endpoint_path: str) -> str:
    import re as _re

    slug = _re.sub(r"[^a-zA-Z0-9]+", "_", endpoint_path).strip("_").lower() or "root"
    doc_short = _re.sub(r"[^a-zA-Z0-9]", "", document_id)[:8]
    return f"api_{doc_short}_{method.lower()}_{slug}"[:60]


def _build_dynamic_tool_doc(title: str, method: str, endpoint_path: str, parameters: List[Dict[str, Any]]) -> str:
    lines = [
        f"업로드된 외부 시스템 문서 '{title}'의 {method} {endpoint_path} 엔드포인트를 실제로 호출합니다.",
    ]
    if parameters:
        lines.append("파라미터:")
        for p in parameters:
            if not isinstance(p, dict):
                continue
            lines.append(
                f"- {p.get('name', '?')} ({'필수' if p.get('required') else '선택'}, "
                f"{p.get('in', 'query')}): {p.get('description', '')}"
            )
    lines.append(
        "Args: owner(테넌트 ID, 자동 채움 — 무시하고 절대 임의로 채우지 말 것), "
        "params(경로·쿼리 파라미터를 담은 dict, 없으면 생략 가능), "
        "body(요청 본문 dict, 쓰기 메서드에만 필요, 없으면 생략 가능)"
    )
    lines.append("Returns: JSON 문자열 {ok, status, data, error}")
    return "\n".join(lines)


def _make_dynamic_tool_fn(document_id: str, method: str, endpoint_path: str):
    """document_id/method/endpoint_path를 클로저로 고정한 실행 함수를 만든다(late-binding 방지)."""

    async def _dyn_tool_fn(
        owner: str,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
    ) -> str:
        ctx = build_execution_context(document_id, owner=owner)
        if ctx is None:
            return json.dumps(
                {"ok": False, "error": "이 문서의 실행 정보(base_url)를 찾을 수 없습니다. 지식 업로드 화면에서 base_url을 설정해 주세요."},
                ensure_ascii=False,
            )
        call_params = dict(params or {})
        resolved_path = endpoint_path
        for key in list(call_params.keys()):
            placeholder = "{" + key + "}"
            if placeholder in resolved_path:
                resolved_path = resolved_path.replace(placeholder, str(call_params.pop(key)))
        result = await execute_api_endpoint(
            base_url=ctx["base_url"], endpoint_path=resolved_path, method=method,
            headers=ctx["headers"], params=call_params or None, json_body=body or None,
            approved_methods=ctx["approved_methods"], document_id=document_id, owner=owner,
        )
        return json.dumps(result, ensure_ascii=False)

    return _dyn_tool_fn


def build_dynamic_tools_for_owner(owner: str) -> List[Any]:
    """owner가 업로드한 OpenAPI 문서의 승인된 메서드를 LangChain Tool 목록으로 만든다.

    GET은 승인 없이 항상 포함되고(기본 능동), 쓰기 메서드는 `approved_methods_json`에
    있는 경우만 Tool로 노출된다(미승인 메서드는 아예 LLM에게 보이지 않음 — NFR9 화이트리스트).
    문서가 없거나 DB 조회에 실패하면 빈 리스트를 반환한다(정적 SELF_SERVICE_TOOLS 흐름에는
    영향 없음).
    """
    try:
        from src.common.knowledge_documents_db import list_document_endpoints, list_documents
    except ImportError:
        return []

    try:
        docs = list_documents(owner=owner, source_type="openapi")
    except Exception as exc:
        logger.warning("dynamic_api_tools_list_documents_failed owner=%s err=%s", owner, exc)
        return []

    tools: List[Any] = []
    for doc in docs:
        document_id = doc.get("document_id")
        if not document_id:
            continue
        approved = {m.upper() for m in (doc.get("approved_methods") or ["GET"])}
        try:
            endpoints = list_document_endpoints(document_id)
        except Exception as exc:
            logger.warning("dynamic_api_tools_list_endpoints_failed document_id=%s err=%s", document_id, exc)
            continue
        for ep in endpoints:
            method = str(ep.get("method") or "").upper()
            endpoint_path = str(ep.get("endpoint_path") or "")
            if not method or not endpoint_path:
                continue
            if method != "GET" and method not in approved:
                continue  # 미승인 쓰기 메서드는 Tool 목록에서 아예 제외
            fn = _make_dynamic_tool_fn(document_id, method, endpoint_path)
            fn.__name__ = _sanitize_tool_name(document_id, method, endpoint_path)
            fn.__doc__ = _build_dynamic_tool_doc(
                str(doc.get("title") or ""), method, endpoint_path, ep.get("parameters") or [],
            )
            tools.append(_make_tool(fn))

    if docs:
        async def _undo_last_dynamic_api_change(owner: str) -> str:
            """방금 실행한 외부 시스템 REST-API 변경을 이전 상태로 되돌립니다.

            Args:
                owner: 테넌트 ID(자동 채움)

            Returns:
                JSON 문자열 {ok, message/error}
            """
            document_id = await find_last_undoable_document_id(owner)
            if not document_id:
                return json.dumps({"ok": False, "error": "되돌릴 실행 이력이 없습니다."}, ensure_ascii=False)
            result = await undo_last_execution(owner=owner, document_id=document_id)
            return json.dumps(result, ensure_ascii=False)

        tools.append(_make_tool(_undo_last_dynamic_api_change))

    return tools

