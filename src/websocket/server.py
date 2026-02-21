"""Socket.IO WebSocket Server"""
import socketio
import aiohttp.web
import asyncio
import structlog
from typing import Dict, Any, Optional
from datetime import datetime

from src.api.auth_utils import decode_jwt, JWTError
from src.sip_core.utils import extract_extension_from_uri

logger = structlog.get_logger(__name__)

# CallManager 인스턴스 (외부에서 주입)
_call_manager = None


def set_call_manager(call_manager):
    """CallManager 인스턴스 주입"""
    global _call_manager
    _call_manager = call_manager

# Socket.IO 서버 생성
sio = socketio.AsyncServer(
    async_mode='aiohttp',
    cors_allowed_origins='*',  # 개발용: 모든 origin 허용
    logger=True,
    engineio_logger=False
)

# aiohttp 웹 앱 생성
app = aiohttp.web.Application()
sio.attach(app)

# 연결된 클라이언트 추적
connected_clients: Dict[str, Dict[str, Any]] = {}


@sio.event
async def connect(sid: str, environ: dict, auth: dict):
    """
    클라이언트 연결 (JWT 기반 인증)
    
    Args:
        sid: Session ID
        environ: WSGI 환경
        auth: 인증 정보 {'token': JWT}
    """
    token = auth.get('token') if auth else None
    
    if not token:
        logger.warning("ws_connection_rejected_no_token",
                      progress="realtime",
                      sid=sid)
        return False
    
    # JWT 검증 및 extension 추출
    try:
        payload = decode_jwt(token)
        extension = payload.get("extension") or payload.get("sub")
        role = payload.get("role", "operator")
        tenant_name = payload.get("tenant_name", extension)
        
        if not extension:
            logger.warning("ws_connection_rejected_invalid_token",
                          progress="realtime",
                          sid=sid,
                          reason="missing_extension")
            return False
        
        # 세션 저장
        await sio.save_session(sid, {
            'extension': extension,
            'role': role,
            'tenant_name': tenant_name,
            'connected_at': datetime.now().isoformat(),
            'subscribed_calls': set()  # 구독 중인 call_id 추적
        })
        
        # 역할별 룸에 입장
        await sio.enter_room(sid, f"role_{role}")
        
        # 클라이언트 추적
        connected_clients[sid] = {
            'extension': extension,
            'role': role,
            'connected_at': datetime.now()
        }
        
        logger.info("ws_client_connected",
                   progress="realtime",
                   sid=sid,
                   extension=extension,
                   role=role)
        
        # 연결 확인 메시지
        await sio.emit('connection_established', {
            'message': '연결 성공',
            'extension': extension,
            'role': role,
            'tenant_name': tenant_name
        }, room=sid)
        
        return True
        
    except JWTError as e:
        logger.warning("ws_connection_rejected_jwt_error",
                      progress="realtime",
                      sid=sid,
                      error=str(e))
        return False


@sio.event
async def disconnect(sid: str):
    """클라이언트 연결 해제"""
    if sid in connected_clients:
        user_info = connected_clients[sid]
        logger.info("ws_client_disconnected",
                   progress="realtime",
                   sid=sid, 
                   extension=user_info.get('extension'))
        del connected_clients[sid]


@sio.on('subscribe_call')
async def on_subscribe_call(sid: str, data: dict):
    """
    특정 통화의 업데이트 구독 (callee 권한 검사)
    
    Args:
        data: {'call_id': str}
        
    Returns:
        {'success': bool, 'error'?: str}
    """
    call_id = data.get('call_id')
    if not call_id:
        return {'success': False, 'error': 'call_id required'}
    
    # CallManager 필요
    if not _call_manager:
        logger.error("subscribe_call_no_call_manager", sid=sid, call_id=call_id)
        return {'success': False, 'error': 'service unavailable'}
    
    # 세션에서 extension 조회
    session = await sio.get_session(sid)
    user_extension = session.get('extension')
    
    if not user_extension:
        logger.warning("subscribe_call_no_extension",
                      progress="realtime",
                      sid=sid,
                      call_id=call_id)
        return {'success': False, 'error': 'unauthorized'}
    
    # CallSession 조회
    call_session = _call_manager.get_session(call_id)
    if not call_session:
        logger.warning("subscribe_call_not_found",
                      progress="realtime",
                      sid=sid,
                      call_id=call_id,
                      extension=user_extension)
        return {'success': False, 'error': 'call not found'}
    
    # callee extension 추출 및 권한 검사
    callee_uri = call_session.get_callee_uri()
    callee_extension = extract_extension_from_uri(callee_uri) if callee_uri else ""
    
    if callee_extension != user_extension:
        logger.warning("subscribe_call_forbidden",
                      progress="realtime",
                      sid=sid,
                      call_id=call_id,
                      user_extension=user_extension,
                      callee_extension=callee_extension)
        return {'success': False, 'error': 'forbidden'}
    
    # 구독 허용: room 입장
    await sio.enter_room(sid, f"call_{call_id}")
    
    # 구독 목록에 추가
    subscribed_calls = session.get('subscribed_calls', set())
    if len(subscribed_calls) >= 10:  # 최대 10개 제한
        return {'success': False, 'error': 'too_many_subscriptions'}
    
    subscribed_calls.add(call_id)
    session['subscribed_calls'] = subscribed_calls
    await sio.save_session(sid, session)
    
    logger.info("ws_call_subscribed",
               progress="realtime",
               sid=sid,
               call_id=call_id,
               extension=user_extension)
    
    return {'success': True, 'call_id': call_id}


@sio.on('unsubscribe_call')
async def on_unsubscribe_call(sid: str, data: dict):
    """통화 구독 해제"""
    call_id = data.get('call_id')
    if not call_id:
        return {'success': False, 'error': 'call_id required'}
    
    await sio.leave_room(sid, f"call_{call_id}")
    
    # 구독 목록에서 제거
    session = await sio.get_session(sid)
    subscribed_calls = session.get('subscribed_calls', set())
    subscribed_calls.discard(call_id)
    session['subscribed_calls'] = subscribed_calls
    await sio.save_session(sid, session)
    
    logger.info("ws_call_unsubscribed",
               progress="realtime",
               sid=sid,
               call_id=call_id)
    
    return {'success': True}


@sio.on('submit_hitl_response')
async def on_submit_hitl_response(sid: str, data: dict):
    """
    HITL 답변 제출
    
    Args:
        data: {
            'call_id': str, 
            'response_text': str, 
            'save_to_kb': bool,
            'category': Optional[str]
        }
    """
    call_id = data.get('call_id')
    response_text = data.get('response_text')
    save_to_kb = data.get('save_to_kb', False)
    category = data.get('category')
    
    if not call_id or not response_text:
        return {'success': False, 'error': 'call_id and response_text required'}
    
    # 세션에서 사용자 정보 가져오기
    session = await sio.get_session(sid)
    operator_id = session.get('user_id')
    
    logger.info("HITL response received via WebSocket",
               call_id=call_id,
               operator_id=operator_id,
               response_length=len(response_text),
               save_to_kb=save_to_kb)
    
    # HITL Service를 통해 응답 처리 (Knowledge Service에 저장 포함)
    from ..services.hitl import get_hitl_service
    hitl_service = get_hitl_service()
    
    if hitl_service:
        result = await hitl_service.submit_response(
            call_id=call_id,
            response_text=response_text,
            operator_id=operator_id,
            save_to_kb=save_to_kb,
            category=category
        )
        
        if not result['success']:
            logger.error("Failed to submit HITL response", 
                        call_id=call_id,
                        error=result.get('error'))
    else:
        logger.warning("HITLService not available, direct broadcast only")
        
        # 모든 클라이언트에게 HITL 해결 알림
        await sio.emit('hitl_resolved', {
            'call_id': call_id,
            'operator': session.get('user_name'),
            'timestamp': datetime.now().isoformat()
        })
    
    return {'success': True}


# ==================== Broadcasting Functions ====================

async def broadcast_to_call(call_id: str, event: str, data: dict):
    """특정 통화를 보고 있는 모든 클라이언트에게 브로드캐스트"""
    await sio.emit(event, data, room=f"call_{call_id}")
    # structlog는 'event' 키를 예약하므로 ws_event로 로깅 (event 중복 → TypeError 방지)
    logger.debug("Broadcast to call", call_id=call_id, ws_event=event)


async def broadcast_to_operators(event: str, data: dict):
    """모든 운영자에게 브로드캐스트"""
    await sio.emit(event, data, room="role_operator")
    logger.debug("Broadcast to operators", ws_event=event)


async def broadcast_global(event: str, data: dict):
    """연결된 모든 클라이언트에게 브로드캐스트"""
    await sio.emit(event, data)
    logger.debug("Global broadcast", ws_event=event)


# ==================== Event Emitters (AI Orchestrator에서 호출) ====================

async def emit_call_started(call_id: str, call_data: dict):
    """통화 시작 이벤트"""
    await broadcast_global('call_started', {
        'call_id': call_id,
        **call_data,
        'timestamp': datetime.now().isoformat()
    })


async def emit_call_ended(call_id: str):
    """통화 종료 이벤트"""
    await broadcast_global('call_ended', {
        'call_id': call_id,
        'timestamp': datetime.now().isoformat()
    })


async def emit_stt_transcript(call_id: str, text: str, is_final: bool):
    """STT 트랜스크립트 이벤트 (대시보드 실시간 대화용)"""
    payload = {
        'call_id': call_id,
        'text': text,
        'is_final': is_final,
        'timestamp': datetime.now().isoformat()
    }
    await broadcast_to_call(call_id, 'stt_transcript', payload)
    logger.info("ws_stt_transcript_sent",
                progress="realtime",
                call_id=call_id,
                is_final=is_final,
                text_len=len(text),
                note="대시보드 구독자(call_room)에게 stt_transcript 발송")


async def emit_tts_started(call_id: str, text: str):
    """TTS 시작 이벤트"""
    await broadcast_to_call(call_id, 'tts_started', {
        'call_id': call_id,
        'text': text,
        'timestamp': datetime.now().isoformat()
    })


async def emit_tts_completed(call_id: str):
    """TTS 완료 이벤트"""
    await broadcast_to_call(call_id, 'tts_completed', {
        'call_id': call_id,
        'timestamp': datetime.now().isoformat()
    })


async def emit_hitl_requested(call_id: str, question: str, context: dict, urgency: str):
    """HITL 요청 이벤트"""
    await broadcast_to_operators('hitl_requested', {
        'call_id': call_id,
        'question': question,
        'context': context,
        'urgency': urgency,
        'timestamp': datetime.now().isoformat()
    })
    
    # 브라우저 알림
    await broadcast_to_operators('notification', {
        'title': '🆘 AI가 도움을 요청했습니다',
        'message': f'질문: {question}',
        'type': 'hitl',
        'call_id': call_id
    })


async def emit_knowledge_updated(action: str, entry_id: str):
    """지식 베이스 업데이트 이벤트"""
    await broadcast_global(f'knowledge_{action}', {
        'entry_id': entry_id,
        'timestamp': datetime.now().isoformat()
    })


# ==================== Main Entry Point ====================

async def start_server():
    """WebSocket 서버 시작"""
    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, '0.0.0.0', 8001)
    await site.start()
    
    logger.info("WebSocket server started on ws://0.0.0.0:8001")
    # 콘솔에도 출력 (별도 프로세스에서 실행 시 확인용)
    print("✅ WebSocket server listening on http://0.0.0.0:8001", flush=True)
    
    # 서버 계속 실행
    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        logger.info("WebSocket server shutting down...")
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(start_server())

