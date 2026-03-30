# RTP 적응형 간격 타이밍 버그 수정 완료

**작성일**: 2026-03-29 17:45  
**버그 발견**: 2026-03-29 17:00 (call_id: 7vV6sKS5nD)  
**수정 파일**: `src/media/rtp_relay.py`  
**관련 리포트**: `2026-03-29_1700_RTP_ADAPTIVE_INTERVAL_CRITICAL_BUG_7vV6sKS5nD.md`

---

## 1. 버그 요약

### 1.1 치명적 증상

**발견 상황** (call_id: 7vV6sKS5nD):
- **80% 오디오 손실** (2120 패킷 예상 → 425 패킷만 전송)
- **817ms Jitter Spike** (정상 12~20ms 간격의 40~68배)
- **타이밍 오차 누적** (600~773ms)
- **사용자 피드백**: "오다가" 부분이 들리지 않음

### 1.2 근본 원인

**타이밍 계산 로직 오류** (`src/media/rtp_relay.py:1755`):

```python
# 버그 코드
ideal_target = self._rtp_base_time + (
    self._rtp_packets_sent_total * current_chunk_interval_sec  # ← 버그!
)
```

**문제 설명**:
- `_rtp_packets_sent_total`: 전체 누적 패킷 수 (예: 2950)
- `current_chunk_interval_sec`: **현재 청크의 간격** (예: 20ms)
- 하지만 **이전 패킷들은 다른 간격**으로 전송됨 (12ms, 15ms, 18ms)

**예시**:
```
패킷 1~100: 12ms 간격 전송 (실제 경과: 1.2초)
패킷 101 계산:
  _rtp_packets_sent_total = 100
  current_chunk_interval_sec = 0.020 (큐 5개 → 정상 모드)
  ideal_target = base_time + (100 × 0.020) = base_time + 2.0초
  
실제 경과: 1.2초
계산 결과: 2.0초
타이밍 오차: 0.8초 (800ms) ← 817ms 갭의 원인!
```

**결과**:
- `sleep_needed = ideal_target - now = 800ms`
- RTP 송신 스레드가 **800ms sleep**
- 이 구간의 **40개 패킷 미전송**
- 단말 Jitter Buffer가 패킷 드롭 → 오디오 누락

---

## 2. 수정 내용

### 2.1 핵심 수정: 누적 절대 시간 추적

**변경 전** (버그):

```python
def _pcm_sender_thread_main(self) -> None:
    packets_sent = 0
    current_chunk_interval_sec = 0.020
    
    while ...:
        # 청크마다 간격 결정
        current_chunk_interval_sec = self._get_adaptive_packet_interval_sec()
        
        for idx, packet in enumerate(rtp_packets):
            # ❌ 잘못된 계산: 현재 간격을 전체 패킷에 적용
            ideal_target = self._rtp_base_time + (
                self._rtp_packets_sent_total * current_chunk_interval_sec
            )
```

**변경 후** (수정):

```python
def _pcm_sender_thread_main(self) -> None:
    packets_sent = 0
    current_chunk_interval_sec = 0.020
    cumulative_ideal_time_sec = 0.0  # ✅ 누적 절대 시간 추적
    
    while ...:
        # 청크마다 간격 결정
        current_chunk_interval_sec = self._get_adaptive_packet_interval_sec()
        
        for idx, packet in enumerate(rtp_packets):
            # ✅ 올바른 계산: 누적 시간 사용
            ideal_target = self._rtp_base_time + cumulative_ideal_time_sec
            
            # ... 패킷 전송 ...
            
            # ✅ 패킷 전송 후 누적 시간 증가
            self._rtp_packets_sent_total += 1
            cumulative_ideal_time_sec += current_chunk_interval_sec
```

### 2.2 수정 위치 목록

**파일**: `src/media/rtp_relay.py`

#### (1) 누적 시간 변수 초기화 (line 1468)

```python
current_chunk_interval_sec = 0.020
cumulative_ideal_time_sec = 0.0  # ← 추가
```

#### (2) 첫 PCM 수신 시 초기화 (line ~1587)

```python
if not hasattr(self, '_rtp_base_time') or self._rtp_base_time is None:
    self._rtp_base_time = time.perf_counter()
    self._rtp_packets_sent_total = 0
    self._rtp_last_send_time = self._rtp_base_time
    cumulative_ideal_time_sec = 0.0  # ← 추가
```

#### (3) 안전장치 초기화 (line ~1728)

```python
if not hasattr(self, '_rtp_base_time') or self._rtp_base_time is None:
    self._rtp_base_time = time.perf_counter()
    self._rtp_packets_sent_total = 0
    self._rtp_last_send_time = self._rtp_base_time
    cumulative_ideal_time_sec = 0.0  # ← 추가
```

#### (4) 새 구간 시작 시 초기화 (line ~1745)

```python
if self._rtp_new_segment_after_empty:
    self._rtp_base_time = time.perf_counter()
    self._rtp_packets_sent_total = 0
    self._rtp_last_send_time = self._rtp_base_time
    cumulative_ideal_time_sec = 0.0  # ← 추가
```

#### (5) ideal_target 계산 변경 (line ~1755)

```python
# Before
ideal_target = self._rtp_base_time + (
    self._rtp_packets_sent_total * current_chunk_interval_sec
)

# After
ideal_target = self._rtp_base_time + cumulative_ideal_time_sec
```

#### (6) Soft Resync 시 초기화 (line ~1778)

```python
if sleep_needed < -resync_thr:
    now_before_sleep = time.perf_counter()
    self._rtp_base_time = now_before_sleep
    self._rtp_packets_sent_total = 0
    cumulative_ideal_time_sec = 0.0  # ← 추가
```

#### (7) expected_from_base_ms 계산 변경 (line ~1831)

```python
# Before
expected_from_base_ms = self._rtp_packets_sent_total * current_chunk_interval_sec * 1000

# After
expected_from_base_ms = cumulative_ideal_time_sec * 1000
```

#### (8) 타이밍 오차 1초+ 리셋 (line ~1890)

```python
if abs(current_error_ms) > 1000.0:
    self._rtp_base_time = time.perf_counter()
    self._rtp_packets_sent_total = 0
    cumulative_ideal_time_sec = 0.0  # ← 추가
```

#### (9) 패킷 전송 후 누적 시간 증가 (line ~1901)

```python
self._rtp_last_send_time = now_after_sleep
self._rtp_packets_sent_total += 1
cumulative_ideal_time_sec += current_chunk_interval_sec  # ← 추가
```

#### (10) behind_schedule 로그 (line ~1820)

```python
expected_from_base_ms=round(cumulative_ideal_time_sec * 1000, 2)  # ← 수정
```

#### (11) adaptive_interval_changed 로그 (line ~1719)

```python
logger.info("adaptive_interval_changed",
           # ... 기존 필드 ...
           cumulative_ideal_time_sec=round(cumulative_ideal_time_sec, 3),  # ← 추가
           note="큐 백로그에 따라 패킷 간격 자동 조정")
```

#### (12) chunk_sent_complete 로그 (line ~2040)

```python
logger.info("rtp_pcm_chunk_sent_complete",
           # ... 기존 필드 ...
           cumulative_ideal_time_sec=round(cumulative_ideal_time_sec, 3),  # ← 추가
           note="PCM 청크 RTP 전송 완료")
```

#### (13) soft_resync 로그 (line ~1797)

```python
logger.info("rtp_schedule_soft_resync",
           # ... 기존 필드 ...
           cumulative_time_reset=True,  # ← 추가
           note="스케줄 대폭 지연 — base_time·누적시간 재앵커")
```

---

## 3. 수정 원리

### 3.1 누적 절대 시간 추적

**기존 방식** (버그):
```python
# 각 패킷의 목표 시각 = base_time + (전체_패킷_수 × 현재_간격)
ideal_target = base_time + (packets_sent_total × current_interval)
```

**문제**:
- 간격이 12→15→18→20ms로 변경
- 하지만 **전체 패킷 수에 현재 간격을 곱함**
- **이전 패킷의 실제 간격 무시** → 타이밍 오차

**새 방식** (수정):
```python
# 초기화
cumulative_ideal_time = 0.0

# 각 패킷 전송 시
ideal_target = base_time + cumulative_ideal_time
cumulative_ideal_time += current_interval  # 패킷마다 증가
```

**장점**:
- **실제 전송 간격을 누적 시간에 반영**
- 간격이 변경되어도 **타이밍 오차 발생 안 함**
- 절대 시간 격자가 **실제 전송과 일치**

### 3.2 시뮬레이션 비교

**시나리오**: 100개 패킷 전송, 처음 50개는 12ms, 나머지 50개는 20ms

#### 기존 방식 (버그)

| 패킷 | 실제 경과 | 계산 (버그) | 오차 |
|------|-----------|-------------|------|
| 50 | 0.600초 (50×12ms) | 1.000초 (50×20ms) | +400ms |
| 100 | 1.600초 (50×12+50×20) | 2.000초 (100×20ms) | +400ms |

**결과**: 400ms sleep → 패킷 20개 분량 미전송

#### 새 방식 (수정)

| 패킷 | 실제 경과 | 누적 시간 | 오차 |
|------|-----------|-----------|------|
| 50 | 0.600초 | 0.600초 (0+50×12ms) | 0ms |
| 100 | 1.600초 | 1.600초 (0.6+50×20ms) | 0ms |

**결과**: 타이밍 오차 없음 → 패킷 정상 전송

### 3.3 Soft Resync 시 동작

**base_time 재설정 시**:
```python
if sleep_needed < -resync_thr:
    self._rtp_base_time = now
    self._rtp_packets_sent_total = 0
    cumulative_ideal_time_sec = 0.0  # ← 함께 초기화
```

**필요성**:
- base_time을 "지금"으로 재설정
- 하지만 cumulative_time은 **과거 기준**
- → **함께 초기화해야 타이밍 일치**

---

## 4. 예상 효과

### 4.1 즉시 효과

**817ms 갭 해소**:
- 타이밍 계산 오류 제거 → **800ms sleep 없음**
- 예상: **갭 < 50ms** (정상 범위)

**80% 손실 해소**:
- 패킷 전송 중단 없음
- 예상: **손실률 < 5%** (네트워크 손실만)

**타이밍 오차 감소**:
- 누적 오차 제거
- 예상: **오차 < 50ms** (CPU 스케줄링 지터만)

### 4.2 적응형 간격 효과 (수정 후)

**백로그 감소**:
- 기존: 14~18개 (버그 포함)
- 수정 후: **10개 이하** 예상 (버그 없이 간격 가속)

**전송 시간 단축**:
```
16개 청크 (400 packets):
- 고정 20ms: 400 × 0.020 = 8.0초
- 적응형 (평균 15ms): 400 × 0.015 = 6.0초 ← 25% 단축
```

**interval_violations 감소**:
- 기존: 25.6% (타이밍 오차 때문)
- 수정 후: **< 5%** 예상 (CPU 지터만)

---

## 5. 수정 전후 비교

### 5.1 타이밍 계산

| 항목 | 기존 (버그) | 수정 후 |
|------|-------------|---------|
| 목표 시각 | `base_time + (packets_total × current_interval)` | `base_time + cumulative_ideal_time` |
| 간격 반영 | 현재 간격만 (이전 무시) | 실제 전송 간격 누적 |
| 타이밍 오차 | 600~800ms 누적 | < 50ms (CPU 지터) |
| Soft Resync | base_time + packets_total 초기화 | base_time + cumulative_time 초기화 |

### 5.2 패킷 전송

| 항목 | 기존 (버그) | 수정 후 |
|------|-------------|---------|
| Jitter Spike | 817ms | < 50ms |
| 손실률 | 80% | < 5% |
| 전송 패킷 | 425 / 2120 | ~2000 / 2120 |
| 백로그 최대 | 18개 | 10개 이하 예상 |

---

## 6. 테스트 방법

### 6.1 수정 검증 테스트

**단계 1: 백엔드 재시작**

```bash
# 터미널에서 기존 프로세스 종료 (Ctrl+C)
# 재시작
python sip-pbx/src/main.py
```

**단계 2: 테스트 통화**

- 긴 응답(20개+ 청크) 유도: "내일 날씨 자세히 알려줘"
- 짧은 응답 유도: "안녕"

**단계 3: 로그 확인**

```bash
# 817ms 갭 재발 여부
rg "jitter_spike.*interval_max_ms: [7-9][0-9]{2}" logs/app.log

# 타이밍 오차 (100ms 이상 drift)
rg "timing_drift_detected.*accumulated_error_ms: [1-9][0-9]{2}" logs/app.log

# 적응형 간격 동작 (cumulative_ideal_time_sec 로그)
rg "adaptive_interval_changed" logs/app.log | tail -20

# 청크 전송 완료 (cumulative_ideal_time_sec 추적)
rg "rtp_pcm_chunk_sent_complete" logs/app.log | tail -20
```

**기대 결과**:
- `jitter_spike`: **없음** (또는 < 100ms)
- `timing_drift_detected`: **없음** (또는 < 100ms)
- `cumulative_ideal_time_sec`: **증가 패턴 확인** (예: 0.5 → 1.0 → 1.5)
- `adaptive_interval_changed`: **정상 작동** (큐 크기에 따라 12~20ms)

### 6.2 안정성 테스트

**장시간 통화**:
- 30초 이상 긴 응답 유도
- 백로그 최대값 확인 (18개 → 10개 이하?)

**연속 통화**:
- 10회 연속 통화
- 각 통화마다 로그 확인

**스트레스 테스트**:
- 동시 통화 3개
- 각 통화의 RTP 품질 확인

---

## 7. 롤백 옵션

버그 수정 후에도 문제가 발생하면 **적응형 간격 비활성화** 가능:

### 방법 1: config.yaml 수정

```yaml
# config/config.yaml
media:
  ai_rtp_adaptive_interval:
    enabled: false  # ← 변경
```

### 방법 2: 환경변수 (재시작 불필요)

```bash
$env:SIPPBX_RTP_ADAPTIVE_INTERVAL="0"
```

**복구**:
```bash
$env:SIPPBX_RTP_ADAPTIVE_INTERVAL="1"
```

---

## 8. 추가 개선 로깅

### 8.1 새로운 로그 필드

#### `adaptive_interval_changed`

```json
{
  "event": "adaptive_interval_changed",
  "cumulative_ideal_time_sec": 1.234  ← 추가
}
```

#### `rtp_pcm_chunk_sent_complete`

```json
{
  "event": "rtp_pcm_chunk_sent_complete",
  "cumulative_ideal_time_sec": 1.500  ← 추가
}
```

#### `rtp_schedule_soft_resync`

```json
{
  "event": "rtp_schedule_soft_resync",
  "cumulative_time_reset": true  ← 추가
}
```

### 8.2 로그 활용

**타이밍 오차 추적**:
```bash
rg "rtp_packet_timing_absolute" logs/app.log | \
  jq '{expected: .expected_time_from_base_ms, actual: .actual_time_from_base_ms, error: .timing_error_ms}'
```

**누적 시간 증가 패턴**:
```bash
rg "cumulative_ideal_time_sec" logs/app.log | tail -50
```

---

## 9. 기술적 배경

### 9.1 왜 절대 시간 추적이 필요한가?

**고정 간격 환경** (기존):
```python
# 모든 패킷이 20ms 간격
ideal_target = base_time + (packets_sent × 0.020)
# 패킷 100: base_time + 2.0초 (정확함)
```

**적응형 간격 환경**:
```python
# 패킷마다 간격이 다름 (12ms, 15ms, 18ms, 20ms)
# 잘못된 계산 (버그):
ideal_target = base_time + (packets_sent × current_interval)
# 패킷 100: base_time + (100 × 0.020) = 2.0초
# 하지만 실제 경과: 1.5초 (평균 15ms)
# 오차: 500ms

# 올바른 계산 (수정):
cumulative_time = sum(각_패킷의_실제_간격)
ideal_target = base_time + cumulative_time
# 패킷 100: base_time + 1.5초 (정확함)
```

### 9.2 RTP 타임스탬프와의 관계

**RTP 타임스탬프**:
- **항상 20ms 단위로 증가** (160 샘플 = 160/8000 = 0.020초)
- 전송 간격과 무관

**실제 전송 간격**:
- 12~20ms로 **동적 변경**
- PCM 큐 백로그 기반

**결론**:
- RTP 타임스탬프: **고정 20ms** (규격)
- 실제 전송: **동적 12~20ms** (최적화)
- 누적 절대 시간: **실제 전송 간격 반영** (정확성)

---

## 10. 체크리스트

### 10.1 수정 완료 항목

- [x] 누적 절대 시간 변수 추가 (`cumulative_ideal_time_sec`)
- [x] 초기화 지점 4곳 수정 (첫 PCM, 안전장치, 새 구간, Soft Resync)
- [x] `ideal_target` 계산 수정
- [x] `expected_from_base_ms` 계산 수정
- [x] 패킷 전송 후 누적 시간 증가
- [x] 로그 필드 추가 (3곳)
- [x] Linter 확인 (에러 없음)

### 10.2 테스트 필요 항목

- [ ] 백엔드 재시작
- [ ] 테스트 통화 (긴 응답)
- [ ] 817ms 갭 재발 확인
- [ ] 타이밍 오차 (< 100ms) 확인
- [ ] 백로그 (< 12개) 확인
- [ ] 손실률 (< 10%) 확인
- [ ] 누적 시간 로그 확인

### 10.3 모니터링 (1주일)

- [ ] 일별 jitter_spike 통계
- [ ] 일별 timing_drift 통계
- [ ] 일별 백로그 최대값
- [ ] 일별 손실률 평균
- [ ] 사용자 피드백 (오디오 품질)

---

## 11. 관련 파일

**수정 파일**:
- `src/media/rtp_relay.py` (line 1468~2040)

**설정 파일**:
- `config/config.yaml` (line 65~71, 적응형 간격 설정)

**관련 리포트**:
- `2026-03-29_1700_RTP_ADAPTIVE_INTERVAL_CRITICAL_BUG_7vV6sKS5nD.md` (버그 분석)
- `2026-03-29_1635_RTP_STRUCTURE_IMPROVEMENT_PROPOSAL.md` (설계)
- `2026-03-29_1640_RTP_ADAPTIVE_INTERVAL_IMPLEMENTATION.md` (구현)

---

## 12. 기대 성능

### 12.1 수정 전 (버그)

```
TTS 16개 청크 (339KB, 10.6초):
- 예상 패킷: 2,120개
- 실제 전송: 425개 (20%)
- 손실: 1,695개 (80%)
- Jitter Spike: 817ms
- 백로그 최대: 18개
- 타이밍 오차: 773ms
```

### 12.2 수정 후 (예상)

```
TTS 16개 청크 (339KB, 10.6초):
- 예상 패킷: 2,120개
- 실제 전송: ~2,015개 (95%)
- 손실: ~105개 (5%, 네트워크 손실)
- Jitter Spike: < 50ms
- 백로그 최대: 10개 이하
- 타이밍 오차: < 50ms
```

**개선율**:
- 손실: 80% → 5% (75%p 개선)
- Jitter: 817ms → 50ms (94% 개선)
- 백로그: 18개 → 10개 (44% 개선)

---

## 13. 결론

### 13.1 수정 완료

**타이밍 계산 버그 수정**:
- ✅ 누적 절대 시간 추적 구현
- ✅ 모든 초기화 지점 수정
- ✅ 로그 강화 (디버깅 용이)

**기대 효과**:
- ✅ 817ms 갭 해소
- ✅ 80% 손실 해소
- ✅ 적응형 간격 정상 작동

### 13.2 다음 단계

**즉시**:
1. 백엔드 재시작
2. 테스트 통화 (긴 응답)
3. 로그 확인 (갭, 오차, 백로그)

**선택 (문제 재발 시)**:
- `config.yaml`에서 `enabled: false` 설정
- 또는 `$env:SIPPBX_RTP_ADAPTIVE_INTERVAL="0"`

**장기**:
- 1주일 모니터링
- 통계 분석
- 사용자 피드백

---

**수정 완료**: 누적 절대 시간 추적 구현 (12곳 수정)  
**예상 효과**: 817ms 갭 해소, 80% 손실 → 5% 손실  
**롤백 방법**: `config.yaml` 또는 환경변수로 비활성화  
**다음 단계**: 백엔드 재시작 후 테스트 통화
