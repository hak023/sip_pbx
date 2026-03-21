# TTS → PCM 큐 → RTP 송출 점검 가이드

AI 응대 시 음성이 살짝씩 깨지는 현상이 있을 때, **TTS 생성 → PCM 큐 투입 → 20ms 간격 RTP 송출** 구간을 로그로 점검하는 방법입니다.

## 흐름 요약

1. **Pipecat Output** (`rtp_transport.py`): TTS가 내보낸 `TTSAudioRawFrame`(또는 `OutputAudioRawFrame`) → `send_audio_to_caller(pcm_data)` 호출
2. **RTP Relay** (`rtp_relay.py`): `send_audio_to_caller`가 PCM을 `_pipecat_pcm_queue`에 넣음 (maxsize=30 청크)
3. **송출 루프** `_pipecat_tts_sender_loop`: 큐에서 PCM을 꺼내 20ms 간격으로 RTP 패킷화·전송

끊김/깨짐이 나는 원인 후보:
- **큐 언더런**: TTS가 청크를 늦게 주면 송출 루프가 1초 타임아웃으로 대기 → 그 구간에 음성 끊김
- **큐 백로그**: TTS가 너무 빠르게 주면 큐가 가득 차서 드롭 → 음성 누락
- **20ms 간격 이탈**: 이벤트 루프 부하로 sleep이 늦게 끝나면 지터 → 깨짐
- **프레임 스킵**: TTS 오디오 프레임이 `TTSAudioRawFrame`이 아니어서 전송 스킵 → 누락

## 로그로 확인할 이벤트

`app.log`에서 아래 이벤트로 구간별로 점검하세요.

| event | 의미 | 조치 방향 |
|-------|------|-----------|
| `rtp_tts_queue_empty_timeout` | PCM 큐가 1초간 비어 있음. 해당 구간에 **끊김** 가능 | TTS가 청크를 더 자주/작게 주는지, 인사말/Phase 전환 구간에서 지연이 있는지 확인 |
| `rtp_tts_sender_resumed_after_empty` | 비어 있다가 새 청크 수신. 직전 구간에서 **끊김** 있었을 수 있음 | `empty_timeout_count`와 함께 빈도 확인 |
| `rtp_tts_queue_depleted` | 송출 중 PCM 큐가 0이 됨. 다음 청크가 늦으면 **끊김** | TTS 스트리밍 지연, 파이프라인 백프레셔 확인 |
| `rtp_tts_pcm_queue_backlog_high` | PCM 큐 백로그 ≥25. 발송이 TTS 속도를 못 따라감 | 20ms 루프 지연 원인(CPU, 다른 태스크) 점검 |
| `pipecat_pcm_queue_full_dropping` | PCM 큐 가득 차서 청크 **드롭** | 큐 크기 증가 검토 또는 TTS 속도 완화 |
| `rtp_sender_session_end` | 통화 종료 시. `empty_timeout_count` > 0이면 해당 횟수만큼 **빈 구간** 있었음 | 위 이벤트와 함께 패턴 확인 |
| `output_audio_frame_skipped` | 오디오가 있는 프레임이 RTP로 전송되지 않음. **음성 누락** 가능 | Pipecat 프레임 타입 확인, `TTSAudioRawFrame`/`OutputAudioRawFrame` 처리 여부 확인 |
| `tts_rtp_duration_mismatch` | Notifier(음원 길이) vs Output(큐에 넣은 양) 불일치 | sample_rate 차이 또는 프레임 스킵 여부 확인 |

## 로그 필터 예시 (PowerShell)

```powershell
# 끊김 관련
Get-Content logs\app.log | Select-String "rtp_tts_queue_empty_timeout|rtp_tts_sender_resumed_after_empty|rtp_tts_queue_depleted"

# 드롭/백로그
Get-Content logs\app.log | Select-String "pipecat_pcm_queue_full_dropping|rtp_tts_pcm_queue_backlog_high"

# 통화별 송출 종료 요약 (empty_timeout_count 포함)
Get-Content logs\app.log | Select-String "rtp_sender_session_end"

# 오디오 프레임 스킵 (음성 누락 가능)
Get-Content logs\app.log | Select-String "output_audio_frame_skipped"
```

## 구조적 안정성 요약

- **단일 송출 루프**: TTS PCM은 하나의 `_pipecat_tts_sender_loop`에서만 20ms 간격으로 RTP 전송되므로, 버스트 전송은 줄어든 구조입니다.
- **PCM 큐 크기**: 30 청크. 한 청크가 큰 경우(예: 0.5초 분량) 약 15초 분량까지 버퍼링 가능. 1초 타임아웃은 큐가 비었을 때만 발생합니다.
- **플러시**: 새 TTS 응답 시작 시 `request_tts_flush()`로 이전 PCM을 비워 RTP 겹침을 막습니다.

이슈 발생 시 위 이벤트를 기준으로 **어느 구간(큐 비움 / 백로그 / 드롭 / 프레임 스킵)**에서 문제가 나는지 좁혀서 조치하면 됩니다.
