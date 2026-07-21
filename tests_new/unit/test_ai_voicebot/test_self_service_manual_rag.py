"""
AI Voicebot Unit Tests - 셀프서비스 매뉴얼 RAG 색인/검색 (Story 1.3)

Story 1.3: 셀프서비스 매뉴얼 RAG 연동
docs/stories/1.3.self-service-manual-rag.story.md §Testing 참고

커버 범위(Task 5):
  - 매뉴얼 Q&A 파서(parse_manual_qa_pairs)
  - 색인 파이프라인의 owner/doc_type 격리, 멱등성(index_self_service_manual)
  - 셀프서비스 전용 RAGEngine 싱글턴(doc_type_allowlist 고정, 캐싱)
  - self_service_agent_node의 RAG 컨텍스트 주입/폴백 동작(HITL 미트리거)
"""

import pytest

from src.ai_voicebot.ai_pipeline.rag_engine import Document, RAGSearchResult
from src.ai_voicebot.self_service import rag as self_service_rag
from src.ai_voicebot.self_service.manual_indexer import (
    SELF_SERVICE_MANUAL_DOC_TYPE,
    index_self_service_manual,
    parse_manual_qa_pairs,
    parse_manual_qa_with_meta,
)
from src.ai_voicebot.langgraph.nodes.self_service_agent import (
    RESPONSE_UNKNOWN_NEEDS_FOLLOWUP,
    self_service_agent_node,
)


SAMPLE_MANUAL = """# 샘플 매뉴얼

## 1. 섹션

**Q: 이 서비스가 무엇인가요?**
A: 예약과 문의를 자동으로 처리하는 AI 서비스입니다.

**Q: 설정은 어디서 하나요?**
A: 설정 메뉴에서
1. 착신 규칙
2. 예약 도메인
을 순서대로 설정하세요.

---

## 2. 다음 섹션

**Q: 다른 질문인가요?**
A: 네 다른 답변입니다.
"""


class TestParseManualQaPairs:
    """매뉴얼 마크다운 Q&A 파서 테스트"""

    def test_parses_all_pairs(self):
        pairs = parse_manual_qa_pairs(SAMPLE_MANUAL)
        assert len(pairs) == 3

    def test_question_and_answer_content(self):
        pairs = parse_manual_qa_pairs(SAMPLE_MANUAL)
        q0, a0 = pairs[0]
        assert q0 == "이 서비스가 무엇인가요?"
        assert "예약과 문의" in a0

    def test_multiline_answer_captured_until_next_question_or_divider(self):
        pairs = parse_manual_qa_pairs(SAMPLE_MANUAL)
        q1, a1 = pairs[1]
        assert q1 == "설정은 어디서 하나요?"
        assert "착신 규칙" in a1
        assert "예약 도메인" in a1
        # 다음 섹션의 답변 내용이 섞여 들어가지 않아야 함
        assert "다른 답변" not in a1

    def test_empty_text_returns_empty_list(self):
        assert parse_manual_qa_pairs("") == []


class TestParseManualQaWithMetaDomainTag:
    """Story 2.8 — 섹션 제목의 명시적 {domain: xxx} 태그 우선 인식 + 키워드 매칭 폴백 검증"""

    def test_explicit_domain_tag_is_used_when_present(self):
        text = """# 매뉴얼

## 3. AI 에스컬레이션 설정 {domain: ai-escalation}

**Q: 질문입니다?**
A: 답변입니다.
"""
        items = parse_manual_qa_with_meta(text)
        assert len(items) == 1
        assert items[0]["related_domain"] == "ai-escalation"
        # 태그는 표시용 제목에서 제거되어야 함(원문 그대로 노출 안 함)
        assert items[0]["section_title"] == "AI 에스컬레이션 설정"

    def test_falls_back_to_keyword_matching_when_no_tag(self):
        text = """# 매뉴얼

## 1. 채팅 자동응답

**Q: 질문입니다?**
A: 답변입니다.
"""
        items = parse_manual_qa_with_meta(text)
        assert items[0]["related_domain"] == "chat-relay"
        assert items[0]["section_title"] == "채팅 자동응답"

    def test_tag_overrides_conflicting_keyword_match(self):
        """제목에 키워드 매칭 대상 단어가 있어도 명시적 태그가 우선한다."""
        text = """# 매뉴얼

## 2. 채팅 관련 예약 안내 {domain: booking}

**Q: 질문입니다?**
A: 답변입니다.
"""
        items = parse_manual_qa_with_meta(text)
        assert items[0]["related_domain"] == "booking"

    def test_no_tag_and_no_keyword_match_returns_empty_domain(self):
        text = """# 매뉴얼

## 9. 알 수 없는 섹션

**Q: 질문입니다?**
A: 답변입니다.
"""
        items = parse_manual_qa_with_meta(text)
        assert items[0]["related_domain"] == ""

    def test_mixed_tagged_and_untagged_sections(self):
        """일부 섹션만 태그가 있어도(점진적 마이그레이션) 각각 올바르게 처리되어야 함(IV1)."""
        text = """# 매뉴얼

## 1. 채팅 자동응답

**Q: 첫 번째 질문?**
A: 첫 번째 답변.

---

## 2. AI 에스컬레이션 설정 {domain: ai-escalation}

**Q: 두 번째 질문?**
A: 두 번째 답변.
"""
        items = parse_manual_qa_with_meta(text)
        assert len(items) == 2
        assert items[0]["related_domain"] == "chat-relay"  # 폴백(키워드 매칭)
        assert items[1]["related_domain"] == "ai-escalation"  # 명시적 태그


class TestIndexSelfServiceManual:
    """add_knowledge/list_knowledge를 모킹해 색인 파이프라인의 owner/doc_type 격리 및 멱등성 검증"""

    @staticmethod
    def _make_fake_store():
        store = []

        def fake_list_knowledge(vector_db, owner=None, category=None, doc_type=None, source=None, limit=500):
            items = [
                d for d in store
                if (not owner or d["owner"] == owner) and (not doc_type or d["doc_type"] == doc_type)
            ]
            return {"items": items, "total": len(items)}

        def fake_add_knowledge(
            vector_db, embedder, text, owner, category,
            doc_type="knowledge", source="api", answer=None, call_id=None, **kwargs
        ):
            store.append({"owner": owner, "doc_type": doc_type, "category": category, "text": text})
            return {"ok": True, "doc_id": f"kb_{len(store)}"}

        return store, fake_list_knowledge, fake_add_knowledge

    def _patch_common(self, monkeypatch, fake_list, fake_add):
        monkeypatch.setattr("src.ai_voicebot.self_service.manual_indexer.list_knowledge", fake_list)
        monkeypatch.setattr("src.ai_voicebot.self_service.manual_indexer.add_knowledge", fake_add)
        monkeypatch.setattr(
            "src.ai_voicebot.self_service.manual_indexer.load_manual_qa_pairs",
            lambda manual_path=None: parse_manual_qa_pairs(SAMPLE_MANUAL),
        )

    def test_indexes_all_pairs_for_owner(self, monkeypatch):
        store, fake_list, fake_add = self._make_fake_store()
        self._patch_common(monkeypatch, fake_list, fake_add)

        result = index_self_service_manual("1003", vector_db=object(), embedder=object())

        assert result["ok"] is True
        assert result["indexed"] == 3
        assert all(d["doc_type"] == SELF_SERVICE_MANUAL_DOC_TYPE for d in store)
        assert all(d["owner"] == "1003" for d in store)

    def test_skips_reindexing_when_already_indexed(self, monkeypatch):
        store, fake_list, fake_add = self._make_fake_store()
        store.append({"owner": "1003", "doc_type": SELF_SERVICE_MANUAL_DOC_TYPE, "category": "question", "text": "existing"})
        self._patch_common(monkeypatch, fake_list, fake_add)

        result = index_self_service_manual("1003", vector_db=object(), embedder=object())

        assert result["skipped"] is True
        assert result["indexed"] == 0
        assert len(store) == 1  # 재색인 안 됨(멱등성)

    def test_force_reindexes_even_if_existing(self, monkeypatch):
        store, fake_list, fake_add = self._make_fake_store()
        store.append({"owner": "1003", "doc_type": SELF_SERVICE_MANUAL_DOC_TYPE, "category": "question", "text": "existing"})
        self._patch_common(monkeypatch, fake_list, fake_add)

        result = index_self_service_manual("1003", vector_db=object(), embedder=object(), force=True)

        assert result["skipped"] is False
        assert result["indexed"] == 3

    def test_different_owners_are_isolated(self, monkeypatch):
        store, fake_list, fake_add = self._make_fake_store()
        self._patch_common(monkeypatch, fake_list, fake_add)

        index_self_service_manual("owner-a", vector_db=object(), embedder=object())
        index_self_service_manual("owner-b", vector_db=object(), embedder=object())

        owner_a_docs = [d for d in store if d["owner"] == "owner-a"]
        owner_b_docs = [d for d in store if d["owner"] == "owner-b"]
        assert len(owner_a_docs) == 3
        assert len(owner_b_docs) == 3

    def test_empty_owner_returns_error(self):
        result = index_self_service_manual("", vector_db=object(), embedder=object())
        assert result["ok"] is False


class TestGetSelfServiceRagEngine:
    """셀프서비스 전용 RAGEngine 싱글턴(Task 3) 테스트"""

    def setup_method(self):
        self_service_rag.reset_self_service_rag_engine_cache()

    def teardown_method(self):
        self_service_rag.reset_self_service_rag_engine_cache()

    def test_returns_none_without_embedder_or_vector_db(self, monkeypatch):
        monkeypatch.setattr("src.ai_voicebot.self_service.rag.get_embedder", lambda: None)
        monkeypatch.setattr("src.ai_voicebot.self_service.rag.get_vector_db", lambda: None)
        assert self_service_rag.get_self_service_rag_engine() is None

    def test_builds_engine_with_doc_type_allowlist(self, monkeypatch):
        monkeypatch.setattr("src.ai_voicebot.self_service.rag.get_embedder", lambda: object())
        monkeypatch.setattr("src.ai_voicebot.self_service.rag.get_vector_db", lambda: object())

        engine = self_service_rag.get_self_service_rag_engine()

        assert engine is not None
        assert engine._doc_type_allowlist == (SELF_SERVICE_MANUAL_DOC_TYPE,)

    def test_caches_instance_across_calls(self, monkeypatch):
        fixed_embedder = object()
        fixed_vector_db = object()
        monkeypatch.setattr("src.ai_voicebot.self_service.rag.get_embedder", lambda: fixed_embedder)
        monkeypatch.setattr("src.ai_voicebot.self_service.rag.get_vector_db", lambda: fixed_vector_db)

        engine1 = self_service_rag.get_self_service_rag_engine()
        engine2 = self_service_rag.get_self_service_rag_engine()

        assert engine1 is engine2

    def test_recreates_engine_when_embedder_instance_changes(self, monkeypatch):
        fixed_vector_db = object()
        monkeypatch.setattr("src.ai_voicebot.self_service.rag.get_vector_db", lambda: fixed_vector_db)
        monkeypatch.setattr("src.ai_voicebot.self_service.rag.get_embedder", lambda: object())
        engine1 = self_service_rag.get_self_service_rag_engine()

        monkeypatch.setattr("src.ai_voicebot.self_service.rag.get_embedder", lambda: object())
        engine2 = self_service_rag.get_self_service_rag_engine()

        assert engine1 is not engine2


class TestSelfServiceAgentNodeRagIntegration:
    """self_service_agent_node()의 RAG 컨텍스트 주입/폴백 동작 검증 (Task 4)"""

    @pytest.mark.asyncio
    async def test_rag_hits_are_passed_as_context_to_llm(self, monkeypatch):
        doc = Document(
            id="kb_1",
            text="Q: 착신 규칙이 뭔가요?\nA: 착신 규칙은 전화를 어떻게 받을지 정하는 설정입니다.",
            score=0.9,
            metadata={"doc_type": SELF_SERVICE_MANUAL_DOC_TYPE},
        )

        class _FakeRagEngine:
            async def search(self, query, owner_filter=None, call_id=None, top_k_override=None, intent=None):
                return RAGSearchResult(documents=[doc], trace={})

        captured = {}

        class _FakeLLM:
            async def generate_response(self, **kwargs):
                captured["system_prompt"] = kwargs.get("system_prompt", "")
                return "착신 규칙 설정 방법을 안내해 드릴게요."

        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent.get_llm_client",
            lambda: _FakeLLM(),
        )
        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent.get_self_service_rag_engine",
            lambda: _FakeRagEngine(),
        )

        state = {
            "user_query": "착신 규칙 어떻게 설정해요?",
            "_owner": "1003",
            "_call_id": "test-rag-1",
            "messages": [],
        }
        result = await self_service_agent_node(state)

        assert "착신 규칙" in captured["system_prompt"]
        assert result["intent"] == "self_service"
        assert result["business_state"] == "self_service_handled"

    @pytest.mark.asyncio
    async def test_no_rag_hits_instructs_fallback_message(self, monkeypatch):
        class _FakeRagEngine:
            async def search(self, query, owner_filter=None, call_id=None, top_k_override=None, intent=None):
                return RAGSearchResult(documents=[], trace={})

        captured = {}

        class _FakeLLM:
            async def generate_response(self, **kwargs):
                captured["system_prompt"] = kwargs.get("system_prompt", "")
                return RESPONSE_UNKNOWN_NEEDS_FOLLOWUP

        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent.get_llm_client",
            lambda: _FakeLLM(),
        )
        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent.get_self_service_rag_engine",
            lambda: _FakeRagEngine(),
        )

        state = {
            "user_query": "제3자 결제 연동은 어떻게 하나요?",
            "_owner": "1003",
            "_call_id": "test-rag-2",
            "messages": [],
        }
        result = await self_service_agent_node(state)

        assert "(관련 정보 없음)" in captured["system_prompt"]
        assert RESPONSE_UNKNOWN_NEEDS_FOLLOWUP in captured["system_prompt"]
        assert result["response"] == RESPONSE_UNKNOWN_NEEDS_FOLLOWUP
        # HITL 트리거 필드(needs_follow_up 등)를 세팅하지 않음 — 관리자 세션이므로 개입 큐에 넣지 않는다.
        assert "needs_follow_up" not in result

    @pytest.mark.asyncio
    async def test_rag_search_error_falls_back_gracefully(self, monkeypatch):
        class _FakeRagEngine:
            async def search(self, *args, **kwargs):
                raise RuntimeError("chroma down")

        class _FakeLLM:
            async def generate_response(self, **kwargs):
                return "잠시 도움을 드리기 어렵지만 다시 말씀해 주세요."

        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent.get_llm_client",
            lambda: _FakeLLM(),
        )
        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent.get_self_service_rag_engine",
            lambda: _FakeRagEngine(),
        )

        state = {"user_query": "질문입니다", "_owner": "1003", "_call_id": "test-rag-3", "messages": []}
        result = await self_service_agent_node(state)

        assert result["response"]
        assert result["intent"] == "self_service"

    @pytest.mark.asyncio
    async def test_no_rag_engine_available_still_responds(self, monkeypatch):
        """rag_engine이 None(embedder/vector_db 미설정)이어도 정상 동작(회귀 없음, Story 1.2 동작 유지)"""

        class _FakeLLM:
            async def generate_response(self, **kwargs):
                return "안녕하세요!"

        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent.get_llm_client",
            lambda: _FakeLLM(),
        )
        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent.get_self_service_rag_engine",
            lambda: None,
        )

        state = {"user_query": "안녕하세요", "_owner": "1003", "_call_id": "test-rag-4", "messages": []}
        result = await self_service_agent_node(state)

        assert result["response"]
        assert result["intent"] == "self_service"
