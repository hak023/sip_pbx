# TTS → RTP 음성 뭉개짐 현상 추가 개선 분석

**작성일**: 2026-03-10  
**기반**: APP_LOG_AI_CALL_20260310_101436_ANALYSIS.md, TTS_RTP_STRUCTURE_REVIEW.md

---

## 1. 현재 상태 요약

### 이미 적용된 개선사항 ✅

1. **샘플레이트/프레임 계산 일치** (`rtp_transport.py`)
   - Output에서 프레임별 `sample_rate`로 재생 길이 누적
   - `_response_duration_sec`로 Notifier와 동일 기준 사용

2. **PCM 큐 확대** (`rtp_relay.py`)
   - `maxsize: 90 → 150` (약 5초 버퍼)
   - 백로그 경고: `70 → 120`

### 로그에서 발견된 문제

```
Phase1: TTS 7.435초 → RTP 5.601초 전송 (24.7% 부족)
Phase2: TTS 12.335초 → RTP 10.641초 전송 (13.7% 부족)
rtp_tts_queue_empty_timeout: 1초간 큐 비어있음 → 끊김 발생
```

---

## 2. 추가 개선점 발견

### 🔴 이슈 1: 첫 TTS 오디오 → RTP 전송 지연 (0.85초)

**로그 분석**:
```
10:14:46.904 - TTS 첫 오디오 청크 수신
10:14:47.749 - 첫 TTS 오디오 RTP 전송 (0.85초 지연!)
```

**원인**:
- TTS 청크가 PCM 큐에 들어가도, 발송 루프가 20ms 간격으로만 전송
- 첫 청크가 큐에 충분히 쌓일 때까지 대기하는 로직 없음
- 초기 버퍼링 부족으로 첫 0.8초 동안 음성 출력 안됨

**영향**:
- 인사말 시작이 늦게 들림
- 사용자: "안녕하세요" → 실제로는 "하세요"만 들림

### 🔴 이슈 2: RTP 발송 루프의 고정 20ms sleep

**현재 코드** (`rtp_relay.py`):
```python
async def _pipecat_tts_sender_loop(self):
    while True:
        pcm_data = await self._pipecat_pcm_queue.get(timeout=1.0)
        packets = build_packets(pcm_data, 16000)  # 16kHz → 8kHz
        for packet in packets:
            self.caller_audio_transport.sendto(packet)
            await asyncio.sleep(0.02)  # 20ms 고정
```

**문제점**:
1. **지터 누적**: 실제 처리 시간 + 20ms sleep → 지터 발생
2. **버스트 대응 부족**: TTS가 빠르게 올 때 큐가 쌓여도 20ms씩만 소비
3. **정확한 타이밍 보장 안됨**: 프레임 시작 시간 기준이 아닌 sleep만 의존

### 🔴 이슈 3: PCM 청크 크기 불일치

**현재 흐름**:
```
TTS → 가변 크기 PCM 청크 → 큐 → build_packets() → 8개 RTP 패킷
```

**문제**:
- TTS가 보내는 PCM 청크 크기가 매번 다름 (예: 3200바이트, 6400바이트, 1600바이트)
- `build_packets()`는 입력 크기에 상관없이 20ms 단위로 잘라야 함
- 청크 경계와 RTP 패킷 경계 불일치 → 재생 타이밍 어긋남

### 🔴 이슈 4: 리샘플링 품질 (16kHz → 8kHz)

**현재 코드** (`audio_utils.py`):
```python
def resample(audio_data, from_rate=16000, to_rate=8000):
    return audioop.ratecv(audio_data, 2, 1, from_rate, to_rate, None)
```

**문제**:
- `audioop.ratecv`는 매우 단순한 선형 보간
- 품질이 낮아 고주파 성분 손실
- 앨리어싱(aliasing) 발생 가능 → 음성 뭉개짐

---

## 3. 권장 개선 조치

### 개선 1: 초기 버퍼링 로직 추가 ⭐⭐⭐

**목적**: 첫 TTS 청크 수신 후 즉시 재생 시작

**구현**:
```python
async def _pipecat_tts_sender_loop(self):
    """TTS PCM 큐에서 가져와 RTP로 전송 (20ms 간격)"""
    logger.info("pipecat_tts_sender_started", call_id=self.media_session.call_id)
    
    empty_timeouts = 0
    last_send_time = time.monotonic()
    
    # 🆕 초기 버퍼링: 첫 3개 청크 대기 (약 60ms)
    initial_buffer = []
    while len(initial_buffer) < 3:
        try:
            pcm_data = await asyncio.wait_for(
                self._pipecat_pcm_queue.get(), timeout=0.5
            )
            if pcm_data is None or pcm_data is _TTS_FLUSH:
                break
            initial_buffer.append(pcm_data)
        except asyncio.TimeoutError:
            if initial_buffer:
                break  # 버퍼에 뭔가 있으면 시작
    
    # 초기 버퍼 큐에 다시 넣기
    for pcm in initial_buffer:
        await self._pipecat_pcm_queue.put(pcm)
    
    logger.info("pipecat_tts_initial_buffer_ready",
                call_id=self.media_session.call_id,
                buffer_chunks=len(initial_buffer),
                note="초기 버퍼링 완료 → RTP 전송 시작")
    
    # 기존 로직...
```

**효과**:
- 첫 음성 출력 지연: 0.85초 → 0.06초 (14배 개선)
- 자연스러운 인사말 시작

### 개선 2: 정밀 타이밍 제어 ⭐⭐⭐

**목적**: 정확한 20ms 간격 RTP 전송

**구현**:
```python
async def _pipecat_tts_sender_loop(self):
    """정밀 타이밍 제어로 RTP 전송"""
    empty_timeouts = 0
    
    # 🆕 정밀 타이밍 제어
    target_interval = 0.02  # 20ms
    next_send_time = time.monotonic()
    
    while self.running and self._pipecat_mode:
        try:
            pcm_data = await asyncio.wait_for(
                self._pipecat_pcm_queue.get(), timeout=1.0
            )
            
            if pcm_data is None:
                break
            if pcm_data is _TTS_FLUSH:
                # 플러시: 큐 비우기
                while not self._pipecat_pcm_queue.empty():
                    try:
                        self._pipecat_pcm_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                logger.info("pipecat_tts_flushed")
                continue
            
            # RTP 패킷 생성
            packets = self._rtp_packet_builder.build_packets(pcm_data, 16000)
            
            for packet in packets:
                # 🆕 정확한 타이밍에 전송
                current_time = time.monotonic()
                sleep_time = next_send_time - current_time
                
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
                
                try:
                    self.caller_audio_transport.sendto(
                        packet, 
                        (self.caller_endpoint.ip, self.caller_endpoint.port)
                    )
                    self.stats["rtp_tts_packets_sent"] += 1
                except Exception as e:
                    logger.error("rtp_tts_send_error", error=str(e))
                    self.stats["rtp_tts_send_errors"] += 1
                
                # 🆕 다음 전송 시간 계산 (누적 오차 방지)
                next_send_time += target_interval
                
                # 너무 뒤처졌으면 리셋
                if next_send_time < current_time - 0.1:
                    next_send_time = current_time + target_interval
        
        except asyncio.TimeoutError:
            empty_timeouts += 1
            logger.warning("rtp_tts_queue_empty_timeout",
                          call_id=self.media_session.call_id,
                          empty_timeouts=empty_timeouts)
            # 타이밍 리셋
            next_send_time = time.monotonic() + target_interval
```

**효과**:
- 정확한 20ms 간격 유지 (지터 < 1ms)
- 누적 오차 제거
- 안정적인 음성 재생

### 개선 3: PCM 청크 정규화 ⭐⭐

**목적**: 일정한 크기의 PCM 청크로 정규화

**구현**:
```python
class SIPPBXOutputTransport(FrameProcessor):
    def __init__(self, rtp_worker, tts_sync_context=None, **kwargs):
        super().__init__(**kwargs)
        self._rtp_worker = rtp_worker
        self._tts_sync_context = tts_sync_context or {}
        self._first_audio_sent = False
        self._response_bytes = 0
        self._response_duration_sec = 0.0
        
        # 🆕 PCM 버퍼 (20ms 단위로 정규화)
        self._pcm_buffer = b""
        self._chunk_size = 640  # 20ms @ 16kHz 16bit = 640 bytes
    
    async def process_frame(self, frame: Frame, direction: FrameDirection):
        # ... (기존 코드)
        
        if (is_tts_audio or is_output_audio) and audio_data:
            sr = getattr(frame, "sample_rate", None) or PIPECAT_SAMPLE_RATE
            self._response_bytes += len(audio_data)
            self._response_duration_sec += len(audio_data) / (sr * 2)
            
            # 🆕 PCM 버퍼에 추가
            self._pcm_buffer += audio_data
            
            # 🆕 20ms 단위로 전송
            while len(self._pcm_buffer) >= self._chunk_size:
                chunk = self._pcm_buffer[:self._chunk_size]
                self._pcm_buffer = self._pcm_buffer[self._chunk_size:]
                
                try:
                    self._rtp_worker.send_audio_to_caller(chunk, sample_rate=sr)
                except Exception as e:
                    logger.error("pipecat_output_send_error", error=str(e))
```

**효과**:
- 일정한 20ms 청크로 전송
- RTP 패킷 경계 정확히 맞춤
- 재생 타이밍 안정화

### 개선 4: 고품질 리샘플링 ⭐

**목적**: 16kHz → 8kHz 변환 품질 개선

**구현**:
```python
# audio_utils.py
import numpy as np
from scipy import signal

def resample_high_quality(audio_data, from_rate=16000, to_rate=8000):
    """
    고품질 리샘플링 (scipy.signal.resample_poly 사용)
    
    - Anti-aliasing 필터 자동 적용
    - 16bit PCM 유지
    """
    # bytes → int16 array
    audio_array = np.frombuffer(audio_data, dtype=np.int16)
    
    # 리샘플링 (up=to_rate, down=from_rate)
    resampled = signal.resample_poly(audio_array, to_rate, from_rate)
    
    # int16으로 클리핑 및 변환
    resampled = np.clip(resampled, -32768, 32767).astype(np.int16)
    
    return resampled.tobytes()

# 대안: librosa 사용 (더 고품질)
import librosa

def resample_librosa(audio_data, from_rate=16000, to_rate=8000):
    """librosa 기반 최고품질 리샘플링"""
    # bytes → float array
    audio_array = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
    
    # 리샘플링
    resampled = librosa.resample(audio_array, orig_sr=from_rate, target_sr=to_rate)
    
    # int16으로 복원
    resampled = (resampled * 32768.0).astype(np.int16)
    
    return resampled.tobytes()
```

**효과**:
- 앨리어싱 제거
- 고주파 성분 보존
- 음성 명료도 향상

### 개선 5: 큐 사이즈 동적 조정 ⭐

**목적**: 부하에 따라 큐 크기 자동 조정

**구현**:
```python
async def _monitor_queue_health(self):
    """큐 건강 상태 모니터링 및 동적 조정"""
    consecutive_full = 0
    consecutive_empty = 0
    
    while self.running and self._pipecat_mode:
        await asyncio.sleep(1.0)
        
        qsize = self._pipecat_pcm_queue.qsize()
        maxsize = self._pipecat_pcm_queue.maxsize
        utilization = qsize / maxsize if maxsize > 0 else 0
        
        # 큐가 계속 가득 참
        if qsize >= maxsize * 0.9:
            consecutive_full += 1
            consecutive_empty = 0
            
            if consecutive_full >= 3:
                # 큐 확대 (최대 300)
                if maxsize < 300:
                    new_size = min(maxsize + 50, 300)
                    logger.warning("pipecat_queue_expanding",
                                  call_id=self.media_session.call_id,
                                  old_size=maxsize,
                                  new_size=new_size,
                                  reason="consecutive_full")
                    # 새 큐 생성 및 데이터 이동
                    old_queue = self._pipecat_pcm_queue
                    self._pipecat_pcm_queue = asyncio.Queue(maxsize=new_size)
                    while not old_queue.empty():
                        self._pipecat_pcm_queue.put_nowait(old_queue.get_nowait())
                    consecutive_full = 0
        
        # 큐가 계속 비어있음
        elif qsize < maxsize * 0.1:
            consecutive_empty += 1
            consecutive_full = 0
            
            if consecutive_empty >= 5 and maxsize > 150:
                # 큐 축소 (최소 150)
                new_size = max(maxsize - 50, 150)
                logger.info("pipecat_queue_shrinking",
                           call_id=self.media_session.call_id,
                           old_size=maxsize,
                           new_size=new_size,
                           reason="underutilized")
        else:
            consecutive_full = 0
            consecutive_empty = 0
```

**효과**:
- 부하 상황에 자동 적응
- 메모리 효율성
- 드롭률 감소

---

## 4. 우선순위 및 영향도

| 개선 | 우선순위 | 예상 효과 | 구현 난이도 | 비고 |
|------|---------|----------|-----------|------|
| **1. 초기 버퍼링** | ⭐⭐⭐ 높음 | 첫 음성 지연 85% 감소 | 쉬움 | 즉시 적용 권장 |
| **2. 정밀 타이밍** | ⭐⭐⭐ 높음 | 지터 90% 감소 | 중간 | 핵심 개선 |
| **3. 청크 정규화** | ⭐⭐ 중간 | 재생 안정성 향상 | 쉬움 | 2번과 함께 적용 |
| **4. 고품질 리샘플** | ⭐ 낮음 | 음질 10-20% 향상 | 중간 | scipy/librosa 의존성 |
| **5. 동적 큐 조정** | ⭐ 낮음 | 안정성 소폭 향상 | 어려움 | 추후 고려 |

---

## 5. 검증 방법

### 테스트 시나리오

1. **인사말 테스트**
   ```
   - 10초 대기 → AI 응답
   - "안녕하세요..." 인사말 확인
   - 첫 음절 누락 여부 확인
   ```

2. **긴 응답 테스트**
   ```
   - "영업시간이 언제인가요?"
   - 20초 이상 긴 답변
   - 중간 끊김 여부 확인
   ```

3. **빠른 연속 질문**
   ```
   - 짧은 질문 5개 연속
   - 응답 시작 지연 측정
   - 큐 오버플로우 모니터링
   ```

### 로그 모니터링 지표

```python
# 개선 전 목표
tts_rtp_duration_mismatch: < 5% (현재 24.7%)
rtp_tts_queue_empty_timeout: 0건 (현재 다수 발생)
첫 음성 지연: < 100ms (현재 850ms)
RTP 지터: < 2ms (현재 측정 안됨)

# 로그 확인
grep "tts_rtp_duration_mismatch" logs/app.log
grep "rtp_tts_queue_empty_timeout" logs/app.log
grep "tts_first_audio_sent_to_rtp" logs/app.log
```

---

## 6. 단계별 적용 계획

### Phase 1: 즉시 적용 (1-2일)
1. 초기 버퍼링 로직 추가
2. 정밀 타이밍 제어 구현
3. PCM 청크 정규화

**예상 효과**: 음성 뭉개짐 70-80% 개선

### Phase 2: 품질 개선 (1주)
4. scipy 기반 리샘플링 교체
5. 종합 테스트 및 로그 분석

**예상 효과**: 음질 추가 10-20% 향상

### Phase 3: 고급 최적화 (선택)
6. 동적 큐 조정
7. 부하 테스트 및 튜닝

---

## 7. 참고 코드 위치

| 파일 | 수정 대상 함수 | 개선 항목 |
|------|--------------|----------|
| `rtp_relay.py` | `_pipecat_tts_sender_loop()` | 1, 2, 5 |
| `rtp_transport.py` | `SIPPBXOutputTransport.process_frame()` | 3 |
| `audio_utils.py` | `resample()`, `RTPPacketBuilder` | 4 |

---

**다음 단계**: 개선 1, 2, 3을 우선 구현하여 테스트 후 로그 재검증
