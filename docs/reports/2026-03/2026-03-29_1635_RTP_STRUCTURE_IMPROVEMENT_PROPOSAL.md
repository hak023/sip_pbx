# RTP 전송 구조 개선 필요성 분석

**작성일**: 2026-03-29 16:35  
**현재 상태**: 백로그 40% 감소했으나 근본 문제 미해결  
**핵심 이슈**: **생산-소비 속도 불균형**으로 인한 필연적 백로그  
**사용자 지적**: "소스보니까 현재 단순 sleep하는데 구조개선해서 안정적인 전송하도록 하는게 중요하지는 않아?"

---

## 1. 현재 구조의 근본적 문제

### 1.1 아키텍처 개요

```
Google TTS API (비실시간 일괄 생성)
         ↓
    [빠른 프레임 푸시: 60ms/청크]
         ↓
  _pipecat_pcm_queue (Python Queue)
         ↓
_pcm_sender_thread_main (전용 스레드)
  - PCM 청크 → RTP 패킷 변환
  - 20ms 간격으로 sleep
  - 패킷을 _tts_udp_out_queue에 투입
         ↓
_drain_tts_udp_out_queue (asyncio 태스크)
  - UDP sendto() 호출
         ↓
    네트워크 (단말)
```

### 1.2 병목 지점 (Bottleneck)

**문제 1: 고정 20ms Sleep 강제**

```python
# rtp_relay.py line 1728
if sleep_needed > 0:
    self._wait_until_send_deadline(target_time)
```

**현재 로직**:
- 각 RTP 패킷을 **정확히 20ms 간격**으로 전송하기 위해 `sleep` + `yield` + `busy-wait`
- 청크당 25개 패킷 → **500ms 고정 소요**
- **TTS가 60ms마다 청크 생성** → **PCM 큐 백로그 필연적 발생**

**근본 원인**:
- **실시간 재생을 위한 20ms 간격 준수**는 맞지만
- **이미 생성된 오디오를 실시간처럼 천천히 보내는 구조**
- TTS가 **비실시간**이라 초반에 모든 오디오를 빠르게 생성 → **큐에 쌓임**

### 1.3 왜 이 구조인가?

**설계 의도**:
1. **단말의 실시간 재생 요구사항**: RTP는 20ms 간격으로 패킷 도착 기대
2. **Jitter Buffer 한계**: 패킷이 한꺼번에 도착하면 버퍼 오버플로우
3. **네트워크 부하 방지**: 버스트 전송 시 네트워크 혼잡 가능

**하지만**:
- Google TTS는 **스트리밍 미지원** → 전체 오디오 일괄 생성
- 생산 속도(60ms/청크) << 소비 속도(500ms/청크)
- **큐 백로그 누적 불가피**

---

## 2. 구조 개선 방향

### 2.1 근본 해결: TTS 스트리밍 전환

**목표**: 생산 속도 = 소비 속도

**방법**: Google TTS → 스트리밍 TTS 전환
- **Azure Speech Service**: Streaming API 지원
- **ElevenLabs**: WebSocket 스트리밍
- **Deepgram Aura**: 실시간 TTS

**효과**:
```
현재: TTS 생성 60ms/청크 → 큐 쌓임 → RTP 500ms/청크 소비
개선: TTS 생성 500ms/청크 (실시간) → 큐 쌓이지 않음 → RTP 500ms/청크 소비
```

**장점**:
- ✅ **백로그 완전 제거** (생산 = 소비)
- ✅ **메모리 사용량 감소** (큐에 최대 1~2개 청크만 대기)
- ✅ **응답 시작 지연 감소** (첫 청크 즉시 재생)

**단점**:
- ⚠️ **비용 증가** (Azure: $16/1M chars, Google: $4/1M chars)
- ⚠️ **TTS 품질 차이** (품질 비교 테스트 필요)
- ⚠️ **통합 복잡도** (WebSocket 연결, 에러 처리)

### 2.2 중간 해결책: 적응형 전송 속도

**목표**: 백로그 발생 시 전송 속도 자동 증가

**방법 A: 큐 크기 기반 동적 간격**

```python
def _get_adaptive_packet_interval(self) -> float:
    """큐 백로그에 따라 패킷 간격 조정"""
    queue_size = self._pipecat_pcm_queue.qsize()
    
    if queue_size > 15:
        return 0.012  # 12ms (긴급 모드, 1.67배 속도)
    elif queue_size > 10:
        return 0.015  # 15ms (버스트 모드, 1.33배 속도)
    elif queue_size > 5:
        return 0.018  # 18ms (약간 빠름, 1.11배 속도)
    else:
        return 0.020  # 20ms (정상)
```

**적용 위치**:
```python
# line 1386
# interval_sec = self._RTP_PACKET_MS / 1000.0  # 고정 0.020초
interval_sec = self._get_adaptive_packet_interval()  # 동적 조정
```

**효과**:
- 큐 15개 시 12ms 간격 → **청크당 300ms** (기존 500ms 대비 40% 단축)
- 백로그 해소 속도: **생산 60ms vs 소비 300ms** → 여전히 느리지만 **5배에서 2.5배로 개선**
- **추가 백로그 누적 속도 감소**

**리스크**:
- 단말 jitter buffer가 12~15ms 간격 처리 못할 수 있음
- 테스트 필요: Asterisk, FreeSWITCH 등 주요 SIP 단말 호환성

**방법 B: 청크 단위 버스트 + 청크 간 갭**

```python
# 청크 내 25개 패킷을 빠르게 전송 (10ms 간격)
# 청크 간에는 250ms 갭
# 전체 시간: 25 * 10ms + 250ms = 500ms (동일)
# 하지만 단말은 청크 단위로 버퍼링 가능
```

**장점**:
- 전체 전송 시간 동일 (500ms/청크)
- 단말 버퍼가 청크 단위로 처리 가능

**단점**:
- 단말 호환성 리스크 높음
- 청크 내 버스트가 네트워크 혼잡 유발 가능

### 2.3 단기 완화: 백로그 제한 + 드롭 정책

**목표**: 큐 크기 제한으로 메모리 폭발 방지

**방법**:
```python
# PCM 큐 투입 시점 (send_audio_to_caller)
MAX_QUEUE_SIZE = 15

if self._pipecat_pcm_queue.qsize() >= MAX_QUEUE_SIZE:
    # 오래된 청크 드롭 (중요도 낮은 청크 선별)
    try:
        dropped_chunk = self._pipecat_pcm_queue.get_nowait()
        logger.warning("pcm_chunk_dropped_queue_full",
                      call_id=self._call_id,
                      queue_size=MAX_QUEUE_SIZE,
                      dropped_bytes=len(dropped_chunk),
                      note="PCM 큐 가득 참 — 오래된 청크 드롭")
    except queue.Empty:
        pass

self._pipecat_pcm_queue.put(pcm_data)
```

**효과**:
- **큐 크기 15개로 제한** (메모리 안정화)
- 백로그가 15개 초과 시 **오래된 청크 드롭** → 최신 오디오 우선

**단점**:
- ❌ **오디오 손실 발생** (일부 문장 건너뜀)
- 사용자 경험 저하 가능

**평가**: 비권장 (오디오 품질 저하)

---

## 3. 현재 구조의 한계

### 3.1 Sleep 기반 패이싱의 문제

**코드 분석**:

```python
# line 1664~1665
ideal_target = self._rtp_base_time + (self._rtp_packets_sent_total * interval_sec)
target_time = ideal_target

# line 1728~1729
if sleep_needed > 0:
    self._wait_until_send_deadline(target_time)
```

**동작**:
1. **절대 시간 격자 계산**: `base_time + (패킷_수 × 20ms)`
2. **현재 시각과 비교**: `목표 시각 - 현재 시각 = sleep_needed`
3. **대기**: `sleep(sleep_needed - spin_cap)` + `yield` + `busy-wait`

**문제점**:
- ✅ **타이밍은 정확함** (절대 시간 기준, 오차 누적 방지)
- ❌ **각 패킷마다 sleep** → 청크 처리가 **500ms 고정**
- ❌ **큐 백로그를 고려하지 않음** → 백로그가 쌓여도 속도 변화 없음

### 3.2 왜 sleep이 문제인가?

**시나리오**:
1. TTS가 0.968초에 16개 청크(244KB) 생성 완료
2. RTP 송신 스레드는 **16개 × 500ms = 8초** 소요
3. **생산 완료 후 7초 동안** 나머지 청크가 큐에 대기
4. 사용자는 **실시간으로 듣는데** 오디오가 **7초 늦게 도착** → 끊김

**비유**:
- 요리사(TTS)가 1초에 접시 16개 완성
- 서빙(RTP)이 **한 접시당 30초씩** 나르기
- 손님(사용자)은 **접시를 기다리며** 굶주림
- **요리는 다 됐는데 서빙이 느림** → 구조적 병목

### 3.3 이전 수정의 한계

**수정 1: `_pcm_keepalive_queue_timeout_sec()`**
```python
if self._pipecat_pcm_queue.qsize() > 0:
    return 0.02  # 즉시 get
```

**효과**:
- ✅ 큐가 **비었다가 채워질 때** 블로킹 제거
- ❌ 큐가 **계속 차 있을 때**는 효과 없음 (여전히 500ms/청크)

**수정 2: `ai_rtp_keepalive_interval_sec` 단축 (8.0 → 3.0)**
```yaml
ai_rtp_keepalive_interval_sec: 3.0
```

**효과**:
- ✅ keepalive 갭에서의 뭉개짐 감소
- ❌ TTS 응답 재생 시 백로그 문제는 해결 안됨

**종합**:
- 이전 수정은 **증상 완화** (백로그 40% 감소)
- 하지만 **근본 원인(생산-소비 불균형) 미해결**

---

## 4. 제안: 3단계 구조 개선

### 4.1 Phase 1: 적응형 패킷 간격 (즉시 적용 가능)

**목표**: 백로그 발생 시 자동으로 전송 속도 증가

**구현**:

```python
# src/media/rtp_relay.py

def _get_adaptive_packet_interval_sec(self) -> float:
    """
    PCM 큐 백로그에 따라 RTP 패킷 간격 동적 조정.
    
    큐 크기    간격     청크 시간    소비 속도
    0~5개     20ms     500ms       정상 (1.0x)
    6~10개    18ms     450ms       약간 빠름 (1.11x)
    11~15개   15ms     375ms       버스트 (1.33x)
    16개+     12ms     300ms       긴급 (1.67x)
    
    Returns:
        패킷 간격 (초)
    """
    if self._pipecat_pcm_queue is None:
        return 0.020
    
    queue_size = self._pipecat_pcm_queue.qsize()
    
    # 큐 백로그 기반 동적 간격
    if queue_size > 15:
        return 0.012  # 12ms (긴급)
    elif queue_size > 10:
        return 0.015  # 15ms (버스트)
    elif queue_size > 5:
        return 0.018  # 18ms (약간 빠름)
    else:
        return 0.020  # 20ms (정상)

# line 1386 수정
# interval_sec = self._RTP_PACKET_MS / 1000.0  # 고정 0.020초
interval_sec = self._get_adaptive_packet_interval_sec()  # 동적 조정

# line 1664~1665 수정 (목표 시간 계산 시 동적 간격 반영)
# 각 패킷마다 간격이 다를 수 있으므로, 누적 시간 계산 로직 개선 필요
# 또는 간격을 청크 단위로 고정 (청크 시작 시 결정)
```

**효과 시뮬레이션**:

| 큐 크기 | 간격 | 청크 시간 | 16개 청크 총 시간 | 백로그 |
|---------|------|-----------|-------------------|--------|
| **현재** | 20ms | 500ms | 8.0초 | 14개 |
| **Phase 1** | 동적 | 평균 350ms | 5.6초 | **예상 8~10개** |

**백로그 감소 메커니즘**:
- 초반(큐 1~5): 20ms 간격 (정상)
- 중반(큐 6~10): 18ms 간격 (소비 속도 11% 증가)
- 후반(큐 11~15): 15ms 간격 (소비 속도 33% 증가)
- **백로그가 쌓이면 자동으로 빠르게 처리** → 백로그 감소

**구현 난이도**: ⭐⭐☆☆☆ (낮음)  
**리스크**: ⭐⭐☆☆☆ (단말 jitter buffer 호환성, 12~20ms는 대부분 허용 범위)

### 4.2 Phase 2: 적응형 버스트 전송 (중기)

**목표**: 백로그 임계값 초과 시 청크 단위 버스트

**구현**:

```python
def _send_chunk_adaptive(self, rtp_packets, base_interval_sec):
    """
    청크 내 패킷을 적응형으로 전송.
    
    큐 백로그가 높으면:
    - 청크 내 패킷 간격 단축 (10~15ms)
    - 청크 간 갭 유지 (100~200ms)
    
    큐 정상이면:
    - 정상 20ms 간격
    """
    queue_size = self._pipecat_pcm_queue.qsize()
    
    if queue_size > 15:
        # 긴급 모드: 청크 내 10ms 간격
        packet_interval = 0.010
        inter_chunk_gap = 0.100  # 청크 간 100ms 갭
    elif queue_size > 10:
        packet_interval = 0.015
        inter_chunk_gap = 0.150
    else:
        packet_interval = base_interval_sec
        inter_chunk_gap = 0.0
    
    # 청크 내 패킷 전송
    for idx, packet in enumerate(rtp_packets):
        # ... (기존 로직)
        
        if idx < len(rtp_packets) - 1:
            # 청크 내 패킷 간격
            self._wait_until_send_deadline(
                time.perf_counter() + packet_interval
            )
    
    # 청크 간 갭
    if inter_chunk_gap > 0:
        time.sleep(inter_chunk_gap)
```

**효과**:
- **백로그 > 15**: 청크당 **250ms + 100ms = 350ms** (30% 단축)
- **백로그 10~15**: 청크당 **375ms + 150ms = 525ms** (약간 증가, 안전)
- **백로그 < 10**: 청크당 **500ms** (정상)

**장점**:
- ✅ 백로그 발생 시 **자동 대응**
- ✅ 청크 간 갭으로 **단말 버퍼 정리 시간** 제공
- ✅ 정상 상태에서는 **20ms 유지** (품질 보장)

**단점**:
- ⚠️ 복잡도 증가
- ⚠️ 청크 간 갭이 **미세 끊김**으로 들릴 수 있음

**구현 난이도**: ⭐⭐⭐☆☆ (중간)  
**리스크**: ⭐⭐⭐☆☆ (청크 간 갭의 음질 영향)

### 4.3 Phase 3: TTS 청크 크기 최적화 (장기)

**목표**: 생산 청크 수 감소 → 백로그 기회 감소

**방법 1: 청크 크기 증가**

```python
# 현재: 16000 bytes/청크 (500ms)
# 제안: 32000 bytes/청크 (1000ms)
```

**효과**:
- 청크 수 **절반 감소** (16개 → 8개)
- 청크당 처리 시간 **2배 증가** (500ms → 1000ms)
- **생산 속도**: 60ms/청크 → 120ms/청크 (청크 크기 2배)
- **소비 속도**: 500ms/청크 → 1000ms/청크
- **불균형**: 8.3배 → 8.3배 (비율 동일, 하지만 청크 수 감소로 백로그 누적 시간 단축)

**장점**:
- ✅ 청크 수 감소 → 큐 오버헤드 감소
- ✅ 백로그 최대값 감소 (14개 → 7개)

**단점**:
- ⚠️ 첫 음성 출력 지연 증가 (500ms → 1000ms)
- ⚠️ TTS API가 청크 크기 제어 지원해야 함

**방법 2: TTS 응답 사전 버퍼링**

```python
# TTS 생성 완료 시점에 전체 오디오를 한 번에 큐에 넣지 말고
# RTP 송신 속도에 맞춰 "throttling" 하여 투입

async def _throttled_tts_push(self, audio_frames):
    """TTS 프레임을 RTP 소비 속도에 맞춰 투입"""
    for frame in audio_frames:
        # 큐 백로그 체크
        while self._pipecat_pcm_queue.qsize() > 10:
            await asyncio.sleep(0.1)  # 백로그 해소 대기
        
        # 프레임 투입
        self.output_transport.send_frame(frame)
```

**효과**:
- ✅ **큐 백로그 10개 이하로 제한**
- ✅ 오디오 손실 없음

**단점**:
- ⚠️ TTS 파이프라인 구조 변경 필요
- ⚠️ Output Transport 로직 수정 복잡

**구현 난이도**: ⭐⭐⭐⭐☆ (높음)

---

## 5. 권장 로드맵

### 5.1 즉시 적용 (1주 내)

**Phase 1-A: 적응형 패킷 간격**

**구현**:
1. `_get_adaptive_packet_interval_sec()` 메서드 추가
2. line 1386에서 호출
3. 로깅 강화: `adaptive_interval_applied` 이벤트

**예상 효과**:
- 백로그 **14개 → 8~10개** (30% 추가 감소)
- 끝부분 끊김 **대폭 완화**

**테스트 방법**:
1. 긴 TTS 응답 (20개 이상 청크) 테스트
2. `pcm_queue_size` 모니터링
3. 사용자 체감 음질 확인

**롤백 조건**:
- 단말에서 패킷 손실 발생 시
- 음질 저하 발생 시

### 5.2 중기 검토 (1개월)

**Phase 1 효과 평가 후 결정**:

**옵션 A: Phase 1 충분하면 종료**
- 백로그 < 10개 유지
- 사용자 끊김 미감지
- → **추가 개선 불필요**

**옵션 B: Phase 2 적용**
- 백로그 여전히 > 10개
- 끊김 지속
- → **적응형 버스트 전송** 적용

### 5.3 장기 전략 (3개월~)

**TTS 스트리밍 전환 검토**:

**조건**:
- Phase 1~2로도 **백로그 < 5개** 달성 실패
- 사용자 클레임 지속
- 비용 증가 수용 가능

**마이그레이션 계획**:
1. Azure/ElevenLabs TTS 품질 테스트
2. 비용 분석 (통화량 × TTS 사용량)
3. 파일럿 테스트 (10% 트래픽)
4. 점진적 전환 (30% → 50% → 100%)

---

## 6. 구현 예시: Phase 1-A

### 6.1 코드 변경

```python
# src/media/rtp_relay.py

def _get_adaptive_packet_interval_sec(self) -> float:
    """
    PCM 큐 백로그에 따라 RTP 패킷 간격 동적 조정.
    
    백로그가 많으면 간격을 단축하여 빠르게 소비.
    단말 jitter buffer 허용 범위 내(12~20ms)에서 조정.
    
    Returns:
        패킷 간격 (초)
    """
    if self._pipecat_pcm_queue is None:
        return 0.020
    
    queue_size = self._pipecat_pcm_queue.qsize()
    
    # 환경변수로 오버라이드 가능
    env_key = "SIPPBX_RTP_ADAPTIVE_INTERVAL"
    if os.environ.get(env_key, "").lower() in ("0", "false", "off"):
        return 0.020  # 적응형 비활성화
    
    # 큐 백로그 기반 동적 간격
    if queue_size > 15:
        interval = 0.012  # 12ms (긴급 모드)
    elif queue_size > 10:
        interval = 0.015  # 15ms (버스트 모드)
    elif queue_size > 5:
        interval = 0.018  # 18ms (약간 빠름)
    else:
        interval = 0.020  # 20ms (정상)
    
    # 로깅 (상태 변화 시에만)
    prev_interval = getattr(self, "_prev_adaptive_interval", 0.020)
    if interval != prev_interval:
        logger.info("adaptive_interval_changed",
                   call_id=self.media_session.call_id,
                   progress="rtp_timing",
                   queue_size=queue_size,
                   prev_interval_ms=int(prev_interval * 1000),
                   new_interval_ms=int(interval * 1000),
                   note="큐 백로그에 따라 패킷 간격 자동 조정")
        self._prev_adaptive_interval = interval
    
    return interval


def _pcm_sender_thread_main(self) -> None:
    """
    TTS PCM 큐 소비·적응형 패이싱·RTP 빌드를 전용 스레드에서 수행.
    """
    # line 1386 수정
    # interval_sec = self._RTP_PACKET_MS / 1000.0
    # → 삭제, 아래에서 각 청크마다 동적 계산
    
    packets_sent = 0
    # ... (기존 초기화)
    
    while self._pipecat_mode and self._pipecat_pcm_queue is not None:
        try:
            # ... (큐 get 로직)
            
            # ✅ 이 청크 처리에 사용할 간격 결정 (청크 시작 시점 기준)
            interval_sec = self._get_adaptive_packet_interval_sec()
            
            # ... (RTP 패킷 생성)
            
            for idx, packet in enumerate(rtp_packets):
                # ... (기존 로직)
                
                # 목표 시간 계산 (동적 간격 반영)
                ideal_target = self._rtp_base_time + (
                    self._rtp_packets_sent_total * interval_sec
                )
                # ... (sleep 로직)
```

### 6.2 config.yaml 추가

```yaml
# RTP 적응형 간격 설정
media:
  # 기존 설정
  ai_rtp_keepalive_interval_sec: 3.0
  
  # 새 설정
  ai_rtp_adaptive_interval_enabled: true
  ai_rtp_adaptive_thresholds:
    normal_queue_max: 5    # 0~5개: 20ms
    slight_queue_max: 10   # 6~10개: 18ms
    burst_queue_max: 15    # 11~15개: 15ms
    emergency_min: 16      # 16개+: 12ms
```

### 6.3 모니터링 강화

```python
# 통화 종료 시 백로그 통계
def _log_pcm_queue_stats_on_call_end(self):
    """통화 종료 시 PCM 큐 백로그 통계 출력"""
    logger.info("pcm_queue_stats_summary",
               call_id=self.media_session.call_id,
               max_queue_size=self._max_pcm_queue_size_observed,
               avg_queue_size=self._avg_pcm_queue_size,
               time_above_threshold_sec=self._time_queue_above_10,
               adaptive_interval_triggered_count=self._adaptive_interval_count,
               note="PCM 큐 백로그 통계 — 개선 효과 평가용")
```

---

## 7. 대안: 근본적 재설계 (고려 사항)

### 7.1 Push → Pull 모델 전환

**현재 (Push)**:
```
TTS → 빠르게 청크 푸시 → 큐 쌓임 → RTP 느리게 소비
```

**제안 (Pull)**:
```
RTP 송신 스레드 → 필요 시점에 TTS 요청 → TTS 온디맨드 생성
```

**구현**:
- TTS를 **lazy 생성**: RTP가 필요할 때까지 생성 지연
- 또는 TTS를 **디스크 캐싱**: 생성 후 파일 저장, RTP가 읽어서 전송

**장점**:
- ✅ 백로그 완전 제거
- ✅ 메모리 사용량 최소화

**단점**:
- ❌ **TTS 지연 증가** (온디맨드 생성 시 대기)
- ❌ 디스크 I/O 오버헤드
- ❌ **구조 대폭 변경** 필요

**평가**: ⚠️ 복잡도 대비 효과 낮음 (비권장)

### 7.2 이중 큐: Fast Lane + Slow Lane

**현재**:
```
PCM Queue (하나) → 모든 청크가 동일한 우선순위
```

**제안**:
```
Fast Queue (우선순위 높음): 첫 3개 청크
Slow Queue (우선순위 낮음): 나머지 청크

RTP 송신 스레드:
- Fast Queue 우선 소비
- Fast 비면 Slow 소비
```

**효과**:
- ✅ **초반 응답 즉시 전송** (첫 3개 청크 우선)
- ✅ 후반 백로그는 허용 (사용자는 이미 듣고 있음)

**단점**:
- ⚠️ 여전히 후반 백로그 존재
- ⚠️ 복잡도 증가

**평가**: ⚠️ 제한적 개선 (비권장)

---

## 8. 비용-효과 분석

### 8.1 Phase 1 (적응형 간격)

| 항목 | 현재 | Phase 1 | 개선 |
|------|------|---------|------|
| 최대 백로그 | 14개 | 8~10개 | **-35%** |
| 구현 시간 | - | 2~3시간 | 낮음 |
| 리스크 | - | 단말 호환성 | 낮음 |
| 비용 | - | 없음 | - |
| 음질 영향 | - | 미미 | 허용 가능 |

**ROI**: ⭐⭐⭐⭐⭐ (매우 높음)

### 8.2 Phase 2 (버스트 전송)

| 항목 | Phase 1 | Phase 2 | 개선 |
|------|---------|---------|------|
| 최대 백로그 | 8~10개 | 5~7개 | **-30%** |
| 구현 시간 | - | 1~2일 | 중간 |
| 리스크 | - | 청크 간 갭 | 중간 |
| 비용 | - | 없음 | - |
| 음질 영향 | - | 약간 | 테스트 필요 |

**ROI**: ⭐⭐⭐☆☆ (중간)

### 8.3 TTS 스트리밍 전환

| 항목 | Phase 2 | 스트리밍 | 개선 |
|------|---------|----------|------|
| 최대 백로그 | 5~7개 | 0~2개 | **-100%** |
| 구현 시간 | - | 1~2주 | 높음 |
| 리스크 | - | TTS 품질 | 높음 |
| 비용 | $4/1M chars | $16/1M chars | **+300%** |
| 음질 영향 | - | 품질 변화 | 테스트 필수 |

**ROI**: ⭐⭐☆☆☆ (낮음, 비용 대비)

---

## 9. 결론 및 즉시 조치

### 9.1 사용자 지적이 정확함

**"구조개선해서 안정적인 전송하도록 하는게 중요하지는 않아?"**

✅ **완전히 동의합니다.**

**이유**:
1. 현재 구조는 **증상 완화**만 가능 (백로그 감소 한계)
2. **sleep 기반 고정 속도**로는 생산-소비 불균형 해소 불가
3. **적응형 메커니즘 없음** → 백로그가 쌓여도 대응 못함

### 9.2 권장 조치

**우선순위 1: Phase 1 (적응형 간격) 즉시 적용**

**이유**:
- ✅ 구현 시간 짧음 (2~3시간)
- ✅ 리스크 낮음 (12~20ms는 대부분 단말 허용)
- ✅ 효과 명확 (백로그 30% 추가 감소 예상)
- ✅ 비용 없음
- ✅ 롤백 쉬움 (환경변수로 비활성화 가능)

**구현 체크리스트**:
- [ ] `_get_adaptive_packet_interval_sec()` 메서드 추가
- [ ] line 1386에서 `interval_sec` 계산 수정
- [ ] line 1664 목표 시간 계산 로직 개선 (동적 간격 반영)
- [ ] 로깅 강화 (`adaptive_interval_changed` 이벤트)
- [ ] config.yaml 설정 추가 (활성화/비활성화 토글)
- [ ] 테스트: 긴 응답(20개 청크) 재생 확인
- [ ] 모니터링: 1주일 운영 후 백로그 통계 수집

**우선순위 2: Phase 2 검토 (Phase 1 효과 확인 후)**

**우선순위 3: TTS 스트리밍 전환 (비용·품질 트레이드오프 평가 후)**

---

## 10. 최종 판단

### 현재 상태: ⚠️ **구조 개선 필요**

**객관적 평가**:
- 현재: 백로그 14개 (7초 지연)
- 사용자 체감: "엄청 많이 개선" + "아직 약간 문제"
- **수용 가능하지만, 최적은 아님**

**구조 개선의 중요성**:
1. ✅ **확장성**: 긴 응답(30초+)에서 백로그 폭발 가능
2. ✅ **안정성**: 현재는 "운 좋게" 14개로 멈춤, 보장 안됨
3. ✅ **품질**: 끝부분 끊김 완전 해소 필요
4. ✅ **유지보수**: 적응형 메커니즘 없으면 케이스별 튜닝 필요

**권고**: 🚀 **Phase 1 (적응형 간격) 즉시 적용 권장**

---

## 11. 다음 단계

1. **Phase 1 구현** (적응형 패킷 간격)
   - 코드 수정: `_get_adaptive_packet_interval_sec()`
   - 테스트: 긴 응답 재생 확인
   - 모니터링: 백로그 통계

2. **1주 후 재평가**
   - 백로그 < 10개 달성 여부
   - 사용자 끊김 감지 여부
   - Phase 2 필요성 판단

3. **장기 전략 수립**
   - TTS 스트리밍 비용 분석
   - 품질 테스트 계획
   - 마이그레이션 로드맵

---

**분석자**: AI Agent (Cursor)  
**분석 시각**: 2026-03-29T16:35:00+09:00  
**권고**: ✅ **구조 개선 필수** (Phase 1 적응형 간격 즉시 적용)  
**예상 효과**: 백로그 14개 → 8~10개 (추가 30% 감소)
