"""
Call Control REST API

착신 라우팅 규칙, 시간 스케줄, 안내멘트(레거시 API), 통화 연결음 스케줄 할당 CRUD + 현재 적용 규칙 조회.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Body, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response

import structlog

from src.call_control import db as _db
from src.call_control import routing_engine as _engine
from src.call_control.models import (
    AnnouncementCreate,
    AnnouncementProfile,
    AnnouncementUpdate,
    CallerFilter,
    CallerFilterCreate,
    ForwardTarget,
    ForwardTargetCreate,
    ForwardTargetUpdate,
    OverflowPolicy,
    PriorityUpdate,
    ResolvedRoutingRule,
    RingGroup,
    RingGroupCreate,
    RingGroupUpdate,
    RingbackAssignmentsReorderBody,
    RingbackScheduleAssignment,
    RingbackScheduleAssignmentCreate,
    RingbackScheduleAssignmentOut,
    RingbackScheduleAssignmentUpdate,
    RoutingRule,
    RoutingRuleCreate,
    RoutingRuleUpdate,
    Schedule,
    ScheduleCreate,
    ScheduleUpdate,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/call-control", tags=["call-control"])


def _http_request_log_fields(request: Request | None, payload: Dict[str, Any] | None, max_len: int = 4000) -> Dict[str, Any]:
    """Suno 전제 실패 등에서 요청 맥락을 structlog 한 줄에 남긴다."""
    out: Dict[str, Any] = {}
    if request is not None:
        out["http_request_method"] = request.method
        out["http_request_url"] = str(request.url)
        cl = request.client
        out["http_request_client_host"] = cl.host if cl else None
        peek = getattr(request.state, "body_preview", None) or ""
        if peek:
            out["http_request_raw_body_preview"] = peek[:max_len]
    if payload is not None:
        try:
            out["request_payload_preview"] = json.dumps(payload, ensure_ascii=False, default=str)[:max_len]
        except Exception:
            out["request_payload_preview"] = str(payload)[:max_len]
    return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _new_id() -> str:
    return str(uuid.uuid4())


def _enum_to_str(v: Any) -> str:
    return v.value if hasattr(v, "value") else str(v)


def _validate_forward_target_payload(
    kind: str,
    single_extension: Optional[str],
    members: List[Any],
) -> None:
    k = (kind or "single").lower()
    se = (single_extension or "").strip()
    mem = [str(m).strip() for m in (members or []) if str(m).strip()]
    if k == "single":
        if not se:
            raise HTTPException(status_code=400, detail="단일 대상은 내선 번호가 필요합니다.")
        if mem:
            raise HTTPException(status_code=400, detail="단일 대상에서는 멤버 목록을 비워 주세요.")
    elif k == "group":
        if len(mem) < 1:
            raise HTTPException(status_code=400, detail="그룹은 최소 1개의 내선이 필요합니다.")
    else:
        raise HTTPException(status_code=400, detail="kind 는 single 또는 group 이어야 합니다.")


# ---------------------------------------------------------------------------
# Routing Rules
# ---------------------------------------------------------------------------


@router.get("/rules", response_model=List[RoutingRule])
def list_rules(owner: str = Query(..., description="내선 번호")) -> List[Dict[str, Any]]:
    return _db.list_rules(owner)


@router.post("/rules", response_model=RoutingRule, status_code=201)
def create_rule(body: RoutingRuleCreate) -> Dict[str, Any]:
    data = body.model_dump()
    data["id"] = _new_id()
    rule = _db.create_rule(data)
    logger.info("call_control_rule_created", owner=body.owner, rule_id=data["id"], action=body.action)
    return rule


@router.get("/rules/{rule_id}", response_model=RoutingRule)
def get_rule(rule_id: str) -> Dict[str, Any]:
    rule = _db.get_rule(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="규칙을 찾을 수 없습니다.")
    return rule


@router.put("/rules/{rule_id}", response_model=RoutingRule)
def update_rule(rule_id: str, body: RoutingRuleUpdate) -> Dict[str, Any]:
    existing = _db.get_rule(rule_id)
    if not existing:
        raise HTTPException(status_code=404, detail="규칙을 찾을 수 없습니다.")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    rule = _db.update_rule(rule_id, updates)
    logger.info("call_control_rule_updated", rule_id=rule_id)
    return rule


@router.delete("/rules/{rule_id}", status_code=204, response_class=Response)
def delete_rule(rule_id: str, response: Response):
    if not _db.delete_rule(rule_id):
        raise HTTPException(status_code=404, detail="규칙을 찾을 수 없습니다.")
    logger.info("call_control_rule_deleted", rule_id=rule_id)
    response.status_code = 204


@router.patch("/rules/{rule_id}/priority", response_model=RoutingRule)
def update_priority(rule_id: str, body: PriorityUpdate) -> Dict[str, Any]:
    rule = _db.update_rule_priority(rule_id, body.priority)
    if not rule:
        raise HTTPException(status_code=404, detail="규칙을 찾을 수 없습니다.")
    return rule


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------


@router.get("/schedules", response_model=List[Schedule])
def list_schedules(owner: str = Query(..., description="내선 번호")) -> List[Dict[str, Any]]:
    return _db.list_schedules(owner)


@router.post("/schedules", response_model=Schedule, status_code=201)
def create_schedule(body: ScheduleCreate) -> Dict[str, Any]:
    data = body.model_dump()
    # TimeRange 객체를 dict로 변환
    data["time_ranges"] = [
        tr if isinstance(tr, dict) else tr.model_dump()
        for tr in data.get("time_ranges", [])
    ]
    data["days"] = [d.value if hasattr(d, "value") else d for d in data.get("days", [])]
    data["id"] = _new_id()
    schedule = _db.create_schedule(data)
    logger.info("call_control_schedule_created", owner=body.owner, schedule_id=data["id"])
    return schedule


@router.get("/schedules/{schedule_id}", response_model=Schedule)
def get_schedule(schedule_id: str) -> Dict[str, Any]:
    schedule = _db.get_schedule(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="스케줄을 찾을 수 없습니다.")
    return schedule


@router.put("/schedules/{schedule_id}", response_model=Schedule)
def update_schedule(schedule_id: str, body: ScheduleUpdate) -> Dict[str, Any]:
    existing = _db.get_schedule(schedule_id)
    if not existing:
        raise HTTPException(status_code=404, detail="스케줄을 찾을 수 없습니다.")
    raw = body.model_dump(exclude_none=True)
    if "time_ranges" in raw:
        raw["time_ranges"] = [
            tr if isinstance(tr, dict) else tr.model_dump()
            for tr in raw["time_ranges"]
        ]
    if "days" in raw:
        raw["days"] = [d.value if hasattr(d, "value") else d for d in raw["days"]]
    schedule = _db.update_schedule(schedule_id, raw)
    return schedule


@router.delete("/schedules/{schedule_id}", status_code=204, response_class=Response)
def delete_schedule(schedule_id: str, response: Response):
    if not _db.delete_schedule(schedule_id):
        raise HTTPException(status_code=404, detail="스케줄을 찾을 수 없습니다.")
    response.status_code = 204


# ---------------------------------------------------------------------------
# Announcements
# ---------------------------------------------------------------------------


@router.get("/announcements/ringback-greeting")
def get_ringback_greeting(owner: str = Query(..., description="내선 번호")) -> Dict[str, Any]:
    """하위 호환용. 링백 인사는 ``ringback_settings`` 및 «통화 연결음» 스케줄에서만 설정한다."""
    return {"owner": owner, "text": None, "name": None, "id": None, "deprecated": True}


@router.get("/announcements", response_model=List[AnnouncementProfile])
def list_announcements(owner: str = Query(..., description="내선 번호")) -> List[Dict[str, Any]]:
    return _db.list_announcements(owner)


@router.post("/announcements", response_model=AnnouncementProfile, status_code=201)
def create_announcement(body: AnnouncementCreate) -> Dict[str, Any]:
    data = body.model_dump()
    data["id"] = _new_id()
    data["use_as_ringback_greeting"] = False
    announcement = _db.create_announcement(data)
    logger.info("call_control_announcement_created", owner=body.owner, id=data["id"])
    return announcement


@router.get("/announcements/{announcement_id}", response_model=AnnouncementProfile)
def get_announcement(announcement_id: str) -> Dict[str, Any]:
    ann = _db.get_announcement(announcement_id)
    if not ann:
        raise HTTPException(status_code=404, detail="안내멘트를 찾을 수 없습니다.")
    return ann


@router.put("/announcements/{announcement_id}", response_model=AnnouncementProfile)
def update_announcement(announcement_id: str, body: AnnouncementUpdate) -> Dict[str, Any]:
    existing = _db.get_announcement(announcement_id)
    if not existing:
        raise HTTPException(status_code=404, detail="안내멘트를 찾을 수 없습니다.")
    updates = body.model_dump(exclude_none=True)
    updates.pop("use_as_ringback_greeting", None)
    ann = _db.update_announcement(announcement_id, updates)
    return ann


@router.delete("/announcements/{announcement_id}", status_code=204, response_class=Response)
def delete_announcement(announcement_id: str, response: Response):
    if not _db.delete_announcement(announcement_id):
        raise HTTPException(status_code=404, detail="안내멘트를 찾을 수 없습니다.")
    response.status_code = 204


# ---------------------------------------------------------------------------
# Ringback schedule assignments (착신 제어 > 통화 연결음 탭)
# ---------------------------------------------------------------------------


def _enrich_ringback_assignments(owner: str, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    scheds = {s["id"]: s for s in _db.list_schedules(owner)}
    out: List[Dict[str, Any]] = []
    for r in rows:
        sid = r.get("schedule_id")
        sn: Optional[str] = None
        if sid:
            sn = (scheds.get(str(sid)) or {}).get("name")
        out.append(
            {
                **r,
                "schedule_name": sn or ("항상" if not sid else "(삭제된 스케줄)"),
            }
        )
    return out


_RINGBACK_SUNO_TRIGGER_KEYS = frozenset(
    {
        "generation_mode",
        "suno_lyrics",
        "suno_style",
        "suno_title",
        "suno_vocal_gender",
        "suno_duration_target",
        "tts_text",
    }
)


def _will_run_suno_after_save(merged: Dict[str, Any]) -> bool:
    if (merged.get("generation_mode") or "suno").strip().lower() != "suno":
        return False
    if not (str(merged.get("suno_lyrics") or "").strip()):
        return False
    if not (str(merged.get("suno_style") or "").strip()):
        return False
    return True


def _suno_inputs_changed(existing: Dict[str, Any], merged: Dict[str, Any]) -> bool:
    for k in (
        "generation_mode",
        "suno_lyrics",
        "suno_style",
        "suno_title",
        "suno_vocal_gender",
        "suno_duration_target",
    ):
        a = existing.get(k)
        b = merged.get(k)
        if str(a or "").strip() != str(b or "").strip():
            return True
    return False


def _should_rerender_tts_audio(
    existing: Optional[Dict[str, Any]], merged: Dict[str, Any]
) -> bool:
    """TTS 모드이고 문구·모드 변경 시 WAV 사전 렌더(문구 비우면 DB에서 경로 제거)."""
    if (merged.get("generation_mode") or "").lower() != "tts":
        return False
    t = (merged.get("tts_text") or "").strip()
    if not existing:
        return bool(t)
    if str(existing.get("generation_mode") or "").lower() != "tts":
        return bool(t)
    prev = str(existing.get("tts_text") or "").strip()
    if not t:
        return bool(prev)  # 문구 삭제 → render가 tts_audio_path 비움
    return prev != t


def _should_kickoff_suno_update(existing: Dict[str, Any], merged: Dict[str, Any]) -> bool:
    """모달 전체 저장 등으로 raw_keys가 항상 넓어도, 의미 있는 경우에만 Suno 재생성."""
    if not _will_run_suno_after_save(merged):
        return False
    st = str(existing.get("suno_generation_status") or "idle").lower()
    if st == "pending":
        return False
    if st == "failed":
        return True
    if _suno_inputs_changed(existing, merged):
        return True
    path = str(existing.get("suno_audio_path") or "").strip()
    tid = str(existing.get("suno_task_id") or "").strip()
    if not path and not tid:
        return True
    return False


@router.get("/ringback-assignments", response_model=List[RingbackScheduleAssignmentOut])
def list_ringback_assignments(owner: str = Query(..., description="내선 번호")) -> List[Dict[str, Any]]:
    rows = _db.list_ringback_schedule_assignments(owner)
    return _enrich_ringback_assignments(owner, rows)


@router.post("/ringback-assignments", response_model=RingbackScheduleAssignment, status_code=201)
def create_ringback_assignment(
    body: RingbackScheduleAssignmentCreate,
    background_tasks: BackgroundTasks,
    request: Request,
) -> Dict[str, Any]:
    from src.services.ringback_service import (
        ensure_suno_generation_prerequisites,
        kickoff_suno_after_assignment_saved,
        render_ringback_assignment_tts_wav,
    )

    data = body.model_dump()
    if not data.get("schedule_id") or str(data["schedule_id"]).strip() == "":
        data["schedule_id"] = None
    data["id"] = _new_id()
    if _will_run_suno_after_save(data):
        try:
            ensure_suno_generation_prerequisites()
        except ValueError as e:
            logger.warning(
                "call_control_ringback_suno_prerequisite_failed",
                operation="create_ringback_assignment",
                owner=body.owner,
                generation_mode=data.get("generation_mode"),
                error=str(e),
                **_http_request_log_fields(request, data),
            )
            raise HTTPException(status_code=400, detail=str(e)) from e
        data["suno_generation_status"] = "pending"
        data["suno_audio_path"] = None
        data["suno_audio_url"] = None
        data["suno_task_id"] = None
    else:
        data["suno_generation_status"] = "idle"
    row = _db.create_ringback_schedule_assignment(data)
    logger.info(
        "ringback_schedule_assignment_created",
        owner=body.owner,
        id=data["id"],
        schedule_id=data.get("schedule_id"),
        generation_mode=data.get("generation_mode"),
        suno_generation_status=row.get("suno_generation_status"),
    )
    if row.get("suno_generation_status") == "pending":
        background_tasks.add_task(kickoff_suno_after_assignment_saved, str(data["id"]))
    if _should_rerender_tts_audio(None, data):
        background_tasks.add_task(render_ringback_assignment_tts_wav, str(data["id"]))
    return row


@router.get("/ringback-assignments/{assignment_id}", response_model=RingbackScheduleAssignmentOut)
def get_ringback_assignment(assignment_id: str, owner: str = Query(...)) -> Dict[str, Any]:
    row = _db.get_ringback_schedule_assignment(assignment_id)
    if not row or row.get("owner") != owner:
        raise HTTPException(status_code=404, detail="항목을 찾을 수 없습니다.")
    enriched = _enrich_ringback_assignments(owner, [row])
    return enriched[0]


def _resolve_safe_data_dir_file(path_raw: Any) -> Optional[Path]:
    """로컬 캐시 등 ``data/`` 이하 파일만 허용 (경로 이탈 방지)."""
    if path_raw is None:
        return None
    s = str(path_raw).strip()
    if not s:
        return None
    p = Path(s)
    if not p.is_absolute():
        p = Path(os.getcwd()) / p
    try:
        rp = p.resolve()
    except (OSError, RuntimeError):
        return None
    if not rp.is_file():
        return None
    try:
        data_root = (Path(os.getcwd()) / "data").resolve()
        rp.relative_to(data_root)
    except ValueError:
        return None
    return rp


@router.get("/ringback-assignments/{assignment_id}/media")
def get_ringback_assignment_media(
    assignment_id: str,
    owner: str = Query(..., description="내선 번호"),
) -> FileResponse:
    """통화 연결음 할당의 로컬 MP3/WAV 미리듣기 (Bearer와 동일 권한 모델 — 프록시 경유 fetch)."""
    row = _db.get_ringback_schedule_assignment(assignment_id)
    if not row or row.get("owner") != owner:
        raise HTTPException(status_code=404, detail="항목을 찾을 수 없습니다.")
    mode = str(row.get("generation_mode") or "suno").strip().lower()
    if mode == "tts":
        raw_path = row.get("tts_audio_path")
        media_type = "audio/wav"
        suffix = ".wav"
    else:
        raw_path = row.get("suno_audio_path")
        media_type = "audio/mpeg"
        suffix = ".mp3"
    resolved = _resolve_safe_data_dir_file(raw_path)
    if resolved is None:
        raise HTTPException(
            status_code=404,
            detail="미리듣기용 로컬 파일이 없습니다. 생성이 완료된 뒤 다시 시도하세요.",
        )
    return FileResponse(
        path=str(resolved),
        media_type=media_type,
        filename=f"ringback-preview-{assignment_id[:8]}{suffix}",
    )


@router.put("/ringback-assignments/{assignment_id}", response_model=RingbackScheduleAssignment)
def update_ringback_assignment(
    assignment_id: str,
    body: RingbackScheduleAssignmentUpdate,
    background_tasks: BackgroundTasks,
    request: Request,
    owner: str = Query(...),
) -> Dict[str, Any]:
    from src.services.ringback_service import (
        ensure_suno_generation_prerequisites,
        kickoff_suno_after_assignment_saved,
        render_ringback_assignment_tts_wav,
    )

    existing = _db.get_ringback_schedule_assignment(assignment_id)
    if not existing or existing.get("owner") != owner:
        raise HTTPException(status_code=404, detail="항목을 찾을 수 없습니다.")
    raw = body.model_dump(exclude_unset=True)
    if "schedule_id" in raw and (raw["schedule_id"] is None or str(raw["schedule_id"]).strip() == ""):
        raw["schedule_id"] = None
    merged = {**existing, **raw}
    raw_keys = frozenset(raw.keys())
    kick_suno = _should_kickoff_suno_update(existing, merged)

    if kick_suno:
        try:
            ensure_suno_generation_prerequisites()
        except ValueError as e:
            logger.warning(
                "call_control_ringback_suno_prerequisite_failed",
                operation="update_ringback_assignment",
                owner=owner,
                assignment_id=assignment_id,
                error=str(e),
                **_http_request_log_fields(request, {**raw, "assignment_id": assignment_id}),
            )
            raise HTTPException(status_code=400, detail=str(e)) from e
        raw["suno_generation_status"] = "pending"
        raw["suno_audio_path"] = None
        raw["suno_audio_url"] = None
        raw["suno_task_id"] = None
    elif raw_keys & _RINGBACK_SUNO_TRIGGER_KEYS and not _will_run_suno_after_save(merged):
        raw["suno_generation_status"] = "idle"

    if str(merged.get("generation_mode") or "").lower() == "suno":
        raw["tts_audio_path"] = None

    final_merge = {**existing, **raw}
    row = _db.update_ringback_schedule_assignment(assignment_id, raw)
    if kick_suno:
        background_tasks.add_task(kickoff_suno_after_assignment_saved, str(assignment_id))
    if _should_rerender_tts_audio(existing, final_merge):
        background_tasks.add_task(render_ringback_assignment_tts_wav, str(assignment_id))
    return row  # type: ignore[return-value]


@router.delete("/ringback-assignments/{assignment_id}", status_code=204, response_class=Response)
def delete_ringback_assignment(
    assignment_id: str,
    response: Response,
    owner: str = Query(...),
):
    existing = _db.get_ringback_schedule_assignment(assignment_id)
    if not existing or existing.get("owner") != owner:
        raise HTTPException(status_code=404, detail="항목을 찾을 수 없습니다.")
    if not _db.delete_ringback_schedule_assignment(assignment_id):
        raise HTTPException(status_code=404, detail="항목을 찾을 수 없습니다.")
    response.status_code = 204


@router.patch("/ringback-assignments/reorder", status_code=204)
def reorder_ringback_assignments(
    body: RingbackAssignmentsReorderBody,
    owner: str = Query(..., description="내선 번호"),
) -> Response:
    """통화 연결음 할당 목록 순서(위→아래 = 평가 순서) 저장."""
    rows = _db.list_ringback_schedule_assignments(owner)
    valid_ids = {r["id"] for r in rows}
    if set(body.ordered_ids) != valid_ids or len(body.ordered_ids) != len(valid_ids):
        raise HTTPException(
            status_code=400,
            detail="ordered_ids는 해당 owner의 모든 할당 id와 일치해야 합니다.",
        )
    _db.reorder_ringback_schedule_assignments(owner, body.ordered_ids)
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Status & Preview
# ---------------------------------------------------------------------------


@router.get("/status/{owner}", response_model=ResolvedRoutingRule)
def get_current_status(owner: str) -> Dict[str, Any]:
    """현재 시각에 적용 중인 착신 규칙 조회 (대시보드용)."""
    now = datetime.now(timezone.utc)
    result = _engine.resolve_rule(owner, now=now)

    if result:
        rule = result["rule"]
        schedule = result["schedule"]
        _ft = rule.get("forward_to") or ""
        action_label = {
            "direct": "직접 연결",
            "no_answer_ai": f"무응답 {rule.get('no_answer_timeout', 20)}초 후 AI 응대",
            "immediate_ai": "즉시 AI 응대",
            "busy_ai": "통화중 시 AI 응대",
            "forward": f"무조건 착신전환 → {_ft}",
            "forward_always": f"무조건 착신전환 → {_ft}",
            "forward_when_busy": f"통화 중 착신전환 → {_ft}",
        }.get(rule["action"], rule["action"])

        if schedule:
            desc = f"{rule['name']} ({schedule['name']}): {action_label}"
        else:
            desc = f"{rule['name']} (항상): {action_label}"

        return {
            "owner": owner,
            "rule": rule,
            "schedule": schedule,
            "is_schedule_active": True,
            "current_time": now.isoformat(),
            "description": desc,
        }

    return {
        "owner": owner,
        "rule": None,
        "schedule": None,
        "is_schedule_active": False,
        "current_time": now.isoformat(),
        "description": "적용 규칙 없음 — 기본 직접 연결",
    }


# ---------------------------------------------------------------------------
# Ring Groups
# ---------------------------------------------------------------------------


@router.get("/ring-groups", response_model=List[RingGroup])
def list_ring_groups(owner: str = Query(...)) -> List[Dict[str, Any]]:
    return _db.list_ring_groups(owner)


@router.post("/ring-groups", response_model=RingGroup, status_code=201)
def create_ring_group(body: RingGroupCreate) -> Dict[str, Any]:
    data = body.model_dump()
    data["id"] = _new_id()
    data["mode"] = data["mode"].value if hasattr(data["mode"], "value") else data["mode"]
    group = _db.create_ring_group(data)
    logger.info("ring_group_created", owner=body.owner, id=data["id"])
    return group


@router.put("/ring-groups/{group_id}", response_model=RingGroup)
def update_ring_group(group_id: str, body: RingGroupUpdate) -> Dict[str, Any]:
    existing = _db.get_ring_group(group_id)
    if not existing:
        raise HTTPException(status_code=404, detail="착신 그룹을 찾을 수 없습니다.")
    updates = body.model_dump(exclude_none=True)
    if "mode" in updates and hasattr(updates["mode"], "value"):
        updates["mode"] = updates["mode"].value
    return _db.update_ring_group(group_id, updates)


@router.delete("/ring-groups/{group_id}", status_code=204, response_class=Response)
def delete_ring_group(group_id: str, response: Response):
    if not _db.delete_ring_group(group_id):
        raise HTTPException(status_code=404, detail="착신 그룹을 찾을 수 없습니다.")
    response.status_code = 204


# ---------------------------------------------------------------------------
# Forward targets (착신 전환 탭 — 규칙 forward_to: `fwd:<id>`)
# ---------------------------------------------------------------------------


@router.get("/forward-targets", response_model=List[ForwardTarget])
def list_forward_targets(owner: str = Query(..., description="내선 번호")) -> List[Dict[str, Any]]:
    return _db.list_forward_targets(owner)


@router.post("/forward-targets", response_model=ForwardTarget, status_code=201)
def create_forward_target(body: ForwardTargetCreate) -> Dict[str, Any]:
    kind = _enum_to_str(body.kind)
    ring_mode = _enum_to_str(body.ring_mode)
    members = [str(m).strip() for m in (body.members or []) if str(m).strip()]
    single_ext = (body.single_extension or "").strip() or None
    if kind == "group":
        single_ext = None
    _validate_forward_target_payload(kind, single_ext, members)
    data = {
        "id": _new_id(),
        "owner": body.owner,
        "name": body.name.strip(),
        "kind": kind,
        "single_extension": single_ext,
        "members": members if kind == "group" else [],
        "ring_mode": ring_mode,
    }
    row = _db.create_forward_target(data)
    logger.info("forward_target_created", owner=body.owner, id=data["id"], kind=kind)
    return row


@router.put("/forward-targets/{target_id}", response_model=ForwardTarget)
def update_forward_target(
    target_id: str,
    owner: str = Query(..., description="내선 번호"),
    body: ForwardTargetUpdate = Body(...),
) -> Dict[str, Any]:
    existing = _db.get_forward_target(target_id)
    if not existing or existing.get("owner") != owner:
        raise HTTPException(status_code=404, detail="착신 전환 대상을 찾을 수 없습니다.")
    raw = body.model_dump(exclude_none=True)
    if "kind" in raw:
        raw["kind"] = _enum_to_str(raw["kind"])
    if "ring_mode" in raw:
        raw["ring_mode"] = _enum_to_str(raw["ring_mode"])
    if "members" in raw:
        raw["members"] = [str(m).strip() for m in raw["members"] if str(m).strip()]
    if "name" in raw:
        raw["name"] = str(raw["name"]).strip()
    merged = {**existing, **raw}
    kind = str(merged.get("kind") or "single").lower()
    single_ext = merged.get("single_extension")
    if isinstance(single_ext, str):
        single_ext = single_ext.strip() or None
    members = merged.get("members") or []
    if isinstance(members, list):
        members = [str(m).strip() for m in members if str(m).strip()]
    else:
        members = []
    if kind == "group":
        single_ext = None
    mem_for_validate = members if kind == "group" else []
    _validate_forward_target_payload(kind, single_ext, mem_for_validate)
    if kind == "single":
        raw["members"] = []
        if single_ext is not None or "single_extension" in raw:
            raw["single_extension"] = single_ext
    elif kind == "group":
        raw["single_extension"] = None
        raw["members"] = members
    row = _db.update_forward_target(target_id, raw)
    logger.info("forward_target_updated", target_id=target_id, owner=owner)
    return row  # type: ignore[return-value]


@router.delete("/forward-targets/{target_id}", status_code=204, response_class=Response)
def delete_forward_target(
    target_id: str,
    response: Response,
    owner: str = Query(..., description="내선 번호"),
):
    existing = _db.get_forward_target(target_id)
    if not existing or existing.get("owner") != owner:
        raise HTTPException(status_code=404, detail="착신 전환 대상을 찾을 수 없습니다.")
    if not _db.delete_forward_target(target_id):
        raise HTTPException(status_code=404, detail="착신 전환 대상을 찾을 수 없습니다.")
    logger.info("forward_target_deleted", target_id=target_id, owner=owner)
    response.status_code = 204


# ---------------------------------------------------------------------------
# Caller Filters (VIP / 차단)
# ---------------------------------------------------------------------------


@router.get("/caller-filters", response_model=List[CallerFilter])
def list_caller_filters(owner: str = Query(...)) -> List[Dict[str, Any]]:
    return _db.list_caller_filters(owner)


@router.post("/caller-filters", response_model=CallerFilter, status_code=201)
def create_caller_filter(body: CallerFilterCreate) -> Dict[str, Any]:
    data = body.model_dump()
    data["id"] = _new_id()
    data["action"] = data["action"].value if hasattr(data["action"], "value") else data["action"]
    cf = _db.create_caller_filter(data)
    logger.info("caller_filter_created", owner=body.owner, pattern=body.pattern)
    return cf


@router.put("/caller-filters/{filter_id}", response_model=CallerFilter)
def update_caller_filter(
    filter_id: str,
    updates: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    existing = _db.get_caller_filter(filter_id)
    if not existing:
        raise HTTPException(status_code=404, detail="발신자 필터를 찾을 수 없습니다.")
    return _db.update_caller_filter(filter_id, updates)


@router.delete("/caller-filters/{filter_id}", status_code=204, response_class=Response)
def delete_caller_filter(filter_id: str, response: Response):
    if not _db.delete_caller_filter(filter_id):
        raise HTTPException(status_code=404, detail="발신자 필터를 찾을 수 없습니다.")
    response.status_code = 204


# ---------------------------------------------------------------------------
# Overflow Policy
# ---------------------------------------------------------------------------


@router.get("/overflow/{owner}", response_model=Optional[OverflowPolicy])
def get_overflow_policy(owner: str) -> Optional[Dict[str, Any]]:
    return _db.get_overflow_policy(owner)


@router.put("/overflow/{owner}", response_model=OverflowPolicy)
def upsert_overflow_policy(owner: str, body: OverflowPolicy) -> Dict[str, Any]:
    data = body.model_dump()
    data["overflow_action"] = (
        data["overflow_action"].value
        if hasattr(data["overflow_action"], "value")
        else data["overflow_action"]
    )
    return _db.upsert_overflow_policy(owner, data)


@router.get("/preview/{owner}")
def preview_rules(owner: str) -> Dict[str, Any]:
    """해당 내선의 모든 규칙과 스케줄, 착신 그룹, 발신자 필터를 반환 (미리보기용)."""
    rules = _db.list_rules(owner)
    schedules = _db.list_schedules(owner)
    announcements = _db.list_announcements(owner)
    ring_groups = _db.list_ring_groups(owner)
    caller_filters = _db.list_caller_filters(owner)
    overflow = _db.get_overflow_policy(owner)
    now = datetime.now(timezone.utc)
    current = _engine.resolve_rule(owner, now=now)

    return {
        "owner": owner,
        "rules": rules,
        "schedules": schedules,
        "announcements": announcements,
        "ring_groups": ring_groups,
        "caller_filters": caller_filters,
        "overflow_policy": overflow,
        "current_rule_id": current["rule"]["id"] if current else None,
        "current_time": now.isoformat(),
    }
