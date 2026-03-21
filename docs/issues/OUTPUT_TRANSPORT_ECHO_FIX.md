# Output Transport 에코 문제 해결

## 문제 설명

AI 응대 중 **사용자가 아무 말도 안했는데 STT 결과가 나오고 AI가 응답**하는 문제.

## 발생 증상

1. **사용자 무언**
   - 사용자가 전화받고 아무 말도 안함
   - 단말은 정상 동작 중

2. **자동 STT 결과**
   ```
   {"text": "Know.", "is_final": true}
   ```

3. **자동 AI 응답**
   ```
   LLM: "좋습니다. 다른 궁금한 점 있으시면 말씀해 주세요."
   ```

4. **프레임 타입이 InputAudioRawFrame**
   ```json
   {
     "event": "tts_first_audio_sent_to_rtp",
     "frame_type": "InputAudioRawFrame",  // TTS가 아니라 INPUT!
     "audio_len": 638
   }
   ```

## 근본 원인 분석

### Output Transport의 잘못된 프레임 판별

**`sip-pbx/src/ai_voicebot/pipecat/rtp_transport.py:196-201`**
```python
# Before (문제 코드)
is_audio_frame = (
    (TTSAudioRawFrame is not type(None) and isinstance(frame, TTSAudioRawFrame))
    or (isinstance(audio_data, bytes) and len(audio_data) > 0)  # 문제!
)
```

**문제점:**
- `or isinstance(audio_data, bytes)` 조건 때문에
- **모든 오디오 프레임**(InputAudioRawFrame 포함)을 TTS로 인식
- InputAudioRawFrame은 **caller의 음성**인데 다시 caller에게 전송
- **에코/루프백** 발생

### 에코 루프의 흐름

```
1. Caller RTP 패킷 수신
   ↓
2. RTP Worker → PCM 변환 → _pipecat_audio_queue
   ↓
3. Input Transport → InputAudioRawFrame 생성
   ↓
4. STT 처리
   ↓
5. 파이프라인 통과 → Output Transport 도달
   ↓
6. Output Transport가 InputAudioRawFrame을 TTS로 오인!
   ↓
7. send_audio_to_caller() 호출 → RTP로 다시 Caller에게 전송
   ↓
8. Caller가 자기 목소리 에코를 받음
   ↓
9. 에코가 다시 Input으로 돌아와 STT로 인식 ("Know.")
```

### 왜 "Know."가 나왔나?

- 에코된 오디오가 Google STT로 전달됨
- Google STT가 노이즈/에코를 "Know."로 인식
- 실제로는 사용자가 말하지 않았음

## 해결 방법

### Output Transport 프레임 판별 수정

**변경:**
```python
# After (수정)
is_tts_audio = (
    TTSAudioRawFrame is not type(None) and isinstance(frame, TTSAudioRawFrame)
)
# InputAudioRawFrame은 명시적으로 제외
```

**효과:**
- TTSAudioRawFrame만 RTP로 전송
- InputAudioRawFrame은 Output Transport를 통과만 하고 전송 안함
- 에코 루프 차단

### 추가 개선 사항

**로그 개선:**
```python
# InputAudioRawFrame이 Output Transport를 통과하면 경고
if isinstance(frame, InputAudioRawFrame):
    logger.warning("input_audio_in_output_transport",
                   call_id=self._rtp_worker.media_session.call_id,
                   note="InputAudioRawFrame이 Output Transport를 통과함 - 파이프라인 구조 점검 필요")
```

## 수정 파일

- `sip-pbx/src/ai_voicebot/pipecat/rtp_transport.py`
  - `SIPPBXOutputTransport.process_frame()`: 프레임 타입 판별 로직 수정

## 테스트 방법

1. **서버 재시작**
   ```powershell
   cd sip-pbx
   ./start-all.ps1
   ```

2. **AI 통화 시작 후 침묵**
   - 1003에서 1004로 전화
   - 10초 대기 (AI 응대 시작)
   - **아무 말도 하지 않고 대기**

3. **확인 사항**
   ```bash
   # 로그 확인
   tail -f logs/app.log | grep -E "tts_first_audio|frame_type|rag_llm_user_input"
   ```

4. **성공 지표**
   - `frame_type` 로그에 **TTSAudioRawFrame만 표시**
   - InputAudioRawFrame 없음
   - 사용자 침묵 시 STT 결과 없음
   - AI가 자동으로 응답하지 않음

## 예상 효과

1. **에코 제거**
   - Caller 음성이 에코되지 않음
   - 정상적인 단방향 오디오

2. **STT 정확도**
   - 에코로 인한 잘못된 STT 없음
   - 실제 사용자 발화만 인식

3. **AI 응답 정확성**
   - 허구의 STT에 응답하지 않음
   - 실제 사용자 질문에만 응답

## 관련 이슈

- Google STT 409 Timeout: [GOOGLE_STT_TIMEOUT_FIX.md](./GOOGLE_STT_TIMEOUT_FIX.md)
- 근본 원인이 다름 (타임아웃 vs 에코)
- 하지만 에코로 인해 STT가 계속 동작해서 타임아웃이 지연되었을 가능성

## 참고

### Pipecat Frame 타입

- `InputAudioRawFrame`: Input Transport에서 생성, caller 음성
- `TTSAudioRawFrame`: TTS Service에서 생성, AI 응답 음성
- `OutputAudioRawFrame`: (사용 안함)

### Pipeline 구조

```
Input Transport → InputAudioRawFrame
    ↓
VAD → (barge-in 감지)
    ↓
STT → TranscriptionFrame
    ↓
RAG/LLM → TextFrame
    ↓
TTS → TTSAudioRawFrame
    ↓
Output Transport → RTP 전송
```

**Input과 Output은 완전히 분리**되어야 하며, InputAudioRawFrame이 Output Transport에 도달해서는 안됩니다.
