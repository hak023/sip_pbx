"""
스트리밍 LLM 문장 청크를 TTS로 넘길 때, 동일한 리스너/안내 프리픽스가 청크마다 반복되는 현상을 완화한다.

- 청크 전체에 걸친 **최장 공통 접두어(LCP)** 가 충분히 길면 2번째 청크부터 제거한다.
- 이후에도 남는 고정 안내구(예: 네 고객님 / 잘 들립니다)는 2번째 청크부터 선행에서 반복 제거한다.
"""

from __future__ import annotations

# 길이 내림차순 — 긴 문구를 먼저 매칭
_KNOWN_LEADING_FILLERS: tuple[str, ...] = (
    "네, 고객님.",
    "잘 들립니다.",
    "네 고객님.",
    "잘 들립니다!",
    "네, 고객님",
    "잘 들립니다",
    "네 고객님",
)


def _longest_common_prefix(strings: list[str]) -> str:
    if not strings:
        return ""
    first = strings[0]
    if not first:
        return ""
    max_len = min(len(s) for s in strings)
    n = 0
    for i in range(max_len):
        ch = first[i]
        if not all(len(s) > i and s[i] == ch for s in strings[1:]):
            break
        n = i + 1
    return first[:n]


def _strip_known_fillers_from_start(text: str) -> str:
    s = text.lstrip()
    changed = True
    while changed and s:
        changed = False
        for phrase in _KNOWN_LEADING_FILLERS:
            if s.startswith(phrase):
                s = s[len(phrase) :].lstrip()
                changed = True
                break
    return s


def dedupe_streaming_tts_chunks(
    chunks: list[str],
    *,
    min_common_prefix_len: int = 12,
) -> list[str]:
    """
    스트리밍 TTS용 청크 리스트에서 턴당 1회만 들리도록 선행 반복을 제거한다.

    Args:
        chunks: 비어 있지 않은 문장/구간 문자열 목록
        min_common_prefix_len: LCP 적용 최소 길이(짧은 우연 일치 방지)
    """
    stripped = [c.strip() for c in chunks if c and c.strip()]
    if len(stripped) <= 1:
        return stripped

    common = _longest_common_prefix(stripped)
    if len(common) >= min_common_prefix_len:
        out: list[str] = [stripped[0]]
        for part in stripped[1:]:
            tail = part[len(common) :].lstrip() if part.startswith(common) else part
            out.append(tail)
        stripped = [p for p in out if p]

    if len(stripped) <= 1:
        return stripped

    out2: list[str] = [stripped[0]]
    for part in stripped[1:]:
        cleaned = _strip_known_fillers_from_start(part)
        if cleaned:
            out2.append(cleaned)
    return out2
