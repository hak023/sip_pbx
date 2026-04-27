## 메타

- 작성일: 2026-04-21 (로컬)
- 상태: 구현 완료
- 선행 점검: `2026-04-21_0938_BOOKING_POST_CREATE_SMS_RCS_AUDIT.md`

## 개요

예약 생성 직후 **SIP MESSAGE** 확인 발송, TTS와 동일 확정 문구 공유, Pipecat·레거시 통화 종료 **요약 SIP MESSAGE**에 LangGraph `booking_context` 반영.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 |
|-----------|------------|------|
| `src/services/booking_confirmation_text.py` | 추가 | `build_booking_confirmation_text` — 템플릿 단일 소스 |
| `src/services/booking_notify.py` | 추가 | `notify_booking_created_sms`, idempotency 테이블 `booking_confirmation_sms` |
| `src/services/end_call_sms_service.py` | 추가 | `send_end_call_summary_sms` — KB 인사·LLM 요약·예약 블록·발송 |
| `src/services/booking_service.py` | 수정 | `create_booking` 성공 후 notify, `confirmation_sms_*` 키 병합 |
| `src/ai_voicebot/langgraph/tools/booking_tools.py` | 수정 | 공통 문구·tool JSON에 `confirmation_sms_*` |
| `src/api/routers/booking.py` | 수정 | REST 응답에서 비모델 필드 제거 |
| `src/ai_voicebot/orchestrator/ai_orchestrator.py` | 수정 | `_send_end_call_sms` → 공통 서비스 위임 |
| `src/ai_voicebot/pipecat/processors/rag_processor.py` | 수정 | `send_end_call_summary_sms_async` |
| `src/ai_voicebot/pipecat/pipeline_builder.py` | 수정 | `caller_id` 주입, 종료 시 요약 SMS await |
| `src/ai_voicebot/langgraph/nodes/booking_agent.py` | 수정 | 프롬프트: `confirmation_message` = SIP 확인 문자 동일 문구 |
| `docs/reports/2026-04/2026-04-21_0938_...AUDIT.md` | 수정 | RCS 용어·잔여 과제·구현 반영 표 |

## 주요 결정 사항

- RCS(문서 용어) = **SIP MESSAGE**; 캐리어 RCS API와 구분해 감사 문서에 명시.
- 즉시 확인은 **LLM 비의존**(서비스 레이어).
- `extra_config.notify_on_create_sms: false` 로 테넌트 단위 끄기.

## 잔여 과제

- (이전) 취소·변경 알림·종료 SMS 비동기·재시도·채널 분기 → **2026-04-21 추가 반영** (`booking_notify` 확장, `pipeline_builder` `create_task`).
- 생성 확인 **수동 재발송 API**·프로세스 shutdown 시 백그라운드 SMS 대기는 미구현.

---

## 2026-04-21 추가 (감사 잔여 1~4)

| 파일 | 요약 |
|------|------|
| `src/services/booking_notify.py` | `notify_channel`(`sip_message`/`chat_api`), `_deliver_booking_text`, 생성 idempotency는 **sent**만 차단·실패 행 삭제 후 재시도, `notify_booking_lifecycle_sms`(cancel/reschedule/update) |
| `src/services/booking_service.py` | `cancel_booking` / `reschedule_booking` / `update_booking` 훅 |
| `src/ai_voicebot/pipecat/pipeline_builder.py` | 종료 요약 SMS `asyncio.create_task` (최대 120s 내부 타임아웃) |
| `docs/reports/...0938...AUDIT.md` | 잔여 1~4 반영·`extra_config` 표 갱신 |
