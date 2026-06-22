# 방안 2. 지능망 내 STT 구성 및 Cloud AI 서버 연동
지능망 내에 STT 서버를 두고 음성 AI Agent(Cloud)에는 AI 서버만 위치시키는 구조입니다.

```mermaid
graph TD
    %% 스타일 정의 (블루 & 화이트 컨설팅 펌 테마)
    classDef default fill:#ffffff,stroke:#cbd5e1,stroke-width:1px,color:#334155,font-family:sans-serif;
    classDef layerBox fill:#f8fafc,stroke:#94a3b8,stroke-width:2px,stroke-dasharray: 4 4,color:#0f172a,font-weight:bold;
    classDef cloudBox fill:#eff6ff,stroke:#60a5fa,stroke-width:2px,stroke-dasharray: 4 4,color:#1d4ed8,font-weight:bold;
    classDef userLayer fill:#f1f5f9,stroke:#94a3b8,stroke-width:2px,stroke-dasharray: 4 4,color:#0f172a,font-weight:bold;
    classDef coreLayer fill:#e2e8f0,stroke:#64748b,stroke-width:2px,stroke-dasharray: 4 4,color:#0f172a,font-weight:bold;
    classDef intellLayer fill:#e0f2fe,stroke:#38bdf8,stroke-width:2px,stroke-dasharray: 4 4,color:#0f172a,font-weight:bold;
    classDef cloudLayer fill:#ede9fe,stroke:#8b5cf6,stroke-width:2px,stroke-dasharray: 4 4,color:#1d4ed8,font-weight:bold;
    classDef nodeBox fill:#ffffff,stroke:#2563eb,stroke-width:2px,color:#1e3a8a,font-weight:bold,rx:4px,ry:4px;
    classDef dashedNodeBox fill:#ffffff,stroke:#2563eb,stroke-width:2px,stroke-dasharray: 5 5,color:#1e3a8a,font-weight:bold,rx:4px,ry:4px;
    classDef clientBox fill:#ffffff,stroke:#475569,stroke-width:2px,color:#334155,font-weight:bold,rx:4px,ry:4px;

    %% 계층별 Subgraph
    subgraph User_Area ["유저 영역 (User Area)"]
        direction LR
        UserTerminal["📱 유저 단말"]:::nodeBox
        PCClient["💻 PC Client"]:::clientBox
    end

    subgraph Core_Network ["코어망 (Core Network)"]
        direction LR
        Switch["🔀 교환기"]:::nodeBox
        MediaTGW["📡 미디어 TGW"]:::nodeBox
    end

    subgraph Intelligent_Network ["지능망 (Intelligent Network)"]
        direction LR
        CallManagerAS["📞 통화매니저 AS"]:::nodeBox
        WTIMS["🎛️ WTIMS"]:::nodeBox
        CallManagerAPI["⚙️ 통화매니저 API"]:::nodeBox
        STTServer["🎙️ STT 서버"]:::dashedNodeBox
    end

    subgraph Cloud_Agent ["음성 AI Agent (Cloud)"]
        direction LR
        AIAgent["🧠 AI Agent 서버"]:::nodeBox
    end

    %% 연결선 및 프로토콜 흐름 (위에서 아래로: Cloud -> Intelligent -> Core -> User)
    
    %% Cloud <-> Intelligent
    AIAgent ==>|"<mark>전사 데이터</mark> / <mark>폭언 감지</mark>"| CallManagerAPI
    AIAgent -.- CallManagerAS
    AIAgent <==>|"<mark>전사 데이터</mark>"| STTServer
    
    %% Intelligent 내부
    STTServer <==>|"<mark>미디어 (TCP 200ms)</mark>"| WTIMS
    CallManagerAPI -.- CallManagerAS
    CallManagerAS -.- WTIMS
    
    %% Intelligent <-> Core
    CallManagerAS -.- Switch
    WTIMS <==> MediaTGW
    
    %% Core <-> User
    Switch -.- UserTerminal
    MediaTGW <==> UserTerminal
    
    %% Intelligent <-> User
    CallManagerAPI ==>|"<mark>전사 데이터</mark> / <mark>폭언 감지</mark>"| PCClient

    %% 서브그래프 스타일 적용
    class User_Area userLayer;
    class Core_Network coreLayer;
    class Intelligent_Network intellLayer;
    class Cloud_Agent cloudLayer;
```
