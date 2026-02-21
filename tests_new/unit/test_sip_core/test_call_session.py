"""
SIP Core Unit Tests - Call Session Models

통화 세션 및 Leg 모델 테스트
"""

import pytest
from datetime import datetime, timedelta

from src.sip_core.models.call_session import CallSession, Leg
from src.sip_core.models.enums import CallState, Direction


class TestLeg:
    """Leg 모델 단위 테스트"""
    
    def test_create_leg_with_defaults(self):
        """
        Given: 기본 매개변수로 Leg 생성
        When: Leg 인스턴스화
        Then: leg_id, direction 등 기본값 설정됨
        """
        # When
        leg = Leg()
        
        # Then
        assert leg.leg_id is not None
        assert leg.direction == Direction.INCOMING
        assert leg.cseq == 1
        assert leg.created_at is not None
    
    def test_create_leg_with_sip_headers(self):
        """
        Given: SIP 헤더 정보 제공
        When: Leg 생성
        Then: 헤더 정보가 올바르게 저장됨
        """
        # Given
        headers = {
            "call_id_header": "abc123@example.com",
            "from_uri": "sip:alice@example.com",
            "to_uri": "sip:bob@example.com",
            "contact": "sip:alice@192.168.1.10:5060",
            "tag": "tag-12345"
        }
        
        # When
        leg = Leg(**headers)
        
        # Then
        assert leg.call_id_header == "abc123@example.com"
        assert leg.from_uri == "sip:alice@example.com"
        assert leg.to_uri == "sip:bob@example.com"
        assert leg.contact == "sip:alice@192.168.1.10:5060"
        assert leg.tag == "tag-12345"
    
    def test_leg_unique_ids(self):
        """
        Given: 두 개의 Leg 생성
        When: leg_id 비교
        Then: 각 Leg는 고유한 ID를 가짐
        """
        # When
        leg1 = Leg()
        leg2 = Leg()
        
        # Then
        assert leg1.leg_id != leg2.leg_id


class TestCallSession:
    """CallSession 모델 단위 테스트"""
    
    def test_create_call_session_with_defaults(self):
        """
        Given: 기본 매개변수로 CallSession 생성
        When: CallSession 인스턴스화
        Then: 초기 상태가 INITIAL
        """
        # When
        session = CallSession()
        
        # Then
        assert session.call_id is not None
        assert session.state == CallState.INITIAL
        assert session.incoming_leg is None
        assert session.outgoing_leg is None
        assert session.start_time is not None
    
    def test_mark_established(self):
        """
        Given: INITIAL 상태의 CallSession
        When: mark_established() 호출
        Then: 상태가 ESTABLISHED로 변경되고 answer_time 설정됨
        """
        # Given
        session = CallSession()
        assert session.answer_time is None
        
        # When
        session.mark_established()
        
        # Then
        assert session.state == CallState.ESTABLISHED
        assert session.answer_time is not None
    
    def test_mark_terminated(self):
        """
        Given: ESTABLISHED 상태의 CallSession
        When: mark_terminated() 호출
        Then: 상태가 TERMINATED로 변경되고 end_time 및 reason 설정됨
        """
        # Given
        session = CallSession(state=CallState.ESTABLISHED)
        session.answer_time = datetime.utcnow()
        
        # When
        session.mark_terminated(reason="user_hangup")
        
        # Then
        assert session.state == CallState.TERMINATED
        assert session.end_time is not None
        assert session.termination_reason == "user_hangup"
    
    def test_mark_failed(self):
        """
        Given: PROCEEDING 상태의 CallSession
        When: mark_failed() 호출
        Then: 상태가 FAILED로 변경됨
        """
        # Given
        session = CallSession(state=CallState.PROCEEDING)
        
        # When
        session.mark_failed(reason="timeout")
        
        # Then
        assert session.state == CallState.FAILED
        assert session.end_time is not None
        assert session.termination_reason == "timeout"
    
    def test_get_duration_seconds(self):
        """
        Given: 통화가 연결되고 종료된 CallSession
        When: get_duration_seconds() 호출
        Then: 올바른 통화 시간(초) 반환
        """
        # Given
        session = CallSession()
        session.answer_time = datetime.utcnow()
        session.end_time = session.answer_time + timedelta(seconds=120)
        
        # When
        duration = session.get_duration_seconds()
        
        # Then
        assert duration == 120
    
    def test_get_duration_returns_none_when_not_answered(self):
        """
        Given: 응답하지 않은 통화 (answer_time이 None)
        When: get_duration_seconds() 호출
        Then: None 반환
        """
        # Given
        session = CallSession()
        session.end_time = datetime.utcnow()
        
        # When
        duration = session.get_duration_seconds()
        
        # Then
        assert duration is None
    
    def test_is_active_returns_true_for_active_states(self):
        """
        Given: ESTABLISHED 상태의 CallSession
        When: is_active() 호출
        Then: True 반환
        """
        # Given
        session = CallSession(state=CallState.ESTABLISHED)
        
        # When
        is_active = session.is_active()
        
        # Then
        assert is_active is True
    
    def test_is_active_returns_false_for_terminated_state(self):
        """
        Given: TERMINATED 상태의 CallSession
        When: is_active() 호출
        Then: False 반환
        """
        # Given
        session = CallSession(state=CallState.TERMINATED)
        
        # When
        is_active = session.is_active()
        
        # Then
        assert is_active is False
    
    def test_get_caller_uri(self):
        """
        Given: incoming_leg에 from_uri가 설정된 CallSession
        When: get_caller_uri() 호출
        Then: 발신자 URI 반환
        """
        # Given
        incoming_leg = Leg(from_uri="sip:alice@example.com")
        session = CallSession(incoming_leg=incoming_leg)
        
        # When
        caller_uri = session.get_caller_uri()
        
        # Then
        assert caller_uri == "sip:alice@example.com"
    
    def test_get_callee_uri(self):
        """
        Given: incoming_leg에 to_uri가 설정된 CallSession
        When: get_callee_uri() 호출
        Then: 수신자 URI 반환
        """
        # Given
        incoming_leg = Leg(to_uri="sip:bob@example.com")
        session = CallSession(incoming_leg=incoming_leg)
        
        # When
        callee_uri = session.get_callee_uri()
        
        # Then
        assert callee_uri == "sip:bob@example.com"
    
    def test_call_state_transition(self):
        """
        Given: CallSession
        When: INITIAL → PROCEEDING → ESTABLISHED → TERMINATED 순서로 상태 전환
        Then: 각 단계에서 올바른 상태 유지
        """
        # Given
        session = CallSession()
        assert session.state == CallState.INITIAL
        
        # When: PROCEEDING
        session.state = CallState.PROCEEDING
        assert session.is_active() is True
        
        # When: ESTABLISHED
        session.mark_established()
        assert session.state == CallState.ESTABLISHED
        assert session.is_active() is True
        
        # When: TERMINATED
        session.mark_terminated()
        assert session.state == CallState.TERMINATED
        assert session.is_active() is False

