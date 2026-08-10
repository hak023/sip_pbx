# Epic 5 — MCP 서버 게이트웨이 계획 리포트 (그룹 C 집중)

**작성일**: 2026-08-10  
**상태**: 계획 수립(코드 변경 없음) — PRD/architecture/Story 문서 증분 반영, 사용자 검토 대기  
**범위 확정**: 2026-08-10 코드 분석 결과, **그룹 C(동적 REST-API Tool)만** MCP 연결 대상으로 확정.  
그룹 A/B/D는 SIP PBX 시스템 고유 정적 도메인 기반이므로 이번 Epic 대상 아님.

**관련 선행 문서**:  
- [FR35 계획 리포트](2026-08-06_epic4_platform_maturation_and_ux_transparency_planning.md) §FR35-G  
- [MCP vs Client-Centric 리서치](../../design/MCP_VS_CLIENT_CENTRIC_UNIVERSAL_AGENT_MARKET_RESEARCH.md)  
- [Story 1.51 — 동적 REST-API Tool 연결 완료](2026-08-07_story_1.51_dynamic_api_tool_agent_integration.md)

> **이 리포트는 계획 문서다.** 아래 설계와 다이어그램은 검토용 초안이며,  
> 사용자 승인 후 Story 착수·구현에 들어간다(하네스 규칙 §1.5).

---

## 0. 범위 확정 배경

2026-08-10 코드 직접 추적 결과:

| 그룹                  | 동적 구성 여부                               | MCP 대상?          |
| --------------------- | -------------------------------------------- | ------------------ |
| A — 조회              | ❌ `settings_catalog` 7개 정적 도메인         | 이번 Epic 제외     |
| B — 변경              | ❌ 동일 정적 카탈로그                         | 이번 Epic 제외     |
| **C — 동적 REST-API** | **✅ OpenAPI 업로드 → DB → 런타임 Tool 생성** | **이번 Epic 대상** |
| D — 투명성            | ❌ Tool 자체는 정적                           | 이번 Epic 제외     |

그룹 C만 "문서 업로드만으로 연계가 동적으로 구성"된다는 요건에 부합한다.

---

## 1. 현재 그룹 C 구현 상태 (재확인)

```
OpenAPI 스펙 업로드
  └─ document_adapters.py::OpenApiSpecAdapter
        │  엔드포인트 파싱
        ▼
  knowledge_document_endpoints 테이블
  (document_id / method / endpoint_path / parameters / request_body)
        │
  build_dynamic_tools_for_owner(owner)     ← 이미 완성된 핵심 로직
        │  DB 조회 → 승인 필터 → 클로저 Tool 생성
        ▼
  LangGraph 루프 (Story 1.51)              ← SIP/SMS 채널에서 사용 중
```

**MCP 서버가 할 일**: 동일한 `build_dynamic_tools_for_owner(owner)`를 호출해  
반환된 LangChain Tool 목록을 FastMCP Tool로 **감싸서 노출**하는 것 뿐이다.  
실행 로직(`execute_api_endpoint`), 승인 검사(`validate_execution_request`),  
Undo(`undo_last_execution`) 모두 기존 코드를 그대로 재사용한다.

---

## 2. 설계 결정

### 2.1 FastMCP 선택 이유

```
pip install fastmcp  (미설치 확인됨 — Story 5.1 착수 시 추가)
```

- `@mcp.tool()` 데코레이터 + `mcp.add_tool()` 런타임 등록 모두 지원
- stdio / SSE 두 transport를 단일 코드베이스로 지원
- 기존 `async def` 함수를 그대로 Tool로 등록 가능 → `_make_dynamic_tool_fn()`과 호환

### 2.2 owner 전달 방식

```bash
python -m src.mcp_gateway.server --owner 9001
```

- MCP 클라이언트 설정 파일(Claude Desktop `claude_desktop_config.json`,  
  VS Code `.vscode/mcp.json`)의 `args`에 `--owner` 값을 고정
- 서버는 시작 시 `owner`로 `build_dynamic_tools_for_owner(owner)`를 호출해  
  Tool 목록을 확정 → MCP Tool로 등록

### 2.3 Tool 이름 충돌 방지

`_sanitize_tool_name(document_id, method, endpoint_path)`가 이미  
`api_{doc_short}_{method}_{slug}` 형식으로 고유한 이름을 만든다 — 그대로 재사용.

### 2.4 동적 재로드 (1차 범위 외)

stdio 모드: 클라이언트 세션마다 프로세스가 재시작되므로 매번 최신 DB 상태를 읽는다.  
→ **업로드 후 MCP 클라이언트를 재연결하면** 새 Tool이 자동으로 반영된다.  
SSE 모드의 실시간 재로드는 1차 범위에서 제외.

---

## 3. 컴포넌트 구조

```
sip-pbx/
  src/
    mcp_gateway/              ← 신규 (이번 Epic)
      __init__.py
      server.py               ← FastMCP 앱 + CLI 진입점
      _tool_bridge.py         ← LangChain Tool → MCP Tool 변환 헬퍼
  requirements-ai.txt         ← fastmcp>=2.0 추가
```

기존 파일은 **한 줄도 수정하지 않는다** — 순수 추가.

---

## 4. 핵심 구현 흐름 (검토용 의사코드)

```python
# src/mcp_gateway/server.py
import argparse
from fastmcp import FastMCP
from src.ai_voicebot.self_service.dynamic_api_tool import build_dynamic_tools_for_owner

def main():
    args = argparse.ArgumentParser()
    args.add_argument("--owner", required=True)
    args.add_argument("--transport", default="stdio", choices=["stdio", "sse"])
    args.add_argument("--port", type=int, default=3001)
    ns = args.parse_args()

    mcp = FastMCP("SIP PBX Dynamic API Gateway")

    # ── 기존 로직 그대로 재사용 ──────────────────────────────────────────
    lc_tools = build_dynamic_tools_for_owner(ns.owner)   # DB → LangChain Tool 목록
    # ─────────────────────────────────────────────────────────────────────

    for lc_tool in lc_tools:
        mcp.add_tool(
            _wrap_lc_tool(lc_tool, default_owner=ns.owner),
            name=lc_tool.__name__,
            description=lc_tool.__doc__ or "",
        )

    if ns.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport="sse", host="127.0.0.1", port=ns.port)


# src/mcp_gateway/_tool_bridge.py
def _wrap_lc_tool(lc_tool, default_owner: str):
    """LangChain Tool의 비동기 함수를 owner 고정 후 MCP Tool 함수로 감싼다."""
    import functools, asyncio, inspect

    underlying = lc_tool.coroutine if hasattr(lc_tool, "coroutine") else lc_tool

    @functools.wraps(underlying)
    async def _mcp_fn(**kwargs):
        kwargs.setdefault("owner", default_owner)   # owner 자동 주입
        return await underlying(**kwargs)

    # owner 파라미터를 시그니처에서 제거해 MCP 클라이언트에 노출하지 않음
    _mcp_fn.__signature__ = _strip_owner_param(inspect.signature(underlying))
    return _mcp_fn
```

---

## 5. MCP 클라이언트 연결 설정 미리보기

### Claude Desktop (`claude_desktop_config.json`)
```json
{
  "mcpServers": {
    "sip-pbx-api": {
      "command": "python",
      "args": ["-m", "src.mcp_gateway.server", "--owner", "9001"],
      "cwd": "C:/work/workspace_sippbx/sip-pbx"
    }
  }
}
```

### VS Code (`.vscode/mcp.json`)
```json
{
  "servers": {
    "sip-pbx-api": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "src.mcp_gateway.server", "--owner", "9001"],
      "cwd": "${workspaceFolder}/sip-pbx"
    }
  }
}
```

---

## 6. 자연어 사용 흐름 미리보기

```
[시나리오: 의류 쇼핑몰 주문 API가 OpenAPI로 업로드·승인된 상태]

사용자(Claude Desktop): "주문 #1234 상태 알려줘"

  → MCP Tool 호출: api_abc12345_get_orders_id(params={"id": "1234"})
  ← {"ok": true, "status": 200, "data": {"order_id": "1234", "status": "배송중"}}

  Claude: "주문 #1234는 현재 배송 중입니다."

사용자: "배송지 수정해줘, 서울 강남구 테헤란로 123"

  → MCP Tool 호출: api_abc12345_put_orders_id(
        params={"id": "1234"},
        body={"shipping_address": "서울 강남구 테헤란로 123"}
      )
  ← {"ok": true, "status": 200, "data": {"updated": true}}

  Claude: "배송지를 수정했습니다."

사용자: "아 잠깐, 취소해줘"

  → MCP Tool 호출: _undo_last_dynamic_api_change(owner="9001")
  ← {"ok": true, "pre_state": {...}, "message": "이전 상태로 복원했습니다."}

  Claude: "수정을 취소하고 이전 배송지로 복원했습니다."
```

---

## 7. Non-Goal (이번 Epic 명시적 범위 제외)

- 그룹 A/B/D Tool 노출 — 이번 Epic 대상 아님
- SSE 모드 실시간 Tool 재로드 — stdio 재연결로 충분
- MCP 인증(OAuth/JWT) — 로컬 stdio 모드에서는 OS 프로세스 보안으로 충분
- 기존 SIP/SMS 채널 코드 수정 — 순수 추가

---

## 8. Story 목록

| Story   | 제목                         | 내용                                                                                                 | 선행조건          |
| ------- | ---------------------------- | ---------------------------------------------------------------------------------------------------- | ----------------- |
| **5.1** | FastMCP 기반 + GET Tool 노출 | `fastmcp` 설치, `server.py`/`_tool_bridge.py` 신규, GET 전용 Tool을 Claude Desktop에서 실제 호출까지 | Story 1.51 Done ✅ |
| **5.2** | 쓰기 Tool + Undo Tool 노출   | 승인된 POST/PUT/DELETE Tool + `_undo_last_dynamic_api_change` 노출, 보안 재검증                      | Story 5.1         |
| **5.3** | 단위테스트 + 연결 가이드     | `tests_new/unit/test_mcp_gateway.py`, `docs/guides/MCP_GATEWAY_GUIDE.md`                             | Story 5.2         |

**권장 착수 순서**: 5.1 → 5.2 → 5.3.  
Story 5.1만 완료해도 MCP 클라이언트에서 조회성 API를 바로 자연어로 사용 가능하다.

---

## 9. Story 5.1 상세 (착수 검토용)

### Acceptance Criteria
- AC1: `pip install fastmcp` 후 `python -m src.mcp_gateway.server --owner 9001 --transport stdio`가 오류 없이 기동된다
- AC2: Claude Desktop 또는 VS Code MCP 설정으로 연결 시, 해당 owner에 업로드된 OpenAPI 문서의 GET 엔드포인트가 Tool로 노출된다
- AC3: Tool 호출이 `execute_api_endpoint()`를 통해 실제 외부 API를 호출하고 결과를 반환한다
- AC4: `owner` 파라미터는 MCP 클라이언트에 노출되지 않는다(서버 내부에서 자동 주입)
- AC5: 업로드된 문서가 없으면 Tool 목록이 비어있고 서버는 정상 기동 상태를 유지한다
- AC6: 기존 REST API(포트 8000)/SIP 서버(포트 5060)에 영향이 없다

### Task 목록
- [ ] Task 1: `requirements-ai.txt`에 `fastmcp>=2.0` 추가
- [ ] Task 2: `src/mcp_gateway/__init__.py` + `_tool_bridge.py` (owner 주입 + 시그니처 제거)
- [ ] Task 3: `src/mcp_gateway/server.py` — argparse, `build_dynamic_tools_for_owner()` 호출, `mcp.add_tool()` 등록, `mcp.run()` 분기
- [ ] Task 4: `start-all.ps1`에 `--mcp` 선택 플래그 추가(기본 미기동)
- [ ] Task 5: Claude Desktop 또는 VS Code에 연결해 실제 GET Tool 호출로 실서버 IV

### 구현 주의사항
- `build_dynamic_tools_for_owner()`는 `src.booking.database.get_db`를 사용하므로  
  `DB_PATH` 환경변수가 서버 기동 전에 설정되어 있어야 한다(`start-all.ps1`과 동일).
- `_tool_bridge.py`의 `_strip_owner_param()`은 `inspect.Signature`의 파라미터에서  
  `owner`를 제거한 새 `Signature`를 반환한다 — FastMCP가 이 시그니처로 JSON Schema를 생성.
- LangChain Tool의 실제 비동기 함수는 `lc_tool.coroutine`(StructuredTool) 또는  
  `lc_tool` 자체(plain async def)이므로 두 경우 모두 처리.

---

*최종 업데이트: 2026-08-10*

