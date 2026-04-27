## 메타

- 작성일: 2026-04-21 (로컬), 갱신: 구현 반영
- 상태: 점검 문서 + **구현 반영됨** (즉시 확인 문자·종료 요약·용어 정리)
- 범위: 예약(create) 후 SIP MESSAGE(RCS) 발송, 통화 종료 요약, 용어

## 용어: 이 프로젝트에서 「RCS」

문서·채팅 API에서 **RCS**라고 하면 **이동통신사 단말의 네이티브 RCS(RCS Business Messaging API 등)** 가 아니라, **SIP `MESSAGE` 메서드로 보내는 단문(텍스트) 메시징**을 가리키는 경우가 많습니다.  
구현상 발송 경로는 `send_sip_sms_sync` / `POST /api/booking/sms/send` / `POST /api/chat/send` 등과 같이 **SIP 스택·REGISTER 매핑**을 전제로 합니다.  
**캐리어 RCS REST API**를 쓰려면 별도 게이트웨이 연동이 필요하며, 현재 예약 확인·종료 요약은 **SIP MESSAGE 기준**입니다.

## 개요 (점검 당시 → 현재)

| 항목 | 점검 당시 | 구현 후 |
|------|-----------|---------|
| create 직후 문자 | 없음 | `booking_notify.notify_booking_created_sms` — DB 커밋 후 SIP MESSAGE, `booking_confirmation_sms` 테이블로 idempotency |
| TTS와 문자 문구 | 도구 내 템플릿만 | `booking_confirmation_text.build_booking_confirmation_text` 단일 소스 + 예약 에이전트 프롬프트에 동일 문구 안내 |
| Pipecat 종료 요약 | 미호출 | `asyncio.create_task`로 `send_end_call_summary_sms_async` 백그라운드 실행 → `emit_call_ended` 즉시 |
| 종료 요약 내 예약 | `_langgraph_state` 미연동 | LangGraph `ConversationAgent._state["booking_context"]`에서 `last_action` / `last_booking` 읽어 `end_call_sms_service`에 전달 |
| 레거시 오케스트레이터 | 인라인 구현 | `end_call_sms_service.send_end_call_summary_sms` 위임 (`_langgraph_state` 있으면 계속 사용) |

## 현행 동작 정리 (구현 반영 후)

| 구간 | 동작 | 비고 |
|------|------|------|
| `booking_service.create_booking` | 커밋 후 즉시 SIP 확인 발송 시도 | `extra_config.notify_on_create_sms: false` 로 끔 |
| `cancel_booking` / `reschedule_booking` / `update_booking` | 성공 후 `notify_booking_lifecycle_sms` | 취소·일정변경 기본 발송 / **수정은** `notify_on_update_sms: true` 일 때만 |
| `_create_booking` / REST | `confirmation_message` + `confirmation_sms_sent` 등 | REST는 `BookingResponse` 필드만 반환 |
| `BOOKING_TOOLS` | `send_booking_sms` 미포함 유지 | 즉시·라이프사이클 발송은 서비스 레이어 |
| Pipecat 종료 | `create_task(send_end_call_summary_sms_async)` | `emit_call_ended` 블로킹 없음 |
| `extra_config.notify_channel` | `sip_message`(기본) 또는 `chat_api` | `chat_api` → `deliver_chat_sip_message` + `resolve_sip_from_for_outbound` |
| 레거시 `end_call` | `_send_end_call_sms` → 공통 서비스 | `conversation` assistant 발화 + `_langgraph_state` booking |

### `booking_settings.extra_config` 예시

| 키 | 기본 | 설명 |
|----|------|------|
| `notify_on_create_sms` | (미설정=발송) | `false` 이면 생성 확인 문자 안 보냄 |
| `notify_on_cancel_sms` | (미설정=발송) | `false` 이면 취소 문자 안 보냄 |
| `notify_on_reschedule_sms` | (미설정=발송) | `false` 이면 일정변경 문자 안 보냄 |
| `notify_on_update_sms` | **미설정=안 보냄** | `true` 일 때만 인원/메모 등 수정 문자 |
| `notify_channel` | `sip_message` | `chat_api` 이면 채팅 릴레이 경로(`chat_sip_delivery`) |

## 잔여 과제 (선택)

- `send_booking_sms` LLM 도구는 계속 비포함 권장(운영·보안). 재도입 시 별도 검토.  
- 생성 확인 문자 **수동 재발송 API**(실패 행 삭제 후 재호출)는 미구현.  
- 백그라운드 종료 SMS와 프로세스 종료 레이스 시 드물게 태스크 취소 가능 — 필요 시 `atexit`/shutdown 훅에서 대기.

## 관련 구현 리포트

- `sip-pbx/docs/reports/2026-04/2026-04-21_0945_BOOKING_SMS_RCS_IMPL.md` — 파일별 변경 요약
