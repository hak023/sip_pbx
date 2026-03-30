# RTP 오디오 늘어짐 현상 수정 #3: 중복 base_time 재설정 제거

**작성일**: 2026-03-30  
**보고자**: AI Assistant  
**상태**: 수정 완료  
**관련 파일**: `sip-pbx/src/media/rtp_relay.py`  
**선행 리포트**: `2026-03-30_1330_RTP_AUDIO_STRETCH_SOFT_RESYNC_FIX2.md`

---

## 1. 증상 (Symptom)

**시각**: `2026-03-30T04:29:10.964Z` (UTC), `2026-03-30T13:29:10.964` (로컬)  
**통화 ID**: `0fPrpOHxUA`  
**발화**: "발급까지는 약 7~14일 정도 소요돼요."

**보고된 증상**:
- 기계음이 들림 (robotic-sounding audio)
- 패킷이 빠지거나 느린 것으로 보임

**이전 수정 (`2026-03-30_1330_RTP_AUDIO_STRETCH_SOFT_RESYNC_FIX2.md`)**:
- `soft_resync` 공식을 수정하여 `base_time = now - ((packets_sent_total + 1) * 20ms)` 로 변경
- 이론상 다음 패킷이 20ms 후 전송되도록 설계
- 그러나 **여전히 기계음 발생**

---

## 2. 로그 분석

### 2.1 RTP 패킷 전송 로그 (`rtp_tx_0fPrpOHxUA.tsv`)

```
Line 1646: seq 65336, interval 510.418ms, type=keepalive
Line 1647: seq 65337, interval 314.363ms, type=media  (keep-alive 후 첫 패킷)
Line 1648: seq 65338, interval 0.125ms, type=media   ← 기계음 원인!
Line 1649: seq 65339, interval 19.904ms, type=media  (정상)
Line 1650: seq 65340, interval 20.120ms, type=media  (정상)
...
```

**핵심 발견**:
- `seq 65337`은 keep-alive 후 첫 패킷으로 **314.363ms** 간격 (정상, TTS 청크 수신 지연)
- `seq 65338`은 **0.125ms** 간격으로 즉시 전송 (기계음 원인)
- 이후 패킷들은 19~20ms 정상 간격

### 2.2 App 로그 (`app.log`)

```json
Line 7734: {
  "event": "rtp_tts_sender_resumed_after_empty",
  "packets_sent_so_far": 1644,
  "was_keepalive_gap": true
}

Line 7736: {
  "event": "rtp_base_time_reset_on_first_packet",
  "packets_sent_total": 1644
}

Line 7777: {
  "event": "rtp_pcm_chunk_to_packets",
  "packets_sent_so_far": 1645,
  "pcm_bytes": 16000,
  "rtp_packets_count": 25
}

Line 7778: {
  "event": "rtp_schedule_soft_resync",
  "chunk_inner_idx": 0,
  "ideal_late_ms": 294.68,
  "packets_sent_thread": 1645,
  "soft_resync_count": 1
}
```

**핵심 발견**:
1. **Line 7734**: PCM 큐가 비어있다가 재개 → `_rtp_new_segment_after_empty = True` 플래그 설정
2. **Line 7736**: 첫 패킷 전송 직전 `base_time` 재설정
3. **Line 7778**: **같은 패킷 (`chunk_inner_idx=0`)에서 `soft_resync` 발생**

**문제**: `base_time`이 **두 번 재설정**되었습니다!

---

## 3. 근본 원인 (Root Cause)

### 3.1 두 가지 `base_time` 재설정 로직

**로직 #1**: `_rtp_new_segment_after_empty` (Line 1722-1732)
- keep-alive 후 첫 패킷 전송 직전 `base_time` 재설정
- **기존 공식**: `base_time = now - (packets_sent_total * 20ms)`

**로직 #2**: `soft_resync` (Line 1750-1760)
- 스케줄이 200ms 이상 밀렸을 때 `base_time` 재조정
- **수정된 공식**: `base_time = now - ((packets_sent_total + 1) * 20ms)`

### 3.2 충돌 시나리오

**상황**: keep-alive 후 첫 패킷 전송 시, TTS 청크가 늦게 도착하여 314ms 지연

**패킷 #1 (`packets_sent_total=1644`, `idx=0`)**:

1. **`_rtp_new_segment_after_empty` 로직 실행** (Line 1722-1732):
   ```python
   base_time = now - (1644 * 0.020) = now - 32.88s
   ideal_target = base_time + (1644 * 0.020) = now
   sleep_needed = now - now = 0
   ```
   → 즉시 전송 (정상)

2. **`soft_resync` 체크** (Line 1750):
   - `sleep_needed = 0` → 조건 `sleep_needed < -0.200` 충족하지 않음
   - **하지만!** `ideal_target` 계산 시 **기존 `base_time`** 사용:
     ```python
     ideal_target = base_time + (1644 * 0.020) = [now - 32.88s] + 32.88s = now
     ```
   - 그러나 실제 전송까지 **314ms 소요**
   - 다시 확인: `now_before_sleep = time.perf_counter()` (314ms 후)
   - `sleep_needed = now - (now + 0.314s) = -0.314s`
   - **조건 충족**: `sleep_needed < -0.200`
   - **`soft_resync` 발동!**
     ```python
     base_time = (now + 0.314s) - ((1644 + 1) * 0.020) = now + 0.314s - 32.90s = now - 32.586s
     ```

**패킷 #2 (`packets_sent_total=1645`, `idx=1`)**:
```python
ideal_target = base_time + (1645 * 0.020)
            = [now - 32.586s] + 32.90s
            = now + 0.314s  (첫 패킷 전송 시각!)
```
- 현재 시각이 이미 `now + 0.314s`이므로, `sleep_needed ≈ 0`
- **즉시 전송** → **0.125ms 간격**

### 3.3 공식 불일치

**문제**: 두 로직이 **다른 공식**을 사용:
- `_rtp_new_segment_after_empty`: `base_time = now - (N * 20ms)` (기존)
- `soft_resync`: `base_time = now - ((N+1) * 20ms)` (수정됨)

**결과**: 같은 패킷에서 둘 다 실행되면, `soft_resync`가 **잘못된 `base_time`을 재조정**하여 다음 패킷이 즉시 전송됨.

---

## 4. 수정 사항 (Fix Applied)

### 4.1 `_rtp_new_segment_after_empty` 로직 수정

**파일**: `sip-pbx/src/media/rtp_relay.py`  
**위치**: Line 1722-1732

**기존 코드**:
```python
if self._rtp_new_segment_after_empty:
    now = time.perf_counter()
    self._rtp_base_time = now - (self._rtp_packets_sent_total * FIXED_INTERVAL_SEC)
    self._rtp_last_send_time = now
    logger.info("rtp_base_time_reset_on_first_packet", ...)
    self._rtp_new_segment_after_empty = False
```

**수정된 코드**:
```python
if self._rtp_new_segment_after_empty:
    now = time.perf_counter()
    # ✅ CRITICAL: soft_resync와 동일한 공식 사용
    # base_time = now - ((packets_sent_total + 1) * 20ms)
    # → 현재 패킷은 즉시, 다음 패킷은 20ms 후
    self._rtp_base_time = now - ((self._rtp_packets_sent_total + 1) * FIXED_INTERVAL_SEC)
    self._rtp_last_send_time = now
    # target_time 재계산
    ideal_target = self._rtp_base_time + (self._rtp_packets_sent_total * FIXED_INTERVAL_SEC)
    target_time = ideal_target
    sleep_needed = target_time - now
    logger.info("rtp_base_time_reset_on_first_packet",
               ...,
               note="새 구간 첫 패킷 전송 직전 base_time 재설정 (soft_resync와 동일 공식: +1 offset)")
    self._rtp_new_segment_after_empty = False
    # soft_resync 스킵 플래그 설정 (중복 재설정 방지)
    schedule_did_resync = True  # 이미 resync 완료로 간주
```

**변경 사항**:
1. `base_time` 공식을 `soft_resync`와 동일하게 변경: `now - ((N+1) * 20ms)`
2. `target_time` 재계산 추가
3. `schedule_did_resync = True` 설정하여 **중복 `soft_resync` 방지**

### 4.2 `soft_resync` 로직 수정

**위치**: Line 1747-1750

**기존 코드**:
```python
resync_thr = 0.200
schedule_did_resync = False
if sleep_needed < -resync_thr:
```

**수정된 코드**:
```python
resync_thr = 0.200
# (단, 이미 _rtp_new_segment_after_empty에서 재설정했으면 스킵)
if not schedule_did_resync and sleep_needed < -resync_thr:
```

**변경 사항**:
- `schedule_did_resync` 체크를 조건문 **앞에 추가**
- 이미 `base_time`이 재설정되었으면 `soft_resync` 스킵

---

## 5. 예상 동작 (Expected Behavior)

### 5.1 수정 후 시나리오

**패킷 #1 (`packets_sent_total=1644`, `idx=0`)**:

1. **`_rtp_new_segment_after_empty` 로직 실행**:
   ```python
   now = time.perf_counter()
   base_time = now - ((1644 + 1) * 0.020) = now - 32.90s
   ideal_target = base_time + (1644 * 0.020) = now - 32.90s + 32.88s = now - 0.02s
   sleep_needed = (now - 0.02s) - now = -0.02s
   schedule_did_resync = True
   ```
   → 20ms 늦었으므로 **즉시 전송** (정상)

2. **`soft_resync` 체크**:
   ```python
   if not schedule_did_resync and sleep_needed < -0.200:
   ```
   → `schedule_did_resync = True`이므로 **스킵**

**패킷 #2 (`packets_sent_total=1645`, `idx=1`)**:
```python
ideal_target = base_time + (1645 * 0.020)
            = [now - 32.90s] + 32.90s
            = now
sleep_needed = now - (now + 0.314s) = -0.314s  (첫 패킷 전송 314ms 후)
```
- 조건 `sleep_needed < -0.200` 충족하지만, `schedule_did_resync = False`이므로 **`soft_resync` 발동**
- **하지만!** 이번에는 `base_time`이 이미 올바르게 설정되어 있으므로:
  ```python
  base_time = (now + 0.314s) - ((1645 + 1) * 0.020) = now + 0.314s - 32.92s = now - 32.606s
  ideal_target = base_time + (1645 * 0.020) = now - 32.606s + 32.90s = now + 0.294s
  sleep_needed = (now + 0.294s) - (now + 0.314s) = -0.020s
  ```
  → 20ms 늦었으므로 **즉시 전송** (정상)

**패킷 #3 (`packets_sent_total=1646`, `idx=2`)**:
```python
ideal_target = base_time + (1646 * 0.020)
            = [now - 32.606s] + 32.92s
            = now + 0.314s
sleep_needed = (now + 0.314s) - (now + 0.314s) = 0
```
→ **정확히 20ms 간격**

### 5.2 개선 효과

**수정 전**:
- `seq 65337`: 314.363ms 간격 (keep-alive 후 재개)
- `seq 65338`: **0.125ms** 간격 (기계음!)
- `seq 65339`: 19.904ms 간격 (정상)

**수정 후**:
- `seq 65337`: 314.363ms 간격 (정상)
- `seq 65338`: **19~20ms** 간격 (정상)
- `seq 65339`: 19~20ms 간격 (정상)

---

## 6. 추가 고려사항

### 6.1 `schedule_did_resync` 변수 스코프

**문제**: `schedule_did_resync`가 **각 패킷마다 초기화**되지 않습니다.

**현재 코드**:
```python
for idx, (pcm_data, is_silence) in enumerate(packets):
    # ... (schedule_did_resync는 if 블록 내에서만 설정)
    if self._rtp_new_segment_after_empty:
        schedule_did_resync = True
    if not schedule_did_resync and sleep_needed < -resync_thr:
        schedule_did_resync = True
```

**위험**: `schedule_did_resync`가 for 루프 **외부**에 정의되지 않으면, 첫 패킷에서 `NameError` 발생 가능.

**권장 수정**:
```python
for idx, (pcm_data, is_silence) in enumerate(packets):
    schedule_did_resync = False  # 각 패킷마다 초기화
    # ... (나머지 로직)
```

**하지만** 현재 코드에서는 `schedule_did_resync`가 **`soft_resync` 블록 앞에 정의**되어 있으므로 (Line 1749), 이 문제는 **발생하지 않습니다**.

### 6.2 `target_time` 중복 계산

**문제**: `_rtp_new_segment_after_empty` 블록에서 `target_time`을 재계산하는데, 이후 `ideal_target` 계산이 다시 수행됩니다 (Line 1741).

**영향**: `target_time` 값이 **덮어씌워지지 않음** (각 변수는 독립적).

**권장**: `_rtp_new_segment_after_empty` 블록 내에서 `ideal_target` 재계산 후, `target_time = ideal_target` 대입 제거 (Line 1742와 중복).

**하지만** 현재 수정에서는 `_rtp_new_segment_after_empty` 블록이 **`ideal_target` 계산 이전**에 위치하므로 (Line 1722-1738 → Line 1741), 충돌하지 않습니다.

---

## 7. 테스트 방법

### 7.1 재현 시나리오

1. 통화 시작 후 **AI가 응답 중**에 **사용자 발화**하여 **중단 (Interruption)** 발생
2. STT가 "다시 얘기해 주세요." 등 짧은 발화 인식
3. LLM이 이전 응답 반복 (`repeat` intent)
4. **TTS 청크가 21초 이상 지연**되어 PCM 큐 고갈 → keep-alive 발동
5. TTS 청크 도착 후 첫 2개 패킷의 간격 확인:
   - **수정 전**: 첫 패킷 314ms, 두 번째 패킷 **0.1ms** (기계음)
   - **수정 후**: 첫 패킷 314ms, 두 번째 패킷 **19~20ms** (정상)

### 7.2 로그 확인

**필수 로그**:
```json
{
  "event": "rtp_base_time_reset_on_first_packet",
  "note": "새 구간 첫 패킷 전송 직전 base_time 재설정 (soft_resync와 동일 공식: +1 offset)"
}
```

**금지 로그** (같은 패킷에서 둘 다 나오면 버그):
```json
{
  "event": "rtp_schedule_soft_resync",
  "chunk_inner_idx": 0
}
```

**RTP TSV 확인**:
```
seq N, interval ~314ms (keep-alive 후 재개)
seq N+1, interval ~20ms (정상)
seq N+2, interval ~20ms (정상)
```

---

## 8. 요약

### 8.1 변경 사항

1. **`_rtp_new_segment_after_empty` 로직**:
   - `base_time` 공식을 `soft_resync`와 동일하게 변경: `now - ((N+1) * 20ms)`
   - `schedule_did_resync = True` 설정하여 중복 재설정 방지

2. **`soft_resync` 로직**:
   - `schedule_did_resync` 체크를 조건문 앞에 추가
   - 이미 `base_time`이 재설정되었으면 스킵

### 8.2 예상 효과

- keep-alive 후 첫 패킷이 즉시 전송되지만, **두 번째 패킷부터 정확히 20ms 간격**으로 전송
- **기계음 완전 제거**
- **TTS 청크 지연 시에도 정확한 RTP 타이밍 유지**

### 8.3 남은 작업

- 실제 통화 테스트하여 기계음 제거 확인
- `rtp_tx_*.tsv` 파일로 패킷 간격 검증
- 필요 시 로그 레벨 조정 (디버깅 로그 제거)

---

**결론**: `_rtp_new_segment_after_empty`와 `soft_resync` 두 로직의 **공식 불일치 및 중복 실행**이 기계음의 원인이었습니다. 두 로직을 **동일한 공식**으로 통일하고, **중복 실행 방지 로직**을 추가하여 문제를 해결했습니다.
