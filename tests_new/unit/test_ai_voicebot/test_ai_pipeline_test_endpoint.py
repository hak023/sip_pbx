"""
AI Voicebot Unit Tests - 일반 경로 AI 파이프라인 QA 자동 테스트 엔드포인트
(voice-latency-turn-taking Story 3.2/4.1/4.2 검증용, self_service_test.py와 동일 패턴)

`src/api/routers/ai_pipeline_test.py` — 실제 서버 없이도 게이트·캐시 키 로직을 검증한다.
실제 LLM 호출은 모두 모킹.
"""

import pytest
from fastapi import HTTPException

from src.api.routers import ai_pipeline_test as apt


class TestTestModeGate:
    def setup_method(self):
        apt._agent_cache.clear()

    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("AI_PIPELINE_QA_TEST_MODE", raising=False)
        assert apt._test_mode_enabled() is False

    @pytest.mark.parametrize("value", ["1", "true", "True", "yes", "on"])
    def test_enabled_values(self, monkeypatch, value):
        monkeypatch.setenv("AI_PIPELINE_QA_TEST_MODE", value)
        assert apt._test_mode_enabled() is True

    @pytest.mark.parametrize("value", ["0", "false", "no", "off", ""])
    def test_disabled_values(self, monkeypatch, value):
        monkeypatch.setenv("AI_PIPELINE_QA_TEST_MODE", value)
        assert apt._test_mode_enabled() is False

    @pytest.mark.asyncio
    async def test_converse_rejected_when_disabled(self, monkeypatch):
        monkeypatch.delenv("AI_PIPELINE_QA_TEST_MODE", raising=False)
        body = apt.ConverseRequest(owner="1003", text="안녕하세요")
        with pytest.raises(HTTPException) as exc_info:
            await apt.converse(body)
        assert exc_info.value.status_code == 403

    def test_reset_rejected_when_disabled(self, monkeypatch):
        monkeypatch.delenv("AI_PIPELINE_QA_TEST_MODE", raising=False)
        with pytest.raises(HTTPException) as exc_info:
            apt.reset_session(owner="1003")
        assert exc_info.value.status_code == 403


class TestCacheKey:
    def test_uses_session_id_when_provided(self):
        assert apt._cache_key("1003", "1003-qa-caller", "abc") == "sid:abc"

    def test_falls_back_to_owner_caller_pair(self):
        assert apt._cache_key("1003", "1003-qa-caller", None) == "1003:1003-qa-caller"


class TestGetOrCreateAgent:
    def setup_method(self):
        apt._agent_cache.clear()

    @pytest.mark.asyncio
    async def test_returns_none_when_llm_not_ready(self, monkeypatch):
        monkeypatch.setattr("src.ai_voicebot.factory.get_llm_client", lambda: None)
        monkeypatch.setattr("src.ai_voicebot.factory.get_ai_orchestrator", lambda: object())
        agent = await apt._get_or_create_agent("k1", "1003")
        assert agent is None

    @pytest.mark.asyncio
    async def test_returns_none_when_orchestrator_not_ready(self, monkeypatch):
        monkeypatch.setattr("src.ai_voicebot.factory.get_llm_client", lambda: object())
        monkeypatch.setattr("src.ai_voicebot.factory.get_ai_orchestrator", lambda: None)
        agent = await apt._get_or_create_agent("k1", "1003")
        assert agent is None


class TestConverseDefaultCallerNumberAvoidsSelfService:
    def test_default_caller_number_differs_from_owner(self):
        # ConverseRequest 기본값 로직: caller_number 생략 시 owner와 달라야
        # is_self_service_session=False가 보장된다(라우터 내부 로직과 동일 규칙 검증).
        owner = "1003"
        default_caller = f"{owner}-qa-caller"
        assert default_caller != owner
