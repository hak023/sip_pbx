# RTP 구조 개선 완료 리포트

**작성일**: 2026-03-29 18:20 KST  
**상태**: 구현 완료  
**버전**: v2.0 (고정 간격)  
**관련 리포트**: `2026-03-29_1810_RTP_ADAPTIVE_INTERVAL_CATASTROPHIC_FAILURE_0M~pwWSh1D.md`

---

## 1. 긴급 요약

### ✅ 완료 사항

1. **복잡한 로직 완전 제거**
   - `cumulative_ideal_time_sec` 변수 및 관련 로직 (12곳) 삭제
   - 적응형 간격 변경 로직 (48줄) 삭제
   - 1초 초과 강제 리셋 로직 삭제

2. **고정 20ms 간격 복원**
   - 단순 곱셈 방식: `ideal_target = base_time + (packets_sent * 0.020)`
   - 예측 가능한 타이밍

3. **PCM Queue 크기 증가**
   - 150 → **500개** (10초 버퍼)
   - 백로그 흡수 능력 3.3배 증가

4. **Soft Resync 완화**
   - `-40ms` → **`-200ms`** (5배 완화)
   - 작은 지연은 자연스럽게 따라잡기

---

## 2. 주요 변경 사항

### 2.1 PCM Queue 크기 증가

**`rtp_relay.py` (line 2028)**

```python
# 변경 전:
# self._pipecat_pcm_queue = queue.Queue(maxsize=150)

# 변경 후:
self._pipecat_pcm_queue = queue.Queue(maxsize=500)  # 10초 버퍼 (백로그 흡수)
```

### 2.2 간격 변수 단순화

**`rtp_relay.py` (line 1467)**

```python
# 변경 전:
# current_chunk_interval_sec = 0.020  # 현재 청크에 적용 중인 간격
# cumulative_ideal_time_sec = 0.0  # 누적 절대 시간 추적

# 변경 후:
FIXED_INTERVAL_SEC = 0.020  # 고정 20ms 간격 (안정성 최우선)
```

### 2.3 적응형 간격 로직 제거

**`rtp_relay.py` (line 1702-1719 삭제)**

```python
# 삭제된 코드:
# prev_chunk_interval = current_chunk_interval_sec
# current_chunk_interval_sec = self._get_adaptive_packet_interval_sec()
# 
# if abs(current_chunk_interval_sec - prev_chunk_interval) > 0.001:
#     queue_size_now = self._pipecat_pcm_queue.qsize()
#     logger.info("adaptive_interval_changed", ...)
```

### 2.4 타이밍 계산 복원

**`rtp_relay.py` (line 1738)**

```python
# 변경 전:
# ideal_target = self._rtp_base_time + cumulative_ideal_time_sec

# 변경 후:
ideal_target = self._rtp_base_time + (self._rtp_packets_sent_total * FIXED_INTERVAL_SEC)
```

**`rtp_relay.py` (line 1805)**

```python
# 변경 전:
# expected_from_base_ms = cumulative_ideal_time_sec * 1000

# 변경 후:
expected_from_base_ms = self._rtp_packets_sent_total * FIXED_INTERVAL_SEC * 1000
```

### 2.5 Soft Resync 완화

**`rtp_relay.py` (line 1750)**

```python
# 변경 전:
# resync_thr = self._RTP_SCHED_SOFT_RESYNC_LATE_MS / 1000.0  # -40ms

# 변경 후:
resync_thr = 0.200  # -200ms (5배 완화)
```

### 2.6 강제 리셋 제거

**`rtp_relay.py` (line 1852-1861 삭제)**

```python
# 삭제된 코드:
# if not getattr(self, "_rtp_new_segment_after_empty", False) and abs(current_error_ms) > 1000.0:
#     logger.warning("rtp_timing_drift_reset", ...)
#     self._rtp_base_time = time.perf_counter()
#     self._rtp_packets_sent_total = 0
#     cumulative_ideal_time_sec = 0.0
```

### 2.7 로그 메시지 업데이트

- `"적응형 간격"` → `"고정 간격"` 또는 `"고정 20ms 간격"`
- `cumulative_ideal_time_sec` 필드 제거
- `current_interval_ms` 필드 제거 (항상 20ms)

---

## 3. 설계 철학

### 3.1 단순성 최우선

> **"Perfect is the enemy of good"**

- 복잡한 적응형 간격 → **단순한 고정 간격**
- 12곳의 초기화 → **단순한 곱셈**
- 예측 불가능 → **예측 가능**

### 3.2 RTP 본질 준수

> RTP는 **일정한 간격(20ms)**을 기대

- 고정 간격 → **Jitter 최소화**
- 수신 측 Jitter Buffer 안정
- 음질 향상

### 3.3 생산자-소비자 분리

```
TTS API (생성) → PCM Queue (완충) → RTP Sender (전송)
     ↑                ↑                    ↓
  가변 속도         큰 버퍼             고정 속도
```

- **PCM Queue가 백로그 흡수**
- **RTP Sender는 일정 속도 유지**
- **디커플링**

---

## 4. 예상 효과

### 4.1 정량적 목표

| 지표 | 현재 (재앙) | 목표 |
|------|------------|------|
| 패킷 손실률 | 46.8% | **< 5%** |
| Jitter (max-min) | 19ms | **< 5ms** |
| 타이밍 오차 | 1초/5초 | **< 100ms** |
| 강제 리셋 빈도 | 5초마다 | **0** |
| 코드 복잡도 | 높음 | **매우 낮음** |

### 4.2 정성적 기대

1. **음질 안정**
   - 뭉개짐/건너뛰기 없음
   - 자연스러운 재생

2. **디버깅 용이**
   - 로그 단순
   - 문제 추적 쉬움

3. **유지보수성**
   - 코드 이해 쉬움
   - 수정 안전

---

## 5. 코드 변경 요약

### 제거된 코드

1. **`cumulative_ideal_time_sec` 관련** (12곳):
   - Line 1468: 초기화
   - Line 1586: 첫 PCM 시 초기화
   - Line 1728: 안전 체크 시 초기화
   - Line 1747: 새 세그먼트 시 초기화
   - Line 1757: Soft Resync 시 초기화
   - Line 1738: `ideal_target` 계산에서 제거
   - Line 1793: 로그에서 제거
   - Line 1805: `expected_from_base_ms` 계산에서 제거
   - Line 1861: 강제 리셋 시 초기화 제거
   - Line 1872: 증가 코드 제거
   - Line 1999: 로그에서 제거

2. **적응형 간격 로직** (line 1702-1719):
   - `_get_adaptive_packet_interval_sec()` 호출 제거
   - 간격 변경 감지 및 로그 제거

3. **1초 초과 강제 리셋** (line 1852-1861):
   - `rtp_timing_drift_reset` 이벤트 제거
   - `base_time`/`packets_sent_total` 리셋 제거

### 변경된 코드

1. **고정 간격 상수** (line 1467)
2. **타이밍 계산** (line 1738, 1805)
3. **Soft Resync 임계값** (line 1750)
4. **PCM Queue 크기** (line 2028)
5. **로그 메시지** (여러 곳)

---

## 6. 테스트 체크리스트

### 6.1 백엔드 시작 전 확인

- [x] 코드 수정 완료
- [x] Linter 오류 없음
- [ ] 백엔드 재시작 필요

### 6.2 테스트 통화 (3~5회)

#### 확인 사항

1. **로그 확인**:
   - [ ] `rtp_timing_drift_reset` 없음
   - [ ] `adaptive_interval_changed` 없음
   - [ ] `rtp_timing_drift_detected` < 5회 (100ms 이상 오차)
   - [ ] `rtp_interval_violation` < 10회 (50 패킷당)

2. **Jitter 측정**:
   - [ ] `interval_max_ms - interval_min_ms < 5ms` (목표)
   - [ ] `rtp_tts_send_window_stats` 로그 확인

3. **손실률 계산**:
   - [ ] TTS 생성 바이트 → 예상 패킷 수
   - [ ] 실제 전송 패킷 수 (로그)
   - [ ] 손실률 < 5%

4. **청취 테스트**:
   - [ ] 뭉개짐/건너뛰기 없음
   - [ ] 자연스러운 재생
   - [ ] 긴 문장(100자+) 완전 재생

### 6.3 백로그 모니터링

1. **PCM Queue 크기**:
   - [ ] 최대 크기 < 400개 (80% 미만)
   - [ ] 평균 크기 < 100개

2. **경고 로그**:
   - [ ] `tts_udp_out_queue_backlog_high` < 3회
   - [ ] `rtp_tts_queue_depleted` 없음

---

## 7. 롤백 정보

### 변경된 파일

1. `src/media/rtp_relay.py`
   - Line 1467: 간격 변수
   - Line 1586: 첫 PCM 초기화
   - Line 1700-1729: 적응형 간격 로직 제거
   - Line 1738: `ideal_target` 계산
   - Line 1750: Soft Resync 임계값
   - Line 1792: 로그 메시지
   - Line 1805: `expected_from_base_ms` 계산
   - Line 1825: 타이밍 로그
   - Line 1826-1861: 강제 리셋 제거
   - Line 1917: sleep 간격
   - Line 1997: 청크 완료 로그
   - Line 2028: PCM Queue 크기

2. `config/config.yaml`
   - Line 67: `enabled: false` (이미 수정됨)

### Git 커밋 메시지 (참고)

```
fix(rtp): 고정 20ms 간격 복원, 적응형 간격 로직 제거

- cumulative_ideal_time_sec 관련 코드 전체 제거 (12곳)
- 적응형 간격 변경 로직 삭제 (48줄)
- 1초 초과 강제 리셋 제거
- 고정 20ms 간격으로 단순화 (base_time + packets_sent * 0.020)
- PCM Queue 크기 150 → 500 (10초 버퍼)
- Soft Resync 임계값 -40ms → -200ms (완화)

근본 원인: 동적 간격 + 절대 시간 추적 + 강제 리셋 = 타이밍 붕괴
해결책: 단순한 고정 간격 (예측 가능, Jitter 최소화, 유지보수 용이)

기대 효과: 손실률 46.8% → < 5%, Jitter 19ms → < 5ms
```

---

## 8. 기술 부채 해소

### 제거된 복잡도

1. **12곳의 초기화 로직** → **0곳**
2. **4가지 리셋 조건** → **1가지 (Soft Resync, 완화됨)**
3. **48줄의 적응형 간격 로직** → **0줄**
4. **예측 불가능한 타이밍** → **완전 예측 가능**

### 코드 라인 수 감소

- **총 감소**: 약 80줄
- **복잡도**: 높음 → **매우 낮음**
- **유지보수성**: 어려움 → **쉬움**

---

## 9. 설계 원칙 준수

### ✅ KISS (Keep It Simple, Stupid)
- 가장 단순한 해결책 선택
- 복잡한 로직 제거

### ✅ YAGNI (You Aren't Gonna Need It)
- 적응형 간격은 "필요하다고 생각했지만" 실제로는 **불필요**
- 고정 간격으로 충분

### ✅ 단일 책임 원칙
- PCM Queue: 백로그 흡수
- RTP Sender: 일정한 전송

---

## 10. 다음 단계

### 즉시 (사용자 실행)

1. **백엔드 재시작**
   ```bash
   # 기존 프로세스 종료 (이미 완료)
   # 새 백엔드 시작
   python sip-pbx/src/main.py
   ```

2. **테스트 통화** (3~5회)
   - 긴 문장 (100자+) 포함
   - 로그 확인

3. **로그 분석**
   - `app.log`에서 Jitter/손실률 계산
   - 뭉개짐 여부 청취

### 단기 (1~2일)

1. **안정성 모니터링**
   - 실제 통화에서 Jitter/손실률 추적
   - 백로그 패턴 분석

2. **필요 시 미세 조정**
   - Soft Resync 임계값 조정
   - PCM Queue 크기 조정

### 중장기 (선택)

1. **응답별 고정 간격** (필요 시)
   - 백로그 패턴이 일정하면 고려

2. **전문 RTP 스택** (대규모 배포 시)
   - PJSIP/GStreamer 검토

---

## 11. 지식베이스 업로드 수정 (보너스)

### 문제
- TXT 업로드 FAQ가 프론트엔드에서 보이지 않음
- `doc_type: "faq"` (프론트엔드 필터에 없음)

### 해결
1. **`manual_to_faq_extractor.py`** (line 365-380):
   - `category`: LLM 생성값 → `"question"` (프론트엔드 호환)
   - `doc_type`: `"faq"` → `"knowledge"` (프론트엔드 호환)
   - `source`: `"manual_upload:파일명"` → `"manual"` (프론트엔드 호환)
   - LLM 원본 카테고리는 `metadata.faq_category`에 보관

2. **`knowledge_service.py`** (line 229-268):
   - `delete_by_source_file()` 메서드 추가 (파일명 기반 일괄 삭제)

3. **`knowledge_api.py`** (line 127):
   - `replace_existing` 파라미터 추가 (자동 삭제 후 업로드)

4. **삭제 스크립트** (`scripts/delete_manual_faqs.py`):
   - 기존 6개 FAQ 삭제용

---

## 12. 결론

### ✅ 구현 완료

1. **RTP 전송 구조 단순화** (고정 20ms 간격)
2. **복잡한 로직 완전 제거** (80줄 감소)
3. **PCM Queue 크기 증가** (500개, 10초 버퍼)
4. **지식베이스 업로드 수정** (프론트엔드 호환)

### 예상 결과

- **패킷 손실률**: 46.8% → **< 5%**
- **Jitter**: 19ms → **< 5ms**
- **타이밍 오차**: 1초/5초 → **< 100ms**
- **음질**: 뭉개짐 → **자연스러운 재생**

### 교훈

> **단순한 해결책이 복잡한 해결책보다 낫다**

- 적응형 간격: 좋은 의도, 나쁜 결과
- 고정 간격: 단순하지만 안정적
- **안정성 > 최적화**

---

## 13. 백엔드 시작 가이드

```bash
# 1. 터미널에서 백엔드 디렉토리로 이동
cd c:\work\workspace_sippbx\sip-pbx

# 2. 백엔드 시작
python src/main.py

# 3. 로그 확인
# - "RTP 적응형 패킷 간격 비활성화 — 고정 20ms 간격 사용" 로그 확인
# - 테스트 통화 후 "rtp_timing_drift_reset" 없는지 확인
# - "rtp_tts_send_window_stats"에서 Jitter < 5ms 확인
```

---

**작성자**: AI Assistant  
**구현 시간**: 10분  
**검증 대기**: 백엔드 재시작 후 테스트 통화
