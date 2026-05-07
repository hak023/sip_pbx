# SmartPBX AI - Production Deployment Architecture
## 상용 적용 상세 아키텍처 (기존 교환기/통화매니저AS/WTIMS 활용)

본 문서는 실제 상용 목표 용량을 기준으로, 이미 보유한 통신 노드(교환기, 통화매니저AS, WTIMS)를 활용하여 AI 확장 계층(STT/TTS/LLM/API/Runtime/DB/관측)을 설계한다.

| 항목 | 내용 |
|------|------|
| 용량 목표 | 가입자 10,000명, 50 CPS, 평균 통화 유지 120초 |
| 동시세션 산정 | `50 CPS x 120s = 6,000 동시 세션` |
| 기존 자산 | 교환기 N개, 통화매니저AS 2 Pair(A/S), WTIMS RTP 서버 |
| 신규 구축 | Internal STT, Internal TTS, Internal LLM, AI Runtime, API/Realtime, Observability |
| DB 제약 | RDB는 Altibase 사용 필수 |

---

## 1) 설계 전제 및 해석

### 1.1 용량 해석

- **동시세션**: 6,000호 (Busy Hour 기준)
- **CPS**: 50 INVITE/s 지속 유입
- **AI 적용률 가정**: 70% (나머지는 단순 연결/전달/정책 처리)
- **실시간 AI 활성 구간 가정**:
  - STT 활성 스트림: `6,000 x 0.7 = 4,200`
  - TTS 활성 채널: `6,000 x 0.7 x 0.6 = 2,520`
  - LLM 동시 생성 요청: `6,000 x 0.7 x 0.15 = 630`

### 1.2 기존 노드 활용 원칙

1. **LB 없음**: 외부 교환기 N개가 분산 진입점 역할 수행
2. **SIP Core 신규 구축 없음**: 통화매니저AS(Active/Standby 2 Pair) 활용
3. **RTP Core 신규 구축 없음**: WTIMS가 RTP Relay 수행
4. **신규 개발 포인트**: WTIMS RTP 복제(fork/mirror) -> STT 파이프라인 연계

---

## 2) 전체 배포 구조 (Mermaid)

```mermaid
flowchart LR
    subgraph EXT["외부 통신 영역"]
        CUST["PSTN/SIP 가입자 (10,000 users)"]
        EX["교환기 노드 N개<br/>SIP Trunk"]
    end

    subgraph CORE["기존 코어 통신 영역 (기존 자산)"]
        CM["통화매니저AS Pair-1/2<br/>Active/Standby x 2"]
        WT["WTIMS RTP Cluster<br/>RTP Relay + RTP Mirror"]
    end

    subgraph AI["신규 AI 처리 영역 (내부 구축)"]
        AIR["AI Runtime Cluster<br/>Session Orchestrator / Intent / Policy / HITL"]
        STT["STT Server Pool<br/>Streaming ASR"]
        LLM["LLM Inference Pool<br/>Agent/Tool Reasoning"]
        TTS["TTS Server Pool<br/>Streaming TTS"]
    end

    subgraph APP["업무/API 영역"]
        API["API/Realtime Cluster<br/>REST + WebSocket + SIP MESSAGE Bridge"]
    end

    subgraph DATA["데이터 영역"]
        ALT["Altibase HA<br/>RDB (필수)"]
        VDB["VectorDB Cluster<br/>Chroma(샤딩/복제) 또는 대체 엔진"]
        OBJ["Object Storage<br/>Recordings/Transcripts/Artifacts/Backups"]
    end

    subgraph OBS["관측 영역"]
        OBSV["Observability Cluster<br/>Metrics/Logs/Traces/Alerting"]
    end

    CUST -->|SIP/RTP| EX
    EX -->|SIP INVITE/UPDATE/BYE| CM
    CM -->|SIP+SDP Session Control| WT
    WT -->|RTP Relay| CUST
    WT -->|RTP Mirror SRTP RTP fork| STT

    CM -->|Session Event gRPC Kafka| AIR
    AIR -->|gRPC Streaming ASR| STT
    AIR -->|OpenAI-compatible HTTP/gRPC| LLM
    AIR -->|gRPC/HTTP TTS synth| TTS
    TTS -->|PCM/RTP payload| WT

    API <-->|HTTPS REST / WSS| AIR
    API <-->|SQL| ALT
    AIR <-->|SQL| ALT
    AIR <-->|Vector Query/Upsert| VDB
    AIR -->|Object PUT/GET| OBJ
    API -->|Object presigned URL| OBJ

    CM --> OBSV
    WT --> OBSV
    AIR --> OBSV
    STT --> OBSV
    LLM --> OBSV
    TTS --> OBSV
    API --> OBSV
    ALT --> OBSV
    VDB --> OBSV
```

### 구조 설명

- 교환기 N개가 외부 트래픽을 분산하므로 별도 LB를 두지 않는다.
- 통화매니저AS는 SIP 세션 상태 머신/호제어를 담당하고, WTIMS는 RTP 실시간 중계를 담당한다.
- AI Runtime은 통화 이벤트 기반으로 STT/LLM/TTS를 호출하고, 결과 음성을 다시 WTIMS로 전달한다.
- Altibase는 거래성 데이터(세션, 정책, 예약, 이력), VectorDB는 의미 검색, Object Storage는 대용량 비정형 파일 저장을 담당한다.

---

## 3) 프로토콜/연동 규격 상세

```mermaid
flowchart TD
    CM["통화매니저AS"] -->|SIP/2.0 + SDP| WT["WTIMS"]
    WT -->|RTP/RTCP relay| EP["통화 단말"]
    WT -->|RTP Mirror fork| STT["STT Server"]
    AIR["AI Runtime"] -->|gRPC bidi · 16k PCM Opus| STT
    AIR -->|HTTP2 gRPC 또는 REST · OpenAI-compatible| LLM["LLM Server"]
    AIR -->|gRPC/HTTP TTS API| TTS["TTS Server"]
    TTS -->|PCM chunk / RTP payload| WT
    API["API/Realtime"] -->|HTTPS REST JSON| AIR
    API -->|WSS WebSocket| CON["운영 콘솔"]
    AIR -->|SQL/JDBC| ALT["Altibase"]
    AIR -->|HTTP/gRPC| VDB["VectorDB"]
    AIR -->|S3 API PUT GET| OBJ["Object Storage"]
```

### 연동 규격 제안

- **교환기 <-> 통화매니저AS**: SIP Trunk (UDP/TCP/TLS)
- **통화매니저AS <-> WTIMS**: SIP/SDP 제어 + RTP/RTCP
- **WTIMS -> STT**: RTP mirror stream (codec normalized PCM 16k 권장)
- **AI Runtime <-> STT**: gRPC bidirectional streaming
- **AI Runtime <-> LLM**: OpenAI-compatible REST 또는 gRPC inference API
- **AI Runtime <-> TTS**: gRPC streaming synth (chunked PCM 반환)
- **API/Realtime <-> 운영 콘솔**: HTTPS REST + WSS 이벤트
- **AI/API <-> Altibase**: JDBC/ODBC(SQL)
- **AI <-> VectorDB**: query/upsert API (HTTP/gRPC)
- **AI/API <-> Object Storage**: S3-compatible API

---

## 4) 통화 처리 시퀀스 (Mermaid Sequence)

```mermaid
sequenceDiagram
    participant U as 가입자
    participant EX as 교환기
    participant CM as 통화매니저AS
    participant WT as WTIMS
    participant AIR as AI Runtime
    participant STT as STT
    participant LLM as LLM
    participant TTS as TTS

    U->>EX: INVITE
    EX->>CM: SIP INVITE
    CM->>WT: SIP+SDP (media anchoring)
    WT-->>CM: 200 OK (media ready)
    CM-->>EX: 200 OK
    EX-->>U: 200 OK / ACK

    U->>WT: RTP 음성
    WT->>STT: RTP mirror stream
    CM->>AIR: call_started event
    STT-->>AIR: partial/final transcript (stream)
    AIR->>LLM: inference request (intent/context/tool)
    LLM-->>AIR: answer + action
    AIR->>TTS: synth request
    TTS-->>AIR: PCM chunks
    AIR->>WT: play audio command
    WT-->>U: RTP(TTS)

    U->>EX: BYE
    EX->>CM: SIP BYE
    CM->>WT: release media
    CM->>AIR: call_ended event
```

---

## 5) 서버 역할별 권장 모델 및 스펙

## 5.1 STT 서버 (내부 구축)

- **권장 모델**
  - 1순위: `NVIDIA NeMo Conformer-CTC (ko fine-tune)`
  - 2순위: `Whisper-large-v3-turbo` (추론 최적화 필요)
- **권장 형태**: GPU inference + gRPC streaming
- **서버 스펙(노드당)**: 32 vCPU / 128 GB RAM / GPU L40S 1장 이상 / NVMe 1 TB
- **처리량 가정**: 600 동시 스트림/노드

## 5.2 TTS 서버 (내부 구축)

- **권장 모델**
  - 1순위: `FastSpeech2 + HiFi-GAN` (한국어 화자 튜닝)
  - 2순위: `VITS 계열` (자연스러움 우선)
- **권장 형태**: gRPC streaming synth + 캐시
- **서버 스펙(노드당)**: 24 vCPU / 96 GB RAM / GPU L40S 1장 / NVMe 1 TB
- **처리량 가정**: 500 동시 합성 채널/노드

## 5.3 LLM 서버 (내부 구축)

- **권장 모델**
  - 운영 기본: `Qwen2.5-14B-Instruct` 또는 `Llama-3.1-8B-Instruct` (저지연)
  - 고정밀 풀: `Qwen2.5-32B` 또는 동급 (복잡 질의 전용)
- **권장 형태**: OpenAI-compatible endpoint + vLLM/TGI
- **서버 스펙(노드당)**: 32 vCPU / 256 GB RAM / GPU L40S 2장 이상 / NVMe 2 TB
- **처리량 가정**: 80 동시 생성 요청/노드 (평균 128~256 tokens)

## 5.4 AI Runtime 서버

- **역할**: 세션 오케스트레이션, 정책 판단, HITL, 도구 호출, STT/TTS/LLM 라우팅
- **서버 스펙(노드당)**: 16 vCPU / 64 GB RAM / NVMe 500 GB
- **처리량 가정**: 1,200 동시 세션/노드

## 5.5 API/Realtime 서버

- **역할**: REST API, 운영 UI, WebSocket 이벤트, SIP MESSAGE 브릿지
- **연동규격**: HTTPS(JSON), WSS, 내부 gRPC/HTTP
- **서버 스펙(노드당)**: 16 vCPU / 32 GB RAM / NVMe 500 GB
- **처리량 가정**: 2,500 동시 WS + 400 rps

---

## 6) 6,000 동시세션 기준 서버 산정표

| 계층 | 동시 부하 산정 | 노드당 처리량 가정 | 필요 Active 노드 | 권장 구성(여유 포함) |
|------|----------------|--------------------|------------------|----------------------|
| 통화매니저AS | 기존 코어 사용 | 기존 Pair 용량 기준 | 기존 2 Pair 활용 | 추가 구축 없음 |
| WTIMS RTP | 6,000 RTP 세션 | 800 세션/노드 | 8 | 8 Active + 2 Standby |
| STT | 4,200 스트림 | 600/노드 | 7 | 7 Active + 2 Standby |
| TTS | 2,520 채널 | 500/노드 | 6 | 6 Active + 2 Standby |
| LLM | 630 동시 생성 | 80/노드 | 8 | 8 Active + 2 Standby |
| AI Runtime | 6,000 세션 | 1,200/노드 | 5 | 5 Active + 1 Standby |
| API/Realtime | 10,000 user, 6,000 WS peak | 2,500 WS/노드 | 4 | 4 Active + 1 Standby |
| Altibase | 세션/정책/이력 | DB HA 기준 | 2 | Primary + Standby + Read Replica(권장) |
| VectorDB | 고QPS 검색/업서트 | 200 QPS/샤드 가정 | 4 샤드 | 4 Active + 2 Replica |
| Object Storage | 녹음/아티팩트 저장 | 대역폭 중심 | 2 | 2 Active 또는 관리형 |
| Observability | 전 계층 수집 | 수집량 기준 | 2 | 2 Active(수집/조회 분리 권장) |

> 상기 수치는 초기 계획치이며, 반드시 스테이징에서 50 CPS/120초/6,000 동시세션 부하로 재검증한다.

### 6.1 서버 스펙 최종 요약표 (권장)

| 서버 역할 | 권장 대수 (Active+Standby) | CPU | RAM | GPU | 스토리지 | NIC | 비고 |
|-----------|-----------------------------|-----|-----|-----|----------|-----|------|
| 통화매니저AS | 기존 2 Pair 활용 | 기존 사양 | 기존 사양 | - | 기존 사양 | 기존 사양 | 신규 구축 없음 |
| WTIMS RTP | 8 + 2 | 24 vCPU | 64 GB | - | NVMe 1 TB | 10 Gbps | RTP Relay + RTP Mirror |
| STT Server | 7 + 2 | 32 vCPU | 128 GB | L40S x1 | NVMe 1 TB | 10 Gbps | gRPC streaming ASR |
| TTS Server | 6 + 2 | 24 vCPU | 96 GB | L40S x1 | NVMe 1 TB | 10 Gbps | gRPC streaming TTS |
| LLM Server | 8 + 2 | 32 vCPU | 256 GB | L40S x2 | NVMe 2 TB | 25 Gbps | vLLM/TGI 추론 풀 |
| AI Runtime | 5 + 1 | 16 vCPU | 64 GB | - | NVMe 500 GB | 10 Gbps | 세션 오케스트레이션 |
| API/Realtime | 4 + 1 | 16 vCPU | 32 GB | - | NVMe 500 GB | 10 Gbps | REST/WSS 게이트웨이 |
| Altibase | 2 + 1(읽기복제) | 24 vCPU | 128 GB | - | NVMe 2 TB (고IOPS) | 10 Gbps | Primary/Standby/Read |
| VectorDB | 4 + 2 | 24 vCPU | 128 GB | 선택(0~1) | NVMe 2 TB | 10 Gbps | 샤드+레플리카 |
| Object Storage | 2 이상 | 16 vCPU | 64 GB | - | HDD 20 TB + SSD Cache | 10 Gbps | S3 API 호환 |
| Observability | 2 + 1 | 16 vCPU | 64 GB | - | NVMe 2 TB | 10 Gbps | OTel/TSDB/Log/Trace |

### 6.2 목표 용량 대비 계산 체크

- 동시세션 목표: `6,000`
- WTIMS 유효 수용량: `8 active x 800 = 6,400` (약 6.7% 여유, standby 별도)
- STT 유효 수용량: `7 active x 600 = 4,200` (AI 적용률 70% 가정과 정합)
- TTS 유효 수용량: `6 active x 500 = 3,000` (동시 합성 2,520 가정 대비 여유)
- LLM 유효 수용량: `8 active x 80 = 640` (동시 생성 630 가정, 피크 대응은 standby 승격 권장)

---

## 7) DB/스토리지 설계 포인트

### 7.1 Altibase (필수 RDB)

- 저장 대상: 세션 상태, 정책, 예약, 사용자/권한, 운영 이벤트 인덱스
- 구성: Primary/Standby + Read Replica
- 요구사항: WAL/로그 백업, 장애 전환 자동화, PITR 리허설

### 7.2 VectorDB 성능 고려

- Chroma 단일 노드 운영은 6,000 세션 규모에서 병목 가능성이 높다.
- 권장:
  - Chroma 사용 시 샤딩/리드 레플리카/캐시 계층 필수
  - 고부하 검색이 핵심이면 Milvus/Qdrant 계열 PoC 병행 권장

### 7.3 Object Storage 역할

Object Storage는 다음 용도로 필수에 가깝다.

1. 통화 녹음 파일(원본/혼합본)
2. STT 중간 산출물(segments, diarization chunks)
3. TTS 캐시 음성(반복 응답)
4. 모델 입력/출력 아카이브(규정 준수 범위 내)
5. 백업 스냅샷 및 장기보관 데이터

---

## 8) Observability 상세

```mermaid
flowchart LR
    subgraph NODES["서비스 노드"]
      CM["통화매니저AS"]
      WT["WTIMS"]
      AIR["AI Runtime"]
      STT["STT"]
      TTS["TTS"]
      LLM["LLM"]
      API["API/Realtime"]
      DB["Altibase/VectorDB/Object"]
    end

    subgraph OBS["Observability"]
      OTL["OTel Collector"]
      MTS["Metrics TSDB (Prometheus/Mimir)"]
      LOG["Log Store (Loki/ELK)"]
      TRC["Trace Store (Tempo/Jaeger)"]
      ALR["Alert Manager"]
      GRA["Grafana"]
    end

    CM --> OTL
    WT --> OTL
    AIR --> OTL
    STT --> OTL
    TTS --> OTL
    LLM --> OTL
    API --> OTL
    DB --> OTL

    OTL --> MTS
    OTL --> LOG
    OTL --> TRC
    MTS --> ALR
    LOG --> GRA
    TRC --> GRA
    MTS --> GRA
```

### 핵심 모니터링 지표

- SIP: INVITE 성공률, 4xx/5xx 비율, CPS 실시간
- RTP: packet loss, jitter, one-way delay, mirror backlog
- STT/TTS: p95 latency, timeout ratio, stream drop ratio
- LLM: TTFT, tokens/sec, queue depth, error ratio
- AI Runtime: 세션당 처리시간, HITL 전환율, 실패 복구율
- API/WS: rps, ws fanout delay, reconnect rate
- DB: query p95, lock wait, replication lag

---

## 9) 상용 적용 체크리스트

- [ ] 교환기 N개 -> 통화매니저AS 라우팅 정책 검증
- [ ] WTIMS RTP mirror 기능 개발/검증 완료
- [ ] Internal STT/TTS/LLM API 스펙 확정(gRPC/REST)
- [ ] AI Runtime 장애 격리(서킷브레이커/타임아웃/재시도) 적용
- [ ] Altibase HA 및 백업/복구 리허설 완료
- [ ] VectorDB 샤딩/복제/캐시 정책 반영
- [ ] 6,000 동시세션 + 50 CPS 부하테스트 통과
- [ ] 관측 대시보드/알람 임계치 운영팀 인수

---

## 10) 결론

본 구조는 기존 통신 코어(교환기/통화매니저AS/WTIMS)를 최대한 재활용하면서, AI 처리 계층(STT/TTS/LLM/Runtime/API)을 내부화해 주권과 확장성을 확보하는 설계다.  
핵심 성공 요소는 `WTIMS RTP mirror 안정화`, `AI 계층 프로토콜 표준화`, `6,000 세션 실부하 검증`이다.

