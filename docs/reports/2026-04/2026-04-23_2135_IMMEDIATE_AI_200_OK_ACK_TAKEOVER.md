---
작성일: 2026-04-23
상태: 구현 완료
관련: `sip-pbx/docs/reports/2026-04/2026-04-23_2015_CALL_GQUBVGI090_IMMEDIATE_AI_SILENT_ROOT_CAUSE.md`
---

## 개요

`immediate_ai`(착신 INVITE 생략) 경로에서 **발신 INVITE에 대한 200 OK+SDP가 전송되지 않아** 단말이 미디어를 수립하지 못하던 문제를 수정했다. Early bind 이후 **무응답 AI와 동일한 SIP·RTP 처리**를 공용 메서드로 빼서, 즉시 응대 시에도 200 OK·ACK·`notify_call_established` 순서를 맞췄다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `sip-pbx/src/sip_core/sip_endpoint.py` | 수정 | `caller_200_ok_sent` 플래그, `_ai_takeover_send_200_ok_to_caller` 공용화, away 블록에서 200 OK 후 `handle_no_answer_timeout`, ACK 기반 인사; 5s ACK 폴백 | 설계대로 |
| `sip-pbx/docs/reports/2026-04/2026-04-23_2015_*.md` | — | 분석 문서는 참고만 | 코드는 본 리포트 시점 반영 |

## 주요 결정 사항

- **`ai_mode_activated`만으로 `_handle_no_answer_timeout`에서 조기 return 하던 로직 제거** — 실제로는 `caller_200_ok_sent`로 200 OK 멱등을 제어한다.
- **immediate_ai**: 링백 없음·착신 CANCEL 불필요 → `stop_ringback=False`, `send_cancel_to_callee=False`로 200 OK만 공용 경로 사용.
- **인사말 타이밍**: away 시 즉시 `notify_call_established` 호출을 제거하고, **`_handle_ack`의 AI 분기**에서만 set(표준 ACK 후 인사). 단말이 ACK를 보내지 않는 경우를 대비해 **5초 폴백**으로 동일 이벤트 set.
- **정리 시** `immediate_ai_ack_fallback_task` 취소.

## 잔여 과제 (선택)

- 착신 200 수립 시와 같이 **Session-Expires/UPDATE**를 immediate_ai 발신 다이얼로그에도 둘지 검토.
- ACK·200 OK 경쟁 시 `call_established` 이벤트 등록 타이밍 레이스는 기존 무응답 경로에도 잠재적 — 필요 시 `notify_call_established` 멱등·대기 큐 검토.
