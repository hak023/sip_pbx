"""
Smart Turn stop 전략 관측 래퍼 (Story 7.1 Task 4).

`pipeline_builder.py`가 pipecat의 `UserTurnStrategies(start=[...])`를 만들 때 `stop=`을
지정하지 않으면 pipecat 기본값(`TurnAnalyzerUserTurnStopStrategy(LocalSmartTurnAnalyzerV3())`,
즉 Smart Turn v3.2 문법/억양/속도 기반 발화완료 모델)이 암묵적으로 적용된다는 사실을
Story 7.1에서 실제 실행으로 확인했다.

본 모듈은 그 기본값과 **완전히 동일한 전략 인스턴스**를 명시적으로 생성하고, 순수 관측용
이벤트 핸들러(`on_user_turn_stopped`)만 추가한다 — 판단 로직(`process_frame`,
`_maybe_trigger_user_turn_stopped` 등)은 단 한 줄도 오버라이드하지 않는다. pipecat의
`BaseObject.add_event_handler()`는 동일 이벤트에 여러 핸들러를 등록할 수 있고 각 핸들러는
독립적으로 실행되므로, 이 관측 핸들러를 추가해도 기존 turn-stop 동작(사용자 턴 종료 트리거)에는
전혀 영향을 주지 않는다(회귀 위험 없음).

관측 목적: 사용자가 "말하다가 쉬었다가 다시 말하는" 경우에도 이 모델이 실제로 잘 판단하는지
(Epic 7, Story 7.2 설계 결정의 근거 데이터)를 실통화에서 파악하기 위함.
"""

import time
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


def build_observed_smart_turn_stop_strategy(*, call_id: str = "") -> Optional[Any]:
    """pipecat 기본값과 동일한 Smart Turn stop 전략을 생성하고 관측 로깅만 추가해 반환한다.

    실패(임포트 실패, 모델 로드 실패 등) 시 None을 반환한다 — 호출부는 None이면 pipecat 기본값
    (stop 미지정)으로 폴백해야 한다(기존 동작과 동일 보장).
    """
    try:
        from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import (
            LocalSmartTurnAnalyzerV3,
        )
        from pipecat.turns.user_stop.turn_analyzer_user_turn_stop_strategy import (
            TurnAnalyzerUserTurnStopStrategy,
        )
    except ImportError as e:
        logger.debug("smart_turn_stop_observer_import_failed", error=str(e))
        return None

    try:
        strategy = TurnAnalyzerUserTurnStopStrategy(turn_analyzer=LocalSmartTurnAnalyzerV3())
    except Exception as e:
        logger.warning("smart_turn_stop_strategy_build_failed", error=str(e), call_id=call_id)
        return None

    async def _on_user_turn_stopped(*args, **kwargs) -> None:
        logger.info(
            "smart_turn_stop_triggered",
            call=True,
            call_id=call_id or "",
            category="timing",
            progress="timing",
            triggered_at_mono=round(time.monotonic(), 4),
            note=(
                "Story 7.1 관측 로깅 — Smart Turn v3.2 stop 전략이 실제로 발화 종료를 확정한 "
                "시점(판단 로직 변경 없음, 순수 관측용). 이후 짧은 시간 내 stt_turn_superseded가 "
                "발생하면 '일시 정지를 종료로 오인'했을 가능성이 있는 사례로 간주해 분석한다."
            ),
        )

    try:
        strategy.add_event_handler("on_user_turn_stopped", _on_user_turn_stopped)
    except Exception as e:
        # 이벤트 핸들러 등록 실패는 관측 기능 상실일 뿐 판단 로직에는 영향 없음 — 안전하게 계속 진행.
        logger.debug("smart_turn_stop_observer_handler_attach_failed", error=str(e), call_id=call_id)

    return strategy
