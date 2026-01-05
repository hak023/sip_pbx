"""CANCEL Handler 테스트"""

import pytest
from src.sip_core.cancel_handler import CANCELHandler, CancelRequest
from src.sip_core.models.call_session import CallSession, Leg
from src.sip_core.models.enums import CallState, Direction, SIPResponseCode
from src.common.logger import setup_logging


@pytest.fixture(scope="module", autouse=True)
def setup_test_logging():
    """테스트용 로깅 설정"""
    setup_logging(level="DEBUG", format_type="text")


@pytest.fixture
def call_session_proceeding():
    """테스트용 Call Session (PROCEEDING 상태)"""
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
        state=CallState.PROCEEDING,
    )


@pytest.fixture
def call_session_ringing():
    """테스트용 Call Session (RINGING 상태)"""
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
        call_id="test-call-456",
        incoming_leg=incoming_leg,
        outgoing_leg=outgoing_leg,
        state=CallState.RINGING,
    )


@pytest.fixture
def call_session_established():
    """테스트용 Call Session (ESTABLISHED 상태)"""
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
        call_id="test-call-789",
        incoming_leg=incoming_leg,
        outgoing_leg=outgoing_leg,
        state=CallState.ESTABLISHED,
    )


class TestCancelRequest:
    """CancelRequest 데이터 클래스 테스트"""
    
    def test_cancel_request_creation(self):
        """CancelRequest 생성 테스트"""
        req = CancelRequest(
            call_id="test-call",
            from_direction=Direction.INCOMING,
            reason="User requested",
        )
        
        assert req.call_id == "test-call"
        assert req.from_direction == Direction.INCOMING
        assert req.reason == "User requested"
        assert req.timestamp is not None
    
    def test_cancel_request_without_reason(self):
        """Reason 없는 CancelRequest"""
        req = CancelRequest(
            call_id="test-call",
            from_direction=Direction.INCOMING,
        )
        
        assert req.reason is None


class TestCANCELHandler:
    """CANCEL 핸들러 테스트"""
    
    def test_handler_creation(self):
        """핸들러 생성 테스트"""
        handler = CANCELHandler()
        
        assert handler is not None
        assert len(handler.pending_cancels) == 0
        assert len(handler.race_conditions) == 0
    
    def test_handle_cancel_in_proceeding_state(self, call_session_proceeding):
        """PROCEEDING 상태에서 CANCEL 수신"""
        handler = CANCELHandler()
        
        response_code = handler.handle_cancel_request(
            call_session=call_session_proceeding,
            from_direction=Direction.INCOMING,
            reason="User cancelled",
        )
        
        # 200 OK
        assert response_code == SIPResponseCode.OK
        
        # Pending CANCEL 등록 확인
        assert handler.is_cancelled(call_session_proceeding.call_id) is True
        assert handler.get_cancel_reason(call_session_proceeding.call_id) == "User cancelled"
    
    def test_handle_cancel_in_ringing_state(self, call_session_ringing):
        """RINGING 상태에서 CANCEL 수신"""
        handler = CANCELHandler()
        
        response_code = handler.handle_cancel_request(
            call_session=call_session_ringing,
            from_direction=Direction.INCOMING,
        )
        
        # 200 OK
        assert response_code == SIPResponseCode.OK
        
        # Pending CANCEL 등록 확인
        assert handler.is_cancelled(call_session_ringing.call_id) is True
    
    def test_handle_cancel_in_established_state_race_condition(self, call_session_established):
        """ESTABLISHED 상태에서 CANCEL 수신 (Race Condition)"""
        handler = CANCELHandler()
        
        response_code = handler.handle_cancel_request(
            call_session=call_session_established,
            from_direction=Direction.INCOMING,
        )
        
        # 200 OK (Race condition으로 처리)
        assert response_code == SIPResponseCode.OK
        
        # Race condition 등록 확인
        assert handler.race_conditions.get(call_session_established.call_id) is True
    
    def test_should_send_487(self, call_session_proceeding):
        """487 전송 여부 확인"""
        handler = CANCELHandler()
        
        # CANCEL 전
        assert handler.should_send_487(call_session_proceeding) is False
        
        # CANCEL 수신
        handler.handle_cancel_request(
            call_session=call_session_proceeding,
            from_direction=Direction.INCOMING,
        )
        
        # 487 전송 필요
        assert handler.should_send_487(call_session_proceeding) is True
    
    def test_should_not_send_487_on_race_condition(self, call_session_established):
        """Race condition 시 487 전송하지 않음"""
        handler = CANCELHandler()
        
        # CANCEL 수신 (Race condition)
        handler.handle_cancel_request(
            call_session=call_session_established,
            from_direction=Direction.INCOMING,
        )
        
        # Race condition이므로 487 전송하지 않음
        assert handler.should_send_487(call_session_established) is False
    
    def test_handle_cancel_propagation(self, call_session_proceeding):
        """Outgoing leg으로 CANCEL 전달 필요 여부"""
        handler = CANCELHandler()
        
        # CANCEL 전
        assert handler.handle_cancel_propagation(call_session_proceeding) is False
        
        # CANCEL 수신
        handler.handle_cancel_request(
            call_session=call_session_proceeding,
            from_direction=Direction.INCOMING,
        )
        
        # CANCEL 전달 필요
        assert handler.handle_cancel_propagation(call_session_proceeding) is True
    
    def test_handle_cancel_response_success(self, call_session_proceeding):
        """CANCEL 응답 성공 처리"""
        handler = CANCELHandler()
        
        # CANCEL 응답 (200 OK)
        handler.handle_cancel_response(
            call_session=call_session_proceeding,
            from_direction=Direction.OUTGOING,
            response_code=200,
        )
        
        # 로그 확인 (실제로는 로그를 캡처하여 확인)
        # 여기서는 예외가 발생하지 않으면 성공
        assert True
    
    def test_handle_487_response(self, call_session_proceeding):
        """487 Request Terminated 응답 처리"""
        handler = CANCELHandler()
        
        # CANCEL 수신
        handler.handle_cancel_request(
            call_session=call_session_proceeding,
            from_direction=Direction.INCOMING,
        )
        
        # 487 응답
        handler.handle_487_response(
            call_session=call_session_proceeding,
            from_direction=Direction.OUTGOING,
        )
        
        # 정리 확인
        assert handler.is_cancelled(call_session_proceeding.call_id) is False
    
    def test_handle_200ok_race_condition(self, call_session_proceeding):
        """200 OK (for INVITE)와 CANCEL의 Race Condition"""
        handler = CANCELHandler()
        
        # CANCEL 수신
        handler.handle_cancel_request(
            call_session=call_session_proceeding,
            from_direction=Direction.INCOMING,
        )
        
        # 200 OK (for INVITE) 도착
        is_race = handler.handle_200ok_race_condition(call_session_proceeding)
        
        # Race condition 감지
        assert is_race is True
        assert handler.race_conditions.get(call_session_proceeding.call_id) is True
    
    def test_cleanup_call(self, call_session_proceeding):
        """호 종료 시 정리"""
        handler = CANCELHandler()
        
        # CANCEL 수신
        handler.handle_cancel_request(
            call_session=call_session_proceeding,
            from_direction=Direction.INCOMING,
            reason="User cancelled",
        )
        
        assert handler.is_cancelled(call_session_proceeding.call_id) is True
        
        # 정리
        handler.cleanup_call(call_session_proceeding.call_id)
        
        # 모두 제거
        assert handler.is_cancelled(call_session_proceeding.call_id) is False
        assert len(handler.pending_cancels) == 0
    
    def test_get_stats(self, call_session_proceeding, call_session_ringing):
        """통계 조회"""
        handler = CANCELHandler()
        
        # 초기 상태
        stats = handler.get_stats()
        assert stats["pending_cancels"] == 0
        assert stats["race_conditions"] == 0
        
        # CANCEL 수신
        handler.handle_cancel_request(
            call_session=call_session_proceeding,
            from_direction=Direction.INCOMING,
        )
        handler.handle_cancel_request(
            call_session=call_session_ringing,
            from_direction=Direction.INCOMING,
        )
        
        stats = handler.get_stats()
        assert stats["pending_cancels"] == 2
        assert stats["race_conditions"] == 0


class TestCANCELScenarios:
    """CANCEL 시나리오 테스트"""
    
    def test_normal_cancel_flow(self, call_session_ringing):
        """정상 CANCEL 흐름"""
        handler = CANCELHandler()
        
        # 1. Caller가 CANCEL 전송
        response_code = handler.handle_cancel_request(
            call_session=call_session_ringing,
            from_direction=Direction.INCOMING,
            reason="User requested",
        )
        
        assert response_code == SIPResponseCode.OK
        
        # 2. 487 전송 필요 확인
        assert handler.should_send_487(call_session_ringing) is True
        
        # 3. Outgoing leg으로 CANCEL 전달
        assert handler.handle_cancel_propagation(call_session_ringing) is True
        
        # 4. Outgoing leg에서 200 OK 응답
        handler.handle_cancel_response(
            call_session=call_session_ringing,
            from_direction=Direction.OUTGOING,
            response_code=200,
        )
        
        # 5. Outgoing leg에서 487 응답
        handler.handle_487_response(
            call_session=call_session_ringing,
            from_direction=Direction.OUTGOING,
        )
        
        # 6. 정리 확인
        assert handler.is_cancelled(call_session_ringing.call_id) is False
    
    def test_cancel_after_200ok_race_condition(self, call_session_proceeding):
        """200 OK 직후 CANCEL 도착 (Race Condition)"""
        handler = CANCELHandler()
        
        # 1. Callee가 200 OK 전송 (call_session이 ESTABLISHED로 변경됨)
        call_session_proceeding.state = CallState.ESTABLISHED
        
        # 2. Caller가 CANCEL 전송 (거의 동시)
        response_code = handler.handle_cancel_request(
            call_session=call_session_proceeding,
            from_direction=Direction.INCOMING,
        )
        
        # 3. Race condition으로 처리 (200 OK 응답)
        assert response_code == SIPResponseCode.OK
        assert handler.race_conditions.get(call_session_proceeding.call_id) is True
        
        # 4. 487을 보내지 않음
        assert handler.should_send_487(call_session_proceeding) is False
        
        # 5. 200 OK를 caller에게 전달 (BYE로 정리)
        # (실제로는 상위 레이어에서 처리)
    
    def test_multiple_cancel_requests(self, call_session_ringing):
        """중복 CANCEL 요청"""
        handler = CANCELHandler()
        
        # 첫 번째 CANCEL
        response_code1 = handler.handle_cancel_request(
            call_session=call_session_ringing,
            from_direction=Direction.INCOMING,
        )
        
        assert response_code1 == SIPResponseCode.OK
        assert handler.is_cancelled(call_session_ringing.call_id) is True
        
        # 두 번째 CANCEL (중복)
        response_code2 = handler.handle_cancel_request(
            call_session=call_session_ringing,
            from_direction=Direction.INCOMING,
        )
        
        # 여전히 200 OK
        assert response_code2 == SIPResponseCode.OK
        
        # Pending CANCEL은 하나만 (덮어쓰기됨)
        stats = handler.get_stats()
        assert stats["pending_cancels"] == 1

