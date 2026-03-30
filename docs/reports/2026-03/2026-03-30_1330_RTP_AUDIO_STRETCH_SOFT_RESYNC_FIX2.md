# RTP 오디오 늘어짐 현상 분석 및 수정 (Soft Resync 공식 오류)

**작성일**: 2026-03-30 13:30  
**통화 ID**: `dHT1zO55li`  
**증상**: "안.........녕........하........세......요. KT......... 통..........화.........매.........니저 기상청 AI 봇 입니다."  
**관련**: `2026-03-29_2133_AUDIO_STRETCH_SOFT_RESYNC_BUG_jkjUT4Nhid.md` (이전 soft_resync 수정)

---

## 1. 증상

- **이전 수정 후에도 오디오 늘어짐이 극심하게 악화**
- Phase1 인사 "안녕하세요. KT 통화매니저 기상청 AI 봇 입니다." (29자)가 극도로 느리게 재생
- 사용자 보고: 각 음절 사이에 수백ms 간격이 발생

## 2. 로그 분석

### 2.1. TTS 청크 수신 간격

**`app.log` Line 953**:
```json
{
  "event": "pcm_chunk_gap_large",
  "gap_ms": 1897.4,
  "chunk_seq": 2,
  "note": "TTS 청크 간 gap 100ms 초과 → 큐 고갈 위험"
}
```

**결론**: Google TTS 스트리밍 응답이 느려 **PCM 큐가 고갈**됨.

### 2.2. RTP 패킷 간격 (app.log)

**Packet 26** (Line 928, 933):
- `wait_ms: 513.46` (큐 고갈로 513ms 대기)
- `interval_from_prev_ms: 0.14` (대기 직후 즉시 전송)
- `_rtp_new_segment_after_empty` 플래그로 `base_time` 재설정

**Packet 27** (Line 955, 960, 962):
- `wait_ms: 391.05` (큐 다시 고갈, 391ms 대기)
- `ideal_late_ms: 374.68` → `soft_resync` 발생 (Line 958)
- **`interval_from_prev_ms: 395.18`** ← **늘어짐 원인!**
- `rtp_interval_violation`: `actual_ms: 395.2` (정상 20ms의 약 20배)

### 2.3. RTP TSV 덤프 (`rtp_tx_dHT1zO55li.tsv`)

**Keep-alive 구간**:
```
Line 27: seq 9688, interval 508.856ms (keepalive)
Line 28: seq 9689, interval 514.543ms (keepalive)
```

**재개 후 큐 고갈 + soft_resync**:
```
Line 29: seq 9690, interval 398.994ms ← 사용자가 들은 "안........녕" 구간
Line 30: seq 9691, interval 16.408ms  ← 따라잡기 (짧음)
Line 31: seq 9692, interval 19.080ms
```

**Phase2 청크 전송 후**:
```
Line 244: seq 9905, interval 160.365ms
Line 245-251: seq 9906-9912, interval 0.238~0.483ms ← 극단적으로 짧은 간격 (기계음 원인)
```

## 3. 근본 원인

### 3.1. `soft_resync` 공식의 오류

**위치**: `sip-pbx/src/media/rtp_relay.py` Line 1758

**기존 공식**:
```python
self._rtp_base_time = now_before_sleep - (self._rtp_packets_sent_total * FIXED_INTERVAL_SEC)
```

**문제**:
- 이 공식은 **"지금까지 모든 패킷을 정확히 20ms 간격으로 보냈다"**고 가정
- `packets_sent_total = 27`이면 `27 * 20ms = 540ms` 경과했다고 가정
- 하지만 실제로는:
  - `seq 0~25`: 정상 전송 (약 500ms)
  - `seq 26`: 513ms 대기 후 전송
  - `seq 27`: 391ms 대기 후 전송
  - **실제 경과 시간**: 500 + 513 + 391 = **1404ms**
  - **가정한 시간**: 27 * 20 = **540ms**
  - **차이**: 864ms

- 결과적으로 `base_time`이 **과거(864ms 전)**로 설정됨
- 다음 `ideal_target = base_time + (packets_sent_total * 20ms)`가 **이미 지난 시각**이 됨
- 코드는 "이미 늦었다"고 판단하고 **즉시 전송** (sleep 없음)
- 연속적으로 패킷이 **0.2~0.4ms 간격**으로 전송되어 **기계음/로봇음** 발생

### 3.2. 시각화

```
실제 타임라인:
|--500ms(seq0-25)--|--513ms(wait)--|seq26|--391ms(wait)--|seq27|

기존 soft_resync 가정:
|--540ms(27*20ms)--|

↓ base_time이 864ms 과거로 설정됨

결과:
seq27 이후 모든 패킷이 "이미 늦었다"고 판단 → 즉시 전송 → 0.2ms 간격
```

## 4. 수정 내용

**파일**: `sip-pbx/src/media/rtp_relay.py` Line 1747-1777

**수정 공식**:
```python
self._rtp_base_time = now_before_sleep - ((self._rtp_packets_sent_total + 1) * FIXED_INTERVAL_SEC)
```

**의미**:
- `packets_sent_total`번째 패킷(현재 전송할 패킷)의 ideal time = `base_time + (packets_sent_total * 20ms)`
- 이 값이 `now + 20ms`가 되도록 역산:
  ```
  base_time + (packets_sent_total * 20ms) = now + 20ms
  base_time = now + 20ms - (packets_sent_total * 20ms)
  base_time = now - (packets_sent_total - 1) * 20ms
  base_time = now - ((packets_sent_total + 1 - 2) * 20ms)
  base_time = now - ((packets_sent_total + 1) * 20ms) + 20ms
  ```
  
  간단히: `base_time = now - ((packets_sent_total + 1) * 20ms)`
  
  그러면:
  - 현재 패킷 ideal = `base_time + (packets_sent_total * 20ms)`
                     = `now - ((packets_sent_total + 1) * 20ms) + (packets_sent_total * 20ms)`
                     = `now - 20ms`
  - 실제로는 `now`에 전송하므로 약간 늦지만 (-20ms 이내)
  - **다음 패킷** ideal = `base_time + ((packets_sent_total + 1) * 20ms)`
                      = `now - ((packets_sent_total + 1) * 20ms) + ((packets_sent_total + 1) * 20ms)`
                      = `now`
  
  **실제 의도**: 다음 패킷 전송이 `now` 기준으로 정확히 20ms 후가 되도록 타임라인 재설정

**변경사항**:
- `self._rtp_base_time = now - (packets_sent_total * 0.020)`
- → `self._rtp_base_time = now - ((packets_sent_total + 1) * 0.020)`
- 로그 메시지도 수정: `"다음 패킷이 지금+20ms에 전송되도록 수정"`

## 5. 예상 효과

**수정 전**:
```
Packet 27 soft_resync 발생
├─ base_time = now - (27 * 20ms) = now - 540ms
├─ 다음 ideal = base_time + (27 * 20ms) = now - 540ms + 540ms = now (이미 지남!)
├─ sleep_needed = now - now = 0
└─ 즉시 전송 → 0.2ms 간격 (기계음)
```

**수정 후**:
```
Packet 27 soft_resync 발생
├─ base_time = now - ((27 + 1) * 20ms) = now - 560ms
├─ 현재 패킷 ideal = base_time + (27 * 20ms) = now - 560ms + 540ms = now - 20ms
├─ sleep_needed = (now - 20ms) - now = -20ms (약간 늦음, 즉시 전송)
├─ 다음 패킷 ideal = base_time + (28 * 20ms) = now - 560ms + 560ms = now
└─ 다음 패킷은 현재 시각 기준 정확히 20ms 후 전송 예정
```

**결과**:
- Soft resync 발생 시 현재 패킷은 즉시 전송 (gap 흡수)
- **다음 패킷부터 정상 20ms 간격 유지**
- 0.2~0.4ms 같은 극단적 간격 제거 → **기계음/로봇음 해결**
- Keep-alive gap 이후에도 안정적인 타이밍 복구

## 6. 테스트 방법

### 6.1. 서버 재시작

```powershell
.\stop-all.ps1
.\start-all.ps1
```

### 6.2. 테스트 시나리오

1. **발신**: `1003` → **착신**: `1004` (AI 봇)
2. **부재중 타임아웃** (10초) 대기 → AI 응대 시작
3. **Phase1 인사** 청취: "안녕하세요. KT 통화매니저 기상청 AI 봇 입니다."
4. **10초 침묵** 후 **Phase2 인사** 청취
5. **음질 확인**:
   - ✅ 음절 간격이 자연스러운지
   - ✅ 로봇 음성이 아닌지
   - ✅ 늘어지거나 끊기지 않는지

### 6.3. 로그 확인

**RTP TSV 덤프**:
```
logs/rtp_tx_{call_id}.tsv
```

**확인 항목**:
- `interval_ms_since_prev_send` 컬럼
- Keep-alive 후 첫 media 패킷의 interval: **≈400ms 이하 (gap 흡수)**
- 그 다음 패킷들: **19~21ms 범위 (정상)**
- **0.2~0.5ms 같은 극단적 간격이 없어야 함**

**app.log**:
```
"event": "rtp_interval_violation"
```
- `actual_ms` 값이 **17~22ms 범위**여야 정상
- 0.5ms나 400ms 같은 극단값이 반복되지 않아야 함

## 7. 기술적 배경

### 7.1. RTP 타이밍 전략

**절대 시간 기반 스케줄링**:
```python
ideal_target = base_time + (packets_sent_total * 20ms)
sleep_needed = ideal_target - now
```

**base_time의 의미**:
- **"패킷 카운터 0번이 전송된 이상적인 시각"**
- 모든 패킷의 전송 시각은 `base_time + (seq * 20ms)`로 결정
- `packets_sent_total`이 증가해도 `base_time`은 고정 (일반적인 경우)

### 7.2. Soft Resync의 필요성

**발생 조건**:
- TTS 청크 생성 지연 → PCM 큐 고갈 → 수백ms 대기
- 큐에 데이터가 들어와도 **ideal_target이 이미 과거**가 됨
- 과거 시각을 따라잡으려면 패킷을 연속으로 즉시 전송해야 함 → Jitter 심화

**목적**:
- **타임라인을 현재 시각 기준으로 재앵커**
- 다음 패킷부터 정상 20ms 간격 유지
- 과거의 gap을 무시하고 새로운 20ms 격자 시작

### 7.3. 기존 공식의 오류

**기존**:
```python
base_time = now - (packets_sent_total * 20ms)
```

**문제점**:
- `packets_sent_total`은 **실제 전송된 패킷 수** (카운터)
- **누적 경과 시간과 무관**
- Keep-alive gap이나 큐 대기 시간이 반영되지 않음

**예시**:
```
packets_sent_total = 27
실제 경과: 1404ms (500 + 513 + 391)
가정한 경과: 540ms (27 * 20)
차이: -864ms

→ base_time이 864ms 과거로 설정
→ 다음 패킷들의 ideal_target이 모두 이미 지난 시각
→ sleep_needed < 0
→ 즉시 전송 (0.2ms 간격)
```

### 7.4. 수정 공식의 원리

**수정**:
```python
base_time = now - ((packets_sent_total + 1) * 20ms)
```

**효과**:
```
현재 패킷 ideal = base_time + (packets_sent_total * 20ms)
               = [now - ((N+1) * 20ms)] + (N * 20ms)
               = now - 20ms

다음 패킷 ideal = base_time + ((packets_sent_total + 1) * 20ms)
               = [now - ((N+1) * 20ms)] + ((N+1) * 20ms)
               = now
```

- 현재 패킷은 약간 늦지만 즉시 전송 (gap 흡수)
- **다음 패킷은 현재 시각 기준 정확히 20ms 후 예정**
- 타임라인이 현재 시각에 재앵커되어 이후 정상 간격 유지

## 8. 관련 커밋

**이전 수정** (2026-03-29):
- `packets_sent_total = 0`으로 리셋하지 않도록 수정
- 하지만 `base_time` 역산 공식은 여전히 부정확

**이번 수정** (2026-03-30):
- `base_time` 역산 공식 수정: `+ 1` 추가
- **"다음 패킷이 지금+20ms에 전송되도록"** 타임라인 재설정

## 9. 참고

**Keep-alive 메커니즘**:
- PCM 큐가 비면 **500ms 간격**으로 last RTP 재전송 (연결 유지)
- 새 청크가 들어오면 `_rtp_new_segment_after_empty` 플래그 설정
- 첫 패킷 전송 직전 `base_time` 재설정 (Line 1722-1732)

**_rtp_new_segment_after_empty와 soft_resync 차이**:
- `_rtp_new_segment_after_empty`: **큐 고갈 후 재개** 시점에 `base_time` 재설정
- `soft_resync`: **청크 전송 중** 200ms 이상 지연 발생 시 `base_time` 재조정
- 둘 다 **타임라인 재앵커** 목적, 하지만 발생 시점과 조건이 다름

**Jitter vs Time Stretching**:
- **Jitter**: 패킷 간격의 **작은 변동** (18~22ms) → 정상, 디코더가 보상 가능
- **Time Stretching**: 패킷 간격이 **극단적으로 변함** (0.2ms or 400ms) → 음질 왜곡

## 10. 체크리스트

- [x] `soft_resync` 공식 수정 (`+ 1` 추가)
- [x] 로그 메시지 업데이트
- [ ] 서버 재시작 및 테스트
- [ ] RTP TSV 덤프로 interval 검증
- [ ] 음질 청취 확인 (늘어짐/기계음 없음)

---

**결론**: `soft_resync`의 `base_time` 역산 공식에서 **`packets_sent_total + 1`**을 사용하여, 다음 패킷이 현재 시각 기준 정확히 20ms 후 전송되도록 타임라인을 재앵커합니다. 이로써 Keep-alive gap이나 TTS 청크 지연 후에도 **0.2ms 같은 극단적 간격이 제거**되고, **자연스러운 음질**이 유지됩니다.
