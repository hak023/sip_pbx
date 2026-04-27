# 09 통화 연결음 (§4.9)

`SYSTEM_OVERVIEW`용. PNG는 [README](README.md)의 `mermaid-cli` 명령으로 생성한다.

```mermaid
%% 4.9 통화 연결음 — LLM + Suno + early RTP
flowchart LR
  SET[settings / persona] --> LLM[LLM: lyrics + style]
  LLM --> SUNO[Suno generate]
  SUNO -->|callback| API[POST /api/ringback/...]
  API --> MP3[cache MP3]
  MP3 --> PL[RingbackPlayer]
  PL --> RTP[early RTP]
```
