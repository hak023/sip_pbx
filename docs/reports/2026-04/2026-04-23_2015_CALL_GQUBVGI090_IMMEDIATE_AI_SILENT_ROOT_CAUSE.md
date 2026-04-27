## 메타

- 작성일: 2026-04-23 (로컬)
- 상태: 점검 완료 (로그·코드 대조)
- call_id: `gqubvGI090` (1004 → 1003, immediate_ai)

## 개요

프론트·파이프라인·TTS·RTP 송신 로그는 정상인데 단말에서 묵음이었던 이유는, **착신 규칙 `immediate_ai` 처리 시 발신 INVITE에 대한 최종 응답(200 OK + SDP)이 생략**되어 단말이 세션 미디어를 수립하지 못한 것으로 해석된다. 동일 호에서 **발신 RTP 0패킷·STT 입력 0프레임**이 로그로 확정된다.

## 로그 근거 (`logs/app.log`)

| 관찰 | 의미 |
|------|------|
| `call_control_rule_resolved` … `action`: `immediate_ai` | 착신 제어 의도는 즉시 AI |
| `away_mode_skip_invite_to_callee` | callee INVITE 생략 (설계대로) |
| `rtp_first_packet_sent` … `dest_port`: 54151 | 서버는 TTS RTP를 발신 단말 주소로 전송 시도 |
| `pipecat_audio_stream_no_data` … `packets_consumed_so_far`: 0 (반복) | **발신→PBX RTP가 파이프라인에 들어오지 않음** |
| `stt_path_input_total` … `total_frames`: 0 | STT 경로 미가동 |
| `Empty buffer, skipping WAV save` … `caller.wav` | 녹음 기준 **caller 측 RTP 없음** |
| `rtp_relay_stopped` … `caller_audio_packets`: 0, `rtp_tts_packets_sent`: 1466 | **역방향 0, TTS 송신만** |
| 해당 구간에 `✅ [AI Takeover] 200 OK sent to caller` **없음** | 무응답 AI 터크오버의 200 OK 경로 미실행 |

## 코드 상관 (`sip_endpoint.py`)

1. `immediate_ai` 시 `_is_away_call` 로 callee INVITE를 건너뛴 뒤 `early_bind` 후 **`call_manager.handle_no_answer_timeout`** 만 호출된다 (Pipecat·TTS만 기동).
2. 발신자에게 **200 OK + caller leg RTP 포트가 담긴 SDP**를 보내는 블록은 **`_handle_no_answer_timeout`** (약 4446–4568행, `🔄 [AI Takeover] Sending 200 OK to caller`) 에만 있다.
3. `call_info` 에는 INVITE 처리 초기에 이미 `ai_mode_activated`: True 가 들어간다. 이후 `_handle_no_answer_timeout` 을 호출해도 **4311–4314행에서 `no_answer_timeout_already_ai_mode` 로 즉시 return** 하므로 200 OK는 보내지지 않는다.

즉 **immediate_ai 전용 경로는 “AI는 켜지만 SIP 응답으로 미디어 다이얼로그를 완료하지 않는” 상태**가 될 수 있다. 많은 UA는 200 OK/ACK 이후에만 수신 RTP를 재생하거나, 송신 RTP를 안정적으로 보내므로 **청각 묵음 + 역 RTP 0** 과 일치한다.

## 권장 수정 방향 (구현 시)

- `immediate_ai` / early bind 직후 **발신자에게 200 OK+SDP를 보내는 단계**를 `_handle_no_answer_timeout` 과 분리해 공용화하거나, away 전용으로 동일 SDP를 전송한다.
- `ai_mode_activated` 사전 설정과 `_handle_no_answer_timeout` 의 early return 조건을 정리해, **200 OK 미전송 상태**에서는 터크오버 로직이 빠지지 않도록 한다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|------------|------|------|
| (없음) | — | 분석·문서만 | 코드 수정은 후속 |
