# RTP 로그 레벨 상향 리포트

- 작성일: 2026-04-10
- 상태: 완료
- 관련 경로: `sip-pbx/src/media/rtp_relay.py`, `sip-pbx/src/ai_voicebot/pipecat/rtp_transport.py`

---

## 개요

RTP가 안정화된 이후에도 디버깅용 고빈도 로그(`rtp_bypass_relay_sent` 등)가 INFO 레벨로 찍혀 `app.log` 가독성을 저하시키는 문제가 있었다. 해당 로그들을 `DEBUG`로 상향하여 현재 INFO 레벨 설정에서는 출력되지 않도록 변경했다.

---

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 |
|-----------|-----------|------|
| `src/media/rtp_relay.py` | 수정 | 고빈도 RTP 로그 7종 INFO → DEBUG |
| `src/ai_voicebot/pipecat/rtp_transport.py` | 수정 | 고빈도 RTP/STT 로그 5종 INFO → DEBUG |

---

## 변경된 로그 이벤트 목록

### `src/media/rtp_relay.py`

| 이벤트명 | 변경 전 | 변경 후 | 발생 빈도 | 비고 |
|----------|---------|---------|-----------|------|
| `rtp_bypass_relay_sent` | INFO | DEBUG | 패킷마다 (최초 12개+400개마다+지터 시) | 가장 큰 노이즈 원인 |
| `stun_binding_request_relaying` | INFO | DEBUG | STUN 패킷마다 | ICE/STUN 협상 중 집중 발생 |
| `caller_rtp_to_stt_input` | INFO | DEBUG | 최초 50개+100개마다 | STT 입력 추적용 |
| `stt_path_rtp_first` | INFO | DEBUG | 패킷 첫 수신 시 | STT 경로 시작 표시 |
| `stt_path_rtp_to_queue` | INFO | DEBUG | 200개마다 | STT 큐 투입 누적 |
| `timing_caller_rtp_first_to_pipeline` | INFO | DEBUG | 1회 (AEC경로·일반경로 각 1회) | 타이밍 측정용 |
| `rtp_packet_timing_absolute` | INFO | DEBUG | 첫 30개 패킷 | 절대 타이밍 추적용 |
| `rtp_tts_send_window_stats` | INFO | DEBUG | 50패킷마다 | TTS 송출 간격 요약 |
| `rtp_sent_3s_equivalent` | INFO | DEBUG | 1회 | 미디어 3초 전송 달성 표시 |
| `tts_rtp_trace_udp_sent` | INFO | DEBUG | 10개+20개마다 | UDP 트레이스 |
| `rtp_absolute_timing_summary` | INFO | DEBUG | 세션 종료 시 1회 | 전체 타이밍 집계 |

### `src/ai_voicebot/pipecat/rtp_transport.py`

| 이벤트명 | 변경 전 | 변경 후 | 발생 빈도 | 비고 |
|----------|---------|---------|-----------|------|
| `stt_path_input_first` | INFO | DEBUG | 1회 | 파이프라인 첫 프레임 |
| `input_audio_frame_to_pipeline` | INFO | DEBUG | 첫 10개+100개마다 | Input→Pipeline 추적 |
| `stt_path_input_to_pipeline` | INFO | DEBUG | 200개마다 | 파이프라인 투입 누적 |
| `output_audio_frame_received` | INFO | DEBUG | 오디오 프레임마다 | Output 수신 추적 |
| `tts_response_audio_chunk` | INFO | DEBUG | 10/30/50+20개마다 | TTS 청크 누적 |
| `output_sending_audio_to_caller` | INFO | DEBUG | 오디오 프레임마다 | send_audio_to_caller 호출 추적 |

---

## INFO로 유지한 로그 (변경 대상 제외)

아래는 1회 발생하거나 문제 감지 목적이므로 INFO 유지:

- `rtp_relay_worker_created`, `rtp_socket_bound`, `rtp_relay_started`, `rtp_relay_stopped`
- `callee_endpoint_updated`, `ai_mode_changed`, `ai_mode_enabled`
- `rtp_recording_ingest_worker_started`, `rtp_worker_started_successfully`
- `rtp_first_packet_sent`, `rtp_base_time_initialized`
- `pipecat_input_transport_started`, `pipecat_input_transport_stopped`, `stt_path_input_total`
- `tts_first_audio_sent_to_rtp`, `timing_first_tts_rtp_sent_to_caller`
- `warning` 레벨 이상: `rtp_interval_violation`, `tts_udp_out_queue_backlog_high` 등

---

## 주요 결정 사항

- **DEBUG 레벨 선택**: `WARNING`으로 올리면 문제 발생 시 재활성화가 번거롭다. `DEBUG`는 설정 파일에서 `level: debug`로 바꾸기만 하면 즉시 재확인 가능하다.
- **`rtp_bypass_relay_sent`**: 조건부 출력(지터·패킷 손실 시)도 함께 `DEBUG`로 변경했다. 이상 상황은 `rtp_interval_violation`(WARNING) 등 별도 이벤트로 이미 감지되므로 중복 불필요.
- **INFO 유지 기준**: 통화 생명주기 시작/종료, 설정 확인, 최초 1회 이벤트는 INFO 유지.
