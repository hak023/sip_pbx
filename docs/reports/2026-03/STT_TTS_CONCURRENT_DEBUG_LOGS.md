# STT 인식 문제 진단 로그 추가 보고서

## 📋 개요

**작성일**: 2026-03-10  
**목적**: TTS 송출 중 STT(Speech-to-Text) 인식이 제대로 동작하지 않는 문제를 진단하기 위한 상세 로그 추가  
**의심 원인**: TTS RTP 전송 로직과 STT 수신 로직 간의 리소스 경합 또는 타이밍 충돌

---

## 🔍 문제 정의

### 증상

사용자 보고:
> "STT도 제대로 인식 못하는 이슈가 있어. 아마 TTS 로 인하여 RTP가 처리할때인것같은데 동시에 STT가 안되는 이슈가있는지 점검해줘."

### 가설

1. **RTP 송수신 충돌**: TTS를 caller에게 전송(송신)하는 동안, caller의 음성(수신)이 제대로 처리되지 않을 수 있음
2. **비동기 큐 블로킹**: TTS PCM 큐(`_pipecat_pcm_queue`)가 가득 차거나, STT 입력 큐(`_pipecat_audio_queue`)가 가득 차서 패킷이 드롭될 수 있음
3. **리소스 경합**: `asyncio.sleep()` 기반 RTP 타이밍으로 인해 CPU 시간을 과도하게 소비하여 STT 처리가 지연될 수 있음
4. **VAD/STT 파이프라인 지연**: TTS 송출 시 발생하는 부하로 인해 VAD(Voice Activity Detection)나 STT 프로세서가 제때 caller 음성을 처리하지 못할 수 있음

---

## 🛠️ 추가된 디버깅 로그

### 1. Caller RTP → STT 입력 로그 (`caller_rtp_to_stt_input`)

**파일**: `sip-pbx/src/media/rtp_relay.py`  
**위치**: `on_packet_received()` 메서드 내, `caller_audio_rtp` 처리 부분

**목적**: Caller의 RTP 음성 패킷이 STT 입력 큐에 정상적으로 들어가는지 확인하고, TTS 송출 상태와 동시에 모니터링

**조건**: 첫 50개 패킷 + 100개마다 기록

**필드**:
- `call_id`: 통화 ID
- `progress`: `"stt_rtp"`
- `packet_count`: 수신한 caller RTP 패킷 수 (누적)
- `rtp_bytes`: RTP 패킷 크기 (bytes)
- `pcm_bytes`: RTP → PCM 변환 후 크기 (bytes, 16kHz)
- `stt_queue_size`: STT 입력 큐 현재 크기
- `tts_sending_active`: TTS 송출이 현재 진행 중인지 여부 (boolean)
- `tts_queue_size`: TTS PCM 큐 현재 크기
- `note`: 설명

**예시**:
```json
{
  "event": "caller_rtp_to_stt_input",
  "call_id": "abc123",
  "progress": "stt_rtp",
  "packet_count": 25,
  "rtp_bytes": 172,
  "pcm_bytes": 320,
  "stt_queue_size": 5,
  "tts_sending_active": true,
  "tts_queue_size": 12,
  "note": "Caller RTP → STT 입력 (TTS 동시 송출 여부 확인)"
}
```

**분석 방법**:
```bash
# STT 입력 로그 추출
Select-String -Path "app.log" -Pattern "caller_rtp_to_stt_input"

# TTS 송출 중 STT 입력 패킷 수 확인
Select-String -Path "app.log" -Pattern "caller_rtp_to_stt_input" | Select-String -Pattern "tts_sending_active.*true"
```

**정상 기준**:
- `stt_queue_size` < 900 (maxsize=1000의 90% 미만)
- `tts_sending_active: true` 상태에서도 `packet_count`가 계속 증가해야 함
- `pcm_bytes` > 0 (RTP → PCM 변환 성공)

**이상 징후**:
- `stt_queue_size` 가 1000에 근접 → STT 입력 큐가 가득 차서 패킷 드롭 위험
- `tts_sending_active: true` 상태에서 `packet_count` 증가가 멈춤 → RTP 수신 중단 (심각)
- `pcm_bytes: 0` 반복 → RTP → PCM 변환 실패

---

### 2. STT 최종 결과 → RAG 로그 개선 (`timing_stt_final_to_rag`)

**파일**: `sip-pbx/src/ai_voicebot/pipecat/processors/rag_processor.py`  
**위치**: `process_frame()` 메서드 내, `TranscriptionFrame` 처리 부분

**목적**: STT 최종 결과가 RAG/LLM에 도달할 때, TTS 송출이 진행 중이었는지 확인

**조건**: 모든 최종 STT 결과마다 기록

**필드 (신규 추가)**:
- `tts_active_during_stt`: STT 처리 시점에 TTS가 활성화되어 있었는지 (boolean)
- `tts_pending_bytes`: TTS로 송출 중인 PCM 바이트 수 (누적)

**예시**:
```json
{
  "event": "timing_stt_final_to_rag",
  "call_id": "abc123",
  "progress": "timing",
  "ts_iso": "2026-03-10T16:48:20.009",
  "text_preview": "날씨 알려주세요",
  "tts_active_during_stt": true,
  "tts_pending_bytes": 48000,
  "note": "STT 최종 결과가 RAG에 도달한 시점 (LLM 호출 직전, TTS 동시 처리 여부 확인)"
}
```

**분석 방법**:
```bash
# TTS 송출 중 STT 인식 확인
Select-String -Path "app.log" -Pattern "timing_stt_final_to_rag" | Select-String -Pattern "tts_active_during_stt.*true"
```

**정상 기준**:
- `tts_active_during_stt: false` 일 때가 대부분 (사용자가 AI 응답 종료 후 말함)
- `tts_active_during_stt: true` 는 barge-in(끼어들기) 시나리오로, VAD가 감지하고 TTS를 중단해야 함

**이상 징후**:
- `tts_active_during_stt: true` 상태에서 STT 인식 없음 → TTS 송출로 인한 STT 차단 의심
- `tts_pending_bytes`가 매우 큼 (예: > 320000 = 10초 분량) → TTS 큐 백로그로 인한 지연

---

### 3. TTS 상태 플래그 (`_tts_active`, `_tts_pending_pcm_bytes`)

**파일**: `sip-pbx/src/ai_voicebot/pipecat/rtp_transport.py`  
**위치**: `SIPPBXOutputTransport.process_frame()` 메서드

**목적**: TTS 송출 시작/종료 시점과 송출 바이트 수를 `tts_sync_context`에 기록하여, STT 로그에서 참조 가능하도록 함

**동작**:
- `LLMFullResponseStartFrame` 수신 시:
  - `_tts_active = True` 설정
  - `_tts_pending_pcm_bytes = 0` 초기화
- 각 오디오 프레임 송출 시:
  - `_tts_pending_pcm_bytes` 누적
- `LLMFullResponseEndFrame` 수신 시:
  - `_tts_active = False` 설정
  - `_tts_pending_pcm_bytes = 0` 리셋

**코드 변경**:
```python
# LLMFullResponseStartFrame 처리
self._tts_sync_context["_tts_active"] = True
self._tts_sync_context["_tts_pending_pcm_bytes"] = 0

# 오디오 프레임 송출 시
self._tts_sync_context["_tts_pending_pcm_bytes"] = self._response_bytes

# LLMFullResponseEndFrame 처리
self._tts_sync_context["_tts_active"] = False
self._tts_sync_context["_tts_pending_pcm_bytes"] = 0
```

---

## 📊 로그 분석 시나리오

### 시나리오 1: 정상 동작 (TTS 종료 후 STT 인식)

**로그 순서**:
1. `tts_text_input` → AI 응답 텍스트 TTS 입력
2. `tts_first_audio_sent_to_rtp` → TTS 오디오 송출 시작
3. `output_endframe_processed` → TTS 송출 완료
4. `caller_rtp_to_stt_input` (tts_sending_active: false) → Caller 음성 수신 시작
5. `timing_stt_final_to_rag` (tts_active_during_stt: false) → STT 인식 성공

**기대 결과**:
- STT 인식 시점에 `tts_active_during_stt: false`
- `caller_rtp_to_stt_input` 로그에서 `stt_queue_size`가 적정 수준 (< 100)

---

### 시나리오 2: Barge-in (TTS 중 사용자 끼어들기)

**로그 순서**:
1. `tts_text_input` → AI 응답 텍스트 TTS 입력
2. `tts_first_audio_sent_to_rtp` → TTS 오디오 송출 시작
3. `caller_rtp_to_stt_input` (tts_sending_active: true) → **TTS 송출 중 Caller 음성 수신**
4. `timing_stt_final_to_rag` (tts_active_during_stt: true) → **STT 인식 성공 (barge-in)**
5. TTS 중단 (VAD StartInterruptionFrame 발생 예상)

**기대 결과**:
- STT 인식 시점에 `tts_active_during_stt: true` 가능 (barge-in)
- VAD가 사용자 음성을 감지하고 `StartInterruptionFrame` 발생
- TTS 송출이 중단되고 새로운 LLM 응답 생성

---

### 시나리오 3: 문제 상황 (TTS 중 STT 인식 실패)

**로그 순서**:
1. `tts_text_input` → AI 응답 텍스트 TTS 입력
2. `tts_first_audio_sent_to_rtp` → TTS 오디오 송출 시작
3. `caller_rtp_to_stt_input` (tts_sending_active: true, stt_queue_size: 950+) → **STT 큐 가득 참**
4. `stt_input_queue_full_dropping` → **Caller PCM 드롭 경고**
5. STT 인식 없음 (silence)

**이상 징후**:
- `stt_queue_size` 가 maxsize(1000)에 근접 → STT 처리 지연
- `stt_input_queue_full_dropping` 경고 발생 → Caller 음성 패킷 드롭
- `timing_stt_final_to_rag` 로그 없음 → STT 인식 자체가 발생하지 않음

**원인 가설**:
- STT 프로세서(Google STT API)가 TTS 송출 부하로 인해 처리 속도 저하
- `asyncio.sleep()` 기반 RTP 타이밍으로 인한 CPU 시간 독점
- AEC(Acoustic Echo Cancellation) 처리 지연

---

## 🔧 로그 분석 명령어

### 1. STT 입력 패킷 수신 현황 확인

```bash
# 전체 caller RTP → STT 입력 로그
Select-String -Path "app.log" -Pattern "caller_rtp_to_stt_input"

# TTS 송출 중 STT 입력 패킷
Select-String -Path "app.log" -Pattern "caller_rtp_to_stt_input" | Select-String -Pattern "tts_sending_active.*true"

# STT 큐 크기가 높은 경우만 필터링 (900 이상)
Select-String -Path "app.log" -Pattern "caller_rtp_to_stt_input" | Select-String -Pattern "stt_queue_size.*9[0-9][0-9]"
```

### 2. TTS 송출 중 STT 인식 확인

```bash
# TTS 활성 상태에서 STT 최종 결과 확인
Select-String -Path "app.log" -Pattern "timing_stt_final_to_rag" | Select-String -Pattern "tts_active_during_stt.*true"

# TTS 비활성 상태에서 STT 최종 결과 확인 (정상)
Select-String -Path "app.log" -Pattern "timing_stt_final_to_rag" | Select-String -Pattern "tts_active_during_stt.*false"
```

### 3. STT 큐 드롭 경고 확인

```bash
# STT 입력 큐 가득 참 경고
Select-String -Path "app.log" -Pattern "stt_input_queue_full_dropping"
```

### 4. Python 스크립트로 통계 분석

```python
import json

stt_during_tts_count = 0
stt_after_tts_count = 0
queue_full_count = 0

with open("app.log", "r", encoding="utf-8") as f:
    for line in f:
        if "timing_stt_final_to_rag" in line:
            try:
                data = json.loads(line)
                if data.get("tts_active_during_stt"):
                    stt_during_tts_count += 1
                else:
                    stt_after_tts_count += 1
            except:
                pass
        elif "stt_input_queue_full_dropping" in line:
            queue_full_count += 1

print(f"TTS 송출 중 STT 인식: {stt_during_tts_count}회")
print(f"TTS 종료 후 STT 인식: {stt_after_tts_count}회")
print(f"STT 큐 드롭 경고: {queue_full_count}회")

if queue_full_count > 0:
    print("\n⚠️ STT 입력 큐가 가득 차서 패킷이 드롭되었습니다!")
    print("   → STT 처리 속도 저하 또는 TTS 송출 부하 의심")
```

---

## 🎯 문제 진단 기준

### 정상 (No Issue)

- ✅ `stt_queue_size` 평균 < 100
- ✅ `stt_input_queue_full_dropping` 경고 없음
- ✅ `tts_active_during_stt: true` 시에도 STT 인식 발생 (barge-in)
- ✅ `caller_rtp_to_stt_input` 로그가 TTS 송출 중에도 계속 기록됨

### 의심 (Potential Issue)

- ⚠️ `stt_queue_size` 가 간헐적으로 500 이상
- ⚠️ `tts_active_during_stt: true` 시 STT 인식 지연 (3초 이상)
- ⚠️ `caller_rtp_to_stt_input` 로그 간격이 불규칙 (1초 이상 gap)

### 심각 (Critical Issue)

- 🚨 `stt_input_queue_full_dropping` 경고 발생
- 🚨 `stt_queue_size` 가 900 이상
- 🚨 `tts_active_during_stt: true` 상태에서 STT 인식 없음
- 🚨 `caller_rtp_to_stt_input` 로그가 TTS 송출 중 중단됨

---

## 💡 예상되는 개선 방안

### 문제가 확인되면 적용할 수 있는 해결책:

1. **STT 입력 큐 크기 증가**:
   ```python
   # rtp_relay.py: enable_pipecat_mode()
   self._pipecat_audio_queue = asyncio.Queue(maxsize=2000)  # 1000 → 2000
   ```

2. **RTP 타이밍 우선순위 조정**:
   - 절대 시간 기반 스케줄링 이미 적용됨
   - 필요 시 `asyncio.sleep()` → `time.sleep()` + 별도 스레드 고려

3. **STT 처리 병렬화**:
   - Google STT API 호출을 별도 executor pool에서 실행
   - 현재는 메인 이벤트 루프에서 순차 처리

4. **AEC 비활성화 (테스트용)**:
   - 에코 제거 처리가 부하를 유발하는지 확인
   - `enable_pipecat_mode()`에서 `self._aec_processor = None`로 임시 비활성화

5. **TTS 청크 크기 최적화**:
   - Google TTS가 너무 큰 청크를 한 번에 생성하면 RTP 큐 적체 발생
   - TTS API 스트리밍 옵션 조정

---

## 📝 테스트 시나리오

### 1. 정상 동작 테스트

**절차**:
1. AI 통화 시작
2. AI 인사말 완료 **후** 사용자 질문 (예: "날씨 알려줘")
3. 로그 확인:
   - `timing_stt_final_to_rag` 에서 `tts_active_during_stt: false`
   - `caller_rtp_to_stt_input` 에서 `stt_queue_size` < 100

**예상 결과**: STT 정상 인식, AI 응답 생성

---

### 2. Barge-in 테스트 (TTS 중 끼어들기)

**절차**:
1. AI 통화 시작
2. AI 응답 **중간에** 사용자가 말하기 시작
3. 로그 확인:
   - `timing_stt_final_to_rag` 에서 `tts_active_during_stt: true`
   - VAD `StartInterruptionFrame` 발생 여부
   - TTS 중단 여부

**예상 결과**: VAD가 사용자 음성 감지, TTS 중단, STT 인식 성공

---

### 3. 긴 TTS 응답 중 STT 테스트

**절차**:
1. AI에게 긴 응답을 유도하는 질문 (예: "기상청 서비스를 자세히 설명해줘")
2. AI가 30초 이상 응답하는 동안 사용자가 질문
3. 로그 확인:
   - `caller_rtp_to_stt_input` 에서 `tts_sending_active: true` 상태 지속
   - `stt_queue_size` 변화 추이
   - `stt_input_queue_full_dropping` 발생 여부

**예상 결과**: 
- 정상: STT 인식 성공, barge-in
- 문제: STT 큐 드롭, 인식 실패

---

## ✅ 체크리스트

- [x] Caller RTP → STT 입력 로그 추가
- [x] TTS 상태 플래그 (`_tts_active`, `_tts_pending_pcm_bytes`) 구현
- [x] STT → RAG 로그에 TTS 상태 필드 추가
- [x] 로그 분석 가이드 작성
- [x] 문제 진단 기준 정의
- [x] 테스트 시나리오 작성
- [ ] 실제 통화 테스트 수행
- [ ] 로그 분석 결과 확인
- [ ] 문제 확인 시 개선 방안 적용

---

**작성자**: AI Assistant  
**검토자**: (사용자 검토 필요)  
**승인자**: (사용자 승인 필요)
