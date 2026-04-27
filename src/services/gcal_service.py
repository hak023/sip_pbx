"""Google Calendar API 연동 서비스.

owner(테넌트) 단위로 Google OAuth 2.0 토큰을 관리하고,
예약(bookings)을 Google Calendar 이벤트로 CRUD한다.

공개 함수:
    get_token(owner)            → dict | None
    save_token(owner, data)     → None
    delete_token(owner)         → None
    get_oauth_status(owner)     → dict
    build_oauth_authorization_url(state) → str
    exchange_oauth_authorization_code(code) → dict
    oauth_code_response_to_token_row(resp) → dict  (save_token 인자)
    sign_oauth_owner_state(owner) / verify_oauth_owner_state(state) → str | None
    create_event(owner, booking) → str | None   (gcal_event_id)
    cancel_event(owner, booking_id) → bool
    update_event(owner, booking_id, booking) → bool
    list_events(owner, date_from, date_to) → list[dict]
    bulk_sync(owner)            → dict  {synced, failed}

내부:
    _get_credentials(owner)     → google.oauth2.credentials.Credentials | None
    _build_service(creds)       → googleapiclient.discovery Resource
    _booking_to_event(booking, duration_min) → dict (Google Calendar event body)
    save_gcal_map(booking_id, gcal_event_id, owner) → None
    get_gcal_event_id(booking_id) → str | None
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# ── 설정 ─────────────────────────────────────────────────────────────────────

def _cfg() -> dict:
    """config.yaml의 google_calendar 블록을 반환. 환경변수 오버라이드 지원."""
    try:
        import yaml
        cfg_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "config", "config.yaml"
        )
        with open(cfg_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        return raw.get("google_calendar", {})
    except Exception:
        return {}


def _client_id() -> str:
    return os.environ.get("GCAL_CLIENT_ID") or _cfg().get("client_id", "")


def _client_secret() -> str:
    return os.environ.get("GCAL_CLIENT_SECRET") or _cfg().get("client_secret", "")


def _redirect_uri() -> str:
    return (
        os.environ.get("GCAL_REDIRECT_URI")
        or _cfg().get("redirect_uri", "http://localhost:8000/api/google/oauth/callback")
    )


def oauth_app_credentials_ok() -> bool:
    """OAuth 인가·토큰 교환에 필요한 client_id / client_secret 존재 여부."""
    return bool(str(_client_id()).strip() and str(_client_secret()).strip())


_SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _oauth_state_secret() -> str:
    """OAuth state HMAC 비밀. 운영에서는 GCAL_OAUTH_STATE_SECRET 필수 권장."""
    return (
        os.environ.get("GCAL_OAUTH_STATE_SECRET")
        or _client_secret()
        or "gcal-oauth-state-dev-only-change-me"
    )


def sign_oauth_owner_state(owner: str) -> str:
    """콜백에서 owner를 복원·위조 방지용 state 문자열."""
    own = (owner or "").strip()
    if not own:
        raise ValueError("owner is required for OAuth state")
    payload = json.dumps(
        {"owner": own, "ts": int(datetime.now(timezone.utc).timestamp())},
        separators=(",", ":"),
    )
    sig = hmac.new(
        _oauth_state_secret().encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:32]
    raw = f"{payload}|{sig}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def verify_oauth_owner_state(state: str, *, max_age_sec: int = 7200) -> str | None:
    """sign_oauth_owner_state 로 서명된 state에서 owner 추출."""
    if not state or not isinstance(state, str):
        return None
    try:
        pad = "=" * ((4 - len(state) % 4) % 4)
        decoded = base64.urlsafe_b64decode(state.strip() + pad).decode("utf-8")
        payload, sig = decoded.rsplit("|", 1)
        expect = hmac.new(
            _oauth_state_secret().encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()[:32]
        if not hmac.compare_digest(expect, sig):
            logger.warning("gcal_oauth_state_bad_signature")
            return None
        data = json.loads(payload)
        own = (data.get("owner") or "").strip()
        if not own:
            return None
        ts = int(data.get("ts") or 0)
        now = int(datetime.now(timezone.utc).timestamp())
        if ts <= 0 or now - ts > max_age_sec:
            logger.warning("gcal_oauth_state_expired", owner=own, age_sec=now - ts if ts else None)
            return None
        return own
    except Exception as e:
        logger.warning("gcal_oauth_state_verify_failed", error=str(e))
        return None


def build_oauth_authorization_url(state: str) -> str:
    """브라우저로 보낼 Google OAuth 2.0 인가 URL."""
    cid = _client_id()
    if not cid:
        raise ValueError("GCAL_CLIENT_ID 또는 config google_calendar.client_id 가 비어 있습니다.")
    params = {
        "client_id": cid,
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": " ".join(_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)


def exchange_oauth_authorization_code(code: str) -> dict[str, Any]:
    """인가 코드 → 토큰 엔드포인트 교환. 응답 JSON(dict) 그대로 반환."""
    body = urllib.parse.urlencode(
        {
            "code": code,
            "client_id": _client_id(),
            "client_secret": _client_secret(),
            "redirect_uri": _redirect_uri(),
            "grant_type": "authorization_code",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:4000]
        logger.warning(
            "gcal_oauth_token_exchange_http_error",
            status=e.code,
            body_preview=err_body,
        )
        raise ValueError(f"Google token exchange failed: HTTP {e.code}: {err_body}") from e


def oauth_code_response_to_token_row(token_json: dict[str, Any]) -> dict[str, Any]:
    """exchange_oauth_authorization_code 응답 → save_token()용 row."""
    expires_in = int(token_json.get("expires_in") or 3600)
    exp = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    return {
        "access_token": token_json.get("access_token", "") or "",
        "refresh_token": token_json.get("refresh_token", "") or "",
        "token_expiry": exp.isoformat(),
        "calendar_id": "primary",
        "connected_at": _now_str(),
    }


# ── DB 헬퍼 ──────────────────────────────────────────────────────────────────

def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_token(owner: str) -> dict | None:
    """google_tokens 테이블에서 토큰 정보를 조회한다."""
    from src.booking.database import get_connection
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM google_tokens WHERE owner = ?", (owner,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def save_token(owner: str, token_data: dict) -> None:
    """토큰을 저장하거나 갱신한다."""
    from src.booking.database import get_db
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO google_tokens
                (owner, access_token, refresh_token, token_expiry, calendar_id, connected_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(owner) DO UPDATE SET
                access_token = excluded.access_token,
                refresh_token = CASE WHEN excluded.refresh_token != '' THEN excluded.refresh_token
                                     ELSE google_tokens.refresh_token END,
                token_expiry = excluded.token_expiry,
                calendar_id  = excluded.calendar_id,
                updated_at   = excluded.updated_at
            """,
            (
                owner,
                token_data.get("access_token", ""),
                token_data.get("refresh_token", ""),
                token_data.get("token_expiry", ""),
                token_data.get("calendar_id", "primary"),
                token_data.get("connected_at", _now_str()),
                _now_str(),
            ),
        )
    logger.info("gcal_token_saved", owner=owner)


def delete_token(owner: str) -> None:
    """토큰과 이벤트 매핑을 모두 삭제한다 (연동 해제)."""
    from src.booking.database import get_db
    with get_db() as conn:
        conn.execute("DELETE FROM google_tokens WHERE owner = ?", (owner,))
        conn.execute("DELETE FROM gcal_event_map WHERE owner = ?", (owner,))
    logger.info("gcal_token_deleted", owner=owner)


def get_oauth_status(owner: str) -> dict:
    """연동 상태 정보를 반환한다 (비밀: access/refresh 전체는 노출하지 않음)."""
    token = get_token(owner)
    if not token:
        return {
            "connected": False,
            "owner": owner,
            "has_access_token": False,
            "has_refresh_token": False,
            "token_expiry": "",
            "calendar_id": "",
        }
    at = (token.get("access_token") or "").strip()
    rt = (token.get("refresh_token") or "").strip()
    return {
        "connected": bool(at),
        "owner": owner,
        "calendar_id": token.get("calendar_id", "primary"),
        "connected_at": token.get("connected_at"),
        "updated_at": token.get("updated_at"),
        "has_access_token": bool(at),
        "has_refresh_token": bool(rt),
        "token_expiry": token.get("token_expiry") or "",
        "access_token_prefix": (at[:8] + "…") if at else "",
    }


def save_gcal_map(booking_id: str, gcal_event_id: str, owner: str) -> None:
    """예약 ID ↔ Google Calendar 이벤트 ID 매핑을 저장한다."""
    from src.booking.database import get_db
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO gcal_event_map (booking_id, gcal_event_id, owner, synced_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(booking_id) DO UPDATE SET
                gcal_event_id = excluded.gcal_event_id,
                synced_at     = excluded.synced_at
            """,
            (booking_id, gcal_event_id, owner, _now_str()),
        )


def get_gcal_event_id(booking_id: str) -> str | None:
    """예약 ID로 Google Calendar 이벤트 ID를 조회한다."""
    from src.booking.database import get_connection
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT gcal_event_id FROM gcal_event_map WHERE booking_id = ?",
            (booking_id,),
        ).fetchone()
        return row["gcal_event_id"] if row else None
    finally:
        conn.close()


# ── Google API 인증 ──────────────────────────────────────────────────────────

def _get_credentials(owner: str):
    """owner 토큰으로 google.oauth2.credentials.Credentials를 만든다.

    만료된 경우 refresh_token으로 자동 갱신하고 DB에 저장한다.
    """
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
    except ImportError:
        logger.error("gcal_missing_google_auth_lib")
        return None

    token = get_token(owner)
    if not token:
        logger.debug("gcal_no_token", owner=owner)
        return None

    expiry_str = token.get("token_expiry", "")
    try:
        expiry = datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
    except Exception:
        expiry = datetime.now(timezone.utc) - timedelta(hours=1)

    creds = Credentials(
        token=token["access_token"],
        refresh_token=token.get("refresh_token") or None,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=_client_id(),
        client_secret=_client_secret(),
        scopes=_SCOPES,
        expiry=expiry,
    )

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            save_token(owner, {
                "access_token": creds.token,
                "token_expiry": creds.expiry.isoformat() if creds.expiry else "",
            })
            logger.info("gcal_token_refreshed", owner=owner)
        except Exception as e:
            logger.warning("gcal_token_refresh_failed", owner=owner, error=str(e))
            return None

    return creds


def _build_service(creds):
    """google-api-python-client 서비스 객체를 생성한다."""
    try:
        from googleapiclient.discovery import build
        return build("calendar", "v3", credentials=creds, cache_discovery=False)
    except Exception as e:
        logger.error("gcal_build_service_failed", error=str(e))
        return None


# ── 이벤트 변환 ──────────────────────────────────────────────────────────────

def _booking_to_event(booking: dict, duration_min: int = 60) -> dict:
    """예약 dict를 Google Calendar 이벤트 body로 변환한다."""
    slot_date = booking.get("slot_date", "")
    slot_time = booking.get("slot_time", "")

    try:
        start_dt = datetime.strptime(f"{slot_date} {slot_time}", "%Y-%m-%d %H:%M")
    except Exception:
        try:
            start_dt = datetime.strptime(f"{slot_date} {slot_time}", "%Y-%m-%d %H:%M:%S")
        except Exception:
            start_dt = datetime.now()

    end_dt = start_dt + timedelta(minutes=duration_min)

    customer_name = booking.get("customer_name") or "고객"
    party_size = booking.get("party_size") or 1
    service_type = booking.get("service_type") or ""
    booking_id = booking.get("booking_id") or ""
    customer_phone = booking.get("customer_phone") or ""
    memo = booking.get("memo") or ""

    summary_parts = [f"[예약] {customer_name} ({party_size}명)"]
    if service_type:
        summary_parts.append(f"- {service_type}")
    summary = " ".join(summary_parts)

    description_lines = [f"예약번호: {booking_id}"]
    if customer_phone:
        description_lines.append(f"연락처: {customer_phone}")
    if memo:
        description_lines.append(f"메모: {memo}")

    return {
        "summary": summary,
        "description": "\n".join(description_lines),
        "start": {
            "dateTime": start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            "timeZone": "Asia/Seoul",
        },
        "end": {
            "dateTime": end_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            "timeZone": "Asia/Seoul",
        },
        "extendedProperties": {
            "private": {
                "sippbx_booking_id": booking_id,
                "sippbx_owner": booking.get("owner", ""),
            }
        },
    }


def _get_slot_duration(owner: str) -> int:
    """booking_settings에서 slot_duration_min을 가져온다."""
    try:
        from src.booking.database import get_connection
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT slot_duration_min FROM booking_settings WHERE owner = ?",
                (owner,),
            ).fetchone()
            return int(row["slot_duration_min"]) if row else 60
        finally:
            conn.close()
    except Exception:
        return 60


# ── 이벤트 CRUD ──────────────────────────────────────────────────────────────

def create_event(owner: str, booking: dict) -> str | None:
    """예약을 Google Calendar 이벤트로 생성한다.

    Returns:
        생성된 이벤트 ID 또는 None (연동 미설정 / 오류)
    """
    creds = _get_credentials(owner)
    if not creds:
        return None

    service = _build_service(creds)
    if not service:
        return None

    token = get_token(owner)
    calendar_id = (token or {}).get("calendar_id", "primary")
    duration_min = _get_slot_duration(owner)
    event_body = _booking_to_event(booking, duration_min)

    try:
        result = service.events().insert(calendarId=calendar_id, body=event_body).execute()
        gcal_event_id: str = result.get("id", "")
        logger.info("gcal_event_created",
                    owner=owner,
                    booking_id=booking.get("booking_id"),
                    gcal_event_id=gcal_event_id)
        return gcal_event_id
    except Exception as e:
        logger.warning("gcal_create_event_failed", owner=owner, error=str(e))
        return None


def cancel_event(owner: str, booking_id: str) -> bool:
    """예약 취소 시 Google Calendar 이벤트를 삭제한다."""
    gcal_event_id = get_gcal_event_id(booking_id)
    if not gcal_event_id:
        logger.debug("gcal_cancel_no_mapping", booking_id=booking_id)
        return False

    creds = _get_credentials(owner)
    if not creds:
        return False

    service = _build_service(creds)
    if not service:
        return False

    token = get_token(owner)
    calendar_id = (token or {}).get("calendar_id", "primary")

    try:
        service.events().delete(calendarId=calendar_id, eventId=gcal_event_id).execute()
        from src.booking.database import get_db
        with get_db() as conn:
            conn.execute("DELETE FROM gcal_event_map WHERE booking_id = ?", (booking_id,))
        logger.info("gcal_event_cancelled", owner=owner, booking_id=booking_id)
        return True
    except Exception as e:
        logger.warning("gcal_cancel_event_failed", owner=owner, booking_id=booking_id, error=str(e))
        return False


def update_event(owner: str, booking_id: str, booking: dict) -> bool:
    """예약 변경 시 Google Calendar 이벤트를 수정한다."""
    gcal_event_id = get_gcal_event_id(booking_id)
    if not gcal_event_id:
        # 매핑이 없으면 새로 생성
        new_id = create_event(owner, booking)
        if new_id:
            save_gcal_map(booking_id, new_id, owner)
        return new_id is not None

    creds = _get_credentials(owner)
    if not creds:
        return False

    service = _build_service(creds)
    if not service:
        return False

    token = get_token(owner)
    calendar_id = (token or {}).get("calendar_id", "primary")
    duration_min = _get_slot_duration(owner)
    event_body = _booking_to_event(booking, duration_min)

    try:
        service.events().update(
            calendarId=calendar_id, eventId=gcal_event_id, body=event_body
        ).execute()
        logger.info("gcal_event_updated", owner=owner, booking_id=booking_id)
        return True
    except Exception as e:
        logger.warning("gcal_update_event_failed", owner=owner, booking_id=booking_id, error=str(e))
        return False


def list_events(owner: str, date_from: str, date_to: str) -> list[dict[str, Any]]:
    """Google Calendar 이벤트 목록을 조회한다.

    Args:
        date_from: 'YYYY-MM-DD' 형식 시작일
        date_to:   'YYYY-MM-DD' 형식 종료일 (포함)

    Returns:
        이벤트 dict 목록 (id, summary, start, end, description, booking_id)
    """
    creds = _get_credentials(owner)
    if not creds:
        return []

    service = _build_service(creds)
    if not service:
        return []

    token = get_token(owner)
    calendar_id = (token or {}).get("calendar_id", "primary")

    time_min = f"{date_from}T00:00:00+09:00"
    time_max = f"{date_to}T23:59:59+09:00"

    try:
        result = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
                maxResults=250,
            )
            .execute()
        )
        events = []
        for item in result.get("items", []):
            ext = item.get("extendedProperties", {}).get("private", {})
            events.append({
                "id": item.get("id"),
                "summary": item.get("summary"),
                "description": item.get("description"),
                "start": item.get("start", {}).get("dateTime") or item.get("start", {}).get("date"),
                "end": item.get("end", {}).get("dateTime") or item.get("end", {}).get("date"),
                "status": item.get("status"),
                "booking_id": ext.get("sippbx_booking_id"),
                "html_link": item.get("htmlLink"),
            })
        return events
    except Exception as e:
        logger.warning("gcal_list_events_failed", owner=owner, error=str(e))
        return []


def bulk_sync(owner: str) -> dict[str, int]:
    """owner의 미래 예약 전체를 Google Calendar에 일괄 동기화한다.

    Returns:
        {"synced": int, "failed": int, "skipped": int}
    """
    from src.booking.database import get_connection
    conn = get_connection()
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        rows = conn.execute(
            """
            SELECT * FROM bookings
            WHERE owner = ? AND slot_date >= ? AND status = 'confirmed'
            ORDER BY slot_date, slot_time
            """,
            (owner, today),
        ).fetchall()
        bookings = [dict(r) for r in rows]
    finally:
        conn.close()

    synced = failed = skipped = 0
    for booking in bookings:
        booking_id = booking["booking_id"]
        existing = get_gcal_event_id(booking_id)
        try:
            if existing:
                ok = update_event(owner, booking_id, booking)
                if ok:
                    synced += 1
                else:
                    failed += 1
            else:
                gcal_event_id = create_event(owner, booking)
                if gcal_event_id:
                    save_gcal_map(booking_id, gcal_event_id, owner)
                    synced += 1
                else:
                    failed += 1
        except Exception as e:
            logger.warning("gcal_bulk_sync_item_failed", booking_id=booking_id, error=str(e))
            failed += 1

    logger.info("gcal_bulk_sync_done", owner=owner, synced=synced, failed=failed, skipped=skipped)
    return {"synced": synced, "failed": failed, "skipped": skipped}
