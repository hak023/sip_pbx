# AI 인사말(TTS) RTP 전송 이슈 조치

## 증상

- AI 응대 시나리오에서 **TTS 음성이 발신자에게 거의 전달되지 않음** (RTP가 거의 전송되지 않음).

## 원인 (app.log 타임라인 기준)

1. **TTS가 200 OK 직후 시작됨**  
   - No-answer 타임아웃 → 200 OK 전송 → 곧바로 Legacy AI 인사말(2-Phase Greeting) 시작.  
   - 인사말 TTS가 **ACK 수신 전** 약 10초간 재생됨.

2. **발신자 측 미디어 경로**  
   - 대부분의 SIP 단말은 **ACK를 보낸 뒤**에야 RTP 수신을 시작함.  
   - 따라서 ACK 이전에 보낸 TTS RTP는 수신·재생되지 않을 수 있음.

3. **ACK 직후 Barge-in**  
   - ACK 수신 시점(`call_established`) 직후(수 ms 이내) **Barge-in 감지**로 TTS가 중단됨.  
   - 그 결과, 미디어 경로가 열린 뒤에는 거의 TTS가 재생되지 않음.

정리하면, **인사말이 “ACK 이전”에 재생되고, “ACK 이후”에는 곧바로 Barge-in으로 끊겨서** RTP로 전달되는 TTS가 거의 없었음.

## 조치 내용

- **인사말(TTS)을 ACK 수신(call_established) 이후에만 시작**하도록 변경함.

### 1. CallManager (`src/sip_core/call_manager.py`)

- `_call_established_events: Dict[str, asyncio.Event]` 추가.  
- `handle_no_answer_timeout()`에서 AI 활성화 시:
  - `asyncio.Event()` 생성 후 `_call_established_events[call_id]`에 보관.
  - `ai_orchestrator.set_call_established_event(call_id, event)` 호출.
- `notify_call_established(call_id)` 추가:
  - ACK 수신 시 sip_endpoint에서 호출.
  - 해당 `call_id`의 이벤트를 `set()` 하고 딕셔너리에서 제거.

### 2. AIOrchestrator (`src/ai_voicebot/orchestrator/ai_orchestrator.py`)

- `set_call_established_event(call_id, event)` 추가.
- `handle_call()` 내부에서 **`play_greeting()` 호출 전**에:
  - `_call_established_event`가 설정되어 있으면  
    `await asyncio.wait_for(self._call_established_event.wait(), timeout=15.0)` 로 **최대 15초 대기**.
  - 이벤트가 set되면(ACK 수신) 곧바로 인사말 재생으로 진행.

### 3. SIPEndpoint (`src/sip_core/sip_endpoint.py`)

- ACK 처리 시, AI 모드에서 `call_established` 로그를 남긴 직후  
  `self.call_manager.notify_call_established(call_id)` 호출 추가.

## 적용 후 기대 동작

- 200 OK 전송 → 발신자가 ACK 전송 → **그 시점에** 인사말 TTS 시작.  
- 발신자 단말이 이미 RTP 수신을 시작한 이후이므로, TTS RTP가 정상적으로 전달·재생될 가능성이 높음.

## 참고

- **Pipecat** 경로는 이번 변경 대상이 아님. Legacy 오케스트레이터 경로만 수정됨.
- Barge-in이 ACK 직후 잘못 감지되는 경우는 별도 조정(예: 수립 직후 1~2초 무시)이 필요할 수 있음.
