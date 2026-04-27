## 메타

- 작성일: 2026-04-15
- 상태: 구현 완료 (로그 점검 → 원인 수정)
- 관련: `sip_endpoint.py` `send_chat_sip_message`, `send_sip_message`, SIP MESSAGE 릴레이·IMDN

## 개요

`app.log`에서 `chat_sip_message_send_error`: `'utf-8' codec can't encode character '\\udc9c' in position 184: surrogates not allowed` 가 다수 발생했다. 수신 SIP MESSAGE 본문을 `surrogateescape`로 디코딩한 뒤 릴레이할 때, 송신 측이 `encode("utf-8", errors="surrogateescape")`를 사용해 서로게이트 코드포인트에서 인코딩이 실패한 것이 원인이다.

## 결론 (로그 해석)

1. **2558–2562**: 1003→1004 채팅 `안녕` 전송 후 15초 내 최종 SIP 응답 미수신 → `sip_timeout`으로 DB 저장은 진행.
2. **2563–2595**: 지연된 `200` 및 다수의 `MESSAGE` 수신(바이트 보존용 `surrogateescape` 디코딩 로그).
3. **2578–2596**: `message/imdn+xml`(전달/표시 알림) 릴레이 시작 — 본문에 비 UTF-8·깨진 시퀀스가 `surrogateescape`로 들어온 뒤 **문자열 전체를 다시 UTF-8 strict 계열로 인코딩**하면서 예외.
4. **2599–2618**: 동일 예외 반복 → `sip_message_relay_finished` `send_error`.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|------------|------|------|
| `src/sip_core/sip_endpoint.py` | 수정 | `send_chat_sip_message` / `send_sip_message`: 본문 `encode(..., surrogatepass)`, SIP 패킷은 `헤더 UTF-8` + `body_bytes` 결합 | surrogateescape로 encode 불가 |
| `src/sip_core/sip_endpoint.py` | 수정 | `_extract_top_via_branch`에는 헤더 문자열만 전달 | Via는 헤더에만 존재 |
| `src/sip_core/sip_endpoint.py` | 수정 | `chat_sip_message_body_encode` debug 로그(서로게이트 여부) | 점검용 |

## 주요 결정 사항

- Python 문서상 **decode의 `surrogateescape` ↔ encode의 `surrogatepass`** 조합으로 비 UTF-8 바이트 의미를 유지한 채 송신한다.
- 본문을 SIP f-string에 끼워 넣은 뒤 전체를 한 번에 인코딩하지 않고, **헤더와 본문 바이트를 분리**해 `Content-Length`와 실제 페이로드가 항상 일치하게 한다.

## 잔여 과제

- `send_chat_sip_message`의 `body.strip()`이 IMDN 등에서 본문 변형을 일으키는지 필요 시 별도 검토.
