"""Human-in-the-Loop Service"""
import asyncio
import json
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from uuid import uuid4
from enum import Enum
import structlog

logger = structlog.get_logger(__name__)


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
    
    def __init__(self, redis_client=None, websocket_manager=None, db=None):
        """
        Args:
            redis_client: Redis 클라이언트
            websocket_manager: WebSocket 관리자
            db: Database 클라이언트 (PostgreSQL)
        """
        self.redis_client = redis_client
        self.websocket_manager = websocket_manager
        self.db = db
        
        # Mock 저장소 (Redis 대체)
        self.hitl_requests: Dict[str, Dict[str, Any]] = {}
        
        logger.info("HITLService initialized")
    
    async def request_human_help(
        self,
        call_id: str,
        question: str,
        context: Dict[str, Any],
        urgency: str = 'medium',
        timeout_seconds: int = 300  # 5분
    ) -> bool:
        """
        AI가 사람의 도움을 요청
        
        Args:
            call_id: 통화 ID
            question: 사용자 질문
            context: 대화 컨텍스트 (이전 메시지, RAG 결과, 발신자 정보)
            urgency: 긴급도 (high/medium/low)
            timeout_seconds: 타임아웃 (초)
            
        Returns:
            True: HITL 요청 성공 (운영자 대기 중)
            False: HITL 요청 거절 (운영자 부재중/오프라인)
        """
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
                   call_id=call_id,
                   question=question,
                   urgency=urgency,
                   timeout_at=timeout_at.isoformat())
        
        return True
    
    async def _handle_timeout(self, call_id: str, timeout_seconds: int):
        """
        HITL 타임아웃 처리
        
        타임아웃 시간 후에도 답변이 없으면 기본 응답 반환
        """
        await asyncio.sleep(timeout_seconds)
        
        # 아직 답변되지 않았는지 확인
        if call_id in self.hitl_requests:
            request = self.hitl_requests[call_id]
            if request.get('status') == 'pending':
                logger.warning("HITL request timed out", call_id=call_id)
                
                # Frontend에 타임아웃 알림
                if self.websocket_manager:
                    await self.websocket_manager.broadcast_global('hitl_timeout', {
                        'call_id': call_id,
                        'timestamp': datetime.now().isoformat()
                    })
                
                # TODO: AI Orchestrator에 타임아웃 알림
                # await orchestrator.handle_hitl_timeout(call_id)
                
                # 요청 삭제
                del self.hitl_requests[call_id]
    
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
            # await knowledge_service.add_from_hitl(
            #     question=request['question'],
            #     answer=response_text,
            #     category=category or 'faq'
            # )
        
        # Redis에서 요청 삭제
        if self.redis_client:
            try:
                await self.redis_client.delete(f"hitl:{call_id}")
            except Exception as e:
                logger.error("Failed to delete HITL request from Redis", error=str(e))
        
        if call_id in self.hitl_requests:
            del self.hitl_requests[call_id]
        
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


def initialize_hitl_service(redis_client=None, websocket_manager=None, db=None):
    """HITL Service 초기화"""
    global _hitl_service_instance
    _hitl_service_instance = HITLService(
        redis_client=redis_client,
        websocket_manager=websocket_manager,
        db=db
    )
    return _hitl_service_instance

