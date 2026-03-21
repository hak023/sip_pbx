"""
Stage 3 품질 검증: 전사 재구성 + 의미 기반(임베딩 유사도) 검증.
지식베이스 중복 제외(dedup) 및 상세 로깅 포함.

사용 예:
  from knowledge_pipeline import (
      reconstruct_callee_transcript,
      verify_extracted_items,
      filter_duplicates_for_save,
  )
  callee_text = reconstruct_callee_transcript(transcript_raw)
  verified, stats = verify_extracted_items(
      extracted_items, callee_text, embed_fn,
      threshold_grounding=0.70, call_id="...", log_fn=logger.info
  )
  to_store, dedup_stats = filter_duplicates_for_save(
      verified, similarity_to_existing_fn, threshold_dedup=0.92,
      call_id="...", log_fn=logger.info
  )
"""
from __future__ import annotations

import re
import logging
from typing import Callable, List, Dict, Any, Optional, Tuple

# 기본 로거 (호출 측에서 log_fn으로 덮어쓸 수 있음)
logger = logging.getLogger(__name__)


def _default_log(level: str, msg: str, **kwargs: Any) -> None:
    extra = " ".join(f"{k}={v!r}" for k, v in kwargs.items())
    getattr(logger, level)(f"[knowledge_stage3] {msg} {extra}".strip())


def reconstruct_callee_transcript(
    transcript_raw: str,
    split_sentences: bool = False,
) -> str | Tuple[str, List[str]]:
    """
    '착신자: ... \\n발신자: ...' 형태 전사에서 착신자(callee) 발화만 추출해 재구성.
    문장 단위로 쪼개려면 split_sentences=True.

    Returns:
        split_sentences=False: 재구성된 전체 문자열 (공백 하나로 연결).
        split_sentences=True: (전체문자열, 문장리스트).
    """
    lines = transcript_raw.strip().split("\n")
    callee_parts: List[str] = []
    for line in lines:
        line = line.strip()
        if line.startswith("착신자:"):
            part = line[4:].strip()
            if part:
                callee_parts.append(part)
    callee_text = " ".join(callee_parts)

    if not split_sentences:
        return callee_text

    # 문장 경계: 마침표/물음표/느낌표 뒤 공백 또는 끝
    sentence_pattern = re.compile(r"[.!?]\s*|[.!?]$")
    sentences = [
        s.strip()
        for s in sentence_pattern.split(callee_text)
        if s and s.strip()
    ]
    if not sentences and callee_text:
        sentences = [callee_text]
    return callee_text, sentences


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _max_similarity_to_texts(
    embedding: List[float],
    ref_embeddings: List[List[float]],
) -> float:
    if not ref_embeddings:
        return 0.0
    return max(
        _cosine_similarity(embedding, ref) for ref in ref_embeddings
    )


def verify_extracted_items(
    extracted_items: List[Dict[str, Any]],
    transcript_reconstructed: str,
    embed_fn: Callable[[str], List[float]],
    *,
    threshold_grounding: float = 0.70,
    call_id: str = "",
    log_fn: Optional[Callable[..., None]] = None,
    transcript_sentences: Optional[List[str]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """
    추출 항목을 전사 재구성본과의 임베딩 유사도로 검증(의미 기반).
    threshold_grounding 이상이면 verified.

    Returns:
        (verified_items, stats) where stats has verified, skipped_halluc, skipped_quality.
    """
    log = log_fn or (lambda msg, **kw: _default_log("info", msg, **kw))
    stats = {"verified": 0, "skipped_halluc": 0, "skipped_quality": 0}

    log(
        "knowledge_stage3_start",
        call_id=call_id,
        item_count=len(extracted_items),
    )

    # 재구성 전사 임베딩: 문장 리스트가 있으면 문장별로, 없으면 전체 1개
    if transcript_sentences:
        ref_texts = transcript_sentences
    else:
        ref_texts = [transcript_reconstructed]
    try:
        ref_embeddings = [embed_fn(t) for t in ref_texts]
    except Exception as e:
        log(
            "knowledge_stage3_error",
            call_id=call_id,
            error=str(e),
            phase="embed_transcript",
        )
        return [], stats

    log(
        "knowledge_stage3_transcript_reconstructed",
        call_id=call_id,
        callee_text_length=len(transcript_reconstructed),
        ref_embed_count=len(ref_embeddings),
    )

    verified_items: List[Dict[str, Any]] = []
    for idx, item in enumerate(extracted_items):
        text = item.get("text") or ""
        text_preview = (text[:80] + "…") if len(text) > 80 else text
        try:
            emb = embed_fn(text)
        except Exception as e:
            log(
                "knowledge_stage3_verification_item",
                call_id=call_id,
                index=idx,
                text_preview=text_preview,
                error=str(e),
                verified=False,
            )
            stats["skipped_quality"] += 1
            continue

        sim = _max_similarity_to_texts(emb, ref_embeddings)
        verified = sim >= threshold_grounding

        log(
            "knowledge_stage3_verification_item",
            call_id=call_id,
            index=idx,
            text_preview=text_preview,
            similarity_max=round(sim, 4),
            threshold_grounding=threshold_grounding,
            verified=verified,
        )

        if verified:
            verified_items.append(item)
            stats["verified"] += 1
        else:
            stats["skipped_halluc"] += 1

    log(
        "knowledge_stage3_complete",
        call_id=call_id,
        verified=stats["verified"],
        skipped_halluc=stats["skipped_halluc"],
        skipped_quality=stats["skipped_quality"],
        skipped_dedup=0,
    )
    return verified_items, stats


def filter_duplicates_for_save(
    items: List[Dict[str, Any]],
    similarity_to_existing_fn: Callable[[str], float],
    *,
    threshold_dedup: float = 0.92,
    call_id: str = "",
    owner: str = "",
    log_fn: Optional[Callable[..., None]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """
    저장 후보 항목에 대해 기존 지식베이스와 유사도가 threshold_dedup 이상이면
    중복으로 보고 제외. 남은 항목만 반환.

    similarity_to_existing_fn(text) -> float: 해당 tenant의 기존 KB와의 최대 유사도.
    """
    log = log_fn or (lambda msg, **kw: _default_log("info", msg, **kw))
    to_store: List[Dict[str, Any]] = []
    skipped_dedup = 0

    log(
        "knowledge_stage4_start",
        call_id=call_id,
        candidate_count=len(items),
        owner=owner,
    )

    for idx, item in enumerate(items):
        text = item.get("text") or ""
        text_preview = (text[:80] + "…") if len(text) > 80 else text
        try:
            max_sim = similarity_to_existing_fn(text)
        except Exception as e:
            log(
                "knowledge_stage4_dedup_check",
                call_id=call_id,
                index=idx,
                text_preview=text_preview,
                error=str(e),
                skip_reason=None,
            )
            to_store.append(item)
            continue

        is_dup = max_sim >= threshold_dedup
        log(
            "knowledge_stage4_dedup_check",
            call_id=call_id,
            index=idx,
            text_preview=text_preview,
            max_similarity_existing=round(max_sim, 4),
            threshold_dedup=threshold_dedup,
            skip_reason="duplicate" if is_dup else None,
        )

        if is_dup:
            skipped_dedup += 1
            log(
                "knowledge_stage4_skip_duplicate",
                call_id=call_id,
                index=idx,
                text_preview=text_preview,
            )
        else:
            to_store.append(item)

    stats = {"stored_candidates": len(to_store), "skipped_dedup": skipped_dedup}
    log(
        "knowledge_stage4_complete",
        call_id=call_id,
        stored=len(to_store),
        skipped_dedup=skipped_dedup,
        failed=0,
    )
    return to_store, stats


def make_logger_json_event(logger_instance: logging.Logger) -> Callable[..., None]:
    """
    구조화 로그용: event와 키워드 인자를 JSON-like로 한 줄에 남기려면
    logger.info({"event": "knowledge_stage3_start", "call_id": "...", ...})
    형태로 남기도록 하는 log_fn을 반환.
    """
    def log_event(msg: str, **kwargs: Any) -> None:
        if isinstance(msg, str) and not kwargs:
            logger_instance.info(msg)
            return
        payload = {"event": msg, **kwargs} if kwargs else {"message": msg}
        logger_instance.info(payload)
    return log_event
