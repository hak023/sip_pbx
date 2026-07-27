"""
통화 이력 REST: 녹음 디렉터리 `metadata.json` + `call_insights.json` 병합.

- `append_call_history` / `record_hitl_request`: RAG 등에서 import — 현재는 인덱스는 파일 스캔으로 충분해 디버그 로그만 남김.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from src.common.call_insights_buffer import (
    load_call_insights_for_directory,
    resolve_callee_summary_for_list_item as _resolve_ai_flag,
)
from src.common.sip_owner import normalize_owner_username
from src.common.caller_needle import caller_match_needle as _caller_match_needle

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/call-history", tags=["call-history"])

_ALLOWED_MEDIA = {"mixed": "mixed.wav", "caller": "caller.wav", "callee": "callee.wav"}


def _coerce_bool_unresolved(raw: Any) -> bool:
    """SQLite/JSON 등에서 온 `is_unresolved`를 API 응답용 bool로 정규화.

    ``bool("false")`` 가 True가 되는 것을 막기 위해 문자열 true/false를 구분한다.
    """
    if raw is None:
        return False
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return raw != 0
    if isinstance(raw, str):
        s = raw.strip().lower()
        if s in ("true", "1", "yes", "y", "on"):
            return True
        if s in ("false", "0", "no", "n", "off", ""):
            return False
        return False
    return False


def _resolve_caller_id_for_list(d: Dict[str, Any]) -> str:
    """통화이력 목록용 발신 표시값.

    `metadata.json` / DB `call_records` 가 `caller_id` 없이 `from_number`·`caller` 등만
    넣는 경우가 있어, 프론트가 기대하는 단일 필드를 보강한다.
    """
    for k in ("caller_id", "caller", "from_number", "caller_number", "from"):
        v = d.get(k)
        if v is None:
            continue
        s = str(v).strip()
        if not s or s.lower() in ("unknown", "anonymous"):
            continue
        return s
    raw_uri = d.get("caller_uri")
    if raw_uri:
        u = str(raw_uri).strip()
        low = u.lower()
        if low.startswith("sip:") and "@" in u:
            try:
                user = u.split(":", 1)[1].split("@", 1)[0].strip("<>\" ")
                if user and user.lower() not in ("unknown", "anonymous"):
                    return user
            except (IndexError, ValueError):
                pass
        elif u and u.lower() not in ("unknown", "anonymous"):
            return u
    return ""


def _recordings_root() -> Path:
    raw = (
        os.environ.get("SIP_RECORDINGS_DIR")
        or os.environ.get("RECORDINGS_DIR")
        or "./recordings"
    )
    return Path(raw).resolve()


def append_call_history(entry: Dict[str, Any]) -> None:
    """통화 시작 시 1회 호출(설계상). 목록 소스는 통화 종료 후 `metadata.json` 스캔."""
    cid = entry.get("call_id") if isinstance(entry, dict) else None
    logger.debug("append_call_history call_id=%s", cid)


def record_hitl_request(
    *,
    call_id: str,
    callee_id: str = "",
    user_question: str = "",
    ai_confidence: Optional[float] = None,
    caller_id: Optional[str] = None,
) -> None:
    """HITL 요청 기록 훅 — 미처리 큐는 HITL 서비스·WS 경로 사용."""
    logger.debug(
        "record_hitl_request call_id=%s callee_id=%s q_preview=%s conf=%s caller=%s",
        call_id,
        callee_id,
        (user_question or "")[:80],
        ai_confidence,
        caller_id,
    )


def _owner_matches_row(owner_filter: str, callee_id: str, caller_id: str = "") -> bool:
    """owner_filter가 callee_id(수신) 또는 caller_id(발신) 어느 쪽에든 해당하면 True."""
    if not owner_filter:
        return True
    want = normalize_owner_username(owner_filter)

    def _matches(field: str) -> bool:
        got = normalize_owner_username(field or "")
        if want and got:
            return want == got or want in got or got in want
        return owner_filter.strip().lower() in (field or "").lower()

    return _matches(callee_id) or _matches(caller_id)


def _load_metadata_rows(root: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not root.is_dir():
        return rows
    for sub in root.iterdir():
        if not sub.is_dir() or sub.name.startswith("."):
            continue
        meta_path = sub / "metadata.json"
        if not meta_path.is_file():
            continue
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(meta, dict) or not meta.get("call_id"):
            continue
        meta["_call_dir"] = str(sub)
        rows.append(meta)
    return rows


def _sort_key(m: Dict[str, Any]) -> str:
    return str(m.get("end_time") or m.get("start_time") or "")


def _sip_pbx_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


def _logs_dir() -> Path:
    d = _sip_pbx_root() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _find_call_dir(call_id: str) -> Optional[Path]:
    if not (call_id or "").strip():
        return None
    root = _recordings_root()
    if not root.is_dir():
        return None
    for sub in root.iterdir():
        if not sub.is_dir() or sub.name.startswith("."):
            continue
        meta_path = sub / "metadata.json"
        if not meta_path.is_file():
            continue
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(meta, dict) and str(meta.get("call_id") or "") == str(call_id):
            return sub
    return None


def _scan_call_data_record_for_call(call_id: str, max_items: int) -> Tuple[List[Dict[str, Any]], bool]:
    """`logs/call_data_record_*.log` 에서 해당 call_id 행만 수집 (시간순 정렬)."""
    log_dir = _logs_dir()
    if not log_dir.is_dir():
        return [], False
    files = sorted(log_dir.glob("call_data_record_*.log"), reverse=True)
    out: List[Dict[str, Any]] = []
    truncated = False
    want = str(call_id)
    for path in files:
        if len(out) >= max_items:
            truncated = True
            break
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if len(out) >= max_items:
                        truncated = True
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if str(obj.get("call_id") or "") != want:
                        continue
                    out.append(obj)
        except OSError:
            continue
    out.sort(key=lambda x: str(x.get("ts") or ""))
    return out, truncated


def _recording_flags(call_dir: Path, meta: Dict[str, Any]) -> Dict[str, bool]:
    files = meta.get("files")
    fd: Dict[str, Any] = files if isinstance(files, dict) else {}

    def _has(key: str, wav_name: str) -> bool:
        v = fd.get(key)
        if v and str(v).strip():
            return True
        return (call_dir / wav_name).is_file()

    return {
        "has_recording_mixed": _has("mixed", "mixed.wav"),
        "has_recording_caller": _has("caller", "caller.wav"),
        "has_recording_callee": _has("callee", "callee.wav"),
    }


class UnhandledReplyRequest(BaseModel):
    reply_text: str
    send: bool = False


class ResolveRequest(BaseModel):
    is_unresolved: bool


@router.post("/batch-init-unresolved")
def batch_init_unresolved(
    owner: Optional[str] = Query(None, description="테넌트 필터"),
    dry_run: bool = Query(False, description="true이면 변경 없이 대상만 반환"),
) -> Dict[str, Any]:
    """기존 통화 레코드의 is_unresolved 초기화 배치.

    - call_insights.json이 있으면: JSON의 is_unresolved를 읽어 DB와 파일 모두 정합성 보장
    - call_insights.json이 없으면: ai_unhandled_count > 0 → is_unresolved=True, 아니면 False
    - call_insights.json이 있지만 is_unresolved 키가 없으면: ai_unhandled_count 기반으로 자동 채움

    결과: { processed, skipped, dry_run, details[] }
    """
    root = _recordings_root()
    owner_f = (owner or "").strip()

    details: List[Dict[str, Any]] = []
    processed = 0
    skipped = 0

    # DB 레코드 전체 조회
    db_items: List[Dict[str, Any]] = []
    try:
        from src.common.call_record_db import get_call_records_page
        db_result = get_call_records_page(owner=owner_f, limit=10000, offset=0)
        if db_result:
            db_items = db_result.get("items") or []
    except Exception as exc:
        logger.warning("batch_init_db_load_failed err=%s", exc)

    # 파일 스캔으로도 보완 (DB에 없는 레코드)
    scan_rows = _load_metadata_rows(root)
    db_call_ids = {str(r.get("call_id") or "") for r in db_items}
    for m in scan_rows:
        cid = str(m.get("call_id") or "")
        if not cid or cid in db_call_ids:
            continue
        if owner_f and not _owner_matches_row(
            owner_f,
            str(m.get("callee_id") or ""),
            str(m.get("caller_id") or ""),
        ):
            continue
        db_items.append({
            "call_id": cid,
            "ai_unhandled_count": 0,
            "is_unresolved": None,
            "recordings_dir": m.get("_call_dir") or "",
        })

    for db_row in db_items:
        cid = str(db_row.get("call_id") or "")
        if not cid:
            skipped += 1
            continue

        call_dir = _find_call_dir(cid) or (
            Path(db_row.get("recordings_dir") or "")
            if db_row.get("recordings_dir")
            else None
        )
        insights = load_call_insights_for_directory(call_dir) if call_dir and call_dir.is_dir() else None

        if insights is not None:
            # JSON이 있을 때
            if "is_unresolved" in insights:
                # 이미 명시적으로 설정된 값 → DB 동기화만
                target_val = _coerce_bool_unresolved(insights["is_unresolved"])
                reason = "json_already_set"
            else:
                # JSON은 있지만 is_unresolved 키 없음 → ai_unhandled_count 기반 채움
                target_val = int(insights.get("ai_unhandled_count") or 0) > 0
                reason = "json_inferred_from_unhandled_count"
                if not dry_run:
                    try:
                        insights["is_unresolved"] = target_val
                        insights_path = call_dir / "call_insights.json"  # type: ignore[operator]
                        with open(insights_path, "w", encoding="utf-8") as f:
                            import json as _json
                            _json.dump(insights, f, ensure_ascii=False, indent=2)
                    except Exception as exc:
                        logger.warning("batch_init_json_write_failed call_id=%s err=%s", cid, exc)
        else:
            # JSON 없음 → DB ai_unhandled_count 기반
            target_val = int(db_row.get("ai_unhandled_count") or 0) > 0
            reason = "no_json_inferred_from_db"

        # DB 업데이트
        if not dry_run:
            try:
                from src.common.call_record_db import upsert_call_record
                upsert_call_record(call_id=cid, is_unresolved=target_val)
            except Exception as exc:
                logger.warning("batch_init_db_update_failed call_id=%s err=%s", cid, exc)

        details.append({"call_id": cid, "is_unresolved": target_val, "reason": reason})
        processed += 1

    logger.info(
        "batch_init_unresolved_done owner=%s processed=%s skipped=%s dry_run=%s",
        owner_f, processed, skipped, dry_run,
    )
    return {
        "processed": processed,
        "skipped": skipped,
        "dry_run": dry_run,
        "details": details,
    }


@router.get("/caller-context")
def get_caller_context_for_inbound(
    owner: str = Query(..., description="착신 테넌트(owner / 내선)"),
    caller: str = Query(..., description="발신 식별자(SIP URI 또는 번호)"),
    exclude_call_id: str = Query("", description="현재 진행 중 통화 ID — 직전 이력에서 제외"),
) -> Dict[str, Any]:
    """인입 CID용: 직전 종료 통화 1건, 연락처 표시명, 최근 30일 인입 건수 등.

    DB ``call_records`` 가 비어 있거나 매칭 없으면 ``has_prior_call=false`` (연락처·건수는 별도 조회).
    """
    from datetime import datetime, timedelta, timezone

    own = (owner or "").strip()
    cr = (caller or "").strip()
    if not own or not cr:
        raise HTTPException(status_code=400, detail="owner and caller are required")

    needle, needle_src = _caller_match_needle(cr)
    logger.info(
        "caller_context_request owner=%s caller_preview=%s needle=%s needle_src=%s exclude=%s",
        own[:48],
        (cr[:80] + "...") if len(cr) > 80 else cr,
        needle,
        needle_src,
        (exclude_call_id or "")[:24],
    )

    if not needle:
        raise HTTPException(status_code=400, detail="caller has no dialable digits for matching")

    ex = (exclude_call_id or "").strip()
    since_30d = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat().replace("+00:00", "Z")

    contact_name: Optional[str] = None
    try:
        from src.common.caller_contact_db import get_caller_contact

        crow = get_caller_contact(own, needle)
        if crow and (crow.get("display_name") or "").strip():
            contact_name = str(crow["display_name"]).strip()
    except Exception as exc:
        logger.warning("caller_context_contact_lookup_failed err=%s", exc)

    inbound_30d = 0
    inbound_all = 0
    try:
        from src.common.call_record_db import count_inbound_calls_for_caller

        inbound_30d = count_inbound_calls_for_caller(
            owner=own,
            caller_like=needle,
            since_iso=since_30d,
            exclude_call_id=ex,
        )
        inbound_all = count_inbound_calls_for_caller(
            owner=own,
            caller_like=needle,
            since_iso=None,
            exclude_call_id=ex,
        )
    except Exception as exc:
        logger.warning("caller_context_count_failed err=%s", exc)

    try:
        from src.common.call_record_db import get_prior_inbound_call_for_caller

        prior = get_prior_inbound_call_for_caller(
            owner=own,
            caller_like=needle,
            exclude_call_id=ex,
        )
    except Exception as exc:
        logger.warning("caller_context_db_failed err=%s", exc)
        prior = None

    base_stats = {
        "contact_display_name": contact_name,
        "inbound_count_30d": inbound_30d,
        "inbound_count_all": inbound_all,
    }

    if not prior:
        logger.info(
            "caller_context_no_prior owner=%s needle=%s needle_src=%s exclude=%s",
            own[:48],
            needle,
            needle_src,
            ex[:24],
        )
        return {
            "has_prior_call": False,
            "prior_call_id": None,
            "prior_call_at": None,
            "prior_summary": None,
            "relationship_label": "first",
            **base_stats,
        }

    at = prior.get("end_time") or prior.get("start_time")
    summary = prior.get("call_summary")
    if isinstance(summary, str):
        summary = summary.strip() or None
    else:
        summary = None

    out = {
        "has_prior_call": True,
        "prior_call_id": prior.get("call_id"),
        "prior_call_at": at,
        "prior_summary": summary,
        "relationship_label": "returning",
        **base_stats,
    }
    logger.info(
        "caller_context_prior_hit owner=%s needle=%s needle_src=%s prior_call_id=%s",
        own[:48],
        needle,
        needle_src,
        prior.get("call_id"),
    )
    return out


@router.get("/{call_id}/bookings")
def get_call_bookings(call_id: str) -> Dict[str, Any]:
    """통화 ID로 연결된 예약 목록을 조회한다 (bookings.call_id 기준).

    예약 DB가 없거나 연결된 예약이 없으면 빈 목록을 반환한다.
    """
    try:
        from src.booking.database import get_db, row_to_dict
    except ImportError:
        return {"call_id": call_id, "items": []}

    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM bookings WHERE call_id = ? ORDER BY created_at ASC",
                (call_id,),
            ).fetchall()
        items = [row_to_dict(r) for r in rows if r is not None]
        return {"call_id": call_id, "items": items}
    except Exception as exc:
        logger.warning("get_call_bookings_failed call_id=%s err=%s", call_id, exc)
        return {"call_id": call_id, "items": []}


@router.post("/{call_id}/unhandled/{item_id}/draft")
async def draft_unhandled_reply(call_id: str, item_id: str) -> Dict[str, Any]:
    """미처리 항목에 대한 LLM 초안 답변 생성.

    call_insights.json에서 해당 item을 찾아 LLM으로 답변 초안을 생성한다.
    """
    call_dir = _find_call_dir(call_id)
    if call_dir is None:
        raise HTTPException(status_code=404, detail="call not found")

    insights = load_call_insights_for_directory(call_dir)
    if not insights:
        raise HTTPException(status_code=404, detail="insights not found")

    items_list: List[Dict[str, Any]] = insights.get("ai_unhandled_items") or []
    target = next((it for it in items_list if str(it.get("id") or "") == item_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="unhandled item not found")

    question = target.get("user_question", "")
    if not question:
        return {"draft": ""}

    try:
        from src.ai_voicebot.factory import get_llm_client
        from src.common.gemini_api_key import resolve_gemini_api_key

        # [2026-07-27] 이전에는 "gemini-2.0-flash-lite"를 하드코딩했으나 이 계정에서 이미
        # 404로 폐지되어 있어 항상 실패하고 있었다(Story 6.3에서 발견). 다른 LLM 호출 경로
        # (LLMClient)와 동일한 모델을 쓰도록 전역 싱글턴을 재사용한다.
        llm_client = get_llm_client()
        client = getattr(llm_client, "_client", None) if llm_client is not None else None
        model_name = (
            getattr(llm_client, "model_name", None) if llm_client is not None else None
        ) or "gemini-2.5-flash"

        if client is None:
            api_key = resolve_gemini_api_key()
            if not api_key:
                return {"draft": ""}
            from google import genai  # type: ignore

            client = genai.Client(api_key=api_key)

        call_summary = insights.get("call_summary", "")
        prompt = (
            f"다음은 AI 전화 상담 중 처리하지 못한 고객 질문입니다.\n"
            f"통화 요약: {call_summary}\n"
            f"고객 질문: {question}\n\n"
            f"운영자가 고객에게 보낼 짧고 친절한 답변을 한국어로 작성해 주세요. "
            f"200자 이내로 작성하고, 실제 정보 없이는 추측하지 마세요."
        )
        resp = await client.aio.models.generate_content(
            model=model_name, contents=prompt
        )
        draft_text = resp.text.strip() if resp.text else ""
        return {"draft": draft_text}
    except Exception as exc:
        logger.warning("unhandled_draft_failed call_id=%s item_id=%s err=%s", call_id, item_id, exc)
        return {"draft": ""}


@router.put("/{call_id}/unhandled/{item_id}/reply")
def save_unhandled_reply(
    call_id: str,
    item_id: str,
    body: UnhandledReplyRequest = Body(...),
) -> Dict[str, Any]:
    """미처리 항목 답변 저장. call_insights.json에 reply_text·reply_sent_at을 기록한다."""
    import datetime

    call_dir = _find_call_dir(call_id)
    if call_dir is None:
        raise HTTPException(status_code=404, detail="call not found")

    insights_path = call_dir / "call_insights.json"
    if not insights_path.is_file():
        raise HTTPException(status_code=404, detail="insights not found")

    try:
        with open(insights_path, "r", encoding="utf-8") as f:
            insights: Dict[str, Any] = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"insights read failed: {exc}") from exc

    items_list: List[Dict[str, Any]] = insights.get("ai_unhandled_items") or []
    target = next((it for it in items_list if str(it.get("id") or "") == item_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="unhandled item not found")

    sent_at = datetime.datetime.utcnow().isoformat() + "Z" if body.send else None
    target["reply_text"] = body.reply_text
    if sent_at:
        target["reply_sent_at"] = sent_at

    try:
        with open(insights_path, "w", encoding="utf-8") as f:
            json.dump(insights, f, ensure_ascii=False, indent=2)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"insights write failed: {exc}") from exc

    logger.info(
        "unhandled_reply_saved call_id=%s item_id=%s send=%s",
        call_id, item_id, body.send,
    )
    return {"ok": True, "reply_sent_at": sent_at}


@router.patch("/{call_id}/resolve")
def toggle_call_resolve(
    call_id: str,
    body: ResolveRequest = Body(...),
) -> Dict[str, Any]:
    """통화 단위 미해결/해결 상태를 수동으로 토글한다.

    call_insights.json이 있으면 해당 파일의 is_unresolved를 갱신한다.
    DB call_records의 is_unresolved도 동기화한다.
    """
    call_dir = _find_call_dir(call_id)

    # call_insights.json 갱신 (파일이 있을 때만)
    if call_dir is not None:
        insights_path = call_dir / "call_insights.json"
        if insights_path.is_file():
            try:
                with open(insights_path, "r", encoding="utf-8") as f:
                    insights: Dict[str, Any] = json.load(f)
                insights["is_unresolved"] = body.is_unresolved
                with open(insights_path, "w", encoding="utf-8") as f:
                    json.dump(insights, f, ensure_ascii=False, indent=2)
                logger.info(
                    "call_resolve_toggled call_id=%s is_unresolved=%s via_file",
                    call_id, body.is_unresolved,
                )
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("call_resolve_file_update_failed call_id=%s err=%s", call_id, exc)

    # DB 동기화
    try:
        from src.common.call_record_db import upsert_call_record
        upsert_call_record(call_id=call_id, is_unresolved=body.is_unresolved)
        logger.info(
            "call_resolve_toggled call_id=%s is_unresolved=%s via_db",
            call_id, body.is_unresolved,
        )
    except Exception as exc:
        logger.warning("call_resolve_db_update_failed call_id=%s err=%s", call_id, exc)

    return {"ok": True, "call_id": call_id, "is_unresolved": body.is_unresolved}


@router.get("/{call_id}/debug-trace")
def get_call_debug_trace(
    call_id: str,
    limit: int = Query(800, ge=1, le=5000),
) -> Dict[str, Any]:
    """통화별 call_data_record (대시보드 `call_debug_trace`와 동일 필드) 조회.

    recordings 폴더 유무에 관계없이 CDR 로그에서 call_id를 검색한다.
    recordings 폴더가 없거나 metadata.json이 없어도 CDR이 있으면 데이터를 반환한다.
    CDR과 recordings 모두 없는 경우에만 404를 반환한다.
    """
    items, truncated = _scan_call_data_record_for_call(call_id, limit)
    if not items and _find_call_dir(call_id) is None:
        raise HTTPException(status_code=404, detail="call not found")
    return {"call_id": call_id, "items": items, "truncated": truncated}


@router.get("/{call_id}/media/{kind}")
def get_call_media(call_id: str, kind: str) -> FileResponse:
    if kind not in _ALLOWED_MEDIA:
        raise HTTPException(status_code=404, detail="unknown media kind")
    call_dir = _find_call_dir(call_id)
    if call_dir is None:
        raise HTTPException(status_code=404, detail="call not found")
    fname = _ALLOWED_MEDIA[kind]
    base = call_dir.resolve()
    path = (call_dir / fname).resolve()
    if path.parent != base:
        raise HTTPException(status_code=404, detail="invalid path")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(path, media_type="audio/wav", filename=fname)


@router.get("/{call_id}/transcript")
def get_call_transcript(call_id: str) -> PlainTextResponse:
    call_dir = _find_call_dir(call_id)
    if call_dir is None:
        raise HTTPException(status_code=404, detail="call not found")
    tp = call_dir / "transcript.txt"
    if not tp.is_file():
        raise HTTPException(status_code=404, detail="transcript not found")
    try:
        text = tp.read_text(encoding="utf-8", errors="replace")
    except OSError:
        raise HTTPException(status_code=404, detail="transcript read failed")
    return PlainTextResponse(content=text, media_type="text/plain; charset=utf-8")


@router.get("")
def list_call_history(
    owner: Optional[str] = Query(None, description="테넌트 필터 — caller_id(발신) 또는 callee_id(착신) 어느 쪽에든 매칭"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    since: Optional[str] = Query(None, description="ISO 8601 기준 시각 — 이 시각 이후 통화만 반환 (최근 30일 등)"),
    direction: Optional[str] = Query(
        None,
        description="통화 방향 필터: inbound | outbound (미지정 시 전체)",
    ),
) -> Dict[str, Any]:
    """
    완료 통화 목록. DB(call_records) 우선 조회, 없으면 파일 스캔 fallback.

    각 항목에 `ai_unhandled_items`, `ai_unhandled_count`, `has_booking` 포함
    (`call_insights.json` 또는 DB 기준).
    owner 필터는 caller_id(발신)·callee_id(착신) 양쪽을 검사하므로 수신·발신 통화 모두 반환됨.
    """
    root = _recordings_root()
    owner_f = (owner or "").strip()
    since_f = (since or "").strip()
    direction_f = (direction or "").strip().lower()
    if direction_f and direction_f not in ("inbound", "outbound"):
        direction_f = ""

    # ── DB 우선 조회 시도 ────────────────────────────────────────────────────
    _db_result: Optional[Dict[str, Any]] = None
    try:
        from src.common.call_record_db import get_call_records_page
        _db_result = get_call_records_page(
            owner=owner_f,
            since=since_f or None,
            direction=direction_f or None,
            limit=limit,
            offset=offset,
        )
    except Exception as _dbe:
        logger.debug("call_records_db_query_skip err=%s", _dbe)

    if _db_result is not None and _db_result.get("total", 0) > 0:
        # DB에 데이터가 있으면 DB 기반으로 응답 구성
        db_items: List[Dict[str, Any]] = _db_result.get("items") or []
        db_total: int = int(_db_result.get("total") or 0)

        # 예약 존재 여부 배치 조회
        _booking_call_ids: set[str] = set()
        try:
            from src.booking.database import get_db as _get_bdb
            _page_cids = [str(r.get("call_id") or "") for r in db_items if r.get("call_id")]
            if _page_cids:
                placeholders = ",".join("?" * len(_page_cids))
                with _get_bdb() as _bconn:
                    _brows = _bconn.execute(
                        f"SELECT DISTINCT call_id FROM bookings WHERE call_id IN ({placeholders})",
                        _page_cids,
                    ).fetchall()
                _booking_call_ids = {str(r[0]) for r in _brows}
        except Exception as _be:
            logger.debug("booking_batch_check_failed err=%s", _be)

        out: List[Dict[str, Any]] = []
        for db_row in db_items:
            cid = str(db_row.get("call_id") or "")
            call_dir = _find_call_dir(cid) or Path(db_row.get("recordings_dir") or "")
            insights = load_call_insights_for_directory(call_dir) if call_dir and call_dir.is_dir() else None

            _ex = db_row.get("extra_data")
            _merged: Dict[str, Any] = dict(db_row)
            if isinstance(_ex, dict):
                _merged.update(_ex)

            item: Dict[str, Any] = {
                "call_id": cid,
                "directory": db_row.get("recordings_dir") or str(call_dir) if call_dir else None,
                "caller_id": _resolve_caller_id_for_list(_merged),
                "callee_id": db_row.get("callee_id") or "",
                "direction": db_row.get("direction") or (
                    "outbound" if cid.startswith("outbound-") else "inbound"
                ),
                "start_time": db_row.get("start_time"),
                "end_time": db_row.get("end_time"),
                "duration": db_row.get("duration"),
                "type": None,
                "has_transcript": bool(db_row.get("has_transcript")),
                "transcript_source": None,
                "files": None,
                "call_summary": db_row.get("call_summary") or None,
                "is_ai_handled_call": bool(db_row.get("is_ai_handled")),
                "ai_unhandled_items": [],
                "ai_unhandled_count": int(db_row.get("ai_unhandled_count") or 0),
                "ai_unhandled_resolved_by_hitl_count": 0,
                "ai_unhandled_total_recorded": 0,
                "is_unresolved": _coerce_bool_unresolved(db_row.get("is_unresolved")),
                "has_booking": cid in _booking_call_ids,
                "has_recording_mixed": bool(db_row.get("has_recording")),
                "has_recording_caller": False,
                "has_recording_callee": False,
            }
            # call_insights.json이 있으면 상세 정보 보완 (is_unresolved는 JSON 우선)
            if insights:
                _cs = insights.get("call_summary")
                if isinstance(_cs, str) and _cs.strip():
                    item["call_summary"] = _cs
                item["ai_unhandled_items"] = insights.get("ai_unhandled_items") or []
                item["ai_unhandled_count"] = int(insights.get("ai_unhandled_count") or item["ai_unhandled_count"])
                item["ai_unhandled_resolved_by_hitl_count"] = int(
                    insights.get("ai_unhandled_resolved_by_hitl_count") or 0
                )
                item["ai_unhandled_total_recorded"] = int(
                    insights.get("ai_unhandled_total_recorded") or 0
                )
                item["is_ai_handled_call"] = bool(insights.get("is_ai_handled_call", item["is_ai_handled_call"]))
                if "is_unresolved" in insights:
                    item["is_unresolved"] = _coerce_bool_unresolved(insights["is_unresolved"])
            # 녹음 파일 실제 존재 여부로 보완
            if call_dir and call_dir.is_dir():
                flags = _recording_flags(call_dir, {})
                item.update(flags)

            item["is_unresolved"] = _coerce_bool_unresolved(item.get("is_unresolved"))
            out.append(item)

        return {
            "items": out,
            "total": db_total,
            "limit": limit,
            "offset": offset,
            "recordings_dir": str(root),
            "source": "db",
        }

    # ── 파일 스캔 fallback (기존 로직) ──────────────────────────────────────
    logger.debug("call_history_fallback_file_scan total_db=%s", _db_result.get("total") if _db_result else "none")
    metas = _load_metadata_rows(root)
    metas.sort(key=_sort_key, reverse=True)

    def _row_matches(m: Dict[str, Any]) -> bool:
        if owner_f and not _owner_matches_row(
            owner_f,
            str(m.get("callee_id") or ""),
            str(m.get("caller_id") or ""),
        ):
            return False
        if since_f:
            row_time = str(m.get("end_time") or m.get("start_time") or "")
            if row_time and row_time < since_f:
                return False
        if direction_f:
            row_dir = str(m.get("direction") or "").strip().lower()
            if not row_dir:
                cid = str(m.get("call_id") or "")
                row_dir = "outbound" if cid.startswith("outbound-") else "inbound"
            if row_dir != direction_f:
                return False
        return True

    filtered = [m for m in metas if _row_matches(m)]
    total_matching = len(filtered)
    page = filtered[offset : offset + limit]

    # 예약 존재 여부를 배치로 조회 (DB 연결 가능할 때만)
    _booking_call_ids_fs: set[str] = set()
    try:
        from src.booking.database import get_db as _get_bdb
        _page_cids = [str(m.get("call_id") or "") for m in page if m.get("call_id")]
        if _page_cids:
            placeholders = ",".join("?" * len(_page_cids))
            with _get_bdb() as _bconn:
                _brows = _bconn.execute(
                    f"SELECT DISTINCT call_id FROM bookings WHERE call_id IN ({placeholders})",
                    _page_cids,
                ).fetchall()
            _booking_call_ids_fs = {str(r[0]) for r in _brows}
    except Exception as _be:
        logger.debug("booking_batch_check_failed err=%s", _be)

    out_fs: List[Dict[str, Any]] = []
    for m in page:
        call_dir = Path(m.get("_call_dir") or "")
        insights = load_call_insights_for_directory(call_dir) if call_dir.is_dir() else None

        item_fs: Dict[str, Any] = {
            "call_id": m.get("call_id"),
            "directory": m.get("directory"),
            "caller_id": _resolve_caller_id_for_list(m),
            "callee_id": m.get("callee_id"),
            "direction": (
                m.get("direction")
                or ("outbound" if str(m.get("call_id") or "").startswith("outbound-") else "inbound")
            ),
            "start_time": m.get("start_time"),
            "end_time": m.get("end_time"),
            "duration": m.get("duration"),
            "type": m.get("type"),
            "has_transcript": m.get("has_transcript"),
            "transcript_source": m.get("transcript_source"),
            "files": m.get("files"),
            "call_summary": None,
            "is_ai_handled_call": False,
            "ai_unhandled_items": [],
            "ai_unhandled_count": 0,
            "ai_unhandled_resolved_by_hitl_count": 0,
            "ai_unhandled_total_recorded": 0,
            "is_unresolved": False,
            "has_booking": str(m.get("call_id") or "") in _booking_call_ids_fs,
        }
        if call_dir.is_dir():
            item_fs.update(_recording_flags(call_dir, m))
            _, ai_flag = _resolve_ai_flag(call_dir, m, insights)
            item_fs["is_ai_handled_call"] = ai_flag
        else:
            item_fs["has_recording_mixed"] = False
            item_fs["has_recording_caller"] = False
            item_fs["has_recording_callee"] = False

        if insights:
            _cs = insights.get("call_summary")
            item_fs["call_summary"] = _cs if isinstance(_cs, str) and _cs.strip() else None
            item_fs["ai_unhandled_items"] = insights.get("ai_unhandled_items") or []
            item_fs["ai_unhandled_count"] = int(insights.get("ai_unhandled_count") or 0)
            item_fs["ai_unhandled_resolved_by_hitl_count"] = int(
                insights.get("ai_unhandled_resolved_by_hitl_count") or 0
            )
            item_fs["ai_unhandled_total_recorded"] = int(
                insights.get("ai_unhandled_total_recorded") or 0
            )
            if "is_unresolved" in insights:
                item_fs["is_unresolved"] = _coerce_bool_unresolved(insights["is_unresolved"])

        item_fs["is_unresolved"] = _coerce_bool_unresolved(item_fs.get("is_unresolved"))
        out_fs.append(item_fs)

    return {
        "items": out_fs,
        "total": total_matching,
        "limit": limit,
        "offset": offset,
        "recordings_dir": str(root),
        "source": "file_scan",
    }
