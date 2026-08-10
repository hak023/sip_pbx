"""
LangChain Tool → FastMCP Tool 변환 헬퍼 (Epic 8, Story 8.1).

핵심 역할:
  1. LangChain StructuredTool / plain async def 어느 쪽이든 실제 비동기 callable 추출.
  2. `owner` 파라미터를 default_owner 값으로 고정 주입 — MCP 클라이언트에 노출하지 않는다.
  3. `inspect.Signature`에서 `owner`를 제거한 새 시그니처를 함수에 부착해
     FastMCP가 올바른 JSON Schema를 생성하도록 한다.
"""

from __future__ import annotations

import functools
import inspect
from typing import Any, Callable


def _extract_callable(lc_tool: Any) -> Callable:
    """LangChain Tool에서 실제로 호출 가능한 비동기 함수를 꺼낸다.

    langchain_core.tools.StructuredTool은 `.coroutine` 속성에 실제 async def를 보관한다.
    _make_tool()이 langchain_core 없이 원본 함수를 그대로 반환한 경우 lc_tool 자체가 callable이다.
    """
    coroutine = getattr(lc_tool, "coroutine", None)
    if coroutine is not None and callable(coroutine):
        return coroutine
    if callable(lc_tool):
        return lc_tool
    raise TypeError(f"LangChain Tool에서 callable을 추출할 수 없습니다: {lc_tool!r}")


def _strip_owner_param(sig: inspect.Signature) -> inspect.Signature:
    """시그니처에서 `owner` 파라미터를 제거한 새 Signature 반환."""
    params = [p for name, p in sig.parameters.items() if name != "owner"]
    return sig.replace(parameters=params)


def wrap_lc_tool_for_mcp(lc_tool: Any, default_owner: str) -> Callable:
    """LangChain Tool을 owner 고정 후 FastMCP에 등록 가능한 async 함수로 변환한다.

    - MCP 클라이언트는 `owner`를 볼 수 없다(시그니처에서 제거됨).
    - 실제 호출 시 `owner=default_owner`가 자동 주입된다.
    """
    underlying = _extract_callable(lc_tool)

    @functools.wraps(underlying)
    async def _mcp_fn(**kwargs: Any) -> Any:
        kwargs["owner"] = default_owner  # 항상 서버 고정값 사용 (외부 주입 불가)
        return await underlying(**kwargs)

    try:
        original_sig = inspect.signature(underlying)
        _mcp_fn.__signature__ = _strip_owner_param(original_sig)
    except (ValueError, TypeError):
        pass  # 시그니처 제거 실패는 비치명적 — FastMCP가 기본 스키마로 대체

    # FastMCP는 __name__ / __doc__ 을 Tool 이름·설명으로 사용한다
    name = getattr(lc_tool, "name", None) or getattr(underlying, "__name__", "unnamed_tool")
    doc = getattr(lc_tool, "description", None) or getattr(underlying, "__doc__", "") or ""
    _mcp_fn.__name__ = name
    _mcp_fn.__doc__ = doc

    return _mcp_fn
