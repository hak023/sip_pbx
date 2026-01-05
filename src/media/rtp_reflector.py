"""RTP Reflector

RTP 패킷을 relay하면서 동시에 AI 분석 큐로 전송
"""

import asyncio
from typing import Optional, Tuple
from dataclasses import dataclass
from datetime import datetime

from src.media.rtp_packet import RTPParser, RTPPacket, RTCPPacket
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


@dataclass
class AudioPacket:
    """AI 분석용 오디오 패킷
    
    RTP 패킷에서 추출한 정보
    """
    call_id: str
    from_caller: bool  # True: caller → callee, False: callee → caller
    rtp_packet: RTPPacket
    received_at: datetime
    
    def get_payload(self) -> bytes:
        """Payload 반환"""
        return self.rtp_packet.payload
    
    def get_ssrc(self) -> int:
        """SSRC 반환"""
        return self.rtp_packet.header.ssrc
    
    def get_timestamp(self) -> int:
        """RTP Timestamp 반환"""
        return self.rtp_packet.header.timestamp
    
    def get_sequence(self) -> int:
        """Sequence Number 반환"""
        return self.rtp_packet.header.sequence_number
    
    def get_payload_type(self) -> int:
        """Payload Type (코덱 타입) 반환"""
        return self.rtp_packet.header.payload_type


class RTPReflector:
    """RTP Reflector
    
    Reflecting 모드: RTP 패킷을 relay하면서 동시에 분석 큐로 전송
    """
    
    def __init__(
        self,
        media_session: MediaSession,
        caller_endpoint: RTPEndpoint,
        callee_endpoint: RTPEndpoint,
        analysis_queue: Optional[asyncio.Queue] = None,
        max_queue_size: int = 1000,
    ):
        """초기화
        
        Args:
            media_session: 미디어 세션
            caller_endpoint: Caller의 RTP 엔드포인트
            callee_endpoint: Callee의 RTP 엔드포인트
            analysis_queue: AI 분석용 큐 (None이면 자동 생성)
            max_queue_size: 분석 큐 최대 크기
        """
        self.media_session = media_session
        self.caller_endpoint = caller_endpoint
        self.callee_endpoint = callee_endpoint
        
        # 분석 큐 (AI 파이프라인용)
        self.analysis_queue = analysis_queue or asyncio.Queue(maxsize=max_queue_size)
        self.max_queue_size = max_queue_size
        
        # UDP 소켓들
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
            "packets_queued_for_analysis": 0,
            "queue_full_drops": 0,
            "parse_errors": 0,
        }
        
        logger.info("rtp_reflector_created",
                   call_id=media_session.call_id,
                   caller=str(caller_endpoint),
                   callee=str(callee_endpoint),
                   max_queue_size=max_queue_size)
    
    async def start(self) -> None:
        """Reflector 시작 (소켓 바인딩 및 수신 대기)"""
        if self.running:
            logger.warning("rtp_reflector_already_running", call_id=self.media_session.call_id)
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
            protocol = RTPReflectorProtocol(
                self,
                "caller_audio_rtp",
                self.callee_endpoint,
                callee_audio_rtp_port,
                is_rtcp=False,
                from_caller=True,
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
            protocol = RTPReflectorProtocol(
                self,
                "caller_audio_rtcp",
                self.callee_endpoint,
                callee_audio_rtcp_port,
                is_rtcp=True,
                from_caller=True,
            )
            transport, _ = await loop.create_datagram_endpoint(
                lambda: protocol,
                local_addr=("0.0.0.0", caller_audio_rtcp_port)
            )
            self.protocols["caller_audio_rtcp"] = protocol
        
        # Callee Audio RTP 소켓
        if callee_audio_rtp_port:
            protocol = RTPReflectorProtocol(
                self,
                "callee_audio_rtp",
                self.caller_endpoint,
                caller_audio_rtp_port,
                is_rtcp=False,
                from_caller=False,
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
            protocol = RTPReflectorProtocol(
                self,
                "callee_audio_rtcp",
                self.caller_endpoint,
                caller_audio_rtcp_port,
                is_rtcp=True,
                from_caller=False,
            )
            transport, _ = await loop.create_datagram_endpoint(
                lambda: protocol,
                local_addr=("0.0.0.0", callee_audio_rtcp_port)
            )
            self.protocols["callee_audio_rtcp"] = protocol
        
        logger.info("rtp_reflector_started",
                   call_id=self.media_session.call_id,
                   sockets_bound=len(self.protocols))
    
    async def stop(self) -> None:
        """Reflector 중지 (소켓 닫기)"""
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
        
        logger.info("rtp_reflector_stopped",
                   call_id=self.media_session.call_id,
                   stats=self.stats)
    
    def on_packet_received(
        self,
        socket_type: str,
        data: bytes,
        addr: Tuple[str, int],
        is_rtcp: bool,
        from_caller: bool,
    ) -> None:
        """패킷 수신 콜백
        
        Args:
            socket_type: 소켓 타입
            data: 패킷 데이터
            addr: 송신자 주소
            is_rtcp: RTCP 패킷 여부
            from_caller: caller로부터의 패킷 여부
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
        
        # 미디어 세션 RTP 수신 기록
        self.media_session.update_rtp_received(from_caller)
        
        # RTP 패킷만 분석 큐로 전송 (RTCP는 제외)
        if not is_rtcp and "audio" in socket_type:
            self._queue_for_analysis(data, from_caller)
    
    def _queue_for_analysis(self, data: bytes, from_caller: bool) -> None:
        """RTP 패킷을 분석 큐로 전송
        
        Args:
            data: RTP 패킷 데이터
            from_caller: caller로부터의 패킷 여부
        """
        try:
            # RTP 패킷 파싱
            if not RTPParser.is_valid_rtp(data):
                logger.warning("invalid_rtp_packet",
                             call_id=self.media_session.call_id,
                             size=len(data))
                self.stats["parse_errors"] += 1
                return
            
            rtp_packet = RTPParser.parse(data)
            
            # RTCP 패킷은 제외
            if rtp_packet.is_rtcp():
                return
            
            # AudioPacket 생성
            audio_packet = AudioPacket(
                call_id=self.media_session.call_id,
                from_caller=from_caller,
                rtp_packet=rtp_packet,
                received_at=datetime.utcnow(),
            )
            
            # 큐에 추가 (non-blocking)
            try:
                self.analysis_queue.put_nowait(audio_packet)
                self.stats["packets_queued_for_analysis"] += 1
                
            except asyncio.QueueFull:
                # 큐가 가득 찬 경우 드롭
                self.stats["queue_full_drops"] += 1
                
                # 주기적으로 경고 로그 (100번마다)
                if self.stats["queue_full_drops"] % 100 == 1:
                    logger.warning("analysis_queue_full",
                                 call_id=self.media_session.call_id,
                                 drops=self.stats["queue_full_drops"])
        
        except Exception as e:
            logger.error("rtp_parsing_error",
                        call_id=self.media_session.call_id,
                        error=str(e))
            self.stats["parse_errors"] += 1
    
    def get_stats(self) -> dict:
        """통계 정보 반환
        
        Returns:
            통계 딕셔너리
        """
        return self.stats.copy()
    
    def get_queue_size(self) -> int:
        """현재 분석 큐 크기
        
        Returns:
            큐에 있는 패킷 수
        """
        return self.analysis_queue.qsize()


class RTPReflectorProtocol(asyncio.DatagramProtocol):
    """RTP Reflector UDP 프로토콜
    
    asyncio DatagramProtocol 구현
    """
    
    def __init__(
        self,
        reflector: RTPReflector,
        socket_type: str,
        remote_endpoint: RTPEndpoint,
        remote_port: int,
        is_rtcp: bool,
        from_caller: bool,
    ):
        """초기화
        
        Args:
            reflector: RTP Reflector
            socket_type: 소켓 타입
            remote_endpoint: 원격 엔드포인트
            remote_port: 원격 포트
            is_rtcp: RTCP 패킷 여부
            from_caller: caller로부터의 패킷 여부
        """
        self.reflector = reflector
        self.socket_type = socket_type
        self.remote_endpoint = remote_endpoint
        self.remote_port = remote_port
        self.is_rtcp = is_rtcp
        self.from_caller = from_caller
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
        if not self.reflector.running:
            return
        
        # 1. 패킷을 그대로 원격 엔드포인트로 전달 (relay)
        if self.transport:
            try:
                self.transport.sendto(data, (self.remote_endpoint.ip, self.remote_port))
                
                # 2. 콜백 호출 (분석 큐로 전송)
                self.reflector.on_packet_received(
                    self.socket_type,
                    data,
                    addr,
                    self.is_rtcp,
                    self.from_caller,
                )
                
            except Exception as e:
                logger.error("rtp_reflector_send_error",
                           call_id=self.reflector.media_session.call_id,
                           socket_type=self.socket_type,
                           error=str(e))
    
    def error_received(self, exc: Exception) -> None:
        """에러 수신
        
        Args:
            exc: 예외
        """
        logger.error("rtp_reflector_error",
                    call_id=self.reflector.media_session.call_id,
                    socket_type=self.socket_type,
                    error=str(exc))
    
    def connection_lost(self, exc: Optional[Exception]) -> None:
        """연결 종료
        
        Args:
            exc: 예외 (있을 경우)
        """
        if exc:
            logger.warning("rtp_reflector_connection_lost",
                          call_id=self.reflector.media_session.call_id,
                          socket_type=self.socket_type,
                          error=str(exc))

