# 클라우드 STT 연동 콜 플로우 (음성 AI Agent)

본 문서는 음성 AI Agent(Cloud)와 STT/AI 서버 통합 구성 시의 평시 대화 및 폭언 감지 상황, 그리고 AI 통화비서 스팸방지 서비스에 대한 시나리오 흐름을 설명합니다.

## 1. 통화매니저 폭언 판단 Flow

### 시퀀스 다이어그램

```mermaid
sequenceDiagram
    autonumber
    
    participant U as 유저 단말
    participant PC as PC Client
    participant S as 교환기
    participant MT as 미디어 TGW
    participant CAS as 통화매니저 AS
    participant W as WTIMS
    participant CAPI as 통화매니저 API
    participant STT as STT 서버
    participant AI as AI Agent 서버

    %% 1. 평시 대화 (전사 및 UI 표시)
    rect rgb(245, 255, 250)
    Note right of U: 1. 평시 대화 및 PC Client 전사 표시
    U->>MT: 음성 발화 송신
    MT->>W: 음성 패킷 전달
    W->>STT: 음성 스트리밍 전달 (TCP 200ms)
    STT-->>STT: 음성 인식 (Speech-to-Text)
    STT->>AI: 전사 데이터(텍스트) 전달
    AI-->>AI: 텍스트 분석 (정상 대화 판단)
    AI->>CAPI: 전사 데이터 전송
    CAPI->>PC: 전사 데이터 푸시
    Note over PC: PC Client 대화 UI에<br/>전사된 발화 내용 표시
    end

    %% 2. 욕설/폭언 감지 및 흐름
    rect rgb(255, 240, 245)
    Note right of U: 2. 욕설/폭언 감지 및 자동 호 종료
    U->>MT: 음성 발화 송신 (욕설/폭언 포함)
    MT->>W: 음성 패킷 전달
    W->>STT: 음성 스트리밍 전달 (TCP 200ms)
    STT-->>STT: 음성 인식 (Speech-to-Text)
    STT->>AI: 전사 데이터(텍스트) 전달
    AI-->>AI: 전사 텍스트 기반 욕설/폭언 판단!
    AI->>CAPI: 폭언 감지 알림
    CAPI->>PC: 폭언 감지 이벤트 알림 (PC Client)
    Note over PC: PC Client 화면에<br/>폭언 감지 경고 UI 표시
    CAPI->>CAS: 폭언 시나리오 적용 요청
    CAS->>W: 폭언 안내멘트 송출 요청
    Note right of W: 안내멘트: "부적절한 내용이 감지되어 민원처리법에 따라 통화가 종료됩니다."
    W->>MT: 폭언 안내멘트 오디오 송출
    MT->>U: 폭언 안내멘트 재생
    CAS->>S: 안내멘트 송출 후 호 종료 요청
    S->>U: 호 연결 해제 (BYE)
    end
```

### 시나리오 설명

1. **평시 대화 전사 (PC Client 표시)**
   - 발화자의 음성은 WTIMS를 거쳐 클라우드의 STT 서버로 전송됩니다.
   - STT 서버는 인식된 텍스트를 AI Agent 서버로 전달합니다. 
   - AI Agent 서버는 대화를 분석하여 정상 대화로 판단하면 통화매니저 API를 통해 PC Client에 전사 데이터를 푸시합니다.
   - PC Client는 수신된 텍스트 데이터를 사용자 대화 UI에 실시간으로 표시합니다.

2. **욕설/폭언 시 호 종료 흐름**
   - 발화자의 대화 내용에 욕설 또는 폭언이 포함된 경우, STT에서 변환된 텍스트를 바탕으로 AI Agent가 이를 즉시 판단합니다.
   - AI Agent는 통화매니저 API를 통해 PC Client로 폭언 발생 알림을 전송하여 화면에 경고를 표시하도록 합니다.
   - 또한, 통화매니저 API는 통화매니저 AS에 폭언 시나리오 적용을 요청합니다.
   - 통화매니저 AS는 WTIMS에 명령을 내려 **"부적절한 내용이 감지되어 민원처리법에 따라 통화가 종료됩니다."** 라는 폭언 안내멘트를 고객 측에 송출합니다.
   - 멘트 송출 완료 후, 통화매니저 AS는 교환기를 통해 호를 강제로 종료(Disconnect) 합니다.

---

## 2. AI 통화비서 스팸방지 서비스 Flow

이 로직에서는 PC Client와 통화매니저 API가 제외되며, 기존 WTIMS 노드 대신 **AI 통화비서**가 그 역할을 수행합니다. AI 봇이 유저에게 연결하기 전에 직접 인사말을 통해 용무를 파악하고 스팸 여부를 판단합니다.

### 시퀀스 다이어그램

```mermaid
sequenceDiagram
    autonumber
    
    participant Caller as 발신 유저
    participant Callee as 착신 유저
    participant S as 교환기
    participant MT as 미디어 TGW
    participant CAS as 통화매니저 AS
    participant AIBot as AI 통화비서
    participant STT as STT 서버
    participant AI as AI Agent 서버

    %% 1. AI 봇 인사말 응대
    rect rgb(240, 248, 255)
    Note right of Caller: 1. AI 봇 인사말 응대 및 용무 확인
    AIBot->>MT: 인사말 송출 요청
    Note right of AIBot: "안녕하세요. 레스토랑 비스트로 블루밍가든입니다. 어떤 용무로 전화했는지 말씀해주세요."
    MT->>Caller: 인사말 재생
    
    Caller->>MT: 음성 발화 (용무 답변)
    Note left of Caller: "안녕하세요. 시세보다 저렴한 상가가 있어 연락드렸습니다."
    MT->>AIBot: 음성 패킷 전달
    
    AIBot->>STT: 음성 스트리밍 전달
    STT-->>STT: 음성 인식 (Speech-to-Text)
    STT->>AI: 전사 데이터 전달
    end
    
    %% 2. 스팸 판단 및 분기
    AI-->>AI: 텍스트 기반 스팸 여부 판단
    
    alt 스팸성 멘트 확인 시
        rect rgb(255, 240, 245)
        AI->>AIBot: 스팸 의심 이벤트 전달
        AIBot->>CAS: 착신연결 요청 (스팸 의심)
        CAS->>S: 착신 유저 호 연결 요청
        S->>Callee: 호 연결 (Ringing)
        CAS->>AIBot: 스팸 의심 안내멘트 송출 요청
        Note right of AIBot: 안내멘트: "스팸의심 전화입니다."
        AIBot->>MT: 안내멘트 오디오 송출
        MT->>Callee: 안내멘트 재생 (착신 유저에게)
        CAS->>S: 발신-착신 호 연결
        S->>Caller: 통화 수립
        S->>Callee: 통화 수립
        end
    else 정상 통화 (스팸 아님)
        rect rgb(245, 255, 250)
        AI->>AIBot: 일반 통화 이벤트 전달
        AIBot->>CAS: 착신연결 요청 (정상 통화)
        CAS->>S: 착신 유저 호 연결 요청
        S->>Callee: 호 연결 (Ringing)
        CAS->>S: 발신-착신 호 연결
        S->>Caller: 통화 수립
        S->>Callee: 통화 수립
        end
    end
```

### 시나리오 설명

1. **AI 봇 인사말 응대**
   - 발신 유저의 호가 인입되면 유저에게 연결하기 전 AI 통화비서가 미디어 TGW를 통해 발신 유저에게 인사말을 전송합니다. ("안녕하세요. 레스토랑 비스트로 블루밍가든입니다. 어떤 용무로 전화했는지 말씀해주세요.")
   - 발신 유저가 인사말에 응답하여 용무를 말하면("안녕하세요. 시세보다 저렴한 상가가 있어 연락드렸습니다."), 해당 음성은 미디어 TGW를 거쳐 AI 통화비서로 전달됩니다.
   - AI 통화비서는 인입되는 음성을 STT 서버에 전달하여 텍스트로 전사하고, 전사된 텍스트를 AI Agent가 넘겨받아 스팸성 내용인지 판단합니다.

2. **스팸 여부 판단 및 호 연결 (분기)**
   - **스팸성 멘트를 확인할 경우:** AI Agent는 AI 통화비서에 '스팸 의심 이벤트'를 전달합니다. AI 통화비서는 통화매니저 AS에 착신연결(스팸의심)을 알립니다. 통화매니저 AS는 교환기를 통해 착신 유저와 연결을 시도하고, AI 통화비서와 TGW를 통해 착신 유저에게 **"스팸의심 전화입니다."** 라는 안내 멘트를 우선 송출한 뒤 정상적으로 발신 유저-착신 유저 간의 호를 연결합니다.
   - **스팸 의심 멘트가 아닐 경우:** AI Agent는 AI 통화비서에 '일반 통화 이벤트'를 전달합니다. AI 통화비서는 통화매니저 AS에 착신연결(정상통화) 이벤트를 전달하며, 통화매니저 AS는 별도의 경고 멘트 송출 없이 교환기를 통해 즉시 발신 유저와 착신 유저 간의 호를 연결합니다.
