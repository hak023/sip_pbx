"""Human-in-the-Loop Service.

Knowledge extraction from HITL: when operators submit a response in the frontend
with save_to_kb=True, submit_response() calls knowledge_service.add_from_hitl()
to store the Q&A in the vector DB. This is the only knowledge ingestion path for
AI-handled calls (human-to-human and HITL results only; AI-to-caller transcripts
are excluded from extraction in sip_endpoint._cleanup_call).

설계 (TTS_RTP_AND_HITL_DESIGN.md):
- RAG 부족 시: "해당 내용은 확인이 필요합니다. 잠시만 기다려 주세요." + HITL 요청
- HITL timeout 시: timeout_message TTS 재생 후 통화 종료, frontend에 hitl_timeout 피드백
- HITL 응답 수신 시: LLM으로 고객용 문장 정리 후 TTS (RAG 프로세서에서 처리)
"""
import asyncio
import json
from typing import Optional, Dict, Any, List, Callable, Awaitable
from datetime import datetime, timedelta
from uuid import uuid4
from enum import Enum
import structlog

# 설계 문서 2.2: HITL timeout 시 재생 문구
DEFAULT_TIMEOUT_MESSAGE = "확인이 지연되고 있습니다. 확인되는 대로 연락 드리겠습니다."
HITL_TIMEOUT_TTS_DELAY_SEC = 8  # timeout 메시지 TTS 재생 후 통화 종료까지 대기

from .knowledge_service import get_knowledge_service

logger = structlog.get_logger(__name__)

# call_id -> asyncio.Queue: 운영자 응답 텍스트를 해당 통화 파이프라인(TTS)으로 전달
_hitl_response_queues: Dict[str, asyncio.Queue] = {}


class OperatorStatus(str, Enum):
    """운영자 상태"""
    AVAILABLE = "available"   # 대기 중
    AWAY = "away"            # 부재중
    BUSY = "busy"            # 통화 중
    OFFLINE = "offline"      # 오프라인


class HITLService:
    """
    Human-in-the-Loop 관리 서비스
    
    Features:
    - HITL 요청 생성 및 저장 (Redis)
    - 운영자 알림 (WebSocket)
    - 타임아웃 관리
    - AI Orchestrator와 통신
    - 운영자 상태 관리 (부재중 모드)
    """
    
    def __init__(
        self,
        redis_client=None,
        websocket_manager=None,
        db=None,
        timeout_seconds: int = 60,
        timeout_message: Optional[str] = None,
    ):
        """
        Args:
            redis_client: Redis 클라이언트
            websocket_manager: WebSocket 관리자
            db: Database 클라이언트 (PostgreSQL)
            timeout_seconds: HITL 응답 대기 시간 (초)
            timeout_message: timeout 시 고객에게 TTS로 재생할 문구
        """
        self.redis_client = redis_client
        self.websocket_manager = websocket_manager
        self.db = db
        self._timeout_seconds = timeout_seconds
        self._timeout_message = timeout_message or DEFAULT_TIMEOUT_MESSAGE

        # Mock 저장소 (Redis 대체)
        self.hitl_requests: Dict[str, Dict[str, Any]] = {}
        # 운영자 응답을 해당 통화 파이프라인으로 전달하기 위한 큐 등록 (전역 사용)
        self._response_queues = _hitl_response_queues
        # HITL timeout 시 통화 종료 콜백 (call_id) -> None
        self._on_hitl_timeout: Optional[Callable[[str], Awaitable[None]]] = None

        logger.info("HITLService initialized", timeout_seconds=self._timeout_seconds)

    def register_hitl_response_queue(self, call_id: str, queue: asyncio.Queue) -> None:
        """해당 통화의 운영자 응답을 TTS로 넣기 위한 큐 등록 (파이프라인 시작 시 호출)"""
        self._response_queues[call_id] = queue
        logger.debug("hitl_response_queue_registered", call_id=call_id)

    def unregister_hitl_response_queue(self, call_id: str) -> None:
        """통화 종료 시 큐 해제"""
        self._response_queues.pop(call_id, None)
        logger.debug("hitl_response_queue_unregistered", call_id=call_id)

    def register_on_hitl_timeout(self, callback: Callable[[str], Awaitable[None]]) -> None:
        """HITL timeout 시 통화 종료를 위해 호출할 콜백 등록 (예: call_manager.request_hangup)."""
        self._on_hitl_timeout = callback
        logger.debug("hitl_timeout_callback_registered")

    def set_config(
        self,
        timeout_seconds: Optional[int] = None,
        timeout_message: Optional[str] = None,
    ) -> None:
        """설정 갱신 (main 등에서 config 로드 후 호출)."""
        if timeout_seconds is not None:
            self._timeout_seconds = timeout_seconds
        if timeout_message is not None:
            self._timeout_message = timeout_message
        logger.debug("hitl_config_updated", timeout_seconds=self._timeout_seconds)

    def push_operator_response(self, call_id: str, text: str) -> bool:
        """
        운영자가 입력한 응답 텍스트를 해당 통화 파이프라인의 TTS로 전달.
        submit_response()에서 호출.
        """
        queue = self._response_queues.get(call_id)
        if not queue:
            logger.warning("hitl_response_queue_not_found", call_id=call_id)
            return False
        try:
            queue.put_nowait(text)
            logger.info("hitl_operator_response_pushed", call_id=call_id, text_len=len(text))
            return True
        except Exception as e:
            logger.error("hitl_operator_response_push_failed", call_id=call_id, error=str(e))
            return False
    
    async def request_human_help(
        self,
        call_id: str,
        question: str,
        context: Dict[str, Any],
        urgency: str = 'medium',
        timeout_seconds: Optional[int] = None,
    ) -> bool:
        """
        AI가 사람의 도움을 요청
        
        Args:
            call_id: 통화 ID
            question: 사용자 질문
            context: 대화 컨텍스트 (이전 메시지, RAG 결과, 발신자 정보)
            urgency: 긴급도 (high/medium/low)
            timeout_seconds: 타임아웃 (초). None이면 서비스 초기화 시 설정값 사용.
            
        Returns:
            True: HITL 요청 성공 (운영자 대기 중)
            False: HITL 요청 거절 (운영자 부재중/오프라인)
        """
        if timeout_seconds is None:
            timeout_seconds = self._timeout_seconds
        # 1. 운영자 상태 확인 (신규)
        operator_status = await self._get_operator_status()
        
        if operator_status in [OperatorStatus.AWAY, OperatorStatus.OFFLINE]:
            logger.warning("Operator is away/offline - auto fallback",
                          call_id=call_id,
                          operator_status=operator_status)
            
            # 2. 미처리 HITL 요청 기록
            await self._save_unresolved_hitl_request(
                call_id=call_id,
                question=question,
                context=context
            )
            
            # 3. 자동 fallback (AI Orchestrator에 거절 신호)
            return False
        
        # 4. 운영자 대기 중 - 기존 로직 실행
        timestamp = datetime.now()
        timeout_at = timestamp + timedelta(seconds=timeout_seconds)
        
        request_data = {
            'call_id': call_id,
            'question': question,
            'context': context,
            'urgency': urgency,
            'timestamp': timestamp.isoformat(),
            'timeout_at': timeout_at.isoformat(),
            'status': 'pending'
        }
        
        # Redis에 저장 (TTL 설정)
        if self.redis_client:
            try:
                await self.redis_client.setex(
                    f"hitl:{call_id}",
                    timeout_seconds,
                    json.dumps(request_data, default=str)
                )
            except Exception as e:
                logger.error("Failed to store HITL request in Redis", 
                           call_id=call_id, error=str(e))
                # Mock 저장소 사용
                self.hitl_requests[call_id] = request_data
        else:
            # Mock 저장소
            self.hitl_requests[call_id] = request_data
        
        # Frontend에 WebSocket으로 알림
        if self.websocket_manager:
            try:
                await self.websocket_manager.emit_hitl_requested(
                    call_id=call_id,
                    question=question,
                    context=context,
                    urgency=urgency
                )
                logger.info("HITL request sent to operators via WebSocket",
                          call_id=call_id, urgency=urgency)
            except Exception as e:
                logger.error("Failed to send HITL notification via WebSocket",
                           call_id=call_id, error=str(e))
        
        # 타임아웃 태스크 스케줄링
        asyncio.create_task(self._handle_timeout(call_id, timeout_seconds))
        
        logger.info("HITL request created",
                   call=True,
                   call_id=call_id,
                   question=question,
                   urgency=urgency,
                   timeout_at=timeout_at.isoformat())
        
        return True
    
    async def _handle_timeout(self, call_id: str, timeout_seconds: int):
        """
        HITL 타임아웃 처리 (설계 2.2).
        타임아웃 시: (1) timeout_message를 큐에 넣어 TTS 재생 (2) frontend에 hitl_timeout (3) TTS 재생 후 통화 종료 콜백 호출.
        """
        await asyncio.sleep(timeout_seconds)
        
        # Redis에서 pending 여부 확인 (submit_response에서 이미 삭제됐을 수 있음)
        still_pending = False
        if call_id in self.hitl_requests:
            request = self.hitl_requests[call_id]
            if request.get('status') == 'pending':
                still_pending = True
                del self.hitl_requests[call_id]
        if self.redis_client:
            try:
                data = await self.redis_client.get(f"hitl:{call_id}")
                if data:
                    still_pending = True
                    await self.redis_client.delete(f"hitl:{call_id}")
            except Exception as e:
                logger.debug("hitl_timeout_redis_check", call_id=call_id, error=str(e))

        if not still_pending:
            return

        logger.warning("HITL request timed out", call_id=call_id)

        # (1) 고객에게 timeout 메시지 TTS 재생 (큐에 문구 넣기)
        queue = self._response_queues.get(call_id)
        if queue:
            try:
                queue.put_nowait(self._timeout_message)
                logger.info("hitl_timeout_message_queued", call_id=call_id)
            except Exception as e:
                logger.warning("hitl_timeout_queue_failed", call_id=call_id, error=str(e))

        # (2) Frontend에 타임아웃 피드백
        if self.websocket_manager:
            try:
                await self.websocket_manager.broadcast_global('hitl_timeout', {
                    'call_id': call_id,
                    'timestamp': datetime.now().isoformat(),
                })
            except Exception as e:
                logger.warning("hitl_timeout_ws_failed", call_id=call_id, error=str(e))

        # (3) TTS 재생 후 통화 종료 (설계: 확인되는 대로 연락 드리겠습니다 후 종료)
        if self._on_hitl_timeout:
            async def _delayed_hangup():
                await asyncio.sleep(HITL_TIMEOUT_TTS_DELAY_SEC)
                try:
                    if asyncio.iscoroutinefunction(self._on_hitl_timeout):
                        await self._on_hitl_timeout(call_id)
                    else:
                        self._on_hitl_timeout(call_id)
                except Exception as e:
                    logger.error("hitl_timeout_callback_error", call_id=call_id, error=str(e))
            asyncio.create_task(_delayed_hangup())
    
    async def submit_response(
        self,
        call_id: str,
        response_text: str,
        operator_id: str,
        save_to_kb: bool = False,
        category: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        운영자 답변 제출
        
        Args:
            call_id: 통화 ID
            response_text: 운영자가 작성한 답변
            operator_id: 운영자 ID
            save_to_kb: 지식 베이스에 저장 여부
            category: 지식 베이스 카테고리
            
        Returns:
            처리 결과
        """
        # HITL 요청 확인
        request = None
        if self.redis_client:
            try:
                request_json = await self.redis_client.get(f"hitl:{call_id}")
                if request_json:
                    request = json.loads(request_json)
            except Exception as e:
                logger.error("Failed to get HITL request from Redis", 
                           call_id=call_id, error=str(e))
        
        if not request and call_id in self.hitl_requests:
            request = self.hitl_requests[call_id]
        
        if not request:
            logger.warning("HITL request not found", call_id=call_id)
            return {
                'success': False,
                'error': 'HITL request not found or expired'
            }
        
        # 응답 시간 계산
        request_timestamp = datetime.fromisoformat(request['timestamp'])
        response_time = (datetime.now() - request_timestamp).total_seconds()
        
        logger.info("HITL response received",
                   call_id=call_id,
                   operator_id=operator_id,
                   response_time_seconds=response_time,
                   save_to_kb=save_to_kb)
        
        # TODO: AI Orchestrator에 답변 전달
        # await orchestrator.handle_human_response(
        #     call_id=call_id,
        #     response_text=response_text,
        #     operator_id=operator_id
        # )
        
        # TODO: 지식 베이스에 저장 (save_to_kb=True인 경우)
        if save_to_kb:
            logger.info("Saving HITL response to knowledge base",
                       call_id=call_id,
                       category=category)
            
            # Knowledge Service를 통해 Vector DB에 저장
            knowledge_service = get_knowledge_service()
            if knowledge_service:
                # 착신자 ID (owner) 추출 - 착신자별 지식으로 저장
                owner_id = request.get('context', {}).get('callee_id')
                
                save_result = await knowledge_service.add_from_hitl(
                    question=request['question'],
                    answer=response_text,
                    call_id=call_id,
                    operator_id=operator_id,
                    category=category or 'faq',
                    owner_id=owner_id
                )
                
                if save_result['success']:
                    logger.info("HITL knowledge saved successfully",
                               doc_id=save_result['doc_id'],
                               category=save_result['category'])
                else:
                    logger.error("Failed to save HITL knowledge",
                                error=save_result.get('error'))
            else:
                logger.warning("KnowledgeService not initialized, HITL knowledge not saved")
        
        # Redis에서 요청 삭제
        if self.redis_client:
            try:
                await self.redis_client.delete(f"hitl:{call_id}")
            except Exception as e:
                logger.error("Failed to delete HITL request from Redis", error=str(e))
        
        if call_id in self.hitl_requests:
            del self.hitl_requests[call_id]

        # 해당 통화 파이프라인에 운영자 응답을 TTS로 주입 (Pipecat 경로)
        self.push_operator_response(call_id, response_text)
        
        # Frontend에 해결 알림
        if self.websocket_manager:
            await self.websocket_manager.broadcast_global('hitl_resolved', {
                'call_id': call_id,
                'operator_id': operator_id,
                'response_time': response_time,
                'timestamp': datetime.now().isoformat()
            })
        
        # TODO: HITL 히스토리에 저장 (PostgreSQL)
        # await db.execute(
        #     """
        #     INSERT INTO hitl_history 
        #     (call_id, question, response, operator_id, response_time_seconds, resolved_at)
        #     VALUES ($1, $2, $3, $4, $5, NOW())
        #     """,
        #     call_id, request['question'], response_text, operator_id, response_time
        # )
        
        return {
            'success': True,
            'response_time': response_time
        }
    
    async def get_queue(self) -> list:
        """
        대기 중인 HITL 요청 목록 조회
        
        Returns:
            HITL 요청 리스트
        """
        requests = []
        
        if self.redis_client:
            try:
                # Redis에서 모든 HITL 요청 조회
                keys = await self.redis_client.keys("hitl:*")
                for key in keys:
                    data = await self.redis_client.get(key)
                    if data:
                        requests.append(json.loads(data))
            except Exception as e:
                logger.error("Failed to get HITL queue from Redis", error=str(e))
        
        # Mock 저장소에서 조회
        for request in self.hitl_requests.values():
            if request.get('status') == 'pending':
                requests.append(request)
        
        # 긴급도 및 시간 순 정렬
        urgency_order = {'high': 0, 'medium': 1, 'low': 2}
        requests.sort(key=lambda x: (
            urgency_order.get(x.get('urgency', 'medium'), 1),
            x.get('timestamp', '')
        ))
        
        return requests
    
    async def get_request(self, call_id: str) -> Optional[Dict[str, Any]]:
        """특정 HITL 요청 조회"""
        if self.redis_client:
            try:
                data = await self.redis_client.get(f"hitl:{call_id}")
                if data:
                    return json.loads(data)
            except Exception as e:
                logger.error("Failed to get HITL request from Redis", error=str(e))
        
        return self.hitl_requests.get(call_id)
    
    async def _get_operator_status(self) -> OperatorStatus:
        """
        운영자 상태 조회
        
        Returns:
            운영자 상태 (available, away, busy, offline)
        """
        if self.redis_client:
            try:
                status = await self.redis_client.get("operator:status")
                if status:
                    return OperatorStatus(status.decode() if isinstance(status, bytes) else status)
            except Exception as e:
                logger.error("Failed to get operator status from Redis", error=str(e))
        
        # 기본값: available (운영자 대기 중)
        return OperatorStatus.AVAILABLE
    
    async def _save_unresolved_hitl_request(
        self,
        call_id: str,
        question: str,
        context: Dict[str, Any]
    ) -> str:
        """
        미처리 HITL 요청을 DB에 저장
        
        Args:
            call_id: 통화 ID
            question: 사용자 질문
            context: 대화 컨텍스트
            
        Returns:
            request_id: 생성된 요청 ID
        """
        request_id = str(uuid4())
        
        unresolved_request = {
            "request_id": request_id,
            "call_id": call_id,
            "caller_id": context.get('caller_id'),
            "callee_id": context.get('callee_id'),
            "user_question": question,
            "conversation_history": json.dumps(context.get('conversation_history', [])),
            "rag_results": json.dumps(context.get('rag_results', [])),
            "ai_confidence": context.get('ai_confidence', 0.0),
            "timestamp": datetime.now(),
            "status": "unresolved"
        }
        
        # PostgreSQL에 저장
        if self.db:
            try:
                await self.db.execute(
                    """
                    INSERT INTO unresolved_hitl_requests
                    (request_id, call_id, caller_id, callee_id, user_question,
                     conversation_history, rag_results, ai_confidence, timestamp, status)
                    VALUES (:request_id, :call_id, :caller_id, :callee_id, :user_question,
                            :conversation_history, :rag_results, :ai_confidence, :timestamp, :status)
                    """,
                    unresolved_request
                )
                logger.info("Unresolved HITL request saved to DB", request_id=request_id)
            except Exception as e:
                logger.error("Failed to save unresolved HITL request to DB", 
                           request_id=request_id, error=str(e))
        
        # Redis 큐에 추가
        if self.redis_client:
            try:
                await self.redis_client.lpush("unresolved_hitl_queue", request_id)
                logger.info("Unresolved HITL request added to Redis queue", request_id=request_id)
            except Exception as e:
                logger.error("Failed to add unresolved HITL request to Redis queue", error=str(e))
        
        logger.info("Unresolved HITL request saved", 
                   request_id=request_id,
                   call_id=call_id,
                   caller_id=context.get('caller_id'))
        
        return request_id


# 싱글톤 인스턴스 (추후 main.py에서 초기화)
_hitl_service_instance: Optional[HITLService] = None


def get_hitl_service() -> HITLService:
    """HITL Service 싱글톤 인스턴스 반환"""
    global _hitl_service_instance
    if _hitl_service_instance is None:
        _hitl_service_instance = HITLService()
    return _hitl_service_instance


def initialize_hitl_service(
    redis_client=None,
    websocket_manager=None,
    db=None,
    timeout_seconds: int = 60,
    timeout_message: Optional[str] = None,
):
    """HITL Service 초기화"""
    global _hitl_service_instance
    _hitl_service_instance = HITLService(
        redis_client=redis_client,
        websocket_manager=websocket_manager,
        db=db,
        timeout_seconds=timeout_seconds,
        timeout_message=timeout_message,
    )
    return _hitl_service_instance

