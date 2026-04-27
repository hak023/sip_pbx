"""HTTP 4xx/422 응답 시 요약 로깅 — structlog → app.log(메인 프로세스 설정 시).

POST/PUT/PATCH 본문은 미들웨어에서 ``await request.body()`` 로 한 번 읽어
``request.state.body_preview`` 에 두며, Starlette 본문 캐시로 라우트와 공유한다.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import HTTPException, Request
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError

logger = structlog.get_logger(__name__)

_BODY_PREVIEW_MAX = 8192
_LOG_PREVIEW_MAX = 4000


def _detail_to_str(detail: Any) -> str:
    if isinstance(detail, str):
        return detail[:4000]
    try:
        import json

        return json.dumps(detail, ensure_ascii=False)[:4000]
    except Exception:
        return str(detail)[:4000]


async def capture_jsonish_request_body_middleware(request: Request, call_next):
    """``/api/`` 하위의 POST·PUT·PATCH 만 본문 미리 읽기 (대용량 업로드 회피).

    Starlette는 ``await request.body()`` 후 내부에 본문을 캐시하므로, 하위 라우트의
    ``body()`` 호출은 캐시를 쓴다. **receive 를 덮어쓰면 안 된다** — 응답 단계에서
    ``listen_for_disconnect`` 가 ``receive()`` 를 다시 호출할 때 원래 스트림으로
    ``http.disconnect`` 가 와야 하는데, 잘못된 재생기는 매번 ``http.request`` 를
    돌려 ``RuntimeError: Unexpected message received: http.request`` 가 난다(로그인 등).
    """
    path = request.url.path
    if (
        request.method in ("POST", "PUT", "PATCH")
        and path.startswith("/api/")
    ):
        try:
            body = await request.body()
        except Exception as e:
            logger.debug("request_body_read_failed", path=path, error=str(e))
            body = b""
        request.state.body_preview = (
            body[:_BODY_PREVIEW_MAX].decode("utf-8", errors="replace") if body else ""
        )
    response = await call_next(request)
    return response


async def logging_http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code >= 400:
        preview = getattr(request.state, "body_preview", "") or ""
        cl = request.client
        logger.warning(
            "http_exception",
            method=request.method,
            path=request.url.path,
            http_request_url=str(request.url),
            http_request_client_host=cl.host if cl else None,
            query=str(request.query_params),
            status_code=exc.status_code,
            detail=_detail_to_str(exc.detail),
            request_body_preview=preview[:_LOG_PREVIEW_MAX] if preview else None,
        )
    return await http_exception_handler(request, exc)


async def logging_validation_exception_handler(
    request: Request, exc: RequestValidationError
):
    preview = getattr(request.state, "body_preview", "") or ""
    cl = request.client
    logger.warning(
        "request_validation_error",
        method=request.method,
        path=request.url.path,
        http_request_url=str(request.url),
        http_request_client_host=cl.host if cl else None,
        query=str(request.query_params),
        errors=exc.errors(),
        request_body_preview=preview[:_LOG_PREVIEW_MAX] if preview else None,
    )
    return await request_validation_exception_handler(request, exc)


def register_http_error_logging(app: Any) -> None:
    """앱에 미들웨어·예외 핸들러 등록 (``app = FastAPI()`` 직후 한 번 호출)."""
    app.middleware("http")(capture_jsonish_request_body_middleware)
    app.add_exception_handler(HTTPException, logging_http_exception_handler)
    app.add_exception_handler(RequestValidationError, logging_validation_exception_handler)
