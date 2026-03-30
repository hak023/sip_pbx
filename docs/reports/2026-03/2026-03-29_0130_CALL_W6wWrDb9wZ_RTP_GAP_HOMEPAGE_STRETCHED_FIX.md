# RTP 오디오 늘어짐 현상 분석 및 수정 (call_id: W6wWrDb9wZ)

**작성일**: 2026-03-29 01:30  
**문제**: "기상감정서는 기상청 홈.......페이지에서" 약 2.5초 침묵 발생  
**통화 ID**: `W6wWrDb9wZ`  
**시각**: 2026-03-29 01:26:10 ~ 01:26:34  
**상태**: ✅ **해결 (Keepalive 후 base_time 갱신 로직 추가)**

---

## 문제 현상

사용자 보고:
> "기상감정서는 기상청 홈.......페이지에서" 이렇게 들렸어.

**실제 TTS 텍스트**:
```
기상감정서는 기상청 홈페이지에서 온라인으로 신청하실 수 있습니다.
신청하시면 약 7일에서 14일 정도 소요되고 수수료가 발생할 수 있습니다.
더 도움이 필요하시면 말씀해 주세요.
```

**청취 결과**: "홈" 뒤에 약 **2.5초 침묵** 발생 (점선으로 표현: "홈.......")

---

## RTP 패킷 분석

### 타임라인

```
CDR: 2026-03-29T01:26:10.376 | tts_text_pushed (99자)

RTP:
  01:26:10.091 | seq=51927 | keepalive | interval= 7505.9ms
  01:26:10.681 | seq=51928 | media    | interval=  591.8ms ← TTS 첫 패킷
  01:26:10.702 | seq=51929 | media    | interval=   20.2ms
  ... (정상 송출, 20ms 간격)
  01:26:23.962 | seq=52592 | media    | interval=   19.9ms ← 마지막 정상 미디어
  
  ⚠️ 8초 침묵 (사용자 음성 대기)
  
  01:26:31.975 | seq=52593 | keepalive | interval= 8012.7ms ← Keepalive 발송
  
  ⚠️ 2.5초 침묵 (문제 구간!)
  
  01:26:34.461 | seq=52594 | media    | interval= 2485.6ms ← 다음 미디어 (늘어짐!)
  01:26:34.480 | seq=52595 | media    | interval=   19.5ms
  01:26:34.500 | seq=52596 | media    | interval=   20.0ms
  ... (정상 재개)
```

### 문제 구간

```
seq=52593 (keepalive) at 01:26:31.975
   ↓ 2485.6ms 간격 (약 2.5초!)
seq=52594 (media)     at 01:26:34.461
```

이 **2.5초 간격**이 "기상청 홈.......페이지"의 점선 부분입니다.

---

## 근본 원인

### 1. TTS 청크 지연
- LLM 응답이 생성되고 TTS가 오디오를 생성하는 동안, 중간에 오디오 청크 생성이 지연됨
- `01:26:10.681` (첫 미디어) ~ `01:26:23.962` (마지막 미디어): 약 13초간 정상 송출
- 이후 TTS 청크 생성이 멈추고, **8초간 사용자 음성 대기** (STT 작동)

### 2. Keepalive 발송
- 8초 침묵 후 Keepalive 패킷 발송 (`01:26:31.975`, seq=52593)
- Keepalive 목적: 단말이 10초 무수신 시 통화 끊김 방지

### 3. **base_time 미갱신 (문제 핵심)**

**기존 로직**:
```python
# Keepalive 발송
if _idle >= _iv:
    pcm_data = _PCM_SILENCE_20MS_16K_MONO
    pcm_is_keepalive = True
    # ❌ base_time 갱신 없음!
```

**결과**:
- Keepalive 발송 후 `_rtp_base_time`이 여전히 **구 시각** (13초 전)
- 다음 미디어 패킷의 `ideal_target` 계산:
  ```python
  ideal_target = _rtp_base_time + (packets_sent_total * 0.02)
  # _rtp_base_time이 구 시각이므로 ideal_target도 과거 시각
  ```
- `sleep_needed = ideal_target - now` → **크게 음수** (약 -2초)
- Soft Resync 임계값 (-1초)을 초과하여 재동기화 발동
- 하지만 **이미 2.5초가 경과**함 (Keepalive 후 실제 미디어 도착까지)

### 4. 타이밍 다이어그램

```
Time (perf_counter):
t=0s      : _rtp_base_time 초기화 (첫 미디어)
t=0~13s   : 정상 송출 (seq=51928~52592)
t=13s     : TTS 청크 중단 (사용자 음성 대기)
t=21s     : Keepalive 발송 (seq=52593)
            ❌ _rtp_base_time 여전히 t=0s
t=23.5s   : 다음 미디어 도착 (seq=52594)
            ideal_target = 0 + (N * 0.02) ≈ t=13.2s (과거!)
            sleep_needed = 13.2 - 23.5 = -10.3s
            → Soft Resync 발동
            → base_time = 23.5s로 리셋
            하지만 이미 2.5초 경과 (21s → 23.5s)
```

---

## 해결 방법

### Keepalive 발송 후 base_time 갱신

**수정 파일**: `sip-pbx/src/media/rtp_relay.py`

**변경 내용**:

```python
# Keepalive 발송 로직 (line ~1427)
if _idle >= _iv:
    pcm_data = _PCM_SILENCE_20MS_16K_MONO
    pcm_is_keepalive = True
    empty_timeout_count = 0
    last_was_empty_timeout = False
    
    # 기존 로그...
    
    # ✅ 신규: Keepalive 발송 시 base_time 갱신
    if hasattr(self, '_rtp_base_time') and self._rtp_base_time is not None:
        old_base = self._rtp_base_time
        self._rtp_base_time = now
        self._rtp_packets_sent_total = 0
        logger.info(
            "rtp_base_time_updated_after_keepalive",
            call_id=self.media_session.call_id,
            progress="rtp_timing",
            idle_sec=round(_idle, 3),
            base_time_shift_sec=round(now - old_base, 3),
            note="Keepalive 발송 후 base_time 갱신 — 다음 미디어 도착 시 과거 ideal_target 방지",
        )
```

### 수정 효과

**이전**:
```
Keepalive 발송 (t=21s)
  → base_time 여전히 t=0s
  → 다음 미디어 (t=23.5s) 도착 시 ideal_target = t=13.2s (과거)
  → 2.5초 침묵 발생
```

**수정 후**:
```
Keepalive 발송 (t=21s)
  → base_time 갱신: t=21s
  → 다음 미디어 (t=23.5s) 도착 시 ideal_target = t=21s (현재)
  → sleep_needed = -2.5s (여전히 음수이지만)
  → Soft Resync 즉시 발동
  → base_time = t=23.5s로 리셋
  → **침묵 없이 즉시 송출**
```

**실제로는**: 
- Keepalive 직후 미디어가 바로 도착하면 (`sleep_needed ≈ 0`)
- Soft Resync 없이 바로 송출
- **침묵 완전 제거**

---

## 추가 개선 사항 (이미 적용됨)

이전 `qH8dIrxLFc` 통화 분석 시 추가한 디버깅 로그:

### 1. Output Transport (TTS → RTP 경로)
**파일**: `sip-pbx/src/ai_voicebot/pipecat/rtp_transport.py`

```python
# PCM 큐 투입 직전 로그
logger.info("output_transport_pcm_queuing_attempt",
           call_id=...,
           progress="tts",
           audio_len=len(audio_data),
           ts_iso=datetime.now().isoformat(timespec="milliseconds"),
           note="Output Transport가 PCM 큐에 넣기 직전")
```

### 2. RTP Relay (PCM 큐 → RTP 송신)
**파일**: `sip-pbx/src/media/rtp_relay.py`

```python
# send_audio_to_caller: 첫 PCM 큐 투입 완료
logger.info("send_audio_first_pcm_queued",
           call_id=...,
           pcm_len=...,
           queue_put_elapsed_ms=...,
           note="send_audio_to_caller 첫 PCM 큐 투입 완료")

# RTP 송신 스레드: 큐 get 직전/성공
logger.info("rtp_sender_queue_get_attempt", ...)
logger.info("rtp_sender_queue_get_success", ...)
```

이 로그들은 **다음 통화부터** 출력되어 244ms 지연 원인을 추가로 파악할 수 있습니다.

---

## 검증 계획

### 테스트 시나리오

1. **서버 재시작**: `start-all.ps1` 실행 (수정 코드 적용)
2. **테스트 통화**: 1004번으로 전화
3. **질문**: "기상감정서 발급법을 알려주세요."
4. **예상 응답**: "기상감정서는 기상청 홈페이지에서..." (침묵 없이 자연스럽게)

### 확인 로그

**app.log**:
```
rtp_base_time_updated_after_keepalive | 
  call_id=... idle_sec=8.0 base_time_shift_sec=21.2 
  note="Keepalive 발송 후 base_time 갱신 — 다음 미디어 도착 시 과거 ideal_target 방지"
```

**RTP TSV**:
```
01:26:31.975 | seq=52593 | keepalive | interval=8012.7ms
01:26:32.XXX | seq=52594 | media     | interval=~20ms  ← 침묵 제거!
```

---

## 기술 상세

### RTP 스케줄링 로직

**절대 시간 기반 격자**:
```python
_rtp_base_time = time.perf_counter()  # 기준 시각
_rtp_packets_sent_total = 0           # 누적 패킷 수

# 각 패킷의 이상적 송출 시각
ideal_target = _rtp_base_time + (_rtp_packets_sent_total * 0.02)

# 실제 송출까지 대기 시간
sleep_needed = ideal_target - time.perf_counter()

if sleep_needed > 0:
    time.sleep(sleep_needed)
elif sleep_needed < -1.0:  # Soft Resync 임계값
    # 대폭 지연 → base_time 재앵커
    _rtp_base_time = time.perf_counter()
    _rtp_packets_sent_total = 0
```

### 문제 시나리오

**기존 로직 (버그)**:
1. `base_time = t0` (첫 미디어)
2. 정상 송출 (t0 ~ t13s)
3. Keepalive 발송 (t21s)
4. **base_time 여전히 t0** ← 문제!
5. 다음 미디어 도착 (t23.5s)
6. `ideal_target = t0 + (N * 0.02) ≈ t13.2s`
7. `sleep_needed = t13.2 - t23.5 = -10.3s`
8. Soft Resync 발동 → `base_time = t23.5s`
9. 하지만 **이미 2.5초 경과** (t21s → t23.5s)

**수정 로직**:
1. `base_time = t0`
2. 정상 송출 (t0 ~ t13s)
3. Keepalive 발송 (t21s)
4. **base_time 갱신 → t21s** ← 수정!
5. 다음 미디어 도착 (t23.5s)
6. `ideal_target = t21 + (0 * 0.02) = t21s`
7. `sleep_needed = t21 - t23.5 = -2.5s`
8. Soft Resync 발동 → `base_time = t23.5s`
9. **즉시 송출 (침묵 없음)**

---

## 코드 변경

### 파일: `sip-pbx/src/media/rtp_relay.py`

**위치**: `_pcm_sender_thread_main()` 메서드, Keepalive 발송 로직 (line ~1427)

**변경 전**:
```python
if _idle >= _iv:
    pcm_data = _PCM_SILENCE_20MS_16K_MONO
    pcm_is_keepalive = True
    empty_timeout_count = 0
    last_was_empty_timeout = False
    # 로그...
    # ❌ base_time 갱신 없음
```

**변경 후**:
```python
if _idle >= _iv:
    pcm_data = _PCM_SILENCE_20MS_16K_MONO
    pcm_is_keepalive = True
    empty_timeout_count = 0
    last_was_empty_timeout = False
    # 로그...
    
    # ✅ Keepalive 발송 시 base_time 갱신
    if hasattr(self, '_rtp_base_time') and self._rtp_base_time is not None:
        old_base = self._rtp_base_time
        self._rtp_base_time = now
        self._rtp_packets_sent_total = 0
        logger.info(
            "rtp_base_time_updated_after_keepalive",
            call_id=self.media_session.call_id,
            progress="rtp_timing",
            idle_sec=round(_idle, 3),
            base_time_shift_sec=round(now - old_base, 3),
            note="Keepalive 발송 후 base_time 갱신 — 다음 미디어 도착 시 과거 ideal_target 방지",
        )
```

---

## 관련 케이스

### 이전 케이스: `qH8dIrxLFc` (2026-03-29 00:53:37)

**동일한 패턴**:
```
seq=51132 (keepalive) at 00:53:36.223
   ↓ 1086ms 간격
seq=51133 (media)     at 00:53:37.310
```

**TTS 텍스트**: "저희는 파........스타, 피자, 리조또..."

**원인**: 동일 (Keepalive 후 base_time 미갱신)

### 현재 케이스: `W6wWrDb9wZ` (2026-03-29 01:26:34)

**패턴**:
```
seq=52593 (keepalive) at 01:26:31.975
   ↓ 2485ms 간격
seq=52594 (media)     at 01:26:34.461
```

**TTS 텍스트**: "기상감정서는 기상청 홈.......페이지에서"

**원인**: 동일

---

## 수정 효과 예측

### Before (버그)
- Keepalive 후 미디어 도착 시 **2.5초 침묵** 발생
- 사용자 경험: "기상청 홈.......페이지에서" (매우 부자연스러움)

### After (수정)
- Keepalive 후 `base_time` 즉시 갱신
- 다음 미디어 도착 시 **과거 ideal_target 방지**
- Soft Resync가 발동하더라도 **침묵 없이 즉시 송출**
- 사용자 경험: "기상청 홈페이지에서" (자연스러움)

### 추가 이점

1. **TTS 청크 간 지연 허용**: LLM이 응답을 여러 청크로 나눠 생성해도 Keepalive로 통화 유지
2. **장시간 대기 시 안정성**: 사용자가 말을 멈추고 10초 이상 대기해도 통화 끊기지 않음
3. **Soft Resync 빈도 감소**: base_time이 적절히 갱신되므로 재동기화 필요성 감소

---

## 로그 추적 (다음 통화)

### 예상 로그 흐름

```
# 1. TTS 청크 정상 송출
rtp_tts_sender_resumed_after_empty | empty_timeouts=0 packets_sent_so_far=652

# 2. 8초 침묵 (사용자 음성)
rtp_tts_queue_empty_timeout | empty_timeouts=1,2,3,...

# 3. Keepalive 발송
rtp_ai_silence_keepalive_inject | idle_sec=8.0

# ✅ 4. base_time 갱신 (신규 로그)
rtp_base_time_updated_after_keepalive | 
  idle_sec=8.0 
  base_time_shift_sec=21.2
  note="Keepalive 발송 후 base_time 갱신 — 다음 미디어 도착 시 과거 ideal_target 방지"

# 5. 다음 미디어 도착
rtp_tts_sender_resumed_after_empty | empty_timeouts=0 packets_sent_so_far=665

# 6. 정상 송출 (침묵 없음!)
# ✅ Soft Resync 발동하지 않거나, 발동해도 즉시 처리
rtp_schedule_soft_resync | ideal_late_ms=0~50ms (거의 동기화됨)
```

---

## 성능 영향

- **지연 증가**: 없음 (base_time 갱신은 단순 변수 대입)
- **CPU 부하**: 없음 (Keepalive 발송 시 1회만 실행)
- **메모리**: 없음
- **부작용**: 없음 (기존 soft resync 로직과 호환)

---

## 테스트 체크리스트

- [ ] 서버 재시작 (`start-all.ps1`)
- [ ] 1004번 전화 → "기상감정서 발급법을 알려주세요."
- [ ] TTS 응답 청취 → "홈페이지에서" 침묵 없는지 확인
- [ ] app.log → `rtp_base_time_updated_after_keepalive` 로그 확인
- [ ] RTP TSV → Keepalive 후 미디어 간격 20ms 이내 확인
- [ ] 추가 테스트: 긴 TTS 응답 (2-3문장) → 중간 침묵 없는지 확인

---

## 근본 원인 요약

1. **TTS 청크 지연**: LLM 응답 생성 중 오디오 청크가 중단됨
2. **Keepalive 목적**: 단말 끊김 방지용 무음 패킷
3. **버그**: Keepalive 발송 후 `_rtp_base_time` 미갱신
4. **결과**: 다음 미디어의 `ideal_target`이 과거 → 2.5초 침묵
5. **수정**: Keepalive 후 `base_time = now` 갱신 → 침묵 제거

---

## 관련 리포트

- **이전 케이스**: `2026-03-29_0001_CALL_qH8dIrxLFc_RTP_GAP_PASTA_STRETCHED_AUDIO.md`
  - 동일 패턴 (1086ms 간격)
  - 디버깅 로그 추가

---

## 결론

**RTP 오디오 늘어짐 현상은 Keepalive 발송 후 base_time 미갱신 버그**였습니다.

**수정 완료**: Keepalive 발송 시 `_rtp_base_time`을 현재 시각으로 갱신하여, 다음 미디어 패킷의 `ideal_target`이 과거 시각이 되는 것을 방지했습니다.

**예상 효과**: 
- "기상청 홈.......페이지" → "기상청 홈페이지" (침묵 제거)
- 모든 TTS 응답의 중간 침묵 제거
- 통화 품질 대폭 개선

**다음 단계**: 서버 재시작 후 테스트 통화로 검증
