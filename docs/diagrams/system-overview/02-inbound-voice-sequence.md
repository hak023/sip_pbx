# 02 복잡 음성 루프: 무응답·AI·HITL (§3.3)

인입 통화에서 **착신 사람이 응답하지 않은 뒤 AI가 먼저 응대**하고, **답이 어려울 때 HITL**로 **운영자가 대시보드에 채팅으로 답한 내용**을 **AI가 가공해 TTS**로 전달하는 흐름(발표·온보딩용). PNG는 [README](README.md)의 `mermaid-cli` 명령으로 생성한다.

```mermaid
sequenceDiagram
  autonumber
  participant A as 발신자
  participant PBX as B2BUA / RTP
  participant C as 착신(사람)
  participant AI as AI 음성 파이프라인
  participant G as LangGraph
  participant WS as Socket.IO(대시보드)
  participant OP as 운영자(채팅 입력)

  A->>PBX: INVITE
  PBX->>C: 2nd INVITE(링)
  Note over C: 착신 무응답(타임아웃·정책)
  Note over PBX,AI: RTP·세션 → AI 음성 모드
  PBX->>AI: Pipecat / 음성 에이전트 기동
  loop 발신자↔AI 음성
    A->>AI: STT(발화)
    AI->>G: 의도·RAG·응답 생성
    G-->>A: TTS
  end
  G->>G: 신뢰도 부족·nlu_fallback 등
  G->>WS: HITL 요청(질문·call_id)
  OP->>WS: 상담원 답변(채팅·텍스트)
  WS->>G: HITL 응답 전달(큐)
  G->>G: 운영자 문구 LLM 정제(고객용 멘트)
  G-->>A: TTS(운영자 지식·톤 반영)
```
