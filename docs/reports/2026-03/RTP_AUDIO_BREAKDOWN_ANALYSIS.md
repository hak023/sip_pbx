# RTP 오디오 깨짐 현상 분석 보고서

**통화 ID**: `za904d1t13`  
**분석일**: 2026-03-10  
**통화 시간**: 16:47:49 - 16:49:21 (약 92초)

---

## 🚨 핵심 문제 요약

**심각도**: ⚠️ **HIGH** - 사용자가 체감할 수 있는 오디오 끊김 발생

### 확인된 문제

1. ✅ **PCM 큐 비어있음 (Empty Queue)** - 30회 발생
2. ✅ **TTS/RTP 길이 불일치** - 12-24% 손실
3. ✅ **RTP 패킷 손실** - 예상 대비 실제 전송량 부족

---

## 📊 상세 분석

### 1. PCM 큐 Empty Timeout (오디오 끊김 직접 원인)

```
16:47:58.030  empty_timeouts: 1   packets_sent: 287
16:48:13.121  empty_timeouts: 2   packets_sent: 909   (15초 뒤)
16:48:14.135  empty_timeouts: 3   packets_sent: 909   (1초 뒤)
16:48:21.139  empty_timeouts: 10  packets_sent: 909   (7초 뒤)
16:48:44.918  empty_timeouts: 20  packets_sent: 1529  (23초 뒤)
16:48:54.958  empty_timeouts: 30  packets_sent: 1529  (10초 뒤)
```

**해석**:
- 총 **30회** PCM 큐가 1초 이상 비어있음
- 이는 **최소 30초** 동안 오디오가 끊김을 의미
- 특히 `16:48:13 - 16:48:21` 구간: **8초 연속 끊김**
- `16:48:44 - 16:48:54` 구간: **10초 연속 끊김**

**원인**:
- TTS가 PCM 청크를 생성하지 않음
- 또는 생성 속도가 RTP 전송 속도(20ms/패킷)를 따라가지 못함

---

### 2. TTS/RTP 길이 불일치 (Duration Mismatch)

#### Phase 1 인사말
```
Time: 16:47:52.246
TTS Duration:  7.495초 (실제 음원 길이)
RTP Sent:      5.681초 (RTP로 전송된 길이)
Loss:          1.814초 (24.2% 손실) ❌
```

#### Phase 2 업무 안내
```
Time: 16:48:00.906
TTS Duration: 14.494초
RTP Sent:     12.401초
Loss:          2.093초 (14.4% 손실) ❌
```

#### 사용자 응답 1
```
Time: 16:48:29.592
TTS Duration: 14.075초
RTP Sent:     12.361초
Loss:          1.714초 (12.2% 손실) ❌
```

#### 사용자 응답 2
```
Time: 16:48:59.079
TTS Duration:  9.237초
RTP Sent:      8.080초
Loss:          1.157초 (12.5% 손실) ❌
```

**총 손실**: 약 **6.778초** (전체 TTS 중 12-24% 손실)

---

### 3. RTP 패킷 전송 통계

```json
{
  "rtp_tts_packets_sent": 1832,
  "rtp_tts_packets_dropped": 0,
  "rtp_tts_send_errors": 0
}
```

**분석**:
- 전송된 패킷: **1832개**
- 드롭된 패킷: **0개** (큐 가득참으로 인한 드롭 없음)
- 전송 에러: **0개** (네트워크 전송 정상)

**예상 패킷 수 계산**:
```
총 TTS 길이: 7.495 + 14.494 + 14.075 + 9.237 = 45.301초
예상 패킷 수: 45.301초 / 0.020초 = 2,265 패킷

실제 전송: 1832 패킷
손실:      433 패킷 (19.1% 손실)
```

→ **433개 패킷 (약 8.66초)이 큐에 들어가지 못했거나 전송되지 않음**

---

## 🔍 근본 원인 분석

### 원인 1: Sample Rate Mismatch (가장 유력)

**증거**:
1. 로그에 `tts_rtp_duration_mismatch` 경고 4회
2. 모든 응답에서 일관되게 12-24% 손실
3. `note: "sample_rate 차이 또는 프레임 누락 가능"`

**가설**:
```python
# TTS 출력: 16kHz (16000 samples/sec)
# RTP 전송: 8kHz로 설정? 또는 계산 오류

# 예시:
TTS가 16000 바이트 (16kHz, 0.5초) 생성
→ RTP는 8kHz 기준으로 계산 → 0.25초로 인식
→ 패킷 수 절반만 생성
```

**확인 필요**:
- `rtp_relay.py`의 `build_packets(pcm_data, 16000)` 호출 시 sample_rate 파라미터
- `RTPPacketBuilder`의 sample_rate 설정
- PCM → RTP 변환 로직의 sample_rate 사용

---

### 원인 2: PCM 청크 크기 불일치

**증거**:
```
16:47:51.026  tts_first_audio_sent_to_rtp  audio_len: 16000
16:47:59.317  tts_first_audio_sent_to_rtp  audio_len: 16000
16:48:27.843  tts_first_audio_sent_to_rtp  audio_len: 16000
16:48:58.139  tts_first_audio_sent_to_rtp  audio_len: 16000
```

모든 첫 청크가 **16000 바이트**로 동일

**문제**:
- TTS는 가변 크기 청크를 생성할 수 있음
- 하지만 RTP는 고정 크기 패킷(160 바이트/패킷, 8kHz 기준) 기대
- 크기 불일치 시 일부 데이터가 버려질 수 있음

---

### 원인 3: TTS 생성 속도 문제

**타임라인 분석**:

```
Phase 1 인사말:
16:47:49.745  TTS 첫 청크 수신
16:47:51.026  RTP 첫 패킷 전송 (1.3초 지연)
16:47:52.246  TTS 완료 (7.495초 음원)
16:47:58.030  큐 비어있음 (5.8초 후)

→ TTS가 7.5초 음원을 만들었지만, RTP는 5.7초만 받음
→ 1.8초 이후 큐가 비어버림
```

**문제**:
- TTS가 청크를 **불연속적으로** 생성 (burst 방식)
- RTP는 **연속적으로** 20ms마다 소비
- TTS 생성 중단 시 큐가 즉시 비어버림

---

## 🎯 타임라인 재구성

### Phase 1: 인사말 (16:47:49 - 16:47:58)

```
00:00.00  TTS 시작 "안녕하세요. 기상청 AI 통화 비서입니다. 무엇을 도와드릴까요?"
00:01.28  RTP 첫 패킷 전송 시작
00:02.50  TTS 완료 (7.495초 음원 생성)
00:05.68  RTP 전송 완료 (5.681초만 전송)
00:08.28  PCM 큐 비어있음 (empty_timeout #1) ❌ 끊김 발생
```

**끊김 구간**: 00:05.68 - 00:08.28 (약 2.6초)

---

### Phase 2: 업무 안내 (16:47:58 - 16:48:13)

```
00:00.00  TTS 시작 "저는 날씨 예보 조회..."
00:00.52  RTP 첫 패킷 전송
00:02.12  TTS 완료 (14.494초 음원 생성)
00:12.40  RTP 전송 완료 (12.401초만 전송)
00:15.00  PCM 큐 비어있음 (empty_timeout #2) ❌ 끊김 발생
00:16.01  PCM 큐 여전히 비어있음 (empty_timeout #3) ❌
00:23.01  PCM 큐 여전히 비어있음 (empty_timeout #10) ❌
```

**끊김 구간**: 00:12.40 - 00:23+ (약 10초 이상 끊김)

---

## 💡 해결 방안

### 우선순위 1: Sample Rate 통일 (즉시 필요)

**문제**: TTS 16kHz vs RTP 계산 오류

**수정 위치**: `sip-pbx/src/media/rtp_relay.py`

```python
# 현재 (추정):
rtp_packets = self._rtp_packet_builder.build_packets(pcm_data, 16000)
# 하지만 내부에서 8kHz로 계산?

# 수정:
# 1. RTPPacketBuilder 초기화 시 sample_rate 명확히 지정
# 2. build_packets에서 sample_rate 일관성 확인
# 3. 로그로 sample_rate 추적
```

**검증**:
```python
logger.info("rtp_packet_builder_config",
           sample_rate=self._rtp_packet_builder.sample_rate,
           codec=codec,
           bytes_per_packet=self._rtp_packet_builder.bytes_per_packet)
```

---

### 우선순위 2: TTS 청크 크기 표준화

**문제**: 가변 크기 청크 → 고정 크기 패킷 변환 시 손실

**수정**: TTS 출력을 고정 크기 청크로 표준화

```python
# Pipecat Output Transport에서:
CHUNK_SIZE = 3200  # 16kHz, 100ms (20ms * 5패킷)

def aggregate_pcm_chunks(self, pcm_data):
    """PCM을 고정 크기 청크로 집계"""
    self._pcm_buffer += pcm_data
    
    while len(self._pcm_buffer) >= CHUNK_SIZE:
        chunk = self._pcm_buffer[:CHUNK_SIZE]
        self._pcm_buffer = self._pcm_buffer[CHUNK_SIZE:]
        yield chunk
```

---

### 우선순위 3: PCM 큐 크기 증가

**현재**: `maxsize=150` (약 3초 버퍼)

**수정**: `maxsize=300` (약 6초 버퍼)

```python
self._pipecat_pcm_queue = asyncio.Queue(maxsize=300)
```

**이유**: TTS가 burst로 생성 시 충분한 버퍼 확보

---

### 우선순위 4: 고품질 리샘플링

**현재**: `audioop.ratecv` (저품질)

**수정**: `scipy.signal.resample_poly` (고품질)

```python
import scipy.signal

def resample_pcm(pcm_data, from_rate, to_rate):
    """고품질 리샘플링"""
    audio = np.frombuffer(pcm_data, dtype=np.int16)
    resampled = scipy.signal.resample_poly(audio, to_rate, from_rate)
    return resampled.astype(np.int16).tobytes()
```

---

## 📈 예상 효과

| 수정 항목 | 현재 손실 | 예상 개선 |
|----------|---------|----------|
| Sample Rate 통일 | 12-24% | → 0-2% ✅ |
| 청크 크기 표준화 | 끊김 30회 | → 5회 이하 ✅ |
| 큐 크기 증가 | 버퍼 3초 | → 버퍼 6초 ✅ |
| 고품질 리샘플링 | 음질 저하 | → 원음 유지 ✅ |

---

## 🔧 즉시 적용 가능한 디버깅

이미 추가된 로그로 확인 가능:

1. **PCM 청크 크기 확인**:
   ```bash
   grep "pcm_chunk_queued" app.log | jq '.pcm_bytes, .estimated_duration_ms'
   ```

2. **RTP 패킷 타이밍 확인**:
   ```bash
   grep "rtp_packet_timing_detail" app.log | jq '.actual_interval_ms'
   ```

3. **PCM → RTP 변환 비율 확인**:
   ```bash
   grep "rtp_pcm_chunk_to_packets" app.log | jq '.pcm_bytes, .rtp_packets_count'
   ```

---

## 📋 체크리스트

수정 후 확인사항:

- [ ] `tts_rtp_duration_mismatch` 경고 사라짐
- [ ] `rtp_tts_queue_empty_timeout` 발생 빈도 감소 (0-2회)
- [ ] 실제 전송 패킷 수 ≈ 예상 패킷 수 (오차 5% 이내)
- [ ] 사용자 체감 음질 개선 확인

---

## 🎯 결론

### 확인된 문제

1. ✅ **PCM 큐 30회 비어있음** → 30초 이상 오디오 끊김
2. ✅ **TTS/RTP 길이 12-24% 불일치** → 6.8초 손실
3. ✅ **RTP 패킷 433개 손실** → 8.66초 누락

### 근본 원인 (추정)

1. 🔴 **Sample Rate Mismatch** (가장 유력)
2. 🟠 **PCM 청크 크기 불일치**
3. 🟡 **TTS 생성 속도 불안정**

### 권장 조치

1. **즉시**: Sample Rate 통일 및 검증 로그 추가
2. **단기**: 청크 크기 표준화, 큐 크기 증가
3. **중기**: 고품질 리샘플링 적용

---

## 📚 관련 문서

- [TTS_RTP_AUDIO_QUALITY_IMPROVEMENT.md](./TTS_RTP_AUDIO_QUALITY_IMPROVEMENT.md)
- [RTP_TIMING_DEBUG_LOGS.md](./RTP_TIMING_DEBUG_LOGS.md)
- [APP_LOG_20260310_153028_DETAILED_ANALYSIS.md](./APP_LOG_20260310_153028_DETAILED_ANALYSIS.md)
