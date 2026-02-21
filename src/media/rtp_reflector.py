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
        bind_ip: str = "0.0.0.0",  # RTP 소켓을 bind할 IP
        analysis_queue: Optional[asyncio.Queue] = None,
        max_queue_size: int = 1000,
    ):
        """초기화
        
        Args:
            media_session: 미디어 세션
            caller_endpoint: Caller의 RTP 엔드포인트
            callee_endpoint: Callee의 RTP 엔드포인트
            bind_ip: RTP 소켓을 bind할 IP 주소
            analysis_queue: AI 분석용 큐 (None이면 자동 생성)
            max_queue_size: 분석 큐 최대 크기
        """
        self.media_session = media_session
        self.caller_endpoint = caller_endpoint
        self.callee_endpoint = callee_endpoint
        self.bind_ip = bind_ip  # Bind IP 저장
        
        # RTCP 엔드포인트 (MediaSession에서 RTCP 포트 가져오기)
        self.caller_rtcp_endpoint = RTPEndpoint(
            ip=caller_endpoint.ip,
            port=media_session.caller_leg.original_audio_rtcp_port or (caller_endpoint.port + 1)
        )
        self.callee_rtcp_endpoint = RTPEndpoint(
            ip=callee_endpoint.ip,
            port=media_session.callee_leg.original_audio_rtcp_port or (callee_endpoint.port + 1)
        )
        
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
            try:
                protocol = RTPReflectorProtocol(
                    self,
                    "caller_audio_rtp",
                    self.callee_endpoint,
                    self.callee_endpoint.port,  # ✅ 클라이언트의 실제 RTP 포트
                    is_rtcp=False,
                    from_caller=True,
                )
                transport, _ = await loop.create_datagram_endpoint(
                    lambda: protocol,
                    local_addr=(self.bind_ip, caller_audio_rtp_port)
                )
                self.caller_audio_transport = transport
                self.protocols["caller_audio_rtp"] = protocol
                
                logger.info("rtp_socket_bound",
                           call_id=self.media_session.call_id,
                           type="caller_audio_rtp",
                           bind_ip=self.bind_ip,
                           port=caller_audio_rtp_port)
            except Exception as e:
                logger.error("rtp_socket_bind_failed",
                           call_id=self.media_session.call_id,
                           type="caller_audio_rtp",
                           bind_ip=self.bind_ip,
                           port=caller_audio_rtp_port,
                           error=str(e))
        
        # Caller Audio RTCP 소켓
        if caller_audio_rtcp_port:
            try:
                protocol = RTPReflectorProtocol(
                    self,
                    "caller_audio_rtcp",
                    self.callee_rtcp_endpoint,  # ✅ Callee의 RTCP 엔드포인트
                    self.callee_rtcp_endpoint.port,
                    is_rtcp=True,
                    from_caller=True,
                )
                transport, _ = await loop.create_datagram_endpoint(
                    lambda: protocol,
                    local_addr=(self.bind_ip, caller_audio_rtcp_port)
                )
                self.protocols["caller_audio_rtcp"] = protocol
                
                logger.info("rtp_socket_bound",
                           call_id=self.media_session.call_id,
                           type="caller_audio_rtcp",
                           bind_ip=self.bind_ip,
                           port=caller_audio_rtcp_port)
            except Exception as e:
                logger.error("rtp_socket_bind_failed",
                           call_id=self.media_session.call_id,
                           type="caller_audio_rtcp",
                           bind_ip=self.bind_ip,
                           port=caller_audio_rtcp_port,
                           error=str(e))
        
        # Callee Audio RTP 소켓
        if callee_audio_rtp_port:
            try:
                protocol = RTPReflectorProtocol(
                    self,
                    "callee_audio_rtp",
                    self.caller_endpoint,
                    self.caller_endpoint.port,  # ✅ 클라이언트의 실제 RTP 포트
                    is_rtcp=False,
                    from_caller=False,
                )
                transport, _ = await loop.create_datagram_endpoint(
                    lambda: protocol,
                    local_addr=(self.bind_ip, callee_audio_rtp_port)
                )
                self.callee_audio_transport = transport
                self.protocols["callee_audio_rtp"] = protocol
                
                logger.info("rtp_socket_bound",
                           call_id=self.media_session.call_id,
                           type="callee_audio_rtp",
                           bind_ip=self.bind_ip,
                           port=callee_audio_rtp_port)
            except Exception as e:
                logger.error("rtp_socket_bind_failed",
                           call_id=self.media_session.call_id,
                           type="callee_audio_rtp",
                           bind_ip=self.bind_ip,
                           port=callee_audio_rtp_port,
                           error=str(e))
        
        # Callee Audio RTCP 소켓
        if callee_audio_rtcp_port:
            try:
                protocol = RTPReflectorProtocol(
                    self,
                    "callee_audio_rtcp",
                    self.caller_rtcp_endpoint,  # ✅ Caller의 RTCP 엔드포인트
                    self.caller_rtcp_endpoint.port,
                    is_rtcp=True,
                    from_caller=False,
                )
                transport, _ = await loop.create_datagram_endpoint(
                    lambda: protocol,
                    local_addr=(self.bind_ip, callee_audio_rtcp_port)
                )
                self.protocols["callee_audio_rtcp"] = protocol
                
                logger.info("rtp_socket_bound",
                           call_id=self.media_session.call_id,
                           type="callee_audio_rtcp",
                           bind_ip=self.bind_ip,
                           port=callee_audio_rtcp_port)
            except Exception as e:
                logger.error("rtp_socket_bind_failed",
                           call_id=self.media_session.call_id,
                           type="callee_audio_rtcp",
                           bind_ip=self.bind_ip,
                           port=callee_audio_rtcp_port,
                           error=str(e))
        
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
    
    def update_callee_endpoint(self, callee_ip: str, callee_rtp_port: int, callee_rtcp_port: int) -> None:
        """Callee Endpoint 업데이트 (200 OK 수신 후)
        
        Early Bind 시나리오: INVITE 시점에 bind는 완료했지만, 
        Callee의 실제 IP/Port는 200 OK에서 받기 때문에 나중에 업데이트
        
        Args:
            callee_ip: Callee의 실제 IP
            callee_rtp_port: Callee의 실제 RTP 포트
            callee_rtcp_port: Callee의 실제 RTCP 포트 (명시적 또는 RTP+1)
        """
        self.callee_endpoint = RTPEndpoint(ip=callee_ip, port=callee_rtp_port)
        self.callee_rtcp_endpoint = RTPEndpoint(ip=callee_ip, port=callee_rtcp_port)
        
        # 이미 생성된 프로토콜의 remote_addr 업데이트
        if "caller_audio_rtp" in self.protocols:
            self.protocols["caller_audio_rtp"].remote_addr = (callee_ip, callee_rtp_port)
        if "caller_audio_rtcp" in self.protocols:
            self.protocols["caller_audio_rtcp"].remote_addr = (callee_ip, callee_rtcp_port)
        
        logger.info("callee_endpoint_updated",
                   call_id=self.media_session.call_id,
                   callee_ip=callee_ip,
                   callee_rtp_port=callee_rtp_port,
                   callee_rtcp_port=callee_rtcp_port)
    
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
        # 🔍 디버깅: RTP 패킷 수신 (DEBUG 레벨)
        logger.debug("rtp_packet_received_raw",
                    call_id=self.reflector.media_session.call_id,
                    socket_type=self.socket_type,
                    from_addr=f"{addr[0]}:{addr[1]}",
                    size=len(data))
        
        if not self.reflector.running:
            logger.warning("rtp_packet_dropped_not_running",
                          call_id=self.reflector.media_session.call_id,
                          socket_type=self.socket_type)
            return
        
        # ✅ Symmetric RTP 학습: 실제 송신자 주소 확인
        # MizuDroid 등 일부 클라이언트가 SDP를 무시하고 잘못된 포트로 보낼 수 있음
        if self.socket_type == "caller_audio_rtp" or self.socket_type == "caller_audio_rtcp":
            # Caller 소켓으로 들어온 패킷
            expected_ip = self.reflector.caller_endpoint.ip
            
            if addr[0] != expected_ip:
                # ❌ Caller 소켓에 Callee 패킷이 들어옴!
                # 하지만 MizuDroid처럼 SDP를 무시하는 경우가 있으므로
                # Callee 소켓으로 리다이렉트
                logger.warning("symmetric_rtp_detected_redirecting",
                              call_id=self.reflector.media_session.call_id,
                              socket_type=self.socket_type,
                              expected_ip=expected_ip,
                              actual_ip=addr[0],
                              actual_addr=f"{addr[0]}:{addr[1]}",
                              message="Callee sent RTP to wrong port, redirecting to callee socket")
                
                # Callee 소켓으로 전달 (callee_audio_rtp 프로토콜 찾기)
                callee_socket_type = "callee_audio_rtp" if "rtp" in self.socket_type else "callee_audio_rtcp"
                if callee_socket_type in self.reflector.protocols:
                    callee_protocol = self.reflector.protocols[callee_socket_type]
                    # Callee 프로토콜의 datagram_received 호출
                    callee_protocol.datagram_received(data, addr)
                    return
                else:
                    logger.error("callee_socket_not_found_for_redirect",
                               call_id=self.reflector.media_session.call_id,
                               socket_type=callee_socket_type)
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

