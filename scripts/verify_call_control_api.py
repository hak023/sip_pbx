#!/usr/bin/env python3
"""call-control REST + routing_engine 검증 (별도 SQLite).

httpx 0.28+ 에서 ASGITransport 는 AsyncClient 전용이므로 asyncio 로 호출한다.

  cd sip-pbx
  $env:PYTHONPATH = (Resolve-Path .).Path
  .\\venv\\Scripts\\python.exe scripts\\verify_call_control_api.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_VERIFY_DB = _ROOT / "data" / "_api_verify_call_control.db"
_VERIFY_DB.parent.mkdir(parents=True, exist_ok=True)
if _VERIFY_DB.is_file():
    _VERIFY_DB.unlink()
os.environ["CALL_CONTROL_DB_PATH"] = str(_VERIFY_DB)

import httpx  # noqa: E402

from src.api.main import app  # noqa: E402
from src.call_control import db as cc_db  # noqa: E402
from src.call_control import routing_engine as re  # noqa: E402


def _fail(msg: str) -> None:
    print("FAIL:", msg)
    sys.exit(1)


def _ok(name: str) -> None:
    print("PASS:", name)


async def _run_checks(client: httpx.AsyncClient, owner: str) -> None:
    r = await client.get("/api/call-control/rules", params={"owner": owner})
    if r.status_code != 200:
        _fail(f"GET rules: {r.status_code} {r.text}")
    _ok("GET /rules empty")

    body = {
        "owner": owner,
        "name": "always direct",
        "priority": 50,
        "action": "direct",
        "no_answer_timeout": 20,
        "forward_to": None,
        "announcement_id": None,
        "schedule_id": None,
        "enabled": True,
    }
    r = await client.post("/api/call-control/rules", json=body)
    if r.status_code != 201:
        _fail(f"POST rule: {r.status_code} {r.text}")
    rule_id = r.json()["id"]
    _ok("POST /rules")

    r = await client.get(f"/api/call-control/rules/{rule_id}")
    if r.status_code != 200 or r.json().get("id") != rule_id:
        _fail("GET /rules/{id}")
    _ok("GET /rules/{id}")

    r = await client.put(f"/api/call-control/rules/{rule_id}", json={"name": "renamed", "priority": 40})
    if r.status_code != 200 or r.json().get("name") != "renamed":
        _fail("PUT /rules/{id}")
    _ok("PUT /rules/{id}")

    r = await client.patch(f"/api/call-control/rules/{rule_id}/priority", json={"priority": 200})
    if r.status_code != 200 or r.json().get("priority") != 200:
        _fail("PATCH priority (always-rule 를 뒤로 — 스케줄 규칙이 먼저 평가되도록)")
    _ok("PATCH /rules/{id}/priority")

    sch_body = {
        "owner": owner,
        "name": "weekday 9-18",
        "days": ["mon", "tue", "wed", "thu", "fri"],
        "time_ranges": [{"start": "09:00", "end": "18:00"}],
        "timezone": "Asia/Seoul",
        "include_holidays": False,
        "holiday_country": "KR",
    }
    r = await client.post("/api/call-control/schedules", json=sch_body)
    if r.status_code != 201:
        _fail(f"POST schedule: {r.status_code} {r.text}")
    schedule_id = r.json()["id"]
    _ok("POST /schedules")

    r2_body = {
        "owner": owner,
        "name": "biz immediate_ai",
        "priority": 10,
        "action": "immediate_ai",
        "no_answer_timeout": 15,
        "schedule_id": schedule_id,
        "enabled": True,
    }
    r = await client.post("/api/call-control/rules", json=r2_body)
    if r.status_code != 201:
        _fail(f"POST scheduled rule: {r.status_code} {r.text}")
    rule2_id = r.json()["id"]
    _ok("POST /rules with schedule")

    mon_noon_kst = datetime(2026, 4, 13, 3, 0, 0, tzinfo=timezone.utc)
    resolved = re.resolve_rule(owner, now=mon_noon_kst)
    if not resolved or resolved["rule"].get("id") != rule2_id:
        _fail(
            f"resolve_rule expected biz rule; got {json.dumps(resolved, default=str)[:400]}"
        )
    _ok("routing_engine.resolve_rule matches schedule + priority")

    r = await client.get(f"/api/call-control/status/{owner}")
    if r.status_code != 200 or "description" not in r.json():
        _fail("GET /status/{owner}")
    _ok("GET /status/{owner}")

    r = await client.get(f"/api/call-control/preview/{owner}")
    if r.status_code != 200:
        _fail("GET preview")
    pv = r.json()
    if pv.get("current_rule_id") not in (rule2_id, rule_id, None):
        _fail(f"preview current_rule_id unexpected: {pv.get('current_rule_id')}")
    _ok("GET /preview/{owner}")

    ann = {
        "owner": owner,
        "name": "greet",
        "text": "안녕하세요",
        "use_tts": True,
        "use_as_ringback_greeting": True,
        "generation_mode": "tts",
    }
    r = await client.post("/api/call-control/announcements", json=ann)
    if r.status_code != 201:
        _fail(f"POST announcement: {r.status_code} {r.text}")
    ann_id = r.json()["id"]
    _ok("POST /announcements")

    r = await client.get("/api/call-control/announcements/ringback-greeting", params={"owner": owner})
    if r.status_code != 200 or r.json().get("text") != "안녕하세요":
        _fail(f"ringback-greeting: {r.text}")
    _ok("GET /announcements/ringback-greeting")

    rg = {
        "owner": owner,
        "name": "sales",
        "members": ["1001", "1002"],
        "mode": "simultaneous",
        "no_answer_timeout": 25,
    }
    r = await client.post("/api/call-control/ring-groups", json=rg)
    if r.status_code != 201:
        _fail(f"POST ring-group: {r.status_code} {r.text}")
    rg_id = r.json()["id"]
    _ok("POST /ring-groups")

    cf = {
        "owner": owner,
        "name": "vip",
        "pattern": "010*",
        "action": "immediate_ai",
        "enabled": True,
        "priority": 0,
    }
    r = await client.post("/api/call-control/caller-filters", json=cf)
    if r.status_code != 201:
        _fail(f"POST caller-filter: {r.status_code} {r.text}")
    cf_id = r.json()["id"]
    _ok("POST /caller-filters")

    r = await client.put(
        f"/api/call-control/caller-filters/{cf_id}",
        json={"enabled": False, "name": "vip-off"},
    )
    if r.status_code != 200:
        _fail(f"PUT caller-filter: {r.status_code} {r.text}")
    if r.json().get("enabled") is not False:
        _fail(f"PUT caller-filter body not applied: {r.json()}")
    _ok("PUT /caller-filters/{id} with JSON body")

    matched = re.resolve_caller_filter(owner, "01012345678")
    if matched is not None:
        _fail("disabled caller filter should not match")
    _ok("resolve_caller_filter respects enabled=false")

    await client.put(f"/api/call-control/caller-filters/{cf_id}", json={"enabled": True})
    matched = re.resolve_caller_filter(owner, "01099998888")
    if not matched or matched.get("id") != cf_id:
        _fail("caller filter prefix match")
    _ok("resolve_caller_filter pattern 010*")

    ov = {
        "owner": owner,
        "enabled": True,
        "max_concurrent_calls": 2,
        "overflow_action": "immediate_ai",
        "announcement_id": None,
    }
    r = await client.put(f"/api/call-control/overflow/{owner}", json=ov)
    if r.status_code != 200:
        _fail(f"PUT overflow: {r.status_code} {r.text}")
    r = await client.get(f"/api/call-control/overflow/{owner}")
    if r.status_code != 200 or r.json().get("max_concurrent_calls") != 2:
        _fail("GET overflow")
    _ok("GET/PUT /overflow/{owner}")

    for method, path in [
        ("DELETE", f"/api/call-control/caller-filters/{cf_id}"),
        ("DELETE", f"/api/call-control/ring-groups/{rg_id}"),
        ("DELETE", f"/api/call-control/announcements/{ann_id}"),
        ("DELETE", f"/api/call-control/rules/{rule2_id}"),
        ("DELETE", f"/api/call-control/rules/{rule_id}"),
        ("DELETE", f"/api/call-control/schedules/{schedule_id}"),
    ]:
        r = await client.request(method, path)
        if r.status_code != 204:
            _fail(f"{method} {path}: {r.status_code} {r.text}")
    _ok("DELETE cascade 204")


async def async_main() -> None:
    cc_db.init_db()
    owner = "cc_verify_owner_42"
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await _run_checks(client, owner)
    print("All checks passed. DB:", _VERIFY_DB)


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
