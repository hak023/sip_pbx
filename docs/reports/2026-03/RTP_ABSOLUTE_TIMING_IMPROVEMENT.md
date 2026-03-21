# RTP 절대 시간 기반 타이밍 개선 보고서

## 📋 개요

**작성일**: 2026-03-10  
**목적**: RTP 패킷 전송 타이밍의 불안정성(jitter) 문제를 해결하기 위해 절대 시간 기반 스케줄링 방식으로 개선  
**관련 보고서**: 
- `RTP_TIMING_VALIDATION_REPORT.md` (문제 진단)
- `RTP_TIMING_DEBUG_LOGS.md` (로그 추가)

---

## 🔍 문제 분석 요약

### 기존 방식의 문제점

**상대 시간 기반 스케줄링**:
```python
# 기존 로직 (문제 있음)
last_send_time = time.perf_counter()
for packet in rtp_packets:
    elapsed = time.perf_counter() - last_send_time
    if elapsed < interval_sec:
        sleep_needed = interval_sec - elapsed
        await asyncio.sleep(sleep_needed)
    last_send_time = time.perf_counter()  # ⚠️ 오차 누적!
```

**문제점**:
1. **`asyncio.sleep()` 부정확성**: `asyncio.sleep(0.02)`는 최소 20ms를 보장하지만, 정확히 20ms를 보장하지 않음 (스케줄러 지연, OS 인터럽트 등)
2. **오차 누적**: 각 패킷마다 `last_send_time = now`로 갱신하여 이전 오차가 누적됨
3. **타이밍 불안정**: 실제 간격이 1.02ms ~ 32.40ms로 극심하게 변동 (목표: 20ms)

### 로그 분석 결과

```
평균 간격: 19.02ms (목표: 20ms)
표준편차: 8.36ms
최소 간격: 1.02ms  ⚠️ 너무 짧음 → 네트워크 부하
최대 간격: 32.40ms ⚠️ 너무 김 → 음성 끊김
```

**영향**:
- 음성이 늘어지거나 깨짐
- 네트워크 버스트 발생 (짧은 간격 연속 발생 시)
- 전체 오디오 품질 저하

---

## ✅ 개선 방안: 절대 시간 기반 스케줄링

### 핵심 원리

각 패킷의 전송 시간을 **절대 기준 시간(base_time)으로부터 계산**하여 오차 누적을 방지합니다.

```python
# ✅ 개선된 로직 (절대 시간 기반)
base_time = time.perf_counter()  # 전송 시작 시간 (기준점)
packets_sent_total = 0

for packet in rtp_packets:
    # 목표 전송 시간 = 기준 시간 + (패킷 번호 × 20ms)
    target_time = base_time + (packets_sent_total * 0.020)
    
    # 현재 시간과 비교하여 대기 시간 계산
    now = time.perf_counter()
    sleep_needed = target_time - now
    
    if sleep_needed > 0:
        await asyncio.sleep(sleep_needed)
    
    # 패킷 전송
    send_packet(packet)
    packets_sent_total += 1
```

### 장점

1. **오차 독립성**: 각 패킷의 대기 시간이 이전 패킷의 오차와 무관
2. **자동 보정**: `asyncio.sleep()`이 부정확해도 다음 패킷에서 자동으로 보정
3. **누적 오차 최소화**: 장기적으로 평균 간격이 정확히 20ms에 수렴
4. **안정성**: 표준편차 및 최대/최소 간격 변동이 크게 감소 예상

---

## 🛠️ 구현 내용

### 1. 절대 시간 기반 타이밍 로직 구현

**파일**: `sip-pbx/src/media/rtp_relay.py`

**변경 사항**:

```python
# 타이밍 변수 초기화 (최초 또는 청크 시작 시)
if not hasattr(self, '_rtp_base_time') or self._rtp_base_time is None:
    self._rtp_base_time = time.perf_counter()
    self._rtp_packets_sent_total = 0
    logger.info("rtp_absolute_timing_started",
               call_id=self.media_session.call_id,
               progress="rtp_timing",
               base_time=self._rtp_base_time,
               note="절대 시간 기반 RTP 스케줄링 시작")

for idx, packet in enumerate(rtp_packets):
    # 절대 시간 기반: 목표 전송 시간 계산
    target_time = self._rtp_base_time + (self._rtp_packets_sent_total * interval_sec)
    now_before_sleep = time.perf_counter()
    sleep_needed = target_time - now_before_sleep
    
    # 목표 시간까지 대기 (음수면 이미 지나침)
    if sleep_needed > 0:
        await asyncio.sleep(sleep_needed)
    
    # 실제 전송 시간 기록
    now_after_sleep = time.perf_counter()
    actual_from_base_ms = (now_after_sleep - self._rtp_base_time) * 1000
    expected_from_base_ms = self._rtp_packets_sent_total * self._RTP_PACKET_MS
    current_error_ms = actual_from_base_ms - expected_from_base_ms
    
    # ... 패킷 전송 로직 ...
    
    self._rtp_last_send_time = now_after_sleep
    self._rtp_packets_sent_total += 1
```

### 2. 상세 디버깅 로그 추가

#### 2.1 시작 로그 (`rtp_absolute_timing_started`)

**목적**: 절대 시간 기반 스케줄링 시작 확인  
**조건**: 최초 패킷 전송 시  
**필드**:
- `call_id`: 통화 ID
- `progress`: `"rtp_timing"`
- `base_time`: 기준 시간 (perf_counter)
- `note`: 설명

**예시**:
```json
{
  "event": "rtp_absolute_timing_started",
  "call_id": "abc123",
  "progress": "rtp_timing",
  "base_time": 123456.789,
  "note": "절대 시간 기반 RTP 스케줄링 시작"
}
```

#### 2.2 패킷 타이밍 상세 로그 (`rtp_packet_timing_absolute`)

**목적**: 개별 패킷의 정확한 타이밍 추적  
**조건**: 첫 30개 패킷만 기록 (로그 과부하 방지)  
**필드**:
- `call_id`: 통화 ID
- `progress`: `"rtp_timing"`
- `packet_seq`: 전체 패킷 순서 번호
- `chunk_packet_idx`: 현재 청크 내 패킷 인덱스
- `expected_time_from_base_ms`: 기준 시간으로부터 예상 경과 시간 (ms)
- `actual_time_from_base_ms`: 기준 시간으로부터 실제 경과 시간 (ms)
- `timing_error_ms`: 타이밍 오차 (ms) = actual - expected
- `interval_from_prev_ms`: 이전 패킷과의 실제 간격 (ms)
- `sleep_requested_ms`: 요청한 sleep 시간 (ms)
- `note`: 설명

**예시**:
```json
{
  "event": "rtp_packet_timing_absolute",
  "call_id": "abc123",
  "progress": "rtp_timing",
  "packet_seq": 10,
  "chunk_packet_idx": 2,
  "expected_time_from_base_ms": 200.00,
  "actual_time_from_base_ms": 201.23,
  "timing_error_ms": 1.23,
  "interval_from_prev_ms": 20.15,
  "sleep_requested_ms": 18.50,
  "note": "절대 시간 기반 타이밍 (오차 누적 방지)"
}
```

#### 2.3 간격 위반 경고 (`rtp_interval_violation`)

**목적**: 20ms ± 5ms를 벗어난 패킷 추적  
**조건**: 첫 5개 + 50개마다 기록  
**필드**:
- `call_id`: 통화 ID
- `expected_ms`: 목표 간격 (20ms)
- `actual_ms`: 실제 간격 (ms)
- `violation_count`: 누적 위반 횟수
- `packets_sent`: 현재까지 전송된 패킷 수
- `timing_error_ms`: 기준 시간으로부터의 누적 오차 (ms)
- `note`: 설명

**예시**:
```json
{
  "event": "rtp_interval_violation",
  "call_id": "abc123",
  "expected_ms": 20,
  "actual_ms": 31.5,
  "violation_count": 3,
  "packets_sent": 50,
  "timing_error_ms": 2.34,
  "note": "20ms 간격 이탈 (절대 시간 오차 포함)"
}
```

#### 2.4 타이밍 드리프트 경고 (`rtp_timing_drift_detected`)

**목적**: 누적 타이밍 오차가 100ms 초과 시 경고  
**조건**: 누적 오차 절댓값 > 100ms, 50개마다 기록  
**필드**:
- `call_id`: 통화 ID
- `progress`: `"rtp_timing"`
- `accumulated_error_ms`: 누적 타이밍 오차 (ms)
- `packets_sent`: 현재까지 전송된 패킷 수
- `note`: 설명

**예시**:
```json
{
  "event": "rtp_timing_drift_detected",
  "call_id": "abc123",
  "progress": "rtp_timing",
  "accumulated_error_ms": 123.45,
  "packets_sent": 150,
  "note": "누적 타이밍 오차 큼 - asyncio.sleep 부정확성"
}
```

#### 2.5 통화 종료 시 통계 로그 (`rtp_absolute_timing_summary`)

**목적**: 전체 통화의 RTP 타이밍 성능 평가  
**조건**: `stop_pipecat_mode()` 호출 시  
**필드**:
- `call_id`: 통화 ID
- `progress`: `"rtp_timing"`
- `total_packets_sent`: 총 전송된 패킷 수
- `expected_duration_ms`: 예상 전송 시간 (ms) = 패킷 수 × 20ms
- `actual_duration_ms`: 실제 전송 시간 (ms)
- `timing_error_ms`: 총 타이밍 오차 (ms)
- `timing_error_pct`: 타이밍 오차 비율 (%)
- `note`: 설명

**예시**:
```json
{
  "event": "rtp_absolute_timing_summary",
  "call_id": "abc123",
  "progress": "rtp_timing",
  "total_packets_sent": 500,
  "expected_duration_ms": 10000.00,
  "actual_duration_ms": 10012.34,
  "timing_error_ms": 12.34,
  "timing_error_pct": 0.12,
  "note": "절대 시간 기반 RTP 전송 완료 통계"
}
```

### 3. 타이밍 변수 초기화 및 정리

#### 3.1 `enable_pipecat_mode()`

```python
# ✅ 절대 시간 기반 RTP 타이밍 변수 초기화
self._rtp_base_time = None
self._rtp_packets_sent_total = 0
self._rtp_last_send_time = None
```

#### 3.2 `stop_pipecat_mode()`

```python
# ✅ 절대 시간 기반 RTP 타이밍 통계 로그 출력
if hasattr(self, '_rtp_packets_sent_total') and self._rtp_packets_sent_total > 0:
    total_packets = self._rtp_packets_sent_total
    expected_duration_ms = total_packets * self._RTP_PACKET_MS
    if hasattr(self, '_rtp_base_time') and hasattr(self, '_rtp_last_send_time'):
        actual_duration_ms = (self._rtp_last_send_time - self._rtp_base_time) * 1000
        timing_error_ms = actual_duration_ms - expected_duration_ms
        timing_error_pct = (timing_error_ms / expected_duration_ms * 100) if expected_duration_ms > 0 else 0
        
        logger.info("rtp_absolute_timing_summary", ...)
    
    # 타이밍 상태 리셋
    self._rtp_base_time = None
    self._rtp_packets_sent_total = 0
    self._rtp_last_send_time = None
```

---

## 📊 예상 개선 효과

### 1. 타이밍 안정성

| 지표 | 개선 전 (상대 시간) | 개선 후 (절대 시간, 예상) |
|------|-------------------|-------------------------|
| 평균 간격 | 19.02ms | 19.95ms ~ 20.05ms |
| 표준편차 | 8.36ms | < 3ms |
| 최소 간격 | 1.02ms | > 15ms |
| 최대 간격 | 32.40ms | < 25ms |

### 2. 오디오 품질

- **끊김 감소**: 간격 변동이 줄어들어 음성 끊김 현상 최소화
- **네트워크 부하 안정**: 버스트 전송(짧은 간격 연속) 방지
- **장시간 통화 안정성**: 누적 오차 제거로 긴 통화에서도 타이밍 유지

### 3. 디버깅 용이성

- **실시간 모니터링**: 첫 30개 패킷의 상세 타이밍 추적
- **문제 조기 발견**: `rtp_timing_drift_detected`로 100ms 이상 드리프트 즉시 감지
- **통화 후 분석**: `rtp_absolute_timing_summary`로 전체 통화 성능 평가

---

## 🔧 로그 분석 가이드

### 1. 정상 동작 확인

**첫 패킷 확인**:
```bash
Select-String -Path "app.log" -Pattern "rtp_absolute_timing_started" -Context 0,2
```

**첫 30개 패킷 타이밍 확인**:
```bash
Select-String -Path "app.log" -Pattern "rtp_packet_timing_absolute" | Select-Object -First 30
```

**목표**: `timing_error_ms`가 ±5ms 이내, `interval_from_prev_ms`가 15~25ms 범위

### 2. 타이밍 위반 확인

```bash
Select-String -Path "app.log" -Pattern "rtp_interval_violation"
```

**목표**: `violation_count`가 전체 패킷의 5% 미만

### 3. 드리프트 확인

```bash
Select-String -Path "app.log" -Pattern "rtp_timing_drift_detected"
```

**목표**: 이 로그가 거의 나타나지 않아야 함 (100ms 이상 드리프트는 심각한 문제)

### 4. 통화 종료 통계 확인

```bash
Select-String -Path "app.log" -Pattern "rtp_absolute_timing_summary"
```

**목표**: `timing_error_pct`가 ±1% 이내

### 5. Python 스크립트로 상세 분석

```python
import json
import statistics

timing_errors = []
intervals = []

with open("app.log", "r", encoding="utf-8") as f:
    for line in f:
        if "rtp_packet_timing_absolute" in line:
            try:
                data = json.loads(line)
                timing_errors.append(data.get("timing_error_ms", 0))
                intervals.append(data.get("interval_from_prev_ms", 0))
            except:
                pass

if timing_errors:
    print(f"타이밍 오차 평균: {statistics.mean(timing_errors):.2f} ms")
    print(f"타이밍 오차 표준편차: {statistics.stdev(timing_errors):.2f} ms")
    print(f"타이밍 오차 최소: {min(timing_errors):.2f} ms")
    print(f"타이밍 오차 최대: {max(timing_errors):.2f} ms")

if intervals:
    print(f"\n간격 평균: {statistics.mean(intervals):.2f} ms")
    print(f"간격 표준편차: {statistics.stdev(intervals):.2f} ms")
    print(f"간격 최소: {min(intervals):.2f} ms")
    print(f"간격 최대: {max(intervals):.2f} ms")
```

---

## 🎯 성공 기준

### 최소 목표 (Acceptable)

- ✅ 평균 간격: 19 ~ 21ms
- ✅ 표준편차: < 5ms
- ✅ 최소/최대 간격: 10 ~ 30ms 범위 내
- ✅ 타이밍 오차: < 2% (통화 종료 시)

### 이상적 목표 (Ideal)

- 🎯 평균 간격: 19.5 ~ 20.5ms
- 🎯 표준편차: < 2ms
- 🎯 최소/최대 간격: 15 ~ 25ms 범위 내
- 🎯 타이밍 오차: < 0.5% (통화 종료 시)
- 🎯 `rtp_timing_drift_detected` 발생 없음

---

## 📝 테스트 시나리오

### 1. 단순 통화 테스트

**목적**: 기본 타이밍 안정성 확인  
**절차**:
1. AI 통화 시작 (SIP 1003 → 1004)
2. AI 인사말 재생 (약 5초)
3. 간단한 질문 및 AI 응답 (약 10초)
4. 통화 종료
5. 로그 분석:
   - `rtp_packet_timing_absolute` 첫 30개 확인
   - `rtp_absolute_timing_summary` 확인

**성공 조건**:
- `timing_error_pct` < 1%
- `rtp_interval_violation` < 10회

### 2. 장시간 통화 테스트

**목적**: 누적 오차 방지 확인  
**절차**:
1. AI 통화 시작
2. 여러 차례 질문/응답 반복 (총 5분 이상)
3. 통화 종료
4. 로그 분석:
   - `rtp_timing_drift_detected` 발생 여부
   - 최종 `timing_error_ms` 확인

**성공 조건**:
- `rtp_timing_drift_detected` 발생 없음
- 최종 `timing_error_ms` < 500ms (5분 기준 0.17%)

### 3. 다중 통화 테스트

**목적**: 연속 통화 시 타이밍 변수 리셋 확인  
**절차**:
1. 첫 번째 통화 (30초)
2. 통화 종료 → `rtp_absolute_timing_summary` 확인
3. 두 번째 통화 (30초)
4. 통화 종료 → `rtp_absolute_timing_summary` 확인
5. 두 통화의 `timing_error_pct` 비교

**성공 조건**:
- 두 통화 모두 `timing_error_pct` < 1%
- `rtp_absolute_timing_started` 로그가 각 통화마다 1회씩 기록됨

### 4. 높은 부하 테스트

**목적**: 시스템 부하 시에도 타이밍 유지 확인  
**절차**:
1. AI 통화 중 CPU 부하 생성 (예: `stress` 명령어)
2. 긴 AI 응답 재생 (30초 이상)
3. 로그 분석:
   - `rtp_interval_violation` 발생 빈도
   - `rtp_timing_drift_detected` 발생 여부

**성공 조건**:
- `rtp_interval_violation` < 20회 (전체 패킷의 5% 미만)
- `timing_error_pct` < 2%

---

## 🚀 배포 및 롤백 계획

### 배포

1. **코드 변경 확인**:
   - `sip-pbx/src/media/rtp_relay.py` 수정 완료 확인
2. **로컬 테스트**:
   - 위 테스트 시나리오 1, 2 실행
3. **Production 배포**:
   ```bash
   cd sip-pbx
   git add src/media/rtp_relay.py
   git commit -m "feat: RTP 절대 시간 기반 타이밍 개선 (오차 누적 방지)"
   systemctl restart sip-pbx  # 또는 해당 서비스 재시작 명령어
   ```
4. **배포 후 모니터링**:
   - 첫 통화의 `rtp_absolute_timing_summary` 확인
   - 1시간 동안 `rtp_timing_drift_detected` 발생 여부 모니터링

### 롤백 (필요 시)

만약 타이밍이 더 나빠지거나 예상치 못한 문제 발생 시:

1. **Git Revert**:
   ```bash
   git revert HEAD
   systemctl restart sip-pbx
   ```
2. **기존 로직 복원**:
   - 상대 시간 기반 로직으로 되돌림
3. **문제 분석**:
   - 로그 분석하여 실패 원인 파악
   - 필요 시 `asyncio.sleep()` 대신 `time.sleep()` 또는 다른 타이머 고려

---

## 📌 참고 자료

- **RTP RFC 3550**: Real-time Transport Protocol
- **Python asyncio 문서**: https://docs.python.org/3/library/asyncio.html
- **관련 보고서**:
  - `RTP_TIMING_VALIDATION_REPORT.md`: 문제 진단 및 원인 분석
  - `RTP_TIMING_DEBUG_LOGS.md`: 디버깅 로그 설명
  - `RTP_AUDIO_BREAKDOWN_ANALYSIS.md`: 오디오 끊김 현상 분석

---

## ✅ 체크리스트

- [x] 절대 시간 기반 타이밍 로직 구현
- [x] 상세 디버깅 로그 추가 (6개 이벤트)
- [x] 타이밍 변수 초기화 및 정리 (`enable_pipecat_mode`, `stop_pipecat_mode`)
- [x] 로그 분석 가이드 작성
- [x] 테스트 시나리오 정의
- [ ] 단순 통화 테스트 실행
- [ ] 장시간 통화 테스트 실행
- [ ] 다중 통화 테스트 실행
- [ ] Production 배포

---

**작성자**: AI Assistant  
**검토자**: (사용자 검토 필요)  
**승인자**: (사용자 승인 필요)
