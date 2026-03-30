# 묵음 RTP 킵얼라이브 — TTS 청취 깨짐 점검·수정

- **작성일**: 2026-03-28 (로컬)
- **관련 호**: `S0O9Ldm~p9` (로그상 `pcm_queue_wait_time` ~88ms 등 TTS 청크 간 갭)
- **코드**: `sip-pbx/src/media/rtp_relay.py`

## 원인

이전 동작은 **PCM 큐가 비는 매 폴링(기본 20ms)** 마다 곧바로 **16k 무음 20ms** 를 RTP로 넣었다.

Google TTS 등은 **청크를 50~100ms 간격**으로 넣는 경우가 많아, “한 문장 안”에서도 큐가 잠깐 비는 구간이 반복된다. 그 사이에 무음 프레임이 끼어 **끊김·지터·뭉개짐**으로 들리고, `rtp_schedule_soft_resync`·`interval_violation`이 누적되기 쉽다.

즉 **NO_RTP 방지용 묵음**이 **TTS 스트리밍 갭에도 적용**된 것이 문제.

## 수정 요약

1. **`SIPPBX_AI_RTP_SILENCE_KEEPALIVE` 기본값 `0` (끔)** — 필요한 환경만 `1` 로 켬.
2. **켠 경우에도** `SIPPBX_AI_RTP_KEEPALIVE_MIN_IDLE_SEC`(기본 **0.75초**) 동안 큐가 **연속으로** 비었을 때만 묵음 송신. 그 전에는 예전처럼 짧은 empty 대기만 함.
3. 큐에서 **실제 PCM을 받으면** `_rtp_keepalive_empty_streak` 리셋.

## 환경 변수

| 변수 | 기본 | 의미 |
|------|------|------|
| `SIPPBX_AI_RTP_SILENCE_KEEPALIVE` | `0` | `1`/`true`일 때만 장유휴 묵음 킵얼라이브 |
| `SIPPBX_AI_RTP_KEEPALIVE_POLL_SEC` | `0.02` | 켰을 때 큐 폴링 주기(초), 0.01~0.5 |
| `SIPPBX_AI_RTP_KEEPALIVE_MIN_IDLE_SEC` | `0.75` | 이 시간 이상 공백일 때만 묵음 삽입 시작 |

## 기대 효과

- 기본 구성에서는 **묵음 삽입 없음** → TTS 청크 간 갭만으로 재생 타이밍 유지.
- 단말 NO_RTP가 문제인 경우에만 킵얼라이브를 켜고, `MIN_IDLE_SEC`로 LLM 대기 구간만 타겟팅.
