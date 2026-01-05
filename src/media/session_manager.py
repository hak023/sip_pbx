"""Media Session Manager

미디어 세션 생명주기 관리
"""

from typing import Dict, Optional, List
from threading import RLock

from src.media.media_session import MediaSession, MediaLeg, MediaMode
from src.media.sdp_parser import SDPParser
from src.media.port_pool import PortPoolManager
from src.common.logger import get_logger

logger = get_logger(__name__)


class MediaSessionManager:
    """미디어 세션 관리자
    
    미디어 세션 생성, 조회, 삭제 및 포트 풀 통합
    """
    
    def __init__(self, port_pool: PortPoolManager, default_mode: MediaMode = MediaMode.REFLECTING):
        """초기화
        
        Args:
            port_pool: 포트 풀 관리자
            default_mode: 기본 미디어 처리 모드
        """
        self.port_pool = port_pool
        self.default_mode = default_mode
        
        self._sessions: Dict[str, MediaSession] = {}
        self._lock = RLock()
        
        logger.info("media_session_manager_initialized",
                   default_mode=default_mode.value)
    
    def create_session(
        self,
        call_id: str,
        caller_sdp: str,
        mode: Optional[MediaMode] = None,
    ) -> MediaSession:
        """미디어 세션 생성
        
        Args:
            call_id: 통화 ID
            caller_sdp: Caller의 SDP
            mode: 미디어 처리 모드 (None이면 기본값 사용)
            
        Returns:
            생성된 MediaSession
            
        Raises:
            ValueError: 이미 존재하는 call_id
            PortPoolExhaustedError: 포트 부족
        """
        with self._lock:
            if call_id in self._sessions:
                raise ValueError(f"Media session already exists: {call_id}")
            
            # 포트 할당 (8개)
            allocated_ports = self.port_pool.allocate_ports(call_id)
            
            # Caller SDP 파싱
            caller_sdp_obj = SDPParser.parse(caller_sdp)
            
            # Caller Leg 생성 (미디어 레벨 connection IP 우선 - RFC 4566)
            caller_leg = MediaLeg(
                original_sdp=caller_sdp_obj,
                original_ip=caller_sdp_obj.get_audio_connection_ip(),
                original_audio_port=caller_sdp_obj.get_audio_port(),
                original_video_port=caller_sdp_obj.get_video_port(),
                allocated_ports=allocated_ports[:4],  # 앞 4개
            )
            
            # Callee Leg 생성 (포트만 할당, SDP는 나중에)
            callee_leg = MediaLeg(
                allocated_ports=allocated_ports[4:8],  # 뒤 4개
            )
            
            # MediaSession 생성
            session = MediaSession(
                call_id=call_id,
                caller_leg=caller_leg,
                callee_leg=callee_leg,
                mode=mode if mode else self.default_mode,
            )
            
            self._sessions[call_id] = session
            
            logger.info("media_session_created",
                       call_id=call_id,
                       mode=session.mode.value,
                       caller_ports=caller_leg.allocated_ports,
                       callee_ports=callee_leg.allocated_ports,
                       has_audio=caller_sdp_obj.has_audio(),
                       has_video=caller_sdp_obj.has_video())
            
            return session
    
    def update_callee_sdp(self, call_id: str, callee_sdp: str) -> None:
        """Callee SDP 업데이트 (200 OK 수신 시)
        
        Args:
            call_id: 통화 ID
            callee_sdp: Callee의 SDP
            
        Raises:
            ValueError: 세션이 존재하지 않음
        """
        with self._lock:
            session = self._sessions.get(call_id)
            if not session:
                raise ValueError(f"Media session not found: {call_id}")
            
            # Callee SDP 파싱
            callee_sdp_obj = SDPParser.parse(callee_sdp)
            
            # Callee Leg 업데이트 (미디어 레벨 connection IP 우선 - RFC 4566)
            session.callee_leg.original_sdp = callee_sdp_obj
            session.callee_leg.original_ip = callee_sdp_obj.get_audio_connection_ip()
            session.callee_leg.original_audio_port = callee_sdp_obj.get_audio_port()
            session.callee_leg.original_video_port = callee_sdp_obj.get_video_port()
            
            logger.info("callee_sdp_updated",
                       call_id=call_id,
                       callee_ip=callee_sdp_obj.get_audio_connection_ip(),
                       audio_port=callee_sdp_obj.get_audio_port())
    
    def get_session(self, call_id: str) -> Optional[MediaSession]:
        """세션 조회
        
        Args:
            call_id: 통화 ID
            
        Returns:
            MediaSession 또는 None
        """
        with self._lock:
            return self._sessions.get(call_id)
    
    def destroy_session(self, call_id: str) -> bool:
        """세션 종료 및 포트 반환
        
        Args:
            call_id: 통화 ID
            
        Returns:
            성공 여부
        """
        with self._lock:
            session = self._sessions.pop(call_id, None)
            
            if not session:
                logger.warning("media_session_not_found_for_destroy", call_id=call_id)
                return False
            
            # 세션 종료 마킹
            session.mark_ended()
            
            # 포트 반환
            released = self.port_pool.release_ports(call_id)
            
            logger.info("media_session_destroyed",
                       call_id=call_id,
                       duration=session.get_duration_seconds(),
                       ports_released=released)
            
            return True
    
    def get_active_sessions(self) -> List[MediaSession]:
        """활성 세션 리스트
        
        Returns:
            활성 MediaSession 리스트
        """
        with self._lock:
            return [s for s in self._sessions.values() if s.is_active()]
    
    def get_session_count(self) -> int:
        """전체 세션 수
        
        Returns:
            세션 개수
        """
        with self._lock:
            return len(self._sessions)
    
    def check_timeouts(self, timeout_seconds: int = 60) -> List[str]:
        """타임아웃된 세션 검사
        
        Args:
            timeout_seconds: 타임아웃 시간 (초)
            
        Returns:
            타임아웃된 call_id 리스트
        """
        timed_out_calls = []
        
        with self._lock:
            for call_id, session in self._sessions.items():
                if not session.is_active():
                    continue
                
                seconds_since = session.get_seconds_since_last_rtp()
                
                # RTP를 한번도 받지 못했거나, 타임아웃 초과
                if seconds_since is None or seconds_since >= timeout_seconds:
                    timed_out_calls.append(call_id)
                    
                    logger.warning("media_session_timeout",
                                 call_id=call_id,
                                 seconds_since_last_rtp=seconds_since,
                                 timeout_threshold=timeout_seconds)
        
        return timed_out_calls
    
    def update_rtp_received(self, call_id: str, from_caller: bool) -> bool:
        """RTP 수신 기록
        
        Args:
            call_id: 통화 ID
            from_caller: caller로부터의 RTP 여부
            
        Returns:
            성공 여부
        """
        with self._lock:
            session = self._sessions.get(call_id)
            if not session:
                return False
            
            session.update_rtp_received(from_caller)
            return True
    
    def get_stats(self) -> Dict[str, any]:
        """통계 정보
        
        Returns:
            통계 딕셔너리
        """
        with self._lock:
            active_count = len([s for s in self._sessions.values() if s.is_active()])
            
            return {
                "total_sessions": len(self._sessions),
                "active_sessions": active_count,
                "port_utilization": self.port_pool.get_utilization(),
                "max_concurrent_calls": self.port_pool.get_max_concurrent_calls(),
            }

