# HITL(Human-in-the-Loop) 구현 현황 점검 및 외부 리서치

## 1. 목표 HITL 흐름 (요구사항)

1. **프론트엔드**: 사용자가 AI가 응대 중인 **실시간 통화 화면**을 확인한다.
2. **채팅 개입**: 발신자와 AI 대화를 보다가 **채팅으로 AI에게 정보를 알려준다.**  
   (예: "토요일 영업시간은 오전 10시부터 오후 14시까지입니다.")
3. **발신자 전달**: **LLM/파이프라인이 사용자가 전달한 정보를 받아**, 통화 기록을 참고하여 **STT/TTS로 발신자에게 알려준다.**
4. **지식 저장**: 사용자가 알려준 정보는 **ChromaDB(지식 베이스)에 저장**한다.

---

## 2. 현재 구현 상태 (단계별)

| 단계 | 요청 동작 | 구현 상태 | 비고 |
|------|-----------|-----------|------|
| **1** | 프론트에서 AI 응대 중 실시간 통화 화면 확인 | ✅ 구현됨 | 대시보드 활성 통화 목록 + `LiveCallMonitor`로 실시간 STT/TTS 표시. HITL 요청 시 `HITLDialog`로 질문·컨텍스트 표시. |
| **2** | 채팅으로 AI에게 알려줌 | ✅ 구현됨 | `HITLDialog`에서 운영자 텍스트 입력 후 전송 → WebSocket `submit_hitl_response`로 백엔드 전달. |
| **3** | LLM이 정보를 받아 통화 기록 참고 후 STT/TTS로 발신자에게 전달 | ✅ 구현됨 | `submit_response()`에서 `push_operator_response(call_id, response_text)` 호출 → 해당 통화의 `hitl_response_queue`에 적재 → `RAGLLMProcessor` 백그라운드 소비 → `TextFrame` → TTS 재생. |
| **4** | 사용자가 알려준 정보 ChromaDB 저장 | ✅ 구현됨 | `knowledge_service.add_from_hitl(...)` 호출로 저장. (`KnowledgeService.add_from_hitl` 메서드 추가 완료.) |

### 2.1 파이프라인별 HITL 연동

- **Legacy AI Orchestrator**  
  - `request_human_help()` 구현됨 → `HITLService.request_human_help()` 호출 → `emit_hitl_requested`로 프론트에 HITL 요청 전달.  
  - 운영자 응답을 해당 통화 TTS로 넣는 경로는 Pipecat과 동일한 큐 메커니즘을 쓰지 않으면 미연동일 수 있음 (Pipecat 사용 시에는 동일 큐 사용).
- **Pipecat 파이프라인**  
  - 파이프라인 빌더에서 `HITLManager(on_alert=_on_hitl_alert)` 연결 → `needs_human` 시 `request_human_help()` 호출 → **`hitl_requested`가 프론트로 전달**됨.  
  - 운영자 응답은 `push_operator_response` → 통화별 큐 → `RAGLLMProcessor`가 `TextFrame`으로 TTS 전달.

### 2.2 요약

- **1, 2, 4**는 구현되어 있음.  
- **3번(운영자 답변 → 해당 통화 파이프라인 → TTS로 발신자에게 전달)** 이 빠져 있음.  
- Pipecat 사용 시, HITL **요청**이 프론트까지 가려면 `HITLManager`에 `on_alert` 콜백을 연결해 `HITLService.request_human_help()`를 호출하도록 해야 함.

---

## 3. 보완 사항 (구현 완료)

1. **운영자 답변 → TTS 전달** ✅  
   - `HITLService`: `register_hitl_response_queue(call_id, queue)`, `unregister_hitl_response_queue(call_id)`, `push_operator_response(call_id, text)` 추가.  
   - `submit_response()` 내에서 `push_operator_response(call_id, response_text)` 호출로 해당 통화 큐에 텍스트 적재.  
   - `RAGLLMProcessor`: `hitl_response_queue` 수신 시 백그라운드 태스크로 큐 소비 → `TextFrame(text)`로 하류 전달 → TTS 재생.  
   - 파이프라인 빌더에서 통화별 큐 생성·등록, 종료 시 해제.

2. **Pipecat에서 HITL 요청 발송** ✅  
   - 파이프라인 빌더에서 `HITLManager(on_alert=_on_hitl_alert)`에 콜백 연결.  
   - `_on_hitl_alert`에서 `HITLService.request_human_help(call_id, question, context, urgency)` 호출 → `emit_hitl_requested`로 프론트에 HITL 요청 표시.  
   - `handle_hitl_result`에 `user_text` 인자 추가 후 `alert_data["question"]`으로 전달.

---

## 4. 외부 HITL/핸드오프 리서치 요약

### 4.1 공통 아키텍처 (Voice AI + HITL)

- **실시간 STT**: 지연 300ms 이하 스트리밍 인식.  
- **핸드오프 결정**:  
  - 긴급도, 명시적 요청("사람이랑 통화하고 싶어요"), **신뢰도 임계값**(보통 60–70%, 최소 40%), 부정 감정, 대화 루프 감지, 규제·보안(금융 분쟁 등).  
- **컨텍스트 이전**: 대화 기록·수집 데이터·제안 응답을 운영자에게 그대로 전달해 고객이 반복 설명하지 않도록 함.  
- **Co-pilot 모드**: 운영자에게 AI 제안 응답·지식 검색·다음 액션 추천 제공.

참고: Petronella Tech, Smith.ai, Voiceflow 등 블로그/가이드.

### 4.2 Flametree – Operator Handover

- **발생 조건**: 에스컬레이션 기준 도달, 사용자 요청, 자동(설정 조건), 수동(운영자 클릭).  
- **핸드오프 절차**:  
  - AI 일시정지 → 운영자에게 알림 → **전체 대화 기록 전달** → 운영자 제어로 전환, 필요 시 다시 AI로 복귀.  
- **메시지 로깅**: 운영자가 보낸 메시지·핸드오프 시점 기록.  
- **UI**: 빠른 액션, 제안 응답, 세션 결과·전체 히스토리, **AI/운영자 구분 아이콘**.

출처: [Flametree – Operator Handover](https://docs.flametree.ai/monitoring/monitoring/operator-handover)

### 4.3 Twilio – 실시간 전사 및 운영자 지원

- **실시간 전사**: 발화 단위로 웹훅 콜백 전송 → 운영자가 통화 내용을 실시간 확인.  
- **발신자에게 메시지 전달**: **ConversationRelay**로  
  - STT(발신자 음성 → 텍스트), TTS(운영자/시스템 응답 → 발신자 음성),  
  - WebSocket 기반 실시간 양방향 통신.  
- TTS 음성·언어·프로바이더(Google, Amazon, ElevenLabs 등) 설정 가능.  
- 운영자는 전사 스트림을 보면서 응답 텍스트를 입력하면, 해당 텍스트가 TTS로 발신자에게 재생되는 구조.

출처: [Twilio ConversationRelay](https://www.twilio.com/docs/voice/conversationrelay), [Real-Time Transcripts](https://www.twilio.com/en-us/changelog/send-real-time-transcripts-to-voice-intelligence)

### 4.4 Microsoft Copilot Studio – Generic Handoff

- **제네릭 핸드오프**: 봇이 “사람에게 넘기기” 시, 지정된 engagement hub(콜센터 등)로 **컨텍스트와 함께** 전달.  
- 세션/대화 상태 유지로 이어지는 상담 지원.

출처: [Configure handoff to any generic engagement hub](https://learn.microsoft.com/en-us/microsoft-copilot-studio/configure-generic-handoff)

### 4.5 시사점 (본 프로젝트에 적용 시)

- **운영자 입력 → 발신자 TTS**는 Twilio ConversationRelay처럼 “운영자 텍스트 → TTS 스트림” 경로가 필수.  
  → 현재 갭인 **3번(운영자 답변을 해당 통화 파이프라인의 TTS로 주입)** 구현이 필요.  
- **HITL 요청 시** Flametree처럼 **전체 대화 맥락 + 질문**을 운영자에게 전달하는 것은 이미 `hitl_requested`의 `context` 등으로 부분 구현 가능.  
- **Co-pilot**: 운영자에게 제안 응답을 보여주는 것은 추후 확장으로 두고, 우선은 “운영자 자유 텍스트 → TTS”만 연결해도 목표 흐름 1~4에 가까워짐.

---

## 5. 관련 코드 위치 (참고)

| 역할 | 파일/위치 |
|------|-----------|
| HITL 다이얼로그(프론트) | `frontend/components/HITLDialog.tsx` |
| 실시간 통화 모니터 | `frontend/components/LiveCallMonitor.tsx` |
| HITL 응답 전송(WS) | `submit_hitl_response` → `src/websocket/server.py` `on_submit_hitl_response` |
| HITL 비즈니스 로직 | `src/services/hitl.py` (`submit_response`, `request_human_help`) |
| HITL KB 저장 | `src/services/knowledge_service.py` (`add_from_hitl`) |
| 파이프라인 HITL 처리 | `src/ai_voicebot/pipecat/processors/hitl_processor.py` (`HITLManager`), `rag_processor.py` |
| 오케스트레이터 HITL | `src/ai_voicebot/orchestrator/ai_orchestrator.py` (`request_human_help`) |
| WS 브로드캐스트 | `src/websocket/server.py` (`emit_hitl_requested`) |

---

## 6. 동작 점검 체크리스트

구현 후 아래 순서로 동작 여부를 확인할 수 있다.

1. **서버 기동**  
   - `python -m src.main` 또는 `start_all`로 SIP + WebSocket + 프론트 기동.

2. **실시간 통화 화면**  
   - 대시보드에서 AI 응대 중인 통화 선택 → `LiveCallMonitor`에 STT/TTS 실시간 표시되는지 확인.

3. **HITL 요청 노출 (Pipecat)**  
   - 발신자가 LangGraph Agent가 `needs_human=True`로 판단하는 질문을 하면, 운영자 대시에 HITL 요청(`hitl_requested`)이 뜨는지 확인.  
   - (Agent 설정에 따라 낮은 신뢰도/전환 의도 등에서 트리거.)

4. **채팅으로 응답 제출**  
   - HITLDialog에서 응답 텍스트 입력 후 전송 → `submit_hitl_response` 호출되는지, `hitl_resolved` 수신되는지 확인.

5. **발신자에게 TTS 전달**  
   - 같은 통화가 유지된 상태에서 위 4번으로 응답 제출 후, **발신자 측에서 해당 문장이 TTS로 재생**되는지 확인.

6. **ChromaDB 저장**  
   - HITL 응답 시 "지식 베이스에 저장" 체크 후 제출 → `KnowledgeService.add_from_hitl` 호출로 ChromaDB에 저장되는지 확인.

*문서 작성일: 2025-02-19. 구현 상태는 해당 시점 코드 기준.*
