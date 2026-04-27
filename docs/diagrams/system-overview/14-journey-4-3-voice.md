```mermaid
flowchart TB
  U["고객 발화"] --> VAD["VAD·STT·턴"]
  VAD --> SB["스마트 바지인\n키워드·단어·LLM"]
  SB -->|맞장구| T1["TTS 유지"]
  SB -->|끼어들기| T2["TTS 중단\n새 질문 처리"]
  T1 --> U
  T2 --> U
```
