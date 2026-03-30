# RTP 전송 구조 재설계 제안

**작성일**: 2026-03-29 18:15 KST  
**상태**: 설계 제안  
**관련 리포트**: `2026-03-29_1810_RTP_ADAPTIVE_INTERVAL_CATASTROPHIC_FAILURE_0M~pwWSh1D.md`

---

## 1. 현재 문제 요약

### 근본 원인
- **동적 간격 변경 + 절대 시간 추적 = 구조적 충돌**
- **강제 리셋 로직이 누적값 파괴** → 타이밍 기준 붕괴
- **복잡도 폭발** → 12곳의 초기화 로직, 4가지 리셋 조건

### 결과
- **패킷 손실률 46.8%**
- **타이밍 오차 5초마다 1초 초과** → 강제 리셋 반복
- **사용자: "전체적으로 완전 뭉개지면서 들렸어"**

---

## 2. 설계 원칙

### 원칙 1: 단순성 (Simplicity First)
> "Simple is better than complex."

- **복잡한 로직은 예측 불가능**
- **디버깅 어려움**
- **유지보수 불가능**

### 원칙 2: RTP 본질 준수
> RTP는 **일정한 간격(20ms)**을 기대

- **Jitter Buffer는 일정한 패킷 도착 가정**
- **간격 변동 = Jitter 증가 = 음질 저하**

### 원칙 3: 생산자-소비자 분리
> PCM 생성 속도 ≠ RTP 전송 속도

- **큐로 완충**
- **전송은 고정 속도**
- **백로그는 큐 크기로 흡수**

---

## 3. 설계 옵션

### Option 1: 고정 간격 + 큰 큐 (★ 최우선 권장)

#### 구조
```
TTS API → PCM Queue (크기: 500개) → RTP Sender (고정 20ms)
```

#### 특징
- **간격**: 완전 고정 20ms
- **PCM Queue 크기**: 200 → **500개** (10초 버퍼)
- **타이밍**: `base_time + (packets_sent * 0.020)`
- **리셋**: 완전 제거

#### 장점
1. **최대 단순성** - 코드 복잡도 최소
2. **예측 가능** - 항상 20ms
3. **Jitter 최소** - 수신 측 안정
4. **디버깅 쉬움** - 로직 명확

#### 단점
1. TTS 버스트 시 큐 백로그 발생 (하지만 500개면 10초 버퍼 → 충분)
2. 백로그 해소 속도 느림 (하지만 TTS는 보통 20ms보다 빠르게 생성)

#### 구현 난이도
- **매우 쉬움** (기존 코드 단순화)
- **1~2시간**

---

### Option 2: 응답별 고정 간격 (백로그 기반 초기 결정)

#### 구조
```
응답 시작 → 백로그 확인 → 간격 결정 (12/15/18/20ms)
→ 해당 응답 끝까지 고정 유지
→ 다음 응답 시작 → 재결정
```

#### 특징
- **응답 시작 시**: PCM Queue 크기로 간격 결정
  - 0~5개: 20ms
  - 6~10개: 18ms
  - 11~15개: 15ms
  - 16개+: 12ms
- **응답 도중**: 절대 변경 안 함
- **타이밍**: `base_time + (packets_sent * fixed_interval)`
- **리셋**: 각 응답 시작 시에만

#### 장점
1. **간격 안정** - 응답 내에서는 고정
2. **백로그 대응** - 큰 백로그는 빠른 간격으로 처리
3. **Jitter 제어 가능** - 응답 내 일정
4. **타이밍 계산 단순** - 곱셈 방식

#### 단점
1. 응답 도중 백로그 증가 시 대응 불가
2. 응답 간 간격 변화 → 약간의 Jitter

#### 구현 난이도
- **중간** (응답 경계 감지 필요)
- **2~3시간**

---

### Option 3: 전문 RTP 스택 사용

#### 라이브러리 후보
1. **PJSIP/PJMEDIA** (C, Python binding 있음)
2. **GStreamer** (rtpbin 플러그인)
3. **PyRTP** (Python 전용, 경량)

#### 장점
- **검증된 타이밍 로직**
- **Jitter Buffer 내장**
- **Production-ready**

#### 단점
- **학습 곡선 높음**
- **의존성 증가**
- **유연성 감소** (커스터마이징 어려움)

#### 구현 난이도
- **높음** (학습 + 통합)
- **1~2주**

---

## 4. 권장 방안: Option 1 (고정 간격 + 큰 큐)

### 이유

1. **안정성 최우선**
   - 복잡한 로직 → 단순한 로직
   - 예측 가능
   - 검증 쉬움

2. **실용성**
   - TTS 생성 속도 ≈ 실시간 (보통 20ms보다 빠름)
   - 큐 백로그는 일시적 (2~3초 내 해소)
   - 500개 큐 = 10초 버퍼 → 충분

3. **시급성**
   - 현재 46.8% 손실 → 즉각 해결 필요
   - 구현 시간 최소 (1~2시간)

### 검증 방법

1. **Jitter 측정**
   - `interval_max - interval_min < 5ms` 목표

2. **손실률 측정**
   - `(TTS 바이트 / 160) - 실제 전송` / `(TTS 바이트 / 160)` < 5%

3. **백로그 모니터링**
   - PCM Queue 최대 크기 < 100개 (정상 범위)

---

## 5. 구현 계획

### Phase 1: 즉시 조치 (긴급)

1. **모든 적응형 간격 로직 제거**
   - `cumulative_ideal_time_sec` 완전 삭제
   - 적응형 간격 변경 로직 제거
   - 간격 변경 로그 제거

2. **고정 20ms 복원**
   ```python
   FIXED_INTERVAL_SEC = 0.020
   ideal_target = base_time + (packets_sent_total * FIXED_INTERVAL_SEC)
   ```

3. **리셋 로직 단순화**
   - 1초 초과 강제 리셋 **제거**
   - Soft Resync(-40ms 초과) **제거** 또는 **완화** (예: -200ms 초과 시에만)

4. **PCM Queue 크기 증가**
   - `queue.Queue(maxsize=200)` → `queue.Queue(maxsize=500)`

### Phase 2: 검증 (1~2일)

1. 테스트 통화 (10통 이상)
2. Jitter/손실률 측정
3. 백로그 패턴 분석
4. 로그 리뷰

### Phase 3: 최적화 (선택)

필요 시 Option 2 (응답별 고정 간격) 검토

---

## 6. 코드 수정 위치

### 6.1 제거할 것

#### `rtp_relay.py`

**Line 1468**: `cumulative_ideal_time_sec` 초기화 삭제
```python
# 삭제:
# cumulative_ideal_time_sec = 0.0
```

**Line 1587, 1728, 1745, 1778, 1890**: 모든 `cumulative_ideal_time_sec = 0.0` 삭제

**Line 1760**: `ideal_target` 계산 복원
```python
# 변경 전:
# ideal_target = self._rtp_base_time + cumulative_ideal_time_sec

# 변경 후:
ideal_target = self._rtp_base_time + (self._rtp_packets_sent_total * FIXED_INTERVAL_SEC)
```

**Line 1901**: 누적 증가 삭제
```python
# 삭제:
# cumulative_ideal_time_sec += current_chunk_interval_sec
```

**Line 1674-1721**: 적응형 간격 변경 로직 전체 제거

**Line 1881-1890**: 1초 초과 강제 리셋 제거
```python
# 삭제:
# if not getattr(self, "_rtp_new_segment_after_empty", False) and abs(current_error_ms) > 1000.0:
#     logger.warning("rtp_timing_drift_reset", ...)
#     self._rtp_base_time = time.perf_counter()
#     self._rtp_packets_sent_total = 0
#     cumulative_ideal_time_sec = 0.0
```

### 6.2 수정할 것

**Line 1467**: 간격 변수 단순화
```python
# 변경 전:
# current_chunk_interval_sec = 0.020

# 변경 후:
FIXED_INTERVAL_SEC = 0.020  # 고정 간격
```

**Line 1831**: 예상 시간 계산 복원
```python
# 변경 전:
# expected_from_base_ms = cumulative_ideal_time_sec * 1000

# 변경 후:
expected_from_base_ms = self._rtp_packets_sent_total * FIXED_INTERVAL_SEC * 1000
```

**Line 1956**: sleep에서 고정 간격 사용
```python
# 변경 전:
# time.sleep(current_chunk_interval_sec)

# 변경 후:
time.sleep(FIXED_INTERVAL_SEC)
```

**PCM Queue 초기화 위치** (추정 line ~400-500, `__init__` 부근):
```python
# 변경 전:
# self._pipecat_pcm_queue = queue.Queue(maxsize=200)

# 변경 후:
self._pipecat_pcm_queue = queue.Queue(maxsize=500)
```

### 6.3 간소화할 것

**Soft Resync 로직 (Line 1774-1800)**:
- 임계값을 `-40ms` → **`-200ms`**로 완화 (또는 완전 제거)
- 작은 지연은 자연스럽게 따라잡게 함

---

## 7. 예상 효과

### 즉시 효과 (Phase 1 완료 후)

| 지표 | 현재 | 목표 |
|------|------|------|
| 패킷 손실률 | 46.8% | **< 5%** |
| Jitter (max-min) | 19ms | **< 5ms** |
| 타이밍 오차 | 1초/5초 | **< 100ms** |
| 강제 리셋 빈도 | 5초마다 | **0** |

### 부가 효과

- **디버깅 시간 90% 감소**
- **코드 라인 수 30% 감소**
- **유지보수성 대폭 향상**

---

## 8. 리스크 관리

### 리스크 1: 백로그 누적

**시나리오**:
- TTS 버스트 생성 (1초에 5초치 오디오)
- PCM Queue 가득 참 (500개)

**완화책**:
- 500개 큐 = 10초 버퍼
- TTS 생성 속도는 보통 실시간보다 빠름
- **실제 발생 가능성: 매우 낮음**

**대응**:
- 로그 모니터링: `pcm_queue_size > 400` 경고
- 필요 시 큐 크기 증가 (500 → 1000)

### 리스크 2: Jitter 증가

**시나리오**:
- 고정 간격이 실제로는 변동 (CPU 스케줄링)

**완화책**:
- `time.sleep()` 대신 **정밀 타이밍** 유지
- `perf_counter()` 기반 절대 시간 추적
- Sleep 후 실제 시간 체크 및 보정

**대응**:
- Jitter 로그 모니터링
- 필요 시 우선순위 높은 스레드로 변경

---

## 9. 단계별 실행 계획

### Step 1: 백엔드 종료 (진행 중)
- 현재 실행 중인 백엔드 종료 완료

### Step 2: 코드 롤백 (긴급, 10분)
1. `cumulative_ideal_time_sec` 관련 코드 전체 제거
2. 고정 20ms 간격으로 복원
3. 적응형 간격 로직 제거
4. 강제 리셋 로직 제거
5. PCM Queue 크기 증가 (200 → 500)

### Step 3: 백엔드 재시작 (1분)
- 수정된 코드 + `config.yaml` 반영

### Step 4: 검증 테스트 (30분)
1. 3~5회 테스트 통화
2. 로그 확인:
   - `rtp_timing_drift_detected` 없는지
   - `rtp_timing_drift_reset` 없는지
   - Jitter < 5ms
   - 손실률 < 5%
3. 사용자 청취 테스트

### Step 5: 모니터링 (1~2일)
- 실제 통화에서 안정성 확인
- Jitter/손실률 추이 관찰
- 백로그 패턴 분석

---

## 10. 코드 변경 상세

### 10.1 제거 대상 (Line 범위)

| 위치 | 내용 | 제거 이유 |
|------|------|----------|
| 1468 | `cumulative_ideal_time_sec = 0.0` | 불필요한 변수 |
| 1587 | 첫 PCM 시 초기화 | 불필요 |
| 1674-1721 | 적응형 간격 변경 로직 | 복잡도·Jitter 증가 |
| 1728 | 안전 체크 시 초기화 | 불필요 |
| 1745 | 새 세그먼트 시 초기화 | 불필요 |
| 1760 | `cumulative_ideal_time_sec` 기반 계산 | 롤백 필요 |
| 1778 | Soft Resync 시 초기화 | 불필요 |
| 1831 | `cumulative_ideal_time_sec` 기반 계산 | 롤백 필요 |
| 1881-1890 | 1초 초과 강제 리셋 | 타이밍 붕괴 원인 |
| 1901 | `cumulative_ideal_time_sec` 증가 | 불필요 |
| 1719, 1820, 2040 | `cumulative_ideal_time_sec` 로그 | 불필요 |

### 10.2 수정 후 코드 (핵심 부분)

```python
def _pcm_sender_thread_main(self):
    """PCM → RTP 변환 및 송신 (고정 20ms 간격)"""
    
    # === 초기화 ===
    packets_sent = 0
    interval_violations = 0
    INTERVAL_TOLERANCE_MS = 5
    empty_timeout_count = 0
    last_was_empty_timeout = False
    behind_schedule_count = 0
    recent_intervals_ms: list = []
    
    # ✅ 고정 간격 (단순성 최우선)
    FIXED_INTERVAL_SEC = 0.020  # 20ms
    
    while self._pipecat_mode and self._pipecat_pcm_queue is not None:
        try:
            queue_wait_start = time.perf_counter()
            pcm_is_keepalive = False
            _get_timeout = self._pcm_keepalive_queue_timeout_sec(packets_sent)
            
            try:
                pcm_data = self._pipecat_pcm_queue.get(timeout=_get_timeout)
            except queue.Empty:
                # ... keepalive 로직 ...
                continue
            
            # ... RTP 패킷 생성 ...
            
            # === base_time 초기화 (첫 PCM 또는 긴 공백 후) ===
            if not hasattr(self, '_rtp_base_time') or self._rtp_base_time is None:
                self._rtp_base_time = time.perf_counter()
                self._rtp_packets_sent_total = 0
                self._rtp_last_send_time = self._rtp_base_time
                logger.info("rtp_base_time_initialized", ...)
            
            # 새 세그먼트 플래그 시 리셋
            if self._rtp_new_segment_after_empty:
                self._rtp_base_time = time.perf_counter()
                self._rtp_packets_sent_total = 0
                self._rtp_last_send_time = self._rtp_base_time
                logger.info("rtp_base_time_reset_on_first_packet", ...)
                self._rtp_new_segment_after_empty = False
            
            # === 타이밍 계산 (단순 곱셈) ===
            ideal_target = self._rtp_base_time + (self._rtp_packets_sent_total * FIXED_INTERVAL_SEC)
            target_time = ideal_target
            
            # 최소 간격 보장
            if self._rtp_packets_sent_total > 0:
                min_next = self._rtp_last_send_time + (self._RTP_SCHED_MIN_INTER_SEND_MS / 1000.0)
                if target_time < min_next:
                    target_time = min_next
            
            now_before_sleep = time.perf_counter()
            sleep_needed = target_time - now_before_sleep
            
            # ✅ Soft Resync: 200ms 이상 밀렸을 때만 (완화)
            # (또는 완전 제거하여 자연스럽게 따라잡게 함)
            if sleep_needed < -0.200:  # -200ms
                now_before_sleep = time.perf_counter()
                self._rtp_base_time = now_before_sleep
                self._rtp_packets_sent_total = 0
                target_time = now_before_sleep
                sleep_needed = 0.0
                logger.info("rtp_schedule_soft_resync", ...)
            
            # === Sleep ===
            if sleep_needed > 0:
                self._wait_until_send_deadline(target_time)
            
            # === 전송 시간 기록 ===
            now_after_sleep = time.perf_counter()
            actual_from_base_ms = (now_after_sleep - self._rtp_base_time) * 1000
            expected_from_base_ms = self._rtp_packets_sent_total * FIXED_INTERVAL_SEC * 1000
            current_error_ms = actual_from_base_ms - expected_from_base_ms
            
            # 간격 확인
            if self._rtp_packets_sent_total > 0:
                interval_from_prev_ms = (now_after_sleep - self._rtp_last_send_time) * 1000
            else:
                interval_from_prev_ms = 0.0
            
            # ✅ 타이밍 오차 로그 (100ms 이상일 때만)
            if abs(current_error_ms) > 100.0 and packets_sent % 50 == 0:
                logger.warning("rtp_timing_drift_detected",
                             accumulated_error_ms=round(current_error_ms, 2),
                             packets_sent=packets_sent,
                             note="누적 타이밍 오차 100ms 초과 (고정 간격)")
            
            # === 패킷 전송 ===
            self._rtp_last_send_time = now_after_sleep
            self._rtp_packets_sent_total += 1
            
            # ... UDP 큐 투입 ...
            
            packets_sent += 1
            
            # === 간격 검증 (Jitter 모니터링) ===
            if interval_from_prev_ms > 0:
                recent_intervals_ms.append(round(interval_from_prev_ms, 2))
                if len(recent_intervals_ms) > 50:
                    recent_intervals_ms.pop(0)
                
                # 간격 이탈 체크
                expected_interval_ms = FIXED_INTERVAL_SEC * 1000
                if abs(interval_from_prev_ms - expected_interval_ms) > INTERVAL_TOLERANCE_MS:
                    interval_violations += 1
            
            # === 주기 로그 (50 패킷마다) ===
            if packets_sent > 0 and packets_sent % 50 == 0 and recent_intervals_ms:
                logger.info("rtp_tts_send_window_stats",
                           window_size=len(recent_intervals_ms),
                           interval_min_ms=min(recent_intervals_ms),
                           interval_max_ms=max(recent_intervals_ms),
                           interval_avg_ms=round(sum(recent_intervals_ms) / len(recent_intervals_ms), 2),
                           interval_std_ms=round(std_dev(recent_intervals_ms), 2),
                           interval_violations=interval_violations,
                           pcm_queue_size=self._pipecat_pcm_queue.qsize(),
                           note="송신 간격 통계 (고정 20ms 목표, Jitter 모니터링)")
```

### 10.3 PCM Queue 크기 증가

**`rtp_relay.py` (추정 line 400-500, `__init__` 부근)**:
```python
# 변경 전:
# self._pipecat_pcm_queue = queue.Queue(maxsize=200)

# 변경 후:
self._pipecat_pcm_queue = queue.Queue(maxsize=500)  # 10초 버퍼 (백로그 흡수)
```

---

## 11. 롤백 체크리스트

- [ ] `cumulative_ideal_time_sec` 변수 선언 제거
- [ ] `cumulative_ideal_time_sec` 모든 초기화 (6곳) 제거
- [ ] `cumulative_ideal_time_sec` 증가 코드 제거
- [ ] `cumulative_ideal_time_sec` 로그 (3곳) 제거
- [ ] `ideal_target` 계산 롤백 (단순 곱셈)
- [ ] `expected_from_base_ms` 계산 롤백 (단순 곱셈)
- [ ] 적응형 간격 변경 로직 (line 1674-1721) 제거
- [ ] 1초 초과 강제 리셋 (line 1881-1890) 제거
- [ ] Soft Resync 임계값 완화 (-40ms → -200ms) 또는 제거
- [ ] PCM Queue 크기 증가 (200 → 500)
- [ ] 모든 `current_chunk_interval_sec` → `FIXED_INTERVAL_SEC` 변경

---

## 12. 장기 전략

### 현재 (긴급)
- **고정 20ms 간격** (Option 1)
- **큰 큐** (500개)
- **단순 로직**

### 향후 (필요 시)
- **응답별 고정 간격** (Option 2) - 백로그 패턴 분석 후 결정
- **전문 RTP 스택** (Option 3) - 대규모 배포 시 검토

---

## 13. 결론

### 권장 방안
**Option 1 (고정 간격 + 큰 큐)** 즉시 구현

### 이유
1. **안정성 최우선** - 예측 가능한 동작
2. **단순성** - 유지보수 용이
3. **시급성** - 즉각 해결 필요 (현재 46.8% 손실)
4. **검증됨** - RTP 표준 방식

### 예상 결과
- **패킷 손실률 < 5%**
- **Jitter < 5ms**
- **타이밍 오차 < 100ms**
- **안정적인 음질**

### 다음 단계
1. 코드 롤백 (10분)
2. 백엔드 재시작 (1분)
3. 테스트 통화 (5분)
4. 검증 (로그 확인)

---

**작성자**: AI Assistant  
**승인 필요**: 사용자 확인 후 구현 진행
