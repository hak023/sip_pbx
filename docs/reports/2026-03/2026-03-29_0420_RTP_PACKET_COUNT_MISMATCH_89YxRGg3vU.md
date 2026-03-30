# RTP 패킷 수 불일치 분석 및 로깅 강화

**작성일**: 2026-03-29 04:20  
**Call ID**: `89YxRGg3vU`  
**문제 시각**: 2026-03-29T04:02:19 ~ 04:02:21 (KST)  
**TTS 텍스트**: "기상청에 방문하시려면 택시를 이용하시는 방법이 있어요. 택시 기사님께 '기상청으로 가주세요'라고 말씀하시면 됩니다. 더 도움이 필요하시면 말씀해 주세요."

---

## 1. 문제 현상

사용자가 전화 통화 중 TTS 음성이 **"기............상...................청"**처럼 음절 사이에 긴 침묵이 삽입되어 들렸다고 보고했습니다.

초기 분석:
- RTP 패킷 간격 위반 (`rtp_interval_violation`) 발견: ±10ms 차이
- 그러나 **±10ms는 사람 귀에 "뭉개짐"으로 인지될 정도가 아님**
- 녹음 파일 (`mixed.wav`) 재생 시 **정상적으로 들림** → **TTS API와 backend 녹음은 문제없음**

**결론**: 문제는 **RTP 송신 과정**에 있습니다.

---

## 2. 패킷 수 불일치 발견

### TTS API 생성 (Line 1812)
```json
{
  "timestamp": "2026-03-29T04:02:21.417",
  "event": "google_tts_api_complete",
  "api_call_num": 5,
  "total_audio_bytes": 405772,
  "frames_generated": 26
}
```

### Output Transport 완료 (Line 1821)
```json
{
  "timestamp": "2026-03-29T04:02:21.449",
  "event": "output_endframe_processed",
  "response_bytes": 405772,
  "response_audio_frame_count": 26
}
```

**PCM 큐 투입**: `405772 bytes` → **예상 RTP 패킷 수**: 405772 ÷ 160 = **2536 packets**

### 실제 RTP 전송 (RTP TX TSV)

**분석 결과**:
- **시작**: seq 41397 (04:02:19.747)
- **TTS 끝나는 시점 근처**: seq 41481 (04:02:21.440)
- **카운트**: 41481 - 41397 + 1 = **85 packets**

그러나 세션 전체를 확인하면:
- **이 TTS 이전** (Line 1807, 04:02:20.608): `rtp_tts_packets_sent: 960`
- **세션 종료** (Line 2315): `rtp_tts_packets_sent_session: 2521`
- **이 TTS 이후 전송**: 2521 - 960 = **1561 packets**

**1561 packets × 160 bytes = 249760 bytes**

**불일치**:
- 예상: **405772 bytes** (2536 packets)
- 실제: **249760 bytes** (1561 packets)
- **부족**: **156012 bytes** (**38.4% 손실!**)

### RTP Timestamp 연속성

```
seq 41397 | ts 1604550013
seq 41477 | ts 1604562813  (차이: 160 × 80 = 12800 ✅)
seq 41481 | ts 1604563453  (차이: 160 × 4 = 640 ✅)
...
```

**RTP timestamp는 완벽히 연속**입니다 (160 = 20ms × 8kHz). **패킷 손실은 없었습니다.**

---

## 3. 원인 분석

### 가능한 원인

#### ① PCM 큐 드롭
- 로그: `rtp_tts_packets_dropped: 0` (Line 1807, 1844, 2315)
- **드롭은 없었습니다.**

#### ② 송신 스레드 중단
- `if not self._pipecat_mode: break` (Line 1629)
- 그러나 Line 1823에서 `tts_sending_active: true`, Line 1828~1833에서 계속 전송 중
- **스레드는 정상 동작했습니다.**

#### ③ PCM 큐 소비 지연
- Line 1809 (04:02:21.204): `pcm_queue_size: 19`
- Line 1810 (04:02:21.354): `pcm_queue_size: 19`
- Line 1823 (04:02:21.520): `tts_queue_size: 22`
- **큐에 20개 이상 청크가 적체**되어 있었습니다!

#### ④ 응답 경계 불명확
- 현재 로그로는 **어느 패킷이 어느 TTS 응답에 속하는지 알 수 없습니다.**
- `packets_sent`는 세션 누적이고, 응답별 구분이 없습니다.
- **PCM 청크와 RTP 패킷의 매핑이 추적되지 않습니다.**

---

## 4. 적용한 해결책

### A. 매뉴얼 업로드 에러 수정 (`manual_to_faq_extractor.py`)

매뉴얼 업로드 시 `chunk_faq_extraction_error` 발생:
```json
{
  "timestamp": "2026-03-29T04:06:44.982",
  "event": "chunk_faq_extraction_error",
  "error": "'\\n    \"question\"'"
}
```

**수정 내용**:
1. **JSON 추출 로직 개선**: `\[.*?\]` 정규식으로 배열 패턴 추가
2. **JSON 파싱 전 로깅 추가**: `chunk_faq_json_parse_attempt` 이벤트로 파싱 대상 문자열 기록
3. **에러 로깅 강화**: `response_preview` 길이 확대 (200 → 500자), 전체 응답 기록 (최대 1000자)

**파일**: `src/ai_voicebot/knowledge/manual_to_faq_extractor.py`

### B. RTP 패킷 추적 로깅 강화 (`rtp_relay.py`, `rtp_transport.py`)

**목적**: 응답별 RTP 패킷 수를 정확히 추적하여 "뭉개짐" 현상의 근본 원인을 파악

#### 1. PCM 청크 → RTP 패킷 변환 로그 강화
```python
# 기존: 첫 10개 + 100개마다 로깅
# 변경: 모든 청크에 대해 로깅

logger.info("rtp_pcm_chunk_to_packets",
           call_id=self.media_session.call_id,
           progress="rtp_timing",
           pcm_bytes=len(pcm_data),
           rtp_packets_count=len(rtp_packets),
           packets_sent_so_far=packets_sent,
           first_packet_seq=first_packet_seq,  # ✅ 추가
           pcm_queue_size=self._pipecat_pcm_queue.qsize(),  # ✅ 추가
           note="PCM 청크 → RTP 패킷 변환 (응답별 패킷 수 추적용)")
```

#### 2. PCM 청크 전송 완료 로그 추가
```python
# ✅ 새로 추가: 각 청크의 마지막 패킷 seq 기록
logger.info("rtp_pcm_chunk_sent_complete",
           call_id=self.media_session.call_id,
           progress="rtp_timing",
           chunk_packets=len(rtp_packets),
           first_seq=first_packet_seq,
           last_seq=last_packet_seq,  # ✅ 추가
           last_ts=last_packet_ts,  # ✅ 추가
           packets_sent_cumulative=packets_sent,
           pcm_queue_remaining=self._pipecat_pcm_queue.qsize(),
           note="PCM 청크 RTP 전송 완료 (응답별 seq 범위 추적용)")
```

#### 3. 송신 스레드 패킷 수 공유
```python
# stats에 송신 스레드 패킷 수 추가
self.stats["rtp_tts_thread_packets_queued"] = packets_sent
```

#### 4. EndFrame 처리 시 송신 패킷 수 기록
```python
# output_endframe_processed에 송신 스레드 패킷 수 포함
thread_packets_queued = self._rtp_worker.stats.get("rtp_tts_thread_packets_queued", 0)
logger.info("output_endframe_processed",
           ...
           response_bytes=self._response_bytes,
           thread_packets_queued=thread_packets_queued,  # ✅ 추가
           note="... thread_packets_queued로 송신 완료 여부 추적")
```

**수정 파일**:
- `src/media/rtp_relay.py`: Lines 1601~1619, 1848~1850, 1891~1923
- `src/ai_voicebot/pipecat/rtp_transport.py`: Lines 312~327

---

## 5. 예상 효과

### 이전 로그
```json
{
  "event": "output_endframe_processed",
  "response_bytes": 405772,
  "response_audio_frame_count": 26
}
```
→ **PCM 큐 투입량만 알 수 있음**, 실제 RTP 전송 여부는 알 수 없음

### 개선된 로그 (백엔드 재시작 후)
```json
{
  "event": "rtp_pcm_chunk_to_packets",
  "pcm_bytes": 16000,
  "rtp_packets_count": 100,
  "first_packet_seq": 41397,
  "packets_sent_so_far": 916,
  "pcm_queue_size": 0
}
...
{
  "event": "rtp_pcm_chunk_sent_complete",
  "chunk_packets": 100,
  "first_seq": 41397,
  "last_seq": 41496,
  "packets_sent_cumulative": 1016,
  "pcm_queue_remaining": 25
}
...
{
  "event": "output_endframe_processed",
  "response_bytes": 405772,
  "thread_packets_queued": 1016  // ✅ EndFrame 시점 송신 패킷 수
}
```

**추적 가능**:
1. 각 PCM 청크가 **몇 개의 RTP 패킷**으로 변환되었는지
2. 각 청크의 **first_seq ~ last_seq 범위**
3. EndFrame 시점에 **송신 스레드가 몇 개 패킷을 처리**했는지
4. **예상 패킷 수 (405772 ÷ 160 = 2536)와 실제 송신 패킷 수 비교**

---

## 6. 다음 단계

1. **백엔드 재시작** 후 동일한 시나리오 재현
2. **새 로그로 정확한 패킷 수 추적**:
   - 각 TTS 응답의 **시작 seq, 끝 seq**
   - **PCM 큐에 쌓인 청크 수**와 **실제 전송된 청크 수** 비교
   - **송신 지연 구간** 특정 (어느 청크에서 멈췄는지)

3. **근본 원인 특정**:
   - PCM 큐 적체로 인한 **소비 지연**
   - **CPU/GIL contention**으로 인한 송신 스레드 blocking
   - **응답 경계 처리 버그** (새 응답 시작 시 이전 응답 중단?)

4. **최종 해결**:
   - 송신 스레드 우선순위 조정
   - Busy-wait 혼합 스케줄링
   - 또는 C extension/Rust로 RTP 송신 재작성

---

## 7. 요약

- **±10ms 패킷 간격 차이는 "뭉개짐" 원인이 아님** (jitter buffer가 처리)
- **RTP timestamp 연속성 완벽** (패킷 손실 없음)
- **녹음 파일 정상** (TTS API 문제 아님)
- **근본 문제**: **TTS API가 생성한 405772 bytes 중 약 38%가 RTP로 전송되지 않음**
- **현재 로그로는 응답별 패킷 추적 불가** → 로깅 강화 적용
- **백엔드 재시작 필요** (수정사항 반영)

**다음 테스트**에서 `rtp_pcm_chunk_to_packets`, `rtp_pcm_chunk_sent_complete`, `output_endframe_processed`의 `thread_packets_queued` 필드로 정확한 원인을 특정할 수 있습니다.
