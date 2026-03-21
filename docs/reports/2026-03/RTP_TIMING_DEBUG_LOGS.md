# RTP 패킷 전송 타이밍 디버깅 로그 추가

**작성일**: 2026-03-10  
**상태**: ✅ 완료

---

## 📋 목적

TTS 오디오가 RTP로 전송될 때 패킷 손실 및 타이밍 문제를 디버깅하기 위해 상세한 로그를 추가합니다.

**배경**: `APP_LOG_20260310_153028_DETAILED_ANALYSIS.md`에서 확인된 문제
- TTS 오디오 중간에 패킷이 누락되거나 지연됨
- 20ms 간격으로 정확히 전송되는지 확인 필요
- PCM 큐에 데이터가 언제, 얼마나 들어가는지 추적 필요

---

## 🔧 추가된 로그

### 1. PCM 청크 큐잉 로그 (`send_audio_to_caller`)

**위치**: `sip-pbx/src/media/rtp_relay.py` Line 960-990

**로그 이벤트**: `pcm_chunk_queued`

**출력 조건**: 
- 첫 10개 PCM 청크
- 이후 10개마다

**로그 필드**:
```python
{
    "event": "pcm_chunk_queued",
    "call_id": "...",
    "progress": "rtp_timing",
    "chunk_seq": 15,                    # 청크 시퀀스 번호 (누적)
    "pcm_bytes": 16000,                 # PCM 바이트 수
    "queue_size_after": 3,              # 큐에 추가 후 크기
    "total_bytes_queued": 240000,       # 누적 바이트 수
    "sample_rate": 16000,
    "estimated_duration_ms": 500.0,     # 예상 재생 시간 (ms)
    "note": "TTS PCM 청크를 큐에 추가 (발송 루프가 20ms 간격으로 소비)"
}
```

**분석 용도**:
- TTS에서 얼마나 빠르게 PCM을 생성하는지 확인
- 큐에 데이터가 쌓이는 속도 측정
- 백로그가 발생하는지 확인

---

### 2. PCM 큐 대기 시간 로그 (`_pipecat_tts_sender_loop`)

**위치**: `sip-pbx/src/media/rtp_relay.py` Line 652-668

**로그 이벤트**: `pcm_queue_wait_time`

**출력 조건**:
- 첫 50개 패킷
- 대기 시간이 1ms 이상인 경우

**로그 필드**:
```python
{
    "event": "pcm_queue_wait_time",
    "call_id": "...",
    "progress": "rtp_timing",
    "packet_seq": 25,                   # RTP 패킷 시퀀스 번호
    "wait_ms": 15.3,                    # 큐 대기 시간 (ms)
    "queue_size_before": 2,             # 대기 전 큐 크기
    "note": "PCM 큐에서 데이터 가져오는데 걸린 시간"
}
```

**분석 용도**:
- 큐가 비어있어서 발송 루프가 대기하는지 확인
- TTS 생성 속도가 RTP 전송 속도를 따라가는지 확인
- 큐가 자주 비면 → TTS 생성이 느림
- 큐 대기 시간이 길면 → 오디오 끊김 발생

---

### 3. PCM → RTP 패킷 변환 로그

**위치**: `sip-pbx/src/media/rtp_relay.py` Line 717-728

**로그 이벤트**: `rtp_pcm_chunk_to_packets`

**출력 조건**:
- 첫 10개 PCM 청크
- 이후 100개마다

**로그 필드**:
```python
{
    "event": "rtp_pcm_chunk_to_packets",
    "call_id": "...",
    "progress": "rtp_timing",
    "pcm_bytes": 16000,                 # 입력 PCM 바이트 수
    "rtp_packets_count": 50,            # 생성된 RTP 패킷 수
    "packets_sent_so_far": 150,         # 누적 전송 패킷 수
    "note": "PCM 청크 → RTP 패킷 변환"
}
```

**분석 용도**:
- PCM 청크 크기에 따라 몇 개의 RTP 패킷이 생성되는지 확인
- 예상: 16000 바이트 (16kHz, 1초) → 50개 패킷 (20ms/패킷)
- 패킷 수가 예상과 다르면 → 변환 로직 문제

---

### 4. RTP 패킷 전송 타이밍 상세 로그

**위치**: `sip-pbx/src/media/rtp_relay.py` Line 730-747

**로그 이벤트**: `rtp_packet_timing_detail`

**출력 조건**:
- **첫 20개 RTP 패킷만** (매우 상세)

**로그 필드**:
```python
{
    "event": "rtp_packet_timing_detail",
    "call_id": "...",
    "progress": "rtp_timing",
    "packet_seq": 5,                        # 패킷 시퀀스 번호 (0부터)
    "chunk_packet_idx": 2,                  # 현재 청크 내 패킷 인덱스
    "expected_interval_ms": 20.0,           # 목표 간격 (ms)
    "actual_interval_ms": 20.15,            # 실제 간격 (ms)
    "sleep_before_send_ms": 18.5,           # 전송 전 sleep 시간 (ms)
    "elapsed_before_sleep_ms": 1.5,         # sleep 전 경과 시간 (ms)
    "note": "첫 20개 패킷 타이밍 상세"
}
```

**분석 용도**:
- **20ms 간격이 정확히 지켜지는지 확인**
- `actual_interval_ms`가 19-21ms 범위를 벗어나면 → 타이밍 문제
- `sleep_before_send_ms`가 20ms보다 크면 → 처리 지연 발생
- `elapsed_before_sleep_ms`가 크면 → 패킷 변환 또는 전송이 느림

**예시 분석**:
```
packet_seq=0: actual_interval_ms=20.02 ✅ 정상
packet_seq=1: actual_interval_ms=20.18 ✅ 정상
packet_seq=2: actual_interval_ms=25.50 ❌ 5.5ms 지연! → 이 구간에서 끊김 발생
packet_seq=3: actual_interval_ms=19.95 ✅ 정상
```

---

## 📊 로그 분석 방법

### 1. 정상 흐름 확인

```bash
# PCM 청크 큐잉
grep "pcm_chunk_queued" app.log

# 예상 출력:
chunk_seq=1, pcm_bytes=16000, queue_size_after=1, estimated_duration_ms=500.0
chunk_seq=2, pcm_bytes=16000, queue_size_after=2, estimated_duration_ms=500.0
...
```

**체크포인트**:
- `queue_size_after`가 계속 증가하면 → 발송 루프가 느림
- `estimated_duration_ms`가 일정하면 → TTS가 일정한 청크 생성

---

### 2. 큐 대기 시간 분석

```bash
# 큐 대기 시간
grep "pcm_queue_wait_time" app.log

# 정상: wait_ms < 5ms
# 경고: wait_ms > 10ms → 큐가 자주 비어있음 (TTS 생성 느림)
# 위험: wait_ms > 50ms → 오디오 끊김 발생
```

---

### 3. RTP 패킷 타이밍 분석

```bash
# 첫 20개 패킷 타이밍
grep "rtp_packet_timing_detail" app.log

# 분석:
# 1. actual_interval_ms가 19-21ms 범위인가?
# 2. sleep_before_send_ms가 적절한가? (대부분 18-20ms)
# 3. elapsed_before_sleep_ms가 작은가? (<2ms 권장)
```

**예시 정상 로그**:
```
packet_seq=0: actual=20.01ms, sleep=19.8ms, elapsed=0.2ms ✅
packet_seq=1: actual=20.03ms, sleep=19.7ms, elapsed=0.3ms ✅
packet_seq=2: actual=19.98ms, sleep=19.9ms, elapsed=0.1ms ✅
```

**예시 문제 로그**:
```
packet_seq=0: actual=20.02ms, sleep=19.8ms, elapsed=0.2ms ✅
packet_seq=1: actual=35.50ms, sleep=0ms, elapsed=35.5ms ❌ → 큐 비어있음!
packet_seq=2: actual=19.95ms, sleep=19.9ms, elapsed=0.05ms ✅
```

→ packet_seq=1에서 15.5ms 지연 → 이 구간에서 오디오 끊김

---

### 4. PCM → RTP 변환 비율 확인

```bash
# PCM → RTP 패킷 변환
grep "rtp_pcm_chunk_to_packets" app.log

# 예상:
# pcm_bytes=16000 (16kHz, 500ms) → rtp_packets_count=25 (20ms/패킷)
# pcm_bytes=32000 (16kHz, 1000ms) → rtp_packets_count=50
```

**계산식**:
```
예상 패킷 수 = (pcm_bytes / 2) / sample_rate / 0.020
             = (16000 / 2) / 16000 / 0.020
             = 0.5 / 0.020
             = 25 패킷

실제 패킷 수와 비교:
- 일치: ✅ 정상
- 불일치: ❌ 변환 로직 문제 또는 sample rate 불일치
```

---

## 🎯 디버깅 시나리오

### 시나리오 1: TTS 오디오 중간에 끊김

**증상**: 인사말 중간에 0.5초 정도 무음

**로그 분석 순서**:

1. **PCM 청크 큐잉 확인**:
   ```bash
   grep "pcm_chunk_queued" app.log | grep "call_id: ABC"
   ```
   - 청크가 연속적으로 들어오는가?
   - 특정 시점에 청크가 멈췄는가?

2. **큐 대기 시간 확인**:
   ```bash
   grep "pcm_queue_wait_time" app.log | grep "call_id: ABC"
   ```
   - `wait_ms`가 500ms 이상인 구간이 있는가?
   - → TTS 생성이 멈춘 시점

3. **RTP 패킷 타이밍 확인**:
   ```bash
   grep "rtp_packet_timing_detail" app.log | grep "call_id: ABC"
   ```
   - `actual_interval_ms`가 크게 벗어난 구간이 있는가?
   - → 패킷 전송 지연 시점

4. **빈 큐 timeout 확인**:
   ```bash
   grep "rtp_tts_queue_empty_timeout" app.log | grep "call_id: ABC"
   ```
   - 1초 이상 큐가 비어있었는가?
   - → 이 구간에서 끊김 발생

---

### 시나리오 2: TTS가 빠르게 재생됨 (속도 빠름)

**증상**: 인사말이 정상보다 빠르게 들림

**로그 분석**:

1. **RTP 패킷 간격 확인**:
   ```bash
   grep "rtp_packet_timing_detail" app.log
   ```
   - `actual_interval_ms`가 20ms보다 작은가? (예: 15ms)
   - → 패킷이 너무 빠르게 전송됨

2. **sample rate 불일치**:
   - TTS: 16kHz
   - RTP: 8kHz 설정 시 → 2배 빠르게 재생
   - 로그에서 `sample_rate` 필드 확인

---

### 시나리오 3: TTS가 느리게 재생됨 (속도 느림)

**로그 분석**:

1. **RTP 패킷 간격 확인**:
   ```bash
   grep "rtp_packet_timing_detail" app.log
   ```
   - `actual_interval_ms`가 20ms보다 큰가? (예: 25ms)
   - → 패킷 전송이 느림

2. **sleep 시간 확인**:
   - `sleep_before_send_ms`가 20ms보다 크면 → 로직 문제

---

## 📈 성능 목표

### 정상 범위

| 지표 | 정상 범위 | 경고 | 위험 |
|------|----------|------|------|
| `actual_interval_ms` | 19-21ms | 18-22ms | <18 또는 >22ms |
| `queue_wait_ms` | <5ms | 5-10ms | >10ms |
| `queue_size_after` | 1-5 | 5-10 | >10 (백로그) |
| `sleep_before_send_ms` | 18-20ms | 15-18ms | <15ms (처리 느림) |

---

## 🔍 추가 분석 도구

### Python 스크립트로 로그 분석

```python
import json
import sys

# RTP 타이밍 분석
with open('app.log', 'r', encoding='utf-8') as f:
    for line in f:
        try:
            log = json.loads(line)
            if log.get('event') == 'rtp_packet_timing_detail':
                seq = log['packet_seq']
                actual = log['actual_interval_ms']
                expected = log['expected_interval_ms']
                diff = abs(actual - expected)
                
                if diff > 2.0:
                    print(f"⚠️ Packet {seq}: {actual:.2f}ms (diff: {diff:.2f}ms)")
                else:
                    print(f"✅ Packet {seq}: {actual:.2f}ms")
        except:
            pass
```

### Grep 원라이너

```bash
# 타이밍 이상 패킷만 추출 (21ms 이상 또는 19ms 이하)
grep "rtp_packet_timing_detail" app.log | \
  jq 'select(.actual_interval_ms > 21 or .actual_interval_ms < 19)'

# 큐 대기 시간 평균
grep "pcm_queue_wait_time" app.log | \
  jq -r '.wait_ms' | \
  awk '{sum+=$1; count++} END {print "Average:", sum/count, "ms"}'

# PCM 청크 크기 분포
grep "pcm_chunk_queued" app.log | \
  jq -r '.pcm_bytes' | \
  sort | uniq -c
```

---

## ✅ 체크리스트

테스트 통화 후 확인사항:

- [ ] `pcm_chunk_queued` 로그가 연속적으로 출력되는가?
- [ ] `queue_size_after`가 적정 범위(1-5)인가?
- [ ] `pcm_queue_wait_time`이 10ms 미만인가?
- [ ] `rtp_packet_timing_detail`에서 `actual_interval_ms`가 19-21ms 범위인가?
- [ ] `rtp_pcm_chunk_to_packets`에서 패킷 수가 예상과 일치하는가?
- [ ] `rtp_tts_queue_empty_timeout` 로그가 없는가? (있으면 끊김 발생)

---

## 📝 관련 문서

- [APP_LOG_20260310_153028_DETAILED_ANALYSIS.md](../logs/APP_LOG_20260310_153028_DETAILED_ANALYSIS.md) - 원본 문제 분석
- [TTS_RTP_AUDIO_QUALITY_IMPROVEMENT.md](./TTS_RTP_AUDIO_QUALITY_IMPROVEMENT.md) - 오디오 품질 개선 권장사항

---

## 🎯 결론

**추가된 로그**:
1. ✅ PCM 청크 큐잉 로그 (10개마다)
2. ✅ PCM 큐 대기 시간 로그 (첫 50개, 1ms 이상)
3. ✅ PCM → RTP 패킷 변환 로그 (첫 10개 + 100개마다)
4. ✅ RTP 패킷 전송 타이밍 상세 로그 (첫 20개)

**디버깅 가능한 문제**:
- 20ms 간격이 정확히 지켜지는지
- PCM 큐가 비어있는 시간
- TTS 생성 속도 vs RTP 전송 속도
- 패킷 변환 비율 정확성

**다음 테스트**:
1. AI 통화 시작
2. 로그 수집: `grep "rtp_timing" app.log`
3. 위 분석 방법으로 타이밍 확인
4. 문제 발견 시 근본 원인 파악
