"""SIP MESSAGE 라우터 — 아웃바운드 발신 및 수신 이력 조회.

실제 SMS 없이 Linphone(소프트폰) 으로 SIP MESSAGE를 보내
예약 확인·알림 문자 시나리오를 테스트할 때 사용한다.

엔드포인트:
    POST /api/messages/send          SIP MESSAGE 발신 (서버 → 소프트폰)
    GET  /api/messages/registered    현재 등록된 SIP 사용자 목록 조회
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import structlog

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/messages", tags=["SIP Messages"])


# ── 요청/응답 스키마 ──────────────────────────────────────────────────

class SendMessageRequest(BaseModel):
    to: str
    """수신자 SIP username 또는 URI. 예: '1001', 'sip:1001@192.168.1.10'"""

    body: str
    """전송할 메시지 본문 (UTF-8 텍스트)"""

    content_type: str = "text/plain; charset=UTF-8"
    """Content-Type. 기본값 text/plain"""


class SendMessageResponse(BaseModel):
    success: bool
    to: str
    body: str
    timestamp: str
    error: Optional[str] = None


class RegisteredUser(BaseModel):
    username: str
    ip: str
    port: int


# ── 엔드포인트 ────────────────────────────────────────────────────────

@router.post("/send", response_model=SendMessageResponse)
async def send_sip_message(req: SendMessageRequest):
    """SIP MESSAGE 아웃바운드 발신 (서버 → Linphone 등 소프트폰).

    to 파라미터에 지정한 username이 현재 SIP 서버에 REGISTER 되어 있어야 한다.
    등록된 IP·port로 UDP SIP MESSAGE 패킷을 전송한다.

    예시:
        POST /api/messages/send
        { "to": "1001", "body": "[예약확인] 내일 오후 2시 예약이 확정되었습니다." }
    """
    try:
        endpoint = _get_sip_endpoint()
        ok = endpoint.send_sip_message(
            to_uri=req.to,
            body=req.body,
            content_type=req.content_type,
        )
        if not ok:
            registered = list(endpoint._registered_users.keys())
            raise HTTPException(
                status_code=404,
                detail=f"'{req.to}' 사용자가 등록되어 있지 않습니다. "
                       f"현재 등록된 사용자: {registered}",
            )

        logger.info("api_sip_message_sent", to=req.to, body_length=len(req.body))
        return SendMessageResponse(
            success=True,
            to=req.to,
            body=req.body,
            timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("api_sip_message_send_error", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/registered", response_model=List[RegisteredUser])
async def get_registered_users():
    """현재 SIP 서버에 REGISTER 된 사용자 목록 조회.

    Linphone이 등록되어 있는지 확인할 때 사용한다.
    """
    try:
        endpoint = _get_sip_endpoint()
        users = [
            RegisteredUser(
                username=username,
                ip=info["ip"],
                port=info["port"],
            )
            for username, info in endpoint._registered_users.items()
        ]
        return users
    except Exception as e:
        logger.error("api_get_registered_users_error", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────

def _get_sip_endpoint():
    """현재 실행 중인 SIP Endpoint 인스턴스를 가져온다.

    src.main 에서 글로벌로 관리하는 endpoint 객체를 참조한다.
    """
    try:
        import src.main as app_main
        endpoint = getattr(app_main, "_sip_endpoint", None)
        if endpoint is None:
            raise HTTPException(
                status_code=503,
                detail="SIP 서버가 아직 시작되지 않았습니다.",
            )
        return endpoint
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="SIP 메인 모듈을 로드할 수 없습니다.",
        )
