# 클라우드 STT 연동 콜 플로우 (음성 AI Agent)

본 문서는 음성 AI Agent(Cloud)와 STT/AI 서버 통합 구성 시의 호 수립, 평시 대화 및 폭언 감지 상황에 대한 시나리오 흐름을 설명합니다.

## 시퀀스 다이어그램

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

    %% 1. 호 수립 (Establish)
    rect rgb(240, 248, 255)
    Note right of U: 1. 호 수립 (Establish)
    U->>S: 발신/수신 호 연결 요청
    S->>CAS: 호 처리 및 제어 요청
    CAS-->>S: 라우팅 및 호 제어 응답
    S->>MT: 미디어 연결 요청
    MT<-->>U: RTP 미디어 스트림 수립
    CAS->>W: 미디어 포크(Forking) 요청
    W<-->>STT: TCP 200ms 미디어 스트리밍 채널 수립 (STT 전송용)
    end

    %% 2. 평시 대화 (전사 및 UI 표시)
    rect rgb(245, 255, 250)
    Note right of U: 2. 평시 대화 및 PC Client 전사 표시
    U->>MT: 음성 발화 송신
    MT->>W: 음성 패킷 전달
    W->>STT: 음성 스트리밍 전달 (TCP 200ms)
    STT-->>STT: 음성 인식 (Speech-to-Text)
    STT->>AI: 전사 데이터(텍스트) 전달
    AI-->>AI: 텍스트 분석 (정상 대화 판단)
    STT->>CAPI: 전사 데이터 전송
    CAPI->>PC: 전사 데이터 푸시
    Note over PC: PC Client 대화 UI에<br/>전사된 발화 내용 표시
    end

    %% 3. 욕설/폭언 감지 및 흐름
    rect rgb(255, 240, 245)
    Note right of U: 3. 욕설/폭언 감지 및 자동 호 종료
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
    CAS->>W: 미디어 포크 종료 요청
    W->>STT: 미디어 스트리밍 종료
    end
```

## 시나리오 설명

1. **호 수립 (Establish)**
   - 유저 단말과 교환기 간의 호 연결 과정에서 통화매니저 AS가 개입하여 라우팅 및 호 제어를 수행합니다.
   - 통화매니저 AS는 WTIMS를 통해 STT 서버로 전달될 미디어 스트리밍(포크) 채널을 수립합니다.

2. **평시 대화 전사 (PC Client 표시)**
   - 발화자의 음성은 WTIMS를 거쳐 클라우드의 STT 서버로 전송됩니다.
   - STT 서버는 인식된 텍스트를 AI Agent 서버로 전달하여 분석하게 하고, 동시에 통화매니저 API를 통해 PC Client에 전사 데이터를 푸시합니다.
   - PC Client는 수신된 텍스트 데이터를 사용자 대화 UI에 실시간으로 표시합니다.

3. **욕설/폭언 시 호 종료 흐름**
   - 발화자의 대화 내용에 욕설 또는 폭언이 포함된 경우, STT에서 변환된 텍스트를 바탕으로 AI Agent가 이를 즉시 판단합니다.
   - AI Agent는 통화매니저 API를 통해 PC Client로 폭언 발생 알림을 전송하여 화면에 경고를 표시하도록 합니다.
   - 또한, 통화매니저 API는 통화매니저 AS에 폭언 시나리오 적용을 요청합니다.
   - 통화매니저 AS는 WTIMS에 명령을 내려 **"부적절한 내용이 감지되어 민원처리법에 따라 통화가 종료됩니다."** 라는 폭언 안내멘트를 고객 측에 송출합니다.
   - 멘트 송출 완료 후, 통화매니저 AS는 교환기를 통해 호를 강제로 종료(Disconnect)하고 STT로 향하는 미디어 스트림도 함께 종료합니다.
