## 메타

- 작성일: 2026-04-15
- 상태: 구현 완료
- 관련: `sip_message_inbound.py`, `sip_endpoint._handle_sip_message_method`

## 개요

웹 채팅 관리에 **깨진 문자(인코딩)** 와 **isComposing XML** 등 SIP 시그널링이 일반 메시지처럼 쌓이는 문제를 점검했다. 원인은 (1) 전체 datagram 을 UTF-8 문자열로만 쪼개 본문을 읽어 **Content-Type charset·message/CPIM** 이 반영되지 않은 점, (2) **RFC 3994 isComposing** 등을 `chat_messages`·`sip_message_received` 로 그대로보낸 점이다. **헤더/본문을 바이트로 분리**한 뒤 charset 으로 디코드하고, **CPIM 이면 내부 페이로드**만 채팅 문자열로 쓰며, 시그널링 Content-Type·XML 본문은 **DB/WS 저장을 생략**한다. 내선 릴레이는 기존처럼 **본문 바이트 → utf-8 surrogateescape** 로 복원한 문자열을 사용한다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----|-----|---|---|
| `sip-pbx/src/sip_core/sip_message_inbound.py` | 추가 | split 헤더/본문, charset·CPIM 파싱, 시그널링 판별 | |
| `sip-pbx/src/sip_core/sip_endpoint.py` | 수정 | MESSAGE 핸들러가 `bytes` 수신, 위 모듈로 채팅용 본문 결정 | |
| `sip-pbx/docs/reports/2026-04/2026-04-15_1845_CHAT_INBOUND_CHARSET_CPIM_SIGNAL_FILTER.md` | 추가 | 본 리포트 | |

## 주요 결정 사항

- **이미 DB에 들어간** 잘못된 행은 자동 삭제하지 않음 — 필요 시 운영자가 스레드별 정리 또는 SQL.
- IMDN·sipfrag·pidf 등도 채팅에서 제외해 UI 노이즈를 줄임.

## 잔여 과제 (선택)

- `message/cpim` 내부 `multipart/*` 는 미구현(드묾).
