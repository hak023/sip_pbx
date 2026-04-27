## 메타

- **작성일(로컬)**: 2026-04-21 11:23
- **상태**: 완료
- **관련 경로**: `sip-pbx/src/services/end_call_sms_service.py`, `sip-pbx/src/ai_voicebot/orchestrator/ai_orchestrator.py`

## 개요

통화 종료 후 LLM이 생성하는 요약이 과도하게 길어지는 문제를 줄이기 위해, 종료 SMS 작성 프롬프트와 아웃바운드 종료 요약 프롬프트를 **한 문장·공백 포함 최대 60자** 기준으로 조정했다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|------------|------|------|
| `sip-pbx/src/services/end_call_sms_service.py` | 수정 | 시스템·사용자 프롬프트에 통화 핵심 요약 60자 한 문장 규칙 명시, 폴백 요약 줄 60자 클램프 | 예약 블록은 별도 섹션으로 유지 |
| `sip-pbx/src/ai_voicebot/orchestrator/ai_orchestrator.py` | 수정 | 아웃바운드 종료 요약: 프롬프트 60자 한 문장 + 결과 60자 하드 클램프 | 레거시 오케스트레이터 경로 |

## 주요 결정 사항

- 종료 SMS는 인사·요약·(선택)예약·고정 마무리로 구성되므로, **60자 제한은「통화 핵심 요약」문장에만** 적용하고 예약 텍스트는 기존 `_booking_section_from_context` 그대로 둠.
- 아웃바운드 `OutboundCallResult.summary`는 단일 필드이므로 프롬프트와 출력 모두 60자로 제한.

## 잔여 과제 (선택)

- `generate_response`에 `max_tokens` 등을 넘길 수 있으면 종료 SMS LLM 호출 비용·지연을 추가로 줄일 수 있음(클라이언트 시그니처 확인 필요).
