## 개요

SIP UDP datagram 수신 시 UTF-8 디코딩 실패 시 **latin-1 폴백**을 제거하고, **`utf-8` + `errors="surrogateescape"`** 로 바꿔 로그·터미널 깨짐을 줄이면서 바이너리 본문(gzip `message/imdn+xml` 등) 바이트를 릴레이 시 보존한다. 채팅 DB는 내선 간 MESSAGE에 대해 **착신 owner inbound** 저장에 더해 **발신 owner outbound 미러**를 추가해, owner(예: 1003)으로 조회 시 소프트폰과 같이 송·수신 이력이 모두 보이게 한다.

**작성일:** 2026-04-15 (로컬)  
**관련:** `sip-pbx/src/sip_core/sip_endpoint.py`, `sip-pbx/src/services/chat_service.py`

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|------------|------|------|
| `sip-pbx/src/sip_core/sip_endpoint.py` | 수정 | 수신 디코딩: latin-1 → utf-8 surrogateescape; MESSAGE DB 이중 저장; MESSAGE 송신 encode 동일 | 설계대로 |
| `sip-pbx/src/services/chat_service.py` | 수정 | 모듈 docstring에 미러 저장 정책 설명 | 설계대로 |

## 주요 결정 사항

- **surrogateescape:** 잘못된 UTF-8 바이트를 surrogate로 올려 문자열로 파싱한 뒤, 송신 시 `encode(..., errors="surrogateescape")`로 원 바이트 복원 가능.
- **이중 저장:** 기존은 `owner=착신 resolve(To)` 만 저장해 발신자 owner로 `get_threads` 시 내가 보낸 줄이 없었음. 발신 측 `owner=resolve(From)`, `thread_id=To`, `direction=outbound` 1건 추가.

## 잔여 과제

- IMDN gzip 본문을 XML 텍스트로 풀어 DB·로그에 넣기(선택).
- latin-1 시대에만 저장된 과거 행은 미러가 없을 수 있음 — 필요 시 배치 보정.
