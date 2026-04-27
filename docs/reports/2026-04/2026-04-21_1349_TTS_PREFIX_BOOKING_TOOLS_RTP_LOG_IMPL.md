## 메타

- **작성일(로컬)**: 2026-04-21 13:49
- **상태**: 구현 완료
- **관련 call 분석**: `sip-pbx/docs/reports/2026-04/2026-04-21_1130_CALL_26XDKYF0_ANALYSIS.md`

## 개요

통화 `26XdkYF0~t`에서 드러난 **예약 도구 재호출·로깅 예외**, **RTP 헬스 스냅샷 info 로그 과다**, **스트리밍 TTS 선행 안내구 반복**을 코드로 완화했다. `booking_tools`가 표준 `logging`에 `error=` 등 키워드를 넘기며 `Logger._log() got an unexpected keyword argument 'error'`가 발생한 뒤 `_execute_tool`이 이를 JSON 오류로 삼킨 것이 재예약 실패 로그의 직접 원인이었다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|------------|------|------|
| `sip-pbx/src/ai_voicebot/langgraph/tools/booking_tools.py` | 수정 | `structlog` 로거로 전환 + 멱등 시 `booking_idempotent_return` CDR | `error=` 등 키워드 로깅 안전 |
| `sip-pbx/src/services/booking_service.py` | 수정 | `structlog` 전환 + `create_booking` 중복 시 멱등 반환·슬롯 UPDATE 전 dup 검사 | LLM 재호출 시 슬롯 이중 증가 방지 |
| `sip-pbx/src/common/tts_streaming_chunk_dedupe.py` | 추가 | 스트리밍 TTS 청크 LCP·고정 안내구 dedupe | 턴당 1회 체감 |
| `sip-pbx/src/ai_voicebot/pipecat/processors/rag_processor.py` | 수정 | `dedupe_streaming_tts_chunks` 적용 | `len(chunks)>1`일 때만 |
| `sip-pbx/src/media/rtp_relay.py` | 수정 | `rtp_health_snapshot` 로그 레벨 `info`→`debug` | 운영 info 노이즈 감소 |

## 주요 결정 사항

1. **멱등 예약**: 동일 `owner`+`customer_phone`+슬롯(또는 동일 `slot_date`/`slot_time`)에 `confirmed`가 있으면 **INSERT·SMS·슬롯 증가 없이** 기존 예약 dict 반환. 재호출은 성공 JSON으로 떨어져 LLM 2라운드가 안정적으로 이어질 여지가 있다.
2. **TTS 프리픽스**: LLM이 청크마다 동일 접두를 붙이는 패턴에 대해 **최장 공통 접두어 제거 + 알려진 짧은 안내구** 제거를 조합(우연 일치 방지용 최소 LCP 길이 12).
3. **RTP 스냅샷**: 구조 점검용 이벤트는 **debug**에 두고, 별도 warning은 기존 경로 유지.

## Google Calendar refresh token (참고 링크)

- OAuth 2.0 웹 서버 앱 흐름 및 **authorization code**로 토큰 교환: [Using OAuth 2.0 to Access Google APIs](https://developers.google.com/identity/protocols/oauth2)
- 웹 서버 앱에서 **offline** 접근·**refresh_token** 수령: [OAuth 2.0 for Web Server Apps](https://developers.google.com/identity/protocols/oauth2/web-server) (문서 내 `access_type=offline`·토큰 응답 필드 설명 참고)
- 액세스 토큰 만료 시 **refresh_token**으로 갱신: [Refresh token / token endpoint](https://developers.google.com/identity/protocols/oauth2#5.-refresh-the-access-token-if-needed)

## 잔여 과제 → 후속 구현

- **(완료)** `MapComposite`/`Struct.extra_data`류: `booking_gemini_fc._sanitize_for_gemini_struct` 및 `ParseDict` 실패 fallback — 상세는 `2026-04-21_1448_BOOKING_GEMINI_STRUCT_STT_WATCHDOG_IMPL.md`.
- **(완료)** `stt_transcript_watchdog_alert`: `rtp_snapshot` 필드로 relay/pipecat 큐·bypass 통계 동시 기록 — 동일 파일 참고.

### 남김(선택)

- Struct fallback이 자주 뜨면 **도구 반환 JSON**에서 비표준 타입을 제거하는 쪽으로 근본 정리.
