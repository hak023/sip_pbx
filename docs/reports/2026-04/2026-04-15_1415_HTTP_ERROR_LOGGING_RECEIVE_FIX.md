## 메타

- **작성일(로컬)**: 2026-04-15
- **상태**: 수정 완료
- **관련 경로**: `sip-pbx/src/api/http_error_logging.py`

## 개요

요청 본문 로깅용 미들웨어가 `request._receive`를 «본문 한 덩어리만 반복 반환»하는 함수로 바꿔, 응답 처리 중 Starlette가 `listen_for_disconnect`로 `receive()`를 추가 호출할 때 `http.request`가 다시 나와 `RuntimeError: Unexpected message received: http.request`가 발생했다. 로그인(`POST /api/auth/login`) 직후 등에서 ASGI 예외가 났다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `sip-pbx/src/api/http_error_logging.py` | 수정 | `receive` 재주입 제거; `await request.body()` 만으로 캐시·미리보기 | Starlette 본문 캐시 활용 |

## 주요 결정 사항

- `await request.body()`는 동일 `Request`에서 이후 호출도 캐시된 바이트를 반환하므로, `receive`를 덮어쓸 필요가 없다.

## 잔여 과제

- 없음.
