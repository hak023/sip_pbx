## 메타

- **작성일(로컬)**: 2026-04-15 13:52
- **상태**: 수정 완료
- **관련 경로**: `sip-pbx/src/api/routers/call_control_api.py`

## 개요

임베디드/스레드 API Gateway 기동 시 `AssertionError: Status code 204 must not have a response body`로 앱 import가 실패했다. 원인은 `DELETE .../forward-targets/{id}` 핸들러의 반환 타입 `-> None`이 FastAPI에 JSON 본문(null) 응답으로 해석되어, HTTP 204와 충돌한 것이다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `sip-pbx/src/api/routers/call_control_api.py` | 수정 | `delete_forward_target`에서 `-> None` 제거 | 다른 204 DELETE와 동일 패턴 |

## 주요 결정 사항

- 204 No Content 라우트는 반환 타입으로 `None`을 명시하지 않거나, 명시적으로 `Response`만 반환한다.

## 잔여 과제

- 없음.
