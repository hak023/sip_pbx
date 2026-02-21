"""RTP Relay Worker

RTP/RTCP 패킷 relay (Bypass Mode)
"""

import asyncio
from typing import Optional, Tuple
from dataclasses import dataclass

from src.media.rtp_packet import RTPParser, RTCPPacket
from src.media.media_session import MediaSession
from src.common.logger import get_async_logger

logger = get_async_logger(__name__)


@dataclass
class RTPEndpoint:
    """RTP 엔드포인트 (IP:Port)"""
    ip: str
    port: int
    
    def __repr__(self) -> str:
        return f"{self.ip}:{self.port}"


class RelayMode:
    """RTP Relay 모드 상수"""
    BYPASS = "bypass"        # 기존: Caller ↔ Callee 직접 릴레이
    AI = "ai"                # 기존: Caller ↔ AI (TTS/STT)
    BRIDGE = "bridge"        # 신규: Caller ↔ Server ↔ New Callee (Transfer)
    HOLD = "hold"            # 신규: Caller에게 대기 안내/음악 재생


class RTPRelayWorker:
    """RTP Relay Worker
    
    Bypass 모드: RTP 패킷을 단순 relay
    Bridge 모드: Transfer 시 발신자↔서버↔새 착신자 릴레이
    """
    
    def __init__(
        self,
        media_session: MediaSession,
        caller_endpoint: RTPEndpoint,
        callee_endpoint: RTPEndpoint,
        bind_ip: str = "0.0.0.0",  # RTP 소켓을 bind할 IP
        ai_orchestrator = None,  # AI Orchestrator (optional)
        sip_recorder = None,  # SIP Call Recorder (optional)
    ):
        """초기화
        
        Args:
            media_session: 미디어 세션
            caller_endpoint: Caller의 RTP 엔드포인트
            callee_endpoint: Callee의 RTP 엔드포인트
            bind_ip: RTP 소켓을 bind할 IP 주소
            ai_orchestrator: AI Orchestrator (AI 모드용, optional)
            sip_recorder: SIP Call Recorder (녹음용, optional)
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
        
        # AI 보이스봇 지원
        self.ai_orchestrator = ai_orchestrator
        self.ai_mode = False
        
        # Pipecat Pipeline 지원 (Phase 1)
        self._pipecat_audio_queue: Optional[asyncio.Queue] = None
        self._pipecat_mode = False  # True이면 Pipecat 파이프라인으로 오디오 전달
        self._rtp_packet_builder = None  # TTS -> RTP 변환용
        # TTS→RTP 실시간 패이싱: 한꺼번에 보내면 전화기 지터 버퍼가 중간 패킷을 버려 앞뒤만 들림
        self._pipecat_outgoing_queue: Optional[asyncio.Queue] = None
        self._pipecat_outgoing_task: Optional[asyncio.Task] = None
        self._RTP_PACKET_MS = 20  # 20ms per RTP packet (G.711 표준)
        
        # ★ Bridge 모드 지원 (Transfer)
        self.relay_mode: str = RelayMode.BYPASS  # 현재 릴레이 모드
        self.bridge_callee_endpoint: Optional[RTPEndpoint] = None  # Bridge 대상 엔드포인트
        self.bridge_callee_transport: Optional[asyncio.DatagramTransport] = None  # Bridge용 소켓
        self._bridge_protocol = None  # Bridge callee RTP protocol
        
        # SIP 통화 녹음 지원 (신규)
        self.sip_recorder = sip_recorder
        self.recording_enabled = sip_recorder is not None
        
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
            "recording_packets": 0,  # 녹음으로 전달된 패킷 수
        }
        
        logger.info("rtp_relay_worker_created",
                   call_id=media_session.call_id,
                   caller=str(caller_endpoint),
                   callee=str(callee_endpoint),
                   ai_enabled=ai_orchestrator is not None,
                   recording_enabled=sip_recorder is not None)
    
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
            try:
                protocol = RTPRelayProtocol(
                    self,
                    "caller_audio_rtp",
                    self.callee_endpoint,
                    self.callee_endpoint.port  # ✅ 클라이언트의 실제 RTP 포트
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
                protocol = RTPRelayProtocol(
                    self,
                    "caller_audio_rtcp",
                    self.callee_rtcp_endpoint,  # ✅ Callee의 RTCP 엔드포인트
                    self.callee_rtcp_endpoint.port
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
                protocol = RTPRelayProtocol(
                    self,
                    "callee_audio_rtp",
                    self.caller_endpoint,
                    self.caller_endpoint.port  # ✅ 클라이언트의 실제 RTP 포트
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
                protocol = RTPRelayProtocol(
                    self,
                    "callee_audio_rtcp",
                    self.caller_rtcp_endpoint,  # ✅ Caller의 RTCP 엔드포인트
                    self.caller_rtcp_endpoint.port
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
        
        # 이미 생성된 프로토콜의 remote_endpoint와 remote_port 업데이트
        if "caller_audio_rtp" in self.protocols:
            self.protocols["caller_audio_rtp"].remote_endpoint = RTPEndpoint(ip=callee_ip, port=callee_rtp_port)
            self.protocols["caller_audio_rtp"].remote_port = callee_rtp_port
        if "caller_audio_rtcp" in self.protocols:
            self.protocols["caller_audio_rtcp"].remote_endpoint = RTPEndpoint(ip=callee_ip, port=callee_rtcp_port)
            self.protocols["caller_audio_rtcp"].remote_port = callee_rtcp_port
        
        logger.info("callee_endpoint_updated",
                   call_id=self.media_session.call_id,
                   callee_ip=callee_ip,
                   callee_rtp_port=callee_rtp_port,
                   callee_rtcp_port=callee_rtcp_port)
    
    def send_stun_binding_request_to_caller(self) -> None:
        """STUN Binding Request를 Caller(UAC)의 미디어 포트로 전송
        
        200 OK 전송 직후 호출하여 미디어 경로를 확인하고 NAT 바인딩을 유지합니다.
        이를 통해 UAC가 ACK+BYE를 동시에 보내는 문제를 방지합니다.
        
        RFC 5389에 따라 신뢰성을 위해 여러 번 전송합니다.
        """
        try:
            # Caller Audio RTP 소켓이 있는지 확인
            if "caller_audio_rtp" not in self.protocols:
                logger.warning("stun_request_no_caller_rtp_socket",
                             call_id=self.media_session.call_id)
                return
            
            caller_protocol = self.protocols["caller_audio_rtp"]
            if not caller_protocol.transport:
                logger.warning("stun_request_no_transport",
                             call_id=self.media_session.call_id)
                return
            
            # Caller의 RTP 엔드포인트로 전송
            caller_rtp_addr = (self.caller_endpoint.ip, self.caller_endpoint.port)
            
            # STUN Binding Request를 3번 전송 (간격: 즉시, 20ms, 40ms)
            # 정상 통화에서는 여러 STUN 패킷이 교환되므로 이를 모방
            stun_request = caller_protocol._create_stun_binding_request()
            
            # 1차 전송 (즉시)
            caller_protocol.transport.sendto(stun_request, caller_rtp_addr)
            logger.info("stun_binding_request_sent_to_caller",
                       call_id=self.media_session.call_id,
                       caller_rtp_addr=f"{caller_rtp_addr[0]}:{caller_rtp_addr[1]}",
                       attempt=1,
                       size=len(stun_request))
            
            # 2차, 3차 전송을 비동기로 스케줄링
            import asyncio
            async def send_additional_stun():
                try:
                    # 20ms 대기 후 2차 전송
                    await asyncio.sleep(0.02)
                    stun_request2 = caller_protocol._create_stun_binding_request()
                    caller_protocol.transport.sendto(stun_request2, caller_rtp_addr)
                    logger.info("stun_binding_request_sent_to_caller",
                               call_id=self.media_session.call_id,
                               caller_rtp_addr=f"{caller_rtp_addr[0]}:{caller_rtp_addr[1]}",
                               attempt=2,
                               size=len(stun_request2))
                    
                    # 40ms 대기 후 3차 전송
                    await asyncio.sleep(0.02)
                    stun_request3 = caller_protocol._create_stun_binding_request()
                    caller_protocol.transport.sendto(stun_request3, caller_rtp_addr)
                    logger.info("stun_binding_request_sent_to_caller",
                               call_id=self.media_session.call_id,
                               caller_rtp_addr=f"{caller_rtp_addr[0]}:{caller_rtp_addr[1]}",
                               attempt=3,
                               size=len(stun_request3))
                except Exception as e:
                    logger.error("stun_request_additional_send_error",
                               call_id=self.media_session.call_id,
                               error=str(e))
            
            # 비동기 태스크로 실행 (블로킹하지 않음)
            asyncio.create_task(send_additional_stun())
            
        except Exception as e:
            logger.error("stun_request_send_error",
                       call_id=self.media_session.call_id,
                       error=str(e),
                       exc_info=True)
    
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
        
        # AI 모드: Pipecat 파이프라인 또는 기존 Orchestrator로 패킷 전달
        if self.ai_mode and socket_type == "caller_audio_rtp":
            # Pipecat 모드 우선
            if self._pipecat_mode and self._pipecat_audio_queue:
                try:
                    from src.ai_voicebot.pipecat.audio_utils import rtp_to_pcm16k
                    codec = getattr(self.media_session, 'codec', 'PCMU')
                    pcm_data = rtp_to_pcm16k(data, codec)
                    if pcm_data:
                        try:
                            self._pipecat_audio_queue.put_nowait(pcm_data)
                        except asyncio.QueueFull:
                            pass  # 큐 가득 차면 드롭
                    self.stats["ai_packets"] += 1
                except Exception as e:
                    logger.error("pipecat_packet_forward_error",
                               call_id=self.media_session.call_id,
                               error=str(e))
            # 기존 Orchestrator 모드 (fallback)
            elif self.ai_orchestrator:
                try:
                    asyncio.create_task(
                        self.ai_orchestrator.on_audio_packet(data, direction="caller")
                    )
                    self.stats["ai_packets"] += 1
                except Exception as e:
                    logger.error("ai_packet_forward_error",
                               call_id=self.media_session.call_id,
                               error=str(e))
        
        # SIP 통화 녹음
        if self.recording_enabled and self.sip_recorder:
            # AI 모드에서도 caller 음성 녹음 (caller_audio_rtp)
            # 일반 모드에서는 caller + callee 모두 녹음
            should_record = False
            if not self.ai_mode:
                should_record = True  # 일반 모드: 모든 오디오 RTP 녹음
            elif socket_type == "caller_audio_rtp":
                should_record = True  # AI 모드: caller 음성만 녹음
            
            if should_record:
                # 오디오 RTP 패킷만 녹음
                if "audio" in socket_type and "rtp" in socket_type:
                    try:
                        # RTP 패킷 파싱하여 페이로드 추출
                        try:
                            rtp_packet = RTPParser.parse(data)
                            audio_payload = rtp_packet.payload
                        except Exception as parse_error:
                            # 파싱 실패 시 RTP 헤더(12 bytes) 건너뛰고 페이로드만 사용
                            # RTP 헤더를 포함하면 G.711 디코딩 시 잡음 발생
                            if len(data) > 12:
                                audio_payload = data[12:]  # ✅ 헤더 제거
                                logger.debug("rtp_parse_failed_using_raw_payload",
                                           call_id=self.media_session.call_id,
                                           socket_type=socket_type,
                                           error=str(parse_error),
                                           packet_size=len(data))
                            else:
                                # 너무 짧은 패킷은 스킵
                                logger.warning("rtp_packet_too_short",
                                             call_id=self.media_session.call_id,
                                             packet_size=len(data))
                                return
                        
                        # 방향 결정
                        direction = "caller" if "caller" in socket_type else "callee"
                        
                        # 코덱 결정 (MediaSession에서 가져오기, 기본값 PCMU)
                        codec = getattr(self.media_session, 'codec', 'PCMU')
                        
                        # 비동기 태스크로 녹음 패킷 전달
                        asyncio.create_task(
                            self.sip_recorder.add_rtp_packet(
                                call_id=self.media_session.call_id,
                                audio_data=audio_payload,
                                direction=direction,
                                codec=codec
                            )
                        )
                        self.stats["recording_packets"] += 1
                    except Exception as e:
                        logger.error("recording_packet_forward_error",
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
    
    def enable_ai_mode(self, ai_orchestrator):
        """
        AI 모드 활성화 및 AI Orchestrator 설정
        
        Args:
            ai_orchestrator: AI Orchestrator 인스턴스
        """
        self.ai_orchestrator = ai_orchestrator
        self.ai_mode = True
        logger.info("ai_mode_enabled",
                   call_id=self.media_session.call_id,
                   ai_orchestrator=ai_orchestrator is not None)
    
    def send_ai_audio(self, audio_data: bytes):
        """
        AI에서 생성한 오디오(TTS PCM)를 RTP 패킷으로 변환하여 Caller에게 전송.
        
        Legacy Orchestrator 전용 메서드.
        TTS 출력(LINEAR16 16kHz PCM) → G.711 인코딩 → RTP 패킷화 → Caller로 전송.
        
        Args:
            audio_data: TTS가 생성한 PCM 오디오 데이터 (16-bit, 16kHz)
        """
        if not self.ai_mode:
            logger.warning("not_in_ai_mode",
                         call_id=self.media_session.call_id)
            return
        
        # RTP 패킷 빌더가 없으면 생성 (lazy init)
        if not self._rtp_packet_builder:
            from src.ai_voicebot.pipecat.audio_utils import RTPPacketBuilder
            codec = getattr(self.media_session, 'codec', 'PCMU')
            self._rtp_packet_builder = RTPPacketBuilder(codec=codec)
        
        # Callee Audio RTP transport를 통해 Caller에게 전송
        if self.callee_audio_transport:
            try:
                # ✅ Caller의 실제 RTP 수신 포트 (SDP에서 가져온 포트)
                caller_ip = str(self.caller_endpoint.ip)
                caller_port = int(self.caller_endpoint.port)
                
                # PCM(16kHz) → G.711 → RTP 패킷들로 변환
                rtp_packets = self._rtp_packet_builder.build_packets(audio_data, sample_rate=16000)
                
                for packet in rtp_packets:
                    try:
                        self.callee_audio_transport.sendto(
                            packet, (caller_ip, caller_port)
                        )
                    except Exception as e:
                        logger.error("ai_audio_send_error",
                                   call_id=self.media_session.call_id,
                                   error=str(e))
                        break
            except Exception as e:
                logger.error("ai_audio_send_error",
                           call_id=self.media_session.call_id,
                           error=str(e))
    
    # =========================================================================
    # Pipecat Pipeline 지원 메서드 (Phase 1)
    # =========================================================================
    
    async def _pipecat_outgoing_sender_loop(self):
        """
        RTP 패킷을 20ms 간격으로 전송 (실시간 패이싱).
        한꺼번에 보내면 전화기 지터 버퍼가 중간 패킷을 버려 '앞뒤만 들림' 현상 발생.
        """
        interval_sec = self._RTP_PACKET_MS / 1000.0
        while self._pipecat_mode and self._pipecat_outgoing_queue is not None:
            try:
                packet = await asyncio.wait_for(
                    self._pipecat_outgoing_queue.get(), timeout=0.1
                )
                if packet is None:  # Sentinel
                    break
                if self.callee_audio_transport and self.caller_endpoint:
                    caller_ip = str(self.caller_endpoint.ip)
                    caller_port = int(self.caller_endpoint.port)
                    self.callee_audio_transport.sendto(packet, (caller_ip, caller_port))
                    if self.recording_enabled and self.sip_recorder:
                        try:
                            audio_payload = packet[12:] if len(packet) > 12 else packet
                            codec = getattr(self.media_session, "codec", "PCMU")
                            asyncio.create_task(
                                self.sip_recorder.add_rtp_packet(
                                    call_id=self.media_session.call_id,
                                    audio_data=audio_payload,
                                    direction="callee",
                                    codec=codec,
                                )
                            )
                            self.stats["recording_packets"] += 1
                        except Exception:
                            pass
                await asyncio.sleep(interval_sec)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("pipecat_outgoing_sender_error",
                            call_id=self.media_session.call_id, error=str(e))

    def enable_pipecat_mode(self):
        """
        Pipecat 파이프라인 모드 활성화.
        기존 ai_orchestrator 대신 Pipecat 파이프라인으로 오디오 라우팅.
        TTS→RTP 전송은 실시간 패이싱(20ms 간격)으로 전화기 재생이 끊기지 않도록 함.
        """
        self._pipecat_audio_queue = asyncio.Queue(maxsize=1000)
        self._pipecat_mode = True
        self.ai_mode = True  # AI 모드도 함께 활성화
        
        # RTP 패킷 빌더 생성 (TTS -> RTP 변환용)
        from src.ai_voicebot.pipecat.audio_utils import RTPPacketBuilder
        codec = getattr(self.media_session, 'codec', 'PCMU')
        self._rtp_packet_builder = RTPPacketBuilder(codec=codec)
        
        # 발송 큐 + 실시간 발송 태스크 (한꺼번에 보내면 전화기에서 중간 패킷 유실)
        self._pipecat_outgoing_queue = asyncio.Queue(maxsize=5000)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.get_event_loop()
        self._pipecat_outgoing_task = loop.create_task(self._pipecat_outgoing_sender_loop())
        
        logger.info("pipecat_mode_enabled",
                    call_id=self.media_session.call_id)
    
    async def get_caller_audio_stream(self):
        """
        Caller 오디오를 async generator로 제공 (Pipecat Transport용).
        RTP 패킷을 디코딩하여 16kHz PCM으로 변환 후 yield.
        
        Yields:
            bytes: 16kHz 16-bit PCM 오디오 프레임
        """
        if not self._pipecat_audio_queue:
            logger.error("pipecat_audio_queue_not_initialized",
                        call_id=self.media_session.call_id)
            return
        
        while self._pipecat_mode:
            try:
                pcm_data = await asyncio.wait_for(
                    self._pipecat_audio_queue.get(), timeout=0.1
                )
                if pcm_data is None:  # Sentinel for shutdown
                    break
                yield pcm_data
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error("pipecat_audio_stream_error",
                           call_id=self.media_session.call_id,
                           error=str(e))
                break
    
    def send_audio_to_caller(self, pcm_data: bytes, sample_rate: int = 16000):
        """
        Pipecat에서 생성한 오디오(PCM)를 RTP 패킷으로 변환해 발송 큐에 넣음.
        실제 전송은 _pipecat_outgoing_sender_loop에서 20ms 간격으로 수행(실시간 패이싱).
        """
        if not self.ai_mode:
            return
        if not self._pipecat_outgoing_queue:
            return
        if not self._rtp_packet_builder:
            from src.ai_voicebot.pipecat.audio_utils import RTPPacketBuilder
            codec = getattr(self.media_session, 'codec', 'PCMU')
            self._rtp_packet_builder = RTPPacketBuilder(codec=codec)
        try:
            rtp_packets = self._rtp_packet_builder.build_packets(pcm_data, sample_rate)
            for packet in rtp_packets:
                try:
                    self._pipecat_outgoing_queue.put_nowait(packet)
                except asyncio.QueueFull:
                    logger.warning("pipecat_outgoing_queue_full_dropping",
                                  call_id=self.media_session.call_id)
                    break
        except Exception as e:
            logger.error("pipecat_audio_to_caller_error",
                         call_id=self.media_session.call_id, error=str(e))
    
    def stop_pipecat_mode(self):
        """Pipecat 모드 정지 (발송 큐·태스크 포함)"""
        self._pipecat_mode = False
        if self._pipecat_audio_queue:
            try:
                self._pipecat_audio_queue.put_nowait(None)
            except asyncio.QueueFull:
                pass
        if self._pipecat_outgoing_queue:
            try:
                self._pipecat_outgoing_queue.put_nowait(None)
            except asyncio.QueueFull:
                pass
        if self._pipecat_outgoing_task and not self._pipecat_outgoing_task.done():
            self._pipecat_outgoing_task.cancel()
        self._pipecat_outgoing_task = None
        self._pipecat_outgoing_queue = None
        logger.info("pipecat_mode_stopped", call_id=self.media_session.call_id)
    
    # =========================================================================
    # Bridge 모드 지원 (Transfer)
    # =========================================================================
    
    async def set_bridge_mode(
        self, 
        callee_ip: str, 
        callee_rtp_port: int,
        bridge_rtp_port: int,
    ):
        """AI 모드 → Bridge 모드 전환 (Transfer 연결 완료 시)
        
        Caller의 RTP → Server → New Callee로 릴레이
        New Callee의 RTP → Server → Caller로 릴레이
        
        Args:
            callee_ip: 새 착신자 IP
            callee_rtp_port: 새 착신자 RTP 포트
            bridge_rtp_port: 서버에서 사용할 Bridge 소켓 포트 (이미 할당됨)
        """
        self.bridge_callee_endpoint = RTPEndpoint(ip=callee_ip, port=callee_rtp_port)
        
        # AI 모드 끄기
        self.ai_mode = False
        self._pipecat_mode = False
        self.ai_orchestrator = None
        
        # Bridge 모드 활성화
        self.relay_mode = RelayMode.BRIDGE
        
        # Bridge용 UDP 소켓 생성 (New Callee ↔ Server)
        loop = asyncio.get_event_loop()
        try:
            bridge_protocol = RTPRelayProtocol(
                self,
                "bridge_callee_rtp",
                self.caller_endpoint,  # Bridge callee → Caller로 전달
                self.caller_endpoint.port,
            )
            transport, _ = await loop.create_datagram_endpoint(
                lambda: bridge_protocol,
                local_addr=(self.bind_ip, bridge_rtp_port)
            )
            self.bridge_callee_transport = transport
            self._bridge_protocol = bridge_protocol
            self.protocols["bridge_callee_rtp"] = bridge_protocol
            
            logger.info("bridge_mode_activated",
                       call_id=self.media_session.call_id,
                       bridge_callee=f"{callee_ip}:{callee_rtp_port}",
                       bridge_port=bridge_rtp_port)
            
        except Exception as e:
            logger.error("bridge_socket_create_error",
                        call_id=self.media_session.call_id,
                        error=str(e))
            raise
    
    def set_hold_mode(self):
        """Hold 모드 전환 - 발신자에게 대기 상태 (RTP 무시)"""
        self.relay_mode = RelayMode.HOLD
        logger.info("hold_mode_activated",
                   call_id=self.media_session.call_id)
    
    def set_bypass_mode(self):
        """일반 Bypass 모드로 복귀"""
        self.relay_mode = RelayMode.BYPASS
        self.ai_mode = False
        self.bridge_callee_endpoint = None
        logger.info("bypass_mode_activated",
                   call_id=self.media_session.call_id)
    
    async def stop_bridge_mode(self):
        """Bridge 모드 정지 및 Bridge 소켓 해제"""
        if self.bridge_callee_transport:
            self.bridge_callee_transport.close()
            self.bridge_callee_transport = None
        self.bridge_callee_endpoint = None
        self._bridge_protocol = None
        self.protocols.pop("bridge_callee_rtp", None)
        self.relay_mode = RelayMode.BYPASS
        
        logger.info("bridge_mode_stopped",
                   call_id=self.media_session.call_id)
    
    # =========================================================================
    
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
        # 🔍 디버깅: RTP 패킷 수신 (DEBUG 레벨, 비동기 처리)
        # 성능 최적화: RTP 패킷은 매우 빈번하므로 DEBUG 레벨로만 로깅
        # logger.debug("rtp_packet_received_raw",
        #             call_id=self.relay_worker.media_session.call_id,
        #             socket_type=self.socket_type,
        #             from_addr=f"{addr[0]}:{addr[1]}",
        #             size=len(data))
        
        if not self.relay_worker.running:
            logger.warning("rtp_packet_dropped_not_running",
                          call_id=self.relay_worker.media_session.call_id,
                          socket_type=self.socket_type)
            return
        
        # ✅ STUN Binding Request 처리
        if len(data) >= 20 and data[0] == 0x00 and data[1] == 0x01:
            # STUN Binding Request 감지 (Message Type: 0x0001)
            logger.debug("stun_binding_request_received",
                       call_id=self.relay_worker.media_session.call_id,
                       socket_type=self.socket_type,
                       from_addr=f"{addr[0]}:{addr[1]}",
                       size=len(data),
                       ai_mode=self.relay_worker.ai_mode)
            
            # ✅ AI 모드일 때만 B2BUA가 직접 STUN Response 전송
            # 일반 모드에서는 UAS에게 relay (기존 동작 유지)
            if self.relay_worker.ai_mode:
                # AI 모드: B2BUA가 STUN Binding Response 직접 생성
                try:
                    stun_response = self._create_stun_binding_response(data, addr)
                    if stun_response and self.transport:
                        self.transport.sendto(stun_response, addr)
                        logger.debug("stun_binding_response_sent_ai_mode",
                                   call_id=self.relay_worker.media_session.call_id,
                                   to_addr=f"{addr[0]}:{addr[1]}",
                                   size=len(stun_response))
                except Exception as e:
                    logger.error("stun_response_error",
                               call_id=self.relay_worker.media_session.call_id,
                               error=str(e))
                return
            else:
                # 일반 모드: STUN을 relay (UAS에게 전달)
                logger.info("stun_binding_request_relaying",
                           call_id=self.relay_worker.media_session.call_id,
                           socket_type=self.socket_type,
                           from_addr=f"{addr[0]}:{addr[1]}")
                # relay 로직은 아래 코드에서 처리됨 (그대로 remote_endpoint로 전달)
        
        # ✅ Symmetric RTP 학습: 실제 송신자 주소 확인
        # MizuDroid 등 일부 클라이언트가 SDP를 무시하고 잘못된 포트로 보낼 수 있음
        if self.socket_type == "caller_audio_rtp" or self.socket_type == "caller_audio_rtcp":
            # Caller 소켓으로 들어온 패킷
            expected_ip = self.relay_worker.caller_endpoint.ip
            
            if addr[0] != expected_ip:
                # ❌ Caller 소켓에 Callee 패킷이 들어옴!
                # 하지만 MizuDroid처럼 SDP를 무시하는 경우가 있으므로
                # Callee 소켓으로 리다이렉트
                logger.warning("symmetric_rtp_detected_redirecting",
                              call_id=self.relay_worker.media_session.call_id,
                              socket_type=self.socket_type,
                              expected_ip=expected_ip,
                              actual_ip=addr[0],
                              actual_addr=f"{addr[0]}:{addr[1]}",
                              message="Callee sent RTP to wrong port, redirecting to callee socket")
                
                # Callee 소켓으로 전달 (callee_audio_rtp 프로토콜 찾기)
                callee_socket_type = "callee_audio_rtp" if "rtp" in self.socket_type else "callee_audio_rtcp"
                if callee_socket_type in self.relay_worker.protocols:
                    callee_protocol = self.relay_worker.protocols[callee_socket_type]
                    # Callee 프로토콜의 datagram_received 호출
                    callee_protocol.datagram_received(data, addr)
                    return
                else:
                    logger.error("callee_socket_not_found_for_redirect",
                               call_id=self.relay_worker.media_session.call_id,
                               socket_type=callee_socket_type)
                    return
        
        # 패킷을 그대로 원격 엔드포인트로 전달
        if self.transport:
            try:
                # ★ Bridge 모드: Caller → New Callee, Bridge Callee → Caller
                if self.relay_worker.relay_mode == RelayMode.BRIDGE:
                    if self.socket_type == "caller_audio_rtp":
                        # Caller 음성 → New Callee로 전달
                        if self.relay_worker.bridge_callee_endpoint and self.relay_worker.bridge_callee_transport:
                            bridge_addr = (
                                str(self.relay_worker.bridge_callee_endpoint.ip),
                                int(self.relay_worker.bridge_callee_endpoint.port)
                            )
                            self.relay_worker.bridge_callee_transport.sendto(data, bridge_addr)
                        self.relay_worker.on_packet_received(self.socket_type, data, addr)
                        return
                    elif self.socket_type == "bridge_callee_rtp":
                        # New Callee 음성 → Caller로 전달
                        if self.relay_worker.caller_audio_transport:
                            caller_addr = (
                                str(self.relay_worker.caller_endpoint.ip),
                                int(self.relay_worker.caller_endpoint.port)
                            )
                            self.relay_worker.caller_audio_transport.sendto(data, caller_addr)
                        self.relay_worker.on_packet_received(self.socket_type, data, addr)
                        return
                
                # ★ Hold 모드: 패킷 무시 (발신자 음성 드롭)
                if self.relay_worker.relay_mode == RelayMode.HOLD:
                    if self.socket_type == "caller_audio_rtp":
                        self.relay_worker.on_packet_received(self.socket_type, data, addr)
                        return
                
                # ✅ AI 모드: callee가 없으므로 relay 스킵
                # caller_audio_rtp → AI 파이프라인으로 전달
                # caller_audio_rtcp 등 → callee 없으므로 relay 불필요, 조용히 드롭
                if self.relay_worker.ai_mode:
                    if self.socket_type == "caller_audio_rtp":
                        self.relay_worker.on_packet_received(self.socket_type, data, addr)
                    # RTCP 등 다른 소켓은 AI 모드에서 relay할 대상이 없으므로 스킵
                    return
                
                # ✅ 주소 유효성 검사 (Windows 에러 방지)
                if not self.remote_endpoint or not self.remote_endpoint.ip or str(self.remote_endpoint.ip) == "0.0.0.0":
                    logger.warning("rtp_relay_skip_invalid_remote",
                                 call_id=self.relay_worker.media_session.call_id,
                                 socket_type=self.socket_type)
                    return
                
                if self.remote_port is None or self.remote_port <= 0:
                    logger.warning("rtp_relay_skip_invalid_port",
                                 call_id=self.relay_worker.media_session.call_id,
                                 socket_type=self.socket_type,
                                 port=self.remote_port)
                    return
                
                # 주소 튜플 생성 (Windows 호환성)
                remote_addr = (str(self.remote_endpoint.ip), int(self.remote_port))
                
                self.transport.sendto(data, remote_addr)
                
                # 콜백 호출
                self.relay_worker.on_packet_received(self.socket_type, data, addr)
                
            except Exception as e:
                logger.error("rtp_relay_error",
                           call_id=self.relay_worker.media_session.call_id,
                           socket_type=self.socket_type,
                           error=str(e))
    
    def _create_stun_binding_request(self) -> bytes:
        """STUN Binding Request 생성
        
        RFC 5389: STUN (Session Traversal Utilities for NAT)
        200 OK 전송 후 UAC의 미디어 포트로 전송하여 미디어 경로 확인 및 NAT 바인딩 유지
        
        Returns:
            STUN Binding Request 바이트 데이터
        """
        import random
        
        # STUN 메시지 구조:
        # 0-1: Message Type (0x0001 = Binding Request)
        # 2-3: Message Length (속성이 없으므로 0)
        # 4-7: Magic Cookie (0x2112A442)
        # 8-19: Transaction ID (12 bytes, random)
        
        magic_cookie = 0x2112A442
        
        # Transaction ID 생성 (12 bytes, random)
        transaction_id = bytes([random.randint(0, 255) for _ in range(12)])
        
        # STUN Binding Request (속성 없음)
        request = (
            b'\x00\x01'  # Message Type: Binding Request (0x0001)
            b'\x00\x00'  # Message Length: 0 (no attributes)
            + magic_cookie.to_bytes(4, 'big')  # Magic Cookie
            + transaction_id  # Transaction ID
        )
        
        return request
    
    def _create_stun_binding_response(self, request_data: bytes, client_addr: Tuple[str, int]) -> Optional[bytes]:
        """STUN Binding Response 생성
        
        RFC 5389: STUN (Session Traversal Utilities for NAT)
        
        Args:
            request_data: STUN Binding Request 데이터
            client_addr: 클라이언트 주소 (IP, Port)
            
        Returns:
            STUN Binding Response 바이트 데이터
        """
        try:
            if len(request_data) < 20:
                return None
            
            # STUN 메시지 구조:
            # 0-1: Message Type (0x0001 = Binding Request, 0x0101 = Binding Response)
            # 2-3: Message Length
            # 4-7: Magic Cookie (0x2112A442)
            # 8-19: Transaction ID (12 bytes)
            
            # Transaction ID 추출 (8-19 바이트)
            transaction_id = request_data[8:20]
            
            # XOR-MAPPED-ADDRESS 속성 생성
            # Type: 0x0020 (XOR-MAPPED-ADDRESS)
            # Length: 0x0008 (8 bytes for IPv4)
            # Family: 0x0001 (IPv4)
            # Port: XOR'd with magic cookie의 상위 16비트
            # Address: XOR'd with magic cookie
            
            magic_cookie = 0x2112A442
            
            # 포트를 XOR
            port = client_addr[1]
            xor_port = port ^ (magic_cookie >> 16)
            
            # IP 주소를 XOR
            ip_parts = [int(p) for p in client_addr[0].split('.')]
            xor_ip = bytes([
                ip_parts[0] ^ ((magic_cookie >> 24) & 0xFF),
                ip_parts[1] ^ ((magic_cookie >> 16) & 0xFF),
                ip_parts[2] ^ ((magic_cookie >> 8) & 0xFF),
                ip_parts[3] ^ (magic_cookie & 0xFF)
            ])
            
            # XOR-MAPPED-ADDRESS 속성
            xor_mapped_address = (
                b'\x00\x20'  # Type: XOR-MAPPED-ADDRESS
                b'\x00\x08'  # Length: 8
                b'\x00\x01'  # Family: IPv4
                + xor_port.to_bytes(2, 'big')  # XOR'd Port
                + xor_ip  # XOR'd IP
            )
            
            # STUN Binding Response 생성
            message_length = len(xor_mapped_address)
            
            response = (
                b'\x01\x01'  # Message Type: Binding Response (0x0101)
                + message_length.to_bytes(2, 'big')  # Message Length
                + magic_cookie.to_bytes(4, 'big')  # Magic Cookie
                + transaction_id  # Transaction ID (from request)
                + xor_mapped_address  # Attributes
            )
            
            logger.debug("stun_response_created",
                        call_id=self.relay_worker.media_session.call_id,
                        client_addr=f"{client_addr[0]}:{client_addr[1]}",
                        response_size=len(response))
            
            return response
            
        except Exception as e:
            logger.error("stun_response_creation_error",
                        call_id=self.relay_worker.media_session.call_id,
                        error=str(e))
            return None
    
    def error_received(self, exc: Exception) -> None:
        """에러 수신
        
        Args:
            exc: 예외
        """
        # AI 모드에서 RTCP 소켓의 WinError는 무시 (callee가 없어서 발생)
        if self.relay_worker.ai_mode and "rtcp" in self.socket_type:
            return
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

