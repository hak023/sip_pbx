# Frontend Architecture - AI Voicebot Control Center

## 📋 Document Information

| Item | Content |
|------|---------|
| **Document Version** | v1.0 |
| **Date** | 2025-01-05 |
| **Author** | Winston (Architect) |
| **Project** | AI Voicebot Frontend & HITL System |
| **Status** | Architecture Design |

### Change History

| Date | Version | Description | Author |
|------|---------|-------------|--------|
| 2025-01-05 | v1.0 | Initial frontend architecture with HITL | Winston |

---

## 1. Executive Summary

### 1.1 Purpose

This document defines the **Frontend Control Center** architecture for the AI Voicebot system, enabling:

1. **Real-time Call Monitoring** - Live STT/TTS conversation tracking
2. **Knowledge Base Management** - Vector DB CRUD operations
3. **Human-in-the-Loop (HITL)** - Human intervention when AI confidence is low
4. **System Monitoring** - Metrics, logs, and performance dashboards

### 1.2 Key Features

#### 🎯 Core Capabilities

- **📊 Live Dashboard**: Real-time active calls, AI performance metrics
- **💬 Conversation Monitor**: Live STT transcript + TTS responses
- **🆘 HITL Intervention**: Human operators assist AI when needed
- **📚 Knowledge Management**: Add/Edit/Delete Vector DB entries
- **📈 Analytics**: Call success rate, AI confidence trends, cost tracking
- **🔐 Access Control**: Role-based permissions (Admin, Operator, Viewer)

---

## 2. System Architecture

### 2.1 High-Level Architecture

```mermaid
graph TB
    subgraph "Frontend (Browser)"
        UI[React/Next.js UI]
        WSClient[WebSocket Client]
        APIClient[REST API Client]
        StateManager[Redux/Zustand State]
    end
    
    subgraph "Backend Services"
        APIGateway[API Gateway<br/>FastAPI/aiohttp]
        WSServer[WebSocket Server<br/>Socket.IO/Native WS]
        
        subgraph "Core Services"
            AIOrchestrator[AI Orchestrator]
            KnowledgeService[Knowledge Service]
            MonitoringService[Monitoring Service]
            HITLService[HITL Service]
        end
        
        subgraph "Data Layer"
            VectorDB[(Vector DB<br/>ChromaDB/Pinecone)]
            PostgreSQL[(PostgreSQL<br/>User/Call Data)]
            Redis[(Redis<br/>Real-time State)]
        end
    end
    
    subgraph "External AI Services"
        STT[Google STT]
        TTS[Google TTS]
        LLM[Gemini Flash]
    end
    
    UI --> WSClient
    UI --> APIClient
    WSClient <-.Real-time Events.-> WSServer
    APIClient <-.REST API.-> APIGateway
    
    APIGateway --> KnowledgeService
    APIGateway --> HITLService
    APIGateway --> MonitoringService
    
    WSServer --> AIOrchestrator
    WSServer --> Redis
    
    KnowledgeService --> VectorDB
    MonitoringService --> PostgreSQL
    HITLService --> Redis
    HITLService --> AIOrchestrator
    
    AIOrchestrator --> STT
    AIOrchestrator --> TTS
    AIOrchestrator --> LLM
    
    style UI fill:#e1f5ff
    style WSServer fill:#fff4e1
    style HITLService fill:#ffe1e1
```

### 2.2 Technology Stack

#### Frontend

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| **Framework** | **Next.js 14+** (App Router) | SSR, SEO, API routes, streaming |
| **UI Library** | **React 18+** | Concurrent features, Suspense |
| **State Management** | **Zustand** | Lightweight, TypeScript-first |
| **Styling** | **Tailwind CSS + shadcn/ui** | Rapid development, consistent design |
| **Real-time** | **Socket.IO Client** | Auto-reconnect, fallback to polling |
| **API Client** | **TanStack Query (React Query)** | Caching, retry, optimistic updates |
| **Form Handling** | **React Hook Form + Zod** | Type-safe validation |
| **Charts** | **Recharts / Apache ECharts** | Real-time data visualization |
| **Audio Player** | **Wavesurfer.js** | Waveform visualization for recordings |

#### Backend (New Services)

| Service | Technology | Purpose |
|---------|-----------|---------|
| **API Gateway** | **FastAPI** | High-performance async REST API |
| **WebSocket** | **Socket.IO (Python)** | Real-time bidirectional communication |
| **Auth** | **JWT + OAuth2** | Secure authentication |
| **Database** | **PostgreSQL 15+** | User data, call logs, HITL history |
| **Cache** | **Redis 7+** | Real-time call state, session management |
| **Message Queue** | **Redis Pub/Sub** | Event broadcasting to multiple clients |

---

## 3. Human-in-the-Loop (HITL) Architecture

### 3.1 HITL Workflow

```mermaid
sequenceDiagram
    participant Caller as 📞 Caller
    participant AI as 🤖 AI Orchestrator
    participant Backend as 🔧 HITL Service
    participant Frontend as 👨‍💻 Human Operator
    
    Caller->>AI: "내일 회의 시간은 언제인가요?"
    
    AI->>AI: RAG Search (confidence: 0.4)
    
    alt Low Confidence (< 0.6)
        AI->>Backend: HITL Request (call_id, question, context)
        Backend->>Redis: Store HITL request
        Backend->>Frontend: WebSocket Event: HITL_REQUESTED
        
        AI->>Caller: 🔊 "잠시만 확인 중이니 기다려 주세요"
        AI->>Caller: 🎵 Hold music starts
        
        Frontend->>Frontend: Notification + Highlight Call
        Frontend->>Frontend: Show Question + Call Context
        
        Note over Frontend: Operator reviews and types answer
        
        Frontend->>Backend: Submit Answer (text)
        Backend->>Redis: Store human response
        Backend->>AI: Human Response Event
        
        AI->>AI: Hold music stops
        AI->>LLM: Refine human answer + context
        LLM-->>AI: Polished response
        
        AI->>Caller: 🔊 "내일 오후 2시에 회의가 있습니다"
        
        Backend->>Frontend: WebSocket: HITL_RESOLVED
        
        Note over Backend: Store in KB if useful
        Backend->>VectorDB: Add new knowledge
    else High Confidence (>= 0.6)
        AI->>LLM: Generate response normally
        AI->>Caller: 🔊 Answer
    end
```

### 3.2 HITL Trigger Conditions

```python
class HITLTrigger:
    """Conditions that trigger Human-in-the-Loop"""
    
    # Confidence thresholds
    RAG_CONFIDENCE_THRESHOLD = 0.6  # RAG search score
    LLM_CONFIDENCE_THRESHOLD = 0.5  # LLM generation confidence
    
    # Explicit triggers
    EXPLICIT_KEYWORDS = [
        "담당자", "실제 사람", "사람과 통화",
        "connect to human", "speak to person"
    ]
    
    # Complex question detection
    MAX_QUESTION_COMPLEXITY = 0.7  # Based on NLP analysis
    
    # Business rules
    SENSITIVE_TOPICS = [
        "계약", "결제", "환불", "클레임",
        "contract", "payment", "refund", "complaint"
    ]
```

### 3.2.1 운영자 상태 관리 시스템 (신규)

#### 운영자 상태 정의

```python
from enum import Enum
from typing import Optional
from datetime import datetime
from pydantic import BaseModel

class OperatorStatus(str, Enum):
    """운영자 상태"""
    AVAILABLE = "available"      # 대기 중 (HITL 요청 즉시 처리)
    AWAY = "away"                # 부재중 (HITL 요청 자동 거절 + 통화 이력 기록)
    BUSY = "busy"                # 통화 중 (HITL 요청 대기열 추가)
    OFFLINE = "offline"          # 오프라인 (시스템 로그아웃)

class OperatorConfig(BaseModel):
    """운영자 설정"""
    operator_id: str
    status: OperatorStatus
    away_message: str = "죄송합니다. 해당 부분은 잘 모르는 내용이라 확인 후 별도로 안내드리겠습니다."
    status_changed_at: datetime
    auto_away_minutes: Optional[int] = None  # N분 무응답 시 자동 부재중 전환

class UnresolvedHITLRequest(BaseModel):
    """미처리 HITL 요청 (통화 이력)"""
    request_id: str
    call_id: str
    caller_id: str
    callee_id: str
    user_question: str            # 사용자 질문
    conversation_history: List[Dict]
    rag_results: List[Dict]
    ai_confidence: float
    timestamp: datetime
    status: str = "unresolved"    # unresolved | noted | resolved | contacted
    operator_note: Optional[str]  # 운영자 메모
    follow_up_required: bool = False
    follow_up_phone: Optional[str] = None  # 회신 전화번호
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None
```

#### HITL 워크플로우 - 운영자 대기 중

```mermaid
sequenceDiagram
    participant User as 📞 발신자
    participant AI as 🤖 AI Orchestrator
    participant HITL as 🔧 HITL Service
    participant Redis as 💾 Redis
    participant WS as 🌐 WebSocket
    participant Frontend as 👨‍💻 운영자 UI
    participant Operator as 👤 운영자

    Note over Frontend: 운영자 상태: AVAILABLE

    User->>AI: 질문 (음성)
    AI->>AI: RAG 검색 + LLM 답변 생성
    AI->>AI: 신뢰도 판단 (< 0.6)
    
    Note over AI: 신뢰도 낮음 → HITL 요청
    
    AI->>HITL: request_human_help(call_id, question, context)
    HITL->>Redis: GET operator:status
    Redis-->>HITL: status = "available"
    
    HITL->>Redis: SET hitl:{call_id} (request data)
    HITL->>WS: broadcast('hitl_requested', {...})
    WS->>Frontend: WebSocket Event
    Frontend->>Operator: 🔔 알림 + 다이얼로그 표시
    
    AI->>User: TTS: "잠시만 기다려 주세요. 확인해 드리겠습니다."
    AI->>User: 🎵 대기 음악 재생
    
    Operator->>Frontend: 답변 입력 + 전송
    Frontend->>HITL: POST /api/hitl/response
    HITL->>Redis: UPDATE hitl:{call_id} (status: responded)
    HITL->>AI: deliver_response(call_id, response_text)
    
    AI->>AI: 🎵 대기 음악 중단
    AI->>AI: LLM으로 답변 다듬기
    AI->>User: TTS: 최종 답변
    
    Note over HITL: 타임아웃 시 (5분)
    HITL-->>AI: timeout_response()
    AI->>User: TTS: "죄송합니다. 확인이 지연되고 있습니다."
```

#### HITL 워크플로우 - 운영자 부재중 (신규 기능)

```mermaid
sequenceDiagram
    participant User as 📞 발신자
    participant AI as 🤖 AI Orchestrator
    participant HITL as 🔧 HITL Service
    participant Redis as 💾 Redis
    participant CallHistory as 📋 통화 이력 DB
    participant Frontend as 👨‍💻 운영자 UI
    participant Operator as 👤 운영자 (복귀 후)

    Note over Frontend: 운영자가 "부재중" 토글 활성화
    Frontend->>HITL: PUT /api/operator/status
    HITL->>Redis: SET operator:status = "away"
    HITL->>Redis: SET operator:away_message
    
    User->>AI: 질문 (음성)
    AI->>AI: RAG 검색 + LLM 답변 생성
    AI->>AI: 신뢰도 판단 (< 0.6)
    
    Note over AI: 신뢰도 낮음 → HITL 요청
    
    AI->>HITL: request_human_help(call_id, question, context)
    HITL->>Redis: GET operator:status
    Redis-->>HITL: status = "away"
    
    Note over HITL: ⚠️ 운영자 부재중 감지<br/>자동 거절 모드 활성화
    
    HITL->>CallHistory: INSERT unresolved_hitl_request<br/>(call_id, question, context, status=unresolved)
    HITL->>Redis: LPUSH unresolved_hitl_queue {call_id}
    HITL->>AI: auto_fallback_response(away_message)
    
    AI->>User: TTS: "죄송합니다. 해당 부분은<br/>잘 모르는 내용이라<br/>확인 후 별도로 안내드리겠습니다."
    
    Note over User,AI: 통화 정상 종료
    
    Note over Frontend: 🔄 운영자 복귀
    Frontend->>HITL: PUT /api/operator/status (status: available)
    HITL->>Redis: SET operator:status = "available"
    
    Operator->>Frontend: "미처리 HITL 요청" 배지 클릭
    Frontend->>CallHistory: GET /api/call-history?unresolved_hitl=true
    CallHistory-->>Frontend: 미처리 HITL 요청 목록
    
    Frontend->>Operator: 테이블 형태로 표시<br/>(발신자, 질문, 시각, 상태)
    
    Operator->>Frontend: 특정 통화 선택 → 상세 조회
    Frontend->>CallHistory: GET /api/call-history/{call_id}
    CallHistory-->>Frontend: 통화 전체 내용 + STT 기록
    
    Operator->>Frontend: 메모 작성 + 저장
    Frontend->>CallHistory: POST /api/call-history/{call_id}/note<br/>{operator_note, follow_up_required}
    
    alt 후속 조치 필요
        Operator->>Frontend: "고객에게 전화" 버튼 클릭
        Frontend->>Frontend: 발신자 전화번호 복사 + 알림
        Note over Operator: 운영자가 직접 고객에게 회신
        Operator->>Frontend: "처리 완료" 버튼
        Frontend->>CallHistory: PUT /api/call-history/{call_id}/resolve
    else 메모만 남김
        Frontend->>CallHistory: UPDATE status = "noted"
    end
```

### 3.3 Hold Experience Design

#### Backend Hold Manager

```python
class HoldManager:
    """Manages caller experience during HITL"""
    
    async def start_hold(self, call_id: str, estimated_wait: int = 30):
        """
        Start hold experience
        
        Args:
            call_id: Call identifier
            estimated_wait: Estimated wait time in seconds
        """
        # 1. Play initial hold message
        await self.tts_client.synthesize(
            "잠시만 확인 중이니 기다려 주세요. "
            "곧 답변 드리겠습니다."
        )
        
        # 2. Start hold music (loop)
        await self.audio_player.play_loop(
            file="assets/hold-music.wav",
            call_id=call_id
        )
        
        # 3. Periodic updates (every 15 seconds)
        self.schedule_periodic_updates(call_id, interval=15)
    
    async def periodic_update(self, call_id: str):
        """Send periodic hold messages"""
        await self.audio_player.pause_music(call_id)
        
        await self.tts_client.synthesize(
            "곧 답변 드리겠습니다. 잠시만 더 기다려 주세요."
        )
        
        await self.audio_player.resume_music(call_id)
    
    async def end_hold(self, call_id: str):
        """End hold and resume conversation"""
        await self.audio_player.stop_music(call_id)
        
        await self.tts_client.synthesize(
            "확인되었습니다."
        )
```

---

## 4. Frontend Components Architecture

### 4.1 Page Structure

```
/
├── / (Dashboard)                    # Overview, active calls
├── /calls                           # Call history, search
│   ├── /calls/live                  # Real-time monitoring
│   └── /calls/:id                   # Call detail + recording
├── /knowledge                       # Vector DB management
│   ├── /knowledge/browse            # Browse entries
│   ├── /knowledge/add               # Add new knowledge
│   └── /knowledge/:id/edit          # Edit entry
├── /hitl                            # HITL queue & history
│   ├── /hitl/queue                  # Pending HITL requests
│   └── /hitl/history                # Resolved HITL cases
├── /analytics                       # Metrics & reports
├── /settings                        # System configuration
└── /admin                           # User management, roles
```

### 4.2 Key Components

#### 4.2.1 Live Call Monitor

```tsx
// components/LiveCallMonitor.tsx

interface LiveCallMonitorProps {
  callId: string;
}

export function LiveCallMonitor({ callId }: LiveCallMonitorProps) {
  const { transcript, isAISpeaking } = useLiveCall(callId);
  const { submitHITL } = useHITL();
  
  return (
    <Card>
      <CardHeader>
        <LiveIndicator isActive />
        <CallInfo callId={callId} />
      </CardHeader>
      
      <CardContent>
        {/* Real-time transcript */}
        <TranscriptView 
          messages={transcript}
          isAISpeaking={isAISpeaking}
        />
        
        {/* HITL Alert */}
        {transcript.needsHelp && (
          <HITLAlert 
            question={transcript.currentQuestion}
            context={transcript.context}
            onSubmit={submitHITL}
          />
        )}
        
        {/* Quick Actions */}
        <QuickActions 
          onEndCall={() => {}}
          onTransferCall={() => {}}
        />
      </CardContent>
    </Card>
  );
}
```

#### 4.2.2 HITL Response Interface

```tsx
// components/HITLResponseInterface.tsx

interface HITLRequest {
  callId: string;
  question: string;
  context: {
    previousMessages: Message[];
    ragResults: SearchResult[];
    callerInfo: CallerInfo;
  };
  urgency: 'high' | 'medium' | 'low';
  timestamp: Date;
}

export function HITLResponseInterface({ request }: { request: HITLRequest }) {
  const [response, setResponse] = useState('');
  const { submitResponse, isSubmitting } = useHITLResponse();
  
  return (
    <Dialog open>
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle>
            🆘 AI가 도움을 요청했습니다
          </DialogTitle>
          <DialogDescription>
            통화 상대방은 대기 음악을 듣고 있습니다
          </DialogDescription>
        </DialogHeader>
        
        <div className="grid grid-cols-2 gap-4">
          {/* Left: Context */}
          <div>
            <h3>질문</h3>
            <p className="text-lg font-semibold">{request.question}</p>
            
            <h3>대화 내역</h3>
            <ConversationHistory messages={request.context.previousMessages} />
            
            <h3>발신자 정보</h3>
            <CallerInfoDisplay info={request.context.callerInfo} />
            
            <h3>RAG 검색 결과</h3>
            <RAGResultsDisplay results={request.context.ragResults} />
          </div>
          
          {/* Right: Response */}
          <div>
            <Label>답변 작성</Label>
            <Textarea
              value={response}
              onChange={(e) => setResponse(e.target.value)}
              placeholder="AI에게 전달할 답변을 작성하세요..."
              rows={10}
              className="mb-4"
            />
            
            <div className="flex items-center gap-2 mb-4">
              <Checkbox id="save-kb" />
              <Label htmlFor="save-kb">
                이 답변을 지식 베이스에 저장
              </Label>
            </div>
            
            <div className="flex gap-2">
              <Button
                onClick={() => submitResponse(request.callId, response)}
                disabled={!response || isSubmitting}
                className="flex-1"
              >
                전송 (AI가 다듬어서 발화)
              </Button>
              <Button variant="outline" onClick={() => {}}>
                취소
              </Button>
            </div>
            
            <p className="text-sm text-muted-foreground mt-2">
              💡 Tip: AI가 자연스럽게 다듬어서 발화합니다
            </p>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
```

#### 4.2.3 Knowledge Base Manager

```tsx
// components/KnowledgeManager.tsx

export function KnowledgeManager() {
  const { knowledge, isLoading } = useKnowledgeBase();
  const { createEntry, updateEntry, deleteEntry } = useKnowledgeMutations();
  
  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h1>지식 베이스 관리</h1>
        <Button onClick={() => setShowAddDialog(true)}>
          ➕ 새 항목 추가
        </Button>
      </div>
      
      {/* Search & Filters */}
      <div className="flex gap-2">
        <Input 
          placeholder="검색..." 
          className="flex-1"
        />
        <Select>
          <SelectTrigger>
            <SelectValue placeholder="카테고리" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">전체</SelectItem>
            <SelectItem value="faq">FAQ</SelectItem>
            <SelectItem value="policy">정책</SelectItem>
            <SelectItem value="schedule">일정</SelectItem>
          </SelectContent>
        </Select>
      </div>
      
      {/* Knowledge List */}
      <DataTable
        columns={knowledgeColumns}
        data={knowledge}
        onEdit={(entry) => setEditingEntry(entry)}
        onDelete={(entry) => deleteEntry(entry.id)}
      />
      
      {/* Add/Edit Dialog */}
      <KnowledgeEntryDialog
        entry={editingEntry}
        onSave={(data) => {
          if (editingEntry) {
            updateEntry(editingEntry.id, data);
          } else {
            createEntry(data);
          }
        }}
      />
    </div>
  );
}
```

#### 4.2.4 Real-time Dashboard

```tsx
// components/Dashboard.tsx

export function Dashboard() {
  const { activeCalls } = useActiveCalls();
  const { metrics } = useMetrics();
  const { hitlQueue } = useHITLQueue();
  const { operatorStatus, unresolvedHITLCount } = useOperatorStatus(); // 신규
  
  return (
    <div className="grid grid-cols-12 gap-4">
      {/* Operator Status Toggle (신규) */}
      <Card className="col-span-12">
        <CardContent className="flex items-center justify-between p-4">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium">운영자 상태:</span>
              <Badge variant={operatorStatus === 'available' ? 'success' : 'secondary'}>
                {operatorStatus === 'available' ? '🟢 대기중' : '🔴 부재중'}
              </Badge>
            </div>
            <Switch
              checked={operatorStatus === 'available'}
              onCheckedChange={(checked) => {
                updateOperatorStatus(checked ? 'available' : 'away');
              }}
            />
          </div>
          
          {unresolvedHITLCount > 0 && (
            <Alert variant="warning" className="flex-1 ml-4">
              <AlertTriangle className="h-4 w-4" />
              <AlertTitle>미처리 HITL 요청 {unresolvedHITLCount}건</AlertTitle>
              <AlertDescription>
                부재중에 발생한 HITL 요청이 있습니다.{' '}
                <Button variant="link" onClick={() => router.push('/call-history?filter=unresolved')}>
                  확인하기
                </Button>
              </AlertDescription>
            </Alert>
          )}
        </CardContent>
      </Card>
      
      {/* Top Stats */}
      <Card className="col-span-3">
        <CardHeader>
          <CardTitle>활성 통화</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-4xl font-bold">{activeCalls.length}</div>
        </CardContent>
      </Card>
      
      <Card className="col-span-3">
        <CardHeader>
          <CardTitle>HITL 대기</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-4xl font-bold text-orange-600">
            {hitlQueue.length}
          </div>
        </CardContent>
      </Card>
      
      <Card className="col-span-3">
        <CardHeader>
          <CardTitle>AI 신뢰도</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-4xl font-bold text-green-600">
            {metrics.avgConfidence}%
          </div>
        </CardContent>
      </Card>
      
      <Card className="col-span-3">
        <CardHeader>
          <CardTitle>오늘 통화</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-4xl font-bold">{metrics.todayCalls}</div>
        </CardContent>
      </Card>
      
      {/* Active Calls List */}
      <Card className="col-span-8">
        <CardHeader>
          <CardTitle>실시간 통화</CardTitle>
        </CardHeader>
        <CardContent>
          <ActiveCallsList calls={activeCalls} />
        </CardContent>
      </Card>
      
      {/* HITL Queue */}
      <Card className="col-span-4">
        <CardHeader>
          <CardTitle className="text-orange-600">
            🆘 도움 요청
          </CardTitle>
        </CardHeader>
        <CardContent>
          <HITLQueueList queue={hitlQueue} />
        </CardContent>
      </Card>
      
      {/* Charts */}
      <Card className="col-span-6">
        <CardHeader>
          <CardTitle>시간대별 통화량</CardTitle>
        </CardHeader>
        <CardContent>
          <LineChart data={metrics.hourlyCallVolume} />
        </CardContent>
      </Card>
      
      <Card className="col-span-6">
        <CardHeader>
          <CardTitle>AI 응답 시간</CardTitle>
        </CardHeader>
        <CardContent>
          <BarChart data={metrics.responseTimeDistribution} />
        </CardContent>
      </Card>
    </div>
  );
}
```

---

## 5. Backend API Design

### 5.1 REST API Endpoints

#### Operator Status Management (신규)

```python
# API Routes for Operator Status Management

from enum import Enum
from pydantic import BaseModel
from datetime import datetime

class OperatorStatus(str, Enum):
    AVAILABLE = "available"
    AWAY = "away"
    BUSY = "busy"
    OFFLINE = "offline"

class OperatorStatusUpdate(BaseModel):
    status: OperatorStatus
    away_message: Optional[str] = None

class OperatorStatusResponse(BaseModel):
    operator_id: str
    status: OperatorStatus
    away_message: str
    status_changed_at: datetime
    unresolved_hitl_count: int


@router.put("/api/operator/status")
async def update_operator_status(
    update: OperatorStatusUpdate,
    current_user: User = Depends(get_current_operator)
) -> OperatorStatusResponse:
    """
    운영자 상태 변경
    
    Body:
        status: "available" | "away" | "busy" | "offline"
        away_message: Optional[str] - 부재중 자동 응답 메시지
    """
    # Redis에 운영자 상태 저장
    await redis.set(
        f"operator:{current_user.id}:status",
        update.status,
        ex=86400  # 24시간
    )
    
    if update.away_message:
        await redis.set(
            f"operator:{current_user.id}:away_message",
            update.away_message,
            ex=86400
        )
    
    # 상태 변경 시각 기록
    await redis.set(
        f"operator:{current_user.id}:status_changed_at",
        datetime.now().isoformat(),
        ex=86400
    )
    
    # 미처리 HITL 요청 수 조회
    unresolved_count = await db.execute(
        """
        SELECT COUNT(*) FROM unresolved_hitl_requests
        WHERE status = 'unresolved' AND operator_id = :operator_id
        """,
        {"operator_id": current_user.id}
    )
    
    return OperatorStatusResponse(
        operator_id=current_user.id,
        status=update.status,
        away_message=update.away_message or "죄송합니다. 확인 후 별도로 안내드리겠습니다.",
        status_changed_at=datetime.now(),
        unresolved_hitl_count=unresolved_count
    )


@router.get("/api/operator/status")
async def get_operator_status(
    current_user: User = Depends(get_current_operator)
) -> OperatorStatusResponse:
    """현재 운영자 상태 조회"""
    status = await redis.get(f"operator:{current_user.id}:status") or "offline"
    away_message = await redis.get(f"operator:{current_user.id}:away_message")
    status_changed_at = await redis.get(f"operator:{current_user.id}:status_changed_at")
    
    unresolved_count = await db.execute(
        """
        SELECT COUNT(*) FROM unresolved_hitl_requests
        WHERE status = 'unresolved' AND operator_id = :operator_id
        """,
        {"operator_id": current_user.id}
    )
    
    return OperatorStatusResponse(
        operator_id=current_user.id,
        status=OperatorStatus(status),
        away_message=away_message or "죄송합니다. 확인 후 별도로 안내드리겠습니다.",
        status_changed_at=datetime.fromisoformat(status_changed_at) if status_changed_at else None,
        unresolved_hitl_count=unresolved_count
    )
```

#### Call History & Unresolved HITL Requests (신규)

```python
# API Routes for Call History with Unresolved HITL

class UnresolvedHITLFilter(str, Enum):
    ALL = "all"
    UNRESOLVED = "unresolved"
    NOTED = "noted"
    RESOLVED = "resolved"

class CallHistoryQuery(BaseModel):
    page: int = 1
    limit: int = 50
    unresolved_hitl: Optional[UnresolvedHITLFilter] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None


@router.get("/api/call-history")
async def get_call_history(
    query: CallHistoryQuery = Depends(),
    current_user: User = Depends(get_current_operator)
) -> CallHistoryResponse:
    """
    통화 이력 조회 (미처리 HITL 요청 포함)
    
    Query Params:
        page: int - 페이지 번호
        limit: int - 페이지당 항목 수
        unresolved_hitl: "all" | "unresolved" | "noted" | "resolved" - HITL 필터
        date_from: datetime - 시작 날짜
        date_to: datetime - 종료 날짜
    """
    # SQL 쿼리 구성
    sql = """
        SELECT 
            ch.*,
            uhr.request_id,
            uhr.user_question,
            uhr.ai_confidence,
            uhr.status as hitl_status,
            uhr.operator_note,
            uhr.follow_up_required,
            uhr.resolved_at
        FROM call_history ch
        LEFT JOIN unresolved_hitl_requests uhr ON ch.call_id = uhr.call_id
        WHERE 1=1
    """
    
    params = {}
    
    # 미처리 HITL 필터
    if query.unresolved_hitl and query.unresolved_hitl != UnresolvedHITLFilter.ALL:
        sql += " AND uhr.status = :hitl_status"
        params["hitl_status"] = query.unresolved_hitl
    
    # 날짜 필터
    if query.date_from:
        sql += " AND ch.start_time >= :date_from"
        params["date_from"] = query.date_from
    if query.date_to:
        sql += " AND ch.start_time <= :date_to"
        params["date_to"] = query.date_to
    
    # 정렬 (최신순)
    sql += " ORDER BY ch.start_time DESC"
    
    # 페이지네이션
    sql += " LIMIT :limit OFFSET :offset"
    params["limit"] = query.limit
    params["offset"] = (query.page - 1) * query.limit
    
    results = await db.fetch_all(sql, params)
    total = await db.fetch_one("SELECT COUNT(*) as cnt FROM call_history WHERE 1=1 ...")
    
    return CallHistoryResponse(
        items=results,
        total=total["cnt"],
        page=query.page,
        limit=query.limit
    )


@router.get("/api/call-history/{call_id}")
async def get_call_detail(
    call_id: str,
    current_user: User = Depends(get_current_operator)
) -> CallDetailResponse:
    """
    특정 통화 상세 정보 조회 (STT 전체 기록 포함)
    """
    call = await db.fetch_one(
        """
        SELECT ch.*, uhr.*
        FROM call_history ch
        LEFT JOIN unresolved_hitl_requests uhr ON ch.call_id = uhr.call_id
        WHERE ch.call_id = :call_id
        """,
        {"call_id": call_id}
    )
    
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    
    # STT 전체 기록 조회
    transcripts = await db.fetch_all(
        """
        SELECT * FROM call_transcripts
        WHERE call_id = :call_id
        ORDER BY timestamp ASC
        """,
        {"call_id": call_id}
    )
    
    return CallDetailResponse(
        call_info=call,
        transcripts=transcripts
    )


@router.post("/api/call-history/{call_id}/note")
async def add_call_note(
    call_id: str,
    note: CallNoteCreate,
    current_user: User = Depends(get_current_operator)
) -> CallNoteResponse:
    """
    통화 이력에 운영자 메모 추가
    
    Body:
        operator_note: str - 운영자 메모
        follow_up_required: bool - 후속 조치 필요 여부
        follow_up_phone: Optional[str] - 회신 전화번호
    """
    await db.execute(
        """
        UPDATE unresolved_hitl_requests
        SET 
            operator_note = :note,
            follow_up_required = :follow_up_required,
            follow_up_phone = :follow_up_phone,
            status = 'noted',
            noted_at = :noted_at,
            noted_by = :operator_id
        WHERE call_id = :call_id
        """,
        {
            "note": note.operator_note,
            "follow_up_required": note.follow_up_required,
            "follow_up_phone": note.follow_up_phone,
            "noted_at": datetime.now(),
            "operator_id": current_user.id,
            "call_id": call_id
        }
    )
    
    return CallNoteResponse(
        call_id=call_id,
        operator_note=note.operator_note,
        follow_up_required=note.follow_up_required,
        status="noted"
    )


@router.put("/api/call-history/{call_id}/resolve")
async def resolve_hitl_request(
    call_id: str,
    current_user: User = Depends(get_current_operator)
) -> ResolveResponse:
    """미처리 HITL 요청 해결 처리"""
    await db.execute(
        """
        UPDATE unresolved_hitl_requests
        SET 
            status = 'resolved',
            resolved_at = :resolved_at,
            resolved_by = :operator_id
        WHERE call_id = :call_id
        """,
        {
            "resolved_at": datetime.now(),
            "operator_id": current_user.id,
            "call_id": call_id
        }
    )
    
    return ResolveResponse(
        call_id=call_id,
        status="resolved",
        resolved_at=datetime.now()
    )
```

#### Knowledge Management

```python
# API Routes for Knowledge Base

@router.post("/api/knowledge")
async def create_knowledge(
    entry: KnowledgeEntryCreate,
    current_user: User = Depends(get_current_user)
) -> KnowledgeEntry:
    """
    Create new knowledge entry
    
    Body:
        text: str - The knowledge text
        category: str - Category (faq, policy, schedule, etc.)
        keywords: List[str] - Search keywords
        metadata: dict - Additional metadata
    """
    # Generate embedding
    embedding = await embedder.embed_single(entry.text)
    
    # Store in Vector DB
    doc_id = await vector_db.upsert(
        doc_id=f"manual_{uuid4()}",
        embedding=embedding,
        text=entry.text,
        metadata={
            "category": entry.category,
            "keywords": entry.keywords,
            "created_by": current_user.id,
            "created_at": datetime.now(),
            **entry.metadata
        }
    )
    
    return KnowledgeEntry(id=doc_id, **entry.dict())


@router.get("/api/knowledge")
async def list_knowledge(
    page: int = 1,
    limit: int = 50,
    category: Optional[str] = None,
    search: Optional[str] = None
) -> KnowledgeListResponse:
    """
    List knowledge entries with pagination and filters
    """
    # Build filter
    filter_dict = {}
    if category:
        filter_dict["category"] = category
    
    # Search by text if provided
    if search:
        embedding = await embedder.embed_single(search)
        results = await vector_db.search(
            vector=embedding,
            top_k=limit,
            filter=filter_dict
        )
    else:
        # List all (pagination)
        results = await vector_db.list(
            skip=(page - 1) * limit,
            limit=limit,
            filter=filter_dict
        )
    
    return KnowledgeListResponse(
        items=results,
        total=await vector_db.count(filter=filter_dict),
        page=page,
        limit=limit
    )


@router.put("/api/knowledge/{entry_id}")
async def update_knowledge(
    entry_id: str,
    update: KnowledgeEntryUpdate,
    current_user: User = Depends(get_current_user)
) -> KnowledgeEntry:
    """Update existing knowledge entry"""
    # Re-generate embedding if text changed
    if update.text:
        embedding = await embedder.embed_single(update.text)
    else:
        existing = await vector_db.get(entry_id)
        embedding = existing.embedding
    
    # Update Vector DB
    await vector_db.upsert(
        doc_id=entry_id,
        embedding=embedding,
        text=update.text or existing.text,
        metadata={
            **existing.metadata,
            **update.metadata,
            "updated_by": current_user.id,
            "updated_at": datetime.now()
        }
    )
    
    return await vector_db.get(entry_id)


@router.delete("/api/knowledge/{entry_id}")
async def delete_knowledge(
    entry_id: str,
    current_user: User = Depends(get_current_user)
) -> dict:
    """Delete knowledge entry"""
    await vector_db.delete(entry_id)
    return {"success": True, "id": entry_id}
```

#### Call Monitoring

```python
@router.get("/api/calls/active")
async def get_active_calls() -> List[ActiveCall]:
    """Get all active calls with real-time status"""
    active_calls = await call_manager.get_active_calls()
    
    return [
        ActiveCall(
            call_id=call.call_id,
            caller=call.caller_info,
            callee=call.callee_info,
            status=call.state.value,
            is_ai_handled=call.is_ai_handled,
            duration=call.duration_seconds,
            current_question=call.last_user_message,
            ai_confidence=call.last_confidence_score
        )
        for call in active_calls
    ]


@router.get("/api/calls/{call_id}/transcript")
async def get_call_transcript(call_id: str) -> CallTranscript:
    """Get real-time transcript for a call"""
    orchestrator = ai_orchestrators.get(call_id)
    if not orchestrator:
        raise HTTPException(404, "Call not found or ended")
    
    return CallTranscript(
        call_id=call_id,
        messages=orchestrator.conversation_history,
        is_speaking=orchestrator.is_speaking,
        current_state=orchestrator.state.value
    )
```

#### HITL Management

```python
@router.post("/api/hitl/response")
async def submit_hitl_response(
    response: HITLResponse,
    current_user: User = Depends(get_current_user)
) -> dict:
    """
    Submit human response to AI
    
    Body:
        call_id: str
        response_text: str
        save_to_kb: bool
        category: Optional[str]
    """
    # Get HITL request from Redis
    hitl_request = await redis_client.get(f"hitl:{response.call_id}")
    if not hitl_request:
        raise HTTPException(404, "HITL request not found or expired")
    
    # Send response to AI Orchestrator
    orchestrator = ai_orchestrators.get(response.call_id)
    if orchestrator:
        await orchestrator.handle_human_response(
            response_text=response.response_text,
            operator_id=current_user.id
        )
    
    # Save to knowledge base if requested
    if response.save_to_kb:
        await create_knowledge(
            KnowledgeEntryCreate(
                text=f"Q: {hitl_request['question']}\nA: {response.response_text}",
                category=response.category or "faq",
                keywords=extract_keywords(hitl_request['question']),
                metadata={
                    "source": "hitl",
                    "call_id": response.call_id,
                    "operator": current_user.id
                }
            ),
            current_user
        )
    
    # Log HITL resolution
    await db.execute(
        """
        INSERT INTO hitl_history (call_id, question, response, operator_id, resolved_at)
        VALUES ($1, $2, $3, $4, NOW())
        """,
        response.call_id,
        hitl_request['question'],
        response.response_text,
        current_user.id
    )
    
    # Remove from Redis
    await redis_client.delete(f"hitl:{response.call_id}")
    
    # Notify frontend via WebSocket
    await websocket_server.emit('hitl_resolved', {
        'call_id': response.call_id,
        'operator': current_user.name
    })
    
    return {"success": True}


@router.get("/api/hitl/queue")
async def get_hitl_queue() -> List[HITLRequest]:
    """Get pending HITL requests"""
    keys = await redis_client.keys("hitl:*")
    requests = []
    
    for key in keys:
        data = await redis_client.get(key)
        requests.append(HITLRequest(**data))
    
    # Sort by urgency and timestamp
    requests.sort(key=lambda x: (x.urgency, x.timestamp))
    return requests
```

### 5.2 WebSocket Events

#### Server → Client Events

```python
# WebSocket Event Definitions

class WebSocketEvents:
    """Real-time events sent from server to clients"""
    
    # Call Events
    CALL_STARTED = "call_started"
    CALL_ENDED = "call_ended"
    CALL_STATE_CHANGED = "call_state_changed"
    
    # Conversation Events
    STT_TRANSCRIPT = "stt_transcript"          # Real-time STT results
    TTS_STARTED = "tts_started"                # AI starts speaking
    TTS_COMPLETED = "tts_completed"            # AI finished speaking
    
    # HITL Events
    HITL_REQUESTED = "hitl_requested"          # AI needs help
    HITL_RESOLVED = "hitl_resolved"            # Human responded
    HITL_TIMEOUT = "hitl_timeout"              # No response in time
    
    # Knowledge Events
    KNOWLEDGE_ADDED = "knowledge_added"
    KNOWLEDGE_UPDATED = "knowledge_updated"
    KNOWLEDGE_DELETED = "knowledge_deleted"
    
    # System Events
    METRICS_UPDATE = "metrics_update"          # Periodic metrics
    ERROR_OCCURRED = "error_occurred"


# Example: Send STT transcript
async def on_stt_result(call_id: str, text: str, is_final: bool):
    """Broadcast STT result to connected clients"""
    await sio.emit('stt_transcript', {
        'call_id': call_id,
        'text': text,
        'is_final': is_final,
        'timestamp': datetime.now().isoformat()
    })


# Example: Send HITL request
async def request_human_help(
    call_id: str,
    question: str,
    context: dict,
    urgency: str = 'medium'
):
    """Request human operator assistance"""
    request_data = {
        'call_id': call_id,
        'question': question,
        'context': context,
        'urgency': urgency,
        'timestamp': datetime.now().isoformat()
    }
    
    # Store in Redis
    await redis_client.setex(
        f"hitl:{call_id}",
        300,  # 5 minute expiry
        json.dumps(request_data)
    )
    
    # Broadcast to operators
    await sio.emit('hitl_requested', request_data, room='operators')
    
    # Send browser notification to all connected operators
    await sio.emit('notification', {
        'title': '🆘 AI가 도움을 요청했습니다',
        'message': f'질문: {question}',
        'type': 'hitl',
        'call_id': call_id
    }, room='operators')
```

#### Client → Server Events

```python
# Client events

@sio.on('subscribe_call')
async def handle_subscribe_call(sid, data):
    """Client wants to receive updates for specific call"""
    call_id = data['call_id']
    sio.enter_room(sid, f"call_{call_id}")
    return {"success": True}


@sio.on('submit_hitl_response')
async def handle_hitl_response(sid, data):
    """Client submits HITL response"""
    # Authenticate user
    user = await get_user_from_session(sid)
    
    response = HITLResponse(**data)
    await submit_hitl_response(response, user)
    
    return {"success": True}
```

---

## 6. Data Models

### 6.1 Frontend State Models

```typescript
// types/call.ts

export interface ActiveCall {
  callId: string;
  caller: CallerInfo;
  callee: CalleeInfo;
  status: 'ringing' | 'active' | 'on-hold' | 'ending';
  isAIHandled: boolean;
  duration: number; // seconds
  currentQuestion?: string;
  aiConfidence?: number;
  needsHITL: boolean;
}

export interface ConversationMessage {
  role: 'user' | 'assistant' | 'system' | 'operator';
  content: string;
  timestamp: Date;
  isFinal: boolean; // For STT interim results
  confidence?: number;
  audioFile?: string;
}

export interface CallTranscript {
  callId: string;
  messages: ConversationMessage[];
  isSpeaking: boolean;
  currentState: 'listening' | 'thinking' | 'speaking' | 'waiting_human';
}
```

```typescript
// types/hitl.ts

export interface HITLRequest {
  callId: string;
  question: string;
  context: {
    previousMessages: ConversationMessage[];
    ragResults: SearchResult[];
    callerInfo: CallerInfo;
  };
  urgency: 'high' | 'medium' | 'low';
  timestamp: Date;
  timeoutAt: Date;
}

export interface HITLResponse {
  callId: string;
  responseText: string;
  saveToKB: boolean;
  category?: string;
  operatorId: string;
}
```

```typescript
// types/knowledge.ts

export interface KnowledgeEntry {
  id: string;
  text: string;
  category: string;
  keywords: string[];
  metadata: {
    source: 'manual' | 'hitl' | 'extracted';
    createdBy?: string;
    createdAt: Date;
    updatedAt?: Date;
    usageCount?: number;
  };
  embedding?: number[]; // Only for admin/debug
}

export interface SearchResult {
  id: string;
  text: string;
  score: number;
  metadata: Record<string, any>;
}
```

### 6.2 Backend Database Schema

```sql
-- PostgreSQL Schema for Frontend-related data

-- Users & Authentication
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    role VARCHAR(50) NOT NULL, -- admin, operator, viewer
    hashed_password VARCHAR(255) NOT NULL,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW(),
    last_login TIMESTAMP
);

CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_role ON users(role);

-- HITL History
CREATE TABLE hitl_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    call_id VARCHAR(100) NOT NULL,
    question TEXT NOT NULL,
    response TEXT NOT NULL,
    operator_id UUID REFERENCES users(id),
    confidence_before FLOAT,
    confidence_after FLOAT,
    response_time_seconds INT, -- How long operator took
    saved_to_kb BOOLEAN DEFAULT false,
    resolved_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_hitl_call_id ON hitl_history(call_id);
CREATE INDEX idx_hitl_operator ON hitl_history(operator_id);
CREATE INDEX idx_hitl_resolved_at ON hitl_history(resolved_at);

-- Call Logs (Extended)
CREATE TABLE call_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    call_id VARCHAR(100) UNIQUE NOT NULL,
    caller_uri VARCHAR(255),
    callee_uri VARCHAR(255),
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP,
    duration_seconds INT,
    is_ai_handled BOOLEAN DEFAULT false,
    ai_activated_at TIMESTAMP,
    hitl_count INT DEFAULT 0,
    avg_ai_confidence FLOAT,
    recording_path VARCHAR(500),
    transcript_path VARCHAR(500),
    status VARCHAR(50) -- completed, failed, transferred
);

CREATE INDEX idx_call_start_time ON call_logs(start_time);
CREATE INDEX idx_call_ai_handled ON call_logs(is_ai_handled);

-- Knowledge Usage Tracking
CREATE TABLE knowledge_usage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    knowledge_id VARCHAR(100) NOT NULL,
    call_id VARCHAR(100) NOT NULL,
    used_at TIMESTAMP DEFAULT NOW(),
    was_helpful BOOLEAN, -- Can be rated by operator
    confidence_score FLOAT
);

CREATE INDEX idx_knowledge_usage_kid ON knowledge_usage(knowledge_id);
CREATE INDEX idx_knowledge_usage_callid ON knowledge_usage(call_id);

-- System Metrics (Aggregated)
CREATE TABLE daily_metrics (
    date DATE PRIMARY KEY,
    total_calls INT DEFAULT 0,
    ai_handled_calls INT DEFAULT 0,
    hitl_requests INT DEFAULT 0,
    avg_response_time_ms FLOAT,
    avg_ai_confidence FLOAT,
    knowledge_base_size INT,
    total_cost_usd FLOAT
);
```

---

## 7. Real-time Communication

### 7.1 WebSocket Connection Management

```python
# backend/websocket/manager.py

from socketio import AsyncServer
import structlog

logger = structlog.get_logger(__name__)

class WebSocketManager:
    """Manages WebSocket connections and broadcasts"""
    
    def __init__(self, redis_url: str):
        self.sio = AsyncServer(
            async_mode='aiohttp',
            cors_allowed_origins='*',  # Configure in production
            logger=True,
            engineio_logger=True
        )
        
        # Redis for pub/sub across multiple servers
        self.redis_client = redis.from_url(redis_url)
        self.pubsub = self.redis_client.pubsub()
        
        self._setup_handlers()
        self._setup_pubsub()
    
    def _setup_handlers(self):
        """Setup Socket.IO event handlers"""
        
        @self.sio.event
        async def connect(sid, environ, auth):
            """Client connected"""
            # Authenticate
            token = auth.get('token')
            user = await verify_jwt_token(token)
            
            if not user:
                return False  # Reject connection
            
            # Store user info in session
            await self.sio.save_session(sid, {
                'user_id': user.id,
                'user_role': user.role,
                'user_name': user.name
            })
            
            # Join role-based room
            await self.sio.enter_room(sid, f"role_{user.role}")
            
            logger.info("websocket_connected", sid=sid, user=user.name)
            return True
        
        @self.sio.event
        async def disconnect(sid):
            """Client disconnected"""
            session = await self.sio.get_session(sid)
            logger.info("websocket_disconnected", sid=sid, user=session.get('user_name'))
        
        @self.sio.on('subscribe_call')
        async def on_subscribe_call(sid, data):
            """Subscribe to specific call updates"""
            call_id = data.get('call_id')
            await self.sio.enter_room(sid, f"call_{call_id}")
            return {'success': True, 'call_id': call_id}
        
        @self.sio.on('unsubscribe_call')
        async def on_unsubscribe_call(sid, data):
            """Unsubscribe from call updates"""
            call_id = data.get('call_id')
            await self.sio.leave_room(sid, f"call_{call_id}")
            return {'success': True}
    
    def _setup_pubsub(self):
        """Setup Redis pub/sub for multi-server broadcasting"""
        async def pubsub_handler():
            await self.pubsub.subscribe('broadcast')
            
            async for message in self.pubsub.listen():
                if message['type'] == 'message':
                    data = json.loads(message['data'])
                    await self.sio.emit(
                        data['event'],
                        data['payload'],
                        room=data.get('room')
                    )
        
        asyncio.create_task(pubsub_handler())
    
    async def broadcast_to_call(self, call_id: str, event: str, data: dict):
        """Broadcast event to all clients watching a call"""
        await self.sio.emit(event, data, room=f"call_{call_id}")
    
    async def broadcast_to_operators(self, event: str, data: dict):
        """Broadcast to all operators"""
        await self.sio.emit(event, data, room="role_operator")
    
    async def broadcast_global(self, event: str, data: dict):
        """Broadcast to all connected clients"""
        await self.sio.emit(event, data)
```

### 7.2 Frontend WebSocket Client

```typescript
// lib/websocket.ts

import { io, Socket } from 'socket.io-client';

class WebSocketClient {
  private socket: Socket | null = null;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  
  connect(token: string) {
    this.socket = io(process.env.NEXT_PUBLIC_WS_URL!, {
      auth: { token },
      transports: ['websocket', 'polling'],
      reconnection: true,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 5000
    });
    
    this.setupEventHandlers();
  }
  
  private setupEventHandlers() {
    if (!this.socket) return;
    
    this.socket.on('connect', () => {
      console.log('✅ WebSocket connected');
      this.reconnectAttempts = 0;
      toast.success('실시간 연결 성공');
    });
    
    this.socket.on('disconnect', (reason) => {
      console.warn('❌ WebSocket disconnected:', reason);
      toast.warning('연결이 끊겼습니다. 재연결 중...');
    });
    
    this.socket.on('connect_error', (error) => {
      console.error('WebSocket connect error:', error);
      this.reconnectAttempts++;
      
      if (this.reconnectAttempts >= this.maxReconnectAttempts) {
        toast.error('연결 실패. 페이지를 새로고침 해주세요.');
      }
    });
    
    // HITL Events
    this.socket.on('hitl_requested', (data: HITLRequest) => {
      // Show notification
      this.showNotification('🆘 AI가 도움을 요청했습니다', data.question);
      
      // Play alert sound
      this.playAlertSound();
      
      // Update UI
      useHITLStore.getState().addRequest(data);
    });
    
    this.socket.on('hitl_resolved', (data) => {
      toast.success(`HITL 해결됨 by ${data.operator}`);
      useHITLStore.getState().removeRequest(data.call_id);
    });
    
    // Call Events
    this.socket.on('call_started', (data: ActiveCall) => {
      useCallStore.getState().addCall(data);
    });
    
    this.socket.on('call_ended', (data) => {
      useCallStore.getState().removeCall(data.call_id);
    });
    
    // Transcript Events
    this.socket.on('stt_transcript', (data) => {
      useTranscriptStore.getState().addMessage(data);
    });
    
    this.socket.on('tts_started', (data) => {
      useCallStore.getState().updateCallState(data.call_id, 'speaking');
    });
    
    this.socket.on('tts_completed', (data) => {
      useCallStore.getState().updateCallState(data.call_id, 'listening');
    });
  }
  
  subscribeToCall(callId: string) {
    this.socket?.emit('subscribe_call', { call_id: callId });
  }
  
  unsubscribeFromCall(callId: string) {
    this.socket?.emit('unsubscribe_call', { call_id: callId });
  }
  
  submitHITLResponse(response: HITLResponse) {
    return new Promise((resolve, reject) => {
      this.socket?.emit('submit_hitl_response', response, (ack) => {
        if (ack.success) {
          resolve(ack);
        } else {
          reject(ack.error);
        }
      });
    });
  }
  
  private showNotification(title: string, body: string) {
    if ('Notification' in window && Notification.permission === 'granted') {
      new Notification(title, {
        body,
        icon: '/logo.png',
        badge: '/badge.png',
        tag: 'hitl',
        requireInteraction: true
      });
    }
  }
  
  private playAlertSound() {
    const audio = new Audio('/sounds/alert.mp3');
    audio.play().catch(console.error);
  }
  
  disconnect() {
    this.socket?.disconnect();
  }
}

export const wsClient = new WebSocketClient();
```

---

## 8. Security & Authentication

### 8.1 Authentication Flow

```python
# backend/auth/jwt.py

from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext

SECRET_KEY = os.getenv("JWT_SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
REFRESH_TOKEN_EXPIRE_DAYS = 7

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def create_access_token(user_id: str, role: str) -> str:
    """Create JWT access token"""
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode = {
        "sub": user_id,
        "role": role,
        "exp": expire,
        "type": "access"
    }
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(token: str) -> dict:
    """Verify JWT token and return payload"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(401, "Invalid token")

# Dependency for protected routes
async def get_current_user(
    authorization: str = Header(None)
) -> User:
    """Get current user from JWT token"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid authorization header")
    
    token = authorization.split(" ")[1]
    payload = verify_token(token)
    
    user = await db.fetch_one(
        "SELECT * FROM users WHERE id = $1 AND is_active = true",
        payload["sub"]
    )
    
    if not user:
        raise HTTPException(401, "User not found or inactive")
    
    return User(**user)

# Role-based access control
def require_role(allowed_roles: List[str]):
    """Decorator for role-based access control"""
    def decorator(func):
        async def wrapper(*args, current_user: User = Depends(get_current_user), **kwargs):
            if current_user.role not in allowed_roles:
                raise HTTPException(403, "Insufficient permissions")
            return await func(*args, current_user=current_user, **kwargs)
        return wrapper
    return decorator

# Usage
@router.delete("/api/knowledge/{entry_id}")
@require_role(["admin", "operator"])
async def delete_knowledge(entry_id: str, current_user: User):
    """Only admins and operators can delete knowledge"""
    ...
```

### 8.2 Frontend Auth Context

```typescript
// context/AuthContext.tsx

interface AuthContextType {
  user: User | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  isAuthenticated: boolean;
  isLoading: boolean;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  
  useEffect(() => {
    // Check for existing session
    const token = localStorage.getItem('access_token');
    if (token) {
      verifyToken(token).then(setUser).catch(logout);
    }
    setIsLoading(false);
  }, []);
  
  const login = async (email: string, password: string) => {
    const response = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password })
    });
    
    if (!response.ok) {
      throw new Error('Login failed');
    }
    
    const { access_token, user } = await response.json();
    localStorage.setItem('access_token', access_token);
    setUser(user);
    
    // Connect WebSocket
    wsClient.connect(access_token);
  };
  
  const logout = () => {
    localStorage.removeItem('access_token');
    setUser(null);
    wsClient.disconnect();
    router.push('/login');
  };
  
  return (
    <AuthContext.Provider value={{ user, login, logout, isAuthenticated: !!user, isLoading }}>
      {children}
    </AuthContext.Provider>
  );
}

// Protected Route Component
export function ProtectedRoute({ 
  children, 
  requiredRole 
}: { 
  children: React.ReactNode;
  requiredRole?: string[];
}) {
  const { user, isAuthenticated, isLoading } = useAuth();
  
  if (isLoading) {
    return <LoadingSpinner />;
  }
  
  if (!isAuthenticated) {
    return <Navigate to="/login" />;
  }
  
  if (requiredRole && !requiredRole.includes(user!.role)) {
    return <ForbiddenPage />;
  }
  
  return <>{children}</>;
}
```

---

## 9. Deployment & Infrastructure

### 9.1 Frontend Deployment (Vercel)

```yaml
# vercel.json

{
  "version": 2,
  "builds": [
    {
      "src": "package.json",
      "use": "@vercel/next"
    }
  ],
  "env": {
    "NEXT_PUBLIC_API_URL": "https://api.sippbx.example.com",
    "NEXT_PUBLIC_WS_URL": "wss://ws.sippbx.example.com"
  },
  "regions": ["icn1"]
}
```

### 9.2 Backend API Deployment (Docker)

```dockerfile
# Dockerfile for API Gateway

FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Expose ports
EXPOSE 8000 8001

# Run API + WebSocket servers
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```yaml
# docker-compose.yml (Development)

version: '3.8'

services:
  frontend:
    build: ./frontend
    ports:
      - "3000:3000"
    environment:
      - NEXT_PUBLIC_API_URL=http://localhost:8000
      - NEXT_PUBLIC_WS_URL=ws://localhost:8001
  
  api:
    build: ./backend
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://user:pass@postgres:5432/sippbx
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - postgres
      - redis
  
  websocket:
    build: ./backend
    command: python -m backend.websocket.server
    ports:
      - "8001:8001"
    environment:
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - redis
  
  postgres:
    image: postgres:15
    environment:
      - POSTGRES_DB=sippbx
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=pass
    volumes:
      - postgres_data:/var/lib/postgresql/data
  
  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data

volumes:
  postgres_data:
  redis_data:
```

---

## 10. Testing Strategy

### 10.1 Frontend Tests

```typescript
// __tests__/components/HITLResponseInterface.test.tsx

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HITLResponseInterface } from '@/components/HITLResponseInterface';

describe('HITLResponseInterface', () => {
  const mockRequest: HITLRequest = {
    callId: 'test-123',
    question: '내일 회의 시간은?',
    context: {
      previousMessages: [],
      ragResults: [],
      callerInfo: { name: 'Test User' }
    },
    urgency: 'high',
    timestamp: new Date()
  };
  
  it('renders question and context', () => {
    render(<HITLResponseInterface request={mockRequest} />);
    expect(screen.getByText('내일 회의 시간은?')).toBeInTheDocument();
  });
  
  it('submits response when button clicked', async () => {
    const mockSubmit = jest.fn();
    render(<HITLResponseInterface request={mockRequest} onSubmit={mockSubmit} />);
    
    const textarea = screen.getByPlaceholderText(/답변을 작성/);
    await userEvent.type(textarea, '내일 오후 2시입니다');
    
    const submitButton = screen.getByRole('button', { name: /전송/ });
    await userEvent.click(submitButton);
    
    await waitFor(() => {
      expect(mockSubmit).toHaveBeenCalledWith(
        expect.objectContaining({
          callId: 'test-123',
          responseText: '내일 오후 2시입니다'
        })
      );
    });
  });
});
```

### 10.2 Backend Tests

```python
# tests/test_hitl_service.py

import pytest
from backend.services.hitl import HITLService

@pytest.mark.asyncio
async def test_request_human_help():
    """Test HITL request creation"""
    service = HITLService(redis_client=redis_mock, websocket=ws_mock)
    
    await service.request_human_help(
        call_id="test-123",
        question="Test question",
        context={},
        urgency="high"
    )
    
    # Verify Redis storage
    stored = await redis_mock.get("hitl:test-123")
    assert stored is not None
    assert stored['question'] == "Test question"
    
    # Verify WebSocket emission
    assert ws_mock.emit.called
    assert ws_mock.emit.call_args[0][0] == 'hitl_requested'

@pytest.mark.asyncio
async def test_hitl_timeout():
    """Test HITL request timeout handling"""
    service = HITLService(redis_client=redis_mock, websocket=ws_mock)
    
    # Create request
    await service.request_human_help(call_id="test-123", question="Test", context={})
    
    # Simulate timeout (5 minutes)
    await asyncio.sleep(301)
    
    # Verify timeout event
    assert ws_mock.emit.called_with('hitl_timeout', {'call_id': 'test-123'})
```

---

## 11. Performance Optimization

### 11.1 Frontend Optimization

```typescript
// Lazy loading for heavy components
const LiveCallMonitor = dynamic(() => import('@/components/LiveCallMonitor'), {
  loading: () => <Skeleton className="h-96" />,
  ssr: false // Disable SSR for real-time components
});

// Virtual scrolling for large lists
import { useVirtualizer } from '@tanstack/react-virtual';

function KnowledgeList({ items }: { items: KnowledgeEntry[] }) {
  const parentRef = useRef<HTMLDivElement>(null);
  
  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 80,
    overscan: 5
  });
  
  return (
    <div ref={parentRef} style={{ height: '600px', overflow: 'auto' }}>
      <div style={{ height: `${virtualizer.getTotalSize()}px` }}>
        {virtualizer.getVirtualItems().map((virtualItem) => (
          <KnowledgeItem
            key={virtualItem.key}
            entry={items[virtualItem.index]}
            style={{
              position: 'absolute',
              top: 0,
              left: 0,
              transform: `translateY(${virtualItem.start}px)`
            }}
          />
        ))}
      </div>
    </div>
  );
}

// Debounce search input
const debouncedSearch = useDebouncedCallback((value: string) => {
  setSearchQuery(value);
}, 300);
```

### 11.2 Backend Optimization

```python
# Connection pooling
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

engine = create_async_engine(
    DATABASE_URL,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True
)

AsyncSessionLocal = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

# Redis caching for frequent queries
from functools import wraps
import hashlib

def cache_result(ttl: int = 300):
    """Decorator to cache function results in Redis"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Generate cache key
            cache_key = f"cache:{func.__name__}:{hashlib.md5(str(args).encode()).hexdigest()}"
            
            # Try to get from cache
            cached = await redis_client.get(cache_key)
            if cached:
                return json.loads(cached)
            
            # Execute function
            result = await func(*args, **kwargs)
            
            # Store in cache
            await redis_client.setex(
                cache_key,
                ttl,
                json.dumps(result, default=str)
            )
            
            return result
        return wrapper
    return decorator

# Usage
@cache_result(ttl=60)
async def get_knowledge_list():
    """Cached for 60 seconds"""
    return await vector_db.list()
```

---

## 12. Monitoring & Observability

### 12.1 Frontend Monitoring

```typescript
// lib/monitoring.ts

import * as Sentry from '@sentry/nextjs';
import { Analytics } from '@vercel/analytics/react';

// Error tracking
Sentry.init({
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
  tracesSampleRate: 0.1,
  environment: process.env.NODE_ENV
});

// Custom metrics
export function trackHITLResponse(responseTime: number) {
  if (window.gtag) {
    window.gtag('event', 'hitl_response', {
      value: responseTime,
      event_category: 'hitl'
    });
  }
}

// Performance monitoring
export function usePageLoadTime() {
  useEffect(() => {
    if (typeof window !== 'undefined' && window.performance) {
      const perfData = window.performance.timing;
      const pageLoadTime = perfData.loadEventEnd - perfData.navigationStart;
      
      console.log(`Page load time: ${pageLoadTime}ms`);
      
      // Send to analytics
      if (pageLoadTime > 3000) {
        Sentry.captureMessage(`Slow page load: ${pageLoadTime}ms`, 'warning');
      }
    }
  }, []);
}
```

### 12.2 Backend Monitoring

```python
# Prometheus metrics for frontend-specific operations

from prometheus_client import Histogram, Counter, Gauge

# HITL metrics
hitl_request_count = Counter(
    'hitl_requests_total',
    'Total HITL requests',
    ['urgency']
)

hitl_response_time = Histogram(
    'hitl_response_time_seconds',
    'Time taken for operator to respond',
    buckets=[10, 30, 60, 120, 300]
)

hitl_queue_size = Gauge(
    'hitl_queue_size',
    'Current number of pending HITL requests'
)

# Knowledge base metrics
knowledge_search_time = Histogram(
    'knowledge_search_time_seconds',
    'Vector DB search time',
    buckets=[0.01, 0.05, 0.1, 0.2, 0.5]
)

knowledge_usage_count = Counter(
    'knowledge_usage_total',
    'Knowledge entry usage count',
    ['entry_id', 'category']
)

# WebSocket metrics
websocket_connections = Gauge(
    'websocket_connections_active',
    'Active WebSocket connections',
    ['room']
)

websocket_messages_sent = Counter(
    'websocket_messages_sent_total',
    'WebSocket messages sent',
    ['event_type']
)
```

---

## 13. Roadmap & Future Enhancements

### 13.1 Phase 2 Features

1. **Advanced Analytics Dashboard**
   - Operator performance metrics
   - AI confidence trends over time
   - Cost projection and optimization

2. **Multi-language Support**
   - i18n for frontend (Korean, English)
   - Multi-language knowledge base

3. **Mobile App**
   - React Native app for operators
   - Push notifications for HITL requests
   - Voice input for responses

4. **AI Training Interface**
   - Fine-tune Gemini with custom data
   - A/B testing for different prompts
   - Feedback loop for continuous improvement

### 13.2 Phase 3 Features

1. **Advanced HITL**
   - Video call support for complex issues
   - Screen sharing with caller
   - Co-browsing capabilities

2. **Intelligent Routing**
   - Route HITL requests to specialized operators
   - Skill-based routing

3. **Proactive Knowledge Suggestions**
   - AI suggests knowledge entries to add
   - Automatic FAQ generation from calls

4. **Integration Ecosystem**
   - Slack/Teams integration for notifications
   - CRM integration (Salesforce, HubSpot)
   - Ticketing systems (Jira, Zendesk)

---

## 14. Appendix

### 14.1 API Endpoints Summary

| Endpoint | Method | Description | Auth Required |
|----------|--------|-------------|---------------|
| `/api/auth/login` | POST | User login | No |
| `/api/auth/logout` | POST | User logout | Yes |
| `/api/calls/active` | GET | Get active calls | Yes |
| `/api/calls/{id}/transcript` | GET | Get call transcript | Yes |
| `/api/knowledge` | GET | List knowledge entries | Yes |
| `/api/knowledge` | POST | Create knowledge entry | Yes (Operator+) |
| `/api/knowledge/{id}` | PUT | Update knowledge entry | Yes (Operator+) |
| `/api/knowledge/{id}` | DELETE | Delete knowledge entry | Yes (Admin) |
| `/api/hitl/queue` | GET | Get HITL queue | Yes (Operator+) |
| `/api/hitl/response` | POST | Submit HITL response | Yes (Operator+) |
| `/api/hitl/history` | GET | Get HITL history | Yes |
| `/api/metrics/dashboard` | GET | Get dashboard metrics | Yes |

### 14.2 WebSocket Events Summary

| Event | Direction | Description |
|-------|-----------|-------------|
| `call_started` | Server → Client | New call initiated |
| `call_ended` | Server → Client | Call ended |
| `stt_transcript` | Server → Client | Real-time STT result |
| `tts_started` | Server → Client | AI starts speaking |
| `tts_completed` | Server → Client | AI finished speaking |
| `hitl_requested` | Server → Client | AI needs help |
| `hitl_resolved` | Server → Client | HITL resolved |
| `hitl_timeout` | Server → Client | HITL timeout |
| `subscribe_call` | Client → Server | Subscribe to call updates |
| `submit_hitl_response` | Client → Server | Submit HITL response |

### 14.3 Environment Variables

```bash
# Frontend (.env.local)
NEXT_PUBLIC_API_URL=https://api.example.com
NEXT_PUBLIC_WS_URL=wss://ws.example.com
NEXT_PUBLIC_SENTRY_DSN=https://...
NEXT_PUBLIC_GA_ID=G-XXXXXXXXXX

# Backend (.env)
DATABASE_URL=postgresql://...
REDIS_URL=redis://...
JWT_SECRET_KEY=your-secret-key
GOOGLE_APPLICATION_CREDENTIALS=./credentials/gcp-key.json
GCP_PROJECT_ID=your-project
GEMINI_API_KEY=your-key
SENTRY_DSN=https://...
```

---

## 15. Conclusion

This frontend architecture provides a **comprehensive Human-in-the-Loop system** that:

1. ✅ **Empowers Operators** - Real-time visibility and control
2. ✅ **Enhances AI** - Human feedback improves AI over time
3. ✅ **Maintains UX** - Callers experience smooth hold → response flow
4. ✅ **Scales Efficiently** - WebSocket + Redis pub/sub architecture
5. ✅ **Secure & Reliable** - JWT auth, role-based access, error handling

The system transforms the AI voicebot from **autonomous** to **supervised**, ensuring **high-quality customer experiences** while building a **continuously improving knowledge base**.

---

**Document Status**: ✅ Ready for Implementation  
**Next Steps**: 
1. Review and approve architecture
2. Set up development environment
3. Implement Phase 1 (Core Dashboard + HITL)
4. Test with pilot operators
5. Deploy to production

**Questions?** Contact Winston, System Architect 🏗️

