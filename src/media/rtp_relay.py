"""RTP Relay Worker

RTP/RTCP 패킷 relay (Bypass Mode)
"""

import asyncio
import os
import queue
import struct
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, TextIO, Tuple, Union
from dataclasses import dataclass

from src.media.rtp_packet import RTPParser, RTCPPacket
from src.media.media_session import MediaSession
from src.common.logger import get_async_logger
from src.media.aec_processor import AEC_FRAME_BYTES  # 10ms @ 16kHz = 320 bytes

logger = get_async_logger(__name__)

# AI Pipecat TTS 경로: 16kHz mono s16le, 20ms 프레임 (송신 스레드와 동일)
_PCM_SILENCE_20MS_16K_MONO = b"\x00" * 640

TTS_UDP_QUEUE_ITEM = Union[
    Tuple[bytes, Tuple[str, int], bytes],
    Tuple[bytes, Tuple[str, int], bytes, dict],
]


def _safe_rtp_debug_call_id_segment(raw: str, max_len: int = 100) -> str:
    """로그 파일명용 call_id 정규화."""
    s = (raw or "")[:max_len]
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in s) or "unknown"


def _rtp_peek_header(data: bytes) -> Optional[dict]:
    """RTP v2 헤더만 안전하게 읽기 (로그용). STUN/짧은 패킷은 None."""
    if len(data) < 12:
        return None
    v = (data[0] >> 6) & 0x3
    if v != 2:
        return None
    return {
        "version": v,
        "pt": data[1] & 0x7F,
        "seq": struct.unpack_from("!H", data, 2)[0],
        "ts": struct.unpack_from("!I", data, 4)[0],
        "ssrc": struct.unpack_from("!I", data, 8)[0],
    }


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

    _RTP_PACKET_MS = 20  # 20ms per RTP packet (G.711 표준)
    # TTS 송신 스케줄 (RTP_SENDER_PATH §5-1 / RTP_CUTOUT 분석 반영):
    # - MIN_INTER: 너무 짧으면(8ms) 지연 후 "30ms→10ms" 식 catch-up 지터 쌍이 잦음 → CBR에 가깝게 상향.
    # - SOFT_RESYNC: 한 슬롯(20ms) 부근 지연에서 격자 재앵커로 긴 버스트 꼬리 단축.
    _RTP_SCHED_MIN_INTER_SEND_MS = 17.0  # 연속 전송 최소 간격 (ms); 20ms 격자에 근접
    _RTP_SCHED_SOFT_RESYNC_LATE_MS = 20.0  # 이 이상 늦으면 base_time을 지금에 재앵커 (≈1 RTP 슬롯)
    # busy-wait 완화: time.sleep으로 대부분 소모하고, 끝구간만 짧은 스핀 + OS yield (§5-4)
    _RTP_SCHED_BUSY_SPIN_MAX_SEC = 0.00035  # sleep 후 최대 ~350µs 스핀; 그 앞은 sleep/yield
    _RTP_SCHED_YIELD_FLOOR_SEC = 0.00018  # 이 이상 남으면 Sleep(0)/sched_yield, 미만은 스핀

    def __init__(
        self,
        media_session: MediaSession,
        caller_endpoint: RTPEndpoint,
        callee_endpoint: RTPEndpoint,
        bind_ip: str = "0.0.0.0",  # RTP 소켓을 bind할 IP
        ai_orchestrator = None,  # AI Orchestrator (optional)
        sip_recorder = None,  # SIP Call Recorder (optional)
        rtp_tx_debug: bool = False,
        rtp_tx_debug_path: Optional[str] = None,
        ai_rtp_silence_keepalive: bool = True,
        ai_rtp_keepalive_interval_sec: float = 0.5,
        ai_rtp_adaptive_interval_enabled: bool = True,
        ai_rtp_adaptive_interval_thresholds: Optional[dict] = None,
    ):
        """초기화
        
        Args:
            media_session: 미디어 세션
            caller_endpoint: Caller의 RTP 엔드포인트
            callee_endpoint: Callee의 RTP 엔드포인트
            bind_ip: RTP 소켓을 bind할 IP 주소
            ai_orchestrator: AI Orchestrator (AI 모드용, optional)
            sip_recorder: SIP Call Recorder (녹음용, optional)
            rtp_tx_debug: config.yaml media.rtp_tx_debug — 송신 RTP TSV
            rtp_tx_debug_path: TSV 경로 템플릿 ({call_id} 치환), None이면 logs/rtp_tx_<id>.tsv
            ai_rtp_silence_keepalive: media.ai_rtp_silence_keepalive — env 미지정 시 사용
            ai_rtp_keepalive_interval_sec: media.ai_rtp_keepalive_interval_sec — env 미지정 시 사용
            ai_rtp_adaptive_interval_enabled: media.ai_rtp_adaptive_interval.enabled (기본 True)
            ai_rtp_adaptive_interval_thresholds: media.ai_rtp_adaptive_interval.thresholds
        """
        self.media_session = media_session
        self.caller_endpoint = caller_endpoint
        self.callee_endpoint = callee_endpoint
        self.bind_ip = bind_ip  # Bind IP 저장

        # TTS RTP를 실제로 보낼 목적지 엔드포인트.
        # None이면 인바운드 기본값(caller_endpoint)을 사용.
        # Outbound AI 콜에서는 sip_endpoint.py가 callee_endpoint로 설정한다.
        self.tts_dest_endpoint: Optional[RTPEndpoint] = None
        
        # ✅ Windows Proactor sendto 동시성 보호 (AssertionError 방지)
        self._sendto_lock = asyncio.Lock()
        # TTS 송신 전용 스레드 ↔ RTP 수신 경로 AEC(process_stream) 동시 접근 방지
        self._aec_lock = threading.Lock()
        
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
        self._pipecat_pcm_queue: Optional[queue.Queue] = None  # thread-safe PCM 큐 (TTS → 송신 스레드)
        self._pipecat_outgoing_task: Optional[asyncio.Task] = None  # 레거시: 스레드 송신 시 None
        self._tts_sender_thread: Optional[threading.Thread] = None
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None  # 스레드 → 루프 wake용
        self._tts_udp_out_queue: Optional[queue.Queue] = None  # (packet, addr, rec_payload)
        self._tts_udp_drain_task: Optional[asyncio.Task] = None
        self._tts_last_rtp_seq_sent: Optional[int] = None
        self._tts_last_rtp_ts_sent: Optional[int] = None
        self._rtp_keepalive_logged: bool = False
        self._rtp_keepalive_empty_streak: int = 0  # (레거시) 짧은 공백 로그 상관용; 킵얼라이브 간격은 INTERVAL_SEC
        # TTS RTP가 UDP 큐에 마지막으로 들어간 시각(perf_counter) — 묵음 킵얼라이브 8초 간격 계산
        self._tts_last_udp_enqueued_mono: float = 0.0
        # config media.rtp_tx_debug — sendto 직전 송신 TSV
        self._rtp_tx_debug_enabled: bool = bool(rtp_tx_debug)
        _pat = (rtp_tx_debug_path or "").strip()
        self._rtp_tx_debug_path_pattern: Optional[str] = _pat or None
        self._rtp_tx_debug_fh: Optional[TextIO] = None
        self._rtp_tx_debug_resolved_path: Optional[str] = None
        self._rtp_tx_debug_last_perf: Optional[float] = None
        self._RTP_PACKET_MS = self.__class__._RTP_PACKET_MS
        self._media_ai_rtp_silence_keepalive: bool = bool(ai_rtp_silence_keepalive)
        try:
            self._media_ai_rtp_keepalive_interval_sec: float = float(ai_rtp_keepalive_interval_sec)
        except (TypeError, ValueError):
            self._media_ai_rtp_keepalive_interval_sec = 0.5
        self._media_ai_rtp_keepalive_interval_sec = max(
            0.5, min(self._media_ai_rtp_keepalive_interval_sec, 60.0)
        )
        
        # ✅ 적응형 패킷 간격 설정
        self._adaptive_interval_enabled: bool = bool(ai_rtp_adaptive_interval_enabled)
        if ai_rtp_adaptive_interval_thresholds:
            self._adaptive_interval_threshold_normal = int(
                ai_rtp_adaptive_interval_thresholds.get("normal_max", 5)
            )
            self._adaptive_interval_threshold_slight = int(
                ai_rtp_adaptive_interval_thresholds.get("slight_max", 10)
            )
            self._adaptive_interval_threshold_burst = int(
                ai_rtp_adaptive_interval_thresholds.get("burst_max", 15)
            )
        else:
            self._adaptive_interval_threshold_normal = 5
            self._adaptive_interval_threshold_slight = 10
            self._adaptive_interval_threshold_burst = 15
        
        # TTS RTP 상관 로그: 인사·「정보를 확인 중」 등 특정 멘트 송신 시 PCM/UDP 추적
        self._tts_rtp_log_lock = threading.Lock()
        self._tts_rtp_stream_label: str = ""
        self._tts_rtp_stream_preview: str = ""
        self._tts_rtp_stream_started_mono: float = 0.0
        self._tts_rtp_pcm_trace_count: int = 0
        self._rtp_trace_call_ids: frozenset = frozenset(
            x.strip()
            for x in os.environ.get("SIPPBX_RTP_TRACE_CALL_IDS", "").split(",")
            if x.strip()
        )
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
            "rtp_sched_soft_resync_count": 0,  # 송신 스케줄 소프트 재동기화 횟수
            "bypass_relay_sent": 0,  # Bypass 모드 원격으로 sendto 성공
            "bypass_relay_send_failed": 0,  # Bypass sendto 예외
            # ✅ 송신 스레드 패킷 수 (응답별 추적용)
            "rtp_tts_thread_packets_queued": 0,  # 송신 스레드가 UDP 큐에 넣은 패킷 수 (누적)
        }
        # 지연 분석용: 구간별 첫 로그 한 번만 (RTP→STT→TTS→RTP)
        self._timing_first_caller_rtp_logged = False
        self._timing_first_tts_rtp_sent_logged = False
        self._rtp_health_last_mono: float = 0.0
        
        logger.info("rtp_relay_worker_created",
                   call_id=media_session.call_id,
                   caller=str(caller_endpoint),
                   callee=str(callee_endpoint),
                   ai_enabled=ai_orchestrator is not None,
                   recording_enabled=sip_recorder is not None,
                   rtp_tx_debug=self._rtp_tx_debug_enabled)

    def emit_rtp_health_snapshot(self, reason: str, min_interval_sec: float = 7.0) -> None:
        """
        STT/TTS/Bypass/UDP 큐·통계를 한 줄에 묶어 구조적 병목 추적.
        reason: 로그 상관용 트리거 이름 (bypass_relay_tick, tts_udp_sent, manual 등).
        """
        now = time.monotonic()
        if now - self._rtp_health_last_mono < min_interval_sec:
            return
        self._rtp_health_last_mono = now
        st = self.stats
        _pcm = getattr(self, "_pipecat_pcm_queue", None)
        pcm_q = _pcm.qsize() if _pcm is not None else None
        pcm_max = getattr(_pcm, "maxsize", None) if _pcm is not None else None
        _stt = getattr(self, "_pipecat_audio_queue", None)
        stt_q = _stt.qsize() if _stt is not None else None
        stt_max = getattr(_stt, "maxsize", None) if _stt is not None else None
        _udp = getattr(self, "_tts_udp_out_queue", None)
        udp_q = _udp.qsize() if _udp is not None else None
        udp_max = getattr(_udp, "maxsize", None) if _udp is not None else None
        tts_thread_alive = bool(
            getattr(self, "_tts_sender_thread", None) is not None
            and self._tts_sender_thread.is_alive()
        )
        logger.info(
            "rtp_health_snapshot",
            call_id=self.media_session.call_id,
            progress="rtp_debug",
            trigger_reason=reason,
            relay_mode=self.relay_mode,
            ai_mode=self.ai_mode,
            pipecat_mode=self._pipecat_mode,
            codec=getattr(self.media_session, "codec", None),
            caller_ep=f"{self.caller_endpoint.ip}:{self.caller_endpoint.port}",
            callee_ep=f"{self.callee_endpoint.ip}:{self.callee_endpoint.port}",
            pcm_queue_size=pcm_q,
            pcm_queue_max=pcm_max,
            stt_input_queue_size=stt_q,
            stt_input_queue_max=stt_max,
            tts_udp_out_queue_size=udp_q,
            tts_udp_out_queue_max=udp_max,
            tts_sender_thread_alive=tts_thread_alive,
            bypass_relay_sent=st.get("bypass_relay_sent", 0),
            bypass_relay_send_failed=st.get("bypass_relay_send_failed", 0),
            rtp_tts_packets_sent=st.get("rtp_tts_packets_sent", 0),
            rtp_tts_send_errors=st.get("rtp_tts_send_errors", 0),
            rtp_tts_packets_dropped=st.get("rtp_tts_packets_dropped", 0),
            rtp_sched_soft_resync_count=st.get("rtp_sched_soft_resync_count", 0),
            caller_audio_packets=st.get("caller_audio_packets", 0),
            callee_audio_packets=st.get("callee_audio_packets", 0),
            note="큐 적체=소비·루프 지연, bypass_send_failed=릴레이 sendto 실패, tts_send_errors=Proactor sendto, soft_resync=20ms 격자 재앵커",
        )

    def set_tts_rtp_stream_context(self, label: str, text_preview: str = "") -> None:
        """Output Transport(TextFrame)에서 설정 — 이후 PCM 큐·UDP 송신 로그에 stream_label 부착."""
        with self._tts_rtp_log_lock:
            self._tts_rtp_stream_label = (label or "")[:96]
            self._tts_rtp_stream_preview = (text_preview or "")[:400]
            self._tts_rtp_stream_started_mono = time.monotonic()
            self._tts_rtp_pcm_trace_count = 0

    def clear_tts_rtp_stream_context(self) -> None:
        with self._tts_rtp_log_lock:
            self._tts_rtp_stream_label = ""
            self._tts_rtp_stream_preview = ""
            self._tts_rtp_stream_started_mono = 0.0
            self._tts_rtp_pcm_trace_count = 0

    def _tts_rtp_trace_verbose_call(self) -> bool:
        cid = getattr(self.media_session, "call_id", None) or ""
        return bool(cid and cid in self._rtp_trace_call_ids)

    def _tts_rtp_trace_active(self) -> bool:
        with self._tts_rtp_log_lock:
            if self._tts_rtp_stream_label:
                return True
        return self._tts_rtp_trace_verbose_call()

    def _tts_rtp_log_context_dict(self) -> dict:
        with self._tts_rtp_log_lock:
            prev = self._tts_rtp_stream_preview
            return {
                "tts_stream_label": self._tts_rtp_stream_label or None,
                "tts_stream_text_preview": (
                    (prev[:100] + "…") if len(prev) > 100 else (prev or None)
                ),
            }

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
                        _pcm_q = getattr(self, "_pipecat_pcm_queue", None)
                        _tts_th = getattr(self, "_tts_sender_thread", None)
                        is_tts_active = bool(
                            _tts_th is not None
                            and _tts_th.is_alive()
                            and _pcm_q is not None
                            and _pcm_q.qsize() > 0
                        )
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
                            with self._aec_lock:
                                self._aec_near_buffer = getattr(self, "_aec_near_buffer", b"") + pcm_data
                                while len(self._aec_near_buffer) >= AEC_FRAME_BYTES:
                                    chunk = self._aec_near_buffer[:AEC_FRAME_BYTES]
                                    self._aec_near_buffer = self._aec_near_buffer[AEC_FRAME_BYTES:]
                                    out = self._aec_processor.process_stream(chunk)
                                    try:
                                        self._pipecat_audio_queue.put_nowait(out)
                                        _qs = self._pipecat_audio_queue.qsize()
                                        if _qs >= 6:
                                            if not getattr(self, "_stt_queue_spike_active", False):
                                                self._stt_queue_spike_active = True
                                                logger.warning(
                                                    "stt_input_queue_depth_spike",
                                                    call_id=self.media_session.call_id,
                                                    queue_size=_qs,
                                                    queue_max=self._pipecat_audio_queue.maxsize,
                                                    threshold=6,
                                                    path="aec",
                                                    note="STT 입력 큐 깊이 임계 초과(AEC 경로)",
                                                )
                                        elif _qs < 4:
                                            self._stt_queue_spike_active = False
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
                                # 소규모 백로그(예: 0→6)도 STT 품질·발화 경계에 영향 → 임계 경고(스파이크 1회/구간)
                                if qsize >= 6:
                                    if not getattr(self, "_stt_queue_spike_active", False):
                                        self._stt_queue_spike_active = True
                                        logger.warning(
                                            "stt_input_queue_depth_spike",
                                            call_id=self.media_session.call_id,
                                            queue_size=qsize,
                                            queue_max=self._pipecat_audio_queue.maxsize,
                                            threshold=6,
                                            packet_count=getattr(
                                                self, "_caller_rtp_received_count", 0
                                            ),
                                            note="STT 입력 큐 깊이 임계 초과 — 소비 지연·발화 잘림 가능 (리포트 권장 모니터링)",
                                        )
                                elif qsize < 4:
                                    self._stt_queue_spike_active = False
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
                            if self.sip_recorder.enqueue_rtp_packet(
                                call_id=self.media_session.call_id,
                                audio_data=audio_payload,
                                direction=direction,
                                codec=codec,
                            ):
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
            # tts_dest_endpoint가 설정된 경우(outbound) 그것을 사용, 없으면 caller_endpoint(inbound 기본값)
            _tts_dest = self.tts_dest_endpoint or self.caller_endpoint
            dest_ip = str(_tts_dest.ip)
            dest_port = int(_tts_dest.port)

            # PCM(16kHz) → G.711 → RTP 패킷들로 변환
            rtp_packets = self._rtp_packet_builder.build_packets(audio_data, sample_rate=16000)
            
            for packet in rtp_packets:
                try:
                    # 동기 메서드이므로 직접 전송 (레거시 메서드, Pipecat 모드에서는 미사용)
                    transport.sendto(
                        packet, (dest_ip, dest_port)
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
    
    def _flush_tts_udp_queue_blocking(self) -> None:
        """종료 시 스레드가 남긴 RTP를 동기적으로 루프에서 비움 (미전송 UDP 감소)."""
        loop = self._event_loop
        q = self._tts_udp_out_queue
        if loop is None or loop.is_closed() or q is None:
            return

        async def _run() -> None:
            while True:
                try:
                    item = q.get_nowait()
                except queue.Empty:
                    break
                await self._process_tts_udp_item(item)

        try:
            fut = asyncio.run_coroutine_threadsafe(_run(), loop)
            fut.result(timeout=4.0)
        except Exception:
            pass

    def _wake_tts_udp_drain(self) -> None:
        """송신 전용 스레드 → 이벤트 루프: UDP 전송 드레인 태스크 예약."""
        loop = self._event_loop
        if loop is None or loop.is_closed():
            return

        def _kick() -> None:
            try:
                self._ensure_tts_udp_drain_running()
            except RuntimeError:
                pass

        try:
            loop.call_soon_threadsafe(_kick)
        except RuntimeError:
            pass

    def _ensure_tts_udp_drain_running(self) -> None:
        """이벤트 루프 스레드에서만 호출."""
        t = self._tts_udp_drain_task
        if t is not None and not t.done():
            return
        try:
            self._tts_udp_drain_task = asyncio.create_task(self._drain_tts_udp_out_queue())
        except RuntimeError:
            pass

    async def _drain_tts_udp_out_queue(self) -> None:
        """스레드가 큐에 쌓은 RTP를 asyncio 루프에서 sendto (Proactor 호환)."""
        _drain_t0 = time.perf_counter()
        _drained = 0
        try:
            while True:
                _q = self._tts_udp_out_queue
                if _q is None:
                    break
                try:
                    item = _q.get_nowait()
                except queue.Empty:
                    break
                await self._process_tts_udp_item(item)
                _drained += 1
        finally:
            _elapsed_ms = (time.perf_counter() - _drain_t0) * 1000.0
            _qrem = (
                self._tts_udp_out_queue.qsize()
                if self._tts_udp_out_queue is not None
                else -1
            )
            if _drained > 0 and (_drained >= 8 or _elapsed_ms >= 25.0):
                logger.warning(
                    "tts_udp_drain_bursty_or_slow",
                    call_id=self.media_session.call_id,
                    progress="rtp_timing",
                    drained_count=_drained,
                    elapsed_ms=round(_elapsed_ms, 2),
                    queue_remaining_after=_qrem,
                    note="한 드레인 틱에 다량 처리 또는 지연 — 이벤트 루프 스톨·sendto 락 대기 의심 시 상관",
                )
            self._tts_udp_drain_task = None
            try:
                if (
                    self._pipecat_mode
                    and self._tts_udp_out_queue is not None
                    and not self._tts_udp_out_queue.empty()
                ):
                    self._ensure_tts_udp_drain_running()
            except Exception:
                pass

    async def _process_tts_udp_item(self, item: TTS_UDP_QUEUE_ITEM) -> None:
        packet, addr, rec_payload, meta = self._unpack_tts_udp_item(item)
        tx_kind = str((meta or {}).get("tx_kind") or "media")
        # tts_dest_endpoint가 있으면(outbound) callee 소켓 우선 사용.
        # 없으면(inbound) ai_mode: caller 소켓 우선(인바운드 기본값).
        if self.tts_dest_endpoint is not None:
            _transport = self.callee_audio_transport or self.caller_audio_transport
        elif self.ai_mode:
            _transport = self.caller_audio_transport or self.callee_audio_transport
        else:
            _transport = self.callee_audio_transport or self.caller_audio_transport
        if not _transport or _transport.is_closing():
            logger.error(
                "rtp_transport_invalid_before_send",
                call_id=self.media_session.call_id,
                transport_type=type(_transport).__name__ if _transport else "None",
                is_closing=_transport.is_closing() if _transport else "N/A",
                note="Transport 무효 - TTS 전송 중단",
            )
            return
        _rtp_seq_hdr = struct.unpack_from("!H", packet, 2)[0]
        _rtp_ts_hdr = struct.unpack_from("!I", packet, 4)[0]
        if self._tts_last_rtp_seq_sent is not None:
            _exp_seq = (self._tts_last_rtp_seq_sent + 1) & 0xFFFF
            if _rtp_seq_hdr != _exp_seq:
                logger.warning(
                    "rtp_seq_discontinuity",
                    call_id=self.media_session.call_id,
                    progress="rtp_timing",
                    expected_seq=_exp_seq,
                    actual_seq=_rtp_seq_hdr,
                    chunk_inner_idx=-1,
                    note="RTP sequence 비연속 — 빌더 재생성·중복 전송·패킷 드롭 의심 시 확인",
                )
        if self._tts_last_rtp_ts_sent is not None and self._rtp_packet_builder:
            _exp_ts = (self._tts_last_rtp_ts_sent + self._rtp_packet_builder.timestamp_increment) & 0xFFFFFFFF
            if _rtp_ts_hdr != _exp_ts:
                _delta = (_rtp_ts_hdr - self._tts_last_rtp_ts_sent) & 0xFFFFFFFF
                logger.warning(
                    "rtp_timestamp_discontinuity",
                    call_id=self.media_session.call_id,
                    progress="rtp_timing",
                    expected_ts=_exp_ts,
                    actual_ts=_rtp_ts_hdr,
                    delta_from_prev=_delta,
                    note="RTP timestamp 스텝 비정상 — 코덱/프레임 경계 불일치 추적",
                )
        try:
            _lock_wait_start = time.perf_counter()
            async with self._sendto_lock:
                _lock_wait_ms = (time.perf_counter() - _lock_wait_start) * 1000.0
                if _lock_wait_ms >= 5.0:
                    logger.warning(
                        "rtp_sendto_lock_wait_high",
                        call_id=self.media_session.call_id,
                        progress="rtp_timing",
                        lock_wait_ms=round(_lock_wait_ms, 2),
                        rtp_seq=_rtp_seq_hdr,
                        note="sendto 락 획득 지연 — 다른 RTP/공유 락과 경합 추적",
                    )
                _transport.sendto(packet, addr)
        except Exception as send_err:
            self.stats["rtp_tts_send_errors"] += 1
            logger.error(
                "rtp_sendto_failed",
                call_id=self.media_session.call_id,
                dest_addr=f"{addr[0]}:{addr[1]}",
                error=str(send_err),
                error_type=type(send_err).__name__,
            )
            return
        _qdep = (
            self._tts_udp_out_queue.qsize()
            if self._tts_udp_out_queue is not None
            else None
        )
        self._rtp_tx_debug_append(
            packet=packet,
            addr=addr,
            tx_kind=tx_kind,
            queue_depth_after=_qdep,
        )
        self._tts_last_rtp_seq_sent = _rtp_seq_hdr
        self._tts_last_rtp_ts_sent = _rtp_ts_hdr
        self.stats["rtp_tts_packets_sent"] += 1
        _sent_n = self.stats["rtp_tts_packets_sent"]
        _trace_ctx = self._tts_rtp_log_context_dict()
        _trace_verbose = self._tts_rtp_trace_verbose_call()
        if _trace_ctx.get("tts_stream_label") or _trace_verbose:
            _udp_qsz = (
                self._tts_udp_out_queue.qsize()
                if self._tts_udp_out_queue is not None
                else None
            )
            if _trace_verbose or _sent_n <= 10 or _sent_n % 20 == 0:
                logger.info(
                    "tts_rtp_trace_udp_sent",
                    call_id=self.media_session.call_id,
                    progress="rtp_tts_trace",
                    rtp_seq=_rtp_seq_hdr,
                    rtp_ts=_rtp_ts_hdr,
                    dest_addr=f"{addr[0]}:{addr[1]}",
                    packet_bytes=len(packet),
                    rtp_packets_sent_total=_sent_n,
                    tts_udp_out_queue_size_after_send=_udp_qsz,
                    trace_call_id_verbose=_trace_verbose,
                    **_trace_ctx,
                    note="TTS RTP UDP sendto 완료 — stream_label·seq·큐로 끊김·적체 상관 (SIPPBX_RTP_TRACE_CALL_IDS=통화별 상세)",
                )
        if _sent_n % 120 == 0:
            self.emit_rtp_health_snapshot("tts_udp_sent_burst")
        if self.stats["rtp_tts_packets_sent"] == 1:
            logger.info(
                "rtp_first_packet_sent",
                call_id=self.media_session.call_id,
                dest_ip=addr[0],
                dest_port=addr[1],
                packet_size=len(packet),
                transport_type=type(_transport).__name__,
                note="첫 RTP 패킷 전송 성공",
            )
        if self.recording_enabled and self.sip_recorder:
            try:
                codec = getattr(self.media_session, "codec", "PCMU")
                if self.sip_recorder.enqueue_rtp_packet(
                    call_id=self.media_session.call_id,
                    audio_data=rec_payload,
                    direction="callee",
                    codec=codec,
                ):
                    self.stats["recording_packets"] += 1
            except Exception:
                pass

    @staticmethod
    def _sched_yield_light() -> None:
        """CPU 점유 완화: Windows는 Sleep(0), 그 외는 sched_yield/time.sleep(0)."""
        try:
            if sys.platform == "win32":
                import ctypes

                ctypes.windll.kernel32.Sleep(0)
            else:
                import os

                if hasattr(os, "sched_yield"):
                    os.sched_yield()
                else:
                    time.sleep(0)
        except Exception:
            pass

    @staticmethod
    def _split_pcm_to_buffer(pcm_data: bytes, buf: list) -> None:
        """PCM 청크를 20ms 프레임(640 bytes @16kHz mono s16le) 단위로 쪼개서 buf에 추가."""
        FRAME_BYTES = 640
        for i in range(0, len(pcm_data), FRAME_BYTES):
            frame = pcm_data[i : i + FRAME_BYTES]
            if len(frame) < FRAME_BYTES:
                frame = frame + b"\x00" * (FRAME_BYTES - len(frame))
            buf.append(frame)

    def _wait_until_send_deadline(self, deadline: float) -> None:
        """
        목표 시각까지 대기. 전량 busy-wait 대신 sleep + OS yield + 짧은 스핀 (§5-4).
        """
        spin_cap = self._RTP_SCHED_BUSY_SPIN_MAX_SEC
        y_floor = self._RTP_SCHED_YIELD_FLOOR_SEC
        while True:
            now = time.perf_counter()
            if now >= deadline:
                return
            rem = deadline - now
            if rem > spin_cap + 0.00015:
                time.sleep(rem - spin_cap)
            elif rem > y_floor:
                self._sched_yield_light()
            else:
                pass

    def _ai_silence_rtp_keepalive_enabled(self) -> bool:
        """AI·Pipecat 모드에서 장시간 무송신 시 무음 RTP (단말 NO_RTP 완화).

        우선순위: 환경변수 SIPPBX_AI_RTP_SILENCE_KEEPALIVE(설정 시) > config media.ai_rtp_silence_keepalive(기본 True).
        켜면 **마지막 RTP(UDP 큐 투입) 이후 INTERVAL_SEC마다 20ms 무음 1패킷**만 송신.
        """
        env_key = "SIPPBX_AI_RTP_SILENCE_KEEPALIVE"
        if env_key in os.environ:
            raw = str(os.environ.get(env_key, "")).strip().lower()
            if raw in ("0", "false", "no", "off", ""):
                want = False
            elif raw in ("1", "true", "yes", "on"):
                want = True
            else:
                want = self._media_ai_rtp_silence_keepalive
        else:
            want = self._media_ai_rtp_silence_keepalive
        if not want:
            return False
        return bool(
            self.ai_mode
            and self._pipecat_mode
            and self._rtp_packet_builder is not None
            and self.caller_endpoint
            and (self.caller_audio_transport or self.callee_audio_transport)
        )

    def _rtp_keepalive_interval_sec(self) -> float:
        """단말이 ~10초 무수신 시 끊는 경우 0.5초 주기 권장 (재생 gap 최소화)."""
        env_key = "SIPPBX_AI_RTP_KEEPALIVE_INTERVAL_SEC"
        if env_key in os.environ:
            try:
                v = float(os.environ.get(env_key, "0.5"))
            except ValueError:
                v = 0.5
        else:
            v = float(self._media_ai_rtp_keepalive_interval_sec)
        return max(0.5, min(v, 60.0))

    def _pcm_queue_get_timeout_sec(self) -> float:
        """PCM 큐 대기 타임아웃(초). 킵얼라이브 간격은 송신 스레드에서 별도 계산."""
        return 1.25

    @staticmethod
    def _unpack_tts_udp_item(item: TTS_UDP_QUEUE_ITEM) -> Tuple[bytes, Tuple[str, int], bytes, dict]:
        if len(item) == 4:
            p, a, r, meta = item  # type: ignore[misc]
            return p, a, r, meta if isinstance(meta, dict) else {}
        p, a, r = item  # type: ignore[misc]
        return p, a, r, {}

    def _pcm_keepalive_queue_timeout_sec(self, packets_sent: int) -> float:
        """큐에 청크가 있으면 즉시, 없으면 keepalive 간격까지 대기."""
        if not self._ai_silence_rtp_keepalive_enabled():
            return self._pcm_queue_get_timeout_sec()
        
        # ✅ 큐에 청크가 있으면 즉시 처리 (블로킹 방지)
        if self._pipecat_pcm_queue is not None and self._pipecat_pcm_queue.qsize() > 0:
            return 0.02
        
        # 큐가 비었을 때만 keepalive 간격 고려
        if packets_sent <= 0:
            return 1.25
        
        now = time.perf_counter()
        last = self._tts_last_udp_enqueued_mono
        interval = self._rtp_keepalive_interval_sec()
        if last <= 0:
            return 1.25
        
        gap = interval - (now - last)
        if gap > 0.02:
            return min(1.25, gap)
        return 0.02

    def _get_adaptive_packet_interval_sec(self) -> float:
        """
        PCM 큐 백로그에 따라 RTP 패킷 간격 동적 조정.
        
        큐가 쌓이면 간격을 단축하여 빠르게 소비, 백로그 감소.
        단말 jitter buffer 허용 범위 내(12~20ms)에서 조정.
        
        큐 크기    간격     청크 시간    소비 속도 증가
        0~5개     20ms     500ms       1.0x (정상)
        6~10개    18ms     450ms       1.11x (약간 빠름)
        11~15개   15ms     375ms       1.33x (버스트)
        16개+     12ms     300ms       1.67x (긴급)
        
        config.yaml media.ai_rtp_adaptive_interval.enabled: false 또는
        환경변수 SIPPBX_RTP_ADAPTIVE_INTERVAL=0으로 비활성화 가능.
        
        Returns:
            패킷 간격 (초)
        """
        # config에서 비활성화된 경우
        if not getattr(self, "_adaptive_interval_enabled", True):
            return 0.020
        
        # 환경변수로 비활성화 가능
        env_key = "SIPPBX_RTP_ADAPTIVE_INTERVAL"
        if os.environ.get(env_key, "").strip().lower() in ("0", "false", "off", "no"):
            return 0.020  # 고정 20ms
        
        if self._pipecat_pcm_queue is None:
            return 0.020
        
        queue_size = self._pipecat_pcm_queue.qsize()
        
        # Config 기반 임계값 (fallback to default)
        threshold_normal = getattr(self, "_adaptive_interval_threshold_normal", 5)
        threshold_slight = getattr(self, "_adaptive_interval_threshold_slight", 10)
        threshold_burst = getattr(self, "_adaptive_interval_threshold_burst", 15)
        
        # 큐 백로그 기반 동적 간격
        if queue_size > threshold_burst:
            return 0.012  # 12ms (긴급 모드)
        elif queue_size > threshold_slight:
            return 0.015  # 15ms (버스트 모드)
        elif queue_size > threshold_normal:
            return 0.018  # 18ms (약간 빠름)
        else:
            return 0.020  # 20ms (정상)

    def _rtp_tx_debug_close(self) -> None:
        fh = self._rtp_tx_debug_fh
        self._rtp_tx_debug_fh = None
        self._rtp_tx_debug_last_perf = None
        if fh is not None:
            try:
                fh.close()
            except Exception:
                pass

    def _rtp_tx_debug_ensure_open(self) -> None:
        if self._rtp_tx_debug_fh is not None or not self._rtp_tx_debug_enabled:
            return
        cid = _safe_rtp_debug_call_id_segment(self.media_session.call_id)
        raw_path = (self._rtp_tx_debug_path_pattern or "").strip()
        if raw_path:
            path = Path(raw_path.replace("{call_id}", cid))
        else:
            base = Path(__file__).resolve().parents[2] / "logs"
            base.mkdir(parents=True, exist_ok=True)
            path = base / f"rtp_tx_{cid}.tsv"
        path.parent.mkdir(parents=True, exist_ok=True)
        is_new = not path.exists() or path.stat().st_size == 0
        self._rtp_tx_debug_fh = open(path, "a", encoding="utf-8")
        self._rtp_tx_debug_resolved_path = str(path)
        if is_new:
            self._rtp_tx_debug_fh.write(
                "wall_iso\tperf_mono\tcall_id\tdest\ttx_kind\tseq\tts\tssrc\tpt\t"
                "interval_ms_since_prev_send\tpacket_bytes\tqueue_depth_after\n"
            )
        logger.info(
            "rtp_tx_debug_file_opened",
            call_id=self.media_session.call_id,
            progress="rtp_debug",
            path=str(path),
            note="media.rtp_tx_debug 송신 RTP TSV — seq·간격·sendto 직전 추적",
        )

    def _rtp_tx_debug_append(
        self,
        *,
        packet: bytes,
        addr: Tuple[str, int],
        tx_kind: str,
        queue_depth_after: Optional[int],
    ) -> None:
        if not self._rtp_tx_debug_enabled:
            return
        try:
            self._rtp_tx_debug_ensure_open()
            fh = self._rtp_tx_debug_fh
            if fh is None:
                return
            hdr = _rtp_peek_header(packet) or {}
            seq = hdr.get("seq", -1)
            ts_rtp = hdr.get("ts", -1)
            ssrc = hdr.get("ssrc", -1)
            pt = hdr.get("pt", -1)
            now_perf = time.perf_counter()
            prev = self._rtp_tx_debug_last_perf
            interval_ms = (
                round((now_perf - prev) * 1000.0, 3) if prev is not None else ""
            )
            self._rtp_tx_debug_last_perf = now_perf
            wall = datetime.now().isoformat(timespec="milliseconds")
            dest = f"{addr[0]}:{addr[1]}"
            qd = "" if queue_depth_after is None else str(queue_depth_after)
            fh.write(
                f"{wall}\t{now_perf:.6f}\t{self.media_session.call_id}\t{dest}\t{tx_kind}\t"
                f"{seq}\t{ts_rtp}\t{ssrc}\t{pt}\t{interval_ms}\t{len(packet)}\t{qd}\n"
            )
            fh.flush()
        except Exception as ex:
            logger.warning(
                "rtp_tx_debug_append_failed",
                call_id=self.media_session.call_id,
                error=str(ex),
                error_type=type(ex).__name__,
                hypothesis="path_permission_or_disk",
            )

    def _pcm_sender_thread_main(self) -> None:
        """
        RTP 패킷 송신 스레드 — **지속적 20ms 무음 전송 (Continuous Silence)** 방식.

        구조적 원칙:
        - 항상 정확히 20ms 간격으로 패킷 전송 (미디어 없으면 무음)
        - base_time은 **최초 1회만** 설정하고, 절대로 재설정하지 않음
        - soft_resync, _rtp_new_segment_after_empty 등 복잡한 재앵커 로직 제거
        - 큐는 비블로킹(get_nowait)으로 읽음 → 20ms 타이밍 격자와 분리
        """
        packets_sent = 0
        bytes_sent_cumulative = 0
        interval_violations = 0
        INTERVAL_TOLERANCE_MS = 5
        _logged_3s = False
        behind_schedule_count = 0
        recent_intervals_ms: list = []
        FIXED_INTERVAL_SEC = 0.020  # 고정 20ms 간격
        silence_streak = 0  # 연속 무음 패킷 수 (로그 제어용)
        media_packets_sent = 0  # 실제 미디어(TTS) 패킷 수

        # 첫 PCM 데이터가 도착할 때까지 대기 (블로킹)
        while self._pipecat_mode and self._pipecat_pcm_queue is not None:
            try:
                pcm_data = self._pipecat_pcm_queue.get(timeout=1.25)
                if pcm_data is None:
                    logger.info("rtp_sender_session_end_before_start",
                                call_id=self.media_session.call_id,
                                note="첫 PCM 도착 전 세션 종료 sentinel 수신")
                    return
                break
            except queue.Empty:
                continue

        # base_time 최초 설정 (이후 절대 변경 없음)
        self._rtp_base_time = time.perf_counter()
        self._rtp_packets_sent_total = 0
        self._rtp_last_send_time = self._rtp_base_time
        logger.info("rtp_base_time_initialized",
                     call_id=self.media_session.call_id,
                     progress="rtp_timing",
                     note="첫 PCM 수신 → RTP base_time 설정 (이후 변경 없음, 지속적 20ms 전송)")

        # 첫 PCM 데이터를 내부 버퍼에 넣고, 이후 메인 루프에서 소비
        pcm_buffer: list[bytes] = []
        self._split_pcm_to_buffer(pcm_data, pcm_buffer)
        _session_ending = False  # sentinel 수신 시 True → pcm_buffer 소진 후 종료

        while self._pipecat_pcm_queue is not None:
            try:
                # 1) 큐에서 비블로킹으로 가능한 한 모두 가져와서 버퍼에 넣기
                if not _session_ending:
                    while True:
                        try:
                            chunk = self._pipecat_pcm_queue.get_nowait()
                            if chunk is None:
                                # 종료 sentinel: 큐에 남은 청크를 모두 pcm_buffer로 옮긴 뒤 드레인
                                while True:
                                    try:
                                        _extra = self._pipecat_pcm_queue.get_nowait()
                                        if _extra is None:
                                            break
                                        self._split_pcm_to_buffer(_extra, pcm_buffer)
                                    except queue.Empty:
                                        break
                                _remaining = len(pcm_buffer)
                                if _remaining > 0:
                                    logger.info(
                                        "rtp_sender_session_end_draining",
                                        call_id=self.media_session.call_id,
                                        pcm_buffer_remaining=_remaining,
                                        estimated_drain_sec=round(_remaining * FIXED_INTERVAL_SEC, 2),
                                        packets_sent=packets_sent,
                                        note="sentinel 수신 → 남은 pcm_buffer 소진 후 종료",
                                    )
                                _session_ending = True
                                break
                            self._split_pcm_to_buffer(chunk, pcm_buffer)
                        except queue.Empty:
                            break

                # 2) 버퍼에서 20ms 프레임 1개 꺼내기 (없으면 무음)
                if pcm_buffer:
                    frame_data = pcm_buffer.pop(0)
                    pcm_is_silence = False
                    silence_streak = 0
                elif _session_ending:
                    # sentinel 수신 후 pcm_buffer 소진 완료 → 종료
                    logger.info(
                        "rtp_sender_session_end",
                        call_id=self.media_session.call_id,
                        packets_sent=packets_sent,
                        media_packets=media_packets_sent,
                        silence_packets=packets_sent - media_packets_sent,
                        total_sent=self.stats["rtp_tts_packets_sent"],
                        total_dropped=self.stats["rtp_tts_packets_dropped"],
                        send_errors=self.stats["rtp_tts_send_errors"],
                        interval_violations=interval_violations,
                        behind_schedule_count=behind_schedule_count,
                        note="TTS 발송 루프 종료 (잔여 버퍼 소진 완료)",
                    )
                    return
                else:
                    frame_data = _PCM_SILENCE_20MS_16K_MONO
                    pcm_is_silence = True
                    silence_streak += 1

                # 3) Transport / endpoint 검증
                if not self._rtp_packet_builder:
                    # base_time 격자는 유지 (20ms 대기 후 다음 슬롯)
                    self._rtp_packets_sent_total += 1
                    target_time = self._rtp_base_time + (self._rtp_packets_sent_total * FIXED_INTERVAL_SEC)
                    self._wait_until_send_deadline(target_time)
                    continue

                # TTS 전송용 transport: ai_mode면 caller 소켓 우선(인바운드와 동일 로직)
                if self.ai_mode:
                    _chk_transport = self.caller_audio_transport or self.callee_audio_transport
                else:
                    _chk_transport = self.callee_audio_transport or self.caller_audio_transport
                # tts_dest_endpoint가 설정되어 있으면 그것을 목적지로 사용(outbound),
                # 없으면 caller_endpoint 폴백(인바운드 기본값)
                _tts_dest = self.tts_dest_endpoint or self.caller_endpoint
                if not _chk_transport or not _tts_dest:
                    self._rtp_packets_sent_total += 1
                    target_time = self._rtp_base_time + (self._rtp_packets_sent_total * FIXED_INTERVAL_SEC)
                    self._wait_until_send_deadline(target_time)
                    continue

                caller_ip = str(_tts_dest.ip)
                caller_port = int(_tts_dest.port)

                # 4) AEC far-end 참조 (실제 미디어만)
                if not pcm_is_silence and self._aec_processor:
                    _aec_t0 = time.perf_counter()
                    with self._aec_lock:
                        for i in range(0, len(frame_data), AEC_FRAME_BYTES):
                            aec_chunk = frame_data[i : i + AEC_FRAME_BYTES]
                            if len(aec_chunk) == AEC_FRAME_BYTES:
                                self._aec_processor.feed_reverse_stream(aec_chunk)
                    _aec_hold_ms = (time.perf_counter() - _aec_t0) * 1000.0
                    if _aec_hold_ms >= 12.0:
                        logger.warning(
                            "tts_sender_aec_lock_hold_ms",
                            call_id=self.media_session.call_id,
                            progress="rtp_timing",
                            hold_ms=round(_aec_hold_ms, 2),
                            pcm_bytes=len(frame_data),
                            note="AEC 락 점유가 길면 20ms 슬롯 밀림 가능",
                        )

                # 5) PCM → RTP 패킷 빌드
                rtp_packets = self._rtp_packet_builder.build_packets(frame_data, 16000)

                if not rtp_packets:
                    self._rtp_packets_sent_total += 1
                    target_time = self._rtp_base_time + (self._rtp_packets_sent_total * FIXED_INTERVAL_SEC)
                    self._wait_until_send_deadline(target_time)
                    continue

                # 6) 20ms 절대 시간 격자에 맞춰 전송
                for packet in rtp_packets:

                    _rtp_seq_hdr = struct.unpack_from("!H", packet, 2)[0]
                    _rtp_ts_hdr = struct.unpack_from("!I", packet, 4)[0]

                    target_time = self._rtp_base_time + (self._rtp_packets_sent_total * FIXED_INTERVAL_SEC)
                    now_before = time.perf_counter()
                    sleep_needed = target_time - now_before

                    # 소폭 지연 로그 (200ms 미만)
                    if sleep_needed < 0:
                        behind_schedule_count += 1
                        _late_ms = -sleep_needed * 1000.0
                        if _late_ms > 200.0:
                            logger.warning(
                                "rtp_send_behind_schedule_severe",
                                call_id=self.media_session.call_id,
                                progress="rtp_timing",
                                late_ms=round(_late_ms, 2),
                                behind_schedule_count=behind_schedule_count,
                                packets_sent=packets_sent,
                                pcm_queue_size=self._pipecat_pcm_queue.qsize(),
                                pcm_buffer_size=len(pcm_buffer),
                                note="200ms 이상 지연 — AEC 락 경합 또는 CPU 부족 가능",
                            )
                        elif behind_schedule_count <= 20 or behind_schedule_count % 50 == 0:
                            logger.debug(
                                "rtp_send_behind_schedule",
                                call_id=self.media_session.call_id,
                                progress="rtp_timing",
                                late_ms=round(_late_ms, 2),
                                behind_schedule_count=behind_schedule_count,
                            )

                    if sleep_needed > 0:
                        self._wait_until_send_deadline(target_time)

                    now_after = time.perf_counter()

                    # 이전 패킷과의 간격 (모니터링)
                    if self._rtp_packets_sent_total > 0:
                        interval_from_prev_ms = (now_after - self._rtp_last_send_time) * 1000
                    else:
                        interval_from_prev_ms = 0.0

                    # 디버깅: 첫 30개 패킷 타이밍
                    if packets_sent < 30:
                        expected_from_base_ms = self._rtp_packets_sent_total * FIXED_INTERVAL_SEC * 1000
                        actual_from_base_ms = (now_after - self._rtp_base_time) * 1000
                        logger.info("rtp_packet_timing_absolute",
                                   call_id=self.media_session.call_id,
                                   progress="rtp_timing",
                                   packet_seq=packets_sent,
                                   is_silence=pcm_is_silence,
                                   expected_time_from_base_ms=round(expected_from_base_ms, 2),
                                   actual_time_from_base_ms=round(actual_from_base_ms, 2),
                                   timing_error_ms=round(actual_from_base_ms - expected_from_base_ms, 2),
                                   interval_from_prev_ms=round(interval_from_prev_ms, 2),
                                   note="절대 시간 기반 (20ms 격자, base_time 고정)")

                    # 타이밍 위반 추적
                    if self._rtp_packets_sent_total > 0:
                        expected_interval_ms = FIXED_INTERVAL_SEC * 1000
                        if abs(interval_from_prev_ms - expected_interval_ms) > INTERVAL_TOLERANCE_MS:
                            interval_violations += 1
                            if interval_violations <= 5 or interval_violations % 50 == 0:
                                logger.warning(
                                    "rtp_interval_violation",
                                    call_id=self.media_session.call_id,
                                    progress="rtp_timing",
                                    expected_ms=int(expected_interval_ms),
                                    actual_ms=round(interval_from_prev_ms, 1),
                                    violation_count=interval_violations,
                                    packets_sent=packets_sent,
                                    is_silence=pcm_is_silence,
                                    pcm_buffer_size=len(pcm_buffer),
                                    note="고정 간격 이탈 (Jitter 모니터링)",
                                )

                    self._rtp_last_send_time = now_after
                    self._rtp_packets_sent_total += 1

                    if not self._timing_first_tts_rtp_sent_logged and not pcm_is_silence:
                        self._timing_first_tts_rtp_sent_logged = True
                        from datetime import datetime
                        logger.info(
                            "timing_first_tts_rtp_sent_to_caller",
                            call_id=self.media_session.call_id,
                            progress="timing",
                            ts_iso=datetime.now().isoformat(timespec="milliseconds"),
                            note="TTS→RTP 첫 미디어 패킷 큐 투입(송신 스레드)",
                        )

                    # 7) UDP 출력 큐에 넣기
                    audio_payload = packet[12:] if len(packet) > 12 else packet
                    out_q = self._tts_udp_out_queue
                    if out_q is None:
                        return
                    try:
                        _tx_kind = "silence" if pcm_is_silence else "media"
                        out_q.put_nowait(
                            (packet, (caller_ip, caller_port), audio_payload, {"tx_kind": _tx_kind})
                        )
                        self._tts_last_udp_enqueued_mono = time.perf_counter()
                        _out_depth = out_q.qsize()
                        if _out_depth >= 48:
                            _lw = getattr(self, "_tts_udp_backlog_last_warn_packet", -10**9)
                            if packets_sent - _lw >= 40 or _out_depth >= 96:
                                self._tts_udp_backlog_last_warn_packet = packets_sent
                                logger.warning(
                                    "tts_udp_out_queue_backlog_high",
                                    call_id=self.media_session.call_id,
                                    progress="rtp_timing",
                                    queue_size=_out_depth,
                                    packets_sent_thread=packets_sent,
                                    note="UDP 큐 적체 — 송신 스레드가 루프 sendto보다 빠름",
                                )
                    except queue.Full:
                        self.stats["rtp_tts_packets_dropped"] = (
                            self.stats.get("rtp_tts_packets_dropped", 0) + 1
                        )
                        logger.warning(
                            "tts_udp_out_queue_full_drop",
                            call_id=self.media_session.call_id,
                            progress="rtp_debug",
                            total_dropped=self.stats["rtp_tts_packets_dropped"],
                            note="UDP 큐 가득 — 패킷 드롭",
                        )
                        self.emit_rtp_health_snapshot("tts_udp_out_queue_full")
                        continue
                    self._wake_tts_udp_drain()
                    packets_sent += 1
                    if not pcm_is_silence:
                        media_packets_sent += 1
                    self.stats["rtp_tts_thread_packets_queued"] = packets_sent

                    # 바이트 누적 (미디어만)
                    if not pcm_is_silence:
                        bytes_sent_cumulative += len(frame_data)
                        if not _logged_3s and bytes_sent_cumulative >= 96000:
                            _logged_3s = True
                            logger.info("rtp_sent_3s_equivalent",
                                        call_id=self.media_session.call_id,
                                        progress="rtp_timing",
                                        bytes_sent_cumulative=bytes_sent_cumulative,
                                        media_packets=media_packets_sent,
                                        total_packets=packets_sent,
                                        note="미디어 3초 상당(≈96KB) 전송")

                    # 간격 통계 (50패킷마다)
                    if interval_from_prev_ms > 0:
                        recent_intervals_ms.append(round(interval_from_prev_ms, 2))
                        if len(recent_intervals_ms) > 50:
                            recent_intervals_ms.pop(0)
                    if packets_sent > 0 and packets_sent % 50 == 0 and recent_intervals_ms:
                        _iv = recent_intervals_ms
                        _out_q = getattr(self, "_tts_udp_out_queue", None)
                        _udp_stat = self.stats.get("rtp_tts_packets_sent", 0)
                        _out_sz = _out_q.qsize() if _out_q is not None else -1
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
                            pcm_buffer_size=len(pcm_buffer),
                            silence_streak=silence_streak,
                            tts_udp_out_queue_size=_out_sz,
                            thread_packets_queued=packets_sent,
                            media_packets=media_packets_sent,
                            udp_packets_sent_stat=_udp_stat,
                            note="최근 50패킷 간격 요약 (지속 무음 전송 모드)",
                        )

                    # 무음 연속 로그 (처음 1회 + 이후 100회마다)
                    if pcm_is_silence and (silence_streak == 1 or silence_streak % 100 == 0):
                        logger.debug(
                            "rtp_continuous_silence",
                            call_id=self.media_session.call_id,
                            silence_streak=silence_streak,
                            packets_sent=packets_sent,
                            pcm_queue_size=self._pipecat_pcm_queue.qsize(),
                            note="지속적 무음 전송 중 (큐 비어있음, 20ms 격자 유지)",
                        )

            except Exception as e:
                self.stats["rtp_tts_send_errors"] += 1
                # 프로세스 종료 시 로그 파일이 먼저 닫힌 후 daemon 스레드가
                # 아직 실행 중일 수 있다 (stop_async_logging 타이밍 경쟁).
                # ValueError("I/O operation on closed file") 는 무해하므로
                # stderr fallback 으로만 출력하고 루프를 종료한다.
                if isinstance(e, ValueError) and "closed file" in str(e):
                    import sys as _sys
                    print(
                        f"[tts_rtp_thread] logger closed — thread exiting: {e}",
                        file=_sys.stderr,
                    )
                    return
                try:
                    logger.error(
                        "pcm_sender_thread_error",
                        call_id=self.media_session.call_id,
                        error=str(e),
                        error_type=type(e).__name__,
                        send_errors_total=self.stats["rtp_tts_send_errors"],
                    )
                except (ValueError, OSError):
                    # 로그 파일이 이미 닫힌 경우 조용히 무시
                    pass

    def enable_pipecat_mode(self):
        """
        Pipecat 파이프라인 모드 활성화 (현재 기본 AI 응대 경로).

        config.pipeline_engine = "pipecat" (기본값) 일 때 호출됨.
        TTS→RTP: thread-safe PCM 큐 + 전용 송신 스레드(적응형 패이싱) + 루프에서 UDP sendto.
        """
        self._pipecat_audio_queue = asyncio.Queue(maxsize=1000)
        self._pipecat_mode = True
        self.ai_mode = True  # AI 모드도 함께 활성화

        # RTP 패킷 빌더 생성 (TTS -> RTP 변환용)
        from src.ai_voicebot.pipecat.audio_utils import RTPPacketBuilder
        codec = getattr(self.media_session, 'codec', 'PCMU')
        self._rtp_packet_builder = RTPPacketBuilder(codec=codec)

        # TTS PCM 큐: asyncio 루프(put) ↔ 송신 전용 스레드(get), maxsize=1000 청크 (20초 버퍼, TTS 청크 지연 흡수)
        self._pipecat_pcm_queue = queue.Queue(maxsize=1000)
        # 스레드 → 루프: RTP 바이트만 넘김 (Proactor에서 sendto는 루프 스레드에서 실행)
        self._tts_udp_out_queue = queue.Queue(maxsize=2048)

        # ✅ 절대 시간 기반 RTP 타이밍 변수 초기화
        self._rtp_base_time = None
        self._rtp_packets_sent_total = 0
        self._rtp_last_send_time = None
        self._rtp_new_segment_after_empty = False  # Phase2 등 큐 재개 시 1초 리셋 미적용 플래그
        self._tts_last_rtp_seq_sent = None
        self._tts_last_rtp_ts_sent = None
        self._tts_udp_drain_task = None
        self._pipecat_outgoing_task = None
        self._rtp_keepalive_logged = False
        self._rtp_keepalive_empty_streak = 0
        self._tts_last_udp_enqueued_mono = 0.0

        # AEC (선택): aec-audio-processing 있으면 활성화
        from src.media.aec_processor import create_aec_processor
        self._aec_processor = create_aec_processor(16000, 1, 50)
        self._aec_near_buffer = b""
        if self._aec_processor:
            logger.info("aec_enabled", call_id=self.media_session.call_id, note="WebRTC AEC 활성화")
        
        # ✅ 적응형 패킷 간격 활성화 로그
        if getattr(self, "_adaptive_interval_enabled", True):
            logger.info("rtp_adaptive_interval_enabled",
                       call_id=self.media_session.call_id,
                       threshold_normal=getattr(self, "_adaptive_interval_threshold_normal", 5),
                       threshold_slight=getattr(self, "_adaptive_interval_threshold_slight", 10),
                       threshold_burst=getattr(self, "_adaptive_interval_threshold_burst", 15),
                       note="RTP 적응형 패킷 간격 활성화 — 큐 백로그에 따라 12~20ms 동적 조정")
        else:
            logger.info("rtp_adaptive_interval_disabled",
                       call_id=self.media_session.call_id,
                       note="RTP 적응형 패킷 간격 비활성화 — 고정 20ms 간격 사용")
        
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.get_event_loop()
        self._event_loop = loop

        self._tts_sender_thread = threading.Thread(
            target=self._pcm_sender_thread_main,
            name=f"tts_rtp_{self.media_session.call_id}",
            daemon=True,
        )
        self._tts_sender_thread.start()

        _tts_dest = self.tts_dest_endpoint or self.caller_endpoint
        logger.info(
            "pipecat_mode_enabled",
            call_id=self.media_session.call_id,
            codec=codec,
            ssrc=self._rtp_packet_builder.ssrc,
            caller_endpoint=f"{self.caller_endpoint.ip}:{self.caller_endpoint.port}",
            tts_dest_endpoint=f"{_tts_dest.ip}:{_tts_dest.port}",
            has_transport=self.caller_audio_transport is not None or self.callee_audio_transport is not None,
            note="Pipecat 모드: PCM Queue + TTS RTP 송신 전용 스레드(20ms) + 루프 UDP 전송",
        )
    
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
        실제 RTP 변환·20ms 패이싱은 전용 스레드(_pcm_sender_thread_main), UDP sendto는 이벤트 루프(_drain_tts_udp_out_queue).
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
            
            # ✅ 청크 간 도착 간격 추적 (TTS 생성 속도 모니터링)
            now_mono = time.perf_counter()
            if not hasattr(self, '_last_pcm_enqueue_mono'):
                self._last_pcm_enqueue_mono = None
            gap_ms = None
            if self._last_pcm_enqueue_mono is not None:
                gap_ms = (now_mono - self._last_pcm_enqueue_mono) * 1000
                if gap_ms > 100:  # 100ms 초과 시 경고
                    logger.warning(
                        "pcm_chunk_gap_large",
                        call_id=self.media_session.call_id,
                        progress="rtp_timing",
                        gap_ms=round(gap_ms, 1),
                        chunk_seq=(getattr(self, '_audio_chunks_total', 0) + 1),
                        queue_size=self._pipecat_pcm_queue.qsize(),
                        note="TTS 청크 간 gap 100ms 초과 → 큐 고갈 위험 (Google TTS 스트리밍 지연)"
                    )
            self._last_pcm_enqueue_mono = now_mono
            
            # ✅ 큐 투입 직전 타임스탬프 (244ms 갭 원인 추적)
            queue_put_before = time.perf_counter()
            self._pipecat_pcm_queue.put_nowait(pcm_data)
            queue_put_after = time.perf_counter()
            queue_put_elapsed_ms = (queue_put_after - queue_put_before) * 1000
            
            qsize = self._pipecat_pcm_queue.qsize()
            if not hasattr(self, '_audio_chunks_logged'):
                self._audio_chunks_logged = 0
            if not hasattr(self, '_audio_chunks_total'):
                self._audio_chunks_total = 0
                self._audio_bytes_total = 0

            self._audio_chunks_total += 1
            self._audio_bytes_total += pcm_len
            
            # ✅ 첫 PCM 큐 투입 시점 로그 (send_audio_to_caller 내부)
            if self._audio_chunks_total == 1:
                logger.info("send_audio_first_pcm_queued",
                           call_id=self.media_session.call_id,
                           progress="tts",
                           pcm_bytes=pcm_len,
                           queue_put_elapsed_ms=round(queue_put_elapsed_ms, 3),
                           queue_size_after=qsize,
                           ts_iso=datetime.now().isoformat(timespec="milliseconds"),
                           note="send_audio_to_caller 첫 PCM 큐 투입 완료 (RTP 송신 스레드가 get할 차례)")

            _tctx = self._tts_rtp_log_context_dict()
            _tverb = self._tts_rtp_trace_verbose_call()
            if _tctx.get("tts_stream_label") or _tverb:
                with self._tts_rtp_log_lock:
                    self._tts_rtp_pcm_trace_count += 1
                    _tc = self._tts_rtp_pcm_trace_count
                if _tverb or _tc <= 12 or _tc % 15 == 0:
                    logger.info(
                        "tts_rtp_trace_pcm_enqueued",
                        call_id=self.media_session.call_id,
                        progress="rtp_tts_trace",
                        pcm_chunk_index=_tc,
                        pcm_bytes=pcm_len,
                        pcm_queue_size_after=qsize,
                        sample_rate=sample_rate,
                        est_duration_ms=(
                            round((pcm_len / 2 / sample_rate) * 1000, 1)
                            if sample_rate
                            else None
                        ),
                        total_pcm_chunks_session=self._audio_chunks_total,
                        trace_call_id_verbose=_tverb,
                        **_tctx,
                        dest_caller_rtp="{ip}:{port}".format(
                            ip=(self.tts_dest_endpoint or self.caller_endpoint).ip,
                            port=(self.tts_dest_endpoint or self.caller_endpoint).port,
                        ),
                        note="TTS PCM→송신 스레드 큐 투입 (인사·대기안내 stream_label과 RTP 끊김 상관)",
                    )
            
            # ✅ 모든 PCM 큐 투입 로깅 (유실 추적용)
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
            
            # 백로그 과다 시 1회 경고 (발송 지연·끊김 가능) — maxsize 1000 기준 800에서 경고
            if qsize >= 800 and not getattr(self, '_pcm_backlog_warned', False):
                self._pcm_backlog_warned = True
                logger.warning("rtp_tts_pcm_queue_backlog_high",
                               call_id=self.media_session.call_id,
                               queue_size=qsize,
                               maxsize=self._pipecat_pcm_queue.maxsize,
                               note="PCM 큐 백로그 큼 — 발송 루프가 TTS 속도를 따라가지 못할 수 있음")
        except queue.Full:
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
        """Pipecat 모드 정지 (PCM/오디오 큐·송신 스레드·UDP 드레인·AEC 포함)"""
        self._pipecat_mode = False

        # ✅ 타이밍 요약: stats는 세션 누적, _rtp_packets_sent_total은 소프트 리싱크마다 리셋되므로 혼용하지 않음
        _seg_packets = int(getattr(self, "_rtp_packets_sent_total", 0) or 0)
        _session_packets = int(self.stats.get("rtp_tts_packets_sent", 0) or 0)
        if _session_packets > 0 or _seg_packets > 0:
            _expected_session_ms = round(_session_packets * self._RTP_PACKET_MS, 2)
            _kw = dict(
                call_id=self.media_session.call_id,
                progress="rtp_timing",
                rtp_tts_packets_sent_session=_session_packets,
                last_grid_segment_packets=_seg_packets,
                expected_audio_ms_from_session_packets=_expected_session_ms,
                note="expected_audio_ms = 세션 TTS RTP 패킷 수×20ms; last_grid_segment_packets는 마지막 base_time 구간만",
            )
            if (
                getattr(self, "_rtp_base_time", None) is not None
                and getattr(self, "_rtp_last_send_time", None) is not None
                and _seg_packets > 0
            ):
                _wall_ms = (self._rtp_last_send_time - self._rtp_base_time) * 1000
                _kw["last_segment_wall_ms"] = round(_wall_ms, 2)
                _expected_seg_ms = _seg_packets * self._RTP_PACKET_MS
                _kw["expected_audio_ms_last_segment"] = round(_expected_seg_ms, 2)
                _kw["last_segment_timing_error_ms"] = round(_wall_ms - _expected_seg_ms, 2)
            logger.info("rtp_absolute_timing_summary", **_kw)

        self._aec_processor = None
        self._aec_near_buffer = b""
        if self._pipecat_audio_queue:
            try:
                self._pipecat_audio_queue.put_nowait(None)
            except asyncio.QueueFull:
                pass
        pcm_q = getattr(self, '_pipecat_pcm_queue', None)
        if pcm_q is not None:
            try:
                pcm_q.put_nowait(None)
            except queue.Full:
                pass
        th = getattr(self, '_tts_sender_thread', None)
        if th is not None and th.is_alive():
            # 남은 pcm_buffer 드레인 시간 고려 (최대 15초 TTS + 여유)
            th.join(timeout=20.0)
            if th.is_alive():
                logger.warning("tts_sender_thread_join_timeout",
                              call_id=self.media_session.call_id,
                              note="sender thread가 20초 내 종료되지 않음")
        self._tts_sender_thread = None

        # 타이밍 상태 리셋: 스레드 join 완료 후 리셋해야 None+float TypeError를 방지할 수 있음
        # (스레드가 살아있는 동안 _rtp_base_time=None으로 만들면 target_time 계산에서 에러 발생)
        self._rtp_base_time = None
        self._rtp_packets_sent_total = 0
        self._rtp_last_send_time = None
        self._rtp_new_segment_after_empty = False

        self._flush_tts_udp_queue_blocking()
        self._rtp_tx_debug_close()

        tdt = getattr(self, '_tts_udp_drain_task', None)
        if tdt is not None and not tdt.done():
            tdt.cancel()
        self._tts_udp_drain_task = None
        self._pipecat_outgoing_task = None
        self._tts_udp_out_queue = None
        self._event_loop = None
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
        self._rtp_rx_last_mono: Optional[float] = None
        self._bypass_relay_sample_seq: Optional[int] = None
    
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
                            try:
                                self.relay_worker.bridge_callee_transport.sendto(data, bridge_addr)
                            except OSError as ose:
                                logger.error(
                                    "rtp_bridge_sendto_failed",
                                    call_id=self.relay_worker.media_session.call_id,
                                    progress="rtp_debug",
                                    leg="caller_to_bridge_callee",
                                    dest=f"{bridge_addr[0]}:{bridge_addr[1]}",
                                    errno=getattr(ose, "errno", None),
                                    winerror=getattr(ose, "winerror", None),
                                    error=str(ose),
                                    hypothesis="bridge_media_path_or_firewall",
                                )
                        self.relay_worker.on_packet_received(self.socket_type, data, addr)
                        return
                    elif self.socket_type == "bridge_callee_rtp":
                        # New Callee 음성 → Caller로 전달
                        if self.relay_worker.caller_audio_transport:
                            caller_addr = (
                                str(self.relay_worker.caller_endpoint.ip),
                                int(self.relay_worker.caller_endpoint.port)
                            )
                            try:
                                self.relay_worker.caller_audio_transport.sendto(data, caller_addr)
                            except OSError as ose:
                                logger.error(
                                    "rtp_bridge_sendto_failed",
                                    call_id=self.relay_worker.media_session.call_id,
                                    progress="rtp_debug",
                                    leg="bridge_callee_to_caller",
                                    dest=f"{caller_addr[0]}:{caller_addr[1]}",
                                    errno=getattr(ose, "errno", None),
                                    winerror=getattr(ose, "winerror", None),
                                    error=str(ose),
                                    hypothesis="bridge_media_path_or_firewall",
                                )
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
                
                hdr = _rtp_peek_header(data)
                now_mono = time.perf_counter()
                inter_ms = None
                seq_gap = None
                if hdr and self._rtp_rx_last_mono is not None:
                    inter_ms = (now_mono - self._rtp_rx_last_mono) * 1000.0
                if hdr and self._bypass_relay_sample_seq is not None:
                    seq_gap = (hdr["seq"] - self._bypass_relay_sample_seq) & 0xFFFF
                if hdr:
                    self._rtp_rx_last_mono = now_mono
                    self._bypass_relay_sample_seq = hdr["seq"]

                try:
                    self.transport.sendto(data, remote_addr)
                except OSError as ose:
                    self.relay_worker.stats["bypass_relay_send_failed"] = (
                        self.relay_worker.stats.get("bypass_relay_send_failed", 0) + 1
                    )
                    logger.error(
                        "rtp_bypass_sendto_failed",
                        call_id=self.relay_worker.media_session.call_id,
                        progress="rtp_debug",
                        socket_type=self.socket_type,
                        remote_addr=f"{remote_addr[0]}:{remote_addr[1]}",
                        payload_len=len(data),
                        errno=getattr(ose, "errno", None),
                        winerror=getattr(ose, "winerror", None),
                        error=str(ose),
                        hypothesis=(
                            "icmp_port_unreachable_or_firewall"
                            if getattr(ose, "winerror", None) == 10054
                            or getattr(ose, "errno", None) in (89, 101, 111, 113)
                            else "udp_sendto_os_error"
                        ),
                        note="Bypass 릴레이 sendto 실패 — 상대 미디어 포트·NAT·방화벽·endpoint 불일치 추적",
                    )
                    self.relay_worker.emit_rtp_health_snapshot("bypass_sendto_failed")
                    return
                self.relay_worker.stats["bypass_relay_sent"] = (
                    self.relay_worker.stats.get("bypass_relay_sent", 0) + 1
                )
                n = self.relay_worker.stats["bypass_relay_sent"]
                if hdr and (
                    n <= 12
                    or n % 400 == 0
                    or (inter_ms is not None and inter_ms > 55.0)
                    or (seq_gap is not None and seq_gap > 2)
                ):
                    logger.info(
                        "rtp_bypass_relay_sent",
                        call_id=self.relay_worker.media_session.call_id,
                        progress="rtp_debug",
                        socket_type=self.socket_type,
                        relay_count=n,
                        from_addr=f"{addr[0]}:{addr[1]}",
                        to_addr=f"{remote_addr[0]}:{remote_addr[1]}",
                        payload_len=len(data),
                        rtp_seq=hdr["seq"] if hdr else None,
                        rtp_ts=hdr["ts"] if hdr else None,
                        rtp_pt=hdr["pt"] if hdr else None,
                        interarrival_ms=round(inter_ms, 2) if inter_ms is not None else None,
                        seq_jump_from_prev=seq_gap,
                        hypothesis=(
                            "rx_burst_or_sched_jitter"
                            if inter_ms is not None and inter_ms > 55
                            else (
                                "possible_packet_loss_or_reorder"
                                if seq_gap is not None and seq_gap > 2
                                else "steady_relay"
                            )
                        ),
                        note="Bypass RTP relay OK — interarrival≈20ms 기대, seq_jump>2이면 손실·지터 의심",
                    )
                if n % 500 == 0:
                    self.relay_worker.emit_rtp_health_snapshot("bypass_relay_tick")

                self.relay_worker.on_packet_received(self.socket_type, data, addr)
                
            except Exception as e:
                logger.error(
                    "rtp_relay_error",
                    call_id=self.relay_worker.media_session.call_id,
                    socket_type=self.socket_type,
                    error=str(e),
                    error_type=type(e).__name__,
                )
    
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
        _kw: dict = {
            "call_id": self.relay_worker.media_session.call_id,
            "socket_type": self.socket_type,
            "error": str(exc),
            "error_type": type(exc).__name__,
            "progress": "rtp_debug",
        }
        if isinstance(exc, OSError):
            _kw["errno"] = getattr(exc, "errno", None)
            _kw["winerror"] = getattr(exc, "winerror", None)
            we = getattr(exc, "winerror", None)
            _kw["hypothesis"] = (
                "icmp_port_unreachable_common_on_win"
                if we == 10054
                else "os_udp_socket_error"
            )
        else:
            _kw["hypothesis"] = "asyncio_datagram_error"
        _kw["note"] = "UDP 소켓 async 에러 — ICMP unreachable(Win 10054)·미디어 경로 단절 시 빈번"
        logger.error("rtp_datagram_socket_error_received", **_kw)
        self.relay_worker.emit_rtp_health_snapshot("datagram_error_received", min_interval_sec=2.0)
    
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

