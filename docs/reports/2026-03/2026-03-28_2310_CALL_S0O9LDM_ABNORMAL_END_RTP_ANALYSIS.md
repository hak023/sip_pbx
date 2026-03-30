# 호 S0O9Ldm~p9 “비정상 종료” 로그 점검

- **작성일**: 2026-03-28 (로컬)
- **상태**: 로그 분석 + `rtp_relay.py` 수정(종료 sentinel / 타이밍 요약)
- **관련 로그**: `app.log` 8559–8574, 8565–8567 인용 구간

## 1. SIP·통화 종료는 단말 BYE (정상 시나리오)

- `04:58:16` `sip_recv` **BYE** from `172.30.1.24:34537` → 발신 단말이 끊음.
- `bye_cleanup_triggered`, `reason`: `BYE received in AI mode`
- 녹음 `mixed.wav` 약 **331.9s**, CDR duration 약 **342s** — 통화는 **약 5.5분 유지** 후 사용자(또는 단말) BYE.

→ **PBX가 임의로 끊은 흔적은 없음.** “비정상”이면 **체감 품질(오디오)** 또는 **로그에 보이는 모순** 쪽에 가깝다.

## 2. 8565–8567 구간이 헷갈리는 이유 (버그)

같은 ms에 다음이 연속:

1. `rtp_absolute_timing_summary` — 당시 코드는 `_rtp_packets_sent_total`만 쓰는데, 이 값은 **소프트 리싱크마다 0으로 리셋**되어 **1**처럼 작게 찍힐 수 있음.
2. `rtp_base_time_initialized` — **종료 직전에 다시 “첫 PCM”처럼 보임**
3. `rtp_sender_session_end` — `packets_sent: 11266` 등 **실제 세션 누적**과 일치

**원인**: `stop_pipecat_mode()`가 메인 스레드에서 `_rtp_base_time = None`으로 비운 뒤 PCM 큐에 `None`(sentinel)을 넣으면, 송신 스레드가 **sentinel을 처리할 때** 기존 코드 순서상 **먼저** `base_time` 초기화 블록이 실행되어 가짜 `rtp_base_time_initialized`가 한 번 더 찍혔음.

**조치**: `_pcm_sender_thread_main`에서 **`pcm_data is None`을 `base_time` 초기화보다 앞**에서 처리.

**추가**: `rtp_absolute_timing_summary`는 세션 누적 `stats["rtp_tts_packets_sent"]`와 마지막 격자 구간 `_rtp_packets_sent_total`을 **분리 필드**로 로깅해 혼동을 줄임.

## 3. 통화 중 RTP 품질 신호 (끊김·지터 체감 가능)

동일 `call_id` 구간:

- `interval_violations`·`behind_schedule_count`·`rtp_sched_soft_resync_count`(662) **다수**
- `rtp_tts_send_window_stats`에서 **평균 간격 ~28–32ms** (20ms 목표 대비 길게)
- `pcm_queue_wait_time` **~88ms** 등 — TTS PCM이 20ms보다 드문드문 들어오는 패턴

→ **서버·스케줄러 부하, AEC 락, UDP 드레인, Google TTS 청크 간격** 등과 맞물려 **지터·뭉개짐**이 날 수 있음. 단, 이겧만으로 SIP BYE가 자동 발생한다고 보긴 어렵고, 사용자/단말 종료와 병행 가능.

## 4. Pipecat 정리 순서

- `04:57:44.572` `pipecat_input_transport_stopped`
- `04:57:44.751` 송신 스레드 종료 로그 (위 sentinel 순서 수정 후에는 가짜 `rtp_base_time_initialized` 제거 기대)
- `04:57:48.751` `pipecat_mode_stopped` — `stop_pipecat_mode` 내 `join` 등으로 **BYE보다 앞서** 미디어 파이프라인 정리 시작 (BYE는 `04:58:16`)

## 5. 요약

| 질문 | 답 |
|------|----|
| 서버가 비정상 크래시? | 로그상 아님 |
| 누가 끊었나? | **발신 BYE** |
| 8565–8567이 “다시 첫 PCM”인 이유? | **종료 레이스 + 코드 순서 버그** (수정됨) |
| 청취 이상 가능성? | **RTP 간격 위반·리싱크 다발** — 별도 튜닝 여지 |
