"""
Story 3.2 (voice-latency-turn-taking-prd.md FR2): 5초 SLA 초과 원인 자동 태깅 단위 테스트.

check_and_tag_sla_exceeded()/compute_sla_stage_breakdown_ms()/suspected_sla_stage()는
순수 함수이므로 실제 시각(time.perf_counter) 대신 합성 타임스탬프로 검증한다.
"""

from __future__ import annotations

from src.common.ai_response_latency_compare import (
    check_and_tag_sla_exceeded,
    compute_sla_stage_breakdown_ms,
    suspected_sla_stage,
)


def _t(**marks) -> dict:
    """합성 턴 타이밍 딕셔너리 생성. marks는 초(sec) 단위 절대 오프셋."""
    base = {
        "turn_id": 1,
        "call_id": "call-123",
        "user_text_preview": "테스트 발화",
    }
    for key, value in marks.items():
        base[f"{key}_mono"] = value
    return base


class TestComputeSlaStageBreakdownMs:
    def test_full_breakdown_all_stages_present(self):
        t = _t(stt_final=0.0, llm_start=0.1, llm_first_sentence=0.9, llm_complete=1.5, tts_text_push=1.6, first_audio=2.0)
        breakdown = compute_sla_stage_breakdown_ms(t)
        assert breakdown["cache_or_rag_pre_llm"] == 100.0
        assert breakdown["llm_first_sentence_generation"] == 800.0
        assert breakdown["llm_remaining_generation"] == 600.0
        assert breakdown["post_llm_processing"] == 100.0
        assert breakdown["tts_synthesis_and_rtp"] == 400.0

    def test_partial_breakdown_missing_llm_complete_falls_back_to_first_sentence(self):
        # 청크 스트리밍 등으로 llm_complete 마크가 없는 경우
        t = _t(stt_final=0.0, llm_start=0.1, llm_first_sentence=0.5, tts_text_push=0.6, first_audio=1.0)
        breakdown = compute_sla_stage_breakdown_ms(t)
        assert "llm_remaining_generation" not in breakdown
        assert breakdown["post_llm_processing"] == 100.0
        assert breakdown["tts_synthesis_and_rtp"] == 400.0

    def test_empty_timings_returns_empty_breakdown(self):
        assert compute_sla_stage_breakdown_ms({}) == {}


class TestSuspectedSlaStage:
    def test_returns_stage_with_largest_duration(self):
        breakdown = {"cache_or_rag_pre_llm": 100.0, "llm_first_sentence_generation": 4200.0, "tts_synthesis_and_rtp": 300.0}
        assert suspected_sla_stage(breakdown) == "llm_first_sentence_generation"

    def test_empty_breakdown_returns_unknown(self):
        assert suspected_sla_stage({}) == "unknown"


class TestCheckAndTagSlaExceeded:
    def test_under_threshold_returns_none(self):
        t = _t(stt_final=0.0, llm_start=0.1, llm_first_sentence=0.5, llm_complete=0.8, tts_text_push=0.9, first_audio=1.2)
        result = check_and_tag_sla_exceeded(t, total_ms=1200.0, call_id="call-1")
        assert result is None

    def test_exactly_at_threshold_returns_none(self):
        t = _t(stt_final=0.0)
        result = check_and_tag_sla_exceeded(t, total_ms=5000.0, call_id="call-1")
        assert result is None

    def test_over_threshold_tags_suspected_stage(self):
        # LLM 생성 구간이 압도적으로 긴 케이스(현재 실제 병목 패턴과 유사, 2026-03-30 리포트 근거)
        t = _t(stt_final=0.0, llm_start=0.1, llm_first_sentence=4.7, llm_complete=5.9, tts_text_push=6.0, first_audio=6.3)
        result = check_and_tag_sla_exceeded(t, total_ms=6300.0, call_id="call-42")
        assert result is not None
        assert result["call_id"] == "call-42"
        assert result["turn_id"] == 1
        assert result["total_ms"] == 6300.0
        assert result["threshold_ms"] == 5000.0
        assert result["suspected_stage"] == "llm_first_sentence_generation"
        assert result["stage_breakdown_ms"]["llm_first_sentence_generation"] == 4600.0

    def test_over_threshold_with_no_timings_returns_unknown_stage_but_still_tags(self):
        # AC3: 원인 판별이 애매/불가능해도 이벤트 자체는 발생해야 한다.
        result = check_and_tag_sla_exceeded({}, total_ms=8000.0, call_id="call-99")
        assert result is not None
        assert result["suspected_stage"] == "unknown"
        assert result["stage_breakdown_ms"] == {}

    def test_custom_threshold_respected(self):
        t = _t(stt_final=0.0, tts_text_push=1.0, first_audio=1.5)
        assert check_and_tag_sla_exceeded(t, total_ms=1500.0, call_id="c", threshold_ms=1000.0) is not None
        assert check_and_tag_sla_exceeded(t, total_ms=900.0, call_id="c", threshold_ms=1000.0) is None
