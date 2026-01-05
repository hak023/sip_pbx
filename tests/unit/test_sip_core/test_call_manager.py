"""Call Manager 단위 테스트"""

import pytest
from src.sip_core.call_manager import CallManager
from src.sip_core.models.call_session import CallSession
from src.sip_core.models.enums import CallState, Direction, SIPResponseCode
from src.repositories.call_state_repository import CallStateRepository
from src.common.exceptions import InvalidSIPMessageError
from src.common.logger import setup_logging


# 테스트용 샘플 SDP
SAMPLE_SDP = """v=0
o=user1 53655765 2353687637 IN IP4 192.168.1.100
s=Call
c=IN IP4 192.168.1.100
t=0 0
m=audio 5004 RTP/AVP 0 8 101
a=rtpmap:0 PCMU/8000
a=rtpmap:8 PCMA/8000
a=rtpmap:101 telephone-event/8000
"""


@pytest.fixture(scope="module", autouse=True)
def setup_test_logging():
    """테스트용 로깅 설정"""
    setup_logging(level="DEBUG", format_type="text")


@pytest.fixture
def call_repository():
    """테스트용 Call Repository"""
    return CallStateRepository()


@pytest.fixture
def call_manager(call_repository):
    """테스트용 Call Manager"""
    return CallManager(call_repository)


class TestCallManager:
    """Call Manager 기본 테스트"""
    
    def test_initialization(self, call_manager):
        """초기화 테스트"""
        assert call_manager is not None
        assert call_manager.call_repository is not None
        assert call_manager.get_active_call_count() == 0
    
    def test_handle_incoming_invite_success(self, call_manager):
        """정상 INVITE 처리 테스트"""
        # INVITE 처리
        session, response_code = call_manager.handle_incoming_invite(
            from_uri="sip:alice@example.com",
            to_uri="sip:bob@example.com",
            call_id_header="test-call-id-123",
            contact="sip:alice@192.168.1.100:5060",
            sdp=SAMPLE_SDP,
        )
        
        # 검증
        assert session is not None
        assert isinstance(session, CallSession)
        assert session.state == CallState.PROCEEDING
        assert response_code == SIPResponseCode.TRYING
        
        # Incoming Leg 검증
        assert session.incoming_leg is not None
        assert session.incoming_leg.direction == Direction.INCOMING
        assert session.incoming_leg.from_uri == "sip:alice@example.com"
        assert session.incoming_leg.to_uri == "sip:bob@example.com"
        assert session.incoming_leg.call_id_header == "test-call-id-123"
        assert session.incoming_leg.sdp_raw == SAMPLE_SDP
        
        # Repository에 저장 확인
        retrieved = call_manager.get_session(session.call_id)
        assert retrieved is not None
        assert retrieved.call_id == session.call_id
    
    def test_handle_incoming_invite_no_sdp(self, call_manager):
        """SDP 없는 INVITE 처리 테스트 (400 Bad Request)"""
        with pytest.raises(InvalidSIPMessageError) as exc_info:
            call_manager.handle_incoming_invite(
                from_uri="sip:alice@example.com",
                to_uri="sip:bob@example.com",
                call_id_header="test-call-id-456",
                sdp=None,  # SDP 없음
            )
        
        assert "SDP" in str(exc_info.value)
    
    def test_handle_incoming_invite_missing_from(self, call_manager):
        """From URI 없는 INVITE 처리 테스트"""
        with pytest.raises(InvalidSIPMessageError) as exc_info:
            call_manager.handle_incoming_invite(
                from_uri="",  # 빈 From
                to_uri="sip:bob@example.com",
                call_id_header="test-call-id-789",
                sdp=SAMPLE_SDP,
            )
        
        assert "From" in str(exc_info.value)
    
    def test_handle_incoming_invite_missing_to(self, call_manager):
        """To URI 없는 INVITE 처리 테스트"""
        with pytest.raises(InvalidSIPMessageError) as exc_info:
            call_manager.handle_incoming_invite(
                from_uri="sip:alice@example.com",
                to_uri="",  # 빈 To
                call_id_header="test-call-id-101",
                sdp=SAMPLE_SDP,
            )
        
        assert "To" in str(exc_info.value)
    
    def test_handle_incoming_invite_missing_call_id(self, call_manager):
        """Call-ID 없는 INVITE 처리 테스트"""
        with pytest.raises(InvalidSIPMessageError) as exc_info:
            call_manager.handle_incoming_invite(
                from_uri="sip:alice@example.com",
                to_uri="sip:bob@example.com",
                call_id_header="",  # 빈 Call-ID
                sdp=SAMPLE_SDP,
            )
        
        assert "Call-ID" in str(exc_info.value)
    
    def test_get_session(self, call_manager):
        """세션 조회 테스트"""
        # 세션 생성
        session, _ = call_manager.handle_incoming_invite(
            from_uri="sip:alice@example.com",
            to_uri="sip:bob@example.com",
            call_id_header="test-call-id-202",
            sdp=SAMPLE_SDP,
        )
        
        # 조회
        retrieved = call_manager.get_session(session.call_id)
        assert retrieved is not None
        assert retrieved.call_id == session.call_id
        
        # 존재하지 않는 세션 조회
        not_found = call_manager.get_session("non-existent-id")
        assert not_found is None
    
    def test_get_session_by_sip_call_id(self, call_manager):
        """SIP Call-ID로 세션 조회 테스트"""
        sip_call_id = "unique-sip-call-id-303"
        
        # 세션 생성
        session, _ = call_manager.handle_incoming_invite(
            from_uri="sip:alice@example.com",
            to_uri="sip:bob@example.com",
            call_id_header=sip_call_id,
            sdp=SAMPLE_SDP,
        )
        
        # SIP Call-ID로 조회
        retrieved = call_manager.get_session_by_sip_call_id(sip_call_id)
        assert retrieved is not None
        assert retrieved.call_id == session.call_id
        assert retrieved.incoming_leg.call_id_header == sip_call_id
    
    def test_get_active_call_count(self, call_manager):
        """활성 통화 수 테스트"""
        # 초기 상태
        assert call_manager.get_active_call_count() == 0
        
        # 첫 번째 통화
        session1, _ = call_manager.handle_incoming_invite(
            from_uri="sip:alice@example.com",
            to_uri="sip:bob@example.com",
            call_id_header="call-1",
            sdp=SAMPLE_SDP,
        )
        assert call_manager.get_active_call_count() == 1
        
        # 두 번째 통화
        session2, _ = call_manager.handle_incoming_invite(
            from_uri="sip:charlie@example.com",
            to_uri="sip:david@example.com",
            call_id_header="call-2",
            sdp=SAMPLE_SDP,
        )
        assert call_manager.get_active_call_count() == 2
        
        # 첫 번째 통화 종료
        session1.mark_terminated()
        call_manager.call_repository.update(session1)
        assert call_manager.get_active_call_count() == 1
    
    def test_parse_sdp_info(self, call_manager):
        """SDP 파싱 테스트"""
        info = call_manager.parse_sdp_info(SAMPLE_SDP)
        
        assert info["has_audio"] is True
        assert info["has_video"] is False
        assert info["connection_ip"] == "192.168.1.100"
        assert info["media_port"] == 5004


class TestCallSessionLifecycle:
    """통화 세션 생명주기 테스트"""
    
    def test_multiple_invites(self, call_manager):
        """여러 INVITE 동시 처리 테스트"""
        sessions = []
        
        for i in range(5):
            session, _ = call_manager.handle_incoming_invite(
                from_uri=f"sip:user{i}@example.com",
                to_uri="sip:pbx@example.com",
                call_id_header=f"call-{i}",
                sdp=SAMPLE_SDP,
            )
            sessions.append(session)
        
        assert call_manager.get_active_call_count() == 5
        
        # 각 세션이 독립적으로 존재
        for i, session in enumerate(sessions):
            retrieved = call_manager.get_session(session.call_id)
            assert retrieved is not None
            assert retrieved.incoming_leg.from_uri == f"sip:user{i}@example.com"


class TestOutgoingInvite:
    """Outgoing INVITE 테스트 (Story 1.5)"""
    
    def test_create_outgoing_invite_success(self, call_manager):
        """Outgoing INVITE 생성 성공 테스트"""
        # 먼저 incoming INVITE 처리
        session, _ = call_manager.handle_incoming_invite(
            from_uri="sip:alice@example.com",
            to_uri="sip:bob@example.com",
            call_id_header="incoming-call-123",
            sdp=SAMPLE_SDP,
        )
        
        # Outgoing INVITE 생성
        b2bua_contact = "sip:pbx@192.168.1.1:5060"
        outgoing_leg, sdp = call_manager.create_outgoing_invite(session, b2bua_contact)
        
        # 검증
        assert outgoing_leg is not None
        assert outgoing_leg.direction == Direction.OUTGOING
        assert outgoing_leg.from_uri == b2bua_contact  # From: B2BUA
        assert outgoing_leg.to_uri == "sip:bob@example.com"  # To: 원래 destination
        assert outgoing_leg.contact == b2bua_contact
        assert outgoing_leg.sdp_raw == SAMPLE_SDP  # SDP 복사
        
        # Call ID 매핑 확인
        assert outgoing_leg.call_id_header.startswith("outgoing-")
        assert session.call_id in outgoing_leg.call_id_header
        
        # Session 업데이트 확인
        assert session.outgoing_leg is not None
        assert session.outgoing_leg.leg_id == outgoing_leg.leg_id
    
    def test_create_outgoing_invite_no_incoming_leg(self, call_manager):
        """Incoming leg 없이 outgoing INVITE 생성 시도 (에러)"""
        session = CallSession()  # incoming_leg 없음
        
        with pytest.raises(InvalidSIPMessageError) as exc_info:
            call_manager.create_outgoing_invite(session, "sip:pbx@192.168.1.1:5060")
        
        assert "incoming leg" in str(exc_info.value).lower()
    
    def test_create_outgoing_invite_no_sdp(self, call_manager):
        """SDP 없이 outgoing INVITE 생성 시도 (에러)"""
        session, _ = call_manager.handle_incoming_invite(
            from_uri="sip:alice@example.com",
            to_uri="sip:bob@example.com",
            call_id_header="call-no-sdp",
            sdp=SAMPLE_SDP,
        )
        
        # SDP 제거
        session.incoming_leg.sdp_raw = None
        
        with pytest.raises(InvalidSIPMessageError) as exc_info:
            call_manager.create_outgoing_invite(session, "sip:pbx@192.168.1.1:5060")
        
        assert "sdp" in str(exc_info.value).lower()
    
    def test_handle_provisional_response_ringing(self, call_manager):
        """180 Ringing 응답 처리 테스트"""
        # Session 생성
        session, _ = call_manager.handle_incoming_invite(
            from_uri="sip:alice@example.com",
            to_uri="sip:bob@example.com",
            call_id_header="call-ringing",
            sdp=SAMPLE_SDP,
        )
        
        # 180 Ringing 처리
        call_manager.handle_provisional_response(
            session,
            SIPResponseCode.RINGING,
            "Ringing"
        )
        
        # 상태 확인
        assert session.state == CallState.RINGING
    
    def test_handle_provisional_response_session_progress(self, call_manager):
        """183 Session Progress 응답 처리 테스트"""
        session, _ = call_manager.handle_incoming_invite(
            from_uri="sip:alice@example.com",
            to_uri="sip:bob@example.com",
            call_id_header="call-progress",
            sdp=SAMPLE_SDP,
        )
        
        # 183 Session Progress 처리
        call_manager.handle_provisional_response(
            session,
            SIPResponseCode.SESSION_PROGRESS,
            "Session Progress"
        )
        
        # 상태 확인
        assert session.state == CallState.PROCEEDING
    
    def test_handle_invite_timeout(self, call_manager):
        """INVITE 타임아웃 처리 테스트"""
        session, _ = call_manager.handle_incoming_invite(
            from_uri="sip:alice@example.com",
            to_uri="sip:bob@example.com",
            call_id_header="call-timeout",
            sdp=SAMPLE_SDP,
        )
        
        # 타임아웃 처리
        response_code = call_manager.handle_invite_timeout(session, timeout_seconds=30)
        
        # 검증
        assert response_code == SIPResponseCode.REQUEST_TIMEOUT
        assert session.state == CallState.FAILED
        assert session.termination_reason == "timeout_after_30s"
    
    def test_full_b2bua_flow(self, call_manager):
        """전체 B2BUA 흐름 테스트 (incoming → outgoing)"""
        # 1. Incoming INVITE 수신
        session, response = call_manager.handle_incoming_invite(
            from_uri="sip:alice@example.com",
            to_uri="sip:bob@example.com",
            call_id_header="full-flow-call",
            contact="sip:alice@192.168.1.100:5060",
            sdp=SAMPLE_SDP,
        )
        
        assert response == SIPResponseCode.TRYING
        assert session.state == CallState.PROCEEDING
        assert session.incoming_leg is not None
        assert session.outgoing_leg is None
        
        # 2. Outgoing INVITE 생성
        outgoing_leg, sdp = call_manager.create_outgoing_invite(
            session,
            b2bua_contact="sip:pbx@192.168.1.1:5060"
        )
        
        assert session.outgoing_leg is not None
        assert session.outgoing_leg.direction == Direction.OUTGOING
        
        # 3. 180 Ringing 수신 및 전달
        call_manager.handle_provisional_response(session, SIPResponseCode.RINGING, "Ringing")
        assert session.state == CallState.RINGING
        
        # 4. Call-ID 매핑 검증
        incoming_call_id = session.incoming_leg.call_id_header
        outgoing_call_id = session.outgoing_leg.call_id_header
        
        assert incoming_call_id != outgoing_call_id  # 독립적인 Call-ID
        assert "full-flow-call" == incoming_call_id
        assert "outgoing-" in outgoing_call_id


class TestCallAnswer:
    """통화 응답 및 ACK 테스트 (Story 1.6)"""
    
    def test_handle_200_ok_from_outgoing(self, call_manager):
        """Outgoing leg에서 200 OK 수신 테스트"""
        # 세션 생성 및 outgoing leg 추가
        session, _ = call_manager.handle_incoming_invite(
            from_uri="sip:alice@example.com",
            to_uri="sip:bob@example.com",
            call_id_header="call-200ok",
            sdp=SAMPLE_SDP,
        )
        call_manager.create_outgoing_invite(session, "sip:pbx@192.168.1.1:5060")
        
        # Callee의 200 OK SDP
        callee_sdp = """v=0
o=bob 12345 67890 IN IP4 192.168.1.200
s=Call
c=IN IP4 192.168.1.200
t=0 0
m=audio 6000 RTP/AVP 0 8 101
a=rtpmap:0 PCMU/8000
"""
        
        # 200 OK 처리
        modified_sdp = call_manager.handle_200_ok_response(
            session,
            callee_sdp,
            Direction.OUTGOING
        )
        
        # 검증
        assert modified_sdp is not None
        assert session.outgoing_leg.sdp_raw == callee_sdp
    
    def test_handle_200_ok_no_sdp(self, call_manager):
        """SDP 없는 200 OK (에러)"""
        session, _ = call_manager.handle_incoming_invite(
            from_uri="sip:alice@example.com",
            to_uri="sip:bob@example.com",
            call_id_header="call-no-sdp-ok",
            sdp=SAMPLE_SDP,
        )
        call_manager.create_outgoing_invite(session, "sip:pbx@192.168.1.1:5060")
        
        with pytest.raises(InvalidSIPMessageError) as exc_info:
            call_manager.handle_200_ok_response(session, "", Direction.OUTGOING)
        
        assert "sdp" in str(exc_info.value).lower()
    
    def test_handle_200_ok_no_outgoing_leg(self, call_manager):
        """Outgoing leg 없이 200 OK 처리 (에러)"""
        session, _ = call_manager.handle_incoming_invite(
            from_uri="sip:alice@example.com",
            to_uri="sip:bob@example.com",
            call_id_header="call-no-out",
            sdp=SAMPLE_SDP,
        )
        # outgoing leg 생성 안 함
        
        with pytest.raises(InvalidSIPMessageError) as exc_info:
            call_manager.handle_200_ok_response(session, SAMPLE_SDP, Direction.OUTGOING)
        
        assert "outgoing leg" in str(exc_info.value).lower()
    
    def test_handle_ack_from_incoming(self, call_manager):
        """Incoming leg에서 ACK 수신 테스트"""
        # 세션 생성
        session, _ = call_manager.handle_incoming_invite(
            from_uri="sip:alice@example.com",
            to_uri="sip:bob@example.com",
            call_id_header="call-ack",
            sdp=SAMPLE_SDP,
        )
        
        # 초기 상태 확인
        assert session.state == CallState.PROCEEDING
        assert session.answer_time is None
        
        # ACK 처리
        call_manager.handle_ack(session, Direction.INCOMING)
        
        # 검증
        assert session.state == CallState.ESTABLISHED
        assert session.answer_time is not None
        assert session.is_active()
    
    def test_full_call_establishment_flow(self, call_manager):
        """전체 통화 연결 흐름 테스트 (INVITE → 200 OK → ACK)"""
        # 1. Incoming INVITE
        session, _ = call_manager.handle_incoming_invite(
            from_uri="sip:alice@example.com",
            to_uri="sip:bob@example.com",
            call_id_header="full-establishment",
            sdp=SAMPLE_SDP,
        )
        assert session.state == CallState.PROCEEDING
        
        # 2. Outgoing INVITE 생성
        call_manager.create_outgoing_invite(session, "sip:pbx@192.168.1.1:5060")
        assert session.outgoing_leg is not None
        
        # 3. 180 Ringing
        call_manager.handle_provisional_response(session, SIPResponseCode.RINGING, "Ringing")
        assert session.state == CallState.RINGING
        
        # 4. 200 OK from callee
        callee_sdp = """v=0
o=bob 11111 22222 IN IP4 192.168.1.200
s=Call
c=IN IP4 192.168.1.200
t=0 0
m=audio 7000 RTP/AVP 0
a=rtpmap:0 PCMU/8000
"""
        modified_sdp = call_manager.handle_200_ok_response(
            session,
            callee_sdp,
            Direction.OUTGOING
        )
        assert modified_sdp is not None
        assert session.outgoing_leg.sdp_raw == callee_sdp
        
        # 5. ACK from caller
        call_manager.handle_ack(session, Direction.INCOMING)
        assert session.state == CallState.ESTABLISHED
        assert session.answer_time is not None
        
        # 6. 통화 연결 완료 확인
        assert call_manager.get_active_call_count() == 1
        assert session.is_active()
        
        # 7. Caller/Callee URI 확인
        assert session.get_caller_uri() == "sip:alice@example.com"
        assert session.get_callee_uri() == "sip:bob@example.com"


class TestCallTermination:
    """통화 종료 (BYE) 테스트 (Story 1.7)"""
    
    def test_handle_bye_from_incoming(self, call_manager):
        """Incoming leg에서 BYE 수신 테스트"""
        # 통화 연결
        session, _ = call_manager.handle_incoming_invite(
            from_uri="sip:alice@example.com",
            to_uri="sip:bob@example.com",
            call_id_header="call-bye-incoming",
            sdp=SAMPLE_SDP,
        )
        call_manager.handle_ack(session, Direction.INCOMING)
        assert session.state == CallState.ESTABLISHED
        
        # BYE 수신 (caller hangup)
        response_code = call_manager.handle_bye(
            session,
            Direction.INCOMING,
            reason="caller_hangup"
        )
        
        # 검증
        assert response_code == SIPResponseCode.OK
        assert session.state == CallState.TERMINATED
        assert session.termination_reason == "caller_hangup"
        assert session.end_time is not None
    
    def test_handle_bye_from_outgoing(self, call_manager):
        """Outgoing leg에서 BYE 수신 테스트"""
        # 통화 연결
        session, _ = call_manager.handle_incoming_invite(
            from_uri="sip:alice@example.com",
            to_uri="sip:bob@example.com",
            call_id_header="call-bye-outgoing",
            sdp=SAMPLE_SDP,
        )
        call_manager.handle_ack(session, Direction.INCOMING)
        
        # BYE 수신 (callee hangup)
        response_code = call_manager.handle_bye(
            session,
            Direction.OUTGOING,
            reason="callee_hangup"
        )
        
        # 검증
        assert response_code == SIPResponseCode.OK
        assert session.state == CallState.TERMINATED
        assert session.termination_reason == "callee_hangup"
    
    def test_cleanup_terminated_call(self, call_manager):
        """종료된 통화 정리 테스트"""
        # 통화 생성 및 연결
        session, _ = call_manager.handle_incoming_invite(
            from_uri="sip:alice@example.com",
            to_uri="sip:bob@example.com",
            call_id_header="call-cleanup",
            sdp=SAMPLE_SDP,
        )
        call_manager.handle_ack(session, Direction.INCOMING)
        
        # BYE 처리
        call_manager.handle_bye(session, Direction.INCOMING, reason="normal")
        
        # 정리
        cdr_data = call_manager.cleanup_terminated_call(session)
        
        # CDR 데이터 검증
        assert cdr_data is not None
        assert cdr_data["call_id"] == session.call_id
        assert cdr_data["caller_uri"] == "sip:alice@example.com"
        assert cdr_data["callee_uri"] == "sip:bob@example.com"
        assert cdr_data["termination_reason"] == "normal"
        assert cdr_data["state"] == CallState.TERMINATED
        assert cdr_data["duration_seconds"] is not None
        
        # Repository에서 제거 확인
        retrieved = call_manager.get_session(session.call_id)
        assert retrieved is None
    
    def test_full_call_lifecycle(self, call_manager):
        """전체 통화 생명주기 테스트 (INVITE → ACK → BYE → Cleanup)"""
        # 1. Incoming INVITE
        session, _ = call_manager.handle_incoming_invite(
            from_uri="sip:alice@example.com",
            to_uri="sip:bob@example.com",
            call_id_header="full-lifecycle",
            sdp=SAMPLE_SDP,
        )
        assert session.state == CallState.PROCEEDING
        assert call_manager.get_active_call_count() == 1
        
        # 2. Outgoing INVITE
        call_manager.create_outgoing_invite(session, "sip:pbx@192.168.1.1:5060")
        
        # 3. 180 Ringing
        call_manager.handle_provisional_response(session, SIPResponseCode.RINGING, "Ringing")
        assert session.state == CallState.RINGING
        
        # 4. 200 OK
        callee_sdp = """v=0
o=bob 99999 11111 IN IP4 192.168.1.200
s=Call
c=IN IP4 192.168.1.200
t=0 0
m=audio 8000 RTP/AVP 0
a=rtpmap:0 PCMU/8000
"""
        call_manager.handle_200_ok_response(session, callee_sdp, Direction.OUTGOING)
        
        # 5. ACK
        call_manager.handle_ack(session, Direction.INCOMING)
        assert session.state == CallState.ESTABLISHED
        assert session.answer_time is not None
        assert call_manager.get_active_call_count() == 1
        
        # 6. BYE (caller hangup)
        response = call_manager.handle_bye(session, Direction.INCOMING, reason="caller_hangup")
        assert response == SIPResponseCode.OK
        assert session.state == CallState.TERMINATED
        assert session.end_time is not None
        assert not session.is_active()  # 더 이상 활성 통화 아님
        
        # 7. Cleanup
        cdr_data = call_manager.cleanup_terminated_call(session)
        assert cdr_data["duration_seconds"] is not None
        assert cdr_data["duration_seconds"] >= 0
        assert call_manager.get_session(session.call_id) is None
        assert call_manager.get_active_call_count() == 0
    
    def test_bye_without_answer(self, call_manager):
        """응답 전 BYE 테스트 (INVITE 중 취소)"""
        # INVITE만 수신
        session, _ = call_manager.handle_incoming_invite(
            from_uri="sip:alice@example.com",
            to_uri="sip:bob@example.com",
            call_id_header="call-early-bye",
            sdp=SAMPLE_SDP,
        )
        assert session.state == CallState.PROCEEDING
        assert session.answer_time is None
        
        # BYE (early termination)
        call_manager.handle_bye(session, Direction.INCOMING, reason="cancelled")
        
        # 검증
        assert session.state == CallState.TERMINATED
        assert session.get_duration_seconds() is None  # 응답 전이므로 duration 없음
        
        # Cleanup
        cdr_data = call_manager.cleanup_terminated_call(session)
        assert cdr_data["duration_seconds"] is None
        assert cdr_data["termination_reason"] == "cancelled"

