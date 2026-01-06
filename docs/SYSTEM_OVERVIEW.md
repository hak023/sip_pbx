# 🏗️ AI SIP PBX System - Complete Overview

## 📊 System Architecture Map

```
┌────────────────────────────────────────────────────────────────────────┐
│                        COMPLETE SYSTEM ARCHITECTURE                     │
└────────────────────────────────────────────────────────────────────────┘

┌──────────────────────┐       ┌──────────────────────┐       ┌──────────────────────┐
│   EXTERNAL USERS     │       │   FRONTEND (NEW!)    │       │   BACKEND SERVICES   │
├──────────────────────┤       ├──────────────────────┤       ├──────────────────────┤
│                      │       │                      │       │                      │
│  📞 SIP Callers      │◄─────►│  🖥️ Web Dashboard    │◄─────►│  🔄 SIP/RTP Engine   │
│  👤 Phone Users      │  SIP  │  (Next.js)           │  WS   │  (Python asyncio)    │
│                      │       │                      │ REST  │                      │
│                      │       │  Features:           │       │  🤖 AI Orchestrator  │
│                      │       │  • Live Monitor      │◄─────►│  (Python asyncio)    │
│                      │       │  • Knowledge CRUD    │       │                      │
│                      │       │  • HITL Queue        │       │  📚 Vector DB        │
│                      │       │  • Analytics         │◄─────►│  (ChromaDB/Pinecone) │
│                      │       │                      │       │                      │
└──────────────────────┘       └──────────────────────┘       └──────┬───────────────┘
                                                                      │
                                                                      ↓
                                                            ┌──────────────────────┐
                                                            │   EXTERNAL AI APIs   │
                                                            ├──────────────────────┤
                                                            │  🎤 Google STT       │
                                                            │  🔊 Google TTS       │
                                                            │  💡 Gemini 1.5 Flash │
                                                            └──────────────────────┘
```

---

## 🎯 Key Use Cases

### 1️⃣ Normal Call (No AI)

```
Caller → PBX → Callee
        ↓
    RTP Relay (direct)
```

- Callee answers within 10 seconds
- PBX acts as B2BUA
- Low-latency RTP relay
- Call recording (optional)

### 2️⃣ AI Auto-Response (Callee No Answer)

```
Caller → PBX → [10sec timeout] → AI Orchestrator
        ↓                              ↓
    RTP Relay                      STT/TTS/LLM
                                       ↓
                                   RAG Search
                                       ↓
                                  AI Response
```

**Workflow:**
1. Callee doesn't answer in 10 seconds
2. PBX activates AI Orchestrator
3. AI: "안녕하세요, 무엇을 도와드릴까요?"
4. Real-time conversation (STT → LLM → TTS)
5. RAG-based intelligent answers
6. Call recording & knowledge extraction

### 3️⃣ Human-in-the-Loop (Low AI Confidence)

```
Caller → AI → [Low Confidence] → HITL Request
               ↓                      ↓
          Hold Music          Frontend Alert
               ↓                      ↓
          [Waiting]            Operator Types Answer
               ↓                      ↓
          LLM Refine ◄───────── Human Response
               ↓
          Final Answer → Caller
               ↓
       Save to Knowledge Base
```

**Workflow:**
1. AI can't find good answer (confidence < 0.6)
2. Caller hears: "잠시만 확인 중이니 기다려 주세요" + music
3. Frontend alerts operator (🔔 sound + notification)
4. Operator reviews context and types answer
5. AI polishes the answer with LLM
6. AI speaks final answer to caller
7. Answer saved to Vector DB for future use

---

## 📁 Component Breakdown

### Backend Components

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **SIP Endpoint** | Python asyncio | SIP signaling (INVITE, BYE, etc.) |
| **RTP Relay** | UDP sockets | Media stream relay |
| **Call Manager** | Python | Call state management |
| **AI Orchestrator** | Python asyncio | AI conversation flow |
| **STT Client** | Google Cloud | Speech-to-Text (streaming) |
| **TTS Client** | Google Cloud | Text-to-Speech (streaming) |
| **LLM Client** | Gemini 1.5 Flash | Response generation |
| **RAG Engine** | Sentence Transformers | Knowledge retrieval |
| **Vector DB** | ChromaDB/Pinecone | Embedding storage |
| **HITL Service** | Python + Redis | Human intervention logic |
| **API Gateway** | FastAPI | REST API for frontend |
| **WebSocket Server** | Socket.IO | Real-time events |

### Frontend Components

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Dashboard** | Next.js + React | Main control panel |
| **Live Monitor** | React + WebSocket | Real-time call tracking |
| **Knowledge Manager** | React + TanStack Query | Vector DB CRUD UI |
| **HITL Interface** | React | Operator response UI |
| **Analytics** | Recharts | Metrics visualization |
| **Auth** | JWT + OAuth2 | User authentication |

### Data Stores

| Store | Technology | Purpose |
|-------|-----------|---------|
| **Vector DB** | ChromaDB (dev) / Pinecone (prod) | Knowledge embeddings |
| **PostgreSQL** | PostgreSQL 15+ | User data, call logs, HITL history |
| **Redis** | Redis 7+ | Real-time state, WebSocket pub/sub |

---

## 🔄 Data Flow Examples

### Example 1: Simple Question with High Confidence

```
User: "영업시간이 언제인가요?"
  ↓
STT: "영업시간이 언제인가요?" (confidence: 0.98)
  ↓
RAG Search: [
  {text: "영업시간은 평일 9시~6시입니다", score: 0.95}
]
  ↓
LLM Input: 
  System: "간결하게 답변하세요"
  Context: "영업시간은 평일 9시~6시입니다"
  Question: "영업시간이 언제인가요?"
  ↓
LLM Output: "평일 오전 9시부터 오후 6시까지 영업합니다."
  ↓
TTS: 🔊 "평일 오전 9시부터 오후 6시까지 영업합니다."
```

**Response Time:** ~0.9 seconds

### Example 2: Complex Question with HITL

```
User: "다음 주 화요일 오후에 김대리님과 미팅 가능한가요?"
  ↓
STT: "다음 주 화요일 오후에 김대리님과 미팅 가능한가요?"
  ↓
RAG Search: [
  {text: "김대리 연락처: 010-1234-5678", score: 0.4}
]  ← Low confidence!
  ↓
HITL Trigger: confidence < 0.6
  ↓
AI: "잠시만 확인 중이니 기다려 주세요" + 🎵
  ↓
Frontend Alert: 🔔 → Operator
  ↓
Operator Context:
  - Question: "다음 주 화요일 오후에 김대리님과 미팅 가능한가요?"
  - Caller: 박과장 (010-9876-5432)
  - Previous: [conversation history]
  ↓
Operator Input: "화요일 오후 3시 가능합니다"
  ↓
LLM Refinement:
  Input: "화요일 오후 3시 가능합니다"
  Context: User asked about meeting with 김대리
  ↓
LLM Output: "확인해 드렸습니다. 다음 주 화요일 오후 3시에 
             김대리님과 미팅이 가능합니다."
  ↓
TTS: 🔊 "확인해 드렸습니다..."
  ↓
Save to KB: 
  Q: "김대리 미팅 시간"
  A: "화요일 오후 3시 가능"
```

**Response Time:** 
- HITL request: ~1 second
- Operator response: 15-30 seconds (human)
- LLM refinement + TTS: ~1 second
- **Total: ~17-32 seconds** (acceptable with hold music)

---

## 📈 Performance Metrics

### AI Response Time

| Scenario | Average | P95 | P99 |
|----------|---------|-----|-----|
| **High Confidence** | 0.9s | 1.2s | 1.5s |
| **Medium Confidence** | 1.3s | 1.8s | 2.2s |
| **HITL (with operator)** | 20s | 35s | 60s |

### Cost Estimates (100 calls/day)

| Service | Daily Cost | Monthly Cost |
|---------|-----------|--------------|
| **Gemini 1.5 Flash** | ₩46 | ₩1,400 |
| **Google STT** | ₩100 | ₩3,000 |
| **Google TTS** | ₩66 | ₩2,000 |
| **Vector DB (ChromaDB)** | ₩0 (local) | ₩0 |
| **Total** | **₩212** | **₩6,400** |

> 💡 With Gemini Pro instead of Flash: **₩23,400/month** (3.6x more expensive)

### System Capacity

| Metric | Capacity |
|--------|----------|
| **Concurrent Calls** | 100+ |
| **Concurrent AI Sessions** | 50+ |
| **WebSocket Connections** | 1,000+ |
| **API Requests** | 10,000+/min |
| **Vector DB Size** | 1M+ documents |

---

## 🔐 Security Features

### Authentication & Authorization

- **JWT Tokens** for API access
- **OAuth2** for social login
- **Role-Based Access Control** (Admin, Operator, Viewer)
- **WebSocket Authentication** via token

### Data Security

- **TLS/SSL** for all external connections
- **SRTP** for encrypted media (optional)
- **Encrypted Credentials** in environment variables
- **Database Encryption** at rest

### Privacy Compliance

- **Call Recording Consent** (configurable)
- **PII Masking** in logs
- **GDPR-compliant** data retention policies
- **Audit Logs** for all operator actions

---

## 📊 Monitoring & Observability

### Metrics (Prometheus)

**Call Metrics:**
- `active_calls_total` - Current active calls
- `call_duration_seconds` - Call duration histogram
- `ai_activated_calls_total` - AI-handled calls counter

**AI Metrics:**
- `ai_response_time_seconds` - AI response time histogram
- `ai_confidence_score` - AI confidence distribution
- `rag_search_time_seconds` - RAG search latency

**HITL Metrics:**
- `hitl_requests_total` - HITL request count
- `hitl_response_time_seconds` - Operator response time
- `hitl_queue_size` - Current HITL queue depth

**Cost Metrics:**
- `llm_tokens_used_total` - LLM token usage
- `stt_duration_seconds_total` - STT audio duration
- `tts_characters_total` - TTS character count

### Logs (structured JSON)

```json
{
  "timestamp": "2025-01-05T10:30:45.123Z",
  "level": "info",
  "event": "ai_response_time_breakdown",
  "call_id": "abc-123",
  "rag_search_ms": 75.2,
  "llm_generation_ms": 412.8,
  "tts_first_chunk_ms": 235.1,
  "total_response_ms": 923.5
}
```

### Dashboards (Grafana)

**Main Dashboard:**
- Active calls graph
- AI confidence trends
- Response time heatmap
- Cost tracking

**HITL Dashboard:**
- Queue depth over time
- Average operator response time
- Resolution rate
- Top unresolved questions

**System Health:**
- API latency
- WebSocket connections
- Database query time
- Error rates

---

## 🚀 Deployment Options

### Development

```bash
# Run all services locally
docker-compose up

# Frontend: http://localhost:3000
# API: http://localhost:8000
# WebSocket: ws://localhost:8001
```

### Production

**Option 1: Single Server**
- Ubuntu 22.04 LTS
- 8 CPU, 16GB RAM
- Docker + Docker Compose
- Nginx reverse proxy

**Option 2: Kubernetes**
- Frontend: Vercel / Netlify
- Backend: GKE / EKS
- Database: Cloud SQL / RDS
- Vector DB: Pinecone Cloud

**Option 3: Hybrid**
- Frontend: Vercel (CDN)
- Backend: On-premise VM
- AI Services: Google Cloud
- Vector DB: Self-hosted ChromaDB

---

## 📚 Documentation Index

### Core Docs

| Document | Description |
|----------|-------------|
| **[README.md](../README.md)** | Project overview & quick start |
| **[ai-voicebot-architecture.md](ai-voicebot-architecture.md)** | Complete AI system design |
| **[frontend-architecture.md](frontend-architecture.md)** | Frontend & HITL detailed design |

### Technical Specs

| Document | Description |
|----------|-------------|
| **[gemini-model-comparison.md](gemini-model-comparison.md)** | Flash vs Pro analysis |
| **[ai-response-time-analysis.md](ai-response-time-analysis.md)** | Performance breakdown |
| **[google-api-setup.md](google-api-setup.md)** | Google Cloud API setup guide |

### Guides

| Document | Description |
|----------|-------------|
| **[AI_QUICKSTART.md](AI_QUICKSTART.md)** | 15-minute setup guide |
| **[USER_MANUAL.md](USER_MANUAL.md)** | End-user guide |
| **[DEBUGGING.md](DEBUGGING.md)** | Troubleshooting |

---

## 🎯 Roadmap

### ✅ Phase 1: Core AI (Completed)
- Basic AI auto-response
- STT/TTS/LLM integration
- RAG knowledge retrieval
- Call recording

### 🚧 Phase 2: Frontend & HITL (In Progress)
- Web dashboard
- Real-time monitoring
- Knowledge base management
- Human-in-the-loop system

### 📋 Phase 3: Advanced Features (Planned)
- Mobile app for operators
- Multi-language support
- Advanced analytics
- CRM integration
- A/B testing framework

### 🌟 Phase 4: Enterprise (Future)
- Multi-tenant support
- SSO integration
- Custom AI model training
- White-label frontend
- Enterprise SLA

---

## 🤝 Contributing

We welcome contributions! Areas that need help:

1. **Frontend Components** - React UI improvements
2. **AI Prompt Engineering** - Better LLM prompts
3. **Testing** - Unit tests, integration tests
4. **Documentation** - Tutorials, examples
5. **Translations** - i18n support

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

---

## 📞 Support

- **Issues:** [GitHub Issues](https://github.com/hak023/sip_pbx/issues)
- **Discussions:** [GitHub Discussions](https://github.com/hak023/sip_pbx/discussions)
- **Email:** hak023@example.com

---

## 📄 License

MIT License - see [LICENSE](../LICENSE)

---

**Built with ❤️ by Winston (Architect) & Team**

*Last Updated: 2025-01-05*

