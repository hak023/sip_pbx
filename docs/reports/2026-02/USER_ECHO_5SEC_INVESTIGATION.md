# 사용자 음성 미러링(5초 후 에코) 현상 조사 보고서

## 현상

- 사용자 관점: 말한 뒤 **약 5초 후** 자신이 한 말이 그대로 돌아옴 (RTP로 미러링 느낌), 그 다음 **또 5초 후** LLM 답변이 옴.

## 조사 결과 요약

### 1. RTP 계층

- **파일**: `src/media/rtp_relay.py`
- AI 모드에서:
  - `caller_audio_rtp` 수신 시: `on_packet_received()`만 호출 후 **return** → relay 없음.
  - `callee_audio_rtp` 수신 시: `ai_mode` 분기에서 **return** → relay 없음.
- Symmetric RTP 리다이렉트(다른 IP가 caller 포트로 보낸 경우): callee 프로토콜로 넘긴 뒤에도 AI 모드에서 **return**만 하고 relay하지 않음.
- **결론**: 코드상 caller 음성을 다시 caller에게 보내는 RTP relay 경로는 없음.

### 2. 파이프라인 (STT → RAG → TTS)

- **RAG 프로세서**: `TranscriptionFrame` → Agent → **응답 텍스트만** `TextFrame(response)`로 push. 사용자 발화 텍스트를 그대로 TTS로 보내는 코드 없음.
- **StreamingTTSGateway**: `TextFrame`만 TTS로 전달. 사용자 발화가 TTS 입력으로 들어가는 경로 없음.
- **결론**: STT 결과(사용자 말)가 TTS로 직접 나가는 경로는 없음.

### 3. 가능한 원인: LLM 응답 첫 문장에서 질문 반복

- 통화 비서 LLM이 흔히 "○○ 말씀하셨죠, …"처럼 사용자 질문을 반복한 뒤 답변을 이어감.
- 스트리밍 TTS이므로 **첫 문장(질문 반복)이 먼저 읽혀** 사용자가 “자기 말이 돌아온다”고 느낄 수 있음.
- 시간차: VAD+STT ~1–3초 + LLM 첫 토큰 ~2–5초 → 약 5초 후 “에코” 구간, 이후 나머지 답변으로 또 5초 체감 가능.

## 적용한 수정

### 1. 응답 규칙 추가 (generate_response.py)

- **파일**: `src/ai_voicebot/langgraph/nodes/generate_response.py`
- **추가 규칙**:  
  `8. 사용자 질문을 그대로 반복하거나 인용하지 마세요. "○○ 말씀하셨죠" 같은 확인 멘트 없이 바로 답변으로 들어가세요.`
- 목적: LLM이 질문을 반복하지 않고 바로 답변으로 시작하도록 유도하여, TTS로 “에코”처럼 들리는 첫 문장을 줄임.

## 추가 권장 사항

1. **로그로 지연 구간 확인**  
   - "첫 RTP 수신 → STT 완료 → 첫 TTS 전송" 구간별 타임스탬프 로그로 5초·10초가 어디서 나오는지 확인.

2. **실제 통화 로그 확인**  
   - `llm_exchange_full` / `response_full` 로그에서 응답 **첫 문장**이 사용자 질문 인용/반복인지 확인.

3. **계속될 경우**  
   - Pipecat/Google STT 측에서 “사용자 발화 재생” 옵션 여부 확인.
   - B2BUA/SDP에서 caller 수신 포트와 실제 전송 소켓 일치 여부 재확인.

---

**작성일**: 2026-02-19  
**관련 파일**: `rtp_relay.py`, `rag_processor.py`, `generate_response_node` (generate_response.py)
