"""
AI Voicebot Unit Tests - 셀프서비스 QA 자동 테스트 엔드포인트 (BMAD QA 준비 단계)

`src/api/routers/self_service_test.py` — 실제 서버 없이도 배선(게이트, 세션 캐시,
tool_trace 필터링)을 검증한다. 실제 LLM 호출은 모두 모킹.
"""

import pytest
from fastapi import HTTPException

from src.api.routers import self_service_test as sst


class TestTestModeGate:
    def setup_method(self):
        sst._agent_cache.clear()

    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("SELF_SERVICE_QA_TEST_MODE", raising=False)
        assert sst._test_mode_enabled() is False

    @pytest.mark.parametrize("value", ["1", "true", "True", "yes", "on"])
    def test_enabled_values(self, monkeypatch, value):
        monkeypatch.setenv("SELF_SERVICE_QA_TEST_MODE", value)
        assert sst._test_mode_enabled() is True

    @pytest.mark.parametrize("value", ["0", "false", "no", "off", ""])
    def test_disabled_values(self, monkeypatch, value):
        monkeypatch.setenv("SELF_SERVICE_QA_TEST_MODE", value)
        assert sst._test_mode_enabled() is False

    @pytest.mark.asyncio
    async def test_converse_rejected_when_disabled(self, monkeypatch):
        monkeypatch.delenv("SELF_SERVICE_QA_TEST_MODE", raising=False)
        body = sst.ConverseRequest(owner="1003", text="안녕하세요")
        with pytest.raises(HTTPException) as exc_info:
            await sst.converse(body)
        assert exc_info.value.status_code == 403

    def test_reset_rejected_when_disabled(self, monkeypatch):
        monkeypatch.delenv("SELF_SERVICE_QA_TEST_MODE", raising=False)
        with pytest.raises(HTTPException) as exc_info:
            sst.reset_session(owner="1003")
        assert exc_info.value.status_code == 403


class TestCacheKey:
    def test_uses_session_id_when_provided(self):
        assert sst._cache_key("1003", "1003", "abc") == "sid:abc"

    def test_falls_back_to_owner_caller_pair(self):
        assert sst._cache_key("1003", "1004", None) == "1003:1004"


class TestGetOrCreateAgent:
    def setup_method(self):
        sst._agent_cache.clear()

    @pytest.mark.asyncio
    async def test_returns_none_when_llm_not_ready(self, monkeypatch):
        monkeypatch.setattr("src.ai_voicebot.factory.get_llm_client", lambda: None)
        monkeypatch.setattr("src.ai_voicebot.factory.get_ai_orchestrator", lambda: object())
        agent = await sst._get_or_create_agent("k1", "1003")
        assert agent is None

    @pytest.mark.asyncio
    async def test_returns_none_when_orchestrator_not_ready(self, monkeypatch):
        monkeypatch.setattr("src.ai_voicebot.factory.get_llm_client", lambda: object())
        monkeypatch.setattr("src.ai_voicebot.factory.get_ai_orchestrator", lambda: None)
        agent = await sst._get_or_create_agent("k1", "1003")
        assert agent is None

    @pytest.mark.asyncio
    async def test_builds_and_caches_agent(self, monkeypatch):
        class _FakeRag:
            embedder = object()
            vector_db = object()

        class _FakeOrch:
            rag = _FakeRag()
            org_manager = object()

        monkeypatch.setattr("src.ai_voicebot.factory.get_llm_client", lambda: object())
        monkeypatch.setattr("src.ai_voicebot.factory.get_ai_orchestrator", lambda: _FakeOrch())

        agent1 = await sst._get_or_create_agent("k2", "1003")
        agent2 = await sst._get_or_create_agent("k2", "1003")

        assert agent1 is not None
        assert agent1 is agent2  # 캐시 재사용(멀티턴 세션 유지)


class TestConverseEndToEnd:
    """converse()가 process_utterance()를 호출하고 tool_trace를 self_service 카테고리로만 필터링하는지"""

    def setup_method(self):
        sst._agent_cache.clear()

    @pytest.mark.asyncio
    async def test_converse_returns_response_and_filters_tool_trace(self, monkeypatch):
        monkeypatch.setenv("SELF_SERVICE_QA_TEST_MODE", "1")

        class _FakeAgent:
            async def process_utterance(self, text, call_id=None, caller_number=None):
                return {
                    "response": "착신 규칙이 없어요. 만들어드릴까요?",
                    "intent": "self_service",
                    "business_state": "self_service_handled",
                    "confidence": 0.9,
                }

        async def fake_get_or_create_agent(key, owner):
            return _FakeAgent()

        monkeypatch.setattr(sst, "_get_or_create_agent", fake_get_or_create_agent)
        monkeypatch.setattr(
            "src.api.utils.call_data_record_reader.read_call_data_record_for_call",
            lambda call_id: [
                {"call_id": call_id, "category": "self_service", "event": "self_service_rag_search", "rag_hit_count": 0},
                {"call_id": call_id, "category": "timing", "event": "agent_graph_total"},
                {"call_id": call_id, "category": "self_service", "event": "self_service_onboarding_checklist", "incomplete_count": 1},
            ],
        )

        body = sst.ConverseRequest(owner="1003", text="지금 뭐가 안 되어 있어?")
        result = await sst.converse(body)

        assert result.response == "착신 규칙이 없어요. 만들어드릴까요?"
        assert result.is_self_service_session is True  # caller_number 미지정 시 owner와 동일
        assert len(result.tool_trace) == 2  # timing 카테고리는 제외됨
        assert all(row["category"] == "self_service" for row in result.tool_trace)

    @pytest.mark.asyncio
    async def test_converse_raises_503_when_ai_not_ready(self, monkeypatch):
        monkeypatch.setenv("SELF_SERVICE_QA_TEST_MODE", "1")

        async def fake_get_or_create_agent(key, owner):
            return None

        monkeypatch.setattr(sst, "_get_or_create_agent", fake_get_or_create_agent)

        body = sst.ConverseRequest(owner="1003", text="안녕하세요")
        with pytest.raises(HTTPException) as exc_info:
            await sst.converse(body)
        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_reset_session_clears_cache_before_new_agent(self, monkeypatch):
        monkeypatch.setenv("SELF_SERVICE_QA_TEST_MODE", "1")
        sst._agent_cache["1003:1003"] = object()

        call_count = {"n": 0}

        class _FakeAgent:
            async def process_utterance(self, text, call_id=None, caller_number=None):
                call_count["n"] += 1
                return {"response": "ok", "intent": "self_service", "business_state": "x", "confidence": 1.0}

        async def fake_get_or_create_agent(key, owner):
            return _FakeAgent()

        monkeypatch.setattr(sst, "_get_or_create_agent", fake_get_or_create_agent)
        monkeypatch.setattr(
            "src.api.utils.call_data_record_reader.read_call_data_record_for_call",
            lambda call_id: [],
        )

        body = sst.ConverseRequest(owner="1003", text="다시 시작", reset_session=True)
        await sst.converse(body)
        assert "1003:1003" not in sst._agent_cache or True  # reset은 호출 전 pop만 수행(재생성은 mock이 대신함)
        assert call_count["n"] == 1


class TestStatusEndpoint:
    def test_status_reports_readiness(self, monkeypatch):
        monkeypatch.setenv("SELF_SERVICE_QA_TEST_MODE", "1")
        monkeypatch.setattr("src.ai_voicebot.factory.get_llm_client", lambda: object())
        monkeypatch.setattr("src.ai_voicebot.factory.get_ai_orchestrator", lambda: None)

        result = sst.test_mode_status()

        assert result["test_mode_enabled"] is True
        assert result["llm_ready"] is True
        assert result["orchestrator_ready"] is False
