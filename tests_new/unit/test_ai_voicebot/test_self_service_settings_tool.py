"""
AI Voicebot Unit Tests - 셀프서비스 설정 조회 Tool + Tool-calling 루프 (Story 1.6)

Story 1.6: 설정 조회 Tool (읽기 전용, 전체 도메인)
docs/stories/1.6.settings-query-tool.story.md §Testing 참고
"""

import json

import pytest

from src.ai_voicebot.self_service.tools import (
    SELF_SERVICE_TOOLS,
    _get_self_service_settings,
    update_self_service_setting_tool,
)
from src.ai_voicebot.langgraph.nodes.self_service_agent import (
    _FALLBACK_RETRY_EXHAUSTED,
    _execute_self_service_tool,
    _run_self_service_tool_loop,
    _try_bind_self_service_tools,
    _try_build_self_service_gemini_fc,
    self_service_agent_node,
)


class TestGetSelfServiceSettingsTool:
    """get_self_service_settings Tool 단위 테스트 (AC1, AC2)"""

    @pytest.mark.asyncio
    async def test_registered_domain_returns_catalog_value(self, monkeypatch):
        async def fake_get_domain_value(domain, owner):
            return {"owner": owner, "name": "이탈리안 비스트로"}

        monkeypatch.setattr(
            "src.ai_voicebot.self_service.tools.settings_catalog.get_domain_value",
            fake_get_domain_value,
        )
        result = json.loads(await _get_self_service_settings("1003", "persona"))
        assert result["name"] == "이탈리안 비스트로"

    @pytest.mark.asyncio
    async def test_unregistered_domain_returns_friendly_message(self, monkeypatch):
        async def fake_get_domain_value(domain, owner):
            return {"error": f"unregistered_domain: {domain}"}

        monkeypatch.setattr(
            "src.ai_voicebot.self_service.tools.settings_catalog.get_domain_value",
            fake_get_domain_value,
        )
        result = json.loads(await _get_self_service_settings("1003", "unknown-domain"))
        assert "확인해드릴" in result["error"]
        assert "available_domains" in result

    @pytest.mark.asyncio
    async def test_other_errors_pass_through_unmodified(self, monkeypatch):
        """unregistered_domain이 아닌 다른 에러(예: persona_service_unavailable)는 그대로 반환"""

        async def fake_get_domain_value(domain, owner):
            return {"error": "persona_service_unavailable"}

        monkeypatch.setattr(
            "src.ai_voicebot.self_service.tools.settings_catalog.get_domain_value",
            fake_get_domain_value,
        )
        result = json.loads(await _get_self_service_settings("1003", "persona"))
        assert result == {"error": "persona_service_unavailable"}

    @pytest.mark.asyncio
    async def test_get_fn_exception_is_absorbed(self, monkeypatch):
        async def fake_get_domain_value(domain, owner):
            raise RuntimeError("boom")

        monkeypatch.setattr(
            "src.ai_voicebot.self_service.tools.settings_catalog.get_domain_value",
            fake_get_domain_value,
        )
        result = json.loads(await _get_self_service_settings("1003", "persona"))
        assert "error" in result


class TestDataConsistencyContract:
    """Task 3: Tool이 settings_catalog.get_domain_value() 외 별도 조회 경로를 쓰지 않음(IV1, AC3)"""

    @pytest.mark.asyncio
    async def test_tool_result_matches_catalog_value_exactly(self, monkeypatch):
        async def fake_get_domain_value(domain, owner):
            return {"owner": owner, "rules": [{"id": "r1"}], "schedules": [], "announcements": []}

        monkeypatch.setattr(
            "src.ai_voicebot.self_service.tools.settings_catalog.get_domain_value",
            fake_get_domain_value,
        )
        expected = await fake_get_domain_value("call-control", "1003")
        tool_result = json.loads(await _get_self_service_settings("1003", "call-control"))
        assert tool_result == expected


class TestSelfServiceToolsRegistry:
    def test_registers_all_tools(self):
        # Story 1.5(온보딩)/1.6(설정 조회)/1.7(통계 조회)/1.8(자동설정 쓰기)/
        # 1.13(통화 이력 NLQ 3개) — 도구가 늘어날 때마다 갱신
        assert len(SELF_SERVICE_TOOLS) == 9

    def test_update_setting_tool_description_lists_real_writable_field_names(self):
        """2026-07-15 QA 자동 테스트에서 발견된 필드명 불일치(LLM이 필드명을 추측해서 호출)
        회귀 방지 — 도구 설명에 실제 카탈로그 writable 필드명이 정확히 나열되어야 한다."""
        desc = update_self_service_setting_tool.description
        assert "message_ai_reply_enabled" in desc
        assert "escalation_mode" in desc
        assert "{writable_fields_hint}" not in desc


class TestTryBindSelfServiceTools:
    def test_no_chat_model_attribute_returns_none(self):
        class _FakeLLM:
            pass

        assert _try_bind_self_service_tools(_FakeLLM(), "call-1", "9001") is None

    def test_bind_tools_success_returns_bound_llm(self, monkeypatch):
        monkeypatch.setattr(
            "src.ai_voicebot.self_service.dynamic_api_tool.build_dynamic_tools_for_owner",
            lambda owner: [],
        )

        class _FakeRawLLM:
            def bind_tools(self, tools):
                return "BOUND"

        class _FakeLLM:
            _chat_model = _FakeRawLLM()

        assert _try_bind_self_service_tools(_FakeLLM(), "call-1", "9001") == "BOUND"

    def test_bind_tools_exception_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            "src.ai_voicebot.self_service.dynamic_api_tool.build_dynamic_tools_for_owner",
            lambda owner: [],
        )

        class _FakeRawLLM:
            def bind_tools(self, tools):
                raise RuntimeError("no fc support")

        class _FakeLLM:
            _chat_model = _FakeRawLLM()

        assert _try_bind_self_service_tools(_FakeLLM(), "call-1", "9001") is None


class TestTryBuildSelfServiceGeminiFc:
    """실제 LLMClient(google-genai 기반, Story 6.1/6.2)를 위한 Gemini 네이티브 FC 폴백 생성 검증
    (2026-07-15 QA 자동 테스트에서 발견된 bind_tools 미동작 버그의 실제 수정 경로)."""

    def test_builds_model_with_tool_from_llm_client(self, monkeypatch):
        monkeypatch.setattr(
            "src.ai_voicebot.self_service.dynamic_api_tool.build_dynamic_tools_for_owner",
            lambda owner: [],
        )

        class _FakeClient:
            pass

        class _FakeLLMClient:
            _client = _FakeClient()
            model_name = "gemini-2.5-flash"

        result = _try_build_self_service_gemini_fc(_FakeLLMClient(), "call-1", "9001")
        assert result is not None
        assert result.client is _FakeLLMClient._client
        assert result.model_name == "gemini-2.5-flash"
        assert len(result.tool.function_declarations) == len(SELF_SERVICE_TOOLS)

    def test_missing_model_attribute_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            "src.ai_voicebot.self_service.dynamic_api_tool.build_dynamic_tools_for_owner",
            lambda owner: [],
        )

        class _FakeLLMClient:
            pass

        assert _try_build_self_service_gemini_fc(_FakeLLMClient(), "call-1", "9001") is None


class TestExecuteSelfServiceTool:
    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self, monkeypatch):
        monkeypatch.setattr(
            "src.ai_voicebot.self_service.dynamic_api_tool.build_dynamic_tools_for_owner",
            lambda owner: [],
        )
        result = json.loads(await _execute_self_service_tool("no_such_tool", {}, "1003"))
        assert "error" in result

    @pytest.mark.asyncio
    async def test_known_tool_executes(self, monkeypatch):
        monkeypatch.setattr(
            "src.ai_voicebot.self_service.dynamic_api_tool.build_dynamic_tools_for_owner",
            lambda owner: [],
        )

        async def fake_checklist(owner):
            return []

        monkeypatch.setattr(
            "src.ai_voicebot.self_service.tools._get_onboarding_checklist_impl",
            fake_checklist,
        )
        tool_name = getattr(SELF_SERVICE_TOOLS[0], "name", None) or getattr(SELF_SERVICE_TOOLS[0], "__name__", "")
        result = await _execute_self_service_tool(tool_name, {"owner": "1003"}, "1003")
        parsed = json.loads(result)
        assert "incomplete_count" in parsed


class TestRunSelfServiceToolLoop:
    @pytest.mark.asyncio
    async def test_loop_executes_tool_then_returns_final_text(self, monkeypatch):
        from langchain_core.messages import AIMessage

        tool_name = getattr(SELF_SERVICE_TOOLS[1], "name", None) or getattr(SELF_SERVICE_TOOLS[1], "__name__", "")
        call_sequence = []

        class _FakeLLMWithTools:
            async def ainvoke(self, messages):
                if not call_sequence:
                    call_sequence.append(1)
                    return AIMessage(
                        content="",
                        tool_calls=[{"name": tool_name, "args": {"domain": "persona"}, "id": "call_1"}],
                    )
                return AIMessage(content="현재 페르소나는 이렇습니다.")

        async def fake_execute(tool_name_arg, args, owner_arg=None):
            return json.dumps({"name": "이탈리안 비스트로"}, ensure_ascii=False)

        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent._execute_self_service_tool",
            fake_execute,
        )

        response, _ = await _run_self_service_tool_loop(
            "system prompt", "설정 알려줘", "1003", "call-x", llm_with_tools=_FakeLLMWithTools(),
        )
        assert response == "현재 페르소나는 이렇습니다."

    @pytest.mark.asyncio
    async def test_owner_is_force_overridden_regardless_of_llm_supplied_value(self, monkeypatch):
        """보안: LLM이 tool_call args에 다른 owner를 채워 보내도 세션 owner로 강제 치환된다
        (프롬프트 인젝션·환각으로 인한 테넌트 경계 침범 방지, Story 1.8 AC 보안 요구사항)."""
        from langchain_core.messages import AIMessage

        tool_name = getattr(SELF_SERVICE_TOOLS[1], "name", None) or getattr(SELF_SERVICE_TOOLS[1], "__name__", "")
        call_sequence = []

        class _FakeLLMWithTools:
            async def ainvoke(self, messages):
                if not call_sequence:
                    call_sequence.append(1)
                    return AIMessage(
                        content="",
                        tool_calls=[{
                            "name": tool_name,
                            "args": {"domain": "persona", "owner": "attacker-owned-tenant"},
                            "id": "call_1",
                        }],
                    )
                return AIMessage(content="완료했습니다.")

        captured_args = {}

        async def fake_execute(tool_name_arg, args, owner_arg=None):
            captured_args.update(args)
            return json.dumps({"ok": True}, ensure_ascii=False)

        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent._execute_self_service_tool",
            fake_execute,
        )

        await _run_self_service_tool_loop(
            "system prompt", "설정 알려줘", "1003", "call-x", llm_with_tools=_FakeLLMWithTools(),
        )

        assert captured_args["owner"] == "1003"
        assert captured_args["owner"] != "attacker-owned-tenant"

    @pytest.mark.asyncio
    async def test_loop_returns_empty_when_max_rounds_exceeded(self, monkeypatch):
        from langchain_core.messages import AIMessage

        class _FakeLLMWithTools:
            async def ainvoke(self, messages):
                return AIMessage(content="", tool_calls=[{"name": "x", "args": {}, "id": "c1"}])

        async def fake_execute(tool_name_arg, args, owner_arg=None):
            return json.dumps({"ok": True})

        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent._execute_self_service_tool",
            fake_execute,
        )
        response, _ = await _run_self_service_tool_loop(
            "system prompt", "질문", "1003", "call-y", llm_with_tools=_FakeLLMWithTools(),
        )
        assert response == ""

    @pytest.mark.asyncio
    async def test_loop_invoke_error_returns_empty(self):
        class _FakeLLMWithTools:
            async def ainvoke(self, messages):
                raise RuntimeError("api down")

        response, _ = await _run_self_service_tool_loop(
            "system prompt", "질문", "1003", "call-z", llm_with_tools=_FakeLLMWithTools(),
        )
        assert response == ""

    @pytest.mark.asyncio
    async def test_loop_executes_tool_via_gemini_native_fc_path(self, monkeypatch):
        """gen_model(Gemini 네이티브 FC)만 주어졌을 때도 Tool 실행 후 최종 텍스트를 반환한다
        (2026-07-15 QA 자동 테스트에서 발견된 버그의 실제 수정 경로 — 프로덕션에서 사용되는 경로)."""
        tool_name = getattr(SELF_SERVICE_TOOLS[1], "name", None) or getattr(SELF_SERVICE_TOOLS[1], "__name__", "")
        call_sequence = []

        async def fake_invoke_with_gemini_fc(*, gen_model, lc_messages, generation_config):
            call_sequence.append(1)
            return "fake_response_object"

        def fake_candidate_function_calls(resp):
            if len(call_sequence) == 1:
                return [(tool_name, {"domain": "persona"}, "call_1")]
            return []

        def fake_candidate_text(resp):
            return "" if len(call_sequence) == 1 else "현재 페르소나는 이렇습니다."

        async def fake_execute(tool_name_arg, args, owner_arg=None):
            return json.dumps({"name": "이탈리안 비스트로"}, ensure_ascii=False)

        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.booking_gemini_fc.invoke_booking_model_with_gemini_fc",
            fake_invoke_with_gemini_fc,
        )
        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.booking_gemini_fc._candidate_function_calls",
            fake_candidate_function_calls,
        )
        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.booking_gemini_fc._candidate_text",
            fake_candidate_text,
        )
        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent._execute_self_service_tool",
            fake_execute,
        )

        response, _ = await _run_self_service_tool_loop(
            "system prompt", "설정 알려줘", "1003", "call-fc",
            gen_model="fake_gen_model", generation_config="fake_gen_config",
        )
        assert response == "현재 페르소나는 이렇습니다."
        assert len(call_sequence) == 2

    @pytest.mark.asyncio
    async def test_empty_candidate_retries_then_succeeds(self, monkeypatch):
        """2026-07-20 실서버 QA에서 발견된 문제 재현: Gemini native FC가 finish_reason=STOP인데
        text도 function_call도 없는 완전히 빈 candidate를 반환하는 경우, 같은 라운드 내에서
        짧게 재시도하면 회복되어야 한다(boolean 켜기/끄기 양방향 모두에서 재현된 간헐적 이슈,
        방향 특정 버그 아님)."""
        call_sequence = []

        async def fake_invoke_with_gemini_fc(*, gen_model, lc_messages, generation_config):
            call_sequence.append(1)
            return f"fake_response_{len(call_sequence)}"

        def fake_candidate_function_calls(resp):
            return []  # 이 시나리오는 Tool 호출 없이 순수 텍스트만 확인

        def fake_candidate_text(resp):
            # 1번째 호출만 완전히 빈 응답, 2번째(재시도) 호출에서 정상 텍스트 반환
            return "" if resp == "fake_response_1" else "네, 채팅 자동응답을 켰습니다."

        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.booking_gemini_fc.invoke_booking_model_with_gemini_fc",
            fake_invoke_with_gemini_fc,
        )
        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.booking_gemini_fc._candidate_function_calls",
            fake_candidate_function_calls,
        )
        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.booking_gemini_fc._candidate_text",
            fake_candidate_text,
        )

        response, _ = await _run_self_service_tool_loop(
            "system prompt", "응 맞아, 켜줘", "1003", "call-empty-retry",
            gen_model="fake_gen_model", generation_config="fake_gen_config",
        )
        assert response == "네, 채팅 자동응답을 켰습니다."
        assert len(call_sequence) == 2  # 최초 1회 + 재시도 1회

    @pytest.mark.asyncio
    async def test_empty_candidate_exhausts_retries_returns_empty(self, monkeypatch):
        """모든 재시도에서 계속 빈 candidate가 오면 명확한 재시도 안내 메시지(`_FALLBACK_RETRY_EXHAUSTED`)를
        반환한다(2026-07-21 Story 1.14 — 빈 문자열 대신 명확한 안내로 교체해 상위 호출부의 일반
        인사말 폴백이 사용자를 혼란시키지 않도록 함)."""
        call_sequence = []

        async def fake_invoke_with_gemini_fc(*, gen_model, lc_messages, generation_config):
            call_sequence.append(1)
            return "always_empty"

        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.booking_gemini_fc.invoke_booking_model_with_gemini_fc",
            fake_invoke_with_gemini_fc,
        )
        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.booking_gemini_fc._candidate_function_calls",
            lambda resp: [],
        )
        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.booking_gemini_fc._candidate_text",
            lambda resp: "",
        )

        response, _ = await _run_self_service_tool_loop(
            "system prompt", "응 맞아, 켜줘", "1003", "call-empty-exhausted",
            gen_model="fake_gen_model", generation_config="fake_gen_config",
        )
        assert response == _FALLBACK_RETRY_EXHAUSTED
        # 최초 1회 + _MAX_EMPTY_CANDIDATE_RETRIES(4)회 재시도 = 총 5회 호출
        assert len(call_sequence) == 5

    @pytest.mark.asyncio
    async def test_loop_includes_prev_messages_in_prompt_for_multiturn_context(self, monkeypatch):
        """prev_messages(직전 턴 히스토리)가 이번 턴 프롬프트에 포함되어야 "확인 발화 →
        긍정 응답" 2턴 쓰기 플로우가 동작한다(2026-07-15 QA 자동 테스트에서 발견된 문제의
        회귀 방지 테스트)."""
        from langchain_core.messages import AIMessage, HumanMessage

        captured_messages = []

        class _FakeLLMWithTools:
            async def ainvoke(self, messages):
                captured_messages.extend(messages)
                return AIMessage(content="네, 채팅 자동응답을 껐습니다.")

        prev = [HumanMessage(content="채팅 자동응답 꺼줘"), AIMessage(content="채팅 자동응답을 끌까요?")]

        response, saved_messages = await _run_self_service_tool_loop(
            "system prompt", "응 맞아, 꺼줘", "1003", "call-multiturn",
            llm_with_tools=_FakeLLMWithTools(), prev_messages=prev,
        )

        # 이전 턴 메시지가 이번 턴 LLM 호출에 그대로 포함되어야 한다
        assert prev[0] in captured_messages
        assert prev[1] in captured_messages
        assert response == "네, 채팅 자동응답을 껐습니다."
        # 반환된 saved_messages에도 이전 히스토리 + 이번 턴이 누적되어 있어야 한다
        assert prev[0] in saved_messages
        assert prev[1] in saved_messages


class TestSelfServiceAgentNodeToolCallingIntegration:
    """self_service_agent_node의 bind_tools 경로/폴백 경로 분기 검증 (Task 2)"""

    @pytest.mark.asyncio
    async def test_node_uses_gemini_fc_path_when_bind_tools_unavailable(self, monkeypatch):
        """실제 LLMClient(bind_tools 미지원)에서는 Gemini 네이티브 FC 경로가 사용된다
        (2026-07-15 QA 자동 테스트에서 발견된 버그의 회귀 방지 테스트)."""

        class _FakeInnerModel:
            model_name = "models/gemini-2.0-flash"

        class _FakeLLMClient:
            model = _FakeInnerModel()

            def _effective_generation_config(self, max_output_tokens=None):
                return "fake_gen_config"

        async def fake_run_tool_loop(system_prompt, user_query, owner, call_id, *, llm_with_tools=None, gen_model=None, generation_config=None, prev_messages=None):
            assert llm_with_tools is None
            assert gen_model is not None
            assert generation_config == "fake_gen_config"
            return "네이티브 FC 경로 응답입니다.", []

        async def fake_checklist(owner):
            return []

        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent.get_llm_client",
            lambda: _FakeLLMClient(),
        )
        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent.get_self_service_rag_engine",
            lambda: None,
        )
        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent.get_onboarding_checklist",
            fake_checklist,
        )
        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent._run_self_service_tool_loop",
            fake_run_tool_loop,
        )

        state = {
            "user_query": "지금 설정 어떻게 돼있어?",
            "_owner": "1003",
            "_call_id": "test-tool-fc",
            "messages": [],
        }
        result = await self_service_agent_node(state)

        assert result["response"] == "네이티브 FC 경로 응답입니다."
        assert result["intent"] == "self_service"

    @pytest.mark.asyncio
    async def test_node_uses_tool_loop_when_bind_tools_available(self, monkeypatch):
        from langchain_core.messages import AIMessage

        class _FakeLLMWithTools:
            async def ainvoke(self, messages):
                return AIMessage(content="현재 설정을 확인했습니다.")

        class _FakeRawLLM:
            def bind_tools(self, tools):
                return _FakeLLMWithTools()

        class _FakeLLM:
            _chat_model = _FakeRawLLM()

        async def fake_checklist(owner):
            return []

        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent.get_llm_client",
            lambda: _FakeLLM(),
        )
        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent.get_self_service_rag_engine",
            lambda: None,
        )
        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent.get_onboarding_checklist",
            fake_checklist,
        )

        state = {
            "user_query": "지금 설정 어떻게 돼있어?",
            "_owner": "1003",
            "_call_id": "test-tool-1",
            "messages": [],
        }
        result = await self_service_agent_node(state)

        assert result["response"] == "현재 설정을 확인했습니다."
        assert result["intent"] == "self_service"

    @pytest.mark.asyncio
    async def test_node_falls_back_to_plain_flow_when_bind_tools_unavailable(self, monkeypatch):
        """_chat_model이 없는 LLM 목(Story 1.2/1.3/1.5 기존 목과 동일)이면 프롬프트 폴백 경로 사용(회귀 없음)"""

        class _FakeLLM:
            async def generate_response(self, **kwargs):
                return "안녕하세요!"

        async def fake_checklist(owner):
            return []

        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent.get_llm_client",
            lambda: _FakeLLM(),
        )
        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent.get_self_service_rag_engine",
            lambda: None,
        )
        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent.get_onboarding_checklist",
            fake_checklist,
        )

        state = {"user_query": "안녕하세요", "_owner": "1003", "_call_id": "test-tool-2", "messages": []}
        result = await self_service_agent_node(state)

        assert result["response"] == "안녕하세요!"
