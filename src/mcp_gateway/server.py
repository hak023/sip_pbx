"""
SIP PBX 동적 REST-API MCP 게이트웨이 서버 (Epic 8, Story 8.1/8.2).

업로드된 OpenAPI 스펙 기반의 동적 Tool을 MCP 프로토콜로 외부 클라이언트에 노출한다.
내부 비즈니스 로직은 기존 `dynamic_api_tool.py`를 그대로 재사용하고,
이 모듈은 FastMCP 어댑터 역할만 수행한다.

실행:
  python -m src.mcp_gateway.server --owner 9001
  python -m src.mcp_gateway.server --owner 9001 --transport sse --port 3001

MCP 클라이언트 설정 예시 (Claude Desktop):
  {
    "mcpServers": {
      "sip-pbx-api": {
        "command": "python",
        "args": ["-m", "src.mcp_gateway.server", "--owner", "9001"],
        "cwd": "/path/to/sip-pbx"
      }
    }
  }
"""

from __future__ import annotations

import argparse
import logging
import sys

logger = logging.getLogger(__name__)


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="SIP PBX 동적 REST-API MCP 게이트웨이 서버",
    )
    p.add_argument("--owner", required=True, help="테넌트 ID (착신 SIP 내선번호)")
    p.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio", "sse"],
        help="MCP 전송 방식 (기본: stdio)",
    )
    p.add_argument("--port", type=int, default=3001, help="SSE 모드 포트 (기본: 3001)")
    p.add_argument("--host", default="127.0.0.1", help="SSE 모드 바인드 주소 (기본: 127.0.0.1)")
    return p


def main() -> None:
    # fastmcp 미설치 시 사용자 친화적 안내
    try:
        from fastmcp import FastMCP
    except ImportError:
        print(
            "[ERROR] fastmcp 패키지가 설치되어 있지 않습니다.\n"
            "  pip install fastmcp\n"
            "또는\n"
            "  pip install -r requirements-ai.txt",
            file=sys.stderr,
        )
        sys.exit(1)

    ns = _build_arg_parser().parse_args()
    owner: str = ns.owner

    # ── DB 초기화 (BOOKING_DB_PATH 환경변수 필요, start-all.ps1과 동일) ──
    try:
        from src.booking.database import init_db

        init_db()
    except Exception as exc:
        logger.warning("mcp_gateway_db_init_failed err=%s", exc)
        # DB 초기화 실패는 치명적이지 않다 — Tool 목록이 빈 채로 서버 기동

    # ── 동적 Tool 생성 (Story 1.51 기존 로직 그대로 재사용) ────────────────
    try:
        from src.ai_voicebot.self_service.dynamic_api_tool import build_dynamic_tools_for_owner

        lc_tools = build_dynamic_tools_for_owner(owner)
    except Exception as exc:
        logger.warning("mcp_gateway_build_tools_failed owner=%s err=%s", owner, exc)
        lc_tools = []

    # ── FastMCP 앱 구성 ────────────────────────────────────────────────────
    from src.mcp_gateway._tool_bridge import wrap_lc_tool_for_mcp

    mcp = FastMCP(
        name="SIP PBX Dynamic API Gateway",
        instructions=(
            f"이 서버는 테넌트 {owner}가 업로드한 OpenAPI 스펙 기반의 REST-API Tool을 제공합니다. "
            "승인된 메서드만 실행 가능하며, 쓰기 작업은 자동으로 Undo 가능합니다."
        ),
    )

    registered = 0
    for lc_tool in lc_tools:
        try:
            mcp_fn = wrap_lc_tool_for_mcp(lc_tool, default_owner=owner)
            mcp.add_tool(mcp_fn)
            registered += 1
        except Exception as exc:
            tool_name = getattr(lc_tool, "name", repr(lc_tool))
            logger.warning("mcp_gateway_tool_register_failed tool=%s err=%s", tool_name, exc)

    logger.info(
        "mcp_gateway_started owner=%s transport=%s tools=%d",
        owner, ns.transport, registered,
    )

    # ── 서버 기동 ──────────────────────────────────────────────────────────
    if ns.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport="sse", host=ns.host, port=ns.port)


if __name__ == "__main__":
    main()
