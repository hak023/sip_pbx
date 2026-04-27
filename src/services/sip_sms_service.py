"""
SIP MESSAGE (SMS) 발송 서비스.

Softphone 환경에서 SIP MESSAGE 메서드를 이용해 SMS를 전송한다.
RFC 3428 (Session Initiation Protocol (SIP) Extension for Instant Messaging) 준수.

발송 흐름:
  1. SIPEndpoint의 _registered_users에서 수신자(to_phone) 주소 조회
  2. 등록된 경우 → SIP MESSAGE 직접 전송 (UDP)
  3. 미등록 / 주소 불명 시 → 로컬 SIP 서버에 MESSAGE 요청 (프록시 경유)

발송 기록은 sms_log 테이블(booking.db)에 저장.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import uuid
from datetime import datetime
from typing import Optional, Tuple

import structlog

logger = structlog.get_logger(__name__)

# SIP MESSAGE 템플릿
_SIP_MESSAGE_TEMPLATE = (
    "MESSAGE sip:{to_user}@{to_host}:{to_port} SIP/2.0\r\n"
    "Via: SIP/2.0/UDP {local_ip}:{local_port};branch=z9hG4bK{branch}\r\n"
    "From: <sip:{from_user}@{local_ip}>;tag={from_tag}\r\n"
    "To: <sip:{to_user}@{to_host}>\r\n"
    "Call-ID: {call_id}@{local_ip}\r\n"
    "CSeq: 1 MESSAGE\r\n"
    "Max-Forwards: 70\r\n"
    "Content-Type: text/plain; charset=UTF-8\r\n"
    "Content-Length: {content_length}\r\n"
    "\r\n"
    "{body}"
)


def _normalize_phone(phone: str) -> str:
    """전화번호에서 숫자와 + 만 추출."""
    return "".join(c for c in phone if c.isdigit() or c == "+")


def _get_local_ip() -> str:
    """로컬 IP 주소 획득."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def _build_message(
    to_user: str,
    to_host: str,
    to_port: int,
    from_user: str,
    local_ip: str,
    local_port: int,
    body: str,
) -> str:
    """SIP MESSAGE 패킷 문자열 생성."""
    branch = uuid.uuid4().hex[:16]
    from_tag = uuid.uuid4().hex[:8]
    call_id = uuid.uuid4().hex[:16]
    body_bytes = body.encode("utf-8")
    return _SIP_MESSAGE_TEMPLATE.format(
        to_user=to_user,
        to_host=to_host,
        to_port=to_port,
        local_ip=local_ip,
        local_port=local_port,
        branch=branch,
        from_user=from_user,
        from_tag=from_tag,
        call_id=call_id,
        content_length=len(body_bytes),
        body=body,
    )


def _get_registered_addr(to_user: str, sip_server_ip: str, sip_server_port: int) -> Optional[Tuple[str, int]]:
    """SIPEndpoint._registered_users 에서 to_user의 실제 IP/port를 조회.

    등록 정보가 있으면 (ip, port) 반환, 없으면 None.
    SIP 서버 모듈을 import할 수 없는 환경에서는 None을 반환해 프록시 방식으로 폴백.
    """
    try:
        import src.main as _main
        endpoint = getattr(_main, "_sip_endpoint", None)
        if endpoint is None:
            return None
        info = endpoint._registered_users.get(to_user)
        if info:
            return (info["ip"], info["port"])
    except Exception as _e:
        logger.debug("sip_sms_registered_lookup_failed", error=str(_e))
    return None


def send_sip_sms_sync(
    to_phone: str,
    message: str,
    from_phone: str = "",
    sip_server_ip: str = "127.0.0.1",
    sip_server_port: int = 5060,
    local_port: int = 0,
) -> dict:
    """SIP MESSAGE를 동기로 전송한다.

    수신자가 SIP 서버에 REGISTER 되어 있으면 그 실제 IP/port로 직접 전송한다.
    (Linphone 등 소프트폰은 NAT 뒤에 있을 수 있으므로 등록 정보를 우선 사용)
    등록 정보가 없으면 sip_server_ip:sip_server_port 로 프록시 경유 전송한다.

    Args:
        to_phone: 수신자 전화번호 (SIP username)
        message: 발송할 메시지 본문
        from_phone: 발신자 번호 (SIP From)
        sip_server_ip: SIP 서버 IP (등록 정보 없을 때 프록시로 사용)
        sip_server_port: SIP 서버 포트
        local_port: 로컬 바인딩 포트 (0이면 OS 자동 할당)

    Returns:
        {"success": bool, "message": str, "to": str, "from": str}
    """
    to_user = _normalize_phone(to_phone) or to_phone
    from_user = _normalize_phone(from_phone) or from_phone or "ai-booking"
    local_ip = _get_local_ip()

    # ① 등록된 소프트폰 IP/port 직접 조회 (Linphone 등)
    registered = _get_registered_addr(to_user, sip_server_ip, sip_server_port)
    if registered:
        dest_host, dest_port = registered
        logger.info(
            "sip_sms_direct_delivery",
            to=to_phone,
            dest=f"{dest_host}:{dest_port}",
            note="registered_user_direct",
        )
    else:
        # ② 폴백: SIP 서버 경유 (프록시)
        dest_host, dest_port = sip_server_ip, sip_server_port
        logger.info(
            "sip_sms_proxy_delivery",
            to=to_phone,
            dest=f"{dest_host}:{dest_port}",
            note="proxy_fallback",
        )

    sip_msg = _build_message(
        to_user=to_user,
        to_host=dest_host,
        to_port=dest_port,
        from_user=from_user,
        local_ip=local_ip,
        local_port=local_port or 5090,
        body=message,
    )

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if local_port:
            try:
                sock.bind(("", local_port))
            except OSError:
                pass
        sock.settimeout(3.0)
        sock.sendto(sip_msg.encode("utf-8"), (dest_host, dest_port))
        sock.close()

        logger.info(
            "sip_sms_sent",
            to=to_phone,
            from_=from_phone,
            dest=f"{dest_host}:{dest_port}",
            msg_len=len(message),
        )
        _log_sms(to_phone, from_phone, message, "sent")
        return {"success": True, "message": "SMS 발송 완료", "to": to_phone, "from": from_phone}

    except Exception as e:
        logger.error("sip_sms_send_error", to=to_phone, error=str(e))
        _log_sms(to_phone, from_phone, message, "failed", error=str(e))
        return {"success": False, "message": f"SMS 발송 실패: {e}", "to": to_phone, "from": from_phone}


def _log_sms(
    to_phone: str,
    from_phone: str,
    message: str,
    status: str,
    error: str = "",
) -> None:
    """SMS 발송 이력을 booking.db sms_log 테이블에 기록 (테이블 없으면 생성)."""
    try:
        from src.booking.database import get_connection
        conn = get_connection()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sms_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                to_phone TEXT NOT NULL,
                from_phone TEXT,
                message TEXT,
                status TEXT,
                error TEXT,
                sent_at TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO sms_log (to_phone, from_phone, message, status, error, sent_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (to_phone, from_phone, message, status, error, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning("sip_sms_log_failed", error=str(e))
