## 메타

- **작성일(로컬)**: 2026-04-21 17:55
- **상태**: 구현 완료
- **관련**: 예약 확인 STT, SIP MESSAGE AI 로그, 통화 종료 SMS·예약 API 정합

## 개요

예약 확인 짧은 발화(「네.」 등)가 `min_length`에 걸려 LLM에 도달하지 않던 문제를 STT 후처리 필터에서 완화했다. SIP MESSAGE AI 자동응답과 통화 종료 SMS의 주요 단계를 `app.log`에서 `event` 필드로 추적하기 쉽게 보강했다. 통화 종료 SMS는 `last_booking_api`로 예약 API 성공/실패를 명시해, 실패 시에도 AI 스니펫만으로 ‘예약 완료’로 쓰이지 않도록 프롬프트·폴백을 조정했다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----|-----|---|---|
| `sip-pbx/src/ai_voicebot/pipecat/stt_post_filter.py` | 수정 | 짧은 긍정 utterance는 `min_length`보다 먼저 통과, `allow_short_confirmations` 설정 | 설계대로 |
| `sip-pbx/src/ai_voicebot/langgraph/nodes/booking_agent.py` | 수정 | 예약 도구마다 `last_booking_api`(ok/detail) 기록, 실패 시 로그 | 설계대로 |
| `sip-pbx/src/services/end_call_sms_service.py` | 수정 | `[시스템 기록(예약 API)]` 블록·시스템 규칙·폴백·발송/LLM 로그에 `body_preview` | 설계대로 |
| `sip-pbx/src/services/sip_message_ai_reply.py` | 수정 | `event=sip_message_ai_reply`, task_start/done에 본문 미리보기, skip 경로 정리 | 설계대로 |
| `sip-pbx/src/sip_core/sip_endpoint.py` | 수정 | AI 자동응답 스케줄 시 `sip_message_ai_reply_scheduled` 로그 | 설계대로 |

## 주요 결정 사항

- **짧은 긍정**: 정규식·접두(네/예/응+진행 등)로 제한해 1~2글자 에코만 무제한 통과하지 않음.
- **SMS 진실 공급원**: `last_booking_api`가 있으면 LLM user 프롬프트에 반드시 포함; 실패 시 성공용 `[예약·변경 내용]` 블록은 비움.
- **레거시 체크포인트**: `last_booking_api` 없이 `last_action`만 있는 경우 기존 `_booking_section_from_context` 동작 유지.

## 잔여 과제

- 짧은 부정(「아니요」) 등은 길이 조건으로 이미 통과하는 경우가 많음. 모호한 한 음절만 추가 튜닝 시 별도 규칙 검토.
