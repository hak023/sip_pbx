"""SIP Endpoint 구현

PJSIP 기반 SIP 서버 Endpoint
"""

import signal
import sys
import asyncio
import random
import re
from typing import Optional, Dict, Tuple
from abc import ABC, abstractmethod

from src.common.logger import get_logger
from src.common.exceptions import SIPEndpointError, SIPTransportError
from src.config.models import Config
from src.sip_core.call_manager import CallManager
from src.media.session_manager import MediaSessionManager
from src.media.media_session import MediaMode
from src.media.port_pool import PortPoolManager
from src.media.sdp_parser import SDPParser, SDPManipulator
from src.media.rtp_relay import RTPRelayWorker, RTPEndpoint
from src.repositories.call_state_repository import CallStateRepository

logger = get_logger(__name__)

# PJSIP import 시도 (개발 환경에서는 없을 수 있음)
try:
    import pjsua2 as pj
    PJSIP_AVAILABLE = True
except ImportError:
    logger.warning("pjsip_not_available", 
                   message="PJSIP library not found. Using mock implementation.")
    PJSIP_AVAILABLE = False
    pj = None


class BaseSIPEndpoint(ABC):
    """SIP Endpoint 추상 기본 클래스"""
    
    @abstractmethod
    def start(self) -> None:
        """SIP 서버 시작"""
        pass
    
    @abstractmethod
    def stop(self) -> None:
        """SIP 서버 종료"""
        pass
    
    @abstractmethod
    def is_running(self) -> bool:
        """서버 실행 중 여부"""
        pass


class PJSIPEndpoint(BaseSIPEndpoint):
    """PJSIP 기반 SIP Endpoint 구현"""
    
    def __init__(self, config: Config):
        """초기화
        
        Args:
            config: 설정 객체
            
        Raises:
            SIPEndpointError: PJSIP 라이브러리를 사용할 수 없는 경우
        """
        if not PJSIP_AVAILABLE:
            raise SIPEndpointError(
                "PJSIP library is not available. "
                "Please install pjsua2: pip install pjsua2"
            )
        
        self.config = config
        self._running = False
        self._ep: Optional['pj.Endpoint'] = None
        self._transport: Optional['pj.TransportConfig'] = None
        
        # Signal handler 등록
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        logger.info("pjsip_endpoint_created", 
                   listen_ip=config.sip.listen_ip,
                   listen_port=config.sip.listen_port)
    
    def start(self) -> None:
        """SIP 서버 시작"""
        try:
            # Endpoint 생성 및 초기화
            self._ep = pj.Endpoint()
            self._ep.libCreate()
            
            # Endpoint 설정
            ep_cfg = pj.EpConfig()
            ep_cfg.logConfig.level = 4  # INFO level
            ep_cfg.logConfig.consoleLevel = 4
            
            self._ep.libInit(ep_cfg)
            
            # Transport 설정
            transport_cfg = pj.TransportConfig()
            transport_cfg.port = self.config.sip.listen_port
            
            # Transport 타입에 따라 생성
            transport_type = self._get_transport_type()
            self._transport = self._ep.transportCreate(transport_type, transport_cfg)
            
            # Endpoint 시작
            self._ep.libStart()
            
            self._running = True
            
            logger.info("sip_server_started",
                       listen_ip=self.config.sip.listen_ip,
                       listen_port=self.config.sip.listen_port,
                       transport=self.config.sip.transport)
            
        except Exception as e:
            logger.error("sip_server_start_failed", error=str(e), exc_info=True)
            raise SIPEndpointError(f"Failed to start SIP server: {e}") from e
    
    def stop(self) -> None:
        """SIP 서버 종료"""
        if not self._running:
            logger.warning("sip_server_not_running", 
                          message="Attempted to stop server that is not running")
            return
        
        try:
            logger.info("sip_server_stopping", message="Gracefully shutting down SIP server")
            
            # 진행 중인 트랜잭션 정리 대기
            if self._ep:
                # Transport 해제
                if self._transport:
                    self._ep.transportClose(self._transport)
                
                # Endpoint 종료
                self._ep.libDestroy()
                self._ep = None
            
            self._running = False
            
            logger.info("sip_server_stopped", message="SIP server stopped successfully")
            
        except Exception as e:
            logger.error("sip_server_stop_failed", error=str(e), exc_info=True)
            raise SIPEndpointError(f"Failed to stop SIP server: {e}") from e
    
    def is_running(self) -> bool:
        """서버 실행 중 여부"""
        return self._running
    
    def _get_transport_type(self) -> 'pj.TransportType':
        """설정에서 Transport 타입 반환"""
        transport_map = {
            "udp": pj.PJSIP_TRANSPORT_UDP,
            "tcp": pj.PJSIP_TRANSPORT_TCP,
            "tls": pj.PJSIP_TRANSPORT_TLS,
        }
        
        transport_type = transport_map.get(self.config.sip.transport.lower())
        if transport_type is None:
            raise SIPTransportError(
                f"Unsupported transport type: {self.config.sip.transport}"
            )
        
        return transport_type
    
    def _signal_handler(self, signum: int, frame) -> None:
        """시그널 핸들러 (SIGINT, SIGTERM)"""
        signal_name = signal.Signals(signum).name
        logger.info("signal_received", signal=signal_name, 
                   message="Initiating graceful shutdown")
        
        self.stop()
        sys.exit(0)


class MockSIPEndpoint(BaseSIPEndpoint):
    """Mock SIP Endpoint (개발/테스트용)
    
    실제 UDP 소켓을 열고 기본적인 SIP 메시지를 수신합니다.
    완전한 B2BUA 기능 포함 (시그널링 + 미디어 릴레이)
    """
    
    def __init__(self, config: Config):
        """초기화
        
        Args:
            config: 설정 객체
        """
        self.config = config
        self._running = False
        self._socket = None
        self._listen_task = None
        self._sip_log_file = None
        
        # 등록된 사용자 저장소: {username: {'ip', 'port', 'contact', 'from'}}
        self._registered_users: Dict[str, Dict] = {}
        
        # 활성 통화 저장소: {call_id: {'caller_addr', 'callee_addr', 'caller_tag', 'callee_tag', ...}}
        self._active_calls: Dict[str, Dict] = {}
        
        # B2BUA Call Mapping: {original_call_id: new_call_id}
        self._call_mapping: Dict[str, str] = {}
        
        # Call Manager 및 Media Session Manager 초기화
        self._port_pool = PortPoolManager(config=config.media.port_pool)
        
        # MediaMode 변환 (config.models.MediaMode → media_session.MediaMode)
        media_mode = MediaMode.BYPASS if config.media.mode.value == "bypass" else MediaMode.REFLECTING
        
        self._media_session_manager = MediaSessionManager(
            port_pool=self._port_pool,
            default_mode=media_mode
        )
        self._call_repository = CallStateRepository()
        self._call_manager = CallManager(
            call_repository=self._call_repository,
            media_session_manager=self._media_session_manager,
            b2bua_ip=config.sip.listen_ip
        )
        
        # RTP Relay Workers: {call_id: RTPRelayWorker}
        self._rtp_workers: Dict[str, RTPRelayWorker] = {}
        
        # SIP 트래픽 로그 파일 설정
        self._setup_sip_traffic_log()
        
        logger.warning("mock_b2bua_endpoint_created",
                      message="Using mock SIP endpoint with full B2BUA (signaling + media relay)")
    
    @property
    def media_session_manager(self) -> MediaSessionManager:
        """MediaSessionManager 접근자"""
        return self._media_session_manager
    
    @property
    def port_pool(self) -> PortPoolManager:
        """PortPoolManager 접근자"""
        return self._port_pool
    
    @property
    def call_manager(self) -> CallManager:
        """CallManager 접근자"""
        return self._call_manager
    
    def _setup_sip_traffic_log(self) -> None:
        """SIP 트래픽 로그 파일 설정"""
        from pathlib import Path
        from datetime import datetime
        
        # 로그 디렉토리 생성
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        
        # 로그 파일 경로 (날짜별)
        timestamp = datetime.now().strftime("%Y%m%d")
        log_file_path = log_dir / f"sip_traffic_{timestamp}.log"
        
        try:
            self._sip_log_file = open(log_file_path, 'a', encoding='utf-8')
            logger.info("sip_traffic_log_opened", log_file=str(log_file_path))
        except Exception as e:
            logger.error("sip_traffic_log_open_failed", error=str(e))
            self._sip_log_file = None
    
    def _log_sip_message(self, direction: str, message: str, addr: tuple) -> None:
        """SIP 메시지를 파일에 로깅
        
        Args:
            direction: 'RECV' 또는 'SEND'
            message: SIP 메시지
            addr: 주소 (ip, port)
        """
        from datetime import datetime
        
        if not self._sip_log_file:
            return
        
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            emoji = "📥" if direction == "RECV" else "📤"
            
            log_entry = (
                f"\n{'='*70}\n"
                f"{emoji} SIP {direction} [{timestamp}] {addr[0]}:{addr[1]}\n"
                f"{'='*70}\n"
                f"{message}\n"
                f"{'='*70}\n"
            )
            
            self._sip_log_file.write(log_entry)
            self._sip_log_file.flush()  # 즉시 디스크에 쓰기
            
        except Exception as e:
            logger.error("sip_traffic_log_write_failed", error=str(e))
    
    async def _handle_sip_message(self, data: bytes, addr: tuple) -> None:
        """SIP 메시지 처리
        
        Args:
            data: 수신한 데이터
            addr: 송신자 주소 (ip, port)
        """
        try:
            # 빈 패킷 무시
            if len(data) == 0:
                logger.debug("empty_packet_received", from_addr=f"{addr[0]}:{addr[1]}")
                return
            
            # UTF-8 디코딩 시도
            try:
                message = data.decode('utf-8')
            except UnicodeDecodeError:
                # 디코딩 실패 시 Latin-1로 시도 (SIP는 ASCII 기반)
                try:
                    message = data.decode('latin-1')
                    logger.warning("decode_fallback_to_latin1", from_addr=f"{addr[0]}:{addr[1]}")
                except Exception as e:
                    logger.error("decode_failed", error=str(e), 
                               raw_bytes=data[:100].hex(), from_addr=f"{addr[0]}:{addr[1]}")
                    return
            
            # 빈 메시지 또는 너무 짧은 메시지 무시
            message_stripped = message.strip()
            if len(message_stripped) < 10:
                logger.debug("message_too_short", 
                           size=len(data),
                           raw_bytes=data.hex(),
                           from_addr=f"{addr[0]}:{addr[1]}")
                return
            
            # SIP 메서드 파싱
            lines = message.split('\r\n')
            if not lines or not lines[0]:
                logger.warning("no_request_line", from_addr=f"{addr[0]}:{addr[1]}")
                return
                
            request_line = lines[0].strip()
            parts = request_line.split()
            if len(parts) < 2:
                logger.warning("invalid_request_line", 
                             request_line=request_line,
                             from_addr=f"{addr[0]}:{addr[1]}")
                return
            
            method = parts[0]
            
            # 📥 RECV 로그 (콘솔 + 파일)
            print(f"\n{'='*70}")
            print(f"📥 SIP RECV from {addr[0]}:{addr[1]} ({len(data)} bytes)")
            print(f"{'='*70}")
            print(message)
            print(f"{'='*70}\n")
            
            # 파일에 로깅
            self._log_sip_message("RECV", message, addr)
            
            logger.info("sip_recv",
                       direction="RECV",
                       method=method,
                       from_addr=f"{addr[0]}:{addr[1]}",
                       size=len(data))
            
            # 응답 생성 및 전송
            response = None
            if method == 'OPTIONS':
                response = self._create_options_response(message, addr)
                if response:
                    self._send_response(response, addr)
            elif method == 'REGISTER':
                response = self._handle_register(message, addr)
                if response:
                    self._send_response(response, addr)
            elif method == 'INVITE':
                # B2BUA INVITE 처리 (비동기)
                asyncio.create_task(self._handle_invite_b2bua(message, addr))
            elif method == 'ACK':
                # ACK 처리 (SIP Dialog 완료, RTP는 200 OK 시점에 이미 시작됨)
                self._handle_ack(message, addr)
            elif method == 'BYE':
                # BYE 처리 (세션 종료)
                asyncio.create_task(self._handle_bye(message, addr))
            elif method == 'CANCEL':
                # CANCEL 처리
                asyncio.create_task(self._handle_cancel(message, addr))
            else:
                # SIP 응답 메시지 (180, 200 OK 등)
                if message.startswith('SIP/2.0'):
                    asyncio.create_task(self._handle_sip_response(message, addr))
                else:
                    logger.warning("sip_method_not_implemented", method=method)
                    response = self._create_not_implemented_response(message, addr)
                    if response:
                        self._send_response(response, addr)
                    
        except Exception as e:
            logger.error("sip_message_handling_error", error=str(e), addr=addr)
    
    def _send_response(self, response: str, addr: tuple) -> None:
        """응답 전송 및 로깅
        
        Args:
            response: SIP 응답 메시지
            addr: 대상 주소 (ip, port)
        """
        self._socket.sendto(response.encode('utf-8'), addr)
        
        # 📤 SEND 로그 (콘솔 + 파일)
        print(f"\n{'='*70}")
        print(f"📤 SIP SEND to {addr[0]}:{addr[1]}")
        print(f"{'='*70}")
        print(response)
        print(f"{'='*70}\n")
        
        # 파일에 로깅
        self._log_sip_message("SEND", response, addr)
        
        # 메서드 추출
        lines = response.split('\r\n')
        if lines and ' ' in lines[0]:
            parts = lines[0].split()
            status_code = parts[1] if len(parts) > 1 else 'UNKNOWN'
        else:
            status_code = 'UNKNOWN'
        
        logger.info("sip_send",
                   direction="SEND",
                   status_code=status_code,
                   to_addr=f"{addr[0]}:{addr[1]}",
                   size=len(response))
    
    def _extract_username(self, sip_uri: str) -> str:
        """SIP URI에서 username 추출
        
        Args:
            sip_uri: SIP URI (예: <sip:1004@10.62.164.233>)
            
        Returns:
            str: username (없으면 빈 문자열)
        """
        import re
        # <sip:username@domain> 또는 sip:username@domain 형식
        match = re.search(r'sip:([^@;>]+)@', sip_uri)
        if match:
            return match.group(1)
        return ''
    
    def _extract_tag(self, header: str) -> Optional[str]:
        """헤더에서 tag 파라미터 추출
        
        Args:
            header: SIP 헤더 (From, To 등)
            
        Returns:
            str: tag 값 (없으면 None)
        """
        match = re.search(r';tag=([^;>\s]+)', header)
        if match:
            return match.group(1)
        return None
    
    def _extract_sdp_body(self, message: str) -> Optional[str]:
        """SIP 메시지에서 SDP body 추출
        
        Args:
            message: 전체 SIP 메시지
            
        Returns:
            str: SDP body (없으면 None)
        """
        # 헤더와 body는 \r\n\r\n으로 구분
        parts = message.split('\r\n\r\n', 1)
        if len(parts) > 1 and parts[1].strip():
            return parts[1].strip()
        return None
    
    async def _handle_sip_response(self, response: str, addr: tuple) -> None:
        """SIP 응답 메시지 처리 (180, 200 OK 등)
        
        Args:
            response: SIP 응답 메시지
            addr: 송신자 주소
        """
        try:
            # 응답 코드 추출
            lines = response.split('\r\n')
            if not lines:
                return
            
            status_line = lines[0]
            parts = status_line.split()
            if len(parts) < 3:
                return
            
            status_code = parts[1]
            call_id = self._extract_header(response, 'Call-ID')
            cseq = self._extract_header(response, 'CSeq')
            
            print(f"\n📥 SIP Response: {status_code} for Call-ID: {call_id}")
            
            # B2BUA Call-ID 매핑 확인
            original_call_id = self._call_mapping.get(call_id)
            if not original_call_id or original_call_id not in self._active_calls:
                logger.debug("response_for_unknown_call", call_id=call_id)
                return
            
            call_info = self._active_calls[original_call_id]
            
            # 응답 릴레이
            if status_code in ['180', '183']:  # Ringing, Session Progress
                print(f"🔔 Relaying {status_code} to caller...")
                # ⚠️ 중요: 180 Ringing에서도 To tag를 추출해야 함!
                # RFC 3261: Early Dialog 생성을 위해 180부터 tag가 있어야 함
                to_hdr = self._extract_header(response, 'To')
                callee_tag = self._extract_tag(to_hdr)
                if callee_tag and not call_info.get('callee_tag'):
                    call_info['callee_tag'] = callee_tag
                    logger.info("callee_tag_from_180", 
                               call_id=original_call_id, 
                               callee_tag=callee_tag)
                
                await self._relay_response_to_caller(response, call_info)
            
            elif status_code == '200' and 'INVITE' in cseq:  # 200 OK for INVITE
                print(f"✅ Relaying 200 OK to caller...")
                # Callee tag 저장 (180에서 이미 저장되었을 수 있음)
                to_hdr = self._extract_header(response, 'To')
                callee_tag = self._extract_tag(to_hdr)
                if callee_tag:
                    # 180의 tag와 일치하는지 확인
                    existing_tag = call_info.get('callee_tag')
                    if existing_tag and existing_tag != callee_tag:
                        logger.warning("callee_tag_mismatch",
                                     call_id=original_call_id,
                                     tag_180=existing_tag,
                                     tag_200=callee_tag)
                    call_info['callee_tag'] = callee_tag
                call_info['state'] = 'answered'
                
                await self._relay_response_to_caller(response, call_info)
                print(f"📞 Call answered! Waiting for ACK...")
            
            elif status_code == '200' and 'BYE' in cseq:  # 200 OK for BYE
                print(f"👋 Call terminated")
                self._cleanup_call(original_call_id)
            
        except Exception as e:
            logger.error("response_handling_error", error=str(e))
    
    async def _relay_response_to_caller(self, callee_response: str, call_info: Dict) -> None:
        """Callee의 응답을 Caller에게 릴레이
        
        Args:
            callee_response: Callee로부터 받은 응답
            call_info: 통화 정보
        """
        try:
            # 원본 INVITE의 헤더를 사용해서 응답 생성
            lines = callee_response.split('\r\n')
            if not lines:
                return
                
            status_line = lines[0]  # SIP/2.0 200 OK 등
            
            # 원본 Call-ID 찾기
            original_call_id = None
            for orig_id, new_id in self._call_mapping.items():
                if new_id == call_info['b2bua_call_id']:
                    original_call_id = orig_id
                    break
            
            if not original_call_id:
                logger.error("original_call_id_not_found", b2bua_call_id=call_info['b2bua_call_id'])
                return
            
            # 원본 INVITE에서 Via, From, To, CSeq를 저장해야 함
            # 지금은 call_info에서 복원
            from_hdr = call_info['original_from']
            to_hdr = call_info['original_to']
            if call_info.get('callee_tag'):
                to_hdr += f";tag={call_info['callee_tag']}"
            
            # 원본 Via와 branch를 저장해야 함 - call_info에 추가 필요
            via_branch = call_info.get('original_via_branch', 'z9hG4bK-unknown')
            via = f"SIP/2.0/UDP {call_info['caller_addr'][0]}:{call_info['caller_addr'][1]};branch={via_branch};rport"
            
            # Callee 응답에서 추가 헤더 복사 (Contact, Allow 등)
            allow_hdr = self._extract_header(callee_response, 'Allow')
            
            # SDP 추출 (있으면)
            callee_sdp = self._extract_sdp_body(callee_response)
            
            # B2BUA IP 가져오기
            b2bua_ip = self.config.sip.listen_ip
            if b2bua_ip == "0.0.0.0":
                import socket
                try:
                    b2bua_ip = socket.gethostbyname(socket.gethostname())
                except:
                    b2bua_ip = "127.0.0.1"
            
            # Contact 헤더를 B2BUA 주소로 rewrite (RFC 3261)
            # 200 OK의 Contact가 ACK의 Request-URI가 되므로 B2BUA 주소여야 함!
            contact_hdr = f"<sip:{call_info['callee_username']}@{b2bua_ip}:{self.config.sip.listen_port}>"
            
            # 📝 Callee SDP Rewrite (200 OK 응답)
            rewritten_sdp = None
            if callee_sdp:
                print(f"📝 Rewriting Callee SDP for 200 OK response...")
                
                # MediaSession에 Callee SDP 업데이트
                try:
                    self.media_session_manager.update_callee_sdp(original_call_id, callee_sdp)
                    media_session = self.media_session_manager.get_session(original_call_id)
                    
                    if media_session:
                        # 1. 벤더 특정 속성 제거 (a=X-nat:0 등)
                        rewritten_sdp = SDPManipulator.remove_vendor_attributes(callee_sdp)
                        
                        # 2. Connection IP를 B2BUA IP로 교체
                        rewritten_sdp = SDPManipulator.replace_connection_ip(rewritten_sdp, b2bua_ip)
                        
                        # 3. Audio 포트를 Caller Leg 할당 포트로 교체
                        caller_audio_port = media_session.caller_leg.get_audio_rtp_port()
                        caller_audio_rtcp_port = media_session.caller_leg.get_audio_rtcp_port()
                        
                        if caller_audio_port:
                            rewritten_sdp = SDPManipulator.replace_media_port(rewritten_sdp, "audio", caller_audio_port)
                            print(f"   ✅ Callee SDP rewritten: c={b2bua_ip}, m=audio {caller_audio_port}")
                        
                        # 4. RTCP 속성도 B2BUA 포트로 교체
                        if caller_audio_rtcp_port:
                            rewritten_sdp = SDPManipulator.replace_rtcp_attribute(rewritten_sdp, "audio", caller_audio_rtcp_port, b2bua_ip)
                            print(f"   ✅ RTCP rewritten: a=rtcp:{caller_audio_rtcp_port} IN IP4 {b2bua_ip}")
                        
                        # 🎵 5. RTP Relay 시작 (200 OK 시점에!)
                        # RFC 3261: 미디어는 200 OK 교환 직후 시작 (ACK 기다리지 않음)
                        print(f"🎵 Starting RTP Relay (at 200 OK)...")
                        rtp_success = await self._start_rtp_relay(original_call_id)
                        
                        if not rtp_success:
                            print(f"❌ RTP Relay start failed at 200 OK!")
                            logger.error("rtp_relay_start_failed_at_200ok", call_id=original_call_id)
                            # RTP 실패해도 200 OK는 전송 (SIP signaling 우선)
                        else:
                            print(f"✅ RTP Relay started successfully!")
                        
                        # TODO: Video 지원 시 video 포트도 교체
                    else:
                        logger.warning("media_session_not_found_for_sdp_rewrite", call_id=original_call_id)
                        rewritten_sdp = callee_sdp  # Fallback: SDP 그대로
                        
                except Exception as sdp_err:
                    logger.error("callee_sdp_rewrite_error", error=str(sdp_err), exc_info=True)
                    rewritten_sdp = callee_sdp  # Fallback: SDP 그대로
            
            # 응답 구성
            response_to_caller = f"{status_line}\r\n"
            response_to_caller += f"Via: {via}\r\n"
            response_to_caller += f"From: {from_hdr}\r\n"
            response_to_caller += f"To: {to_hdr}\r\n"
            response_to_caller += f"Call-ID: {original_call_id}\r\n"
            response_to_caller += "CSeq: 1 INVITE\r\n"
            response_to_caller += f"Contact: {contact_hdr}\r\n"
            if allow_hdr:
                response_to_caller += f"Allow: {allow_hdr}\r\n"
            
            # SDP가 있으면 추가 (Rewritten SDP 사용)
            if rewritten_sdp:
                response_to_caller += "Content-Type: application/sdp\r\n"
                response_to_caller += f"Content-Length: {len(rewritten_sdp)}\r\n"
                response_to_caller += "\r\n"
                response_to_caller += rewritten_sdp
            else:
                response_to_caller += "Content-Length: 0\r\n"
                response_to_caller += "\r\n"
            
            self._send_response(response_to_caller, call_info['caller_addr'])
            
        except Exception as e:
            logger.error("relay_response_error", error=str(e), exc_info=True)
    
    def _handle_ack(self, request: str, addr: tuple) -> None:
        """ACK 처리 (SIP Dialog 완료)
        
        RTP Relay는 이미 200 OK 시점에 시작되었으므로,
        ACK는 단순히 Callee에게 전달하고 호를 active 상태로 표시합니다.
        
        Args:
            request: ACK 요청
            addr: 송신자 주소
        """
        call_id = self._extract_header(request, 'Call-ID')
        
        if call_id not in self._active_calls:
            return
        
        call_info = self._active_calls[call_id]
        print(f"\n✅ ACK received for call {call_id}")
        
        # Callee에게 ACK 전달
        new_call_id = call_info['b2bua_call_id']
        callee_addr = call_info['callee_addr']
        
        # B2BUA IP 가져오기
        b2bua_ip = self.config.sip.listen_ip
        if b2bua_ip == "0.0.0.0":
            import socket
            try:
                b2bua_ip = socket.gethostbyname(socket.gethostname())
            except:
                b2bua_ip = "127.0.0.1"
        
        # B2BUA가 INVITE에서 사용한 From tag와 동일하게 설정
        b2bua_from_tag = call_info.get('b2bua_from_tag', 'b2bua')
        
        ack_to_callee = (
            f"ACK sip:{call_info['callee_username']}@{callee_addr[0]}:{callee_addr[1]} SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP {b2bua_ip}:{self.config.sip.listen_port};branch=z9hG4bK{random.randint(100000, 999999)}\r\n"
            f"From: <sip:{call_info['caller_username']}@{b2bua_ip}>;tag={b2bua_from_tag}\r\n"
            f"To: <sip:{call_info['callee_username']}@{b2bua_ip}>;tag={call_info.get('callee_tag', 'unknown')}\r\n"
            f"Call-ID: {new_call_id}\r\n"
            "CSeq: 1 ACK\r\n"
            "Max-Forwards: 70\r\n"
            "Content-Length: 0\r\n"
            "\r\n"
        )
        
        self._send_response(ack_to_callee, callee_addr)
        
        call_info['state'] = 'active'
        print(f"✅ Call is now ACTIVE! (RTP already relaying)")
        print(f"   {call_info['caller_username']} <-> {call_info['callee_username']}")
        
        logger.info("call_established",
                   caller=call_info['caller_username'],
                   callee=call_info['callee_username'],
                   call_id=call_id)
    
    async def _start_rtp_relay(self, call_id: str) -> bool:
        """RTP Relay 시작 (비동기)
        
        Args:
            call_id: Call-ID
            
        Returns:
            성공 여부 (True: 성공, False: 실패)
        """
        try:
            print(f"🔍 DEBUG: Attempting to start RTP relay for call_id: {call_id}")
            media_session = self.media_session_manager.get_session(call_id)
            print(f"🔍 DEBUG: MediaSession found: {media_session is not None}")
            
            if not media_session:
                logger.error("media_session_not_found_for_rtp", call_id=call_id)
                print(f"❌ MediaSession not found for RTP relay")
                return False
            
            # Caller/Callee SDP 정보 확인
            print(f"🔍 DEBUG: Caller IP: {media_session.caller_leg.original_ip}, Port: {media_session.caller_leg.original_audio_port}")
            print(f"🔍 DEBUG: Callee IP: {media_session.callee_leg.original_ip}, Port: {media_session.callee_leg.original_audio_port}")
            
            # None 체크
            if not media_session.caller_leg.original_ip or not media_session.caller_leg.original_audio_port:
                logger.error("caller_sdp_info_missing", call_id=call_id)
                print(f"❌ Caller SDP info missing!")
                return False
            
            if not media_session.callee_leg.original_ip or not media_session.callee_leg.original_audio_port:
                logger.error("callee_sdp_info_missing", call_id=call_id)
                print(f"❌ Callee SDP info missing!")
                return False
            
            # Caller/Callee Endpoint 정보 (SDP에서 가져온 원본 IP/Port)
            caller_rtp_endpoint = RTPEndpoint(
                ip=media_session.caller_leg.original_ip,
                port=media_session.caller_leg.original_audio_port
            )
            callee_rtp_endpoint = RTPEndpoint(
                ip=media_session.callee_leg.original_ip,
                port=media_session.callee_leg.original_audio_port
            )
            
            print(f"🔍 DEBUG: Creating RTP Worker...")
            # RTP Relay Worker 생성
            rtp_worker = RTPRelayWorker(
                media_session=media_session,
                caller_endpoint=caller_rtp_endpoint,
                callee_endpoint=callee_rtp_endpoint
            )
            
            print(f"🔍 DEBUG: Starting RTP Worker...")
            # RTP Worker 시작
            try:
                await rtp_worker.start()
                logger.info("rtp_worker_started_successfully", call_id=call_id)
                print(f"✅ RTP Worker started successfully!")
            except Exception as e:
                logger.error("rtp_worker_start_failed", call_id=call_id, error=str(e), exc_info=True)
                print(f"❌ RTP Worker start failed: {e}")
                import traceback
                traceback.print_exc()
                return False
            
            # Worker 저장 (종료 시 cleanup)
            self._rtp_workers[call_id] = rtp_worker
            
            print(f"🎵 RTP Relay started!")
            print(f"   Caller: {caller_rtp_endpoint}")
            print(f"   Callee: {callee_rtp_endpoint}")
            print(f"   B2BUA Ports: caller={media_session.caller_leg.allocated_ports[:2]}, callee={media_session.callee_leg.allocated_ports[:2]}")
            
            logger.info("rtp_relay_started",
                       call_id=call_id,
                       caller_endpoint=str(caller_rtp_endpoint),
                       callee_endpoint=str(callee_rtp_endpoint))
            
            return True
                
        except Exception as rtp_err:
            logger.error("rtp_relay_start_error", call_id=call_id, error=str(rtp_err), exc_info=True)
            print(f"❌ RTP Relay start error: {rtp_err}")
            import traceback
            traceback.print_exc()
            return False
    
    async def _handle_bye(self, request: str, addr: tuple) -> None:
        """BYE 처리 (세션 종료)
        
        Args:
            request: BYE 요청
            addr: 송신자 주소
        """
        try:
            call_id = self._extract_header(request, 'Call-ID')
            
            logger.info("bye_received", call_id=call_id, from_addr=f"{addr[0]}:{addr[1]}")
            
            if call_id not in self._active_calls:
                logger.warning("bye_unknown_call", call_id=call_id)
                # 그래도 200 OK는 보내줘야 함
                via = self._extract_header(request, 'Via')
                from_hdr = self._extract_header(request, 'From')
                to_hdr = self._extract_header(request, 'To')
                cseq = self._extract_header(request, 'CSeq')
                
                bye_response = (
                    "SIP/2.0 200 OK\r\n"
                    f"Via: {via}\r\n"
                    f"From: {from_hdr}\r\n"
                    f"To: {to_hdr}\r\n"
                    f"Call-ID: {call_id}\r\n"
                    f"CSeq: {cseq}\r\n"
                    "Content-Length: 0\r\n"
                    "\r\n"
                )
                self._send_response(bye_response, addr)
                return
            
            call_info = self._active_calls[call_id]
            print(f"\n👋 BYE received for call {call_id}")
            
            # 200 OK 응답
            via = self._extract_header(request, 'Via')
            from_hdr = self._extract_header(request, 'From')
            to_hdr = self._extract_header(request, 'To')
            cseq = self._extract_header(request, 'CSeq')
            
            bye_response = (
                "SIP/2.0 200 OK\r\n"
                f"Via: {via}\r\n"
                f"From: {from_hdr}\r\n"
                f"To: {to_hdr}\r\n"
                f"Call-ID: {call_id}\r\n"
                f"CSeq: {cseq}\r\n"
                "Content-Length: 0\r\n"
                "\r\n"
            )
            self._send_response(bye_response, addr)
            logger.info("bye_response_sent", call_id=call_id)
            
            # 원본 Call-ID 가져오기 (MediaSession cleanup용)
            original_call_id = call_info.get('original_call_id', call_id)
            
            # 상대방을 결정 (From tag를 기반으로)
            from_tag = self._extract_tag(from_hdr)
            is_from_caller = (from_tag == call_info.get('caller_tag'))
            
            print(f"🔍 DEBUG: BYE from {'Caller' if is_from_caller else 'Callee'}")
            print(f"   Caller tag: {call_info.get('caller_tag')}, From tag: {from_tag}")
            
            # 상대방에게 BYE 전달
            if is_from_caller:
                print(f"📤 Forwarding BYE from Caller to Callee ({call_info['callee_username']})")
                # Caller가 BYE를 보냈으므로 Callee에게 전달
                other_call_id = call_info['b2bua_call_id'] if call_id == original_call_id else original_call_id
                other_addr = call_info['callee_addr']
                other_username = call_info['callee_username']
                # B2BUA가 Callee에게 보낸 INVITE의 From tag 사용
                from_username = call_info['caller_username']
                from_tag = call_info.get('b2bua_from_tag', 'b2bua')
                to_tag = call_info.get('callee_tag', '')
            else:
                print(f"📤 Forwarding BYE from Callee to Caller ({call_info['caller_username']})")
                # Callee가 BYE를 보냈으므로 Caller에게 전달
                other_call_id = original_call_id if call_id == call_info['b2bua_call_id'] else call_info['b2bua_call_id']
                other_addr = call_info['caller_addr']
                other_username = call_info['caller_username']
                # B2BUA가 Caller에게 보낸 응답의 To tag 사용 (원본 INVITE의 From tag)
                from_username = call_info['callee_username']
                from_tag = call_info.get('callee_tag', 'b2bua')
                to_tag = call_info.get('caller_tag', '')
            
            # B2BUA IP 가져오기
            b2bua_ip = self.config.sip.listen_ip
            if b2bua_ip == "0.0.0.0":
                import socket
                try:
                    b2bua_ip = socket.gethostbyname(socket.gethostname())
                except:
                    b2bua_ip = "127.0.0.1"
            
            to_tag_str = f";tag={to_tag}" if to_tag else ""
            
            bye_to_other = (
                f"BYE sip:{other_username}@{other_addr[0]}:{other_addr[1]} SIP/2.0\r\n"
                f"Via: SIP/2.0/UDP {b2bua_ip}:{self.config.sip.listen_port};branch=z9hG4bK{random.randint(100000, 999999)}\r\n"
                f"From: <sip:{from_username}@{b2bua_ip}>;tag={from_tag}\r\n"
                f"To: <sip:{other_username}@{b2bua_ip}>{to_tag_str}\r\n"
                f"Call-ID: {other_call_id}\r\n"
                "CSeq: 2 BYE\r\n"
                "Max-Forwards: 70\r\n"
                "Content-Length: 0\r\n"
                "\r\n"
            )
            self._send_response(bye_to_other, other_addr)
            logger.info("bye_forwarded", to=other_username, other_call_id=other_call_id)
            print(f"✅ BYE forwarded to {other_username} at {other_addr[0]}:{other_addr[1]}")
            print(f"   Other Call-ID: {other_call_id}")
            
            # 세션 정리
            print(f"🧹 Cleaning up call sessions...")
            self._cleanup_call(original_call_id)
            
        except Exception as e:
            logger.error("bye_handling_error", error=str(e), exc_info=True)
    
    async def _handle_cancel(self, request: str, addr: tuple) -> None:
        """CANCEL 처리
        
        Args:
            request: CANCEL 요청
            addr: 송신자 주소
        """
        call_id = self._extract_header(request, 'Call-ID')
        
        print(f"\n🚫 CANCEL received for call {call_id}")
        
        # 200 OK 응답
        via = self._extract_header(request, 'Via')
        from_hdr = self._extract_header(request, 'From')
        to_hdr = self._extract_header(request, 'To')
        cseq = self._extract_header(request, 'CSeq')
        
        cancel_response = (
            "SIP/2.0 200 OK\r\n"
            f"Via: {via}\r\n"
            f"From: {from_hdr}\r\n"
            f"To: {to_hdr}\r\n"
            f"Call-ID: {call_id}\r\n"
            f"CSeq: {cseq}\r\n"
            "Content-Length: 0\r\n"
            "\r\n"
        )
        self._send_response(cancel_response, addr)
        
        # 세션 정리
        if call_id in self._active_calls:
            call_info = self._active_calls[call_id]
            original_call_id = call_info.get('original_call_id', call_id)
            self._cleanup_call(original_call_id)
    
    def _cleanup_call(self, call_id: str) -> None:
        """통화 세션 정리
        
        Args:
            call_id: 통화 ID (원본 Call-ID)
        """
        if call_id not in self._active_calls:
            logger.warning("cleanup_call_not_found", call_id=call_id)
            return
        
        call_info = self._active_calls[call_id]
        new_call_id = call_info.get('b2bua_call_id')
        
        print(f"🧹 Cleaning up call: {call_id}")
        logger.info("cleanup_call_start", call_id=call_id, b2bua_call_id=new_call_id)
        
        # RTP Worker 정리
        if call_id in self._rtp_workers:
            rtp_worker = self._rtp_workers[call_id]
            try:
                # RTP Worker 중지 (async)
                asyncio.create_task(rtp_worker.stop())
                print(f"   🎵 RTP Relay stopped")
            except Exception as e:
                logger.error("rtp_worker_stop_error", call_id=call_id, error=str(e))
            finally:
                del self._rtp_workers[call_id]
        
        # 📡 MediaSession 종료 및 포트 반환
        try:
            destroyed = self.media_session_manager.destroy_session(call_id)
            if destroyed:
                print(f"   🧹 MediaSession destroyed, ports released")
            else:
                logger.warning("media_session_destroy_failed", call_id=call_id)
        except Exception as e:
            logger.error("media_session_destroy_error", call_id=call_id, error=str(e))
        
        # Call mapping 삭제
        if new_call_id:
            self._call_mapping.pop(call_id, None)
            self._call_mapping.pop(new_call_id, None)
            # B2BUA Call-ID로도 참조되고 있으므로 삭제
            self._active_calls.pop(new_call_id, None)
        
        # Active call 삭제 (원본 Call-ID)
        self._active_calls.pop(call_id, None)
        
        logger.info("call_cleaned_up", call_id=call_id)
        print(f"✅ Call cleaned up")
    
    def _extract_header(self, request: str, header_name: str) -> str:
        """SIP 헤더 추출
        
        Args:
            request: SIP 메시지
            header_name: 헤더 이름
            
        Returns:
            str: 헤더 값 (없으면 빈 문자열)
        """
        lines = request.split('\r\n')
        header_lower = header_name.lower()
        
        for line in lines:
            line_stripped = line.strip()
            if not line_stripped:
                continue
            
            # "Header-Name: value" 형식 체크
            if ':' in line_stripped:
                header_part, _, value_part = line_stripped.partition(':')
                if header_part.strip().lower() == header_lower:
                    return value_part.strip()
        
        # 헤더를 찾지 못한 경우 디버그 로그
        logger.debug("header_not_found", header=header_name)
        return ''
    
    def _create_options_response(self, request: str, addr: tuple) -> str:
        """OPTIONS 응답 생성
        
        Args:
            request: 요청 메시지
            addr: 송신자 주소
            
        Returns:
            str: 응답 메시지
        """
        via = self._extract_header(request, 'Via')
        from_hdr = self._extract_header(request, 'From')
        to_hdr = self._extract_header(request, 'To')
        call_id = self._extract_header(request, 'Call-ID')
        cseq = self._extract_header(request, 'CSeq')
        
        return (
            "SIP/2.0 200 OK\r\n"
            f"Via: {via}\r\n"
            f"From: {from_hdr}\r\n"
            f"To: {to_hdr}\r\n"
            f"Call-ID: {call_id}\r\n"
            f"CSeq: {cseq}\r\n"
            "Allow: INVITE, ACK, CANCEL, OPTIONS, BYE, REGISTER\r\n"
            "Accept: application/sdp\r\n"
            "Content-Length: 0\r\n"
            "\r\n"
        )
    
    def _handle_register(self, request: str, addr: tuple) -> str:
        """REGISTER 처리 및 사용자 등록
        
        Args:
            request: 요청 메시지
            addr: 송신자 주소
            
        Returns:
            str: 응답 메시지
        """
        via = self._extract_header(request, 'Via')
        from_hdr = self._extract_header(request, 'From')
        to_hdr = self._extract_header(request, 'To')
        call_id = self._extract_header(request, 'Call-ID')
        cseq = self._extract_header(request, 'CSeq')
        contact = self._extract_header(request, 'Contact')
        expires = self._extract_header(request, 'Expires')
        
        # username 추출
        username = self._extract_username(from_hdr)
        
        # 등록/해제 처리
        if expires == '0':
            # 등록 해제
            if username in self._registered_users:
                del self._registered_users[username]
                logger.info("user_unregistered", username=username, addr=f"{addr[0]}:{addr[1]}")
                print(f"🔴 User UNREGISTERED: {username}")
        else:
            # 등록
            self._registered_users[username] = {
                'ip': addr[0],
                'port': addr[1],
                'contact': contact,
                'from': from_hdr
            }
            logger.info("user_registered", username=username, addr=f"{addr[0]}:{addr[1]}")
            print(f"🟢 User REGISTERED: {username} at {addr[0]}:{addr[1]}")
            print(f"   📋 Total registered users: {list(self._registered_users.keys())}")
        
        # To 헤더에 tag가 없으면 추가
        if 'tag=' not in to_hdr:
            to_hdr += ';tag=mock-' + call_id[:8]
        
        return (
            "SIP/2.0 200 OK\r\n"
            f"Via: {via}\r\n"
            f"From: {from_hdr}\r\n"
            f"To: {to_hdr}\r\n"
            f"Call-ID: {call_id}\r\n"
            f"CSeq: {cseq}\r\n"
            f"Contact: {contact}\r\n"
            "Expires: 3600\r\n"
            "Content-Length: 0\r\n"
            "\r\n"
        )
    
    async def _handle_invite_b2bua(self, request: str, caller_addr: tuple) -> None:
        """B2BUA INVITE 처리 (완전한 구현)
        
        Args:
            request: INVITE 요청 메시지
            caller_addr: 발신자 주소
        """
        try:
            # 헤더 추출
            via = self._extract_header(request, 'Via')
            from_hdr = self._extract_header(request, 'From')
            to_hdr = self._extract_header(request, 'To')
            call_id = self._extract_header(request, 'Call-ID')
            cseq = self._extract_header(request, 'CSeq')
            contact = self._extract_header(request, 'Contact')
            content_type = self._extract_header(request, 'Content-Type')
            
            # SDP 추출
            sdp = self._extract_sdp_body(request)
            
            # 발신자와 수신자 username 추출
            caller_username = self._extract_username(from_hdr)
            callee_username = self._extract_username(to_hdr)
            
            # From tag 추출
            caller_tag = self._extract_tag(from_hdr)
            
            print(f"\n📞 B2BUA INVITE: {caller_username} → {callee_username}")
            print(f"   Original Call-ID: {call_id}")
            
            # 수신자가 등록되어 있는지 확인
            if callee_username not in self._registered_users:
                logger.warning("callee_not_found", callee=callee_username, caller=caller_username)
                print(f"❌ Callee {callee_username} not registered")
                
                response = (
                    "SIP/2.0 404 Not Found\r\n"
                    f"Via: {via}\r\n"
                    f"From: {from_hdr}\r\n"
                    f"To: {to_hdr};tag=b2bua-{random.randint(1000, 9999)}\r\n"
                    f"Call-ID: {call_id}\r\n"
                    f"CSeq: {cseq}\r\n"
                    "Content-Length: 0\r\n"
                    "\r\n"
                )
                self._send_response(response, caller_addr)
                return
            
            # 수신자 정보 가져오기
            callee_info = self._registered_users[callee_username]
            callee_addr = (callee_info['ip'], callee_info['port'])
            
            print(f"✅ Callee {callee_username} found at {callee_addr[0]}:{callee_addr[1]}")
            
            # 새로운 Call-ID 생성 (B2BUA leg)
            new_call_id = f"b2bua-{random.randint(100000, 999999)}-{call_id[:8]}"
            new_tag = f"b2bua-{random.randint(1000, 9999)}"
            
            # Extract original Via branch (매우 중요 - ACK를 받기 위해 필요!)
            via_branch = None
            via_match = re.search(r'branch=([^;,\s]+)', via)
            if via_match:
                via_branch = via_match.group(1)
            
            # Call mapping 저장
            self._call_mapping[call_id] = new_call_id
            self._call_mapping[new_call_id] = call_id  # 양방향
            
            # Active call 정보 저장
            call_info = {
                'original_call_id': call_id,  # 원본 Call-ID (cleanup용)
                'caller_username': caller_username,
                'callee_username': callee_username,
                'caller_addr': caller_addr,
                'callee_addr': callee_addr,
                'caller_tag': caller_tag,
                'callee_tag': None,  # 나중에 200 OK에서 설정
                'b2bua_from_tag': new_tag,  # B2BUA가 callee에게 보낸 INVITE의 From tag
                'b2bua_call_id': new_call_id,
                'original_from': from_hdr,
                'original_to': to_hdr,
                'original_via_branch': via_branch,  # ACK 수신을 위해 필수!
                'sdp': sdp,
                'state': 'inviting'
            }
            self._active_calls[call_id] = call_info
            # B2BUA Call-ID로도 접근 가능하도록
            self._active_calls[new_call_id] = call_info
            
            logger.info("b2bua_call_setup",
                       caller=caller_username,
                       callee=callee_username,
                       original_call_id=call_id,
                       new_call_id=new_call_id)
            
            print(f"🔄 Creating B2BUA leg with Call-ID: {new_call_id}")
            
            # 📡 MediaSession 생성 및 포트 할당
            print(f"📡 Creating MediaSession and allocating ports...")
            print(f"🔍 DEBUG: Caller SDP exists: {sdp is not None}")
            if sdp:
                print(f"🔍 DEBUG: SDP length: {len(sdp)} bytes")
                print(f"🔍 DEBUG: SDP content:\n{sdp[:200]}...")  # 첫 200자만 출력
            
            media_session = self.media_session_manager.create_session(
                call_id=call_id,
                caller_sdp=sdp,
                mode=None  # 기본 모드 사용
            )
            
            print(f"🔍 DEBUG: MediaSession created successfully")
            print(f"🔍 DEBUG: Caller original_ip: {media_session.caller_leg.original_ip}")
            print(f"🔍 DEBUG: Caller original_audio_port: {media_session.caller_leg.original_audio_port}")
            print(f"🔍 DEBUG: Callee allocated audio RTP port: {media_session.callee_leg.get_audio_rtp_port()}")
            
            logger.info("media_session_created",
                       call_id=call_id,
                       caller_audio_port=media_session.caller_leg.get_audio_rtp_port(),
                       callee_audio_port=media_session.callee_leg.get_audio_rtp_port())
            print(f"   ✅ Ports allocated: caller={media_session.caller_leg.allocated_ports}, callee={media_session.callee_leg.allocated_ports}")
            
            # 발신자에게 100 Trying 전송
            trying_response = (
                "SIP/2.0 100 Trying\r\n"
                f"Via: {via}\r\n"
                f"From: {from_hdr}\r\n"
                f"To: {to_hdr}\r\n"
                f"Call-ID: {call_id}\r\n"
                f"CSeq: {cseq}\r\n"
                "Content-Length: 0\r\n"
                "\r\n"
            )
            self._send_response(trying_response, caller_addr)
            
            # 수신자에게 INVITE 전달
            # 실제 IP 가져오기 (0.0.0.0이면 네트워크 인터페이스 IP 사용)
            b2bua_ip = self.config.sip.listen_ip
            if b2bua_ip == "0.0.0.0":
                # Callee 주소로부터 적절한 IP 추론
                b2bua_ip = callee_addr[0].split('.')[0:3]  # 같은 네트워크 추정
                b2bua_ip = '.'.join(b2bua_ip) + '.233'  # 임시로 .233 사용
                # 더 나은 방법: socket.gethostbyname(socket.gethostname())
                import socket
                try:
                    b2bua_ip = socket.gethostbyname(socket.gethostname())
                except:
                    b2bua_ip = "127.0.0.1"
            
            new_via = f"SIP/2.0/UDP {b2bua_ip}:{self.config.sip.listen_port};branch=z9hG4bK{random.randint(100000, 999999)}"
            new_from = f"<sip:{caller_username}@{b2bua_ip}>;tag={new_tag}"
            new_to = f"<sip:{callee_username}@{b2bua_ip}>"
            new_contact = f"<sip:{caller_username}@{b2bua_ip}:{self.config.sip.listen_port}>"
            
            # 📝 SDP Rewrite - B2BUA IP/Port로 교체
            content_type_header = ""
            content_length_header = ""
            invite_body = ""
            
            if sdp:
                print(f"📝 Rewriting SDP (B2BUA IP: {b2bua_ip}, Callee Audio Port: {media_session.callee_leg.get_audio_rtp_port()})...")
                
                # 1. 벤더 특정 속성 제거 (a=X-* 등)
                rewritten_sdp = SDPManipulator.remove_vendor_attributes(sdp)
                
                # 2. Connection IP를 B2BUA IP로 교체
                rewritten_sdp = SDPManipulator.replace_connection_ip(rewritten_sdp, b2bua_ip)
                
                # 3. Audio 포트를 Callee Leg 할당 포트로 교체
                callee_audio_port = media_session.callee_leg.get_audio_rtp_port()
                callee_audio_rtcp_port = media_session.callee_leg.get_audio_rtcp_port()
                
                if callee_audio_port:
                    rewritten_sdp = SDPManipulator.replace_media_port(rewritten_sdp, "audio", callee_audio_port)
                    print(f"   ✅ SDP rewritten: c={b2bua_ip}, m=audio {callee_audio_port}")
                
                # 4. RTCP 속성도 B2BUA 포트로 교체
                if callee_audio_rtcp_port:
                    rewritten_sdp = SDPManipulator.replace_rtcp_attribute(rewritten_sdp, "audio", callee_audio_rtcp_port, b2bua_ip)
                    print(f"   ✅ RTCP rewritten: a=rtcp:{callee_audio_rtcp_port} IN IP4 {b2bua_ip}")
                
                # TODO: Video 지원 시 video 포트도 교체
                
                content_type_header = f"Content-Type: application/sdp\r\n"
                content_length_header = f"Content-Length: {len(rewritten_sdp)}\r\n"
                invite_body = f"\r\n{rewritten_sdp}"
            else:
                content_length_header = "Content-Length: 0\r\n"
            
            invite_to_callee = (
                f"INVITE sip:{callee_username}@{callee_addr[0]}:{callee_addr[1]} SIP/2.0\r\n"
                f"Via: {new_via}\r\n"
                f"From: {new_from}\r\n"
                f"To: {new_to}\r\n"
                f"Call-ID: {new_call_id}\r\n"
                f"CSeq: 1 INVITE\r\n"
                f"Contact: {new_contact}\r\n"
                "Max-Forwards: 70\r\n"
                "User-Agent: SIP-PBX-B2BUA/1.0\r\n"
                f"{content_type_header}"
                f"{content_length_header}"
                f"{invite_body}"
            )
            
            print(f"📤 Forwarding INVITE to callee...")
            self._send_response(invite_to_callee, callee_addr)
            
            print(f"✅ B2BUA call setup in progress")
            print(f"   Waiting for callee response...")
            
        except Exception as e:
            logger.error("b2bua_invite_error", error=str(e), exc_info=True)
            print(f"❌ B2BUA INVITE error: {e}")
    
    def _create_not_implemented_response(self, request: str, addr: tuple) -> str:
        """501 Not Implemented 응답 생성
        
        Args:
            request: 요청 메시지
            addr: 송신자 주소
            
        Returns:
            str: 응답 메시지
        """
        via = self._extract_header(request, 'Via')
        from_hdr = self._extract_header(request, 'From')
        to_hdr = self._extract_header(request, 'To')
        call_id = self._extract_header(request, 'Call-ID')
        cseq = self._extract_header(request, 'CSeq')
        
        return (
            "SIP/2.0 501 Not Implemented\r\n"
            f"Via: {via}\r\n"
            f"From: {from_hdr}\r\n"
            f"To: {to_hdr}\r\n"
            f"Call-ID: {call_id}\r\n"
            f"CSeq: {cseq}\r\n"
            "Content-Length: 0\r\n"
            "\r\n"
        )
    
    async def _listen_loop(self) -> None:
        """UDP 소켓 리스닝 루프"""
        import asyncio
        import socket
        
        try:
            # UDP 소켓 생성
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._socket.bind((self.config.sip.listen_ip, self.config.sip.listen_port))
            self._socket.setblocking(False)
            
            logger.info("mock_udp_socket_bound",
                       listen_ip=self.config.sip.listen_ip,
                       listen_port=self.config.sip.listen_port)
            
            loop = asyncio.get_event_loop()
            
            while self._running:
                try:
                    # Non-blocking receive
                    data, addr = await loop.sock_recvfrom(self._socket, 65535)
                    asyncio.create_task(self._handle_sip_message(data, addr))
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error("socket_receive_error", error=str(e))
                    await asyncio.sleep(0.1)
                    
        except Exception as e:
            logger.error("mock_sip_listen_error", error=str(e))
        finally:
            if self._socket:
                self._socket.close()
    
    def start(self) -> None:
        """Mock 서버 시작"""
        import asyncio
        
        self._running = True
        
        # asyncio 이벤트 루프 가져오기
        try:
            loop = asyncio.get_running_loop()
            self._listen_task = loop.create_task(self._listen_loop())
        except RuntimeError:
            # 이벤트 루프가 없으면 나중에 시작될 것임
            logger.warning("no_event_loop", 
                          message="Event loop not running, socket will not bind")
        
        logger.info("mock_sip_server_started",
                   listen_ip=self.config.sip.listen_ip,
                   listen_port=self.config.sip.listen_port)
    
    def stop(self) -> None:
        """Mock 서버 종료"""
        self._running = False
        if self._listen_task:
            self._listen_task.cancel()
        
        # SIP 트래픽 로그 파일 닫기
        if self._sip_log_file:
            try:
                self._sip_log_file.close()
                logger.info("sip_traffic_log_closed")
            except Exception as e:
                logger.error("sip_traffic_log_close_failed", error=str(e))
        
        logger.info("mock_sip_server_stopped")
    
    def is_running(self) -> bool:
        """서버 실행 중 여부"""
        return self._running


def create_sip_endpoint(config: Config) -> BaseSIPEndpoint:
    """SIP Endpoint 팩토리 함수
    
    Args:
        config: 설정 객체
        
    Returns:
        BaseSIPEndpoint: SIP Endpoint 인스턴스 (PJSIP 또는 Mock)
    """
    if PJSIP_AVAILABLE:
        return PJSIPEndpoint(config)
    else:
        logger.warning("using_mock_endpoint",
                      message="PJSIP not available, using mock implementation")
        return MockSIPEndpoint(config)

