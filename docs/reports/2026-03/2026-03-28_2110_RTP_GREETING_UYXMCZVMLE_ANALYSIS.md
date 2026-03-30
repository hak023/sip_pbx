# RTP·인사(안녕하세요) 청취 이상 로그 분석 — `call_id: uyXmCzVmLE`

- **작성일**: 2026-03-28 (로컬)
- **로그**: `sip-pbx/logs/app.log`
- **통화 요약**: INVITE `03:57:13`, 무응답 10s 후 AI Takeover, `03:57:23.559` 200 OK / Pipecat 기동

## 사용자 증상과 로그 상의 문구

- KB Phase1 로그 문구: `안녕하세요. KT 통화매니저 기상청 AI 봇 입니다.` (`greeting_from_kb_greeting_phase1`, `03:57:24.897`)
- TTS는 Google 쪽에서 **문장을 쪼개** 먼저 `안녕하세요.`(6자)만 합성 (`tts_text_input`, `03:57:25.141`)

## “RTP 손실”에 해당하는 서버 로그는?

- `rtp_health_snapshot` (`03:57:27.870`): **`rtp_tts_packets_dropped: 0`**, **`rtp_tts_send_errors: 0`**, **`bypass_relay_send_failed: 0`**
- 즉 **애플리케이션이 의도적으로 RTP를 버렸다는 증거는 없음**. 다만 아래 현상은 **지연·지터·버스트 송출**로 단말/지터버퍼에서 앞음절이 잘리거나 뭉개진 것처럼 들리게 할 수 있음.

## 인사 직후 타임라인(핵심)

| 시각(대략) | 이벤트 | 해석 |
|------------|--------|------|
| 03:57:24.897 | `greeting_phase1_sent` | Phase1 전체 문구 파이프라인 투입 |
| 03:57:24.948 | `rag_greeting_blocking_start` | Phase2 전 `event.wait()` — 이 구간 동안 STT·RTP·TTS 경합 지속 |
| 03:57:25.141 | `tts_text_input` `"안녕하세요."` | 첫 음절 구간 합성 시작 |
| 03:57:25.143 | `tts_first_audio_received` | 첫 PCM 청크 수신 |
| 03:57:25.488 | `tts_first_audio_sent_to_rtp` | RTP 경로로 첫 청크 반영 |
| 03:57:25.488 | `rtp_base_time_initialized`, **`pcm_queue_wait_ms`: 631.61** | 첫 PCM 대비 RTP 시계 기준 설정까지 **약 0.63s 대기**가 로그에 명시됨 |
| 03:57:25.488 | `rtp_tts_sender_resumed_after_empty`, **`empty_timeouts: 1`**, `packets_sent_so_far: 0` | 송신 루프가 **빈 큐 타임아웃 후 재개** — 스트림 시작 직전 공백/리셋 구간 |
| 03:57:25.490 | `rtp_first_packet_sent` → `172.30.1.24:47912` | **첫 UDP RTP 전송** |
| 03:57:25.490 | `rtp_send_behind_schedule`, `late_ms`: 0.38 | 스케줄 대비 소폭 지연 |
| 03:57:25.726 | `rtp_interval_violation`, **`actual_ms`: 36.8**, `expected_ms`: 20 | **20ms 격자 이탈** — 이전 패킷 대비 긴 간격 후 이어짐(지터) |
| 03:57:26.161 | `rtp_interval_violation`, **`actual_ms`: 32.1** | 동일 |
| 이후 | `pcm_queue_size` 6~11, `chunk_seq` 연속 증가 | **PCM이 20ms 송신보다 빨리 쌓임**(버스트 송출·큐 적체) |

## 동시에 겹친 부하(맥락)

- `03:57:23.942`~`03:57:24.395`: `caller_rtp_to_stt_input`에서 **`stt_queue_size` 최대 28**까지 쌓였다가 이후 급감 — ACK 직후 **역방향 RTP 폭주 + 파이프라인 기동**이 겹침.
- `03:57:23.945`, `03:57:25.143`: `stt_input_queue_depth_spike` (threshold 6) — STT 입력 경로 **백프레셔** 경고.

## 결론(로그 기반)

1. **“패킷이 안 나갔다”기보다는**, 첫 인사 RTP 직전에 **`pcm_queue_wait_ms` ~632ms**와 **`rtp_tts_sender_resumed_after_empty`**로 **송출 시작이 늦거나 한 박자 비는 구간**이 있다.
2. 이어 **`rtp_interval_violation`(36.8ms 등)** 과 **PCM 큐 적체**로 **20ms 균등 송출이 깨진 구간**이 있어, 단말에서는 **앞부분(“안녕하세요”)이 잘리거나 뭉개짐**으로 느끼기 쉽다.
3. 앱 로그상 **명시적 RTP 드롭 카운터는 0**이므로, 필요 시 **단말 캡처(Wireshark)** 로 네트워크 손실과 구분하는 것이 좋다.

## 개선 시 볼 만한 방향(참고)

- AI Takeover 직후·Phase1 첫 TTS 전 **STT 큐/파이프라인 부하 완화**(우선순위, 짧은 pre-buffer, greeting 전 VAD/STT 백프레셔).
- RTP 송신 쪽 **첫 청크 전 empty timeout·base_time** 정책 재검토(인사 시작 “무음 구간” 최소화).
- Google TTS가 `안녕하세요.`를 단독 청크로 쪼개는 경우 **문장 단위 합성 옵션** 검토(제품/언어 설정).
