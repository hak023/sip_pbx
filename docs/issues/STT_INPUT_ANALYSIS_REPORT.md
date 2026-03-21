# STT 입력 흐름 점검 보고서

**작성일**: 2026-03-09  
**로그 기준**: `sip-pbx/logs/app.log` (13:51~13:52 구간)

---

## 1. 요약

| 항목 | 상태 | 비고 |
|------|------|------|
| `rag_llm_user_input` 로그 | ✅ 존재 | STT 결과가 RAG에 도달함 |
| `timing_stt_final_to_rag` 로그 | ✅ 존재 | 타이밍 로그 정상 |
| Input Transport | ✅ 정상 | 오디오 수신·전달 확인 |
| Google STT 스트림 | ✅ 동작 | 최종 결과 반환됨 |
| VAD | ⚠️ 민감 | mode=3, TTS 에코도 음성으로 감지 |
| **에코** | ❌ **문제** | **음향 에코(Acoustic Echo)** 발생 |

---

## 2. STT 입력 흐름 분석

### 2.1 전체 파이프라인

```
Caller RTP (PCMU) 
  → rtp_relay.on_packet_received(caller_audio_rtp)
  → rtp_to_pcm16k() → _pipecat_audio_queue.put_nowait()
  → SIPPBXInputTransport._read_audio_loop()
  → get_caller_audio_stream() yield
  → InputAudioRawFrame 생성
  → rec_input → VAD → STT → RAGLLMProcessor
  → rag_llm_user_input 로그
```

### 2.2 로그에서 확인된 STT 결과

| 시각 | STT 결과 | TTS 재생 상태 | 의도 |
|------|----------|---------------|------|
| 13:51:31.206 | `"oh,"` | Phase2 TTS 재생 중 | chitchat |
| 13:51:53.756 | `"You."` | "네, 편하게 말씀해주세요" 직후 | help |
| 13:52:30.714 | `"here, you"` | "무엇이 궁금하신가요?" 직후 | help |

**특징**:
- STT 언어 설정: `ko-KR`
- 실제 STT 결과: **영어** 단어/구 ("oh", "You", "here, you")
- TTS 재생 직후 또는 재생 중에 STT 결과 발생

---

## 3. 문제 원인: 음향 에코 (Acoustic Echo)

### 3.1 RTP 루프백 에코 (이미 수정됨)

`OUTPUT_TRANSPORT_ECHO_FIX.md`에 따라:
- Output Transport는 **TTSAudioRawFrame만** RTP로 전송
- InputAudioRawFrame은 전송하지 않음
- **RTP 레벨 에코 루프는 차단된 상태**

### 3.2 음향 에코 (현재 문제)

```
[전화기 스피커] TTS 재생 ("어떤 것이 궁금하신가요?")
        ↓
[전화기 마이크] 스피커 소리 수음 (스피커폰 사용 시)
        ↓
[RTP] Caller → 서버로 전송
        ↓
[STT] 왜곡된 TTS 오디오 → "oh", "You", "here, you" 등으로 오인
        ↓
[LLM] help/chitchat → "저는 날씨 예보 조회... 무엇이 궁금하신가요?"
        ↓
반복
```

- STT 설정은 `ko-KR`이지만, 왜곡·에코된 오디오 때문에 영어로 인식
- "요", "어" 등 한글 음소가 "You", "oh"로 인식될 수 있음

### 3.3 VAD 영향

- VAD mode=3 (가장 민감)
- TTS 에코도 음성으로 판단 → STT로 전달
- TTS 재생 중에도 STT 입력이 계속 들어감

---

## 4. Input Transport / 오디오 수신 상태

### 4.1 RTP → 파이프라인

- `rtp_relay.py` 422~431: `caller_audio_rtp` 수신 시 `_pipecat_audio_queue`에 PCM 적재
- `timing_caller_rtp_first_to_pipeline` 로그로 첫 패킷 투입 시점 확인 가능

### 4.2 Input Transport

- `SIPPBXInputTransport._read_audio_loop()`: `get_caller_audio_stream()`에서 PCM 수신
- `InputAudioRawFrame` 생성 후 파이프라인에 push
- `pipecat_input_transport_started`, `pipecat_audio_stream_first_packet` 로그로 동작 확인

### 4.3 Google STT 스트림

- `rag_llm_user_input`, `timing_stt_final_to_rag` 로그 존재 → STT 최종 결과가 RAG까지 전달됨
- 스트림 타임아웃: `get_caller_audio_stream()` 5초 대기로 keep-alive 유지

---

## 5. 수정 방안

### 5.1 단기 (설정/필터)

1. **STT 후처리 필터 강화** (`stt_post_filter.py`)
   - `min_length`: 3~4 이상으로 설정해 "oh", "You" 같은 짧은 결과 차단
   - `drop_only_reactions`: True로 설정
   - `blocklist`: `["oh", "you", "here you", "here, you"]` 등 에코 패턴 추가

2. **VAD 민감도 조정**
   - `aggressiveness`: 3 → 2 또는 1로 낮춰 TTS 에코를 음성으로 덜 인식

3. **설정 예시** (config 또는 call_manager):

```yaml
stt_post_filter:
  min_length: 3
  drop_only_reactions: true
  blocklist: ["oh", "oh,", "you", "you.", "here, you", "here you"]

vad:
  aggressiveness: 2  # 3 → 2
```

### 5.2 중기 (TTS 재생 중 STT 억제)

- TTS 재생 구간에는 STT 입력을 무시하거나 지연
- Barge-in은 별도 경로로 처리 (VAD + StartInterruptionFrame)
- `tts_sync_context` 또는 TTSCompleteNotifier와 연동해 "TTS 재생 중" 플래그 관리

### 5.3 장기 (음향 에코 제거)

- **AEC (Acoustic Echo Cancellation)**: TTS 참조 신호를 이용해 입력에서 제거
- WebRTC AEC, SpeexDSP, RNNoise 등 활용 검토
- SIP/VoIP 환경에서는 구현 난이도가 높을 수 있음

### 5.4 사용자 측 권장

- 스피커폰 대신 **이어폰/헤드셋** 사용
- 통화 시 스피커 볼륨 낮추기

---

## 6. "Welcome.", "To."에 대한 확인

요청하신 Line 318, 331의 "Welcome.", "To."는 현재 로그에서는 **"oh,"**, **"You."**로 확인됨.

- Line 318: `rag_llm_user_input` text=`"oh,"`
- Line 331: `timing_stt_final_to_rag` text_preview=`"oh,"`
- Line 364: `rag_llm_user_input` text=`"You."`

이들은 **실제 사용자 발화가 아니라 TTS 에코**로 추정됩니다.

---

## 7. 결론

| 구분 | 내용 |
|------|------|
| **STT 입력** | Input Transport → STT → RAG 흐름은 정상 동작 |
| **로그** | `rag_llm_user_input`, `timing_stt_final_to_rag` 정상 기록 |
| **주요 원인** | 음향 에코로 인한 TTS 재인식 → 잘못된 STT 결과 |
| **권장 조치** | STT 후처리 필터 강화, VAD 민감도 조정, (선택) TTS 재생 중 STT 억제 |
