"""Story 1.13 QA용 owner=9003 call_records 시드 스크립트 (일회성, QA 종료 후 삭제 가능)."""
from datetime import datetime, timedelta, timezone

from src.common.call_record_db import upsert_call_record

owner = "9003"
now = datetime.now(timezone.utc)


def iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


upsert_call_record(
    call_id="qa-ch-001", owner=owner, caller_id="010-1111-1111", callee_id=owner,
    direction="inbound", start_time=iso(now - timedelta(days=2)), end_time=iso(now - timedelta(days=2)),
    duration=60.0, call_summary="예약 문의 관련 통화였습니다", is_ai_handled=True, has_recording=True,
)
upsert_call_record(
    call_id="qa-ch-002", owner=owner, caller_id="010-1111-1111", callee_id=owner,
    direction="inbound", start_time=iso(now - timedelta(days=1)), end_time=iso(now - timedelta(days=1)),
    duration=45.0, call_summary="영업시간 문의", is_ai_handled=True, has_recording=True,
)
upsert_call_record(
    call_id="qa-ch-003", owner=owner, caller_id="010-2222-2222", callee_id=owner,
    direction="inbound", start_time=iso(now - timedelta(hours=5)), end_time=iso(now - timedelta(hours=5)),
    duration=30.0, call_summary="예약 취소 요청 문의였습니다", is_ai_handled=True, has_recording=True,
)
upsert_call_record(
    call_id="qa-ch-004", owner=owner, caller_id="010-3333-3333", callee_id=owner,
    direction="inbound", start_time=iso(now - timedelta(minutes=30)), end_time=iso(now - timedelta(minutes=29)),
    duration=5.0, call_summary="", is_ai_handled=False, has_recording=False,
)
print("done inserting QA call records for owner", owner)
