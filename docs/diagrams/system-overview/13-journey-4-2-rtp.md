```mermaid
flowchart TB
  M["통화 구간의\n미디어 모드"] --> B["Bypass\n인간-인간·초저지연"]
  M --> A["AI\nSTT·LLM·TTS\n20ms RTP"]
  M --> R["Bridge\n전환 후 새 레그"]
```
