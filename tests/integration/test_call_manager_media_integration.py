"""CallManager와 Media 모듈 통합 테스트

Story 2.4: SDP Manipulation in INVITE Flow
"""

import pytest
from src.sip_core.call_manager import CallManager
from src.sip_core.models.enums import CallState, Direction, SIPResponseCode
from src.repositories.call_state_repository import CallStateRepository
from src.media.session_manager import MediaSessionManager
from src.media.port_pool import PortPoolManager
from src.media.media_session import MediaMode
from src.media.sdp_parser import SDPParser
from src.config.models import PortPoolConfig
from src.common.logger import setup_logging
from src.common.exceptions import PortPoolExhaustedError


@pytest.fixture(scope="module", autouse=True)
def setup_test_logging():
    """테스트용 로깅 설정"""
    setup_logging(level="DEBUG", format_type="text")


# 샘플 SDP
CALLER_SDP = """v=0
o=caller 1 1 IN IP4 192.168.1.100
s=Call
c=IN IP4 192.168.1.100
t=0 0
m=audio 5004 RTP/AVP 0 8 101
a=rtpmap:0 PCMU/8000
a=rtpmap:8 PCMA/8000
a=rtpmap:101 telephone-event/8000
"""

CALLEE_SDP = """v=0
o=callee 2 2 IN IP4 192.168.1.200
s=Call
c=IN IP4 192.168.1.200
t=0 0
m=audio 6000 RTP/AVP 0 8
a=rtpmap:0 PCMU/8000
a=rtpmap:8 PCMA/8000
"""


@pytest.fixture
def port_pool():
    """테스트용 Port Pool"""
    config = PortPoolConfig(start=10000, end=10100)
    return PortPoolManager(config)


@pytest.fixture
def media_session_manager(port_pool):
    """테스트용 Media Session Manager"""
    return MediaSessionManager(port_pool, default_mode=MediaMode.REFLECTING)


@pytest.fixture
def call_repository():
    """테스트용 Call Repository"""
    return CallStateRepository()


@pytest.fixture
def call_manager_with_media(call_repository, media_session_manager):
    """미디어 통합된 Call Manager"""
    return CallManager(
        call_repository=call_repository,
        media_session_manager=media_session_manager,
        b2bua_ip="10.0.0.1",
    )


class TestCallManagerMediaIntegration:
    """CallManager와 Media 모듈 통합 기본 테스트"""
    
    def test_incoming_invite_with_media_session_creation(self, call_manager_with_media):
        """INVITE 수신 시 미디어 세션 생성"""
        session, response_code = call_manager_with_media.handle_incoming_invite(
            from_uri="sip:alice@example.com",
            to_uri="sip:bob@example.com",
            call_id_header="test-call-1",
            sdp=CALLER_SDP,
        )
        
        # 응답 코드 확인
        assert response_code == SIPResponseCode.TRYING
        
        # Call Session 확인
        assert session.state == CallState.PROCEEDING
        assert session.incoming_leg is not None
        
        # 미디어 세션 생성 확인
        media_session = call_manager_with_media.media_session_manager.get_session(session.call_id)
        assert media_session is not None
        assert len(media_session.caller_leg.allocated_ports) == 4
        assert len(media_session.callee_leg.allocated_ports) == 4
    
    def test_outgoing_invite_sdp_modification(self, call_manager_with_media):
        """Outgoing INVITE 생성 시 SDP 수정"""
        # Incoming INVITE
        session, _ = call_manager_with_media.handle_incoming_invite(
            from_uri="sip:alice@example.com",
            to_uri="sip:bob@example.com",
            call_id_header="test-call-2",
            sdp=CALLER_SDP,
        )
        
        # Outgoing INVITE 생성
        outgoing_leg, modified_sdp = call_manager_with_media.create_outgoing_invite(
            session,
            b2bua_contact="sip:pbx@10.0.0.1:5060"
        )
        
        # SDP 수정 확인
        parsed = SDPParser.parse(modified_sdp)
        
        # IP가 B2BUA IP로 변경되었는지 확인
        assert parsed.connection_ip == "10.0.0.1"
        
        # 포트가 할당된 포트로 변경되었는지 확인
        media_session = call_manager_with_media.media_session_manager.get_session(session.call_id)
        expected_audio_port = media_session.callee_leg.get_audio_rtp_port()
        assert parsed.get_audio_port() == expected_audio_port
        
        # 원본 코덱 정보 유지 확인
        audio = parsed.get_media_by_type("audio")
        assert audio.formats == ["0", "8", "101"]  # 원본과 동일
    
    def test_200_ok_response_sdp_modification(self, call_manager_with_media):
        """200 OK 응답 시 SDP 수정"""
        # Incoming INVITE
        session, _ = call_manager_with_media.handle_incoming_invite(
            from_uri="sip:alice@example.com",
            to_uri="sip:bob@example.com",
            call_id_header="test-call-3",
            sdp=CALLER_SDP,
        )
        
        # Outgoing INVITE
        call_manager_with_media.create_outgoing_invite(session, "sip:pbx@10.0.0.1:5060")
        
        # 200 OK from callee
        modified_sdp = call_manager_with_media.handle_200_ok_response(
            session,
            CALLEE_SDP,
            Direction.OUTGOING
        )
        
        # SDP 수정 확인
        parsed = SDPParser.parse(modified_sdp)
        
        # IP가 B2BUA IP로 변경
        assert parsed.connection_ip == "10.0.0.1"
        
        # 포트가 Caller leg 할당 포트로 변경
        media_session = call_manager_with_media.media_session_manager.get_session(session.call_id)
        expected_audio_port = media_session.caller_leg.get_audio_rtp_port()
        assert parsed.get_audio_port() == expected_audio_port
        
        # Callee SDP가 미디어 세션에 저장되었는지 확인
        assert media_session.callee_leg.original_sdp is not None
    
    def test_full_b2bua_call_flow_with_sdp(self, call_manager_with_media):
        """전체 B2BUA 통화 흐름 (SDP 수정 포함)"""
        # 1. Incoming INVITE
        session, response = call_manager_with_media.handle_incoming_invite(
            from_uri="sip:alice@example.com",
            to_uri="sip:bob@example.com",
            call_id_header="full-flow-call",
            sdp=CALLER_SDP,
        )
        
        assert response == SIPResponseCode.TRYING
        
        # 미디어 세션 확인
        media_session = call_manager_with_media.media_session_manager.get_session(session.call_id)
        assert media_session is not None
        
        # 2. Outgoing INVITE
        outgoing_leg, outgoing_sdp = call_manager_with_media.create_outgoing_invite(
            session,
            "sip:pbx@10.0.0.1:5060"
        )
        
        # Outgoing SDP 검증
        outgoing_parsed = SDPParser.parse(outgoing_sdp)
        assert outgoing_parsed.connection_ip == "10.0.0.1"
        
        # 3. 180 Ringing
        call_manager_with_media.handle_provisional_response(session, SIPResponseCode.RINGING, "Ringing")
        
        # 4. 200 OK from callee
        incoming_sdp = call_manager_with_media.handle_200_ok_response(
            session,
            CALLEE_SDP,
            Direction.OUTGOING
        )
        
        # Incoming SDP 검증
        incoming_parsed = SDPParser.parse(incoming_sdp)
        assert incoming_parsed.connection_ip == "10.0.0.1"
        
        # 5. ACK
        call_manager_with_media.handle_ack(session, Direction.INCOMING)
        assert session.state == CallState.ESTABLISHED
        
        # 6. BYE
        call_manager_with_media.handle_bye(session, Direction.INCOMING, reason="normal")
        
        # 7. Cleanup
        cdr_data = call_manager_with_media.cleanup_terminated_call(session)
        
        # 미디어 세션 정리 확인
        media_session = call_manager_with_media.media_session_manager.get_session(session.call_id)
        assert media_session is None  # 정리됨
        
        # 포트 반환 확인
        port_alloc = call_manager_with_media.media_session_manager.port_pool.get_allocation(session.call_id)
        assert port_alloc is None
    
    def test_port_exhaustion_returns_503(self, call_repository, media_session_manager):
        """포트 고갈 시 503 Service Unavailable 응답"""
        # 작은 포트 풀로 CallManager 생성
        small_config = PortPoolConfig(start=10000, end=10015)  # 최대 2호만 가능
        small_pool = PortPoolManager(small_config)
        small_media_manager = MediaSessionManager(small_pool)
        
        call_manager = CallManager(
            call_repository=call_repository,
            media_session_manager=small_media_manager,
            b2bua_ip="10.0.0.1",
        )
        
        # 최대 호수까지 생성
        max_calls = small_pool.get_max_concurrent_calls()
        for i in range(max_calls):
            session, response = call_manager.handle_incoming_invite(
                from_uri=f"sip:user{i}@example.com",
                to_uri="sip:bob@example.com",
                call_id_header=f"call-{i}",
                sdp=CALLER_SDP,
            )
            assert response == SIPResponseCode.TRYING
        
        # 추가 INVITE (포트 고갈)
        session, response = call_manager.handle_incoming_invite(
            from_uri="sip:overflow@example.com",
            to_uri="sip:bob@example.com",
            call_id_header="overflow-call",
            sdp=CALLER_SDP,
        )
        
        # 503 Service Unavailable 응답 확인
        assert response == SIPResponseCode.SERVICE_UNAVAILABLE
    
    def test_codec_preservation_through_flow(self, call_manager_with_media):
        """통화 흐름 전체에서 코덱 정보 보존 확인"""
        # INVITE
        session, _ = call_manager_with_media.handle_incoming_invite(
            from_uri="sip:alice@example.com",
            to_uri="sip:bob@example.com",
            call_id_header="codec-test",
            sdp=CALLER_SDP,
        )
        
        # Outgoing INVITE SDP
        _, outgoing_sdp = call_manager_with_media.create_outgoing_invite(
            session,
            "sip:pbx@10.0.0.1:5060"
        )
        
        # 코덱 정보 확인
        parsed = SDPParser.parse(outgoing_sdp)
        audio = parsed.get_media_by_type("audio")
        
        # 원본 CALLER_SDP와 동일한 코덱
        assert audio.formats == ["0", "8", "101"]
        assert "rtpmap" in audio.attributes


class TestMedialessCallManager:
    """미디어 매니저 없는 CallManager 테스트 (하위 호환성)"""
    
    def test_call_manager_without_media_manager(self, call_repository):
        """미디어 매니저 없이도 동작하는지 확인"""
        call_manager = CallManager(
            call_repository=call_repository,
            media_session_manager=None,  # 미디어 비활성화
        )
        
        # INVITE 처리
        session, response = call_manager.handle_incoming_invite(
            from_uri="sip:alice@example.com",
            to_uri="sip:bob@example.com",
            call_id_header="no-media-call",
            sdp=CALLER_SDP,
        )
        
        # 정상 처리 (미디어 없이)
        assert response == SIPResponseCode.TRYING
        assert session.state == CallState.PROCEEDING
        
        # Outgoing INVITE (SDP 수정 없이)
        outgoing_leg, sdp = call_manager.create_outgoing_invite(
            session,
            "sip:pbx@127.0.0.1:5060"
        )
        
        # SDP는 원본 그대로
        assert sdp == CALLER_SDP

