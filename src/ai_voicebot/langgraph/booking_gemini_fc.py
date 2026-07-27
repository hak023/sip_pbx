"""
예약 에이전트용 Gemini 네이티브 function calling.

`LLMClient`는 LangChain `BaseChatModel`을 노출하지 않아 `bind_tools` 경로가 비어 있을 수 있다.
Gemini `types.Tool`로 도구 선언 후, 응답의 `function_call` → 로컬 실행 → `function_response`
를 이어 붙여 LLM 최종 텍스트를 얻는다.

루프 중 메시지는 LangChain `AIMessage`/`ToolMessage` 형태로 유지해
`booking_agent`의 히스토리·슬롯 추출 로직과 호환된다.

[2026-07-24, Story 6.2 — Epic 6 Gemini SDK 마이그레이션] 기존 `google.ai.generativelanguage`
(`glm`, protobuf 기반) 대신 `google.genai.types`(pydantic 기반, `LLMClient`가 Story 6.1에서
전환한 것과 동일 SDK)를 사용한다. 참고: docs/architecture/gemini-genai-migration-architecture.md §4.
- `types.FunctionCall.args`/`types.FunctionResponse.response`는 protobuf Struct가 아니라
  **일반 Python dict**라 `struct_pb2`/`ParseDict` 기반 직렬화 코드가 전부 제거됐다(단순화).
- `build_booking_generative_model()`은 더 이상 "tools가 바인딩된 GenerativeModel 인스턴스"를
  반환하지 않는다 — google-genai는 이런 재사용 모델 객체 개념이 없고 호출마다
  `GenerateContentConfig(tools=[...])`로 tools를 실어 보내는 stateless 방식이다. 대신
  `_GenAIToolModel`(client/model_name/tool을 담는 경량 컨테이너)을 반환하며, 이 반환값은
  호출부(`booking_agent.py`, `self_service_agent.py`)에서 `invoke_booking_model_with_gemini_fc()`
  에만 그대로 전달되는 불투명(opaque) 객체이므로 **호출부 코드는 전혀 수정하지 않았다**(CR1).
"""

from __future__ import annotations

import asyncio
import json
import math
import uuid
from typing import Any, Dict, List, Optional, Sequence, Tuple

import structlog
from google.genai import types as genai_types

logger = structlog.get_logger(__name__)


def _json_type_to_genai(t: str) -> "genai_types.Type":
    m = {
        "string": genai_types.Type.STRING,
        "number": genai_types.Type.NUMBER,
        "integer": genai_types.Type.INTEGER,
        "boolean": genai_types.Type.BOOLEAN,
        "object": genai_types.Type.OBJECT,
        "array": genai_types.Type.ARRAY,
    }
    return m.get((t or "").lower(), genai_types.Type.STRING)


def _json_schema_to_genai_schema(schema: Optional[dict]) -> Optional["genai_types.Schema"]:
    """OpenAPI-style JSON Schema subset → genai_types.Schema (예약 도구용).

    [2026-07-21, Story 1.14 근본 원인 수정, Story 6.2에서 google-genai 기준으로 이식] Python
    함수 파라미터를 `Any`로 선언하면(예: `self_service/tools.py::_update_self_service_setting`의
    `value: Any` — 필드마다 boolean/enum 문자열/자유 문자열 등 타입이 제각각이라 의도적으로
    `Any`로 둠) Pydantic이 생성하는 JSON Schema는 `{"title": "Value"}`처럼 `type` 키 자체가
    없다. 예전 코드는 `st in ("object", "")`로 "명시적 object 선언"과 "타입 정보 자체가
    없음(Any)"을 똑같이 취급해 **`type` 없는 필드를 전부 프로퍼티 0개짜리 OBJECT로 선언**해
    버렸다 — Gemini function-calling은 선언된 스키마에 맞춰 인자를 생성하므로, 실제로는
    문자열/불리언 값을 보내야 하는데 스키마상 "빈 OBJECT"만 허용되면 짧은 값(불리언/enum)은
    우연히 통과해도 긴 자유 문자열 값(예: persona.description)은 스키마를 만족시키지 못해
    아예 아무 응답도 생성하지 못하는(완전히 빈 candidate) 현상으로 이어졌다(결함③, Epic 2
    Story 2.7에서 발견). 수정: `type`이 없고 `properties`도 없는 필드(=Any/무제약)는 OBJECT로
    취급하지 않고 STRING으로 취급한다 — Gemini 스키마에 "any" 타입이 없으므로 가장 관대한
    원시 타입인 문자열로 선언하고, 호출측(`tools.py::_coerce_value()`)이 이미 문자열→불리언
    등 후처리를 담당하므로 안전하다. google-genai 이식 시에도 동일 분기 로직을 그대로
    유지한다(회귀 테스트: `test_booking_gemini_fc_schema.py`).
    """
    if not schema or not isinstance(schema, dict):
        return None

    if "anyOf" in schema and isinstance(schema["anyOf"], list) and schema["anyOf"]:
        return _json_schema_to_genai_schema(schema["anyOf"][0])

    st = (schema.get("type") or "").lower()
    if st == "array":
        items = schema.get("items")
        sub = _json_schema_to_genai_schema(items) if isinstance(items, dict) else None
        out = genai_types.Schema(type=genai_types.Type.ARRAY)
        if sub is not None:
            out.items = sub
        return out

    if st == "object" or (st == "" and "properties" in schema):
        props_map: dict[str, genai_types.Schema] = {}
        for key, sub in (schema.get("properties") or {}).items():
            if isinstance(sub, dict):
                conv = _json_schema_to_genai_schema(sub)
                if conv is not None:
                    props_map[key] = conv
        req = [str(x) for x in (schema.get("required") or []) if x]
        return genai_types.Schema(
            type=genai_types.Type.OBJECT,
            properties=props_map,
            required=req,
            description=str(schema.get("description", "") or "")[:2000],
        )

    if st == "":
        # 타입 정보가 전혀 없는 필드(Python `Any`) — OBJECT가 아니라 가장 관대한 STRING으로 취급.
        st = "string"

    desc = str(schema.get("description", "") or "")[:2000]
    fmt = str(schema.get("format", "") or "")
    sch = genai_types.Schema(type=_json_type_to_genai(st), description=desc)
    if fmt:
        sch.format = fmt
    if schema.get("enum"):
        sch.enum = [str(e) for e in schema["enum"]]
    return sch


def _langchain_tools_to_glm_tool(tools: Sequence[Any]) -> "genai_types.Tool":
    """LangChain tool 목록 → `genai_types.Tool`. (함수명은 하위 호환을 위해 유지, 실제로는

    glm이 아니라 google-genai 타입을 반환한다 — 호출부는 반환값을 opaque하게 다루므로
    문제 없음.)
    """
    declarations: List[genai_types.FunctionDeclaration] = []
    for t in tools:
        name = getattr(t, "name", None) or getattr(t, "__name__", "")
        if not name:
            continue
        desc = getattr(t, "description", None) or (getattr(t, "__doc__", None) or "")[:8000]
        args_schema = getattr(t, "args_schema", None)
        params: Optional[genai_types.Schema] = None
        if args_schema is not None and hasattr(args_schema, "model_json_schema"):
            try:
                raw = args_schema.model_json_schema()
                params = _json_schema_to_genai_schema(raw)
            except Exception as e:
                logger.warning("booking_gemini_fc_schema_convert_failed", tool=name, error=str(e))
        declarations.append(
            genai_types.FunctionDeclaration(name=name, description=desc[:8000], parameters=params)
        )
    return genai_types.Tool(function_declarations=declarations)


def _sanitize_for_gemini_json(obj: Any, *, max_str_len: int = 12000, depth: int = 0) -> Any:
    """function_call.args / function_response.response에 넣을 수 있는 JSON 호환 값만 남긴다

    (MapComposite·extra_data 등 비-JSON 객체 직렬화 오류 방지). google-genai에서는 protobuf
    Struct 변환이 필요 없어졌지만(단순 dict), LangChain Tool args/실행 결과에는 여전히 JSON이
    아닌 객체가 섞여 들어올 수 있어 방어적으로 정제한다.
    """
    if depth > 48:
        return "<max_depth>"
    if obj is None:
        return None
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, int) and not isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return str(obj)
        return obj
    if isinstance(obj, str):
        if len(obj) > max_str_len:
            return obj[: max_str_len - 3] + "..."
        return obj
    if isinstance(obj, dict):
        out: Dict[str, Any] = {}
        for k, v in obj.items():
            sk = str(k)
            if not sk:
                continue
            out[sk] = _sanitize_for_gemini_json(v, max_str_len=max_str_len, depth=depth + 1)
        return out
    if isinstance(obj, (list, tuple)):
        return [
            _sanitize_for_gemini_json(x, max_str_len=max_str_len, depth=depth + 1) for x in obj
        ]
    return str(obj)[:max_str_len]


def _dict_from_jsonable(obj: Any, *, debug_context: str = "") -> Dict[str, Any]:
    """function_call.args / function_response.response용 plain dict 빌드.

    google-genai는 protobuf Struct가 아니라 일반 dict를 받으므로(Story 6.2), 예전
    `_struct_from_jsonable()`의 ParseDict 실패 복구 로직은 더 이상 필요 없다 — 순수 Python
    직렬화이므로 실패할 일이 구조적으로 없다(단, JSON 비호환 객체는 `_sanitize_for_gemini_json`
    으로 방어적으로 정제).
    """
    if isinstance(obj, str):
        try:
            obj = json.loads(obj)
        except Exception:
            obj = {"result": obj}
    if not isinstance(obj, dict):
        obj = {"value": obj}
    try:
        return _sanitize_for_gemini_json(obj)
    except Exception as e:
        logger.warning(
            "booking_gemini_dict_sanitize_failed_fallback",
            debug_context=debug_context or "(unset)",
            error=str(e),
            error_type=type(e).__name__,
        )
        return {
            "error": "sanitize_fallback",
            "detail": str(e)[:800],
            "debug_context": (debug_context or "")[:200],
        }


def _function_call_args_to_dict(args: Any) -> Dict[str, Any]:
    if args is None:
        return {}
    if isinstance(args, dict):
        return dict(args)
    if hasattr(args, "items"):
        return dict(args.items())
    return {}


def _lc_messages_to_gemini_contents(
    messages: Sequence[Any],
) -> Tuple[List["genai_types.Content"], str]:
    """LangChain 메시지 → Gemini contents. SystemMessage 는 첫 user 텍스트에 합친다."""
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

    system_chunks: List[str] = []
    out: List[genai_types.Content] = []
    system_merged = False

    for m in messages:
        if isinstance(m, SystemMessage):
            c = getattr(m, "content", "") or ""
            if isinstance(c, str) and c.strip():
                system_chunks.append(c.strip())
            continue
        if isinstance(m, HumanMessage):
            c = getattr(m, "content", "") or ""
            text = c if isinstance(c, str) else str(c)
            if not system_merged and system_chunks:
                text = "\n\n".join(system_chunks) + "\n\n---\n\n" + text
                system_merged = True
            out.append(genai_types.Content(role="user", parts=[genai_types.Part(text=text)]))
            continue
        if isinstance(m, AIMessage):
            parts: List[genai_types.Part] = []
            tc_list = getattr(m, "tool_calls", None) or []
            for tc in tc_list:
                nm = tc.get("name", "")
                raw_args = tc.get("args", {}) or {}
                fc = genai_types.FunctionCall(
                    name=nm,
                    args=_dict_from_jsonable(raw_args, debug_context=f"function_call.args:{nm}"),
                )
                parts.append(genai_types.Part(function_call=fc))
            content = getattr(m, "content", None)
            if content and isinstance(content, str) and content.strip():
                parts.append(genai_types.Part(text=content))
            if parts:
                out.append(genai_types.Content(role="model", parts=parts))
            continue
        if isinstance(m, ToolMessage):
            name = getattr(m, "name", None) or ""
            body = getattr(m, "content", "") or ""
            try:
                payload = json.loads(body) if isinstance(body, str) else body
            except Exception:
                payload = {"raw": str(body)[:4000]}
            fr = genai_types.FunctionResponse(
                name=name or "unknown",
                response=_dict_from_jsonable(
                    payload,
                    debug_context=f"function_response.body:{name or 'unknown'}",
                ),
            )
            out.append(genai_types.Content(role="function", parts=[genai_types.Part(function_response=fr)]))
            continue

    sys_prefix = "\n\n".join(system_chunks) if system_chunks else ""
    return out, sys_prefix


def _candidate_function_calls(response: Any) -> List[Tuple[str, Dict[str, Any], str]]:
    """(name, args_dict, synthetic_id) 목록."""
    out: List[Tuple[str, Dict[str, Any], str]] = []
    try:
        cands = getattr(response, "candidates", None) or []
        if not cands:
            return out
        parts = getattr(cands[0].content, "parts", None) or []
        for p in parts:
            fc = getattr(p, "function_call", None)
            if fc is None or not getattr(fc, "name", ""):
                continue
            nm = fc.name
            args = _function_call_args_to_dict(getattr(fc, "args", None))
            out.append((nm, args, f"call_{uuid.uuid4().hex[:12]}"))
    except Exception as e:
        logger.warning("booking_gemini_fc_parse_calls_failed", error=str(e))
    return out


def _candidate_text(response: Any) -> str:
    try:
        t = getattr(response, "text", None)
        if t:
            return str(t).strip()
    except Exception:
        pass
    try:
        cands = getattr(response, "candidates", None) or []
        if not cands:
            return ""
        chunks: List[str] = []
        for p in getattr(cands[0].content, "parts", None) or []:
            tx = getattr(p, "text", None)
            if tx:
                chunks.append(str(tx))
        return "".join(chunks).strip()
    except Exception:
        return ""


class _GenAIToolModel:
    """`build_booking_generative_model()`의 반환 객체.

    google-genai는 "tools가 바인딩된 재사용 모델 인스턴스" 개념이 없어(stateless
    `client.models.generate_content(model=, contents=, config=)` 방식), client/model_name/tool을
    담아두는 경량 컨테이너로 대체한다. 호출부(`booking_agent.py` 등)는 이 객체를
    `invoke_booking_model_with_gemini_fc(gen_model=...)`에만 그대로 넘기므로 opaque해도 무방하다
    (CR1 — 호출부 코드 무변경).
    """

    __slots__ = ("client", "model_name", "tool")

    def __init__(self, client: Any, model_name: str, tool: "genai_types.Tool"):
        self.client = client
        self.model_name = model_name
        self.tool = tool


async def invoke_booking_model_with_gemini_fc(
    *,
    gen_model: Any,
    lc_messages: List[Any],
    generation_config: Any,
) -> Any:
    contents, _ = _lc_messages_to_gemini_contents(lc_messages)

    # generation_config(Story 6.1에서 이미 genai_types.GenerateContentConfig)에 tools를 얹은
    # 새 config를 만든다 — google-genai는 모델이 아니라 config에 tools를 실어 보낸다(위 클래스
    # docstring 참고).
    if hasattr(generation_config, "model_copy"):
        cfg = generation_config.model_copy(update={"tools": [gen_model.tool]})
    else:
        cfg = genai_types.GenerateContentConfig(tools=[gen_model.tool])

    def _call() -> Any:
        return gen_model.client.models.generate_content(
            model=gen_model.model_name,
            contents=contents,
            config=cfg,
        )

    return await asyncio.to_thread(_call)


def build_booking_generative_model(llm_client: Any, glm_tool: "genai_types.Tool") -> Any:
    """`llm_client`와 동일 client/모델명으로 tools를 실어 보낼 수 있는 컨테이너를 만든다.

    (`glm_tool`이라는 파라미터명은 하위 호환을 위해 유지 — 실제로는 google-genai `types.Tool`.)
    """
    client = getattr(llm_client, "_client", None)
    model_name = getattr(llm_client, "model_name", None) or getattr(
        llm_client.model, "model_name", None
    ) or "gemini-2.5-flash"
    if client is None:
        # Story 6.1 이전 LLMClient(예: 테스트용 목 객체)와의 하위 호환 — 신규 클라이언트를 만든다.
        import os
        from google import genai as _genai_client_module
        from src.common.gemini_api_key import resolve_gemini_api_key

        api_key = resolve_gemini_api_key() or os.environ.get("GEMINI_API_KEY", "")
        client = _genai_client_module.Client(api_key=api_key) if api_key else None
    return _GenAIToolModel(client, model_name, glm_tool)

