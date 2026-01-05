"""PRACK Handler 테스트"""

import pytest
from src.sip_core.prack_handler import PRACKHandler, ReliableProvisionalResponse
from src.sip_core.models.call_session import CallSession, Leg
from src.sip_core.models.enums import CallState, Direction, SIPMethod, SIPResponseCode
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
        call_id_header="test-call-123",
    )
    
    outgoing_leg = Leg(
        tag="outgoing-tag",
        from_uri="sip:b2bua@pbx.com",
        to_uri="sip:callee@example.com",
        direction=Direction.OUTGOING,
        cseq=1,
        call_id_header="test-call-123",
    )
    
    return CallSession(
        call_id="test-call-123",
        incoming_leg=incoming_leg,
        outgoing_leg=outgoing_leg,
        state=CallState.RINGING,
    )


class TestPRACKHandler:
    """PRACK 핸들러 테스트"""
    
    def test_handler_creation(self):
        """핸들러 생성 테스트"""
        handler = PRACKHandler()
        
        assert handler is not None
        assert len(handler.rseq_tracker) == 0
        assert len(handler.pending_prack) == 0
    
    def test_generate_rseq(self):
        """RSeq 생성 테스트"""
        handler = PRACKHandler()
        call_id = "test-call-123"
        
        # 첫 번째 RSeq
        rseq1 = handler.generate_rseq(call_id)
        assert rseq1 == 1
        
        # 두 번째 RSeq (증가)
        rseq2 = handler.generate_rseq(call_id)
        assert rseq2 == 2
        
        # 세 번째 RSeq
        rseq3 = handler.generate_rseq(call_id)
        assert rseq3 == 3
    
    def test_handle_183_session_progress(self, call_session):
        """183 Session Progress 처리 테스트"""
        handler = PRACKHandler()
        
        sdp = "v=0\r\no=- 1 1 IN IP4 10.0.0.2\r\ns=-\r\nc=IN IP4 10.0.0.2\r\nt=0 0\r\nm=audio 20000 RTP/AVP 0\r\n"
        
        # Outgoing leg (callee)에서 183 수신
        rseq, modified_sdp = handler.handle_183_session_progress(
            call_session=call_session,
            from_direction=Direction.OUTGOING,
            sdp=sdp,
        )
        
        # RSeq 생성 확인
        assert rseq == 1
        
        # Pending PRACK 등록 확인
        assert handler.get_pending_prack_count(call_session.call_id) == 1
    
    def test_handle_prack_request_success(self, call_session):
        """PRACK 요청 성공 테스트"""
        handler = PRACKHandler()
        
        # 183 전송
        rseq, _ = handler.handle_183_session_progress(
            call_session=call_session,
            from_direction=Direction.OUTGOING,
            sdp=None,
        )
        
        # PRACK 수신 (incoming leg = caller)
        rack_header = f"{rseq} {call_session.incoming_leg.cseq} INVITE"
        
        response_code = handler.handle_prack_request(
            call_session=call_session,
            from_direction=Direction.INCOMING,
            rack_header=rack_header,
        )
        
        # 200 OK
        assert response_code == SIPResponseCode.OK
        
        # Pending PRACK 제거 확인
        assert handler.get_pending_prack_count(call_session.call_id) == 0
    
    def test_handle_prack_invalid_rack_header(self, call_session):
        """잘못된 RAck 헤더 테스트"""
        handler = PRACKHandler()
        
        # 183 전송
        handler.handle_183_session_progress(
            call_session=call_session,
            from_direction=Direction.OUTGOING,
            sdp=None,
        )
        
        # 잘못된 RAck 헤더
        rack_header = "invalid"
        
        response_code = handler.handle_prack_request(
            call_session=call_session,
            from_direction=Direction.INCOMING,
            rack_header=rack_header,
        )
        
        # 400 Bad Request
        assert response_code == SIPResponseCode.BAD_REQUEST
    
    def test_handle_prack_rseq_mismatch(self, call_session):
        """RSeq 불일치 테스트"""
        handler = PRACKHandler()
        
        # 183 전송
        rseq, _ = handler.handle_183_session_progress(
            call_session=call_session,
            from_direction=Direction.OUTGOING,
            sdp=None,
        )
        
        # 잘못된 RSeq (key에 rseq가 포함되어 있어서 찾을 수 없음)
        rack_header = f"{rseq + 1} {call_session.incoming_leg.cseq} INVITE"
        
        response_code = handler.handle_prack_request(
            call_session=call_session,
            from_direction=Direction.INCOMING,
            rack_header=rack_header,
        )
        
        # 481 Call/Transaction Does Not Exist (key를 찾을 수 없음)
        assert response_code == SIPResponseCode.CALL_DOES_NOT_EXIST
    
    def test_handle_prack_without_pending(self, call_session):
        """Pending 없이 PRACK 수신 테스트"""
        handler = PRACKHandler()
        
        # 183 없이 PRACK 수신
        rack_header = "1 1 INVITE"
        
        response_code = handler.handle_prack_request(
            call_session=call_session,
            from_direction=Direction.INCOMING,
            rack_header=rack_header,
        )
        
        # 481 Call/Transaction Does Not Exist
        assert response_code == SIPResponseCode.CALL_DOES_NOT_EXIST
    
    def test_check_supported_100rel(self):
        """100rel 지원 확인 테스트"""
        handler = PRACKHandler()
        
        # 100rel 포함
        assert handler.check_supported_100rel("100rel") is True
        assert handler.check_supported_100rel("100rel, timer") is True
        assert handler.check_supported_100rel("timer, 100rel") is True
        
        # 100rel 없음
        assert handler.check_supported_100rel("timer") is False
        assert handler.check_supported_100rel("") is False
        assert handler.check_supported_100rel(None) is False
    
    def test_cleanup_call(self, call_session):
        """호 종료 시 정리 테스트"""
        handler = PRACKHandler()
        
        # 183 전송 (여러 번)
        handler.handle_183_session_progress(
            call_session=call_session,
            from_direction=Direction.OUTGOING,
            sdp=None,
        )
        handler.handle_183_session_progress(
            call_session=call_session,
            from_direction=Direction.OUTGOING,
            sdp=None,
        )
        
        # Pending PRACK 2개
        assert handler.get_pending_prack_count(call_session.call_id) == 2
        
        # 정리
        handler.cleanup_call(call_session.call_id)
        
        # 모두 제거
        assert handler.get_pending_prack_count(call_session.call_id) == 0
        assert call_session.call_id not in handler.rseq_tracker
    
    def test_multiple_183_responses(self, call_session):
        """여러 183 응답 테스트"""
        handler = PRACKHandler()
        
        # 첫 번째 183
        rseq1, _ = handler.handle_183_session_progress(
            call_session=call_session,
            from_direction=Direction.OUTGOING,
            sdp=None,
        )
        
        # 두 번째 183
        rseq2, _ = handler.handle_183_session_progress(
            call_session=call_session,
            from_direction=Direction.OUTGOING,
            sdp=None,
        )
        
        # RSeq 증가 확인
        assert rseq2 == rseq1 + 1
        
        # Pending PRACK 2개
        assert handler.get_pending_prack_count(call_session.call_id) == 2
    
    def test_early_media_sdp(self, call_session):
        """Early media SDP 테스트"""
        handler = PRACKHandler()
        
        early_media_sdp = "v=0\r\no=- 1 1 IN IP4 10.0.0.2\r\ns=-\r\nc=IN IP4 10.0.0.2\r\nt=0 0\r\nm=audio 20000 RTP/AVP 0\r\na=sendonly\r\n"
        
        rseq, modified_sdp = handler.handle_183_session_progress(
            call_session=call_session,
            from_direction=Direction.OUTGOING,
            sdp=early_media_sdp,
        )
        
        # SDP 반환 확인
        assert modified_sdp is not None
        assert modified_sdp == early_media_sdp  # 현재는 그대로 반환


class TestReliableProvisionalResponse:
    """ReliableProvisionalResponse 데이터 클래스 테스트"""
    
    def test_response_creation(self, call_session):
        """응답 객체 생성 테스트"""
        response = ReliableProvisionalResponse(
            call_id=call_session.call_id,
            leg=call_session.outgoing_leg,
            response_code=183,
            rseq=1,
            cseq=1,
            cseq_method="INVITE",
        )
        
        assert response.call_id == call_session.call_id
        assert response.response_code == 183
        assert response.rseq == 1
        assert response.needs_prack() is True
    
    def test_response_with_sdp(self, call_session):
        """SDP 포함 응답 테스트"""
        sdp = "v=0\r\no=- 1 1 IN IP4 10.0.0.2\r\ns=-\r\n"
        
        response = ReliableProvisionalResponse(
            call_id=call_session.call_id,
            leg=call_session.outgoing_leg,
            response_code=183,
            rseq=1,
            cseq=1,
            cseq_method="INVITE",
            sdp=sdp,
        )
        
        assert response.sdp == sdp

