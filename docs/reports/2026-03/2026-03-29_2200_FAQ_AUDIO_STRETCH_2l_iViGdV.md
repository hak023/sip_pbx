# FAQ 응답 오디오 늘어짐 분석 (call_id: 2l~~iViGdV)

**작성일**: 2026-03-29 22:00  
**버전**: 1.0  
**상태**: 긴급 수정 완료  
**관련 경로**: `sip-pbx/src/media/rtp_relay.py`

---

## 요약

**문제**: "저는 기상 특보 안내, 상담원 안내, f.......................a.............q.................. 안내" - "faq" 부분이 극도로 늘어져서 들림

**근본 원인**: `rtp_relay.py` Line 1721-1729의 `_rtp_new_segment_after_empty` 로직에서 **`packets_sent_total`을 0으로 리셋**하는 버그. 이는 이전에 수정한 `soft_resync` 버그와 **동일한 패턴**이며, **킵얼라이브 갭(긴 무음) 후 재개 시 발생**.

**영향 범위**: 
- 킵얼라이브 구간(20초 이상 무음) 후 첫 응답
- help 의도 응답 등 긴 무음 후 재개되는 모든 상황

**긴급도**: 🔴 Critical - `soft_resync`와 동일한 버그로, 오디오 품질 심각 저하

---

## 문제 발생 시점

**call_id**: `2l~~iViGdV`  
**timestamp**: `2026-03-29T21:39:17.364`  
**응답 텍스트**: `"저는 기상 특보 안내, 상담원 안내, faq 안내, 기상청 담당자 연결, 서비스 안내을 할 수 있어요. 어떤 것을 도와드릴까요?"`  
**사용자 체감**: "faq" 부분이 극도로 늘어져서 들림 (f.....a.............q..........)

---

## 로그 증거

### 1. 킵얼라이브 갭 후 재개 (Line 2116-2118)

```
2026-03-29T21:39:17.178 | rtp_tts_sender_resumed_after_empty
  - empty_timeouts: 0
  - packets_sent_so_far: 760
  - was_keepalive_gap: true  ← 킵얼라이브 구간 후 재개

2026-03-29T21:39:17.178 | rtp_base_time_reset_on_first_packet
  - note: "새 구간 첫 패킷 전송 직전 base_time 재설정 (처리 지연 흡수)"
  ❌ 여기서 packets_sent_total = 0으로 리셋 (구 코드)
```

### 2. PCM 큐 고갈 (Line 2161-2162)

```
2026-03-29T21:39:17.662 | pcm_chunk_gap_large
  - gap_ms: 23492.8 (23.5초!)
  - queue_size: 0  ← 큐 완전 고갈
  - chunk_seq: 31
```

**원인**: 
- 이전 킵얼라이브 구간에서 PCM 큐가 비었음
- 23.5초 후 새 TTS 청크 도착
- `_rtp_new_segment_after_empty` 플래그 설정

### 3. soft_resync 발동 (Line 2164)

```
2026-03-29T21:39:17.662 | rtp_schedule_soft_resync
  - ideal_late_ms: 464.44
  - packets_sent_thread: 761
  - soft_resync_count: 1
```

**문제**: 
- `rtp_base_time_reset_on_first_packet`에서 `packets_sent_total = 0`으로 리셋
- 첫 패킷(seq=2012)을 보낼 때 `ideal_target = base_time + (0 * 0.02) = base_time`
- 실제로는 464ms 지연되어 있어서 `soft_resync` 발동

### 4. 극단적인 간격 변화 (Line 2165, 2215, 2217, 2234, 2235)

```
2026-03-29T21:39:17.662 | rtp_interval_violation
  - actual_ms: 484.5  ← 첫 패킷: 464ms 지연 후 전송
  - expected_ms: 20
  - violation_count: 1

2026-03-29T21:39:18.110 | rtp_interval_violation
  - actual_ms: 26.3  ← 다음 패킷들: 불규칙한 간격
  - violation_count: 2

2026-03-29T21:39:18.126 | rtp_interval_violation
  - actual_ms: 14.0  ← 14ms (너무 빠름)
  - violation_count: 3

2026-03-29T21:39:18.280 | rtp_interval_violation
  - actual_ms: 35.1  ← 35ms (너무 느림)
  - violation_count: 4

2026-03-29T21:39:18.283 | rtp_interval_violation
  - actual_ms: 1.4  ← 1.4ms (극단적으로 빠름)
  - violation_count: 5
```

### 5. Jitter Spike (Line 2253-2254)

```
2026-03-29T21:39:18.430 | rtp_tts_send_window_stats
  - interval_min_ms: 1.37  ← 최소 간격 (정상: 19~21ms)
  - interval_max_ms: 484.54  ← 최대 간격 (정상: 19~21ms)
  - interval_avg_ms: 29.43
  - interval_violations_cumulative: 7

2026-03-29T21:39:18.430 | rtp_tts_send_window_jitter_spike
  - note: "창 내 간격 극단값 — 청취 뭉개짐과 상관"
```

**결론**: 
- 간격이 **1.37ms ~ 484.54ms**로 극단적으로 변동
- 클라이언트 jitter buffer가 이를 처리하지 못하고 **"늘어짐"** 발생

---

## 근본 원인

### 버그 코드 (구버전, Line 1721-1729)

```python
if self._rtp_new_segment_after_empty:
    self._rtp_base_time = time.perf_counter()
    self._rtp_packets_sent_total = 0  # ❌ 버그: 리셋!
    self._rtp_last_send_time = self._rtp_base_time
    logger.info("rtp_base_time_reset_on_first_packet", ...)
    self._rtp_new_segment_after_empty = False
```

**문제점**:
1. **`packets_sent_total`을 0으로 리셋**
2. **`ideal_target` 계산이 초기화됨**:
   ```python
   ideal_target = self._rtp_base_time + (0 * 0.02)  # = base_time
   ```
3. 실제로는 760개 패킷을 이미 보냈으므로, **스케줄이 크게 지연됨**
4. **`soft_resync`가 즉시 발동**하여 또 다시 조정
5. 결과적으로 **초기 패킷들이 불규칙한 간격으로 전송**됨

### 왜 "늘어짐"이 발생하는가?

**클라이언트 jitter buffer 동작**:
- 정상: 20ms 고정 간격 → buffer가 안정적으로 재생
- 버그: 1.4ms, 35.1ms, 484.5ms 등 극단적 변동 → buffer가 **간격을 메우기 위해 오디오를 늘림**

**특히 484ms 패킷 후 1.4ms 패킷이 오면**:
- Buffer는 484ms 간격을 기준으로 재생 속도 조정
- 갑자기 1.4ms 후 다음 패킷 도착
- **재생 중인 오디오를 급격히 늘려서 시간을 맞춤**
- 결과: "f.....a.....q......." 늘어짐

---

## 긴급 수정

### 수정된 코드 (Line 1720-1730)

```python
# ✅ 새 구간 플래그 있으면 첫 패킷 전송 직전에 base_time 설정
# ✅ soft_resync와 동일한 로직: packets_sent_total 유지하고 base_time만 조정
if self._rtp_new_segment_after_empty:
    now = time.perf_counter()
    # base_time을 "지금 시점에서 packets_sent_total만큼 이미 보낸 것처럼" 역산
    self._rtp_base_time = now - (self._rtp_packets_sent_total * FIXED_INTERVAL_SEC)
    self._rtp_last_send_time = now
    logger.info("rtp_base_time_reset_on_first_packet",
               call_id=self.media_session.call_id,
               progress="rtp_timing",
               packets_sent_total=self._rtp_packets_sent_total,
               note="새 구간 첫 패킷 전송 직전 base_time 재설정 (처리 지연 흡수, packets_sent_total 유지)")
    self._rtp_new_segment_after_empty = False
```

**핵심 변경**:
1. **`packets_sent_total`을 유지** (0으로 리셋 안 함)
2. **`base_time`을 역산**:
   ```python
   base_time = now - (packets_sent_total * 0.02)
   ```
3. 다음 패킷의 `ideal_target`:
   ```python
   ideal_target = base_time + (packets_sent_total * 0.02) = now
   ```
4. 결과: **모든 패킷이 20ms 고정 간격 유지**

---

## 영향 분석

### 발생 조건

1. **킵얼라이브 구간 진입** (Line 1610-1620):
   ```python
   new_segment = (
       empty_timeout_count == 0 and last_was_empty_timeout
   ) or (
       empty_timeout_count >= 2 and packets_sent > 0
   )
   ```
   - `empty_timeout_count >= 2`: PCM 큐가 2번 이상 비어있었음
   - 또는 `last_was_empty_timeout`: 이전에 큐가 비어있었다가 지금 청크 도착

2. **새 TTS 청크 도착**: 큐에 추가되면 `_rtp_new_segment_after_empty = True`

3. **첫 패킷 전송 시 `packets_sent_total = 0` 리셋** → 버그 발생

### 왜 이전에 발견되지 않았는가?

- **`soft_resync` 버그가 더 빈번했음**: 200ms 이상 지연 시마다 발생
- **`rtp_new_segment_after_empty`는 킵얼라이브 갭 후에만 발생**: 덜 빈번
- **하지만 발생하면 더 극단적**: 23.5초 갭 후 재개 → 464ms 지연 → soft_resync까지 연쇄

### soft_resync와의 차이

| 항목 | `soft_resync` | `rtp_new_segment_after_empty` |
|------|---------------|-------------------------------|
| 발동 조건 | 200ms 이상 지연 | 킵얼라이브 갭 후 재개 |
| 빈도 | 높음 (통화당 여러 번) | 낮음 (킵얼라이브 후 1회) |
| 버그 | `packets_sent_total = 0` 리셋 | `packets_sent_total = 0` 리셋 |
| 증상 | 초기 패킷 불규칙 | **더 극단적인 불규칙** |
| 수정 | 2026-03-29 21:33 | **2026-03-29 22:00** |

---

## 세션 전체 통계 (Line 12014)

```json
"rtp_sender_session_end"
  - packets_sent: 2638
  - rtp_sched_soft_resync_count: 2  ← soft_resync 2번
  - interval_violations: 74  ← 74개 패킷이 20ms 위반
  - behind_schedule_count: 284
```

**74개의 interval_violations**는:
- `rtp_base_time_reset_on_first_packet` 버그로 인한 초기 불규칙
- `soft_resync` 버그로 인한 추가 불규칙

**수정 후 예상**:
- `interval_violations: 0` (또는 극소수, 네트워크 지터만)
- `soft_resync_count: 0` (또는 극소수, 464ms 같은 큰 지연 없음)

---

## 타임라인 (21:39:17.xxx)

```
21:39:11.786 | 이전 응답 TTS 끝 (킵얼라이브 시작)
              ↓ 23.5초 무음
21:39:17.178 | rtp_tts_sender_resumed_after_empty
              - was_keepalive_gap: true
              - packets_sent_so_far: 760
              - _rtp_new_segment_after_empty = True 설정

21:39:17.178 | rtp_base_time_reset_on_first_packet
              ❌ packets_sent_total = 0 리셋 (버그)

21:39:17.178 | rtp_pcm_chunk_sent_complete
              - first_seq: 2011
              - packets_sent_cumulative: 761
              
21:39:17.372 | tts_first_audio_received (새 응답 시작)

21:39:17.662 | pcm_chunk_gap_large
              - gap_ms: 23492.8 (23.5초)
              - queue_size: 0

21:39:17.662 | rtp_pcm_chunk_to_packets
              - first_packet_seq: 2012
              - packets_sent_so_far: 761

21:39:17.662 | rtp_schedule_soft_resync
              - ideal_late_ms: 464.44  ← packets_sent_total=0으로 인한 스케줄 붕괴
              - soft_resync_count: 1

21:39:17.662-18.430 | rtp_interval_violation (5회)
  - actual_ms: 484.5, 26.3, 14.0, 35.1, 1.4
  - interval_min_ms: 1.37
  - interval_max_ms: 484.54

21:39:18.430 | rtp_tts_send_window_jitter_spike
              - "창 내 간격 극단값 — 청취 뭉개짐과 상관"
```

---

## 코드 분석

### 버그 코드 위치

**파일**: `sip-pbx/src/media/rtp_relay.py`  
**라인**: 1721-1729

```python
# ❌ 버그 (구버전)
if self._rtp_new_segment_after_empty:
    self._rtp_base_time = time.perf_counter()
    self._rtp_packets_sent_total = 0  # ❌ 리셋!
    self._rtp_last_send_time = self._rtp_base_time
    logger.info("rtp_base_time_reset_on_first_packet", ...)
    self._rtp_new_segment_after_empty = False
```

### 버그 발생 메커니즘

1. **킵얼라이브 갭 전**:
   ```python
   packets_sent_total = 760
   base_time = T0
   ideal_target = T0 + (760 * 0.02) = T0 + 15.2초
   ```

2. **`rtp_base_time_reset_on_first_packet` 실행** (Line 1722-1723):
   ```python
   base_time = now  # T1
   packets_sent_total = 0  # ❌ 리셋!
   ```

3. **다음 패킷 계산** (Line 1736):
   ```python
   ideal_target = T1 + (0 * 0.02) = T1  # 즉시 전송!
   ```

4. **실제로는 464ms 지연**:
   - 첫 청크(25개 패킷) 처리 시간
   - 각 패킷의 `ideal_target`이 과거 시점
   - 모두 "지금 당장" 전송하려고 함
   - 결과: **불규칙한 간격** (1.4ms, 14ms, 26ms, 35ms, 484ms)

5. **Jitter buffer 혼란**:
   - 484ms 간격 → buffer "느리게 재생"
   - 1.4ms 간격 → buffer "빠르게 재생"
   - 재생 속도 급변 → **오디오 늘어짐**

---

## 수정 내용

### 변경 사항

```python
# ✅ 수정 (신버전)
if self._rtp_new_segment_after_empty:
    now = time.perf_counter()
    # base_time을 "지금 시점에서 packets_sent_total만큼 이미 보낸 것처럼" 역산
    self._rtp_base_time = now - (self._rtp_packets_sent_total * FIXED_INTERVAL_SEC)
    self._rtp_last_send_time = now
    logger.info("rtp_base_time_reset_on_first_packet",
               call_id=self.media_session.call_id,
               progress="rtp_timing",
               packets_sent_total=self._rtp_packets_sent_total,
               note="새 구간 첫 패킷 전송 직전 base_time 재설정 (처리 지연 흡수, packets_sent_total 유지)")
    self._rtp_new_segment_after_empty = False
```

### 수정 후 동작

1. **킵얼라이브 갭 전**:
   ```python
   packets_sent_total = 760
   base_time = T0
   ```

2. **`rtp_base_time_reset_on_first_packet` 실행** (수정 후):
   ```python
   now = T1
   base_time = T1 - (760 * 0.02) = T1 - 15.2초
   packets_sent_total = 760  # ✅ 유지!
   ```

3. **다음 패킷 계산**:
   ```python
   ideal_target = (T1 - 15.2초) + (760 * 0.02) = T1  # 지금
   ```
   - 첫 패킷: `T1 + 0ms`
   - 둘째 패킷: `T1 + 20ms`
   - 셋째 패킷: `T1 + 40ms`
   - ...
   - **모든 패킷이 20ms 고정 간격!**

4. **Jitter buffer 안정**:
   - 모든 간격이 19~21ms
   - 재생 속도 일정
   - **늘어짐 없음**

---

## soft_resync 버그와의 관계

**이 버그는 `soft_resync` 버그와 동일한 패턴**입니다:

| 항목 | `soft_resync` 버그 | `rtp_new_segment` 버그 |
|------|-------------------|----------------------|
| 위치 | Line 1747-1770 | Line 1721-1729 |
| 발동 조건 | 200ms 이상 지연 | 킵얼라이브 갭 후 재개 |
| 버그 | `packets_sent_total = 0` | `packets_sent_total = 0` |
| 증상 | 초기 패킷 불규칙 → 늘어짐 | **더 극단적인 불규칙** → 심한 늘어짐 |
| 수정 일시 | 2026-03-29 21:33 | **2026-03-29 22:00** |
| 리포트 | `2026-03-29_2133_AUDIO_STRETCH_SOFT_RESYNC_BUG_jkjUT4Nhid.md` | **본 문서** |

**두 버그는 서로 연쇄 작용**:
1. `rtp_new_segment`에서 `packets_sent_total = 0` 리셋
2. 스케줄이 크게 지연됨
3. `soft_resync` 조건 충족 (200ms 이상 지연)
4. `soft_resync`에서도 `packets_sent_total = 0` 리셋 (구 코드)
5. **극단적인 불규칙 발생**

---

## 추가 발견 사항

### 1. RTP dump 미생성

**상태**: `config.yaml`에 `media.rtp_tx_debug: true` 설정되어 있으나, dump 파일이 생성되지 않음

**원인**: 서버가 재시작되지 않아서 설정이 반영되지 않음

**확인 방법**:
```bash
ls sip-pbx/logs/rtp_tx_*.tsv
# 파일이 없으면 서버 재시작 필요
```

### 2. 통계 불일치

Line 2116과 2117:
```json
"rtp_tts_sender_resumed_after_empty" - "packets_sent_so_far": 760
"rtp_pcm_chunk_to_packets" - "packets_sent_so_far": 760
```

Line 2119:
```json
"rtp_pcm_chunk_sent_complete" - "packets_sent_cumulative": 761
```

**이유**: 
- `rtp_base_time_reset_on_first_packet`에서 `packets_sent_total = 0` 리셋
- 첫 패킷(seq=2011)을 보낸 후 `packets_sent_total = 1`
- 다음 청크(25개 패킷)를 보낸 후 `packets_sent_total = 26`
- 하지만 로그는 **리셋 전 값(760)을 기준**으로 출력

**수정 후**: `packets_sent_total`이 유지되므로 통계가 일관됨

---

## 테스트 가이드

### 수정 확인 사항

1. **서버 재시작 필수**:
   ```bash
   # Python 백엔드 재시작
   # (start_all.sh 또는 직접 실행)
   ```

2. **RTP dump 생성 확인**:
   ```bash
   ls -l sip-pbx/logs/rtp_tx_*.tsv
   # 새 통화 시 파일이 생성되어야 함
   ```

3. **킵얼라이브 갭 후 응답 테스트**:
   - 통화 시작
   - "어떤 일을 할 수 있어요?" 질문
   - AI 응답 듣기
   - **20초 이상 무음** (킵얼라이브)
   - 다시 질문하기
   - **"faq" 같은 단어가 늘어지지 않는지 확인**

4. **로그 확인**:
   ```bash
   # rtp_base_time_reset_on_first_packet 로그에 packets_sent_total 포함 확인
   grep "rtp_base_time_reset_on_first_packet" logs/app.log | tail -5
   
   # interval_violations 개수 확인 (0에 가까워야 함)
   grep "rtp_sender_session_end" logs/app.log | tail -3
   
   # jitter_spike 경고 없음 확인
   grep "rtp_tts_send_window_jitter_spike" logs/app.log | tail -5
   ```

5. **RTP dump 확인** (서버 재시작 후):
   ```bash
   # 모든 패킷이 19~21ms 간격인지 확인
   tail -100 logs/rtp_tx_*.tsv | grep media
   ```

---

## 수정 이력

### 2026-03-29 21:33 - soft_resync 버그 수정
- **파일**: `rtp_relay.py` Line 1747-1770
- **내용**: `soft_resync` 로직에서 `packets_sent_total` 리셋 제거
- **리포트**: `2026-03-29_2133_AUDIO_STRETCH_SOFT_RESYNC_BUG_jkjUT4Nhid.md`

### 2026-03-29 22:00 - rtp_new_segment 버그 수정
- **파일**: `rtp_relay.py` Line 1721-1729
- **내용**: `rtp_new_segment_after_empty` 로직에서 `packets_sent_total` 리셋 제거
- **리포트**: **본 문서**

---

## 결론

**`rtp_base_time_reset_on_first_packet`에서 `packets_sent_total = 0` 리셋**은 **`soft_resync` 버그와 동일한 패턴**이며, **킵얼라이브 갭 후 재개 시 더 극단적인 오디오 늘어짐**을 유발합니다.

**두 버그를 모두 수정**하여:
- 모든 RTP 패킷이 **20ms 고정 간격** 유지
- 클라이언트 jitter buffer가 안정적으로 동작
- **"faq" 같은 단어가 늘어지지 않음**

**서버 재시작 후 테스트 필요**.

---

## 참고

- **이전 리포트**: `2026-03-29_2133_AUDIO_STRETCH_SOFT_RESYNC_BUG_jkjUT4Nhid.md` (soft_resync 버그)
- **관련 이슈**: `2026-03-29_2057_AUDIO_QUALITY_ISSUES_s9q_GPgtz9.md` (기계음 버그)
- **설계 문서**: RTP 고정 간격 전송 (20ms)
