"""UPDATE Handler 테스트"""

import pytest
from src.sip_core.update_handler import UPDATEHandler, UpdateRequest
from src.sip_core.models.call_session import CallSession, Leg
from src.sip_core.models.enums import CallState, Direction, SIPResponseCode, HoldState
from src.common.logger import setup_logging


@pytest.fixture(scope="module", autouse=True)
def setup_test_logging():
    """테스트용 로깅 설정"""
    setup_logging(level="DEBUG", format_type="text")


@pytest.fixture
def call_session():
    """테스트용 Call Session"""
    incoming_leg = Leg(
        tag="incoming-tag",
        from_uri="sip:caller@example.com",
        to_uri="sip:callee@example.com",
        direction=Direction.INCOMING,
        cseq=1,
    )
    
    outgoing_leg = Leg(
        tag="outgoing-tag",
        from_uri="sip:b2bua@pbx.com",
        to_uri="sip:callee@example.com",
        direction=Direction.OUTGOING,
        cseq=1,
    )
    
    return CallSession(
        call_id="test-call-123",
        incoming_leg=incoming_leg,
        outgoing_leg=outgoing_leg,
        state=CallState.ESTABLISHED,
    )


@pytest.fixture
def hold_sdp():
    """Hold SDP (sendonly)"""
    return """v=0
o=- 1 1 IN IP4 10.0.0.1
s=-
c=IN IP4 10.0.0.1
t=0 0
m=audio 20000 RTP/AVP 0
a=sendonly
"""


@pytest.fixture
def hold_sdp_zero_ip():
    """Hold SDP (0.0.0.0)"""
    return """v=0
o=- 1 1 IN IP4 10.0.0.1
s=-
c=IN IP4 0.0.0.0
t=0 0
m=audio 20000 RTP/AVP 0
a=rtpmap:0 PCMU/8000
"""


@pytest.fixture
def resume_sdp():
    """Resume SDP (sendrecv)"""
    return """v=0
o=- 1 1 IN IP4 10.0.0.1
s=-
c=IN IP4 10.0.0.1
t=0 0
m=audio 20000 RTP/AVP 0
a=sendrecv
"""


class TestUpdateRequest:
    """UpdateRequest 데이터 클래스 테스트"""
    
    def test_hold_detection_sendonly(self, hold_sdp):
        """Hold 감지 (a=sendonly)"""
        req = UpdateRequest(
            call_id="test-call",
            from_direction=Direction.INCOMING,
            sdp=hold_sdp,
        )
        
        assert req.is_hold is True
        assert req.is_resume is False
    
    def test_hold_detection_zero_ip(self, hold_sdp_zero_ip):
        """Hold 감지 (c=IN IP4 0.0.0.0)"""
        req = UpdateRequest(
            call_id="test-call",
            from_direction=Direction.INCOMING,
            sdp=hold_sdp_zero_ip,
        )
        
        assert req.is_hold is True
        assert req.is_resume is False
    
    def test_resume_detection(self, resume_sdp):
        """Resume 감지 (a=sendrecv)"""
        req = UpdateRequest(
            call_id="test-call",
            from_direction=Direction.INCOMING,
            sdp=resume_sdp,
        )
        
        assert req.is_hold is False
        assert req.is_resume is True
    
    def test_no_sdp(self):
        """SDP 없는 경우"""
        req = UpdateRequest(
            call_id="test-call",
            from_direction=Direction.INCOMING,
        )
        
        assert req.is_hold is False
        assert req.is_resume is False


class TestUPDATEHandler:
    """UPDATE 핸들러 테스트"""
    
    def test_handler_creation(self):
        """핸들러 생성 테스트"""
        handler = UPDATEHandler()
        
        assert handler is not None
        assert len(handler.hold_states) == 0
        assert len(handler.pending_updates) == 0
    
    def test_handle_update_hold_by_caller(self, call_session, hold_sdp):
        """Caller가 Hold 요청"""
        handler = UPDATEHandler()
        
        response_code, modified_sdp = handler.handle_update_request(
            call_session=call_session,
            from_direction=Direction.INCOMING,
            sdp=hold_sdp,
        )
        
        # 200 OK
        assert response_code == SIPResponseCode.OK
        
        # Hold 상태 확인
        assert handler.get_hold_state(call_session.call_id) == HoldState.HELD_BY_CALLER
        assert handler.is_on_hold(call_session.call_id) is True
    
    def test_handle_update_hold_by_callee(self, call_session, hold_sdp):
        """Callee가 Hold 요청"""
        handler = UPDATEHandler()
        
        response_code, modified_sdp = handler.handle_update_request(
            call_session=call_session,
            from_direction=Direction.OUTGOING,
            sdp=hold_sdp,
        )
        
        # 200 OK
        assert response_code == SIPResponseCode.OK
        
        # Hold 상태 확인
        assert handler.get_hold_state(call_session.call_id) == HoldState.HELD_BY_CALLEE
        assert handler.is_on_hold(call_session.call_id) is True
    
    def test_handle_update_hold_by_both(self, call_session, hold_sdp):
        """양쪽 모두 Hold"""
        handler = UPDATEHandler()
        
        # Caller Hold
        handler.handle_update_request(
            call_session=call_session,
            from_direction=Direction.INCOMING,
            sdp=hold_sdp,
        )
        
        # Callee Hold
        handler.handle_update_request(
            call_session=call_session,
            from_direction=Direction.OUTGOING,
            sdp=hold_sdp,
        )
        
        # Hold 상태 확인
        assert handler.get_hold_state(call_session.call_id) == HoldState.HELD_BY_BOTH
    
    def test_handle_update_resume_by_caller(self, call_session, hold_sdp, resume_sdp):
        """Caller가 Resume 요청"""
        handler = UPDATEHandler()
        
        # Hold
        handler.handle_update_request(
            call_session=call_session,
            from_direction=Direction.INCOMING,
            sdp=hold_sdp,
        )
        
        # Resume
        handler.handle_update_request(
            call_session=call_session,
            from_direction=Direction.INCOMING,
            sdp=resume_sdp,
        )
        
        # Hold 상태 확인
        assert handler.get_hold_state(call_session.call_id) == HoldState.ACTIVE
        assert handler.is_on_hold(call_session.call_id) is False
    
    def test_handle_update_resume_from_both_hold(self, call_session, hold_sdp, resume_sdp):
        """양쪽 Hold 상태에서 한쪽 Resume"""
        handler = UPDATEHandler()
        
        # Caller Hold
        handler.handle_update_request(
            call_session=call_session,
            from_direction=Direction.INCOMING,
            sdp=hold_sdp,
        )
        
        # Callee Hold
        handler.handle_update_request(
            call_session=call_session,
            from_direction=Direction.OUTGOING,
            sdp=hold_sdp,
        )
        
        assert handler.get_hold_state(call_session.call_id) == HoldState.HELD_BY_BOTH
        
        # Caller Resume
        handler.handle_update_request(
            call_session=call_session,
            from_direction=Direction.INCOMING,
            sdp=resume_sdp,
        )
        
        # Callee만 Hold
        assert handler.get_hold_state(call_session.call_id) == HoldState.HELD_BY_CALLEE
        assert handler.is_on_hold(call_session.call_id) is True
    
    def test_handle_update_response_success(self, call_session, hold_sdp):
        """UPDATE 응답 성공 처리"""
        handler = UPDATEHandler()
        
        # UPDATE 요청
        handler.handle_update_request(
            call_session=call_session,
            from_direction=Direction.INCOMING,
            sdp=hold_sdp,
        )
        
        # 200 OK 응답
        modified_sdp = handler.handle_update_response(
            call_session=call_session,
            from_direction=Direction.OUTGOING,  # 응답은 반대편에서
            response_code=200,
            sdp=None,
        )
        
        # Hold 상태 유지
        assert handler.get_hold_state(call_session.call_id) == HoldState.HELD_BY_CALLER
    
    def test_handle_update_response_failure(self, call_session, hold_sdp):
        """UPDATE 응답 실패 처리"""
        handler = UPDATEHandler()
        
        # UPDATE 요청
        handler.handle_update_request(
            call_session=call_session,
            from_direction=Direction.INCOMING,
            sdp=hold_sdp,
        )
        
        # 488 Not Acceptable Here
        modified_sdp = handler.handle_update_response(
            call_session=call_session,
            from_direction=Direction.OUTGOING,
            response_code=488,
            sdp=None,
        )
        
        # Hold 상태는 그대로 (롤백 로직 개선 필요)
        assert handler.get_hold_state(call_session.call_id) == HoldState.HELD_BY_CALLER
    
    def test_cleanup_call(self, call_session, hold_sdp):
        """호 종료 시 정리"""
        handler = UPDATEHandler()
        
        # UPDATE 요청
        handler.handle_update_request(
            call_session=call_session,
            from_direction=Direction.INCOMING,
            sdp=hold_sdp,
        )
        
        assert handler.get_hold_state(call_session.call_id) == HoldState.HELD_BY_CALLER
        
        # 정리
        handler.cleanup_call(call_session.call_id)
        
        # 모두 제거
        assert handler.get_hold_state(call_session.call_id) == HoldState.ACTIVE
        assert len(handler.pending_updates) == 0
    
    def test_update_without_sdp(self, call_session):
        """SDP 없는 UPDATE (일반 SDP 재협상)"""
        handler = UPDATEHandler()
        
        response_code, modified_sdp = handler.handle_update_request(
            call_session=call_session,
            from_direction=Direction.INCOMING,
            sdp=None,
        )
        
        # 200 OK
        assert response_code == SIPResponseCode.OK
        
        # Hold 상태 변화 없음
        assert handler.get_hold_state(call_session.call_id) == HoldState.ACTIVE


class TestHoldStateTransitions:
    """Hold 상태 전환 테스트"""
    
    def test_active_to_held_by_caller(self):
        """ACTIVE → HELD_BY_CALLER"""
        handler = UPDATEHandler()
        handler._update_hold_state("call-1", Direction.INCOMING, is_hold=True)
        
        assert handler.get_hold_state("call-1") == HoldState.HELD_BY_CALLER
    
    def test_active_to_held_by_callee(self):
        """ACTIVE → HELD_BY_CALLEE"""
        handler = UPDATEHandler()
        handler._update_hold_state("call-1", Direction.OUTGOING, is_hold=True)
        
        assert handler.get_hold_state("call-1") == HoldState.HELD_BY_CALLEE
    
    def test_held_by_caller_to_active(self):
        """HELD_BY_CALLER → ACTIVE (Resume)"""
        handler = UPDATEHandler()
        handler._update_hold_state("call-1", Direction.INCOMING, is_hold=True)
        handler._update_hold_state("call-1", Direction.INCOMING, is_hold=False)
        
        assert handler.get_hold_state("call-1") == HoldState.ACTIVE
    
    def test_held_by_both_to_held_by_callee(self):
        """HELD_BY_BOTH → HELD_BY_CALLEE (Caller Resume)"""
        handler = UPDATEHandler()
        handler._update_hold_state("call-1", Direction.INCOMING, is_hold=True)
        handler._update_hold_state("call-1", Direction.OUTGOING, is_hold=True)
        
        assert handler.get_hold_state("call-1") == HoldState.HELD_BY_BOTH
        
        handler._update_hold_state("call-1", Direction.INCOMING, is_hold=False)
        
        assert handler.get_hold_state("call-1") == HoldState.HELD_BY_CALLEE
    
    def test_held_by_both_to_active(self):
        """HELD_BY_BOTH → ACTIVE (양쪽 모두 Resume)"""
        handler = UPDATEHandler()
        handler._update_hold_state("call-1", Direction.INCOMING, is_hold=True)
        handler._update_hold_state("call-1", Direction.OUTGOING, is_hold=True)
        
        handler._update_hold_state("call-1", Direction.INCOMING, is_hold=False)
        handler._update_hold_state("call-1", Direction.OUTGOING, is_hold=False)
        
        assert handler.get_hold_state("call-1") == HoldState.ACTIVE

