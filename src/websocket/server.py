"""Socket.IO WebSocket Server"""
import socketio
import aiohttp.web
import asyncio
import structlog
from typing import Dict, Any
from datetime import datetime

logger = structlog.get_logger(__name__)

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
    클라이언트 연결
    
    Args:
        sid: Session ID
        environ: WSGI 환경
        auth: 인증 정보 (token)
    """
    # TODO: JWT 토큰 검증
    token = auth.get('token') if auth else None
    
    if not token:
        logger.warning("Connection rejected: No token", sid=sid)
        return False
    
    # Mock: 토큰 검증 (추후 실제 JWT 검증)
    if token.startswith('mock_token'):
        user_id = token.split('_')[2]
        user_role = "operator"  # Mock
        
        # 세션 저장
        await sio.save_session(sid, {
            'user_id': user_id,
            'user_role': user_role,
            'user_name': 'Operator User',
            'connected_at': datetime.now().isoformat()
        })
        
        # 역할별 룸에 입장
        await sio.enter_room(sid, f"role_{user_role}")
        
        # 클라이언트 추적
        connected_clients[sid] = {
            'user_id': user_id,
            'role': user_role,
            'connected_at': datetime.now()
        }
        
        logger.info("Client connected", sid=sid, user_id=user_id, role=user_role)
        
        # 연결 확인 메시지
        await sio.emit('connection_established', {
            'message': '연결 성공',
            'user_id': user_id,
            'role': user_role
        }, room=sid)
        
        return True
    else:
        logger.warning("Connection rejected: Invalid token", sid=sid)
        return False


@sio.event
async def disconnect(sid: str):
    """클라이언트 연결 해제"""
    if sid in connected_clients:
        user_info = connected_clients[sid]
        logger.info("Client disconnected", 
                   sid=sid, 
                   user_id=user_info.get('user_id'))
        del connected_clients[sid]


@sio.on('subscribe_call')
async def on_subscribe_call(sid: str, data: dict):
    """
    특정 통화의 업데이트 구독
    
    Args:
        data: {'call_id': str}
    """
    call_id = data.get('call_id')
    if not call_id:
        return {'success': False, 'error': 'call_id required'}
    
    await sio.enter_room(sid, f"call_{call_id}")
    
    logger.info("Client subscribed to call", sid=sid, call_id=call_id)
    
    return {'success': True, 'call_id': call_id}


@sio.on('unsubscribe_call')
async def on_unsubscribe_call(sid: str, data: dict):
    """통화 구독 해제"""
    call_id = data.get('call_id')
    if not call_id:
        return {'success': False, 'error': 'call_id required'}
    
    await sio.leave_room(sid, f"call_{call_id}")
    
    logger.info("Client unsubscribed from call", sid=sid, call_id=call_id)
    
    return {'success': True}


@sio.on('submit_hitl_response')
async def on_submit_hitl_response(sid: str, data: dict):
    """
    HITL 답변 제출
    
    Args:
        data: {'call_id': str, 'response_text': str, 'save_to_kb': bool}
    """
    call_id = data.get('call_id')
    response_text = data.get('response_text')
    
    if not call_id or not response_text:
        return {'success': False, 'error': 'call_id and response_text required'}
    
    # 세션에서 사용자 정보 가져오기
    session = await sio.get_session(sid)
    operator_id = session.get('user_id')
    
    logger.info("HITL response received via WebSocket",
               call_id=call_id,
               operator_id=operator_id,
               response_length=len(response_text))
    
    # TODO: AI Orchestrator에 답변 전달
    # await orchestrator.handle_human_response(call_id, response_text, operator_id)
    
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
    logger.debug("Broadcast to call", call_id=call_id, event=event)


async def broadcast_to_operators(event: str, data: dict):
    """모든 운영자에게 브로드캐스트"""
    await sio.emit(event, data, room="role_operator")
    logger.debug("Broadcast to operators", event=event)


async def broadcast_global(event: str, data: dict):
    """연결된 모든 클라이언트에게 브로드캐스트"""
    await sio.emit(event, data)
    logger.debug("Global broadcast", event=event)


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
    """STT 트랜스크립트 이벤트"""
    await broadcast_to_call(call_id, 'stt_transcript', {
        'call_id': call_id,
        'text': text,
        'is_final': is_final,
        'timestamp': datetime.now().isoformat()
    })


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
    
    # 서버 계속 실행
    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        logger.info("WebSocket server shutting down...")
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(start_server())

