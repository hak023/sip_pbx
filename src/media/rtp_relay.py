"""RTP Relay Worker

RTP/RTCP 패킷 relay (Bypass Mode)
"""

import asyncio
from typing import Optional, Tuple
from dataclasses import dataclass

from src.media.rtp_packet import RTPParser, RTCPPacket
from src.media.media_session import MediaSession
from src.common.logger import get_logger

logger = get_logger(__name__)


@dataclass
class RTPEndpoint:
    """RTP 엔드포인트 (IP:Port)"""
    ip: str
    port: int
    
    def __repr__(self) -> str:
        return f"{self.ip}:{self.port}"


class RTPRelayWorker:
    """RTP Relay Worker
    
    Bypass 모드: RTP 패킷을 단순 relay
    """
    
    def __init__(
        self,
        media_session: MediaSession,
        caller_endpoint: RTPEndpoint,
        callee_endpoint: RTPEndpoint,
        ai_orchestrator = None,  # AI Orchestrator (optional)
    ):
        """초기화
        
        Args:
            media_session: 미디어 세션
            caller_endpoint: Caller의 RTP 엔드포인트
            callee_endpoint: Callee의 RTP 엔드포인트
            ai_orchestrator: AI Orchestrator (AI 모드용, optional)
        """
        self.media_session = media_session
        self.caller_endpoint = caller_endpoint
        self.callee_endpoint = callee_endpoint
        
        # AI 보이스봇 지원
        self.ai_orchestrator = ai_orchestrator
        self.ai_mode = False
        
        # UDP 소켓들 (각 포트별)
        self.caller_audio_transport: Optional[asyncio.DatagramTransport] = None
        self.caller_video_transport: Optional[asyncio.DatagramTransport] = None
        self.callee_audio_transport: Optional[asyncio.DatagramTransport] = None
        self.callee_video_transport: Optional[asyncio.DatagramTransport] = None
        
        # 프로토콜 인스턴스들
        self.protocols: dict = {}
        
        # 실행 중 플래그
        self.running = False
        
        # 통계
        self.stats = {
            "caller_audio_packets": 0,
            "caller_video_packets": 0,
            "callee_audio_packets": 0,
            "callee_video_packets": 0,
            "total_bytes_relayed": 0,
            "ai_packets": 0,  # AI로 전달된 패킷 수
        }
        
        logger.info("rtp_relay_worker_created",
                   call_id=media_session.call_id,
                   caller=str(caller_endpoint),
                   callee=str(callee_endpoint),
                   ai_enabled=ai_orchestrator is not None)
    
    async def start(self) -> None:
        """Relay 시작 (소켓 바인딩 및 수신 대기)"""
        if self.running:
            logger.warning("rtp_relay_already_running", call_id=self.media_session.call_id)
            return
        
        self.running = True
        loop = asyncio.get_event_loop()
        
        # Caller Audio RTP/RTCP
        caller_audio_rtp_port = self.media_session.caller_leg.get_audio_rtp_port()
        caller_audio_rtcp_port = self.media_session.caller_leg.get_audio_rtcp_port()
        
        # Callee Audio RTP/RTCP
        callee_audio_rtp_port = self.media_session.callee_leg.get_audio_rtp_port()
        callee_audio_rtcp_port = self.media_session.callee_leg.get_audio_rtcp_port()
        
        # Caller Audio RTP 소켓
        if caller_audio_rtp_port:
            protocol = RTPRelayProtocol(
                self,
                "caller_audio_rtp",
                self.callee_endpoint,
                callee_audio_rtp_port
            )
            transport, _ = await loop.create_datagram_endpoint(
                lambda: protocol,
                local_addr=("0.0.0.0", caller_audio_rtp_port)
            )
            self.caller_audio_transport = transport
            self.protocols["caller_audio_rtp"] = protocol
            
            logger.info("rtp_socket_bound",
                       call_id=self.media_session.call_id,
                       type="caller_audio_rtp",
                       port=caller_audio_rtp_port)
        
        # Caller Audio RTCP 소켓
        if caller_audio_rtcp_port:
            protocol = RTPRelayProtocol(
                self,
                "caller_audio_rtcp",
                self.callee_endpoint,
                callee_audio_rtcp_port
            )
            transport, _ = await loop.create_datagram_endpoint(
                lambda: protocol,
                local_addr=("0.0.0.0", caller_audio_rtcp_port)
            )
            self.protocols["caller_audio_rtcp"] = protocol
        
        # Callee Audio RTP 소켓
        if callee_audio_rtp_port:
            protocol = RTPRelayProtocol(
                self,
                "callee_audio_rtp",
                self.caller_endpoint,
                caller_audio_rtp_port
            )
            transport, _ = await loop.create_datagram_endpoint(
                lambda: protocol,
                local_addr=("0.0.0.0", callee_audio_rtp_port)
            )
            self.callee_audio_transport = transport
            self.protocols["callee_audio_rtp"] = protocol
            
            logger.info("rtp_socket_bound",
                       call_id=self.media_session.call_id,
                       type="callee_audio_rtp",
                       port=callee_audio_rtp_port)
        
        # Callee Audio RTCP 소켓
        if callee_audio_rtcp_port:
            protocol = RTPRelayProtocol(
                self,
                "callee_audio_rtcp",
                self.caller_endpoint,
                caller_audio_rtcp_port
            )
            transport, _ = await loop.create_datagram_endpoint(
                lambda: protocol,
                local_addr=("0.0.0.0", callee_audio_rtcp_port)
            )
            self.protocols["callee_audio_rtcp"] = protocol
        
        logger.info("rtp_relay_started",
                   call_id=self.media_session.call_id,
                   sockets_bound=len(self.protocols))
    
    async def stop(self) -> None:
        """Relay 중지 (소켓 닫기)"""
        if not self.running:
            return
        
        self.running = False
        
        # 모든 transport 닫기
        if self.caller_audio_transport:
            self.caller_audio_transport.close()
        if self.caller_video_transport:
            self.caller_video_transport.close()
        if self.callee_audio_transport:
            self.callee_audio_transport.close()
        if self.callee_video_transport:
            self.callee_video_transport.close()
        
        logger.info("rtp_relay_stopped",
                   call_id=self.media_session.call_id,
                   stats=self.stats)
    
    def on_packet_received(
        self,
        socket_type: str,
        data: bytes,
        addr: Tuple[str, int]
    ) -> None:
        """패킷 수신 콜백
        
        Args:
            socket_type: 소켓 타입 (caller_audio_rtp 등)
            data: 패킷 데이터
            addr: 송신자 주소
        """
        # 통계 업데이트
        if "caller" in socket_type:
            if "audio" in socket_type:
                self.stats["caller_audio_packets"] += 1
            elif "video" in socket_type:
                self.stats["caller_video_packets"] += 1
        else:
            if "audio" in socket_type:
                self.stats["callee_audio_packets"] += 1
            elif "video" in socket_type:
                self.stats["callee_video_packets"] += 1
        
        self.stats["total_bytes_relayed"] += len(data)
        
        # AI 모드일 경우 AI Orchestrator로 패킷 전달
        if self.ai_mode and self.ai_orchestrator:
            # Caller의 오디오 패킷만 AI로 전달 (AI가 Callee 역할)
            if socket_type == "caller_audio_rtp":
                try:
                    # 비동기 태스크로 AI에 패킷 전달
                    asyncio.create_task(
                        self.ai_orchestrator.on_audio_packet(data, direction="caller")
                    )
                    self.stats["ai_packets"] += 1
                except Exception as e:
                    logger.error("ai_packet_forward_error",
                               call_id=self.media_session.call_id,
                               error=str(e))
        
        # 미디어 세션 RTP 수신 기록
        from_caller = "caller" in socket_type
        self.media_session.update_rtp_received(from_caller)
    
    def set_ai_mode(self, enabled: bool = True):
        """
        AI 모드 활성화/비활성화
        
        Args:
            enabled: AI 모드 활성화 여부
        """
        self.ai_mode = enabled
        logger.info("ai_mode_changed",
                   call_id=self.media_session.call_id,
                   ai_mode=enabled)
    
    def send_ai_audio(self, audio_data: bytes):
        """
        AI에서 생성한 오디오를 Caller에게 전송
        
        Args:
            audio_data: 오디오 데이터 (AI가 생성한 TTS 음성)
        """
        if not self.ai_mode:
            logger.warning("not_in_ai_mode",
                         call_id=self.media_session.call_id)
            return
        
        # Callee Audio RTP transport를 통해 Caller에게 전송
        if self.callee_audio_transport:
            try:
                # RTP 패킷으로 포장하여 전송 (간단한 구현)
                # 실제로는 RTP 헤더를 추가해야 하지만, 여기서는 단순화
                caller_audio_port = self.media_session.caller_leg.get_audio_rtp_port()
                self.callee_audio_transport.sendto(
                    audio_data,
                    (self.caller_endpoint.ip, caller_audio_port)
                )
            except Exception as e:
                logger.error("ai_audio_send_error",
                           call_id=self.media_session.call_id,
                           error=str(e))
    
    def get_stats(self) -> dict:
        """통계 정보 반환
        
        Returns:
            통계 딕셔너리
        """
        stats = self.stats.copy()
        stats["ai_mode"] = self.ai_mode
        return stats


class RTPRelayProtocol(asyncio.DatagramProtocol):
    """RTP Relay UDP 프로토콜
    
    asyncio DatagramProtocol 구현
    """
    
    def __init__(
        self,
        relay_worker: RTPRelayWorker,
        socket_type: str,
        remote_endpoint: RTPEndpoint,
        remote_port: int,
    ):
        """초기화
        
        Args:
            relay_worker: RTP Relay Worker
            socket_type: 소켓 타입
            remote_endpoint: 원격 엔드포인트
            remote_port: 원격 포트
        """
        self.relay_worker = relay_worker
        self.socket_type = socket_type
        self.remote_endpoint = remote_endpoint
        self.remote_port = remote_port
        self.transport: Optional[asyncio.DatagramTransport] = None
    
    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        """연결 생성 (소켓 바인딩 완료)
        
        Args:
            transport: UDP transport
        """
        self.transport = transport
    
    def datagram_received(self, data: bytes, addr: Tuple[str, int]) -> None:
        """데이터그램 수신 (패킷 수신)
        
        Args:
            data: 패킷 데이터
            addr: 송신자 주소 (IP, Port)
        """
        if not self.relay_worker.running:
            return
        
        # 패킷을 그대로 원격 엔드포인트로 전달
        if self.transport:
            try:
                self.transport.sendto(data, (self.remote_endpoint.ip, self.remote_port))
                
                # 콜백 호출
                self.relay_worker.on_packet_received(self.socket_type, data, addr)
                
            except Exception as e:
                logger.error("rtp_relay_send_error",
                           call_id=self.relay_worker.media_session.call_id,
                           socket_type=self.socket_type,
                           error=str(e))
    
    def error_received(self, exc: Exception) -> None:
        """에러 수신
        
        Args:
            exc: 예외
        """
        logger.error("rtp_relay_error",
                    call_id=self.relay_worker.media_session.call_id,
                    socket_type=self.socket_type,
                    error=str(exc))
    
    def connection_lost(self, exc: Optional[Exception]) -> None:
        """연결 종료
        
        Args:
            exc: 예외 (있을 경우)
        """
        if exc:
            logger.warning("rtp_relay_connection_lost",
                          call_id=self.relay_worker.media_session.call_id,
                          socket_type=self.socket_type,
                          error=str(exc))

