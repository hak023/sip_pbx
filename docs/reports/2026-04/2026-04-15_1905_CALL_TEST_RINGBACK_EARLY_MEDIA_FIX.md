## 메타

- 작성일: 2026-04-15
- 상태: 구현 완료
- 관련: `app.log` xegCPIaND9 구간(1004→1003, no_answer_ai 10s), 링백·TTS 경고

## 개요

호 테스트 로그(17:22:35~49)를 보면 **no_answer_timeout(10s) 후 AI 인수**까지 진행되었으나 **`ringback_player_attached` / `ringback_player_started` 로그가 전혀 없음** — `_start_ringback_player` 가 `ringback_settings` 행 부재 또는 `enabled_greeting`/`enabled_ringback` 미활성으로 **무로그 종료**했을 가능성이 큼. 별도로 `RingbackPlayer._play_mp3_loop` 에서 **`send_ai_audio` 가 짧은(패딩) 청크일 때만 호출**되는 들여쓰기 버그로, 통화연결음 PCM 이 사실상 송신되지 않았을 수 있다. 또한 **`send_ai_audio` 가 callee 소켓을 우선** 사용해 SDP 의 caller leg 와 불일치할 수 있고, **착신 180 이 SDP 없이** 오면 발신 단말이 early RTP 를 열지 않아 무음이 된다. 위를 코드로 보완했다.

## 로그에서 확인된 기타 이슈 (코드 미변경)

- **`tts_rtp_duration_mismatch`**: Notifier vs Output 오디오 프레임 수 불일치 — 파이프라인/EndFrame 타이밍 추적용 경고.
- **`pcm_chunk_gap_large`**: Google TTS API 지연으로 큐 간격 확대.
- **`phase1_duration_short_possible_interrupt`**: Phase1 예상 재생 대비 짧음 경고.
- **`org_manager_tenant_config_not_found` (1003)**: VectorDB `tenant_config` 없음 — 기본값 사용.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----|-----|---|---|
| `sip-pbx/src/sip_core/ringback_player.py` | 수정 | `_play_mp3_loop`: 매 20ms 청크마다 `send_ai_audio` 호출 | 버그 수정 |
| `sip-pbx/src/media/rtp_relay.py` | 수정 | `ringback_early_media=True` 일 때 **caller** 트랜스포트 우선 | SDP 정합 |
| `sip-pbx/src/sip_core/sip_endpoint.py` | 수정 | `_start_ringback_player` 스킵 시 `ringback_start_skipped` 로그 | 가시성 |
| `sip-pbx/src/sip_core/sip_endpoint.py` | 추가 | `_caller_early_media_sdp_for_1xx` + 180/183 무본문 시 SDP 주입 | early media |
| `sip-pbx/docs/reports/2026-04/2026-04-15_1905_CALL_TEST_RINGBACK_EARLY_MEDIA_FIX.md` | 추가 | 본 리포트 | |

## 주요 결정 사항

- 주입 SDP 는 **PCMU/8000** 기준 최소 본문(Direct 모드에서는 생략).
- 링백 사용 시 DB `ringback_settings` 에 해당 **owner(착신 내선)** 행과 **`enabled_ringback` 또는 `enabled_greeting`** 이 켜져 있어야 플레이어가 붙는다.

## 잔여 과제 (선택)

- 발신 코덱이 PCMA 단독인 경우 주입 SDP 의 RTP/AVP 목록 확장.
- `tenant_config` 시드로 경고 제거.
