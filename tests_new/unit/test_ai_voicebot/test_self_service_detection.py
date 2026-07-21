"""
AI Voicebot Unit Tests - 셀프서비스 감지(Self-Service Detection)

Story 1.1: 셀프콜/셀프문자 감지 및 세션 플래그
docs/stories/1.1.self-call-detection.story.md §Testing 참고
"""

import time

import pytest

from src.ai_voicebot.self_service.detection import (
    is_self_service_session,
    self_service_enabled,
)


class TestIsSelfServiceSession:
    """is_self_service_session() 단위 테스트 — 순수 함수, 외부 의존성 없음"""

    def test_same_caller_and_owner_returns_true(self):
        """Given: caller_number == owner (정규화 후 동일) / Then: True"""
        assert is_self_service_session("1004", "1004") is True

    def test_different_caller_and_owner_returns_false(self):
        """Given: caller_number != owner / Then: False"""
        assert is_self_service_session("1004", "1003") is False

    def test_sip_uri_form_normalizes_to_same_value(self):
        """Given: caller_number가 sip:1004@host, owner가 1004 / Then: 정규화 후 True"""
        assert is_self_service_session("sip:1004@10.0.0.1", "1004") is True

    def test_empty_caller_number_returns_false(self):
        """Given: caller_number 빈 문자열 / Then: False"""
        assert is_self_service_session("", "1004") is False

    def test_empty_owner_returns_false(self):
        """Given: owner 빈 문자열 / Then: False"""
        assert is_self_service_session("1004", "") is False

    def test_both_empty_returns_false(self):
        """Given: 둘 다 빈 문자열 / Then: False"""
        assert is_self_service_session("", "") is False

    def test_uri_param_suffix_normalizes_correctly(self):
        """Given: caller_number에 ; 파라미터 포함 / Then: 정규화 후 비교 정상 동작"""
        assert is_self_service_session("1004;user=phone", "1004") is True
        assert is_self_service_session("1004;user=phone", "1003") is False

    def test_performance_100_calls_within_50ms(self):
        """IV3: 100회 반복 호출이 50ms 이내"""
        start = time.perf_counter()
        for _ in range(100):
            is_self_service_session("sip:1004@10.0.0.1;user=phone", "1004")
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert elapsed_ms < 50, f"100회 반복 호출이 {elapsed_ms:.2f}ms 소요 (기대: <50ms)"

    def test_killswitch_disabled_returns_false_even_when_matching(self, monkeypatch):
        """SELF_SERVICE_ENABLED=0 이면 다른 조건이 모두 참이어도 False 반환"""
        monkeypatch.setenv("SELF_SERVICE_ENABLED", "0")
        assert is_self_service_session("1004", "1004") is False

    def test_killswitch_enabled_by_default(self, monkeypatch):
        """SELF_SERVICE_ENABLED 미설정 시 기본값은 활성(on)"""
        monkeypatch.delenv("SELF_SERVICE_ENABLED", raising=False)
        assert self_service_enabled() is True
        assert is_self_service_session("1004", "1004") is True


class TestSelfServiceEnabled:
    """self_service_enabled() 킬스위치 함수 단위 테스트"""

    @pytest.mark.parametrize("value", ["0", "false", "False", "no", "off", "OFF"])
    def test_disabled_values(self, monkeypatch, value):
        monkeypatch.setenv("SELF_SERVICE_ENABLED", value)
        assert self_service_enabled() is False

    @pytest.mark.parametrize("value", ["1", "true", "yes", "on"])
    def test_enabled_values(self, monkeypatch, value):
        monkeypatch.setenv("SELF_SERVICE_ENABLED", value)
        assert self_service_enabled() is True
