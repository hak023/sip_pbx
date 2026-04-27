## 메타

- 작성일: 2026-04-14 (로컬)
- 상태: 점검 완료 + 코드 수정 반영
- 관련: `RingbackPlayer`, `RTPRelayWorker.send_ai_audio`, `SIPEndpoint` B2BUA INVITE/200

## 개요

통화 연결음이 **착신 링 구간에 발신자에게 RTP로 재생**되는지,**리스트(포지션) 순서**로 스케줄 할당이 고르는지,**200 OK 이후 연결음 중단**되는지 점검했다. 점검 중 **링백 PCM이 `send_ai_audio`에서 `ai_mode=False` 때문에 전송되지 않는 결함**을 확인하여 수정했다.

## 점검 결과 요약

| 항목 | 기대 동작 | 점검 결과 |
|------|-----------|-----------|
| 링 시 발신자 재생 | Early bind 후 `RingbackPlayer`가 `send_ai_audio`로 Caller RTP | **결함**: `send_ai_audio`가 `ai_mode` 필수라 링 단계에서는 무송신 → **`ringback_early_media=True`로 우회** |
| 리스트 순서 | `position ASC`로 첫 매칭 할당 사용 | **정상**: `list_ringback_schedule_assignments` + `resolve_ringback_segment` 순회 |
| owner | 착신 내선별 `ringback_settings`/할당 | **개선**: `_start_ringback_player`에 **`callee_username`** 전달(기존 `_resolve_owner()`는 단일 테넌트에 편향될 수 있음) |
| 200 OK 후 정지 | 착신 200 relay 직전 `_stop_ringback_player` | **정상**: `_handle_sip_response` callee INVITE 200 경로 |
| AI 전환 시 정지 | takeover 시 `_stop_ringback_player` | **정상**: `_handle_no_answer_timeout` 경로 |

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 |
|-----------|------------|------|
| `sip-pbx/src/media/rtp_relay.py` | 수정 | `send_ai_audio(..., *, ringback_early_media=False)` — True 시 `ai_mode` 생략 |
| `sip-pbx/src/sip_core/ringback_player.py` | 수정 | 링백 TTS/MP3 루프에서 `ringback_early_media=True` 로 송신 |
| `sip-pbx/src/sip_core/sip_endpoint.py` | 수정 | `_start_ringback_player(..., owner=callee_username)` |

## 주요 결정 사항

- 링백은 **AI 파이프라인과 별개 early media**이므로, RTP 송신 경로만 공유하고 `ai_mode`에 묶이지 않는다.
- `priority` 컬럼은 제거되었고, 평가 순서는 **`position` 오름차순**이 맞다(문서·UI에서 priority라 부르던 것과 동일 역할).

## 후속 점검 (200 OK · B2BUA 발신 200)

발신자(UAC)가 받는 **INVITE 200 OK**는 아래 두 경로뿐이며, 둘 다 `_stop_ringback_player`가 **전송 직전에 `await`** 되도록 정리됨(2026-04-15).

| 경로 | 설명 | ringback 정지 |
|------|------|----------------|
| 착신 응답 릴레이 | Callee → B2BUA `200 INVITE` 수신 → `_relay_response_to_caller` 로 발신자에게 전달 | `_handle_sip_response`에서 `await _stop_ringback_player(original_call_id)` 후 세션 타이머·릴레이 |
| AI 무응답 전환 | `_handle_no_answer_timeout`에서 발신자용 200 SDP 조립·전송 | 동일 함수에서 `await _stop_ringback_player(call_id)` 후 200 전송 |

그 외 `caller_addr`로 나가는 200은 **BYE/CANCEL/OPTIONS/REGISTER/SIP MESSAGE** 응답뿐이라 링백과 무관.

통화 연결음 **TTS(할당)** 는 설정 저장 시 WAV 사전 생성 후 링에서 파일만 루프 재생으로 변경 — 상세는 `sip-pbx/docs/reports/2026-04/2026-04-15_1015_RINGBACK_200_AWAIT_AND_TTS_PRERENDER.md`.
