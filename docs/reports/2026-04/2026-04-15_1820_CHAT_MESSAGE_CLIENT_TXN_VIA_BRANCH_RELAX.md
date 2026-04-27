## 메타

- 작성일: 2026-04-15
- 상태: 구현 완료
- 관련: `sip_endpoint.py` MESSAGE 클라이언트 txn, `chat.py` API 응답

## 개요

테넌트 간 웹 채팅(SIP MESSAGE)에서 수신 단말(1004)에는 도착하지만 발신 웹(1003)은 전송 실패로 보이고 발신 말풍선이 기대와 어긋나는 현상을 점검했다. 원인으로 **200 OK 가 도착해도 요청과 응답의 최상단 Via `branch` 불일치 시 클라이언트 txn 을 완료하지 않아** 타임아웃·`success: false` 가 나는 경로를 확인하고, **Call-ID 매칭 시 branch 불일치를 무시**하도록 완화했다. 타임아웃 상한을 15초로 늘리고, `sip_timeout` 시 API `detail` 에 사용자 안내 문구를 덧붙였다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----|-----|---|---|
| `sip-pbx/src/sip_core/sip_endpoint.py` | 수정 | `_complete_chat_message_client_txn`: Via branch 불일치 시 `return False` 제거, `info` 로그 유지 | 설계대로 |
| `sip-pbx/src/sip_core/sip_endpoint.py` | 수정 | `_chat_message_txn_timeout_sec` 8→15, 주석 보강 | 트레이드오프: 대기 시간 증가 |
| `sip-pbx/src/api/routers/chat.py` | 수정 | `sip_timeout` 시 `detail` 에 “상대에 이미 전달됐을 수 있음” 안내 | UX |
| `sip-pbx/docs/reports/2026-04/2026-04-15_1820_CHAT_MESSAGE_CLIENT_TXN_VIA_BRANCH_RELAX.md` | 추가 | 본 리포트 | — |

## 주요 결정 사항

- RFC 관점에서 Via branch 는 엄격히 매칭하는 편이 맞지만, **채팅용 단발 MESSAGE** 에서는 Call-ID 가 txn 당 유일하고, 일부 UA 가 200 OK 의 최상단 Via 를 재작성하는 경우가 있어 **branch 불일치만으로 완료를 거부하면 UDP 전송 성공과 API 실패가 어긋난다**.
- 타임아웃을 소폭 상향해 느린 UA·네트워크에서도 여지를 두었다.

## 잔여 과제 (선택)

- 동일 Call-ID 를 쓰는 다른 다이얼로그와의 이론적 충돌은 현재 설계(채팅 전용 pending)에서는 낮음. 필요 시 CSeq·Method 로 이중 검증 가능.
