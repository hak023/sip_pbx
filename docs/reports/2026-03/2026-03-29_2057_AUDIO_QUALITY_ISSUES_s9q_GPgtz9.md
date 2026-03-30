# 오디오 품질 문제 분석 리포트

**작성일**: 2026-03-29 20:57  
**Call ID**: `s9q~GPgtz9`  
**상태**: 근본 원인 확인, 수정 필요

---

## 요약

사용자가 두 가지 오디오 품질 문제를 보고:

1. **11:49:56 (UTC 20:49:56)** - "기상감정서는 기상청 홈페이지에서 온라인으로 신청하실 수 있습니다." 응답에서 **경미한 끊김** 발생
2. **11:53:21 (UTC 20:53:21)** - "감사합니다. 좋은 하루 되세요." 응답에서 **완전히 늘어져서 기계음** 발생

RTP dump 및 애플리케이션 로그 분석 결과, **RTP 타이밍 로직의 근본적 결함**을 발견했습니다.

---

## 문제 1: 기상감정서 응답 끊김 (20:49:56)

### 증상
- 응답 시작 부분에서 경미한 끊김 감지

### 근본 원인

#### 1.1 거대한 TTS 청크 간 Gap
```
Line 2731 (app.log):
"pcm_chunk_gap_large": gap_ms=32187.9, chunk_seq=31, queue_size=0
```

- 이전 응답(chunk 30)과 현재 응답(chunk 31) 사이에 **32.2초(32,187ms) gap** 발생
- PCM 큐가 **완전 고갈** (`queue_size: 0`)
- 원인: 사용자 발화("기상감정서 발급법을 알려주세요.") → LLM 처리 10.16초 → TTS API 호출까지의 전체 지연

#### 1.2 Soft Resync 발생
```
Line 2734 (app.log):
"rtp_schedule_soft_resync": ideal_late_ms=382.36, soft_resync_count=1, pcm_queue_size=0
```

- 스케줄이 382ms 지연되어 `soft_resync` 트리거 (임계값 200ms 초과)
- `base_time` 재설정으로 타이밍 격자가 리셋됨

#### 1.3 RTP 전송 재개
```
RTP dump (rtp_tx_s9q_GPgtz9.tsv):
seq 5314: interval=402.561ms (keepalive 이후 첫 미디어)
seq 5315: interval=20.158ms (정상)
seq 5316: interval=19.711ms (정상)
...
```

- 킵얼라이브 이후 첫 미디어 패킷은 402ms 간격으로 전송
- 이후 패킷들은 정상 20ms 간격 회복
- **끊김 체감**: 32초 무음 후 갑작스런 재개로 응답 시작이 어색하게 느껴짐

### 개선 완료 사항
- PCM 큐 크기: 500 → **1000으로 증가** (✅ 완료)
- TTS 청크 간 지연 모니터링 로그 추가 (✅ 완료)

---

## 문제 2: "감사합니다" 응답 기계음 (20:53:21) ⚠️ 심각

### 증상
- 응답이 완전히 늘어지면서 기계음 발생
- 사용자가 "완전 늘어져서 기계음"이라고 명확히 인식

### RTP Dump 증거

```
RTP dump (rtp_tx_s9q_GPgtz9.tsv):
2026-03-29T20:53:21.847  seq 8703  interval=99.901ms  (킵얼라이브 → 미디어 전환)
2026-03-29T20:53:21.864  seq 8704  interval=17.212ms  ⚠️ 비정상
2026-03-29T20:53:21.881  seq 8705  interval=17.188ms  ⚠️ 비정상
2026-03-29T20:53:21.898  seq 8706  interval=17.222ms  ⚠️ 비정상
2026-03-29T20:53:21.916  seq 8707  interval=16.858ms  ⚠️ 비정상
2026-03-29T20:53:21.932  seq 8708  interval=16.990ms  ⚠️ 비정상
2026-03-29T20:53:21.949  seq 8709  interval=17.174ms  ⚠️ 비정상
2026-03-29T20:53:21.966  seq 8710  interval=16.833ms  ⚠️ 비정상
2026-03-29T20:53:21.983  seq 8711  interval=17.124ms  ⚠️ 비정상
2026-03-29T20:53:22.000  seq 8712  interval=17.404ms  ⚠️ 비정상
2026-03-29T20:53:22.018  seq 8713  interval=16.852ms  ⚠️ 비정상
...
(약 25개 패킷이 16~17ms 간격으로 지속)
```

### 애플리케이션 로그 증거

```
Line 15633 (app.log):
"rtp_tts_send_window_stats": {
  "interval_violations_cumulative": 23,  ⚠️ 23건 위반!
  "interval_max_ms": 99.89,              ⚠️ 100ms (5배)
  "interval_min_ms": 17.0,               ⚠️ 17ms (15% 빠름)
  "behind_schedule_cumulative": 332,
  "interval_avg_ms": 20.0,
  "pcm_queue_size": 4
}

Line 15634 (app.log):
"rtp_tts_send_window_jitter_spike": {
  "interval_max_ms": 99.89,
  "interval_min_ms": 17.0,
  "note": "창 내 간격 극단값"
}
```

### 근본 원인

#### 2.1 `_RTP_SCHED_MIN_INTER_SEND_MS = 17.0` 설정 문제

**파일**: `src/media/rtp_relay.py`  
**위치**: Line 85

```85:85:c:\work\workspace_sippbx\sip-pbx\src\media\rtp_relay.py
_RTP_SCHED_MIN_INTER_SEND_MS = 17.0  # 연속 전송 최소 간격 (ms); 20ms 격자에 근접
```

이 상수가 **17ms**로 설정되어 있어, Line 1738-1743의 로직에서:

```1738:1743:c:\work\workspace_sippbx\sip-pbx\src\media\rtp_relay.py
if self._rtp_packets_sent_total > 0:
    min_next = self._rtp_last_send_time + (
        self._RTP_SCHED_MIN_INTER_SEND_MS / 1000.0
    )
    if target_time < min_next:
        target_time = min_next
```

**동작 원리**:
1. `soft_resync`로 `base_time` 재설정 → `_rtp_packets_sent_total = 0`
2. 첫 패킷: `_rtp_packets_sent_total = 0`이므로 `min_next` 제약 없음 → 즉시 전송
3. 두 번째 패킷부터: `target_time < min_next` 체크
4. `ideal_target`(20ms 간격 기반)보다 `min_next`(이전 + 17ms)가 더 빠름
5. **`target_time = min_next`로 강제 조정** → 17ms 간격으로 전송

#### 2.2 왜 17ms로 설정했는가?

주석: "20ms 격자에 근접" - 아마도 약간의 오버헤드를 고려한 것으로 보이지만, **실제로는 17ms 간격으로 강제 전송**되는 부작용 발생.

#### 2.3 오디오 품질 영향

**RTP 간격 17ms의 의미**:
- 정상: 20ms당 160샘플(16kHz) = 초당 8000샘플
- 17ms 전송: 20ms 분량을 17ms에 재생 = **1.176배속(17.6% 빠름)**
- **결과**: 음성이 빠르게 재생되어 **높은 톤의 기계음** 발생
- **Jitter Buffer**: 클라이언트 jitter buffer가 17ms 간격을 보상하지 못하고 그대로 재생

---

## 근본 원인 요약

### 타이밍 로직의 구조적 결함

1. **`soft_resync` 메커니즘의 의도**:
   - 200ms 이상 지연 시 타이밍 격자 재설정으로 "따라잡기" 포기
   - 지금부터 새로운 20ms 격자 시작

2. **`_RTP_SCHED_MIN_INTER_SEND_MS = 17.0`의 의도**:
   - 연속 패킷 간 물리적 최소 간격 보장 (CPU 스케줄링 고려)

3. **두 메커니즘의 충돌**:
   - `soft_resync` 후 `_rtp_packets_sent_total = 0`이 되면서 이상적 격자는 20ms
   - 그러나 `min_next` 제약(이전 + 17ms)이 먼저 도달
   - **`target_time = min_next`로 강제** → 17ms 간격으로 연속 전송
   - 20ms 분량의 오디오를 17ms에 재생 → **17.6% 빠른 재생 = 기계음**

---

## 영향 범위

### 언제 발생하는가?

1. **큐 고갈 후 `soft_resync` 발생 시**
2. **킵얼라이브 이후 첫 미디어 전송 시** (99ms+ 간격 후)
3. **긴 무음 구간 후 응답 재개 시**

### 확인된 사례

- **문제 1 (기상감정서)**: `soft_resync` 발생 → 경미한 끊김 (gap 자체가 주원인)
- **문제 2 (감사합니다)**: 킵얼라이브(505ms 간격) → 첫 미디어(100ms 간격) → **이후 25개 패킷이 17ms 간격으로 전송** → 완전한 기계음 발생

---

## 해결 방안

### 즉시 수정 필요 (긴급)

#### Option 1: `_RTP_SCHED_MIN_INTER_SEND_MS` 제거 또는 비활성화 (권장)

**파일**: `src/media/rtp_relay.py`  
**위치**: Line 1738-1743

**변경 전**:
```python
if self._rtp_packets_sent_total > 0:
    min_next = self._rtp_last_send_time + (
        self._RTP_SCHED_MIN_INTER_SEND_MS / 1000.0
    )
    if target_time < min_next:
        target_time = min_next
```

**변경 후** (제거):
```python
# min_next 제약 제거 - ideal_target (20ms 격자) 사용
# soft_resync 후에도 20ms 간격 유지
```

**또는** (조건부 적용):
```python
# soft_resync 직후가 아닐 때만 min_next 제약 적용
if self._rtp_packets_sent_total > 0 and not schedule_did_resync:
    min_next = self._rtp_last_send_time + (
        self._RTP_SCHED_MIN_INTER_SEND_MS / 1000.0
    )
    if target_time < min_next:
        target_time = min_next
```

#### Option 2: `_RTP_SCHED_MIN_INTER_SEND_MS` 값을 20.0으로 변경

**파일**: `src/media/rtp_relay.py`  
**위치**: Line 85

```python
_RTP_SCHED_MIN_INTER_SEND_MS = 20.0  # 20ms로 증가
```

**효과**: 17ms 강제가 20ms로 변경되어, 최소한 정상 속도 유지

---

## 상세 분석

### 문제 2 상세 타임라인

#### TTS 생성
```
20:53:21.575 - google_tts_api_call (api_call_num=9)
20:53:22.176 - google_tts_api_complete (duration_sec=2.76초)
20:53:22.177 - notifier_endframe_processed (duration_sec=3.359초)
```

- TTS API: 2.76초 소요
- 최종 오디오: 3.359초 분량
- 6개 audio frame 생성 (총 88,332 bytes)

#### PCM 큐 투입
```
chunk_seq 158-163 (기존 응답들)
chunk_seq 163: 20:53:22.178, pcm_bytes=8332, queue_size_after=5
```

- 마지막 청크만 8332 bytes (260ms 분량)
- 큐 크기: 4~5개 유지 (정상 범위)

#### RTP 전송 (seq 8703~8777)

**킵얼라이브 구간** (8695-8702):
```
seq 8701: 20:53:21.241, interval=500.575ms (킵얼라이브)
seq 8702: 20:53:21.746, interval=505.045ms (킵얼라이브)
```

**첫 미디어 패킷**:
```
seq 8703: 20:53:21.847, interval=99.901ms ✅ 킵얼라이브→미디어 전환 (정상)
```

**이후 패킷들** (⚠️ 문제 구간):
```
seq 8704: 20:53:21.864, interval=17.212ms ❌ 17% 빠름
seq 8705: 20:53:21.881, interval=17.188ms ❌ 17% 빠름
seq 8706: 20:53:21.898, interval=17.222ms ❌ 17% 빠름
seq 8707: 20:53:21.916, interval=16.858ms ❌ 16% 빠름
seq 8708: 20:53:21.932, interval=16.990ms ❌ 17% 빠름
seq 8709: 20:53:21.949, interval=17.174ms ❌ 17% 빠름
seq 8710: 20:53:21.966, interval=16.833ms ❌ 17% 빠름
seq 8711: 20:53:21.983, interval=17.124ms ❌ 17% 빠름
seq 8712: 20:53:22.000, interval=17.404ms ❌ 13% 빠름
seq 8713: 20:53:22.018, interval=16.852ms ❌ 17% 빠름
seq 8714: 20:53:22.035, interval=17.395ms ❌ 13% 빠름
seq 8715: 20:53:22.052, interval=16.982ms ❌ 15% 빠름
seq 8716: 20:53:22.069, interval=16.627ms ❌ 17% 빠름
seq 8717: 20:53:22.085, interval=17.272ms ❌ 14% 빠름
seq 8718: 20:53:22.102, interval=16.710ms ❌ 16% 빠름
seq 8719: 20:53:22.119, interval=17.517ms ❌ 12% 빠름
seq 8720: 20:53:22.137, interval=17.015ms ❌ 15% 빠름
seq 8721: 20:53:22.154, interval=17.049ms ❌ 15% 빠름
seq 8722: 20:53:22.171, interval=17.314ms ❌ 13% 빠름
seq 8723: 20:53:22.188, interval=16.875ms ❌ 16% 빠름
seq 8724: 20:53:22.205, interval=17.172ms ❌ 14% 빠름
seq 8725: 20:53:22.222, interval=17.061ms ❌ 15% 빠름
seq 8726: 20:53:22.239, interval=17.014ms ❌ 15% 빠름
seq 8727: 20:53:22.257, interval=17.544ms ❌ 12% 빠름
seq 8728: 20:53:22.274, interval=16.420ms ❌ 18% 빠름
seq 8729: 20:53:22.290, interval=17.152ms ❌ 14% 빠름
seq 8730: 20:53:22.307, interval=17.076ms ❌ 15% 빠름
```

**통계**:
- **23건의 간격 위반** 발생
- **평균 17ms** 간격으로 전송
- **20ms 분량의 오디오를 17ms에 재생** = 1.176배속
- **음높이**: 약 **17.6% 상승** → 명백한 기계음

#### RTP Window Stats

```
Line 15633:
interval_avg_ms: 20.0 (평균은 20ms로 보이지만)
interval_max_ms: 99.89 (킵얼라이브 전환)
interval_min_ms: 17.0 (실제 최소값)
interval_violations_cumulative: 23 (위반 23건)
```

---

## 왜 17ms 간격이 문제인가?

### 오디오 재생 속도

- **RTP 타임스탬프 증가**: 160 units/packet (20ms 분량)
- **실제 전송 간격**: 17ms
- **클라이언트 재생**:
  - Jitter buffer가 패킷 도착 간격(17ms)에 맞춰 재생
  - 20ms 분량을 17ms에 재생 = **1.176배속**
  - **음높이 상승**: 17.6% ↑ (예: 100Hz → 117.6Hz)

### 사용자 체감

- "늘어졌다": Jitter buffer가 불안정하게 동작하며 중간중간 버퍼 부족으로 재생이 끊기거나 늘어지는 구간 발생
- "기계음": 17.6% 빠른 재생으로 음높이가 부자연스럽게 상승
- **두 현상이 동시 발생**: 17ms 간격의 불안정성 + 빠른 재생 = "늘어지면서 기계음"

---

## 코드 로직 분석

### Soft Resync 로직 (Line 1748-1774)

```1748:1774:c:\work\workspace_sippbx\sip-pbx\src\media\rtp_relay.py
# ✅ Soft Resync: 200ms 이상 밀렸을 때만 (완화)
resync_thr = 0.200  # -200ms
schedule_did_resync = False
if sleep_needed < -resync_thr:
    # 한 슬롯 이상 밀림: 구 격자 따라잡기 대신 지금부터 cadence 재시작
    now_before_sleep = time.perf_counter()
    self._rtp_base_time = now_before_sleep
    self._rtp_packets_sent_total = 0  # ⚠️ 카운터 리셋
    target_time = now_before_sleep
    sleep_needed = 0.0
    schedule_did_resync = True
    self.stats["rtp_sched_soft_resync_count"] += 1
    _src = self.stats["rtp_sched_soft_resync_count"]
    if _src <= 15 or _src % 40 == 0:
        logger.info(
            "rtp_schedule_soft_resync",
            call_id=self.media_session.call_id,
            progress="rtp_timing",
            soft_resync_count=_src,
            chunk_inner_idx=idx,
            packets_sent_thread=packets_sent,
            ideal_late_ms=round(
                (now_before_sleep - ideal_target) * 1000.0, 2
            ),
            pcm_queue_size=self._pipecat_pcm_queue.qsize(),
            note="스케줄 200ms 이상 지연 — base_time 재설정 (고정 간격)",
        )
```

**문제점**:
- `_rtp_packets_sent_total = 0`으로 리셋
- 이후 `ideal_target` 계산: `base_time + (0 * 20ms)`, `base_time + (1 * 20ms)`, ...
- 그러나 `min_next` 제약이 17ms 간격을 강제함

### Min_next 제약 로직 (Line 1738-1743)

```1738:1743:c:\work\workspace_sippbx\sip-pbx\src\media\rtp_relay.py
if self._rtp_packets_sent_total > 0:
    min_next = self._rtp_last_send_time + (
        self._RTP_SCHED_MIN_INTER_SEND_MS / 1000.0
    )
    if target_time < min_next:
        target_time = min_next
```

**의도**: CPU 스케줄링 오버헤드를 고려하여 물리적 최소 간격 보장  
**실제**: `soft_resync` 이후 17ms 간격을 **강제**하여 오디오 품질 심각 저하

---

## 적응형 간격은 무관

`config.yaml`에서 `ai_rtp_adaptive_interval.enabled: false`로 이미 비활성화되어 있습니다. 이 문제는 **고정 20ms 간격 로직 내부의 `min_next` 제약**에서 발생한 것이며, 적응형 간격과는 무관합니다.

---

## 권장 수정 (긴급)

### 수정 1: `min_next` 제약 제거 (최우선)

**파일**: `src/media/rtp_relay.py`  
**위치**: Line 1738-1743

```python
# ❌ 제거할 코드
if self._rtp_packets_sent_total > 0:
    min_next = self._rtp_last_send_time + (
        self._RTP_SCHED_MIN_INTER_SEND_MS / 1000.0
    )
    if target_time < min_next:
        target_time = min_next
```

**근거**:
- `ideal_target` (20ms 격자 기반)만으로 충분히 안정적
- `_wait_until_send_deadline()`가 이미 정밀한 타이밍 제어 수행
- `min_next` 제약은 불필요하며, 오히려 오디오 품질을 심각하게 저하시킴

### 수정 2: `_RTP_SCHED_MIN_INTER_SEND_MS` 값 증가 (대안)

**파일**: `src/media/rtp_relay.py`  
**위치**: Line 85

```python
_RTP_SCHED_MIN_INTER_SEND_MS = 20.0  # 17.0 → 20.0으로 변경
```

**효과**: 최소한 정상 속도(20ms) 유지  
**단점**: 근본 문제(min_next 제약 자체) 해결 안됨

---

## 테스트 가이드

### 수정 후 확인 사항

1. **RTP dump 확인**:
   ```bash
   # 모든 패킷이 19~21ms 간격인지 확인
   grep "media" logs/rtp_tx_*.tsv | tail -50
   ```

2. **Window stats 확인**:
   ```bash
   # interval_violations_cumulative: 0 확인
   grep "rtp_tts_send_window_stats" logs/app.log | tail -5
   ```

3. **Jitter spike 경고 없음 확인**:
   ```bash
   grep "rtp_tts_send_window_jitter_spike" logs/app.log | tail -5
   ```

4. **사용자 체감**:
   - "감사합니다. 좋은 하루 되세요." 같은 짧은 farewell 문구 테스트
   - 킵얼라이브 이후 재개되는 응답 테스트
   - 긴 무음 후 응답 재개 테스트

---

## 추가 개선 완료 사항

### PCM 큐 크기 증가
- **이전**: `maxsize=500`
- **이후**: `maxsize=1000`
- **효과**: 32초 gap 같은 극단적 상황에서도 버퍼링 용량 2배 확보

### TTS 청크 간 지연 모니터링
- **로그**: `pcm_chunk_gap_large`
- **임계값**: 100ms 초과 시 경고
- **효과**: Google TTS API 스트리밍 지연을 실시간 추적 가능

---

## 결론

### 문제의 본질

**`_RTP_SCHED_MIN_INTER_SEND_MS = 17.0`** 설정으로 인해:
1. `soft_resync` 후 17ms 간격 강제
2. 20ms 분량 오디오를 17ms에 재생
3. **17.6% 빠른 재생 = 기계음**
4. Jitter buffer 불안정 = 늘어짐

### 긴급도

- **문제 1 (기상감정서 끊김)**: 중간 - 큐 증가로 완화됨
- **문제 2 (감사합니다 기계음)**: **긴급 심각** - 즉시 수정 필요

### 다음 단계

1. **즉시**: `min_next` 제약 제거 또는 조건부 적용
2. **테스트**: 다양한 시나리오에서 오디오 품질 확인
3. **모니터링**: `interval_violations_cumulative`, `rtp_tts_send_window_jitter_spike` 로그 추적

---

## 관련 파일

- `src/media/rtp_relay.py` - RTP 타이밍 로직
- `config/config.yaml` - Line 67: `ai_rtp_adaptive_interval.enabled: false`
- `logs/app.log` - 애플리케이션 로그
- `logs/rtp_tx_s9q_GPgtz9.tsv` - RTP 송신 dump

---

**작성자**: AI Analysis System  
**버전**: 1.0  
**태그**: #오디오품질 #RTP타이밍 #기계음 #긴급수정필요
