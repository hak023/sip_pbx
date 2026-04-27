"""
통화 종료 시 통화 이력용 인사이트(착신 요약, AI 미응대 목록).

- needs_follow_up / HITL 에스컬레이션 시 버퍼에 적재.
- 운영자 HITL 응답 제출 시 질문 매칭으로 resolved_by_hitl 표시 → 최종 리스트·count에서 제외.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_lock = threading.Lock()
# call_id -> list of insight rows
_buffers: Dict[str, List[Dict[str, Any]]] = {}


def _norm_q(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


def _questions_match(stored: str, operator_q: str) -> bool:
    a = _norm_q(stored)
    b = _norm_q(operator_q)
    if not a or not b:
        return False
    if a == b:
        return True
    if len(a) >= 8 and a in b:
        return True
    if len(b) >= 8 and b in a:
        return True
    return False


def record_ai_limitation(
    call_id: str,
    user_question: str,
    ai_response: str,
    *,
    kind: str,
    reason: str = "",
) -> None:
    """
    AI가 스스로 해결하지 못한 턴 기록.

    kind:
      - needs_follow_up: 에이전트 needs_follow_up (모르는 내용 등)
      - hitl_escalation: needs_human 이지만 needs_follow_up 아님 (저신뢰·전환 등)
    """
    if not call_id or not (user_question or "").strip():
        return
    row = {
        "id": str(uuid.uuid4()),
        "user_question": (user_question or "").strip(),
        "ai_response_preview": (ai_response or "").strip()[:500],
        "kind": kind,
        "reason": (reason or "").strip()[:300],
        "resolved_by_hitl": False,
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    with _lock:
        _buffers.setdefault(call_id, []).append(row)


def mark_hitl_resolved_for_questions(call_id: str, *question_candidates: str) -> int:
    """
    운영자 HITL 제출 시 질문 문자열들과 매칭되는 미해결 건을 resolved로 표시.

    Returns:
        표시를 바꾼 행 수
    """
    cands = [c for c in question_candidates if (c or "").strip()]
    if not call_id or not cands:
        return 0
    n = 0
    with _lock:
        rows = _buffers.get(call_id)
        if not rows:
            return 0
        for item in rows:
            if item.get("resolved_by_hitl"):
                continue
            uq = item.get("user_question") or ""
            for c in cands:
                if _questions_match(uq, c):
                    item["resolved_by_hitl"] = True
                    n += 1
                    break
    return n


_CALLEE_SPEAKER_LABELS = frozenset(
    {"착신자", "Callee", "callee", "AI", "assistant", "착신", "상담원"}
)
_CALLER_SPEAKER_LABELS = frozenset(
    {"발신자", "Caller", "caller", "고객", "사용자", "user", "발신", "고객님"}
)


def _messages_from_transcript_txt(text: str) -> List[Dict[str, Any]]:
    """
    `transcript.txt` (발신자: / 착신자: 또는 pipeline 한 줄 형식) → 요약용 메시지 목록.
    `conversation.json` 이 없을 때(후처리 STT·일부 녹음) 요약이 비지 않게 한다.
    """
    messages: List[Dict[str, Any]] = []
    for raw_line in text.splitlines():
        line_stripped = raw_line.strip()
        if not line_stripped:
            continue
        for sep in (": ", "："):
            if sep not in line_stripped:
                continue
            label, rest = line_stripped.split(sep, 1)
            label = label.strip()
            rest = (rest or "").strip()
            if not rest:
                break
            lnorm = label.casefold()
            if label in _CALLEE_SPEAKER_LABELS or lnorm in {x.casefold() for x in _CALLEE_SPEAKER_LABELS}:
                role = "assistant"
            elif label in _CALLER_SPEAKER_LABELS or lnorm in {x.casefold() for x in _CALLER_SPEAKER_LABELS}:
                role = "user"
            else:
                role = "user"
            messages.append({"role": role, "content": rest})
            break
    if not messages and (text or "").strip():
        messages.append({"role": "user", "content": (text.strip())[:8000]})
    return messages


def _build_callee_summary(
    messages: List[Dict[str, Any]],
    *,
    duration_sec: float,
    caller_id: str,
    callee_id: str,
    is_ai_transcript: bool,
) -> str:
    """착신자(테넌트/AI) 관점 규칙 기반 요약 (LLM 없음)."""
    user_n = sum(1 for m in messages if m.get("role") == "user")
    asst_n = sum(1 for m in messages if m.get("role") == "assistant")
    lines: List[str] = []
    lines.append(
        f"착신자 기준 요약: 통화 시간 약 {max(0, int(duration_sec))}초, "
        f"발신 {caller_id or '-'}, 착신 {callee_id or '-'}."
    )
    if is_ai_transcript:
        lines.append(f"AI 응대 대화: 고객 발화 {user_n}회, AI(착신) 응답 {asst_n}회.")
    else:
        lines.append(f"대화 로그: 발신측 {user_n}회, 착신측 {asst_n}회.")
    for m in messages:
        if m.get("role") == "user":
            prev = (m.get("content") or "").strip()
            if prev:
                snippet = prev if len(prev) <= 120 else prev[:117] + "…"
                lines.append(f"첫 발신측 발화: {snippet}")
            break
    if asst_n and messages:
        last_a = ""
        for m in reversed(messages):
            if m.get("role") == "assistant":
                last_a = (m.get("content") or "").strip()
                break
        if last_a:
            snippet = last_a if len(last_a) <= 120 else last_a[:117] + "…"
            if is_ai_transcript:
                lines.append(f"마지막 착신(AI) 응답: {snippet}")
            else:
                lines.append(f"마지막 착신측 발화: {snippet}")
    return "\n".join(lines)


def collect_messages_for_summary(call_dir: Path) -> tuple[List[Dict[str, Any]], bool]:
    """
    요약용 메시지 목록 수집.

    Returns:
        (messages, from_conversation) — 후자가 True면 파이프라인 `conversation.json` 기반(AI 응대).
    """
    messages: List[Dict[str, Any]] = []
    from_conversation = False
    conv_path = call_dir / "conversation.json"
    if conv_path.is_file():
        try:
            with open(conv_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            raw = data.get("messages")
            if isinstance(raw, list):
                for m in raw:
                    if isinstance(m, dict) and (m.get("content") or "").strip():
                        role = m.get("role") or "user"
                        if role not in ("user", "assistant"):
                            role = "assistant" if role in ("착신자", "callee") else "user"
                        messages.append({"role": role, "content": (m.get("content") or "").strip()})
            from_conversation = len(messages) > 0
        except (OSError, json.JSONDecodeError):
            messages = []
            from_conversation = False

    if not messages:
        tp = call_dir / "transcript.txt"
        if tp.is_file():
            try:
                raw_txt = tp.read_text(encoding="utf-8", errors="replace")
            except OSError:
                raw_txt = ""
            messages = _messages_from_transcript_txt(raw_txt)

    return messages, from_conversation


def resolve_callee_summary_for_list_item(
    call_dir: Path,
    meta: Dict[str, Any],
    insights: Optional[Dict[str, Any]],
) -> tuple[Optional[str], bool]:
    """
    통화 이력 목록 API용: `call_insights.json`이 있으면 그대로, 없으면 디렉터리만으로 요약 계산.
    """
    if insights:
        summ = insights.get("callee_summary")
        if summ is not None and not isinstance(summ, str):
            summ = str(summ)
        return summ, bool(insights.get("is_ai_handled_call"))

    messages, from_conversation = collect_messages_for_summary(call_dir)
    if not messages:
        return None, (call_dir / "conversation.json").is_file()

    try:
        dur = float(meta.get("duration") or 0)
    except (TypeError, ValueError):
        dur = 0.0
    caller_id = str(meta.get("caller_id") or "")
    callee_id = str(meta.get("callee_id") or "")
    summary = _build_callee_summary(
        messages,
        duration_sec=dur,
        caller_id=caller_id,
        callee_id=callee_id,
        is_ai_transcript=from_conversation,
    )
    return summary, from_conversation


def flush_call_insights_to_dir(
    call_id: str,
    call_dir: Path,
    *,
    duration_sec: float,
    caller_id: str,
    callee_id: str,
) -> int:
    """
    버퍼를 call_insights.json 으로 저장하고 call_id 버퍼를 비운다.

    conversation.json 이 있으면 요약에 사용하고, 없으면 transcript.txt 를 파싱한다.

    Returns:
        저장한 `ai_unhandled_items` 개수 (HITL로 해결된 항목 제외)
    """
    if not call_id:
        return 0
    with _lock:
        rows = _buffers.pop(call_id, None)
    if rows is None:
        rows = []

    messages, from_conversation = collect_messages_for_summary(call_dir)
    is_ai_handled = from_conversation
    summary = _build_callee_summary(
        messages,
        duration_sec=duration_sec,
        caller_id=caller_id,
        callee_id=callee_id,
        is_ai_transcript=from_conversation,
    )

    unhandled = [r for r in rows if not r.get("resolved_by_hitl")]
    public_items = [
        {
            "id": r["id"],
            "user_question": r["user_question"],
            "ai_response_preview": r.get("ai_response_preview") or "",
            "kind": r.get("kind") or "unknown",
            "reason": r.get("reason") or "",
        }
        for r in unhandled
    ]

    unhandled_count = len(public_items)
    payload = {
        "call_id": call_id,
        "callee_summary": summary,
        "is_ai_handled_call": is_ai_handled,
        "call_summary": None,
        "call_summary_source": None,
        "call_summary_generated_at": None,
        "ai_unhandled_items": public_items,
        "ai_unhandled_count": unhandled_count,
        "ai_unhandled_total_recorded": len(rows),
        "ai_unhandled_resolved_by_hitl_count": sum(1 for r in rows if r.get("resolved_by_hitl")),
        "is_unresolved": unhandled_count > 0,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }

    call_dir.mkdir(parents=True, exist_ok=True)
    out_path = call_dir / "call_insights.json"
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except OSError:
        with _lock:
            prev = _buffers.get(call_id, [])
            _buffers[call_id] = list(rows) + prev
        raise

    return len(public_items)


def load_call_insights_for_directory(call_dir: Path) -> Optional[Dict[str, Any]]:
    p = call_dir / "call_insights.json"
    if not p.is_file():
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
