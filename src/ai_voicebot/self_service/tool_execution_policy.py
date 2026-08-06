"""
외부 API Tool 실행 안전 정책 (Story 1.34, FR34-A).

실행 엔진 구현은 Story 1.35에서 진행하고, 이 모듈은 **정책 상수·검증 헬퍼**만 정의한다
(코드 실행 없는 설계 스파이크 산출물). 실제 HTTP 호출 로직은 이 파일에 없다.

보안 설계 원칙 (NFR9):
  - GET은 기본 능동(승인 불필요).
  - 쓰기 메서드(POST/PUT/PATCH/DELETE)는 테넌트가 PATCH /approve-methods 로 명시 승인한 것만 허용.
  - "제외 목록" 방식이 아니라 "화이트리스트" 방식 — 임의 외부 API는 신뢰도 미검증이므로 기본 거부.

Undo 설계 결론 (Story 1.34 스파이크):
  Story 1.17의 "old_value 재적용" 패턴은 자체 서비스 API에는 적합하지만 임의 외부 API에는
  적용 불가 — 외부 API의 이전 상태가 DB에 없기 때문이다. 따라서:
  1. 실행 전 GET으로 현재 상태 스냅샷을 `tool_execution_log.pre_state_json`에 저장한다.
  2. 사용자가 undo 요청 시, 해당 리소스에 pre_state_json을 본문으로 쓰기(PUT/PATCH) 역호출한다.
  3. 역호출이 지원 안 되거나 실패하면 `undo_ok=0`으로 기록하고 관리자에게 수동 복원 안내.

실패 처리 정책:
  - 4xx: 사용자에게 HTTP 상태+응답 본문 그대로 전달(묵살 금지).
  - 5xx/타임아웃: 최대 1회 재시도(지연 1s). 재시도 후에도 실패하면 "외부 서버 오류"로 안내.
  - 실행 자체가 권한 없음(미승인 메서드)이면 재시도 없이 즉시 거부.
"""

from __future__ import annotations

from typing import List

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

ALLOWED_WRITE_METHODS: frozenset = frozenset({"POST", "PUT", "PATCH", "DELETE"})
DEFAULT_TIMEOUT_SEC: float = 10.0
MAX_RETRIES_ON_5XX: int = 1
RETRY_DELAY_SEC: float = 1.0

# 사용자에게 노출할 실패 안내 문구 원칙(LLM 프롬프트 삽입용 — Story 1.35에서 사용)
FAILURE_HINT_PERMISSION_DENIED = (
    "이 API 메서드({method})는 아직 승인되지 않았습니다. "
    "지식 업로드 화면에서 해당 메서드를 승인한 뒤 다시 시도해 주세요."
)
FAILURE_HINT_CLIENT_ERROR = (
    "API 요청이 거부되었습니다(HTTP {status}). 입력값을 다시 확인해 주세요: {detail}"
)
FAILURE_HINT_SERVER_ERROR = (
    "외부 서버에서 오류가 발생했습니다(HTTP {status}). 잠시 후 다시 시도하거나 서비스 관리자에게 문의해 주세요."
)
FAILURE_HINT_TIMEOUT = (
    "외부 API 응답 시간이 초과되었습니다. 네트워크 상태를 확인하거나 잠시 후 다시 시도해 주세요."
)
FAILURE_HINT_UNDO_UNAVAILABLE = (
    "이전 상태로 되돌리지 못했습니다. 직접 수동으로 복원이 필요할 수 있습니다."
)


# ---------------------------------------------------------------------------
# 헬퍼 — 승인 검사(실제 HTTP 호출 없음)
# ---------------------------------------------------------------------------

def is_method_approved(method: str, approved_methods: List[str]) -> bool:
    """HTTP 메서드가 해당 문서의 승인 목록에 있는지 검사한다(대소문자 무시).

    GET은 항상 True — 별도 승인 없이 기본 능동.
    """
    m = method.upper()
    if m == "GET":
        return True
    return m in {a.upper() for a in approved_methods}


def validate_execution_request(
    *,
    method: str,
    approved_methods: List[str],
) -> tuple[bool, str]:
    """실행 요청의 정책 적합성을 검사한다. (ok, 실패 사유)를 반환한다.

    실패 시 반환되는 사유 문자열은 LLM 응답/사용자 안내에 직접 사용된다.
    """
    m = method.upper()
    if m not in ALLOWED_WRITE_METHODS and m != "GET":
        return False, f"지원하지 않는 HTTP 메서드입니다: {m}"
    if not is_method_approved(m, approved_methods):
        return False, FAILURE_HINT_PERMISSION_DENIED.format(method=m)
    return True, ""
