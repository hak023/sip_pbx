# RTP TTS 구간 로그 스냅샷 점검 (뭉개짐·지터)

- **작성일**: 2026-03-27  
- **상태**: 분석 + 로그 필드 보강 반영 (`rtp_relay.py`)  
- **참고 로그**: `app.log` 동일 시각대 `call_id` ≈ `sUODVWVg7-`

## 1. 해당 구간에서 보이는 것

| 시각(대략) | 관찰 |
|------------|------|
| 17:59:28~36 | `rtp_tts_send_window_stats`가 **1초마다** 찍힘. `interval_avg_ms` ≈ 20, `behind_schedule_cumulative` **9로 고정** → “스케줄보다 늦음” 카운터는 이 구간에서 크게 늘지 않음. |
| 17:59:35.207 | **한 윈도우에서** `interval_max_ms` **32.48**, `interval_min_ms` **7.52**, `interval_violations_cumulative` **67→69** (+2). 20ms±5ms 밖으로 **최소 2패킷** 이탈이 창 안에 포함됨. |
| 17:59:32~33 | `timing_error_ms` **1.44** 한 번 — 절대시간 기준 오차가 잠깐 벌어졌다가 다시 0 근처. |
| 17:59:37 | `tts_sending_active: false`, `tts_queue_size: 0` — **TTS 송출 플래그는 이미 종료**. |
| 17:59:40~43 | `rtp_tts_queue_empty_timeout` — `packets_sent` **3231로 고정**, `empty_timeouts`만 증가. 송신 스레드가 **PCM 큐에서 1.25s 타임아웃**으로 깨어나는 상태(다음 청크 없음). |

## 2. 해석 (증상과의 연결)

1. **청취 “뭉개짐”이 TTS 재생 중이었다면**  
   - `interval_max` 32ms급 + `interval_min` 7~8ms급은 **한 틱 늦었다가 다음 틱이 당겨진 패턴**과 잘 맞고, 단말 PLC/지터버퍼에 **간헐적 결손·과밀**로 들어갈 수 있다.  
   - 원인 후보는 (a) 송신 스레드의 **busy-wait/스케줄**, (b) **AEC 락**과 수신 경로 경합, (c) **이벤트 루프에서 UDP 드레인·`sendto` 락** 지연으로 **실제 소켓 전송 간격**이 20ms 그리드와 어긋나는 경우.

2. **TTS 종료 직후~수 초 `empty_timeout`**  
   - 로그만 보면 **“더 넣을 PCM이 없음”**에 가깝다. 사용자가 느낀 “심한 끊김”이 **말 끝 이후 무음·후속 발화 지연**이면 이 타임아웃과 겹칠 수 있다.  
   - 반대로 **말하는 도중** 끊겼다면, 원인은 위 **지터 스파이크(35초대)** 쪽을 우선 의심.

3. **이 스냅샷만으로는 부족했던 정보**  
   - 스레드가 큐에 넣은 패킷 수 vs 루프에서 실제 `sendto`한 수(**파이프라인 라그**).  
   - **UDP 중간 큐** 깊이, **한 번의 드레인**에서 몇 패킷을 몇 ms에 보냈는지.  
   - **`sendto` 락 대기** 시간, **AEC 락 점유** 시간.

→ 위 항목은 코드에 로그를 보강해 다음 재현 시 바로 상관할 수 있게 했다.

## 3. 재테스트 시 확인할 로그 (우선순위)

1. **`rtp_tts_send_window_stats`**  
   - `pipeline_lag_packets`, `tts_udp_out_queue_size`, `thread_packets_queued`, `udp_packets_sent_stat`  
   - **lag가 커지면**: 루프/UDP 경로가 송신 스레드보다 느림.  
2. **`rtp_tts_send_window_jitter_spike`** (신규, `max≥28` 또는 `min≤12`일 때)  
   - 같은 줄의 `pipeline_lag_packets`, `tts_udp_out_queue_size`와 함께 본다.  
3. **`tts_udp_drain_bursty_or_slow`**  
   - 한 틱에 패킷을 몰아 보냄 또는 드레인 자체가 느림 → **루프 스톨** 가설.  
4. **`rtp_sendto_lock_wait_high`**  
   - **락 경합** 가설.  
5. **`tts_sender_aec_lock_hold_ms`**  
   - **AEC**가 송신 스레드를 오래 잡는지.  
6. **`tts_udp_out_queue_backlog_high`**  
   - 중간 큐 적체(스로틀됨).  
7. 기존 **`rtp_interval_violation`**, **`rtp_send_behind_schedule`**, **`rtp_seq_discontinuity`**

## 4. 코드 변경 요약

- 파일: `sip-pbx/src/media/rtp_relay.py`  
- 윈도 통계에 **UDP 큐 크기·파이프라인 라그** 추가, 지터 극단 시 **`rtp_tts_send_window_jitter_spike`**.  
- `_drain_tts_udp_out_queue`: 배치 크기/경과 ms로 **`tts_udp_drain_bursty_or_slow`**.  
- `_process_tts_udp_item`: **`rtp_sendto_lock_wait_high`**.  
- PCM 청크 처리: **`tts_sender_aec_lock_hold_ms`**.  
- UDP 큐 깊이 ≥48: **`tts_udp_out_queue_backlog_high`**(과다 로깅 방지 스로틀).

---

*로그 스냅샷은 사용자 제공 `app.log` 구간에 기반함.*
