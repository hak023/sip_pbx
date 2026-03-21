"""
STT 후처리 필터 (짧은/불완전/감탄만 발화 스킵).

RAGLLMProcessor에서 사용. 설계: STT_ADDITIONAL_CONSIDERATIONS.md §6.
- from_config(config) -> 인스턴스
- filter(text) -> (should_use: bool, filter_reason: Optional[str])
"""

from typing import Any, Dict, Optional, Tuple


class STTPostFilter:
    """
    STT 최종 결과가 LLM으로 넘어가도 되는지 판단.
    짧은 발화, 감탄사만, 불완전 문장 등은 스킵할 수 있음.
    """

    def __init__(
        self,
        *,
        min_length: int = 0,
        drop_only_reactions: bool = False,
        blocklist: Optional[list] = None,
    ):
        self.min_length = min_length
        self.drop_only_reactions = drop_only_reactions
        # 기본 에코 차단: TTS 에코가 STT에서 흔히 인식되는 영어 조각 (ko-KR 설정 시)
        _default_echo_blocklist = [
            "oh", "oh,", "oh.", "you", "you.", "you,", "here", "here,", "here you",
            "here, you", "to", "to.", "know", "know.", "no", "no.", "welcome", "welcome.",
        ]
        user_list = [s.strip().lower() for s in (blocklist or []) if s]
        self.blocklist = list(dict.fromkeys(_default_echo_blocklist + user_list))

    @classmethod
    def from_config(cls, config: Optional[Dict[str, Any]] = None) -> "STTPostFilter":
        if not config:
            return cls(min_length=3)  # 기본: 3자 미만 에코 조각 차단
        return cls(
            min_length=int(config.get("min_length", 3)),
            drop_only_reactions=bool(config.get("drop_only_reactions", False)),
            blocklist=config.get("blocklist"),
        )

    def filter(self, text: str) -> Tuple[bool, Optional[str]]:
        """
        Returns:
            (should_use, filter_reason). should_use=True 이면 LLM으로 전달.
        """
        if not text or not text.strip():
            return False, "empty"
        t = text.strip()
        if len(t) < self.min_length:
            return False, "too_short"
        lower = t.lower()
        if self.blocklist and lower in self.blocklist:
            return False, "blocklist"
        if self.drop_only_reactions and self._is_only_reaction(t):
            return False, "reaction_only"
        return True, None

    def _is_only_reaction(self, text: str) -> bool:
        """감탄·짧은 반응만 있는지 (간단 휴리스틱)."""
        t = text.strip().lower()
        if len(t) <= 2:
            return True
        reactions = {
            "네", "응", "어", "음", "아", "오", "에", "네에", "아니", "글쎄",
            "좋아", "됐어", "고마워", "감사", "알겠", "ㅇㅇ", "ㄴㄴ",
        }
        return t in reactions
