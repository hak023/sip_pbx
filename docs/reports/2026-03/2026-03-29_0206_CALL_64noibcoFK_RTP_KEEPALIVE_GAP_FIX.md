# RTP 뭉개짐 현상 수정 (call_id: 64noibcoFK)

**작성일**: 2026-03-29 02:06  
**Call ID**: `64noibcoFK`  
**증상**: "저는 상담원 안내, 기상....(뭉개짐) 특보 안내" - "기상" 부분이 늘어지고 뭉개짐  
**수정 파일**: `src/media/rtp_relay.py`

---

## 1. 문제 증상

사용자가 "어떤 일을 할 수 있나요?"라고 질문했을 때, AI 응답:
> "저는 상담원 안내, 기상 특보 안내, faq 안내, 서비스 안내, 기상청 담당자 연결을 할 수 있어요."

이 중 **"기상" 부분이 늘어지고 뭉개져서** 들렸다고 보고됨.

### 발생 시각 및 로그
- **Call ID**: `64noibcoFK`
- **TTS 전송 시각**: `2026-03-29T01:59:16.174`
- **텍스트 길이**: 71자
- **Intent**: `help`

---

## 2. 로그 분석

### 2.1. Call Data Record 로그
```json
{"ts": "2026-03-29T01:59:16.174", "call_id": "64noibcoFK", "category": "tts", 
 "event": "tts_text_pushed", 
 "text": "저는 상담원 안내, 기상 특보 안내, faq 안내, 서비스 안내, 기상청 담당자 연결을 할 수 있어요. 어떤 것을 도와드릴까요?"}
```

### 2.2. app.log - RTP 타이밍
```json
{"timestamp": "2026-03-29T01:59:15.447", "event": "rtp_base_time_updated_after_keepalive", 
 "base_time_shift_sec": 8.009, "idle_sec": 8.008, 
 "note": "Keepalive 발송 후 base_time 갱신 — 다음 미디어 도착 시 과거 ideal_target 방지"}

{"timestamp": "2026-03-29T01:59:16.436", "event": "tts_first_audio_sent_to_rtp", 
 "audio_len": 16000, "ts_iso": "2026-03-29T01:59:16.435"}

{"timestamp": "2026-03-29T01:59:16.438", "event": "rtp_schedule_soft_resync", 
 "ideal_late_ms": 970.53, 
 "note": "스케줄 대폭 지연 — base_time 재앵커, 이후 20ms 간격 유지(버스트 완화)"}
```

### 2.3. RTP TX 로그 (rtp_tx_64noibcoFK.tsv)
```
wall_iso                    perf_mono       seq     ts          interval_ms
2026-03-29T01:58:59.434    693499.915891   36447   571131033   20.087      (마지막 미디어)
2026-03-29T01:59:07.438    693507.920758   36448   571131193   8004.868    (keepalive #1)
2026-03-29T01:59:15.447    693515.929399   36449   571131353   8008.64     (keepalive #2)
2026-03-29T01:59:16.437    693516.919993   36450   571131513   990.594     (첫 미디어) ⚠️
2026-03-29T01:59:16.458    693516.940040   36451   571131673   20.047      (정상)
```

**핵심 문제**: 
- keepalive #2 전송: `01:59:15.447`
- 첫 미디어 전송: `01:59:16.437` → **990ms 갭** ⚠️
- 이 갭 동안 RTP timestamp는 정상 증가 (`571131353` → `571131513`, 160 = 20ms), 하지만 **실제 오디오는 전송되지 않음**

---

## 3. 근본 원인

### 3.1. 기존 로직 문제점

이전 수정에서 keepalive 전송 시점에 `base_time`을 갱신하는 로직을 추가했었음:

```python
# (기존 코드, 1449-1463줄)
# ✅ Keepalive 발송 시 base_time 갱신 (다음 미디어 지연 방지)
if hasattr(self, '_rtp_base_time') and self._rtp_base_time is not None:
    old_base = self._rtp_base_time
    self._rtp_base_time = now  # ⚠️ 여기서 갱신
    self._rtp_packets_sent_total = 0
    logger.info("rtp_base_time_updated_after_keepalive", ...)
```

**문제**:
1. keepalive 전송 시점(T0)에 `base_time`을 갱신하고 `_rtp_packets_sent_total = 0`으로 리셋
2. 실제 미디어가 990ms 후(T0+990ms)에 도착
3. 이 시점의 `ideal_target = base_time + (0 * 0.02) = base_time = T0`
4. 하지만 현재 시각은 `T0 + 990ms`이므로 **990ms 지연**으로 판단
5. `soft_resync` 로직이 발동하여 즉시 재앵커하지만, **RTP timestamp는 계속 이어지므로 타이밍 불일치 발생**

### 3.2. 왜 이전에 이 로직을 추가했나?

원래는 keepalive 후 미디어가 오면 `ideal_target`이 과거가 되어 긴 대기가 발생하는 것을 방지하기 위함이었으나, **keepalive 전송 시점이 아니라 실제 미디어 도착 시점에 갱신해야** 정확합니다.

### 3.3. new_segment 로직이 있는데 왜 작동하지 않았나?

기존 코드 (1527-1542줄):
```python
new_segment = last_was_empty_timeout or (
    empty_timeout_count >= 2 and packets_sent > 0
)
```

**문제**: keepalive 전송 시 `last_was_empty_timeout = False`로 설정 (1431줄)  
→ keepalive 후 다음 미디어 도착 시 `new_segment = False`  
→ `base_time` 재설정이 발동하지 않음

---

## 4. 수정 내용

### 4.1. 수정 #1: keepalive 전송 시 base_time 갱신 로직 제거

**파일**: `src/media/rtp_relay.py`  
**위치**: 1449-1463줄 (기존)

**제거한 코드**:
```python
# ✅ Keepalive 발송 시 base_time 갱신 (다음 미디어 지연 방지)
# 이유: Keepalive 후 미디어가 오면 ideal_target이 과거 시각이 되어
# soft resync가 발동하기 전에 2.5초 대기가 발생함
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

**이유**: keepalive 전송 시점에 `base_time`을 갱신하면, 실제 미디어 도착까지의 시간(990ms)이 고려되지 않아 타이밍 불일치 발생.

### 4.2. 수정 #2: keepalive 후 new_segment 발동 보장

**파일**: `src/media/rtp_relay.py`  
**위치**: 1431줄

**변경**:
```python
# Before
last_was_empty_timeout = False

# After
last_was_empty_timeout = True  # ✅ keepalive 후 첫 미디어에서 base_time 재설정 유도
```

**이유**: keepalive 전송 후 다음 미디어 도착 시 `new_segment` 조건을 만족하도록 하여, 미디어 도착 시점에 `base_time`이 정확하게 갱신되도록 함.

### 4.3. 수정 #3: 로그 강화

**파일**: `src/media/rtp_relay.py`  
**위치**: 1530-1535줄

**변경**:
```python
# Before
logger.info("rtp_tts_sender_resumed_after_empty",
            call_id=self.media_session.call_id,
            empty_timeouts=empty_timeout_count,
            packets_sent_so_far=packets_sent,
            note="PCM 큐 비어 있다가 새 청크 수신 — 새 구간 base_time 설정 (Phase2 등)")

# After
logger.info("rtp_tts_sender_resumed_after_empty",
            call_id=self.media_session.call_id,
            empty_timeouts=empty_timeout_count,
            packets_sent_so_far=packets_sent,
            was_keepalive_gap=(empty_timeout_count == 0 and last_was_empty_timeout),
            note="PCM 큐 비어 있다가 새 청크 수신 — 새 구간 base_time 설정 (Phase2/keepalive 후)")
```

**목적**: keepalive 후 갭인지(`was_keepalive_gap=True`) 일반 Phase2 갭인지 구분하여 디버깅 용이성 향상.

---

## 5. 수정 후 예상 동작

### 5.1. Keepalive → 미디어 타임라인
```
T0:      Keepalive #1 전송 (seq 36448)
         last_was_empty_timeout = True 설정
         base_time은 갱신하지 않음

T0+8s:   Keepalive #2 전송 (seq 36449)
         last_was_empty_timeout = True 유지
         base_time은 갱신하지 않음

T0+9s:   첫 미디어 도착 (TTS 시작)
         new_segment = True (last_was_empty_timeout == True)
         ✅ base_time = 현재 시각 (T0+9s)
         _rtp_packets_sent_total = 0
         ideal_target = base_time + (0 * 0.02) = T0+9s
         sleep_needed = 0 (즉시 전송)
         
T0+9.02s: 두 번째 패킷
         ideal_target = base_time + (1 * 0.02) = T0+9.02s
         sleep_needed = 20ms (정상)
```

### 5.2. 로그 확인 포인트
수정 후 다음 로그가 나타나야 함:
```json
{"event": "rtp_tts_sender_resumed_after_empty",
 "empty_timeouts": 0,
 "was_keepalive_gap": true,
 "note": "PCM 큐 비어 있다가 새 청크 수신 — 새 구간 base_time 설정 (Phase2/keepalive 후)"}
```

**`rtp_schedule_soft_resync`는 더 이상 발생하지 않아야 함.**

---

## 6. 근본 원인 요약

**이전 수정의 문제점**:
- keepalive 전송 시점에 `base_time`을 갱신하면, 실제 미디어가 도착하는 시점과의 시간 차이(~1초)가 반영되지 않음
- `last_was_empty_timeout = False`로 설정하여 `new_segment` 로직이 발동하지 않음
- 결과: keepalive 후 첫 미디어가 도착하면 `ideal_target`이 과거가 되어 `soft_resync` 발동 → **990ms 갭 발생**

**올바른 해결**:
1. keepalive 전송 시에는 `base_time`을 갱신하지 않음 (제거)
2. keepalive 전송 시 `last_was_empty_timeout = True`로 설정
3. 다음 미디어 도착 시 `new_segment` 로직이 자동으로 `base_time`을 **미디어 도착 시각 기준**으로 재설정
4. 이로써 keepalive와 미디어 사이의 실제 시간 갭이 정확하게 반영됨

---

## 7. 수정 코드

### 7.1. keepalive 전송 블록 (1428-1447줄)
```python
# Before
pcm_data = _PCM_SILENCE_20MS_16K_MONO
pcm_is_keepalive = True
empty_timeout_count = 0
last_was_empty_timeout = False  # ❌ 문제: new_segment 미발동

# After
pcm_data = _PCM_SILENCE_20MS_16K_MONO
pcm_is_keepalive = True
empty_timeout_count = 0
last_was_empty_timeout = True  # ✅ 수정: keepalive 후 첫 미디어에서 base_time 재설정 유도
```

### 7.2. base_time 갱신 로직 제거 (1449-1463줄 삭제)
기존의 `rtp_base_time_updated_after_keepalive` 블록 전체 제거.

### 7.3. new_segment 로그 강화 (1530-1535줄)
```python
# Before
logger.info("rtp_tts_sender_resumed_after_empty",
            note="PCM 큐 비어 있다가 새 청크 수신 — 새 구간 base_time 설정 (Phase2 등)")

# After
logger.info("rtp_tts_sender_resumed_after_empty",
            was_keepalive_gap=(empty_timeout_count == 0 and last_was_empty_timeout),
            note="PCM 큐 비어 있다가 새 청크 수신 — 새 구간 base_time 설정 (Phase2/keepalive 후)")
```

---

## 8. 검증 방법

### 8.1. 백엔드 재시작
수정한 `rtp_relay.py`를 적용하려면 백엔드 재시작 필요:
```bash
cd c:\work\workspace_sippbx\sip-pbx
.\start-all.ps1
```

### 8.2. 테스트 시나리오
1. AI 봇에 전화 연결
2. "어떤 서비스를 안내해 주나요?" 또는 "무엇을 할 수 있나요?" 질문
3. AI 응답: "저는 상담원 안내, 기상 특보 안내..." 청취
4. **"기상" 부분이 뭉개지지 않고 명료하게 들리는지** 확인

### 8.3. 로그 확인
```bash
# app.log에서 새 로그 확인
Select-String -Path "logs\app.log" -Pattern "rtp_tts_sender_resumed_after_empty|was_keepalive_gap"

# soft_resync가 발생하지 않는지 확인 (keepalive 직후 시점)
Select-String -Path "logs\app.log" -Pattern "rtp_schedule_soft_resync"
```

**기대 결과**:
- `rtp_tts_sender_resumed_after_empty` 로그에서 `"was_keepalive_gap": true` 확인
- keepalive 직후 `rtp_schedule_soft_resync`가 **발생하지 않아야 함**
- RTP TX 로그에서 keepalive → 미디어 전환 시 **20ms 간격 유지** 확인

---

## 9. RTP 타이밍 원칙 (재확인)

### 9.1. base_time 갱신 시점
| 시점 | base_time 갱신 | 이유 |
|------|---------------|------|
| 첫 PCM 도착 | ✅ 갱신 | 절대 시간 기준점 설정 |
| keepalive 전송 | ❌ 갱신 안 함 | 실제 미디어 도착 시각과 차이 발생 |
| new_segment (큐 비었다가 미디어 도착) | ✅ 갱신 | 실제 도착 시각 기준으로 재설정 |
| soft_resync (>20ms 지연) | ✅ 갱신 | 긴 버스트 방지 |

### 9.2. 핵심 규칙
- **`base_time`은 항상 "실제 PCM 데이터가 도착한 시점"을 기준으로 설정**
- keepalive는 단순히 **RTP 연결 유지용 무음 패킷**일 뿐, 타이밍 기준점이 아님
- `last_was_empty_timeout` 플래그는 keepalive 전송 후에도 `True`여야 다음 미디어에서 정확한 재동기화 가능

---

## 10. 이전 수정 이력 참고

### 관련 리포트
1. **`2026-03-28_2234_CALL_QsXak5kOGh_TTS_CHOPPY_FRAME_COUNT_MISMATCH_FIX.md`**
   - TTS 문장 분할 시 프레임 카운트 불일치 수정
   
2. **`2026-03-29_0130_CALL_W6wWrDb9wZ_RTP_GAP_HOMEPAGE_STRETCHED_FIX.md`**
   - "기상청 홈.......페이지" 뭉개짐 현상 수정
   - 당시 keepalive 후 base_time 갱신 로직을 추가했으나, 이번에 해당 로직이 오히려 문제임을 확인

### 차이점
- 이전 수정: keepalive **전송 시점**에 base_time 갱신 → ❌ 타이밍 불일치 발생
- 이번 수정: keepalive **후 미디어 도착 시점**에 base_time 갱신 → ✅ 정확한 타이밍 보장

---

## 11. 결론

**문제**: keepalive 전송 시 `base_time`을 갱신하면, 실제 미디어 도착까지의 시간 갭(~1초)이 반영되지 않아 타이밍 불일치 발생.

**해결**:
1. keepalive 전송 시 base_time 갱신 로직 제거
2. keepalive 전송 시 `last_was_empty_timeout = True`로 설정
3. 다음 미디어 도착 시 `new_segment` 로직이 자동으로 정확한 시점에 base_time 재설정

**기대 효과**: keepalive 후 첫 미디어 전송 시 990ms 갭이 사라지고, "기상" 부분이 뭉개지지 않고 명료하게 들림.

**백엔드 재시작 필요**: 수정 사항 적용을 위해 `start-all.ps1` 실행.

---

## 12. 추가 모니터링

다음 통화에서 다음 로그를 확인:
1. `rtp_tts_sender_resumed_after_empty` → `was_keepalive_gap: true`
2. keepalive 직후 `rtp_schedule_soft_resync` **미발생**
3. RTP TX 로그에서 keepalive → 미디어 간격이 **20ms 전후**로 정상 유지

이 로그들이 정상이면 수정 성공. 여전히 뭉개지면 추가 분석 필요.
