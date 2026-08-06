"""
AI Voicebot Unit Tests - IntelliDecision 판단 근거 투명성 (Story 1.21, FR30)

docs/stories/1.21.intellidecision-rationale-logging-and-api.story.md 참고.
"""

import sqlite3
from contextlib import contextmanager

import pytest

from src.api.routers.self_service import get_decision_log
from src.common.self_service_decision_log_db import record_decision_rationale, list_decision_log
from src.ai_voicebot.self_service.decision_rationale import (
    _parse_classification_result,
    _build_classification_prompt,
    schedule_rationale_capture,
)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_self_service_decision_log.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS self_service_decision_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner TEXT NOT NULL,
            call_id TEXT NOT NULL DEFAULT '',
            caller_number TEXT NOT NULL DEFAULT '',
            matched_type TEXT NOT NULL DEFAULT 'unknown',
            reasoning_summary TEXT NOT NULL DEFAULT '',
            related_domain TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )
        """
    )
    # Story 1.38: 채널(음성/채팅) 판별용 — decision_log.call_id가 여기 있으면 채팅으로 간주.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id TEXT NOT NULL,
            owner TEXT NOT NULL,
            call_id TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.commit()
    conn.close()

    @contextmanager
    def fake_get_db():
        c = sqlite3.connect(str(db_path))
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        finally:
            c.close()

    monkeypatch.setattr("src.booking.database.get_db", fake_get_db)
    return db_path


class TestRecordAndListDecisionRationale:
    """DB 헬퍼: 기록·조회·owner 격리 (AC3/IV3)"""

    def test_record_and_list_roundtrip(self, temp_db):
        ok = record_decision_rationale(
            owner="9001", call_id="call-1", matched_type="B",
            reasoning_summary="채팅 자동응답 끄기 요청", related_domain="chat-relay",
        )
        assert ok is True

        items = list_decision_log("9001", limit=10)
        assert len(items) == 1
        assert items[0]["matched_type"] == "B"
        assert items[0]["reasoning_summary"] == "채팅 자동응답 끄기 요청"

    def test_owner_isolation(self, temp_db):
        record_decision_rationale(owner="owner-a", matched_type="A", reasoning_summary="a")
        record_decision_rationale(owner="owner-b", matched_type="C", reasoning_summary="b")

        result_a = list_decision_log("owner-a", limit=10)
        assert len(result_a) == 1
        assert result_a[0]["owner"] == "owner-a"

    def test_reasoning_summary_truncated_to_200_chars(self, temp_db):
        long_text = "가" * 500
        record_decision_rationale(owner="9001", matched_type="A", reasoning_summary=long_text)

        items = list_decision_log("9001", limit=10)
        assert len(items[0]["reasoning_summary"]) == 200

    def test_sorted_by_created_at_desc(self, temp_db):
        import time

        record_decision_rationale(owner="9001", matched_type="A", reasoning_summary="first")
        time.sleep(1.1)
        record_decision_rationale(owner="9001", matched_type="B", reasoning_summary="second")

        items = list_decision_log("9001", limit=10)
        assert items[0]["matched_type"] == "B"
        assert items[1]["matched_type"] == "A"


class TestGetDecisionLogApi:
    """API 라우터 함수 owner 필터/왕복 검증 (AC4/IV3)"""

    def test_owner_filter_isolates_other_tenants(self, temp_db):
        record_decision_rationale(owner="owner-a", matched_type="A", reasoning_summary="a")
        record_decision_rationale(owner="owner-b", matched_type="B", reasoning_summary="b")

        result = get_decision_log(owner="owner-a", limit=50)

        assert result["total"] == 1
        assert result["items"][0]["owner"] == "owner-a"

    def test_empty_result_when_no_history(self, temp_db):
        result = get_decision_log(owner="owner-none", limit=50)
        assert result == {"items": [], "total": 0}


class TestParseClassificationResult:
    """분류 응답 파싱 — 정상/비정상 케이스 (AC1/AC2)"""

    def test_parses_valid_two_line_response(self):
        text = "유형: B\n요약: 채팅 자동응답 끄기 요청"
        matched_type, summary = _parse_classification_result(text)
        assert matched_type == "B"
        assert summary == "채팅 자동응답 끄기 요청"

    def test_returns_unknown_on_malformed_response(self):
        matched_type, summary = _parse_classification_result("죄송하지만 이해하지 못했습니다.")
        assert matched_type == "unknown"
        assert summary == ""

    def test_returns_unknown_on_empty_response(self):
        matched_type, summary = _parse_classification_result("")
        assert matched_type == "unknown"
        assert summary == ""

    def test_returns_unknown_on_invalid_type_code(self):
        text = "유형: Z\n요약: 알 수 없는 유형"
        matched_type, summary = _parse_classification_result(text)
        assert matched_type == "unknown"


class TestBuildClassificationPrompt:
    def test_includes_intent_types_and_utterance(self):
        prompt = _build_classification_prompt("채팅 자동응답 꺼줘", "네, 껐습니다.")
        assert "채팅 자동응답 꺼줘" in prompt
        assert "네, 껐습니다." in prompt
        assert "A:" in prompt and "I:" in prompt  # 유형 목록이 포함되어야 함


class TestDecisionLogSessionGrouping:
    """Story 1.38(FR34-F): 채널별 세션 그룹핑 — 음성=call_id, 채팅=caller_number+시간 윈도우."""

    def test_voice_calls_group_by_call_id(self, temp_db):
        from src.common.self_service_decision_log_db import list_decision_log_sessions

        # 동일 call_id(음성 통화, chat_messages에 없음) 2턴 = 세션 1개.
        record_decision_rationale(owner="9001", call_id="voice-call-1", caller_number="01011112222", matched_type="A")
        record_decision_rationale(owner="9001", call_id="voice-call-1", caller_number="01011112222", matched_type="E")

        sessions = list_decision_log_sessions("9001", limit=10)
        assert len(sessions) == 1
        assert sessions[0]["channel"] == "voice"
        assert sessions[0]["turn_count"] == 2
        assert sessions[0]["type_sequence"] == ["A", "E"]
        assert sessions[0]["final_type"] == "E"

    def test_chat_messages_with_different_call_ids_group_by_caller_and_window(self, temp_db):
        from src.common.self_service_decision_log_db import list_decision_log_sessions
        from src.booking.database import get_db

        # 채팅 메시지는 트랜잭션마다 call_id가 다르다 — chat_messages에 두 call_id 모두 등록.
        with get_db() as conn:
            conn.execute(
                "INSERT INTO chat_messages (thread_id, owner, call_id) VALUES (?, ?, ?)",
                ("9001|sms|9001", "9001", "chat-msg-1"),
            )
            conn.execute(
                "INSERT INTO chat_messages (thread_id, owner, call_id) VALUES (?, ?, ?)",
                ("9001|sms|9001", "9001", "chat-msg-2"),
            )

        record_decision_rationale(owner="9001", call_id="chat-msg-1", caller_number="9001", matched_type="A")
        record_decision_rationale(owner="9001", call_id="chat-msg-2", caller_number="9001", matched_type="C")

        sessions = list_decision_log_sessions("9001", limit=10)
        assert len(sessions) == 1
        assert sessions[0]["channel"] == "chat"
        assert sessions[0]["turn_count"] == 2
        assert sessions[0]["type_sequence"] == ["A", "C"]

    def test_chat_messages_outside_window_split_into_separate_sessions(self, temp_db):
        from src.common.self_service_decision_log_db import list_decision_log_sessions
        from src.booking.database import get_db

        with get_db() as conn:
            conn.execute(
                "INSERT INTO chat_messages (thread_id, owner, call_id) VALUES (?, ?, ?)",
                ("9001|sms|9001", "9001", "chat-old"),
            )
            conn.execute(
                "INSERT INTO chat_messages (thread_id, owner, call_id) VALUES (?, ?, ?)",
                ("9001|sms|9001", "9001", "chat-new"),
            )
            conn.execute(
                """
                INSERT INTO self_service_decision_log
                    (owner, call_id, caller_number, matched_type, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("9001", "chat-old", "9001", "A", "2026-08-01 10:00:00"),
            )
            conn.execute(
                """
                INSERT INTO self_service_decision_log
                    (owner, call_id, caller_number, matched_type, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("9001", "chat-new", "9001", "C", "2026-08-01 11:00:00"),  # 60분 뒤(기본 30분 초과)
            )

        sessions = list_decision_log_sessions("9001", limit=10)
        assert len(sessions) == 2
        assert {s["turn_count"] for s in sessions} == {1}

    def test_session_detail_returns_full_turns(self, temp_db):
        from src.common.self_service_decision_log_db import (
            get_decision_log_session_detail,
            list_decision_log_sessions,
        )

        record_decision_rationale(owner="9001", call_id="voice-call-2", caller_number="01011112222", matched_type="A")
        record_decision_rationale(owner="9001", call_id="voice-call-2", caller_number="01011112222", matched_type="E")

        sessions = list_decision_log_sessions("9001", limit=10)
        detail = get_decision_log_session_detail("9001", sessions[0]["session_key"])
        assert detail is not None
        assert len(detail["turns"]) == 2
        assert detail["turns"][0]["matched_type"] == "A"

    def test_session_detail_returns_none_for_unknown_key(self, temp_db):
        from src.common.self_service_decision_log_db import get_decision_log_session_detail

        assert get_decision_log_session_detail("9001", "voice:no-such-session") is None


class TestScheduleRationaleCaptureNeverBlocks:
    """FR30 핵심 요구사항: 캡처 실패/예외가 호출부에 전파되지 않아야 한다."""

    def test_returns_none_without_owner(self):
        # owner가 없으면 태스크를 만들지 않고 조용히 None을 반환해야 한다.
        assert schedule_rationale_capture(
            user_query="x", ai_response="y", owner="", call_id="c1",
        ) is None

    @pytest.mark.asyncio
    async def test_schedule_creates_background_task_and_does_not_raise(self, monkeypatch):
        called = {}

        async def _fake_capture(**kwargs):
            called.update(kwargs)

        monkeypatch.setattr(
            "src.ai_voicebot.self_service.decision_rationale._capture_and_log",
            _fake_capture,
        )

        task = schedule_rationale_capture(
            user_query="채팅 자동응답 꺼줘", ai_response="네, 껐습니다.",
            owner="9001", call_id="call-1",
        )
        assert task is not None
        await task  # 테스트에서는 완료를 기다려 부작용을 검증(프로덕션 호출부는 await하지 않음)
        assert called["owner"] == "9001"
        assert called["call_id"] == "call-1"

    @pytest.mark.asyncio
    async def test_capture_and_log_swallows_llm_exception(self, monkeypatch):
        """LLM 호출이 예외를 던져도 _capture_and_log는 예외를 다시 던지지 않아야 한다(FR30)."""
        from src.ai_voicebot.self_service.decision_rationale import _capture_and_log

        class _BoomLLMClient:
            async def generate_response(self, *a, **kw):
                raise RuntimeError("boom")

        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.call_context.get_llm_client",
            lambda: _BoomLLMClient(),
        )

        recorded = {}

        def _fake_record(**kwargs):
            recorded.update(kwargs)
            return True

        monkeypatch.setattr(
            "src.common.self_service_decision_log_db.record_decision_rationale",
            _fake_record,
        )

        # 예외가 전파되지 않아야 한다(assert 실패 시 이 테스트 자체가 실패로 표시됨).
        await _capture_and_log(
            user_query="x", ai_response="y", owner="9001", call_id="call-err",
        )
        assert recorded["matched_type"] == "unknown"
