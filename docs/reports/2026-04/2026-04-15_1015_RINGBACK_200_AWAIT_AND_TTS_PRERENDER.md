## 메타

- 작성일: 2026-04-15 (로컬)
- 상태: 구현 반영
- 관련: `SIPEndpoint` 링백 정지, `resolve_ringback_segment`, `render_ringback_assignment_tts_wav`, `RingbackPlayer`

## 개요

1. **실제 통화로(발신자 INVITE 200 OK)가 열리기 전**에 재생 중인 ringback이 끊기도록, B2BUA가 발신자에게 200을 보내는 경로를 재점검하고 **`await _stop_ringback_player`** 로 순서를 보장했다.  
2. 통화 연결음 **TTS(스케줄 할당)** 는 링 중 실시간 스트리밍이 아니라, **설정 저장 시 WAV 파일을 생성**해 두고 링에서는 **그 파일만** 디코드·루프 송신하도록 변경했다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 |
|-----------|------------|------|
| `sip-pbx/src/sip_core/sip_endpoint.py` | 수정 | 착신 200 릴레이·AI takeover 200 전 `create_task` → `await _stop_ringback_player` |
| `sip-pbx/src/call_control/db.py` | 수정 | `tts_audio_path` 컬럼·INSERT/UPDATE·마이그레이션 |
| `sip-pbx/src/call_control/models.py` | 수정 | 할당 모델에 `tts_audio_path` |
| `sip-pbx/src/services/ringback_service.py` | 수정 | `render_ringback_assignment_tts_wav`, TTS 할당은 WAV 파일만 `resolve` |
| `sip-pbx/src/sip_core/ringback_player.py` | 수정 | 통화 연결음 구간은 파일만; FFmpeg 디코드 경로를 WAV·MP3 공통 `_decode_media_to_pcm16k` |
| `sip-pbx/src/api/routers/call_control_api.py` | 수정 | TTS 저장 시 백그라운드 렌더; Suno 전환 시 `tts_audio_path` 클리어 |
| `sip-pbx/frontend/app/settings/call-control/page.tsx` | 수정 | TTS 안내·요약·`tts_audio_path` API 반영 |
| `sip-pbx/docs/reports/2026-04/2026-04-14_2110_RINGBACK_RUNTIME_AUDIT_AND_FIX.md` | 수정 | 잔여 과제 → 후속 점검 결과 반영 |

## 주요 결정 사항

- **인사말(`enabled_greeting`)** 은 기존처럼 링 단계에서 Google TTS 스트림 1회 — 요청 범위는 «통화 연결음» TTS 할당에 한함.  
- TTS WAV는 `TTSClient.synthesize` (LINEAR16 16k mono) → 표준 `wave` 로 저장; 재생 시 FFmpeg로 PCM 변환(환경에 pydub만 있어도 WAV는 FFmpeg 우선).  
- WAV 생성 전에는 해당 할당이 `resolve` 에서 선택되지 않아 **연결음 구간은 무음**일 수 있음 — 저장 직후 백그라운드 완료 시 다음 통화부터 적용.
