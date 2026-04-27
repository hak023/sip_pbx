## 메타

- 작성일: 2026-04-14
- 상태: 완료
- 관련: Suno `generate-music` HTTP 500 `'NoneType' object has no attribute 'get'`

## 개요

Suno API가 HTTP 200이면서 JSON에 `"data": null` 등을 줄 수 있다. 기존 코드는 `task_id = data.get("data", {}).get("taskId")`처럼 **`dict.get("data", {})`가 키가 존재하고 값이 `null`이면 기본값 `{}`가 아니라 `None`을 반환**하는 Python 동작을 간과해 `None.get(...)`로 500이 났다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `sip-pbx/src/services/ringback_service.py` | 수정 | `_suno_inner_object` / `_suno_json_dict` 도입, `generate_suno_music`에서 안전 파싱·taskId 없으면 RuntimeError+로그 | 설계대로 |
| `sip-pbx/src/services/ringback_service.py` | 수정 | `poll_suno_task`의 `data` 목록 처리·JSON 파싱 예외 | `data: null` 등 |

## 주요 결정 사항

- `taskId`가 여전히 없으면 **502에 가까운 명시적 RuntimeError**로 메시지를 남기고 `suno_generate_no_task_id` 로그에 응답 프리뷰를 남긴다.
