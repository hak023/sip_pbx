# TTS → RTP 지연 및 STT 문제 분석

**날짜**: 2026-03-09  
**Call ID**: `wMgYQLUb5Q`  
**통화 시간**: 14:45:05 ~ 14:45:58

---

## 문제 1: TTS → RTP 출력 지연 (약 3초)

### 타임라인 분석

#### Phase 1 인사말

| 시간 | 이벤트 | 설명 |
|------|--------|------|
| `14:45:25.414` | `rag_llm_greeting_phase1` | TTS 텍스트 생성: "안녕하세요. 기상청 AI 상담원입니다. 어떤 도움이 필요하신가요?" |
| `14:45:25.475` | `tts_text_input` | TTS로 텍스트 전달: "안녕하세요." (첫 문장) |
| `14:45:25.475` | `tts_first_audio_received` | **TTS 음성 합성 완료** (텍스트 → 오디오) |
| `14:45:28.454` | `tts_first_audio_sent_to_rtp` | **RTP 전송 시작** ⚠️ |

**지연 시간**: **2.98초** (25.475 → 28.454)

---

### 원인 분석

#### 1. **Google TTS 지연** (2~3초)
- **현재 Voice 모델**: `ko-KR-Neural2-A`
- **문제**: Neural2 모델은 품질은 높지만 **합성 속도가 느림**
- **로그 증거**:
  ```
  14:45:25.475 - tts_first_audio_received (TTS 완료)
  14:45:28.454 - tts_first_audio_sent_to_rtp (RTP 전송)
  ```

#### 2. **Pipecat Pipeline 오버헤드**
- TTS → Output Transport → RTP Builder → Queue → UDP Send
- 각 단계마다 asyncio context switch 발생

#### 3. **RTP 패킷 빌더 지연**
- PCM 16000 bytes → 25 RTP packets 생성
- `packets_enqueued: 25` (334ms 소요)

---

## 문제 2: RTP 패킷 유실 및 간격 이탈

### 통계

| 항목 | 값 |
|------|-----|
| 총 전송 패킷 | 820+ |
| 간격 이탈 횟수 | **550+** |
| 이탈률 | **67%** |
| 기대 간격 | 20ms |
| 실제 간격 | 2~32ms (불규칙) |

### 로그 증거

```
14:45:28.463 - rtp_interval_violation: actual_ms=8.3, expected_ms=20, packets_sent=1
14:45:28.492 - rtp_interval_violation: actual_ms=28.0, expected_ms=20, packets_sent=2
14:45:28.524 - rtp_interval_violation: actual_ms=31.6, expected_ms=20, packets_sent=3
14:45:28.526 - rtp_interval_violation: actual_ms=2.2, expected_ms=20, packets_sent=4  ⚠️ 너무 빠름
14:45:28.541 - rtp_interval_violation: actual_ms=14.9, expected_ms=20, packets_sent=5
...
14:45:58.298 - rtp_interval_violation: packets_sent=820, violation_count=550
```

### 원인 분석

#### 1. **큐 오버플로우**
- `queue_size: 25 → 74 → 118 → 240 → 418` (1초에 400개 누적)
- **문제**: TTS가 RTP 전송보다 **훨씬 빠르게** 오디오 생성
- **결과**: 큐에 패킷이 쌓이고, 발송 루프가 burst 전송

#### 2. **asyncio.sleep(0.02) 부정확**
- Python asyncio는 **정확한 타이머가 아님**
- 다른 Task가 CPU를 점유하면 sleep이 지연됨
- **증거**: `actual_ms=2.2` (너무 빠름) 또는 `actual_ms=32` (너무 느림)

#### 3. **UDP sendto 블로킹**
- Windows `_ProactorDatagramTransport`는 non-blocking이지만
- OS 네트워크 스택이 혼잡하면 지연 발생

---

## 문제 3: STT 작동하지 않음

### 증거

**로그 전체 검색 결과**: STT 관련 로그가 **단 한 줄도 없음**

#### 예상되는 STT 로그 (없음)
- ❌ `stt_interim_result`
- ❌ `stt_final_result`
- ❌ `TranscriptionFrame`
- ❌ `emit_stt_transcript`

#### 실제 있는 로그
- ✅ `pipecat_audio_stream_started` (14:45:24.818)
- ✅ `pipecat_audio_stream_first_packet` (14:45:24.909, pcm_len=638)
- ✅ `timing_caller_rtp_first_to_pipeline` (14:45:24.818)

**결론**: **Input Transport는 작동하지만, STT가 음성을 인식하지 못함**

---

### 원인 분석

#### 1. **Google STT 스트림이 열리지 않음**
- **로그 부재**: `google_stt_stream_opened`, `stt_request_sent` 등이 없음
- **원인**: `GoogleSTTService`가 초기화되었지만 스트림이 시작되지 않음

#### 2. **VAD가 음성을 탐지하지 못함**
- VAD가 "침묵"으로 판단하면 STT로 전달 안 함
- **로그 부재**: `vad_speech_detected`, `vad_speech_end` 등이 없음

#### 3. **Pipeline 연결 문제**
- Input Transport → VAD → **STT** → LLM
- STT 프로세서가 프레임을 받지 못하고 있음

#### 4. **Google API 인증 실패 (가능성)**
- API 키 또는 권한 문제로 조용히 실패
- **증거 부족**: 에러 로그도 없음

---

## 해결 방안

### 1. TTS 지연 해결

#### ✅ Voice 모델 변경 (속도 우선)
```python
# Before
"voice_name": "ko-KR-Neural2-A",  # 고품질, 느림

# After (Standard - 빠름)
"voice_name": "ko-KR-Standard-A",

# 또는 (Journey - 빠르고 자연스러움, 신모델)
"voice_name": "ko-KR-Journey-F",
```

#### ✅ Streaming TTS 활성화
- 현재는 전체 문장을 합성 후 전송
- **개선**: 문장 단위 스트리밍 (첫 단어부터 빠르게 전송)

---

### 2. RTP 패킷 유실 해결

#### ✅ 정밀한 타이머 사용
```python
import time

async def _pipecat_outgoing_sender_loop(self):
    last_send_time = time.perf_counter()
    while self._pipecat_mode:
        try:
            packet = await asyncio.wait_for(
                self._pipecat_outgoing_queue.get(), 
                timeout=1.0
            )
            
            # 정확한 20ms 대기
            elapsed = time.perf_counter() - last_send_time
            if elapsed < 0.020:
                await asyncio.sleep(0.020 - elapsed)
            
            self._caller_audio_rtp_sock.sendto(packet, self._caller_rtp_addr)
            last_send_time = time.perf_counter()
            
        except asyncio.TimeoutError:
            continue
```

#### ✅ 큐 크기 제한
```python
self._pipecat_outgoing_queue = asyncio.Queue(maxsize=50)  # 기존: 무제한
```

#### ✅ Jitter Buffer 추가 (전화기 측)
- SIP 클라이언트의 jitter buffer 설정 확인
- 권장: 40~60ms

---

### 3. STT 작동 해결

#### ✅ STT 디버깅 로그 추가

**`sip-pbx/src/ai_voicebot/pipecat/rtp_transport.py`**:
```python
async def write_frame_to_stream(self, frame: Frame):
    if isinstance(frame, InputAudioRawFrame):
        logger.info("input_audio_frame_forwarding",
                   call_id=self._call_id,
                   audio_len=len(frame.audio),
                   note="Input Transport → STT로 오디오 전달")
```

**`sip-pbx/src/sip_core/call_manager.py`** (STT Service 생성 시):
```python
_stt_pipecat = GoogleSTTService(**_stt_config)
logger.info("google_stt_service_test",
           call_id=call_id,
           note="STT 서비스 초기화 완료 - 스트림 열기 테스트")
```

#### ✅ VAD 민감도 조정
```python
VADDetector(
    mode=2,  # 기존: 3 (매우 엄격) → 2 (보통)
    frame_duration_ms=30,
    sample_rate=16000
)
```

#### ✅ Google STT 스트림 강제 시작
```python
# Pipeline 시작 직후
await stt.start()  # STT 스트림 명시적 시작
logger.info("stt_stream_started", call_id=call_id)
```

#### ✅ API 키 재확인
```bash
gcloud auth application-default print-access-token
```

---

## 우선순위

| 순위 | 문제 | 영향도 | 해결 난이도 |
|------|------|--------|------------|
| **1** | STT 작동하지 않음 | 🔴 Critical | 중 |
| **2** | RTP 패킷 유실 | 🟠 High | 중 |
| **3** | TTS 지연 | 🟡 Medium | 낮 |

---

## 다음 단계

1. **STT 디버깅 로그 추가** → 로그 확인
2. **VAD mode 2로 변경** → 테스트
3. **Voice 모델 Standard-A로 변경** → 속도 개선
4. **RTP 타이머 정밀화** → 패킷 유실 감소
5. **재테스트 및 로그 분석**

---

## 참고

- Google TTS Voice 목록: https://cloud.google.com/text-to-speech/docs/voices
- asyncio 정밀 타이머: https://docs.python.org/3/library/time.html#time.perf_counter
- RTP Jitter: https://tools.ietf.org/html/rfc3550#section-6.4
