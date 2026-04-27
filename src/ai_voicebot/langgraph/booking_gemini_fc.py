"""
예약 에이전트용 Gemini 네이티브 function calling.

`LLMClient`는 LangChain `BaseChatModel`을 노출하지 않아 `bind_tools` 경로가 비어 있을 수 있다.
동일 `google.generativeai.GenerativeModel` + `glm.Tool` 로 도구 선언 후,
응답의 `function_call` → 로컬 실행 → `function_response` 를 이어 붙여 LLM 최종 텍스트를 얻는다.

루프 중 메시지는 LangChain `AIMessage`/`ToolMessage` 형태로 유지해
`booking_agent`의 히스토리·슬롯 추출 로직과 호환된다.
"""

from __future__ import annotations

import asyncio
import json
import math
import uuid
from typing import Any, Dict, List, Optional, Sequence, Tuple

import structlog
from google.ai import generativelanguage as glm
from google.protobuf import struct_pb2
from google.protobuf.json_format import MessageToDict, ParseDict

logger = structlog.get_logger(__name__)


def _json_type_to_glm(t: str) -> "glm.Type":
    m = {
        "string": glm.Type.STRING,
        "number": glm.Type.NUMBER,
        "integer": glm.Type.INTEGER,
        "boolean": glm.Type.BOOLEAN,
        "object": glm.Type.OBJECT,
        "array": glm.Type.ARRAY,
    }
    return m.get((t or "").lower(), glm.Type.STRING)


def _json_schema_to_glm_schema(schema: Optional[dict]) -> Optional["glm.Schema"]:
    """OpenAPI-style JSON Schema subset → glm.Schema (예약 도구용)."""
    if not schema or not isinstance(schema, dict):
        return None

    if "anyOf" in schema and isinstance(schema["anyOf"], list) and schema["anyOf"]:
        return _json_schema_to_glm_schema(schema["anyOf"][0])

    st = (schema.get("type") or "").lower()
    if st == "array":
        items = schema.get("items")
        sub = _json_schema_to_glm_schema(items) if isinstance(items, dict) else None
        out = glm.Schema(type_=glm.Type.ARRAY)
        if sub is not None:
            out.items = sub
        return out

    if st in ("object", "") or "properties" in schema:
        props_map: dict[str, glm.Schema] = {}
        for key, sub in (schema.get("properties") or {}).items():
            if isinstance(sub, dict):
                conv = _json_schema_to_glm_schema(sub)
                if conv is not None:
                    props_map[key] = conv
        req = [str(x) for x in (schema.get("required") or []) if x]
        return glm.Schema(
            type_=glm.Type.OBJECT,
            properties=props_map,
            required=req,
            description=str(schema.get("description", "") or "")[:2000],
        )

    desc = str(schema.get("description", "") or "")[:2000]
    fmt = str(schema.get("format", "") or "")
    sch = glm.Schema(type_=_json_type_to_glm(st), description=desc)
    if fmt:
        sch.format_ = fmt
    if schema.get("enum"):
        sch.enum.extend([str(e) for e in schema["enum"]])
    return sch


def _langchain_tools_to_glm_tool(tools: Sequence[Any]) -> glm.Tool:
    declarations: List[glm.FunctionDeclaration] = []
    for t in tools:
        name = getattr(t, "name", None) or getattr(t, "__name__", "")
        if not name:
            continue
        desc = getattr(t, "description", None) or (getattr(t, "__doc__", None) or "")[:8000]
        args_schema = getattr(t, "args_schema", None)
        params: Optional[glm.Schema] = None
        if args_schema is not None and hasattr(args_schema, "model_json_schema"):
            try:
                raw = args_schema.model_json_schema()
                params = _json_schema_to_glm_schema(raw)
            except Exception as e:
                logger.warning("booking_gemini_fc_schema_convert_failed", tool=name, error=str(e))
        declarations.append(
            glm.FunctionDeclaration(name=name, description=desc[:8000], parameters=params)
        )
    return glm.Tool(function_declarations=declarations)


def _sanitize_for_gemini_struct(obj: Any, *, max_str_len: int = 12000, depth: int = 0) -> Any:
    """protobuf Struct / Value 에 넣을 수 있는 JSON 호환 값만 남긴다 (MapComposite·extra_data 직렬화 오류 방지)."""
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
            out[sk] = _sanitize_for_gemini_struct(v, max_str_len=max_str_len, depth=depth + 1)
        return out
    if isinstance(obj, (list, tuple)):
        return [
            _sanitize_for_gemini_struct(x, max_str_len=max_str_len, depth=depth + 1) for x in obj
        ]
    return str(obj)[:max_str_len]


def _json_debug_preview(data: Any, *, limit: int = 14000) -> str:
    """ParseDict 실패 등 디버깅용 — 운영 로그에만 쓰고 PI는 별도 마스킹 정책이 있으면 적용."""
    try:
        s = json.dumps(data, ensure_ascii=False, default=str)
    except Exception as ex:
        return f"<json.dumps_failed {type(ex).__name__}:{ex!s}> {repr(data)[:limit]}"
    if len(s) > limit:
        return s[: max(0, limit - 24)] + "…<truncated_for_log>"
    return s


def _struct_from_jsonable(obj: Any, *, debug_context: str = "") -> struct_pb2.Struct:
    if isinstance(obj, struct_pb2.Struct):
        return obj
    if isinstance(obj, str):
        try:
            obj = json.loads(obj)
        except Exception:
            obj = {"result": obj}
    if not isinstance(obj, dict):
        obj = {"value": obj}
    # ParseDict 직전 스냅샷(정규화 전 dict) — 실패 시 원인 역추적용
    _incoming_for_log = dict(obj) if isinstance(obj, dict) else obj
    clean = _sanitize_for_gemini_struct(obj)
    s = struct_pb2.Struct()
    try:
        ParseDict(clean, s, ignore_unknown_fields=True)
    except Exception as e:
        logger.warning(
            "booking_gemini_struct_parse_failed_fallback",
            debug_context=debug_context or "(unset)",
            error=str(e),
            error_type=type(e).__name__,
            keys_after_sanitize=list(clean.keys())[:48] if isinstance(clean, dict) else None,
            keys_incoming=list(_incoming_for_log.keys())[:48]
            if isinstance(_incoming_for_log, dict)
            else None,
            sanitized_json_preview=_json_debug_preview(clean, limit=14000),
            incoming_json_preview=_json_debug_preview(_incoming_for_log, limit=14000),
            note=(
                "Gemini FunctionCall/FunctionResponse용 Struct 빌드 실패. "
                "incoming=sanitize 전·sanitized=sanitize 후. 응답 문장 품질과 무관할 수 있음."
            ),
        )
        fb = _sanitize_for_gemini_struct(
            {
                "error": "struct_serialization_fallback",
                "detail": str(e)[:800],
                "debug_context": (debug_context or "")[:200],
                "payload_preview": json.dumps(clean, ensure_ascii=True, default=str)[:8000],
            }
        )
        ParseDict(fb, s, ignore_unknown_fields=True)
    return s


def _function_call_args_to_dict(args: Any) -> Dict[str, Any]:
    if args is None:
        return {}
    if isinstance(args, struct_pb2.Struct):
        return MessageToDict(args, preserving_proto_field_name=True)
    if hasattr(args, "items"):
        return dict(args.items())
    return {}


def _lc_messages_to_gemini_contents(
    messages: Sequence[Any],
) -> Tuple[List[glm.Content], str]:
    """LangChain 메시지 → Gemini contents. SystemMessage 는 첫 user 텍스트에 합친다."""
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

    system_chunks: List[str] = []
    out: List[glm.Content] = []
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
            out.append(glm.Content(role="user", parts=[glm.Part(text=text)]))
            continue
        if isinstance(m, AIMessage):
            parts: List[glm.Part] = []
            tc_list = getattr(m, "tool_calls", None) or []
            for tc in tc_list:
                nm = tc.get("name", "")
                raw_args = tc.get("args", {}) or {}
                fc = glm.FunctionCall(
                    name=nm,
                    args=_struct_from_jsonable(raw_args, debug_context=f"function_call.args:{nm}"),
                )
                parts.append(glm.Part(function_call=fc))
            content = getattr(m, "content", None)
            if content and isinstance(content, str) and content.strip():
                parts.append(glm.Part(text=content))
            if parts:
                out.append(glm.Content(role="model", parts=parts))
            continue
        if isinstance(m, ToolMessage):
            name = getattr(m, "name", None) or ""
            body = getattr(m, "content", "") or ""
            try:
                payload = json.loads(body) if isinstance(body, str) else body
            except Exception:
                payload = {"raw": str(body)[:4000]}
            fr = glm.FunctionResponse(
                name=name or "unknown",
                response=_struct_from_jsonable(
                    payload,
                    debug_context=f"function_response.body:{name or 'unknown'}",
                ),
            )
            out.append(glm.Content(role="function", parts=[glm.Part(function_response=fr)]))
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


async def invoke_booking_model_with_gemini_fc(
    *,
    gen_model: Any,
    lc_messages: List[Any],
    generation_config: Any,
) -> Any:
    contents, _ = _lc_messages_to_gemini_contents(lc_messages)

    def _call() -> Any:
        return gen_model.generate_content(contents, generation_config=generation_config)

    return await asyncio.to_thread(_call)


def build_booking_generative_model(llm_client: Any, glm_tool: glm.Tool) -> Any:
    """기존 LLMClient와 동일 모델명으로 tools 가 붙은 GenerativeModel."""
    import google.generativeai as genai

    model_name = getattr(llm_client.model, "model_name", None) or getattr(
        llm_client.model, "_model_name", "models/gemini-2.0-flash"
    )
    return genai.GenerativeModel(model_name=model_name, tools=[glm_tool])
