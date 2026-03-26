"""RTP Relay Worker

RTP/RTCP 패킷 relay (Bypass Mode)
"""

import asyncio
import struct
import time
from typing import Optional, Tuple
from dataclasses import dataclass

from src.media.rtp_packet import RTPParser, RTCPPacket
from src.media.media_session import MediaSession
from src.common.logger import get_async_logger
from src.media.aec_processor import AEC_FRAME_BYTES  # 10ms @ 16kHz = 320 bytes

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
        
        # ✅ Windows Proactor sendto 동시성 보호 (AssertionError 방지)
        self._sendto_lock = asyncio.Lock()
        
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
        # TTS→RTP: PCM 큐 + 단일 발송 루프(20ms 패이싱)
        self._pipecat_pcm_queue: Optional[asyncio.Queue] = None
        self._pipecat_outgoing_task: Optional[asyncio.Task] = None
        self._RTP_PACKET_MS = 20  # 20ms per RTP packet (G.711 표준)
        # AEC (선택): far-end 참조 + near-end 에코 제거
        self._aec_processor = None
        self._aec_near_buffer = b""
        
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
            # RTP TTS 전송 품질 모니터링
            "rtp_tts_packets_sent": 0,  # 실제 전송 성공한 RTP 패킷 수
            "rtp_tts_packets_dropped": 0,  # 큐 오버플로우로 드롭된 패킷 수
            "rtp_tts_send_errors": 0,  # sendto() 예외 발생 횟수
        }
        # 지연 분석용: 구간별 첫 로그 한 번만 (RTP→STT→TTS→RTP)
        self._timing_first_caller_rtp_logged = False
        self._timing_first_tts_rtp_sent_logged = False
        
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
        # 일반 통화 실시간 STT 세션 정리 (해당 call_id 스트림 종료)
        try:
            from src.media.bypass_realtime_stt import get_bypass_realtime_stt
            get_bypass_realtime_stt().end_call(self.media_session.call_id)
        except Exception:
            pass
        
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
            
            # 1차 전송 (즉시) - 동기 함수이므로 직접 전송
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
                    async with self._sendto_lock:
                        caller_protocol.transport.sendto(stun_request2, caller_rtp_addr)
                    logger.info("stun_binding_request_sent_to_caller",
                               call_id=self.media_session.call_id,
                               caller_rtp_addr=f"{caller_rtp_addr[0]}:{caller_rtp_addr[1]}",
                               attempt=2,
                               size=len(stun_request2))
                    
                    # 40ms 대기 후 3차 전송
                    await asyncio.sleep(0.02)
                    stun_request3 = caller_protocol._create_stun_binding_request()
                    async with self._sendto_lock:
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
    
    def feed_bypass_realtime_stt(self, socket_type: str, data: bytes) -> None:
        """유저 간 통화용 Google 스트리밍 STT 입력. AI 모드에서는 호출하지 않음."""
        if self.ai_mode:
            return
        if "audio" not in socket_type or "rtp" not in socket_type or "rtcp" in socket_type:
            return
        if socket_type == "caller_audio_rtp":
            channel = "caller"
        elif socket_type == "callee_audio_rtp":
            channel = "callee"
        elif socket_type == "bridge_callee_rtp":
            channel = "callee"
        else:
            return
        try:
            try:
                rtp_packet = RTPParser.parse(data)
                audio_payload = rtp_packet.payload
            except Exception:
                audio_payload = data[12:] if len(data) > 12 else b""
            if not audio_payload:
                return
            codec = getattr(self.media_session, "codec", "PCMU") or "PCMU"
            from src.media.bypass_realtime_stt import get_bypass_realtime_stt

            get_bypass_realtime_stt().feed_audio(
                self.media_session.call_id, channel, audio_payload, codec
            )
            if not getattr(self, "_bypass_stt_feed_logged", False):
                self._bypass_stt_feed_logged = True
                logger.info(
                    "bypass_realtime_stt_feed_started",
                    call_id=self.media_session.call_id,
                    socket_type=socket_type,
                    channel=channel,
                    note="유저 간 통화 RTP → 실시간 STT (대시보드 stt_transcript)",
                )
        except Exception as e:
            if not getattr(self, "_bypass_stt_feed_error_logged", False):
                self._bypass_stt_feed_error_logged = True
                logger.warning(
                    "bypass_realtime_stt_feed_error",
                    call_id=self.media_session.call_id,
                    socket_type=socket_type,
                    error=str(e),
                )
    
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
                    
                    # 디버깅: RTP→STT 입력 모니터링 (첫 50개 + 100개마다)
                    if not hasattr(self, "_caller_rtp_received_count"):
                        self._caller_rtp_received_count = 0
                    self._caller_rtp_received_count += 1
                    
                    if self._caller_rtp_received_count <= 50 or self._caller_rtp_received_count % 100 == 0:
                        is_tts_active = bool(getattr(self, "_pipecat_outgoing_task", None) and 
                                           not self._pipecat_outgoing_task.done() and
                                           getattr(self, "_pipecat_pcm_queue", None) and 
                                           self._pipecat_pcm_queue.qsize() > 0)
                        logger.info("caller_rtp_to_stt_input",
                                   call_id=self.media_session.call_id,
                                   progress="stt_rtp",
                                   packet_count=self._caller_rtp_received_count,
                                   rtp_bytes=len(data),
                                   pcm_bytes=len(pcm_data) if pcm_data else 0,
                                   stt_queue_size=self._pipecat_audio_queue.qsize(),
                                   tts_sending_active=is_tts_active,
                                   tts_queue_size=self._pipecat_pcm_queue.qsize() if hasattr(self, "_pipecat_pcm_queue") and self._pipecat_pcm_queue else 0,
                                   note="Caller RTP → STT 입력 (TTS 동시 송출 여부 확인)")
                    # STT 경로 점검: 첫 패킷 시 한 번, 이후 200마다 (테스트 후 동작 여부 점검용)
                    if self._caller_rtp_received_count == 1:
                        logger.info("stt_path_rtp_first",
                                   call_id=self.media_session.call_id,
                                   note="[STT 경로] RTP → 큐 첫 투입 (이 로그가 있어야 경로 시작)")
                    if self._caller_rtp_received_count > 0 and self._caller_rtp_received_count % 200 == 0:
                        logger.info("stt_path_rtp_to_queue",
                                   call_id=self.media_session.call_id,
                                   packet_count=self._caller_rtp_received_count,
                                   queue_size=self._pipecat_audio_queue.qsize(),
                                   queue_max=self._pipecat_audio_queue.maxsize,
                                   note="[STT 경로] RTP → STT 입력 큐 투입 누적")
                    
                    if pcm_data:
                        if getattr(self, "_aec_processor", None):
                            self._aec_near_buffer = getattr(self, "_aec_near_buffer", b"") + pcm_data
                            while len(self._aec_near_buffer) >= AEC_FRAME_BYTES:
                                chunk = self._aec_near_buffer[:AEC_FRAME_BYTES]
                                self._aec_near_buffer = self._aec_near_buffer[AEC_FRAME_BYTES:]
                                out = self._aec_processor.process_stream(chunk)
                                try:
                                    self._pipecat_audio_queue.put_nowait(out)
                                except asyncio.QueueFull:
                                    if not getattr(self, "_stt_queue_full_logged", False):
                                        self._stt_queue_full_logged = True
                                        logger.warning("stt_input_queue_full_dropping",
                                                     call_id=self.media_session.call_id,
                                                     queue_size=self._pipecat_audio_queue.maxsize,
                                                     note="STT 입력 큐 가득 - caller PCM 드롭 (소비 지연 시 발생)")
                                    break
                                if not self._timing_first_caller_rtp_logged:
                                    self._timing_first_caller_rtp_logged = True
                                    from datetime import datetime
                                    logger.info("timing_caller_rtp_first_to_pipeline",
                                               call_id=self.media_session.call_id,
                                               progress="timing",
                                               ts_iso=datetime.now().isoformat(timespec="milliseconds"),
                                               note="RTP→STT 구간 시작: caller 음성 첫 패킷이 파이프라인에 투입된 시점")
                        else:
                            try:
                                self._pipecat_audio_queue.put_nowait(pcm_data)
                                qsize = self._pipecat_audio_queue.qsize()
                                if qsize >= 800:
                                    if not getattr(self, "_stt_path_queue_high_logged", False):
                                        self._stt_path_queue_high_logged = True
                                        logger.warning("stt_path_queue_high",
                                                      call_id=self.media_session.call_id,
                                                      queue_size=qsize,
                                                      queue_max=self._pipecat_audio_queue.maxsize,
                                                      note="[STT 경로] 큐 백로그 큼 — Input 소비 지연, 파이프라인 블로킹 가능성")
                                elif qsize < 400:
                                    self._stt_path_queue_high_logged = False  # 다음 백로그 시 다시 로그
                                if not self._timing_first_caller_rtp_logged:
                                    self._timing_first_caller_rtp_logged = True
                                    from datetime import datetime
                                    logger.info("timing_caller_rtp_first_to_pipeline",
                                               call_id=self.media_session.call_id,
                                               progress="timing",
                                               ts_iso=datetime.now().isoformat(timespec="milliseconds"),
                                               note="RTP→STT 구간 시작: caller 음성 첫 패킷이 파이프라인에 투입된 시점")
                            except asyncio.QueueFull:
                                if not getattr(self, "_stt_queue_full_logged", False):
                                    self._stt_queue_full_logged = True
                                    logger.warning("stt_input_queue_full_dropping",
                                                 call_id=self.media_session.call_id,
                                                 queue_size=self._pipecat_audio_queue.maxsize,
                                                 note="STT 입력 큐 가득 - caller PCM 드롭 (소비 지연 시 발생)")
                                logger.warning("stt_path_queue_full_drop",
                                             call_id=self.media_session.call_id,
                                             packet_count=getattr(self, "_caller_rtp_received_count", 0),
                                             note="[STT 경로] 큐 풀 → caller PCM 드롭")
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
                                # 녹음만 스킵 — 아래 bypass STT·RTP 통계는 계속 진행
                                logger.warning("rtp_packet_too_short",
                                             call_id=self.media_session.call_id,
                                             packet_size=len(data))
                                audio_payload = b""
                        
                        # 방향 결정
                        direction = "caller" if "caller" in socket_type else "callee"
                        
                        # 코덱 결정 (MediaSession에서 가져오기, 기본값 PCMU)
                        codec = getattr(self.media_session, 'codec', 'PCMU')
                        
                        if audio_payload:
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
        
        # 일반 통화(bypass) 실시간 STT (relay 성공 경로)
        self.feed_bypass_realtime_stt(socket_type, data)
        
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
        AI 모드 활성화 및 AI Orchestrator 설정 (Legacy 경로).

        pipeline_engine="legacy" 일 때만 사용. 현재 기본은 Pipecat이므로
        대부분의 통화에서는 enable_pipecat_mode() 가 호출됩니다.

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
        
        # callee_audio_transport가 닫힌 경우 caller_audio_transport 로 폴백 (Windows ICMP 에러 대응)
        transport = self.callee_audio_transport or self.caller_audio_transport
        if not transport:
            logger.error("send_ai_audio_no_transport",
                        call_id=self.media_session.call_id,
                        message="both callee/caller_audio_transport are None, TTS RTP cannot be sent to caller")
            return
        
        # RTP 패킷 빌더가 없으면 생성 (lazy init)
        if not self._rtp_packet_builder:
            from src.ai_voicebot.pipecat.audio_utils import RTPPacketBuilder
            codec = getattr(self.media_session, 'codec', 'PCMU')
            self._rtp_packet_builder = RTPPacketBuilder(codec=codec)
        
        try:
            # ✅ Caller의 실제 RTP 수신 포트 (SDP에서 가져온 포트)
            caller_ip = str(self.caller_endpoint.ip)
            caller_port = int(self.caller_endpoint.port)
            
            # PCM(16kHz) → G.711 → RTP 패킷들로 변환
            rtp_packets = self._rtp_packet_builder.build_packets(audio_data, sample_rate=16000)
            
            for packet in rtp_packets:
                try:
                    # 동기 메서드이므로 직접 전송 (레거시 메서드, Pipecat 모드에서는 미사용)
                    transport.sendto(
                        packet, (caller_ip, caller_port)
                    )
                    self.stats["callee_audio_packets"] += 1
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
    
    async def _pipecat_tts_sender_loop(self):
        """
        TTS PCM 큐에서 청크를 꺼내 RTP로 변환 후 20ms 간격으로 전송.
        - 근본 해결: RTP 패킷 큐 대신 PCM 큐 사용 → 버스트 제거, 전송률 일정.
        - 한 청크씩 변환·전송하므로 지터 최소화.
        """
        import time
        interval_sec = self._RTP_PACKET_MS / 1000.0  # 0.020초
        packets_sent = 0
        bytes_sent_cumulative = 0  # Phase1 등 RTP 전송량 검증용 (3초 ≈ 96000 바이트)
        interval_violations = 0
        INTERVAL_TOLERANCE_MS = 5
        empty_timeout_count = 0  # 큐 비어서 1초 대기한 횟수 (언더런 지표)
        last_was_empty_timeout = False
        _logged_3s = False  # 3초 상당 전송 시 1회 로그
        # TTS RTP 상세 추적 (늘어짐/끊김: 스케줄 지연·간격·seq/ts 연속성)
        behind_schedule_count = 0
        last_rtp_seq_sent: Optional[int] = None
        last_rtp_ts_sent: Optional[int] = None
        recent_intervals_ms: list = []  # 최근 패킷 간격(직전→현재), 최대 50개

        while self._pipecat_mode and self._pipecat_pcm_queue is not None:
            try:
                # 디버깅: 큐 대기 시작 시간 기록
                queue_wait_start = time.perf_counter()
                
                # 1.0s는 TTS 청크 간 정상 갭에서도 empty_timeout 로그가 자주 남음 → 소폭 완화
                pcm_data = await asyncio.wait_for(
                    self._pipecat_pcm_queue.get(), timeout=1.25
                )
                
                # ✅ RTP base_time 초기화: 첫 PCM 데이터를 가져온 직후 설정 (대기 시간 제외)
                if not hasattr(self, '_rtp_base_time') or self._rtp_base_time is None:
                    self._rtp_base_time = time.perf_counter()
                    self._rtp_packets_sent_total = 0
                    self._rtp_last_send_time = self._rtp_base_time
                    queue_wait_ms = (self._rtp_base_time - queue_wait_start) * 1000
                    logger.info("rtp_base_time_initialized",
                               call_id=self.media_session.call_id,
                               progress="rtp_timing",
                               pcm_queue_wait_ms=round(queue_wait_ms, 2),
                               note="첫 PCM 데이터 수신 → RTP 절대 시간 기준점 설정")
                else:
                    # 디버깅: 큐에서 데이터 가져오는데 걸린 시간 (첫 50개)
                    queue_wait_ms = (time.perf_counter() - queue_wait_start) * 1000
                    if packets_sent < 50 and queue_wait_ms > 1.0:
                        logger.info("pcm_queue_wait_time",
                                   call_id=self.media_session.call_id,
                                   progress="rtp_timing",
                                   packet_seq=packets_sent,
                                   wait_ms=round(queue_wait_ms, 2),
                                   queue_size_before=self._pipecat_pcm_queue.qsize() + 1,
                                   note="PCM 큐에서 데이터 가져오는데 걸린 시간")
                
                if pcm_data is None:  # Sentinel
                    if packets_sent > 0 or empty_timeout_count > 0:
                        logger.info(
                            "rtp_sender_session_end",
                            call_id=self.media_session.call_id,
                            packets_sent=packets_sent,
                            total_sent=self.stats["rtp_tts_packets_sent"],
                            total_dropped=self.stats["rtp_tts_packets_dropped"],
                            send_errors=self.stats["rtp_tts_send_errors"],
                            interval_violations=interval_violations,
                            behind_schedule_count=behind_schedule_count,
                            empty_timeout_count=empty_timeout_count,
                            note="TTS 발송 루프 종료 — behind_schedule_count=스케줄보다 늦은 전송 횟수",
                        )
                    break
                
                # Phase2 등 "큐 비었다가 새 청크" 도착 시 이 청크만 새 구간으로 base_time 설정.
                # last_was_empty_timeout만 쓰면: empty 직후 Phase1 꼬리 청크가 와서 base_time 설정 후
                # Phase2 첫 청크가 올 때 last_was_empty_timeout=False라 새 구간 미적용 → 1초 리셋 발생.
                # empty_timeout_count >= 2(2초 이상 비어 있음)이고 이미 패킷을 보낸 적 있으면
                # 이번 청크도 새 구간으로 간주해 Phase2 첫 청크에서도 항상 base_time 적용.
                new_segment = last_was_empty_timeout or (
                    empty_timeout_count >= 2 and packets_sent > 0
                )
                if new_segment:
                    logger.info("rtp_tts_sender_resumed_after_empty",
                                call_id=self.media_session.call_id,
                                empty_timeouts=empty_timeout_count,
                                packets_sent_so_far=packets_sent,
                                note="PCM 큐 비어 있다가 새 청크 수신 — 새 구간 base_time 설정 (Phase2 등)")
                    self._rtp_base_time = time.perf_counter()
                    self._rtp_packets_sent_total = 0
                    self._rtp_last_send_time = self._rtp_base_time
                    self._rtp_new_segment_after_empty = True  # 이 청크 첫 패킷까지 1초 리셋 미적용
                    if empty_timeout_count >= 2 and packets_sent > 0:
                        empty_timeout_count = 0  # 다중 empty 후 새 구간 적용했으면 소비
                last_was_empty_timeout = False

                bytes_sent_cumulative += len(pcm_data)
                if not _logged_3s and bytes_sent_cumulative >= 96000:  # 16kHz*2*3초
                    _logged_3s = True
                    logger.info("rtp_sent_3s_equivalent",
                                call_id=self.media_session.call_id,
                                progress="rtp_timing",
                                bytes_sent_cumulative=bytes_sent_cumulative,
                                chunks_sent=packets_sent,
                                note="RTP 발송 루프 누적 3초 상당(≈96KB) 전송 — Phase1 검증용")

                if not self._rtp_packet_builder:
                    continue
                # AEC far-end 참조: TTS PCM을 10ms 단위로 AEC에 넣음
                if self._aec_processor:
                    for i in range(0, len(pcm_data), AEC_FRAME_BYTES):
                        chunk = pcm_data[i : i + AEC_FRAME_BYTES]
                        if len(chunk) == AEC_FRAME_BYTES:
                            self._aec_processor.feed_reverse_stream(chunk)
                rtp_packets = self._rtp_packet_builder.build_packets(pcm_data, 16000)
                
                # ✅ AI 모드: Caller Transport 우선 (Callee Transport는 invalid일 수 있음)
                # AI Takeover 후 Callee Transport가 connection_lost될 수 있으므로 Caller Transport 사용
                if self.ai_mode:
                    _transport = self.caller_audio_transport or self.callee_audio_transport
                else:
                    _transport = self.callee_audio_transport or self.caller_audio_transport
                
                if not _transport or not self.caller_endpoint:
                    logger.error("rtp_tts_no_valid_transport",
                                call_id=self.media_session.call_id,
                                ai_mode=self.ai_mode,
                                has_caller_transport=self.caller_audio_transport is not None,
                                has_callee_transport=self.callee_audio_transport is not None,
                                note="TTS 전송 불가 - Transport 없음")
                    continue
                
                caller_ip = str(self.caller_endpoint.ip)
                caller_port = int(self.caller_endpoint.port)
                
                # 디버깅: PCM 청크당 생성된 RTP 패킷 수 로그 (첫 10개 + 100개마다)
                if packets_sent < 10 or packets_sent % 100 == 0:
                    logger.info("rtp_pcm_chunk_to_packets",
                               call_id=self.media_session.call_id,
                               progress="rtp_timing",
                               pcm_bytes=len(pcm_data),
                               rtp_packets_count=len(rtp_packets),
                               packets_sent_so_far=packets_sent,
                               note="PCM 청크 → RTP 패킷 변환")
                
                # ✅ 절대 시간 기반 스케줄링 - 첫 패킷에서 이미 base_time 초기화됨
                # 여기서는 재초기화하지 않음
                if not hasattr(self, '_rtp_base_time') or self._rtp_base_time is None:
                    # 안전장치: 이미 위에서 초기화되어야 하지만, 혹시 모를 경우 대비
                    self._rtp_base_time = time.perf_counter()
                    self._rtp_packets_sent_total = 0
                    self._rtp_last_send_time = self._rtp_base_time
                    logger.warning("rtp_base_time_late_init",
                                  call_id=self.media_session.call_id,
                                  note="RTP base_time이 늦게 초기화됨 (버그 가능성)")
                
                # 오차 누적 추적 (디버깅용)
                accumulated_error_ms = 0.0
                
                for idx, packet in enumerate(rtp_packets):
                    if not self._pipecat_mode:
                        break
                    
                    # RTP 헤더 (전송 전): seq/ts 로그·연속성 검사용
                    _rtp_seq_hdr = struct.unpack_from("!H", packet, 2)[0]
                    _rtp_ts_hdr = struct.unpack_from("!I", packet, 4)[0]
                    
                    # 절대 시간 기반: 목표 전송 시간 계산
                    target_time = self._rtp_base_time + (self._rtp_packets_sent_total * interval_sec)
                    now_before_sleep = time.perf_counter()
                    sleep_needed = target_time - now_before_sleep
                    
                    # 목표 시각보다 늦음 → "따라잡기" 버스트(수신 측에서 늘어짐·지터 유발 가능)
                    if sleep_needed < 0:
                        behind_schedule_count += 1
                        _late_ms = -sleep_needed * 1000.0
                        if behind_schedule_count <= 20 or behind_schedule_count % 50 == 0:
                            logger.warning(
                                "rtp_send_behind_schedule",
                                call_id=self.media_session.call_id,
                                progress="rtp_timing",
                                late_ms=round(_late_ms, 2),
                                behind_schedule_count=behind_schedule_count,
                                packets_sent_so_far=packets_sent,
                                chunk_inner_idx=idx,
                                rtp_seq=_rtp_seq_hdr,
                                rtp_ts=_rtp_ts_hdr,
                                pcm_queue_size=self._pipecat_pcm_queue.qsize(),
                                expected_from_base_ms=round(
                                    self._rtp_packets_sent_total * self._RTP_PACKET_MS, 2
                                ),
                                note="20ms 스케줄보다 늦게 전송 시도 — 이벤트 루프 지연·PCM 버스트·CPU 경합 추적",
                            )
                    
                    # ✅ Hybrid sleep: asyncio.sleep + busy-wait (정밀 타이밍)
                    # asyncio.sleep은 부정확하므로 목표 시간 1ms 전까지만 sleep
                    # 나머지는 busy-wait로 정밀 조정
                    if sleep_needed > 0.001:  # 1ms 이상이면 asyncio.sleep
                        await asyncio.sleep(sleep_needed - 0.001)
                    
                    # Busy-wait: 목표 시간까지 정밀 대기
                    while time.perf_counter() < target_time:
                        pass  # Busy-wait (CPU 사용하지만 정밀함)
                    
                    # 실제 전송 시간 기록
                    now_after_sleep = time.perf_counter()
                    actual_from_base_ms = (now_after_sleep - self._rtp_base_time) * 1000
                    expected_from_base_ms = self._rtp_packets_sent_total * self._RTP_PACKET_MS
                    current_error_ms = actual_from_base_ms - expected_from_base_ms
                    
                    # 이전 패킷과의 간격 (모니터링용)
                    if self._rtp_packets_sent_total > 0:
                        interval_from_prev_ms = (now_after_sleep - self._rtp_last_send_time) * 1000
                    else:
                        interval_from_prev_ms = 0.0
                    
                    # 디버깅: 첫 30개 패킷의 정확한 타이밍 로그
                    if packets_sent < 30:
                        logger.info("rtp_packet_timing_absolute",
                                   call_id=self.media_session.call_id,
                                   progress="rtp_timing",
                                   packet_seq=packets_sent,
                                   chunk_packet_idx=idx,
                                   expected_time_from_base_ms=round(expected_from_base_ms, 2),
                                   actual_time_from_base_ms=round(actual_from_base_ms, 2),
                                   timing_error_ms=round(current_error_ms, 2),
                                   interval_from_prev_ms=round(interval_from_prev_ms, 2),
                                   sleep_requested_ms=round(sleep_needed * 1000, 2) if sleep_needed > 0 else 0,
                                   note="절대 시간 기반 타이밍 (오차 누적 방지)")
                    
                    # 타이밍 위반 추적 (간격 기준)
                    if self._rtp_packets_sent_total > 0:
                        if abs(interval_from_prev_ms - self._RTP_PACKET_MS) > INTERVAL_TOLERANCE_MS:
                            interval_violations += 1
                            if interval_violations <= 5 or interval_violations % 50 == 0:
                                logger.warning(
                                    "rtp_interval_violation",
                                    call_id=self.media_session.call_id,
                                    progress="rtp_timing",
                                    expected_ms=self._RTP_PACKET_MS,
                                    actual_ms=round(interval_from_prev_ms, 1),
                                    violation_count=interval_violations,
                                    packets_sent=packets_sent,
                                    timing_error_ms=round(current_error_ms, 2),
                                    rtp_seq=_rtp_seq_hdr,
                                    rtp_ts=_rtp_ts_hdr,
                                    chunk_inner_idx=idx,
                                    pcm_queue_size=self._pipecat_pcm_queue.qsize(),
                                    note="20ms 간격 이탈 (절대 시간 오차 포함) — seq/ts로 패킷 단위 추적",
                                )
                    
                    # 누적 오차가 너무 크면 base_time 리셋 (1초 이상). Phase2 첫 패킷 이전에는 미적용.
                    if getattr(self, "_rtp_new_segment_after_empty", False):
                        if self._rtp_packets_sent_total >= 1:
                            self._rtp_new_segment_after_empty = False
                    if not getattr(self, "_rtp_new_segment_after_empty", False) and abs(current_error_ms) > 1000.0:
                        logger.warning("rtp_timing_drift_reset",
                                     call_id=self.media_session.call_id,
                                     progress="rtp_timing",
                                     accumulated_error_ms=round(current_error_ms, 2),
                                     packets_sent=packets_sent,
                                     note="누적 오차 1초 이상 → base_time 리셋")
                        self._rtp_base_time = time.perf_counter()
                        self._rtp_packets_sent_total = 0
                    elif abs(current_error_ms) > 100.0 and packets_sent % 50 == 0:
                        logger.warning("rtp_timing_drift_detected",
                                     call_id=self.media_session.call_id,
                                     progress="rtp_timing",
                                     accumulated_error_ms=round(current_error_ms, 2),
                                     packets_sent=packets_sent,
                                     note="누적 타이밍 오차 큼 (100ms 이상)")
                    
                    self._rtp_last_send_time = now_after_sleep
                    self._rtp_packets_sent_total += 1
                    
                    if not self._timing_first_tts_rtp_sent_logged:
                        self._timing_first_tts_rtp_sent_logged = True
                        from datetime import datetime
                        logger.info("timing_first_tts_rtp_sent_to_caller",
                                   call_id=self.media_session.call_id,
                                   progress="timing",
                                   ts_iso=datetime.now().isoformat(timespec="milliseconds"),
                                   note="TTS→RTP 첫 패킷 전송")
                    try:
                        # ✅ Transport 유효성 재확인 (connection_lost 후 None일 수 있음)
                        if not _transport or _transport.is_closing():
                            logger.error("rtp_transport_invalid_before_send",
                                        call_id=self.media_session.call_id,
                                        transport_type=type(_transport).__name__ if _transport else "None",
                                        is_closing=_transport.is_closing() if _transport else "N/A",
                                        note="Transport 무효 - TTS 전송 중단")
                            break
                        
                        # ✅ Windows Proactor 동시성 보호
                        async with self._sendto_lock:
                            _transport.sendto(packet, (caller_ip, caller_port))
                        packets_sent += 1
                        self.stats["rtp_tts_packets_sent"] += 1
                        
                        # RTP seq/ts 연속성 (단일 스트림에서 +1 / +160 기대)
                        if last_rtp_seq_sent is not None:
                            _exp_seq = (last_rtp_seq_sent + 1) & 0xFFFF
                            if _rtp_seq_hdr != _exp_seq:
                                logger.warning(
                                    "rtp_seq_discontinuity",
                                    call_id=self.media_session.call_id,
                                    progress="rtp_timing",
                                    expected_seq=_exp_seq,
                                    actual_seq=_rtp_seq_hdr,
                                    packets_sent=packets_sent,
                                    chunk_inner_idx=idx,
                                    note="RTP sequence 비연속 — 빌더 재생성·중복 전송·패킷 드롭 의심 시 확인",
                                )
                        if last_rtp_ts_sent is not None:
                            _exp_ts = (last_rtp_ts_sent + self._rtp_packet_builder.timestamp_increment) & 0xFFFFFFFF
                            if _rtp_ts_hdr != _exp_ts:
                                _delta = (_rtp_ts_hdr - last_rtp_ts_sent) & 0xFFFFFFFF
                                logger.warning(
                                    "rtp_timestamp_discontinuity",
                                    call_id=self.media_session.call_id,
                                    progress="rtp_timing",
                                    expected_ts=_exp_ts,
                                    actual_ts=_rtp_ts_hdr,
                                    delta_from_prev=_delta,
                                    packets_sent=packets_sent,
                                    chunk_inner_idx=idx,
                                    note="RTP timestamp 스텝 비정상 — 코덱/프레임 경계 불일치 추적",
                                )
                        last_rtp_seq_sent = _rtp_seq_hdr
                        last_rtp_ts_sent = _rtp_ts_hdr
                        
                        if interval_from_prev_ms > 0:
                            recent_intervals_ms.append(round(interval_from_prev_ms, 2))
                            if len(recent_intervals_ms) > 50:
                                recent_intervals_ms.pop(0)
                        if packets_sent > 0 and packets_sent % 50 == 0 and recent_intervals_ms:
                            _iv = recent_intervals_ms
                            logger.info(
                                "rtp_tts_send_window_stats",
                                call_id=self.media_session.call_id,
                                progress="rtp_timing",
                                window_size=len(_iv),
                                interval_min_ms=min(_iv),
                                interval_max_ms=max(_iv),
                                interval_avg_ms=round(sum(_iv) / len(_iv), 2),
                                interval_violations_cumulative=interval_violations,
                                behind_schedule_cumulative=behind_schedule_count,
                                pcm_queue_size=self._pipecat_pcm_queue.qsize(),
                                last_rtp_seq=_rtp_seq_hdr,
                                last_rtp_ts=_rtp_ts_hdr,
                                timing_error_ms=round(current_error_ms, 2),
                                note="최근 N패킷 간격 요약 — 늘어짐 원인(간격 과대/과소) 상관 분석용",
                            )
                    except Exception as send_err:
                        self.stats["rtp_tts_send_errors"] += 1
                        logger.error("rtp_sendto_failed",
                                   call_id=self.media_session.call_id,
                                   dest_addr=f"{caller_ip}:{caller_port}",
                                   error=str(send_err),
                                   error_type=type(send_err).__name__)
                        await asyncio.sleep(interval_sec)
                        continue
                    if packets_sent == 1:
                        logger.info("rtp_first_packet_sent",
                                   call_id=self.media_session.call_id,
                                   dest_ip=caller_ip,
                                   dest_port=caller_port,
                                   packet_size=len(packet),
                                   transport_type=type(_transport).__name__,
                                   note="첫 RTP 패킷 전송 성공")
                    if packets_sent % 100 == 0:
                        qsize = self._pipecat_pcm_queue.qsize()
                        logger.debug("rtp_sender_progress",
                                    call_id=self.media_session.call_id,
                                    packets_sent=packets_sent,
                                    pcm_queue_size=qsize,
                                    total_sent=self.stats["rtp_tts_packets_sent"],
                                    interval_violations=interval_violations,
                                    note="RTP 발송 진행")
                        if qsize == 0:
                            logger.info("rtp_tts_queue_depleted",
                                        call_id=self.media_session.call_id,
                                        packets_sent=packets_sent,
                                        note="PCM 큐 소진 — 다음 TTS 청크 지연 시 끊김/깨짐 가능")
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
            except asyncio.TimeoutError:
                empty_timeout_count += 1
                last_was_empty_timeout = True
                _kw = dict(
                    call_id=self.media_session.call_id,
                    empty_timeouts=empty_timeout_count,
                    packets_sent=packets_sent,
                    note="PCM 큐 대기 타임아웃 — 청크 간 갭이면 정상, 연속 다수면 끊김 가능",
                )
                if empty_timeout_count <= 2:
                    logger.debug("rtp_tts_queue_empty_timeout", **_kw)
                elif empty_timeout_count <= 5 or empty_timeout_count % 10 == 0:
                    logger.info("rtp_tts_queue_empty_timeout", **_kw)
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.stats["rtp_tts_send_errors"] += 1
                logger.error("pipecat_tts_sender_error",
                            call_id=self.media_session.call_id,
                            error=str(e),
                            error_type=type(e).__name__,
                            send_errors_total=self.stats["rtp_tts_send_errors"])

    def enable_pipecat_mode(self):
        """
        Pipecat 파이프라인 모드 활성화 (현재 기본 AI 응대 경로).

        config.pipeline_engine = "pipecat" (기본값) 일 때 호출됨.
        TTS→RTP: PCM 큐 + 단일 발송 루프로 안정화 (큐 적체·버스트 제거, 20ms 정확 전송).
        """
        self._pipecat_audio_queue = asyncio.Queue(maxsize=1000)
        self._pipecat_mode = True
        self.ai_mode = True  # AI 모드도 함께 활성화

        # RTP 패킷 빌더 생성 (TTS -> RTP 변환용)
        from src.ai_voicebot.pipecat.audio_utils import RTPPacketBuilder
        codec = getattr(self.media_session, 'codec', 'PCMU')
        self._rtp_packet_builder = RTPPacketBuilder(codec=codec)

        # TTS PCM 큐 (안정화): TTS가 PCM 청크만 넣고, 발송 루프에서 20ms 간격으로 변환·전송
        # maxsize=150 청크 ≈ 5초 분량 — 인사말 등 버스트 시 empty_timeout/끊김 완화 (권장: APP_LOG_AI_CALL_20260310_101436_ANALYSIS.md)
        self._pipecat_pcm_queue = asyncio.Queue(maxsize=150)
        
        # ✅ 절대 시간 기반 RTP 타이밍 변수 초기화
        self._rtp_base_time = None
        self._rtp_packets_sent_total = 0
        self._rtp_last_send_time = None
        self._rtp_new_segment_after_empty = False  # Phase2 등 큐 재개 시 1초 리셋 미적용 플래그
        
        # AEC (선택): aec-audio-processing 있으면 활성화
        from src.media.aec_processor import create_aec_processor
        self._aec_processor = create_aec_processor(16000, 1, 50)
        self._aec_near_buffer = b""
        if self._aec_processor:
            logger.info("aec_enabled", call_id=self.media_session.call_id, note="WebRTC AEC 활성화")
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.get_event_loop()
        self._pipecat_outgoing_task = loop.create_task(self._pipecat_tts_sender_loop())
        
        logger.info("pipecat_mode_enabled",
                    call_id=self.media_session.call_id,
                    codec=codec,
                    ssrc=self._rtp_packet_builder.ssrc,
                    caller_endpoint=f"{self.caller_endpoint.ip}:{self.caller_endpoint.port}",
                    has_transport=self.caller_audio_transport is not None or self.callee_audio_transport is not None,
                    note="Pipecat 모드: PCM 큐 + 단일 발송 루프 (20ms 패이싱)")
    
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
        
        # 디버깅: 스트림 시작 로그
        logger.info("pipecat_audio_stream_started",
                   call_id=self.media_session.call_id,
                   note="Input Transport가 오디오 스트림 읽기 시작")
        
        packet_count = 0
        while self._pipecat_mode:
            try:
                # 타임아웃을 5초로 늘려서 Google STT 스트림 타임아웃 방지
                pcm_data = await asyncio.wait_for(
                    self._pipecat_audio_queue.get(), timeout=5.0
                )
                if pcm_data is None:  # Sentinel for shutdown
                    break
                packet_count += 1
                
                # 첫 패킷과 100개마다 로그 (테스트 후 STT 경로 점검용)
                if packet_count == 1:
                    logger.info("stt_path_queue_first",
                               call_id=self.media_session.call_id,
                               pcm_len=len(pcm_data),
                               note="[STT 경로] 큐 → Input 첫 소비 (파이프라인이 큐를 읽기 시작)")
                    logger.info("pipecat_audio_stream_first_packet",
                               call_id=self.media_session.call_id,
                               pcm_len=len(pcm_data),
                               note="Input Transport가 첫 오디오 패킷 처리")
                elif packet_count % 100 == 0:
                    logger.debug("pipecat_audio_stream_progress",
                                call_id=self.media_session.call_id,
                                packets_processed=packet_count,
                                queue_size=self._pipecat_audio_queue.qsize())
                if packet_count > 0 and packet_count % 200 == 0:
                    logger.info("stt_path_queue_to_consumer",
                               call_id=self.media_session.call_id,
                               packets_consumed=packet_count,
                               queue_size=self._pipecat_audio_queue.qsize(),
                               note="[STT 경로] 큐 → Input Transport 소비 누적")
                if packet_count > 0 and packet_count % 300 == 0:
                    logger.info("stt_path_queue_yield_ok",
                               call_id=self.media_session.call_id,
                               packets_consumed=packet_count,
                               queue_size=self._pipecat_audio_queue.qsize(),
                               note="[STT 경로] 큐에서 꺼내 yield — 소비 정상 시 계속 증가")
                yield pcm_data
            except asyncio.TimeoutError:
                # 타임아웃 발생 시 로그 (STT 스트림 keep-alive를 위해 silence 전송 고려)
                logger.info("stt_path_queue_timeout",
                           call_id=self.media_session.call_id,
                           packets_consumed_so_far=packet_count,
                           queue_size=self._pipecat_audio_queue.qsize(),
                           note="[STT 경로] 5초간 큐 get 대기 (소비 지연 또는 RTP 없음)")
                if packet_count == 0:
                    logger.warning("pipecat_audio_stream_no_data",
                                  call_id=self.media_session.call_id,
                                  note="5초 동안 오디오 없음 - STT 타임아웃 위험")
                continue
            except Exception as e:
                logger.error("pipecat_audio_stream_error",
                           call_id=self.media_session.call_id,
                           error=str(e))
                break
        
        logger.info("pipecat_audio_stream_stopped",
                   call_id=self.media_session.call_id,
                   total_packets=packet_count)
    
    def send_audio_to_caller(self, pcm_data: bytes, sample_rate: int = 16000):
        """
        Pipecat TTS 오디오(PCM)를 PCM 큐에 넣음.
        실제 RTP 변환·전송은 _pipecat_tts_sender_loop에서 20ms 간격으로 수행(안정적 패이싱).
        큐 가득 시 put_nowait 실패 시 드롭(백프레셔는 발송 루프가 자연스럽게 유지).
        """
        if not self.ai_mode:
            logger.warning("send_audio_to_caller_not_ai_mode",
                          call_id=self.media_session.call_id,
                          note="AI 모드가 아닌데 send_audio_to_caller 호출됨")
            return
        if not getattr(self, '_pipecat_pcm_queue', None):
            logger.error("send_audio_to_caller_no_queue",
                        call_id=self.media_session.call_id,
                        note="PCM 큐 미초기화 - enable_pipecat_mode 필요")
            return
        if not self._rtp_packet_builder:
            from src.ai_voicebot.pipecat.audio_utils import RTPPacketBuilder
            codec = getattr(self.media_session, 'codec', 'PCMU')
            self._rtp_packet_builder = RTPPacketBuilder(codec=codec)
            logger.info("rtp_packet_builder_created",
                       call_id=self.media_session.call_id,
                       codec=codec,
                       ssrc=self._rtp_packet_builder.ssrc)
        
        try:
            pcm_len = len(pcm_data)
            self._pipecat_pcm_queue.put_nowait(pcm_data)
            qsize = self._pipecat_pcm_queue.qsize()
            if not hasattr(self, '_audio_chunks_logged'):
                self._audio_chunks_logged = 0
            if not hasattr(self, '_audio_chunks_total'):
                self._audio_chunks_total = 0
                self._audio_bytes_total = 0
            
            self._audio_chunks_total += 1
            self._audio_bytes_total += pcm_len
            
            # 디버깅: 첫 10개 + 10개마다 상세 로그
            if self._audio_chunks_logged < 10 or self._audio_chunks_total % 10 == 0:
                logger.info("pcm_chunk_queued",
                           call_id=self.media_session.call_id,
                           progress="rtp_timing",
                           chunk_seq=self._audio_chunks_total,
                           pcm_bytes=pcm_len,
                           queue_size_after=qsize,
                           total_bytes_queued=self._audio_bytes_total,
                           sample_rate=sample_rate,
                           estimated_duration_ms=round((pcm_len / 2 / sample_rate) * 1000, 1),
                           note="TTS PCM 청크를 큐에 추가 (발송 루프가 20ms 간격으로 소비)")
                self._audio_chunks_logged += 1
            elif pcm_len > 10000:
                logger.debug("send_audio_to_caller_success",
                           call_id=self.media_session.call_id,
                           pcm_len=pcm_len,
                           sample_rate=sample_rate,
                           queue_size=qsize,
                           codec=self._rtp_packet_builder.codec,
                           note="PCM 큐 투입 (발송 루프에서 20ms 간격 전송)")
            # 백로그 과다 시 1회 경고 (발송 지연·끊김 가능) — maxsize 150 기준 120에서 경고
            if qsize >= 120 and not getattr(self, '_pcm_backlog_warned', False):
                self._pcm_backlog_warned = True
                logger.warning("rtp_tts_pcm_queue_backlog_high",
                               call_id=self.media_session.call_id,
                               queue_size=qsize,
                               maxsize=self._pipecat_pcm_queue.maxsize,
                               note="PCM 큐 백로그 큼 — 발송 루프가 TTS 속도를 따라가지 못할 수 있음")
        except asyncio.QueueFull:
            self.stats["rtp_tts_packets_dropped"] += 1
            logger.warning("pipecat_pcm_queue_full_dropping",
                          call_id=self.media_session.call_id,
                          pcm_len=pcm_len,
                          queue_size=self._pipecat_pcm_queue.maxsize,
                          total_dropped=self.stats["rtp_tts_packets_dropped"],
                          note="PCM 큐 가득 - 청크 1개 드롭 (발송 지연 완화 후 재시도)")
        except Exception as e:
            logger.error("pipecat_audio_to_caller_error",
                         call_id=self.media_session.call_id,
                         pcm_len=len(pcm_data) if pcm_data else 0,
                         sample_rate=sample_rate,
                         error=str(e),
                         error_type=type(e).__name__)

    async def request_tts_flush(self):
        """
        (비활성화) 원래는 새 TTS 시작 시 PCM 큐를 비웠음. 현재는 순차 재생을 위해 no-op.
        나중에 시스템 안정화 후 필요 시 플러시 기능을 다시 넣을 수 있음.
        """
        pass

    def stop_pipecat_mode(self):
        """Pipecat 모드 정지 (PCM/오디오 큐·발송 태스크·AEC 포함)"""
        self._pipecat_mode = False
        
        # ✅ 절대 시간 기반 RTP 타이밍 통계 로그 출력
        if hasattr(self, '_rtp_packets_sent_total') and self._rtp_packets_sent_total > 0:
            total_packets = self._rtp_packets_sent_total
            expected_duration_ms = total_packets * self._RTP_PACKET_MS
            if hasattr(self, '_rtp_base_time') and hasattr(self, '_rtp_last_send_time'):
                actual_duration_ms = (self._rtp_last_send_time - self._rtp_base_time) * 1000
                timing_error_ms = actual_duration_ms - expected_duration_ms
                timing_error_pct = (timing_error_ms / expected_duration_ms * 100) if expected_duration_ms > 0 else 0
                
                logger.info("rtp_absolute_timing_summary",
                           call_id=self.media_session.call_id,
                           progress="rtp_timing",
                           total_packets_sent=total_packets,
                           expected_duration_ms=round(expected_duration_ms, 2),
                           actual_duration_ms=round(actual_duration_ms, 2),
                           timing_error_ms=round(timing_error_ms, 2),
                           timing_error_pct=round(timing_error_pct, 2),
                           note="절대 시간 기반 RTP 전송 완료 통계")
            
            # 타이밍 상태 리셋
            self._rtp_base_time = None
            self._rtp_packets_sent_total = 0
            self._rtp_last_send_time = None
            self._rtp_new_segment_after_empty = False
        
        self._aec_processor = None
        self._aec_near_buffer = b""
        if self._pipecat_audio_queue:
            try:
                self._pipecat_audio_queue.put_nowait(None)
            except asyncio.QueueFull:
                pass
        if getattr(self, '_pipecat_pcm_queue', None):
            try:
                self._pipecat_pcm_queue.put_nowait(None)
            except asyncio.QueueFull:
                pass
        if self._pipecat_outgoing_task and not self._pipecat_outgoing_task.done():
            self._pipecat_outgoing_task.cancel()
        self._pipecat_outgoing_task = None
        self._pipecat_pcm_queue = None
        try:
            logger.info("pipecat_mode_stopped", call_id=self.media_session.call_id)
        except (ValueError, OSError):
            pass  # 서버 종료 시 로그 파일이 이미 닫혀 있을 수 있음
    
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
    
    def _feed_bypass_stt_before_relay_skip(self, data: bytes) -> None:
        """remote 무효 등으로 relay·on_packet_received 가 생략될 때도 유저 간 STT에 RTP 전달."""
        try:
            self.relay_worker.feed_bypass_realtime_stt(self.socket_type, data)
        except Exception:
            pass
    
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
                        # 동기 콜백이므로 직접 전송 (단발성 STUN 응답)
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
                            # 동기 콜백이므로 직접 전송 (이벤트 루프가 순차 호출)
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
                            # 동기 콜백이므로 직접 전송 (이벤트 루프가 순차 호출)
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
                
                # ✅ AI 모드에서는 relay하지 않으므로 invalid_remote 검사 불필요 (이중 방어)
                if self.relay_worker.ai_mode:
                    return
                
                # ✅ Caller 측 소켓에서 remote가 무효(early bind / AI 전환 직후): relay 스킵, 경고 없음
                # caller_audio_rtp/rtcp의 remote는 callee인데, early bind 시 0.0.0.0:0 이므로
                # relay하면 안 되고, AI 전환 전 패킷도 이 경로로 오면 스킵만 하면 됨
                if self.socket_type in ("caller_audio_rtp", "caller_audio_rtcp"):
                    if not self.remote_endpoint or not self.remote_endpoint.ip or str(self.remote_endpoint.ip) == "0.0.0.0":
                        logger.debug("rtp_relay_skip_caller_invalid_remote",
                                   call_id=self.relay_worker.media_session.call_id,
                                   socket_type=self.socket_type,
                                   note="caller 측 소켓, remote 무효(early bind/AI). relay 스킵.")
                        self._feed_bypass_stt_before_relay_skip(data)
                        return
                    if self.remote_port is None or self.remote_port <= 0:
                        logger.debug("rtp_relay_skip_caller_invalid_port",
                                   call_id=self.relay_worker.media_session.call_id,
                                   socket_type=self.socket_type)
                        self._feed_bypass_stt_before_relay_skip(data)
                        return
                
                # ✅ 주소 유효성 검사 (Windows 에러 방지) — callee 측 등
                if not self.remote_endpoint or not self.remote_endpoint.ip or str(self.remote_endpoint.ip) == "0.0.0.0":
                    logger.warning("rtp_relay_skip_invalid_remote",
                                 call_id=self.relay_worker.media_session.call_id,
                                 socket_type=self.socket_type,
                                 ai_mode=self.relay_worker.ai_mode,
                                 note="remote_endpoint 무효(0.0.0.0 등). AI 모드에서는 relay 없음.")
                    self._feed_bypass_stt_before_relay_skip(data)
                    return
                
                if self.remote_port is None or self.remote_port <= 0:
                    logger.warning("rtp_relay_skip_invalid_port",
                                 call_id=self.relay_worker.media_session.call_id,
                                 socket_type=self.socket_type,
                                 port=self.remote_port)
                    self._feed_bypass_stt_before_relay_skip(data)
                    return
                
                # 주소 튜플 생성 (Windows 호환성)
                remote_addr = (str(self.remote_endpoint.ip), int(self.remote_port))
                
                # 동기 콜백이므로 직접 전송 (이벤트 루프가 순차 호출)
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

        # callee_audio_rtp 소켓이 닫히면 transport 참조 제거
        # → send_ai_audio가 다음 호출 시 None 체크로 early return 하거나 caller_audio_transport 폴백 사용
        if self.socket_type == "callee_audio_rtp":
            # AI 모드에서 Callee Transport가 끊긴 경우 Caller Transport로 폴백
            if self.relay_worker.ai_mode:
                logger.info("callee_transport_lost_in_ai_mode_fallback_to_caller",
                           call_id=self.relay_worker.media_session.call_id,
                           has_caller_transport=self.relay_worker.caller_audio_transport is not None,
                           note="AI 모드 - Caller Transport로 폴백 (정상 동작)")
            self.relay_worker.callee_audio_transport = None
            logger.info("callee_audio_transport_cleared",
                       call_id=self.relay_worker.media_session.call_id,
                       reason="connection_lost")

