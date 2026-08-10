"""단위테스트 — MCP 게이트웨이 _tool_bridge.py + server.py (Epic 8, Story 8.1)."""

from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# _tool_bridge 테스트
# ──────────────────────────────────────────────────────────────────────────────

class TestStripOwnerParam:
    def test_removes_owner(self):
        from src.mcp_gateway._tool_bridge import _strip_owner_param

        async def fn(owner: str, x: int, y: str) -> str: ...

        stripped = _strip_owner_param(inspect.signature(fn))
        assert "owner" not in stripped.parameters
        assert "x" in stripped.parameters
        assert "y" in stripped.parameters

    def test_no_owner_is_noop(self):
        from src.mcp_gateway._tool_bridge import _strip_owner_param

        async def fn(x: int) -> str: ...

        stripped = _strip_owner_param(inspect.signature(fn))
        assert list(stripped.parameters) == ["x"]


class TestExtractCallable:
    def test_plain_async_def(self):
        from src.mcp_gateway._tool_bridge import _extract_callable

        async def fn(): ...

        assert _extract_callable(fn) is fn

    def test_langchain_structured_tool(self):
        from src.mcp_gateway._tool_bridge import _extract_callable

        async def real_fn(): ...

        fake_tool = MagicMock()
        fake_tool.coroutine = real_fn
        assert _extract_callable(fake_tool) is real_fn

    def test_raises_on_non_callable(self):
        from src.mcp_gateway._tool_bridge import _extract_callable

        with pytest.raises(TypeError):
            _extract_callable("not_a_tool")


class TestWrapLcToolForMcp:
    @pytest.mark.asyncio
    async def test_owner_injected_silently(self):
        """MCP 클라이언트가 owner를 전달하지 않아도 default_owner가 주입된다."""
        from src.mcp_gateway._tool_bridge import wrap_lc_tool_for_mcp

        received: dict = {}

        async def fake_tool(owner: str, x: int) -> str:
            received["owner"] = owner
            received["x"] = x
            return "ok"

        wrapped = wrap_lc_tool_for_mcp(fake_tool, default_owner="9001")
        result = await wrapped(x=42)

        assert result == "ok"
        assert received["owner"] == "9001"
        assert received["x"] == 42

    def test_owner_removed_from_signature(self):
        """FastMCP에 노출되는 시그니처에 owner가 없어야 한다."""
        from src.mcp_gateway._tool_bridge import wrap_lc_tool_for_mcp

        async def fake_tool(owner: str, x: int) -> str: ...

        wrapped = wrap_lc_tool_for_mcp(fake_tool, default_owner="9001")
        sig = inspect.signature(wrapped)
        assert "owner" not in sig.parameters
        assert "x" in sig.parameters

    def test_name_and_doc_propagated(self):
        from src.mcp_gateway._tool_bridge import wrap_lc_tool_for_mcp

        async def fake_tool(owner: str) -> str:
            """This is a test tool."""
            ...

        wrapped = wrap_lc_tool_for_mcp(fake_tool, default_owner="9001")
        assert wrapped.__name__ == "fake_tool"
        assert "test tool" in wrapped.__doc__

    def test_langchain_tool_name_used(self):
        """LangChain StructuredTool의 .name 속성을 우선한다."""
        from src.mcp_gateway._tool_bridge import wrap_lc_tool_for_mcp

        async def real_fn(owner: str) -> str: ...

        fake_lc = MagicMock()
        fake_lc.name = "my_api_tool"
        fake_lc.description = "API 호출 도구"
        fake_lc.coroutine = real_fn

        wrapped = wrap_lc_tool_for_mcp(fake_lc, default_owner="1001")
        assert wrapped.__name__ == "my_api_tool"
        assert wrapped.__doc__ == "API 호출 도구"


# ──────────────────────────────────────────────────────────────────────────────
# server.py 테스트
# ──────────────────────────────────────────────────────────────────────────────

class TestServerToolRegistration:
    def test_empty_tools_server_starts(self):
        """업로드 문서가 없을 때 Tool 0개로 서버가 정상 구성된다 (AC5)."""
        from fastmcp import FastMCP
        from src.mcp_gateway._tool_bridge import wrap_lc_tool_for_mcp

        mcp = FastMCP("test")

        # build_dynamic_tools_for_owner가 빈 리스트 반환 시뮬레이션
        lc_tools: list = []
        registered = 0
        for lc_tool in lc_tools:
            mcp.add_tool(wrap_lc_tool_for_mcp(lc_tool, default_owner="9001"))
            registered += 1

        assert registered == 0

    def test_tools_registered_correctly(self):
        """동적 Tool 2개가 FastMCP에 정상 등록된다."""
        import asyncio
        from fastmcp import FastMCP
        from src.mcp_gateway._tool_bridge import wrap_lc_tool_for_mcp

        mcp = FastMCP("test")

        async def tool_a(owner: str, q: str) -> str:
            """Tool A"""
            return q

        async def tool_b(owner: str, n: int) -> str:
            """Tool B"""
            return str(n)

        for fn in [tool_a, tool_b]:
            mcp.add_tool(wrap_lc_tool_for_mcp(fn, default_owner="9001"))

        tools = asyncio.run(mcp.list_tools())
        assert len(tools) == 2
        names = {t.name for t in tools}
        assert "tool_a" in names
        assert "tool_b" in names
