# 07 예약 Tool (§4.6)

`SYSTEM_OVERVIEW`용. PNG는 [README](README.md)의 `mermaid-cli` 명령으로 생성한다.

```mermaid
%% 4.6 예약 Tool + LLM 루프
flowchart TD
  A[발화: 예약/취소/조회] --> H[분류 + booking 휴리스틱 병합]
  H --> L[booking_agent: LLM + tools 루프]
  L --> S[슬롯·정책·스키마 조회]
  S --> D[(SQLite)]
  L --> TTS[확인·완료 멘트]
  L --> SM[선택: 예약 SMS 등]
```
