"""
실제(배치) vs 가상(첫 LLM 문장 즉시 TTS) 응답 지연 비교 로그.

현재: LangGraph·LLM 전체 완료 후 TextFrame → TTS.
가상: generate_response 스트리밍 중 첫 문장 완성 시점에 TTS를 시작했다면의 체감 지연.

동일 call_id·turn_id 로 app.log / call_data_record 에 남겨 추후 grep·집계 가능.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

import structlog

from src.common.call_data_record_logger import log_call_data

logger = structlog.get_logger(__name__)

_CTX_KEY = "_ai_latency_turn"

# Story 3.2 (voice-latency-turn-taking-prd.md FR2): 발화 종료→첫 오디오 총 지연 하드 리밋.
# 초과 시 response_latency_sla_exceeded 이벤트로 원인 구간(suspected_stage)을 자동 태깅한다.
SLA_THRESHOLD_MS = 5000.0


def _turn(sync_ctx: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if sync_ctx is None:
        return {}
    t = sync_ctx.get(_CTX_KEY)
    if not isinstance(t, dict):
        t = {}
        sync_ctx[_CTX_KEY] = t
    return t


def begin_turn(
    sync_ctx: Optional[Dict[str, Any]],
    *,
    call_id: str,
    turn_id: int,
    user_text_preview: str = "",
) -> None:
    """새 사용자 턴 — 이전 턴 타이밍 초기화."""
    if sync_ctx is None:
        return
    sync_ctx[_CTX_KEY] = {
        "turn_id": turn_id,
        "call_id": call_id,
        "user_text_preview": (user_text_preview or "")[:120],
    }


def mark_stt_final(sync_ctx: Optional[Dict[str, Any]], *, call_id: str = "") -> None:
    t = _turn(sync_ctx)
    if not t:
        return
    t["stt_final_mono"] = time.perf_counter()
    if call_id:
        t["call_id"] = call_id


def mark_llm_start(sync_ctx: Optional[Dict[str, Any]]) -> None:
    t = _turn(sync_ctx)
    if not t:
        return
    t["llm_start_mono"] = time.perf_counter()


def apply_llm_first_sentence_timing(
    sync_ctx: Optional[Dict[str, Any]],
    *,
    offset_from_llm_start_sec: float,
    sentence_preview: str = "",
    source: str = "streaming",
    elapsed_within_generate_response_sec: Optional[float] = None,
) -> None:
    """
    에이전트 턴 완료 후 호출. offset = LangGraph 시작(llm_start) 이후 첫 문장 준비까지 초.
    (graph 오버헤드 + generate_response 내 첫 문장까지)
    """
    t = _turn(sync_ctx)
    if not t:
        return
    if t.get("llm_first_sentence_mono") is not None:
        return
    llm_start = t.get("llm_start_mono")
    if llm_start is None:
        return
    off = max(0.0, float(offset_from_llm_start_sec))
    t["llm_first_sentence_mono"] = llm_start + off
    t["llm_first_sentence_from_turn_start_sec"] = round(off, 4)
    if elapsed_within_generate_response_sec is not None:
        t["llm_first_sentence_elapsed_sec"] = round(elapsed_within_generate_response_sec, 4)
    t["llm_first_sentence_preview"] = (sentence_preview or "")[:120]
    t["llm_first_sentence_source"] = source


def mark_llm_complete(
    sync_ctx: Optional[Dict[str, Any]],
    *,
    agent_elapsed_sec: float,
    response_len: int = 0,
    chunk_count: int = 0,
    tts_push_mode: str = "batch_after_llm_complete",
    llm_first_sentence_elapsed_sec: Optional[float] = None,
    llm_first_sentence_source: Optional[str] = None,
) -> None:
    t = _turn(sync_ctx)
    if not t:
        return
    t["llm_complete_mono"] = time.perf_counter()
    t["agent_elapsed_sec"] = round(agent_elapsed_sec, 4)
    t["response_len"] = response_len
    t["chunk_count"] = chunk_count
    t["tts_push_mode_planned"] = tts_push_mode
    if llm_first_sentence_elapsed_sec is not None:
        t["llm_first_sentence_elapsed_sec"] = round(llm_first_sentence_elapsed_sec, 4)
    if llm_first_sentence_source:
        t["llm_first_sentence_source"] = llm_first_sentence_source


def mark_tts_text_pushed(
    sync_ctx: Optional[Dict[str, Any]],
    *,
    text_len: int,
    chunk_count: int,
    delivery_mode: str,
) -> None:
    t = _turn(sync_ctx)
    if not t:
        return
    t["tts_text_push_mono"] = time.perf_counter()
    t["tts_text_len"] = text_len
    t["tts_chunk_count"] = chunk_count
    t["tts_delivery_mode"] = delivery_mode


def mark_first_audio_and_compare(sync_ctx: Optional[Dict[str, Any]], *, call_id: str = "") -> None:
    """
    RTP 첫 오디오 송신 시점 — 실제 vs 가상(첫 문장 즉시 TTS) 비교 로그 1회 emit.
    """
    t = _turn(sync_ctx)
    if not t or t.get("_compare_logged"):
        return
    stt_final = t.get("stt_final_mono")
    tts_push = t.get("tts_text_push_mono")
    if stt_final is None or tts_push is None:
        return

    first_audio_mono = time.perf_counter()
    t["first_audio_mono"] = first_audio_mono
    t["_compare_logged"] = True

    cid = call_id or t.get("call_id") or ""
    turn_id = t.get("turn_id")
    mode_actual = t.get("tts_delivery_mode") or "batch_after_llm_complete"

    ms_stt_to_tts_push = _ms(stt_final, tts_push)
    ms_tts_push_to_audio = _ms(tts_push, first_audio_mono)
    ms_stt_to_first_audio_actual = _ms(stt_final, first_audio_mono)

    llm_complete = t.get("llm_complete_mono")
    llm_first = t.get("llm_first_sentence_mono")
    first_sentence_source = t.get("llm_first_sentence_source") or "unknown"
    first_sentence_preview = t.get("llm_first_sentence_preview") or ""

    ms_stt_to_llm_complete = _ms(stt_final, llm_complete) if llm_complete else None
    ms_stt_to_first_sentence = _ms(stt_final, llm_first) if llm_first else None

    # 가상: 첫 문장 시점에 TTS push → 파이프라인 지연(tts_push→첫 오디오)은 동일 가정
    ms_hypothetical_stt_to_first_audio: Optional[float] = None
    ms_saved_perceived: Optional[float] = None
    if ms_stt_to_first_sentence is not None:
        ms_hypothetical_stt_to_first_audio = round(
            ms_stt_to_first_sentence + ms_tts_push_to_audio, 1
        )
        ms_saved_perceived = round(
            ms_stt_to_first_audio_actual - ms_hypothetical_stt_to_first_audio, 1
        )

    ms_wait_after_first_sentence = None
    if llm_first is not None and tts_push is not None:
        ms_wait_after_first_sentence = _ms(llm_first, tts_push)

    ms_llm_complete_to_tts_push = None
    if llm_complete is not None:
        ms_llm_complete_to_tts_push = _ms(llm_complete, tts_push)

    payload: Dict[str, Any] = {
        "turn_id": turn_id,
        "mode_actual": mode_actual,
        "mode_hypothetical": "tts_on_first_llm_sentence",
        "first_sentence_source": first_sentence_source,
        "first_sentence_preview": first_sentence_preview,
        "user_text_preview": t.get("user_text_preview") or "",
        "agent_elapsed_sec": t.get("agent_elapsed_sec"),
        "response_len": t.get("response_len"),
        "tts_text_len": t.get("tts_text_len"),
        "tts_chunk_count": t.get("tts_chunk_count"),
        "ms_stt_final_to_tts_text_push": ms_stt_to_tts_push,
        "ms_tts_text_push_to_first_audio": ms_tts_push_to_audio,
        "ms_stt_final_to_first_audio_actual": ms_stt_to_first_audio_actual,
        "ms_stt_final_to_llm_complete": ms_stt_to_llm_complete,
        "ms_stt_final_to_first_sentence_ready": ms_stt_to_first_sentence,
        "ms_wait_first_sentence_to_tts_push": ms_wait_after_first_sentence,
        "ms_llm_complete_to_tts_text_push": ms_llm_complete_to_tts_push,
        "ms_stt_final_to_first_audio_hypothetical": ms_hypothetical_stt_to_first_audio,
        "ms_perceived_saving_if_early_tts": ms_saved_perceived,
        "llm_first_sentence_elapsed_sec": t.get("llm_first_sentence_elapsed_sec"),
        "note": (
            "actual=STT최종→첫RTP오디오(현행). "
            "hypothetical=STT최종→첫문장준비+TTS파이프라인지연(동일). "
            "ms_perceived_saving_if_early_tts>0 이면 조기 TTS 시 체감 단축 가능(ms)."
        ),
    }

    logger.info(
        "ai_response_latency_compare",
        call=True,
        call_id=cid,
        category="timing",
        progress="timing",
        **payload,
    )

    if cid:
        log_call_data(cid, "timing", "ai_response_latency_compare", **payload)

    # Story 3.2 (FR2): 5초 SLA 초과 시 원인 구간 자동 태깅.
    sla_payload = check_and_tag_sla_exceeded(
        t, total_ms=ms_stt_to_first_audio_actual, call_id=cid
    )
    if sla_payload is not None:
        logger.warning(
            "response_latency_sla_exceeded",
            call=True,
            category="timing",
            progress="timing",
            **sla_payload,
        )
        if cid:
            log_call_data(cid, "timing", "response_latency_sla_exceeded", **sla_payload)


def _ms(t0: float, t1: float) -> float:
    return round((t1 - t0) * 1000.0, 1)


def compute_sla_stage_breakdown_ms(t: Dict[str, Any]) -> Dict[str, float]:
    """
    턴 타이밍 딕셔너리(`t`, `_turn()`이 관리하는 내부 dict)에서 구간별 소요시간(ms)을 계산.

    구간 정의(순서대로): STT 최종 확정(stt_final) → LLM 호출 시작(llm_start) →
    LLM 첫 문장 준비(llm_first_sentence) → LLM 전체 완료(llm_complete) →
    TTS로 텍스트 전달(tts_text_push) → 첫 RTP 오디오 송신(first_audio).

    존재하지 않는 타임스탬프(예: 캐시 히트로 LLM 자체를 안 탄 경우)는 건너뛴다 —
    부분 정보라도 반환한다(voice-latency-turn-taking-prd.md FR2 AC3, "unknown이어도
    구간별 값은 함께 남긴다").
    """
    stt_final = t.get("stt_final_mono")
    llm_start = t.get("llm_start_mono")
    llm_first = t.get("llm_first_sentence_mono")
    llm_complete = t.get("llm_complete_mono")
    tts_push = t.get("tts_text_push_mono")
    first_audio = t.get("first_audio_mono")

    breakdown: Dict[str, float] = {}
    if stt_final is not None and llm_start is not None:
        breakdown["cache_or_rag_pre_llm"] = _ms(stt_final, llm_start)
    if llm_start is not None and llm_first is not None:
        breakdown["llm_first_sentence_generation"] = _ms(llm_start, llm_first)
    if llm_first is not None and llm_complete is not None:
        breakdown["llm_remaining_generation"] = _ms(llm_first, llm_complete)
    if llm_complete is not None and tts_push is not None:
        breakdown["post_llm_processing"] = _ms(llm_complete, tts_push)
    elif llm_first is not None and tts_push is not None and llm_complete is None:
        # chunked 스트리밍 등으로 llm_complete 마크가 없는 경우 첫 문장 기준으로 대체.
        breakdown["post_llm_processing"] = _ms(llm_first, tts_push)
    if tts_push is not None and first_audio is not None:
        breakdown["tts_synthesis_and_rtp"] = _ms(tts_push, first_audio)
    return breakdown


def suspected_sla_stage(breakdown: Dict[str, float]) -> str:
    """구간별 소요시간(ms) 중 가장 큰 구간의 이름을 반환. 값이 없으면 'unknown'."""
    if not breakdown:
        return "unknown"
    return max(breakdown, key=breakdown.get)


def check_and_tag_sla_exceeded(
    t: Dict[str, Any],
    *,
    total_ms: float,
    call_id: str = "",
    threshold_ms: float = SLA_THRESHOLD_MS,
) -> Optional[Dict[str, Any]]:
    """
    총 지연(`total_ms`)이 임계값을 초과하면 원인 구간을 태깅한 payload를 반환하고,
    초과하지 않으면 `None`을 반환한다(정상 케이스는 이벤트를 만들지 않음 — FR2 AC4).

    로깅은 호출부(`mark_first_audio_and_compare`)에서 수행한다 — 이 함수는 순수 계산만
    담당해 단위 테스트가 로거 없이도 가능하게 한다(voice-latency-turn-taking Story 3.2 Task 1).
    """
    if total_ms <= threshold_ms:
        return None
    breakdown = compute_sla_stage_breakdown_ms(t)
    return {
        "call_id": call_id or t.get("call_id") or "",
        "turn_id": t.get("turn_id"),
        "total_ms": round(total_ms, 1),
        "threshold_ms": threshold_ms,
        "suspected_stage": suspected_sla_stage(breakdown),
        "stage_breakdown_ms": breakdown,
        "user_text_preview": t.get("user_text_preview") or "",
    }
