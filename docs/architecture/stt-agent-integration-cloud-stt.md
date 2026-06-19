# 방안 1. 음성 AI Agent(Cloud)에 STT/AI 서버 통합 구성
지능망 내 STT를 제거하고 음성 AI Agent(Cloud) 내에 STT 서버와 AI 서버를 모두 위치시키는 구조입니다.

```mermaid
flowchart TB
    subgraph USER_AREA["유저 영역"]
        USER_DEVICE[유저 단말]
        PC_CLIENT[PC Client]
    end

    subgraph CORE_NETWORK["코어망"]
        EXCHANGE_SERVER[교환기]
        MEDIA_TGW[미디어 TGW]
    end

    subgraph INTELLIGENT_NETWORK["지능망"]
        CALL_MANAGER_AS[통화매니저 AS]
        WTIMS_SERVER[WTIMS]
        CALL_MANAGER_API[통화매니저 API]
    end

    subgraph VOICE_AI_AGENT_CLOUD["음성 AI Agent(Cloud)"]
        style VOICE_AI_AGENT_CLOUD fill:#f8faff,stroke:#0066cc,stroke-width:2px,stroke-dasharray: 5 5
        
        CLOUD_STT_SERVER[STT 서버]
        AI_SERVER[AI 서버]
    end

    EXCHANGE_SERVER <-->|SIP 연동| CALL_MANAGER_AS
    CALL_MANAGER_AS --> WTIMS_SERVER
    USER_DEVICE <-->|SIP 연동| EXCHANGE_SERVER
    USER_DEVICE <-->|RTP 연동| MEDIA_TGW
    MEDIA_TGW <-->|RTP 연동| WTIMS_SERVER

    %% 연동 구간
    CALL_MANAGER_AS -->|호 세션| AI_SERVER
    AI_SERVER -->|호 세션| CLOUD_STT_SERVER
    WTIMS_SERVER -->|"미디어(TCP 200ms)"| CLOUD_STT_SERVER
    CLOUD_STT_SERVER -->|전사| AI_SERVER

    %% AI Agent 연동
    AI_SERVER <-->|폭언·자막·TIP| CALL_MANAGER_API
    CALL_MANAGER_API -->|호 제어| CALL_MANAGER_AS
    CALL_MANAGER_API -->|자막·폭언알림| PC_CLIENT
```
