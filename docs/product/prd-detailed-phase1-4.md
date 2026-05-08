# SmartPBX AI - Detailed Product Requirements Document
## Active RAG 기반 지능형 통화 응대 시스템 - Phase 1-4 상세 요구사항

**문서 버전**: v2.1  
**작성일**: 2026-01-30  
**최종 갱신**: 2026-05-08  
**작성자**: Product Team  
**상태**: Living — 세부 FR·Acceptance Criteria는 구현·리포트와 함께 주기적으로 재검토

---

## 📋 목차

1. [문서 개요](#문서-개요)
2. [Phase 1: Active RAG 기반 지식 자동 구축](#phase-1-active-rag-기반-지식-자동-구축)
3. [Phase 2: AI 기반 Dynamic ARS](#phase-2-ai-기반-dynamic-ars)
4. [Phase 3: HITL + Shadowing Mode](#phase-3-hitl--shadowing-mode)
5. [Phase 4: Agentic AI + Multi-Agent](#phase-4-agentic-ai--multi-agent)
6. [Cross-cutting Concerns](#cross-cutting-concerns)
7. [부록: User Story 템플릿](#부록-user-story-템플릿)

---

## 문서 개요

### 목적
본 문서는 SmartPBX AI의 Phase 1-4에 대한 상세 기능 요구사항과 User Story를 정의합니다. 각 Phase는 독립적으로 배포 가능하며(Incrementally Deliverable), 이전 Phase의 기능을 확장합니다.

### 범위
- **In Scope**: Phase 1-4의 모든 AI 관련 기능 (Active RAG, AI-ARS, HITL, Agentic AI)
- **Out of Scope**: 기본 SIP PBX 기능 (이미 구현 완료, 별도 PRD 참조)

### 구현 정합 (2026-05)

본 문서의 체크리스트·User Story는 **요구사항 정의**이다. **실제 구현 여부**는 [prd.md](./prd.md)의 **AI 기능 구현 스냅샷**, [technical-architecture.md](../architecture/technical-architecture.md), 월별 [reports/README.md](../reports/README.md)를 우선한다. 상용 배포·WTIMS 연동 등 **타깻 아키텍처**는 [production-deployment-architecture.md](../architecture/production-deployment-architecture.md)를 본다.

### 용어 정의
| 용어 | 정의 |
|------|------|
| **Active RAG** | 실시간으로 통화 데이터를 학습하는 Retrieval Augmented Generation |
| **HITL** | Human-In-The-Loop, 운영자가 AI 학습에 직접 개입하는 시스템 |
| **Shadowing Mode** | AI가 상담원에게 실시간 답변 가이드를 제공하는 모드 |
| **Agentic AI** | 자율적으로 도구를 사용하고 결정을 내리는 AI Agent |
| **Confidence Score** | AI 답변의 신뢰도 점수 (0-100%) |
| **Diarization** | 통화 중 화자(발신자/수신자) 구분 |

---

## Phase 1: Active RAG 기반 지식 자동 구축

### Epic 1.1: 통화 데이터 자동 수집 및 저장

#### 개요
모든 통화는 STT로 텍스트 변환되고, 화자 분리(Diarization)를 통해 발신자/수신자를 구분하여 Vector Database에 자동 저장됩니다.

---

#### Feature 1.1.1: 통화 Transcript 실시간 생성

**Feature ID**: `F1.1.1`  
**Priority**: P0 (Must Have)  
**Complexity**: Medium  
**Estimated Story Points**: 8

##### Functional Requirements

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| FR-1.1.1-01 | 통화 시작 시 STT 파이프라인 자동 활성화 | ✅ SIP INVITE 수신 후 1초 이내 STT 시작 |
| FR-1.1.1-02 | Real-time STT (스트리밍 모드) 지원 | ✅ RTP 패킷 수신 즉시 텍스트 변환 (지연 <500ms) |
| FR-1.1.1-03 | 통화 종료 시 Full Transcript 생성 | ✅ BYE 메시지 후 5초 이내 완전한 텍스트 파일 생성 |
| FR-1.1.1-04 | Diarization (화자 분리) 자동 적용 | ✅ Speaker 1 = Caller, Speaker 2 = Callee로 자동 분류 |
| FR-1.1.1-05 | Transcript 메타데이터 포함 | ✅ Call-ID, 타임스탬프, 통화 시간, 참여자 정보 포함 |

##### Non-Functional Requirements

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-1.1.1-01 | STT Latency (실시간 모드) | < 500ms |
| NFR-1.1.1-02 | STT 정확도 (WER) | < 10% (한국어) |
| NFR-1.1.1-03 | 동시 처리 가능 통화 수 | 100개 이상 |
| NFR-1.1.1-04 | Transcript 저장 실패율 | < 0.1% |

##### User Stories

**US-1.1.1-01**: 실시간 통화 텍스트 변환
```gherkin
As a: 시스템 관리자
I want to: 모든 통화가 자동으로 텍스트로 변환되기를 원합니다
So that: 통화 내용을 검색하고 분석할 수 있습니다

Acceptance Criteria:
- Given: 고객이 1003번으로 전화를 걸 때
- When: 통화가 연결되고 대화가 시작되면
- Then: 실시간으로 음성이 텍스트로 변환되어야 합니다
- And: 화자가 자동으로 구분되어야 합니다 (Caller vs. Callee)
- And: 변환된 텍스트는 500ms 이내에 생성되어야 합니다

Example:
  Input (Audio): "안녕하세요, 주문 조회하려고 합니다"
  Output (Text): "[Caller] 안녕하세요, 주문 조회하려고 합니다"
  Timestamp: 2026-01-30T10:00:01.500Z
```

**US-1.1.1-02**: 통화 종료 후 Complete Transcript 생성
```gherkin
As a: 고객센터 운영자
I want to: 통화 종료 후 전체 대화 내용을 텍스트 파일로 받기를 원합니다
So that: 통화 내용을 리뷰하고 품질을 평가할 수 있습니다

Acceptance Criteria:
- Given: 고객과 상담원의 통화가 종료될 때
- When: BYE 메시지가 전송되면
- Then: 5초 이내에 전체 통화 Transcript가 생성되어야 합니다
- And: Transcript는 다음 정보를 포함해야 합니다:
  * Call-ID
  * 통화 시작/종료 시간
  * 통화 길이
  * 발신자/수신자 정보
  * 타임스탬프가 포함된 전체 대화 내용
- And: 파일은 recordings/{call_id}/transcript.txt 경로에 저장되어야 합니다

Example Transcript:
---
Call ID: abc123
Start Time: 2026-01-30T10:00:00Z
End Time: 2026-01-30T10:05:30Z
Duration: 330 seconds
Caller: 1003 (010-1234-5678)
Callee: 1004 (상담원 김철수)

[00:01] [Caller] 안녕하세요, 주문 조회하려고 합니다
[00:03] [Callee] 안녕하세요. 주문번호 알려주시겠어요?
[00:06] [Caller] 주문번호는 2024-0130-001입니다
[00:10] [Callee] 확인해보겠습니다. 잠시만 기다려주세요
...
---
```

##### Technical Design

**Architecture**:
```
[SIP Call] → [RTP Stream] → [STT Pipeline]
                                  ↓
                         [Diarization Engine]
                                  ↓
                         [Transcript Builder]
                                  ↓
                    [File Storage (recordings/)]
```

**Components**:
1. **STT Processor**: Google Cloud Speech-to-Text (Streaming API)
2. **Diarization**: Google Speech Diarization (2 speakers)
3. **Transcript Builder**: Python asyncio-based processor
4. **Storage**: Local file system + S3 backup (optional)

**API Dependencies**:
- Google Cloud Speech-to-Text API v2
- 인증: Service Account (gcp-key.json)
- Quota: 1,000 minutes/day (Free tier)

##### Testing Strategy

**Unit Tests**:
- [ ] STT 파이프라인 초기화 테스트
- [ ] Diarization 정확도 테스트 (Ground Truth 데이터 사용)
- [ ] Transcript 파일 생성 및 저장 테스트

**Integration Tests**:
- [ ] End-to-end 통화 → Transcript 생성 테스트
- [ ] 동시 100통화 처리 부하 테스트
- [ ] STT 서비스 장애 시 Fallback 테스트

**Performance Tests**:
- [ ] STT Latency 측정 (target: <500ms)
- [ ] Throughput 측정 (target: 100 concurrent calls)

##### Dependencies
- ✅ SIP PBX Core (이미 구현 완료)
- ✅ RTP Relay (이미 구현 완료)
- ⬜ Google Cloud 계정 설정
- ⬜ Service Account 권한 설정

---

#### Feature 1.1.2: 화자 분리 및 역할 태깅

**Feature ID**: `F1.1.2`  
**Priority**: P0 (Must Have)  
**Complexity**: Medium  
**Estimated Story Points**: 5

##### Functional Requirements

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| FR-1.1.2-01 | 통화 중 화자 자동 구분 (Caller vs. Callee) | ✅ Diarization 정확도 > 95% |
| FR-1.1.2-02 | 역할 자동 매핑 (발신자 → Caller, 수신자 → Callee) | ✅ SIP 헤더의 From/To 필드 기반 자동 분류 |
| FR-1.1.2-03 | 각 발화(Utterance)에 화자 정보 태깅 | ✅ 모든 텍스트에 [Caller] 또는 [Callee] 태그 추가 |
| FR-1.1.2-04 | 3자 통화 지원 (Transfer 시나리오) | ✅ Speaker 3 추가 시 자동 감지 및 태깅 |

##### User Stories

**US-1.1.2-01**: 화자 자동 구분
```gherkin
As a: AI 시스템
I want to: 통화 중 누가 말하고 있는지 자동으로 구분하고 싶습니다
So that: RAG 검색 시 "고객이 질문"과 "상담원이 답변"을 정확히 구분할 수 있습니다

Acceptance Criteria:
- Given: 고객과 상담원이 대화 중일 때
- When: 화자가 바뀌면
- Then: 시스템은 자동으로 화자를 인식해야 합니다
- And: 각 발화에 [Caller] 또는 [Callee] 태그를 붙여야 합니다
- And: 화자 구분 정확도는 95% 이상이어야 합니다

Example:
  Input Audio 1: "배송은 언제 도착하나요?"
  Output: [Caller] 배송은 언제 도착하나요?
  
  Input Audio 2: "2일 이내에 도착 예정입니다"
  Output: [Callee] 2일 이내에 도착 예정입니다
```

##### Technical Design

**Diarization Flow**:
```python
# Google Speech Diarization 설정
diarization_config = speech.SpeakerDiarizationConfig(
    enable_speaker_diarization=True,
    min_speaker_count=2,
    max_speaker_count=3  # Transfer 지원
)

# 화자 매핑
speaker_map = {
    "speaker_0": "Caller",  # From SIP header
    "speaker_1": "Callee",  # To SIP header
    "speaker_2": "Agent_2"  # Transfer 시
}
```

---

### Epic 1.2: Vector Database 통합 및 지식 저장

#### Feature 1.2.1: Transcript → Knowledge Extraction

**Feature ID**: `F1.2.1`  
**Priority**: P0 (Must Have)  
**Complexity**: High  
**Estimated Story Points**: 13

##### Functional Requirements

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| FR-1.2.1-01 | Transcript에서 Q&A 쌍 자동 추출 | ✅ LLM 기반 자동 추출 (Gemini 2.5 Flash) |
| FR-1.2.1-02 | 의미 기반 Chunking (Semantic Chunking) | ✅ 대화 맥락 유지하며 512 tokens 이하로 분할 |
| FR-1.2.1-03 | 메타데이터 자동 태깅 | ✅ 문의 유형, 감정, 해결 여부 자동 분류 |
| FR-1.2.1-04 | 중복 제거 (Deduplication) | ✅ Embedding 유사도 > 0.95인 경우 중복으로 처리 |
| FR-1.2.1-05 | 저품질 데이터 필터링 | ✅ Transcript 품질 점수 < 0.6인 경우 제외 |

##### User Stories

**US-1.2.1-01**: Q&A 자동 추출
```gherkin
As a: 지식 관리 시스템
I want to: 통화 Transcript에서 질문과 답변을 자동으로 추출하고 싶습니다
So that: 향후 유사한 질문에 바로 답변할 수 있습니다

Acceptance Criteria:
- Given: 통화 Transcript가 생성되었을 때
- When: Knowledge Extraction 파이프라인이 실행되면
- Then: 의미있는 Q&A 쌍이 추출되어야 합니다
- And: 각 Q&A는 다음 정보를 포함해야 합니다:
  * Question (고객 질문)
  * Answer (상담원 답변)
  * Context (대화 맥락)
  * Metadata (문의 유형, 해결 여부)
- And: 추출률은 통화당 평균 3개 이상이어야 합니다

Example:
  Input Transcript:
    [Caller] 배송은 언제 도착하나요?
    [Callee] 주문번호 알려주시겠어요?
    [Caller] 2024-0130-001입니다
    [Callee] 확인해보니 내일 도착 예정입니다
  
  Output Q&A:
    {
      "question": "배송은 언제 도착하나요?",
      "answer": "주문번호 2024-0130-001 기준, 내일 도착 예정입니다",
      "context": "배송 조회 문의",
      "metadata": {
        "category": "delivery_inquiry",
        "resolved": true,
        "sentiment": "neutral"
      }
    }
```

##### Technical Design

**Knowledge Extraction Pipeline**:
```python
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.prompts import PromptTemplate

# 1. Semantic Chunking
splitter = RecursiveCharacterTextSplitter(
    chunk_size=512,
    chunk_overlap=50,
    separators=["\n[Caller]", "\n[Callee]"]  # 화자 전환 기준
)

# 2. Q&A Extraction (LLM)
extraction_prompt = PromptTemplate(
    input_variables=["transcript"],
    template="""
    다음 통화 Transcript에서 고객의 질문과 상담원의 답변을 추출하세요.
    
    Transcript:
    {transcript}
    
    Output (JSON):
    {{
      "qa_pairs": [
        {{
          "question": "고객 질문",
          "answer": "상담원 답변",
          "category": "문의 유형",
          "resolved": true/false
        }}
      ]
    }}
    """
)

# 3. Metadata Tagging
categories = ["배송", "환불", "교환", "상품문의", "기타"]
sentiment_analyzer = pipeline("sentiment-analysis", model="beomi/KcBERT")
```

---

#### Feature 1.2.2: Vector Database 저장

**Feature ID**: `F1.2.2`  
**Priority**: P0 (Must Have)  
**Complexity**: Medium  
**Estimated Story Points**: 8

##### Functional Requirements

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| FR-1.2.2-01 | Embedding 생성 (OpenAI text-embedding-3-large) | ✅ Embedding dimension: 3072 |
| FR-1.2.2-02 | Vector DB에 자동 저장 (Pinecone or Qdrant) | ✅ 저장 성공률 > 99.9% |
| FR-1.2.2-03 | 메타데이터와 함께 저장 | ✅ Call-ID, 날짜, 카테고리, 감정 등 포함 |
| FR-1.2.2-04 | 인덱스 자동 업데이트 | ✅ 저장 후 3초 이내 검색 가능 |
| FR-1.2.2-05 | Backup 및 복구 기능 | ✅ 일일 자동 백업, PITR 지원 |

##### User Stories

**US-1.2.2-01**: 지식 자동 저장
```gherkin
As a: 지식 관리 시스템
I want to: 추출한 Q&A를 Vector Database에 자동으로 저장하고 싶습니다
So that: AI가 유사한 질문에 빠르게 답변할 수 있습니다

Acceptance Criteria:
- Given: Q&A가 추출되었을 때
- When: Vector DB 저장 프로세스가 실행되면
- Then: 각 Q&A는 Embedding으로 변환되어야 합니다
- And: Vector DB에 저장되어야 합니다
- And: 메타데이터가 함께 저장되어야 합니다
- And: 저장 후 3초 이내에 검색 가능해야 합니다

Example:
  Input Q&A:
    question: "배송은 언제 도착하나요?"
    answer: "주문번호 기준, 2일 이내 도착 예정입니다"
  
  Process:
    1. Embedding 생성: [0.123, -0.456, ..., 0.789] (3072 dim)
    2. Metadata 준비:
       {
         "call_id": "abc123",
         "date": "2026-01-30",
         "category": "delivery",
         "resolved": true
       }
    3. Vector DB 저장: Pinecone.upsert(...)
  
  Result:
    ✅ Stored in Pinecone namespace: "knowledge-base"
    ✅ Index updated
    ✅ Searchable in 3 seconds
```

##### Technical Design

**Vector DB Selection**:
| Criteria | Pinecone | Qdrant | Decision |
|----------|----------|--------|----------|
| Performance | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | Pinecone |
| Cost | $70/month | Free (self-hosted) | Qdrant (초기) |
| Scalability | Managed | Self-managed | Pinecone (장기) |
| **Decision** | - | ✅ | **Qdrant (Phase 1), Pinecone (Phase 2+)** |

**Implementation**:
```python
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

# Qdrant Client 초기화
client = QdrantClient(host="localhost", port=6333)

# Collection 생성 (초기 1회)
client.create_collection(
    collection_name="knowledge_base",
    vectors_config=VectorParams(size=3072, distance=Distance.COSINE)
)

# Vector 저장
def store_qa_pair(qa: dict, embedding: list):
    point = PointStruct(
        id=qa["id"],
        vector=embedding,
        payload={
            "question": qa["question"],
            "answer": qa["answer"],
            "call_id": qa["call_id"],
            "date": qa["date"],
            "category": qa["category"],
            "resolved": qa["resolved"]
        }
    )
    client.upsert(collection_name="knowledge_base", points=[point])
```

---

### Epic 1.3: RAG Retrieval 엔진

#### Feature 1.3.1: Semantic Search

**Feature ID**: `F1.3.1`  
**Priority**: P0 (Must Have)  
**Complexity**: High  
**Estimated Story Points**: 13

##### Functional Requirements

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| FR-1.3.1-01 | 고객 질문을 Embedding으로 변환 | ✅ 변환 시간 < 200ms |
| FR-1.3.1-02 | Vector DB에서 Top-K 유사 문서 검색 | ✅ K=5, 검색 시간 < 100ms |
| FR-1.3.1-03 | Reranking (재순위화) | ✅ Cohere Rerank or Cross-encoder 사용 |
| FR-1.3.1-04 | Confidence Score 계산 | ✅ Similarity score > 0.7이면 "High confidence" |
| FR-1.3.1-05 | 검색 결과 없을 시 Fallback | ✅ "죄송합니다, 관련 정보를 찾지 못했습니다" 반환 |

##### User Stories

**US-1.3.1-01**: 유사 질문 검색
```gherkin
As a: AI 시스템
I want to: 고객의 질문과 유사한 과거 Q&A를 찾고 싶습니다
So that: 빠르고 정확하게 답변할 수 있습니다

Acceptance Criteria:
- Given: 고객이 "언제 도착하나요?"라고 질문할 때
- When: RAG Retrieval 엔진이 실행되면
- Then: Vector DB에서 유사한 질문들을 찾아야 합니다
- And: Top 5 결과를 반환해야 합니다
- And: 각 결과는 유사도 점수를 포함해야 합니다
- And: 총 처리 시간은 300ms 이하여야 합니다

Example:
  Input Query: "언제 도착하나요?"
  
  Process:
    1. Query Embedding: [0.111, -0.222, ..., 0.333]
    2. Vector Search (Top 5):
       - Result 1: "배송은 언제 도착하나요?" (similarity: 0.95)
       - Result 2: "주문한 상품 언제 받을 수 있나요?" (similarity: 0.92)
       - Result 3: "배송 예정일 알려주세요" (similarity: 0.88)
       - Result 4: "배송 조회하고 싶어요" (similarity: 0.75)
       - Result 5: "배송 상태 확인 방법" (similarity: 0.72)
    3. Reranking (optional)
    4. Return Top 3 with answers
  
  Output:
    [
      {
        "question": "배송은 언제 도착하나요?",
        "answer": "주문번호 기준, 2일 이내 도착 예정입니다",
        "confidence": 0.95,
        "source_call_id": "xyz789"
      },
      ...
    ]
  
  Performance:
    - Embedding: 150ms
    - Vector Search: 80ms
    - Reranking: 50ms
    - Total: 280ms ✅
```

##### Technical Design

**RAG Pipeline**:
```python
from langchain.embeddings import OpenAIEmbeddings
from qdrant_client import QdrantClient

class RAGRetriever:
    def __init__(self):
        self.embeddings = OpenAIEmbeddings(model="text-embedding-3-large")
        self.vector_db = QdrantClient(host="localhost", port=6333)
    
    async def search(self, query: str, top_k: int = 5):
        # 1. Query Embedding
        query_vector = await self.embeddings.aembed_query(query)
        
        # 2. Vector Search
        results = self.vector_db.search(
            collection_name="knowledge_base",
            query_vector=query_vector,
            limit=top_k,
            score_threshold=0.7  # 최소 유사도
        )
        
        # 3. Confidence Score 계산
        scored_results = []
        for result in results:
            confidence = self._calculate_confidence(result.score)
            scored_results.append({
                "question": result.payload["question"],
                "answer": result.payload["answer"],
                "confidence": confidence,
                "metadata": result.payload
            })
        
        return scored_results
    
    def _calculate_confidence(self, similarity: float) -> float:
        """
        Confidence mapping:
        - similarity > 0.9: High (90-100%)
        - similarity 0.7-0.9: Medium (70-90%)
        - similarity < 0.7: Low (<70%)
        """
        return min(similarity * 100, 100)
```

---

## Phase 2: AI 기반 Dynamic ARS

### Epic 2.1: Natural Language IVR

#### Feature 2.1.1: Intent Classification

**Feature ID**: `F2.1.1`  
**Priority**: P0 (Must Have)  
**Complexity**: High  
**Estimated Story Points**: 13

##### Functional Requirements

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| FR-2.1.1-01 | 고객 발화에서 Intent 자동 추출 | ✅ LLM 기반 분류 (Gemini 2.5 Flash) |
| FR-2.1.1-02 | 주요 Intent 지원 | ✅ 배송 조회, 환불, 교환, 상품 문의, 상담원 연결 등 |
| FR-2.1.1-03 | Multi-intent 지원 | ✅ "환불하고 재주문하고 싶어요" → [환불, 주문] 2개 Intent |
| FR-2.1.1-04 | Intent Confidence Score | ✅ 점수 < 0.7이면 확인 질문 ("~하시는 건가요?") |
| FR-2.1.1-05 | Fallback Intent | ✅ 이해 못할 시 "상담원 연결" Intent로 전환 |

##### User Stories

**US-2.1.1-01**: 고객 의도 자동 파악
```gherkin
As a: AI IVR 시스템
I want to: 고객이 무엇을 원하는지 자동으로 파악하고 싶습니다
So that: 적절한 서비스로 연결하거나 직접 답변할 수 있습니다

Acceptance Criteria:
- Given: 고객이 자연어로 말할 때 (예: "배송 조회하고 싶어요")
- When: Intent Classification이 실행되면
- Then: 고객의 의도를 정확히 분류해야 합니다
- And: Confidence Score를 함께 반환해야 합니다
- And: 처리 시간은 500ms 이하여야 합니다

Example 1 - Single Intent:
  Input: "배송 조회하고 싶어요"
  Output:
    {
      "intents": ["delivery_tracking"],
      "confidence": 0.95,
      "next_action": "ask_order_number"
    }

Example 2 - Multi Intent:
  Input: "환불하고 재주문하고 싶어요"
  Output:
    {
      "intents": ["refund", "reorder"],
      "confidence": 0.88,
      "next_action": "clarify_priority"  # 우선순위 확인
    }

Example 3 - Low Confidence:
  Input: "그거 있잖아요, 그거..."
  Output:
    {
      "intents": ["unknown"],
      "confidence": 0.35,
      "next_action": "clarification_question"  # "무엇을 도와드릴까요?"
    }
```

##### Technical Design

**Intent Classification Pipeline**:
```python
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.prompts import ChatPromptTemplate

# LLM 초기화
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.3,  # 일관성 중시
    max_output_tokens=150
)

# Intent Classification Prompt
intent_prompt = ChatPromptTemplate.from_template("""
당신은 고객 센터 IVR 시스템입니다.
고객의 발화에서 의도(Intent)를 분류하세요.

가능한 Intent:
- delivery_tracking: 배송 조회
- refund: 환불
- exchange: 교환
- product_inquiry: 상품 문의
- order_status: 주문 상태 확인
- agent_request: 상담원 연결 요청
- unknown: 알 수 없음

고객 발화: {user_input}

Output (JSON):
{{
  "intents": ["intent1", "intent2"],  # 다중 가능
  "confidence": 0.0~1.0,
  "reasoning": "분류 이유"
}}
""")

# Intent Classification 함수
async def classify_intent(user_input: str):
    response = await llm.ainvoke(intent_prompt.format(user_input=user_input))
    intent_data = json.loads(response.content)
    return intent_data
```

---

#### Feature 2.1.2: Context-aware Dialog Management

**Feature ID**: `F2.1.2`  
**Priority**: P0 (Must Have)  
**Complexity**: High  
**Estimated Story Points**: 21

##### Functional Requirements

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| FR-2.1.2-01 | 대화 컨텍스트 유지 (최대 10턴) | ✅ 이전 발화 기억하고 참조 |
| FR-2.1.2-02 | Slot Filling (필요한 정보 수집) | ✅ 주문번호, 이름, 전화번호 등 자동 수집 |
| FR-2.1.2-03 | Dynamic Flow (상황에 따라 다음 질문 변경) | ✅ "주문번호 모름" → "이름과 전화번호로 찾기" |
| FR-2.1.2-04 | Error Recovery (오인식 시 재확인) | ✅ "1234라고 하셨나요?" 확인 질문 |
| FR-2.1.2-05 | Early Exit (언제든 상담원 연결) | ✅ "상담원" 키워드 감지 시 즉시 전환 |

##### User Stories

**US-2.1.2-01**: 문맥 이해 대화
```gherkin
As a: 고객
I want to: AI가 이전 대화를 기억하고 자연스럽게 대화하기를 원합니다
So that: 매번 처음부터 설명하지 않아도 됩니다

Acceptance Criteria:
- Given: 고객이 "배송 조회하고 싶어요"라고 말한 후
- When: AI가 "주문번호 알려주세요"라고 묻고
- And: 고객이 "1234"라고 답하면
- Then: AI는 이전 대화를 기억하고 "1234번 주문 확인해드릴게요"라고 답해야 합니다
- And: 고객이 "그거 언제 도착해?"라고 물으면
- Then: AI는 "그거 = 1234번 주문"임을 이해하고 답변해야 합니다

Example Dialog:
  Turn 1:
    Customer: "배송 조회하고 싶어요"
    AI: "주문번호 알려주시겠어요?"
    Context: {intent: "delivery_tracking", slots: {}}
  
  Turn 2:
    Customer: "2024-0130-001이요"
    AI: "2024-0130-001번 주문 확인해드릴게요. 잠시만 기다려주세요"
    Context: {intent: "delivery_tracking", slots: {order_number: "2024-0130-001"}}
  
  Turn 3:
    Customer: "언제 도착해요?"
    AI: (Context 참조) "2024-0130-001번 주문은 내일 도착 예정입니다"
    Context: {intent: "delivery_tracking", slots: {order_number: "2024-0130-001"}}
```

**US-2.1.2-02**: 필요한 정보 자동 수집
```gherkin
As a: AI IVR 시스템
I want to: 고객에게 필요한 정보를 순서대로 물어보고 싶습니다
So that: 완전한 정보를 수집하여 서비스를 제공할 수 있습니다

Acceptance Criteria:
- Given: 고객이 "환불하고 싶어요"라고 말할 때
- When: Slot Filling이 시작되면
- Then: 필요한 정보를 하나씩 물어봐야 합니다:
  * Step 1: 주문번호
  * Step 2: 환불 사유
  * Step 3: 환불 방법 (계좌 or 카드)
- And: 이미 제공된 정보는 다시 묻지 않아야 합니다
- And: 모든 정보 수집 완료 시 환불 프로세스 시작

Example:
  Required Slots: [order_number, reason, refund_method]
  
  Turn 1:
    Customer: "환불하고 싶어요"
    AI: "주문번호 알려주시겠어요?"
    Slots: {}
  
  Turn 2:
    Customer: "2024-0130-001이요. 상품이 파손되어서요"
    AI: (2개 slot 동시 수집) "환불 방법은 어떻게 하시겠어요? 계좌 입금 또는 카드 취소 중 선택해주세요"
    Slots: {order_number: "2024-0130-001", reason: "파손"}
  
  Turn 3:
    Customer: "계좌로 부탁드려요"
    AI: "환불 신청이 완료되었습니다. 3-5 영업일 내 입금 예정입니다"
    Slots: {order_number: "2024-0130-001", reason: "파손", refund_method: "계좌"}
    Action: submit_refund_request()
```

##### Technical Design

**Dialog State Management**:
```python
from typing import Dict, List
from dataclasses import dataclass

@dataclass
class DialogContext:
    session_id: str
    intent: str
    slots: Dict[str, any]  # 수집된 정보
    required_slots: List[str]  # 필요한 정보
    turn_count: int
    history: List[Dict]  # 대화 이력
    
    def is_complete(self) -> bool:
        """모든 필수 정보가 수집되었는지 확인"""
        return all(slot in self.slots for slot in self.required_slots)
    
    def next_slot(self) -> str:
        """다음에 물어볼 정보"""
        for slot in self.required_slots:
            if slot not in self.slots:
                return slot
        return None

# Slot Definitions (Intent별)
SLOT_CONFIGS = {
    "delivery_tracking": {
        "required": ["order_number"],
        "optional": []
    },
    "refund": {
        "required": ["order_number", "reason", "refund_method"],
        "optional": ["account_number"]
    },
    "exchange": {
        "required": ["order_number", "reason", "new_product"],
        "optional": []
    }
}

# Dialog Manager
class DialogManager:
    def __init__(self):
        self.contexts: Dict[str, DialogContext] = {}
    
    async def process_turn(self, session_id: str, user_input: str):
        context = self.contexts.get(session_id)
        if not context:
            # 새 대화 시작
            intent = await classify_intent(user_input)
            context = self._create_context(session_id, intent)
        
        # Slot 추출
        extracted_slots = await self._extract_slots(user_input, context)
        context.slots.update(extracted_slots)
        context.turn_count += 1
        
        # 다음 액션 결정
        if context.is_complete():
            response = await self._execute_action(context)
        else:
            next_slot = context.next_slot()
            response = await self._ask_for_slot(next_slot)
        
        # 대화 이력 저장
        context.history.append({
            "turn": context.turn_count,
            "user": user_input,
            "ai": response
        })
        
        return response
```

---

#### Feature 2.1.3: Tool Calling Integration

**Feature ID**: `F2.1.3`  
**Priority**: P1 (Should Have)  
**Complexity**: High  
**Estimated Story Points**: 13

##### Functional Requirements

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| FR-2.1.3-01 | CRM API 통합 (고객 정보 조회) | ✅ 주문번호로 주문 정보 조회 가능 |
| FR-2.1.3-02 | ERP API 통합 (재고/배송 정보) | ✅ 실시간 배송 상태 조회 가능 |
| FR-2.1.3-03 | Tool Registry 관리 | ✅ 새 Tool 동적 추가 가능 |
| FR-2.1.3-04 | 권한 관리 | ✅ Tool별 읽기/쓰기 권한 설정 |
| FR-2.1.3-05 | Error Handling | ✅ API 장애 시 Fallback 응답 |

##### User Stories

**US-2.1.3-01**: 실시간 정보 조회
```gherkin
As a: AI IVR 시스템
I want to: 외부 시스템의 실시간 정보를 조회하고 싶습니다
So that: 고객에게 정확한 최신 정보를 제공할 수 있습니다

Acceptance Criteria:
- Given: 고객이 "배송 상태 알려주세요"라고 요청할 때
- When: 주문번호를 수집한 후
- Then: ERP API를 호출하여 실시간 배송 상태를 조회해야 합니다
- And: 조회 결과를 자연어로 변환하여 답변해야 합니다
- And: API 호출 시간은 2초 이내여야 합니다

Example:
  Customer: "배송 상태 알려주세요"
  AI: "주문번호 알려주시겠어요?"
  Customer: "2024-0130-001"
  AI: (Tool Call: get_delivery_status("2024-0130-001"))
      → API Response: {
          "status": "in_transit",
          "location": "서울 강남구",
          "estimated_arrival": "2026-01-31"
        }
      → "주문번호 2024-0130-001은 현재 서울 강남구에 있으며, 내일 도착 예정입니다"

Performance:
  - Intent Classification: 300ms
  - Slot Filling: 200ms
  - API Call: 1,500ms
  - Response Generation: 500ms
  - Total: 2,500ms ✅
```

##### Technical Design

**Tool Registry**:
```python
from typing import Callable, Dict, Any
from pydantic import BaseModel

class Tool(BaseModel):
    name: str
    description: str
    parameters: Dict[str, Any]
    permission: str  # "read" or "write"
    function: Callable

# Tool Definitions
tools = [
    Tool(
        name="get_order_info",
        description="주문번호로 주문 정보 조회",
        parameters={
            "order_number": {
                "type": "string",
                "description": "주문번호 (예: 2024-0130-001)"
            }
        },
        permission="read",
        function=lambda order_number: crm_api.get_order(order_number)
    ),
    Tool(
        name="get_delivery_status",
        description="배송 상태 실시간 조회",
        parameters={
            "order_number": {
                "type": "string"
            }
        },
        permission="read",
        function=lambda order_number: erp_api.get_delivery_status(order_number)
    ),
    Tool(
        name="submit_refund",
        description="환불 신청",
        parameters={
            "order_number": {"type": "string"},
            "reason": {"type": "string"},
            "refund_method": {"type": "string", "enum": ["계좌", "카드"]}
        },
        permission="write",  # 쓰기 권한 필요
        function=lambda **kwargs: crm_api.submit_refund(**kwargs)
    )
]

# LLM Tool Calling (Gemini Function Calling)
from langchain.agents import create_tool_calling_agent

agent = create_tool_calling_agent(
    llm=llm,
    tools=tools,
    prompt=agent_prompt
)

# Usage
response = await agent.ainvoke({
    "input": "주문번호 2024-0130-001 배송 상태 알려줘"
})
```

---

### Epic 2.2: 운영자 Dashboard - ARS Flow 관리

#### Feature 2.2.1: Visual Flow Editor

**Feature ID**: `F2.2.1`  
**Priority**: P1 (Should Have)  
**Complexity**: High  
**Estimated Story Points**: 21

##### Functional Requirements

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| FR-2.2.1-01 | 드래그앤드롭 Flow Builder | ✅ React Flow 기반 시각적 편집기 |
| FR-2.2.1-02 | Node 타입 지원 | ✅ Intent, Slot, Tool, Response 노드 제공 |
| FR-2.2.1-03 | Condition 분기 | ✅ IF-ELSE 로직 지원 |
| FR-2.2.1-04 | Flow 검증 | ✅ 저장 전 문법 오류 체크 |
| FR-2.2.1-05 | 버전 관리 | ✅ 이전 버전 롤백 가능 |

##### User Stories

**US-2.2.1-01**: 비개발자도 ARS 수정 가능
```gherkin
As a: 고객센터 운영자
I want to: 개발자 도움 없이 직접 ARS Flow를 수정하고 싶습니다
So that: 빠르게 비즈니스 변화에 대응할 수 있습니다

Acceptance Criteria:
- Given: 운영자가 Dashboard에 로그인할 때
- When: "ARS Flow 편집" 메뉴를 클릭하면
- Then: 시각적 Flow Editor가 열려야 합니다
- And: 기존 Flow가 그래프로 표시되어야 합니다
- And: 노드를 드래그앤드롭으로 추가/삭제/연결할 수 있어야 합니다
- And: 저장 버튼 클릭 시 즉시 반영되어야 합니다 (배포 시간 < 5분)

Example Scenario:
  Task: "배송 조회" Flow에 "배송지 변경" 옵션 추가
  
  Steps:
    1. "배송 조회" Flow 열기
    2. "배송 상태 확인" 노드 선택
    3. 새 노드 추가: "배송지 변경하시겠어요?" (Response 노드)
    4. 분기 추가:
       - Yes → "새 배송지 입력해주세요" (Slot 노드)
       - No → "감사합니다" (Response 노드)
    5. "저장" 버튼 클릭
    6. 자동 배포 (5분 이내)
  
  Result:
    ✅ 다음 통화부터 새 Flow 적용
    ✅ 개발자 개입 없음
    ✅ 변경 이력 자동 저장
```

##### Technical Design

**Frontend**:
- Framework: React 18 + TypeScript
- Flow Editor: React Flow (https://reactflow.dev/)
- State Management: Zustand
- UI Library: Material-UI

**Backend API**:
```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/flows")

class FlowDefinition(BaseModel):
    id: str
    name: str
    version: int
    nodes: List[Dict]
    edges: List[Dict]
    created_by: str
    created_at: datetime

@router.get("/flows")
async def list_flows():
    """모든 Flow 목록"""
    return await flow_repository.get_all()

@router.get("/flows/{flow_id}")
async def get_flow(flow_id: str):
    """특정 Flow 조회"""
    flow = await flow_repository.get_by_id(flow_id)
    if not flow:
        raise HTTPException(status_code=404)
    return flow

@router.post("/flows")
async def create_flow(flow: FlowDefinition):
    """새 Flow 생성"""
    # Validation
    validate_flow(flow)
    # Save
    await flow_repository.create(flow)
    # Deploy
    await deploy_flow(flow)
    return {"id": flow.id, "status": "deployed"}

@router.put("/flows/{flow_id}")
async def update_flow(flow_id: str, flow: FlowDefinition):
    """Flow 업데이트"""
    # Versioning
    flow.version += 1
    await flow_repository.update(flow_id, flow)
    await deploy_flow(flow)
    return {"id": flow_id, "version": flow.version}
```

---

## Phase 3: HITL + Shadowing Mode

### Epic 3.1: Real-time Feedback Loop

#### Feature 3.1.1: Confidence Monitoring

**Feature ID**: `F3.1.1`  
**Priority**: P0 (Must Have)  
**Complexity**: Medium  
**Estimated Story Points**: 8

##### Functional Requirements

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| FR-3.1.1-01 | AI 답변마다 Confidence Score 계산 | ✅ 0-100% 범위, 실시간 계산 |
| FR-3.1.1-02 | Low Confidence 감지 (<60%) | ✅ 감지 시 즉시 운영자에게 알림 |
| FR-3.1.1-03 | Confidence 기준 동적 조정 | ✅ 운영자가 Threshold 설정 가능 |
| FR-3.1.1-04 | Confidence 로그 저장 | ✅ 모든 답변의 Confidence 기록 |

##### User Stories

**US-3.1.1-01**: AI 신뢰도 모니터링
```gherkin
As a: 운영자
I want to: AI가 답변할 때마다 신뢰도를 확인하고 싶습니다
So that: 잘못된 답변을 사전에 차단할 수 있습니다

Acceptance Criteria:
- Given: AI가 고객 질문에 답변할 때
- When: Confidence Score가 계산되면
- Then: 점수가 Dashboard에 실시간으로 표시되어야 합니다
- And: 점수가 60% 미만이면 경고 알림이 떠야 합니다
- And: 운영자가 개입 여부를 결정할 수 있어야 합니다

Example:
  Scenario: 고객이 "이거 언제 와요?"라고 질문
  
  AI Processing:
    1. RAG Retrieval: 유사 질문 찾기
       - Result 1: "배송 언제 오나요?" (similarity: 0.68)
       - Result 2: "주문한 거 언제 와요?" (similarity: 0.65)
    2. Confidence Calculation:
       - RAG Score: 0.68 (Medium)
       - Query Clarity: 0.45 (Low - "이거"가 불명확)
       - **Total Confidence: 56%** ⚠️ Low
    3. Action: 운영자에게 알림 전송
  
  Dashboard Alert:
    ⚠️ Low Confidence Detected (56%)
    Call ID: abc123
    Customer: "이거 언제 와요?"
    AI Answer: "주문번호를 알려주시면 확인해드리겠습니다"
    
    [개입하기] [무시하기]
```

##### Technical Design

**Confidence Score Calculation**:
```python
class ConfidenceCalculator:
    def calculate(self, query: str, rag_results: List, llm_response: str) -> float:
        """
        종합 Confidence Score 계산
        
        Components:
        1. RAG Retrieval Score (40%)
        2. Query Clarity Score (30%)
        3. LLM Certainty Score (30%)
        """
        rag_score = self._rag_score(rag_results)
        clarity_score = self._query_clarity(query)
        llm_score = self._llm_certainty(llm_response)
        
        confidence = (
            rag_score * 0.4 +
            clarity_score * 0.3 +
            llm_score * 0.3
        )
        
        return min(confidence * 100, 100)
    
    def _rag_score(self, results: List) -> float:
        """RAG 검색 결과 품질"""
        if not results:
            return 0.0
        # Top 1 결과의 유사도
        return results[0]["similarity"]
    
    def _query_clarity(self, query: str) -> float:
        """질문 명확성 (대명사, 불완전한 문장 감지)"""
        unclear_words = ["이거", "그거", "저거", "뭐", "어", "음"]
        unclear_count = sum(1 for word in unclear_words if word in query)
        return max(1.0 - (unclear_count * 0.2), 0.0)
    
    def _llm_certainty(self, response: str) -> float:
        """LLM 답변 확실성 (hedging 표현 감지)"""
        hedge_words = ["아마", "아마도", "혹시", "아닐까", "싶습니다", "것 같습니다"]
        hedge_count = sum(1 for word in hedge_words if word in response)
        return max(1.0 - (hedge_count * 0.15), 0.0)
```

---

#### Feature 3.1.2: Real-time Operator Intervention

**Feature ID**: `F3.1.2`  
**Priority**: P0 (Must Have)  
**Complexity**: High  
**Estimated Story Points**: 21

##### Functional Requirements

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| FR-3.1.2-01 | WebSocket 실시간 통신 | ✅ AI ↔ 운영자 간 <200ms latency |
| FR-3.1.2-02 | 운영자 Chat 인터페이스 | ✅ 통화 중 채팅으로 정답 입력 가능 |
| FR-3.1.2-03 | AI 답변 대체 | ✅ 운영자 입력 → AI가 즉시 고객에게 전달 |
| FR-3.1.2-04 | Feedback 즉시 학습 | ✅ 정답은 VectorDB에 즉시 저장 |
| FR-3.1.2-05 | 개입 이력 기록 | ✅ 누가, 언제, 무엇을 수정했는지 Audit Log |

##### User Stories

**US-3.1.2-01**: 통화 중 AI 답변 수정
```gherkin
As a: 운영자
I want to: AI가 잘못된 답변을 하려고 할 때 즉시 개입하고 싶습니다
So that: 고객에게 정확한 정보를 제공할 수 있습니다

Acceptance Criteria:
- Given: AI가 고객 질문에 답변하려고 할 때
- When: Confidence Score가 60% 미만이고
- And: 운영자가 "개입하기" 버튼을 클릭하면
- Then: 실시간 Chat 창이 열려야 합니다
- And: AI가 제시한 답변이 표시되어야 합니다
- And: 운영자가 정답을 입력하면
- Then: AI가 즉시 고객에게 수정된 답변을 전달해야 합니다
- And: 수정된 Q&A는 VectorDB에 즉시 저장되어야 합니다

Example:
  Scenario: 신제품 출시 직후 문의
  
  Call Flow:
    [10:00:00] Customer: "신제품 아이폰 16 Pro 있나요?"
    [10:00:01] AI (Internal): 
      - RAG Search: No results (신제품이라 DB에 없음)
      - Confidence: 25% ⚠️
      - Alert sent to Operator
    
    [10:00:02] Operator Dashboard:
      ⚠️ Low Confidence (25%)
      Question: "신제품 아이폰 16 Pro 있나요?"
      AI Draft: "죄송합니다, 확인이 필요합니다"
      
      [개입하기] ← Click
    
    [10:00:03] Chat Window Opens:
      AI Draft: "죄송합니다, 확인이 필요합니다"
      
      Operator Types:
      "네, 아이폰 16 Pro는 어제 입고되었습니다. 
       256GB 모델 재고 있으며, 가격은 ₩1,500,000입니다"
      
      [전송] ← Click
    
    [10:00:05] AI to Customer (TTS):
      "네, 아이폰 16 Pro는 어제 입고되었습니다. 
       256GB 모델 재고 있으며, 가격은 ₩1,500,000입니다"
    
    [10:00:06] Background:
      ✅ Q&A saved to VectorDB
      ✅ Audit Log created
      ✅ Next call: AI can answer this question automatically

Performance:
  - Operator notification: 200ms
  - Operator typing: 5s
  - AI TTS response: 3s
  - Total intervention time: ~8s
```

##### Technical Design

**Real-time Communication Architecture**:
```
[AI Agent] <--> [WebSocket Server] <--> [Operator Dashboard]
                        ↓
                [Message Queue]
                        ↓
                [Vector DB Writer]
```

**WebSocket Implementation**:
```python
from fastapi import WebSocket, WebSocketDisconnect
from typing import Dict

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
    
    async def connect(self, call_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[call_id] = websocket
    
    async def disconnect(self, call_id: str):
        self.active_connections.pop(call_id, None)
    
    async def send_alert(self, call_id: str, alert: dict):
        """운영자에게 Low Confidence 알림"""
        if call_id in self.active_connections:
            await self.active_connections[call_id].send_json(alert)
    
    async def receive_feedback(self, call_id: str) -> dict:
        """운영자로부터 정답 수신"""
        if call_id in self.active_connections:
            data = await self.active_connections[call_id].receive_json()
            return data
        return None

manager = ConnectionManager()

@app.websocket("/ws/call/{call_id}")
async def websocket_endpoint(websocket: WebSocket, call_id: str):
    await manager.connect(call_id, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            # 운영자 피드백 처리
            await process_operator_feedback(call_id, data)
    except WebSocketDisconnect:
        await manager.disconnect(call_id)

async def process_operator_feedback(call_id: str, feedback: dict):
    """운영자 피드백 처리"""
    # 1. AI에게 새 답변 전달
    await ai_agent.update_response(call_id, feedback["answer"])
    
    # 2. VectorDB에 즉시 저장
    await vector_db.upsert({
        "question": feedback["question"],
        "answer": feedback["answer"],
        "source": "operator_correction",
        "call_id": call_id,
        "timestamp": datetime.now()
    })
    
    # 3. Audit Log 기록
    await audit_log.create({
        "call_id": call_id,
        "operator_id": feedback["operator_id"],
        "action": "correction",
        "original_answer": feedback["original"],
        "new_answer": feedback["answer"]
    })
```

---

#### Feature 3.1.3: Post-call Review & Labeling

**Feature ID**: `F3.1.3`  
**Priority**: P1 (Should Have)  
**Complexity**: Medium  
**Estimated Story Points**: 13

##### Functional Requirements

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| FR-3.1.3-01 | Low Confidence 통화 자동 추출 | ✅ Confidence < 70% 통화 목록화 |
| FR-3.1.3-02 | Transcript Review UI | ✅ 통화 내용 재생 + 텍스트 표시 |
| FR-3.1.3-03 | 정답 레이블링 | ✅ "정답은 이것입니다" 입력 → 저장 |
| FR-3.1.3-04 | Batch Processing | ✅ 한 번에 여러 통화 리뷰 가능 |
| FR-3.1.3-05 | 학습 효과 측정 | ✅ Before/After Confidence 비교 |

##### User Stories

**US-3.1.3-01**: 통화 후 품질 개선
```gherkin
As a: 운영자
I want to: 하루 종료 후 AI가 잘못 답변한 통화를 리뷰하고 싶습니다
So that: 내일부터는 같은 실수를 하지 않도록 학습시킬 수 있습니다

Acceptance Criteria:
- Given: 하루 업무가 종료되었을 때
- When: "통화 리뷰" 메뉴에 접속하면
- Then: Low Confidence 통화 목록이 표시되어야 합니다
- And: 각 통화의 Confidence Score, 문제 유형이 표시되어야 합니다
- And: 통화를 선택하면 Transcript와 AI 답변을 볼 수 있어야 합니다
- And: 정답을 입력하고 저장하면
- Then: VectorDB에 즉시 반영되어야 합니다
- And: 다음날 유사 질문에 정확히 답변해야 합니다

Example:
  End of Day Review:
  
  📋 Low Confidence Calls Today (2026-01-30):
  Total: 15 calls
  
  | Call ID | Time | Question | Confidence | Status |
  |---------|------|----------|------------|--------|
  | abc123 | 10:00 | "신제품 있나요?" | 25% | ⬜ Not Reviewed |
  | def456 | 14:30 | "배송지 변경 가능?" | 58% | ⬜ Not Reviewed |
  | ghi789 | 16:00 | "이거 환불돼?" | 45% | ⬜ Not Reviewed |
  
  Operator Actions:
    1. Click "abc123" → Open Review UI
    2. Listen to audio + Read transcript
    3. Review AI answer: "죄송합니다, 확인이 필요합니다"
    4. Input correct answer: "네, 아이폰 16 Pro 재고 있습니다"
    5. Click "Save & Learn"
    6. Status changed: ✅ Reviewed
  
  Next Day:
    Customer: "신제품 아이폰 16 Pro 있나요?"
    AI: (RAG finds yesterday's correction)
        "네, 아이폰 16 Pro 재고 있습니다"
        Confidence: 92% ✅
```

##### Technical Design

**Review Dashboard UI**:
```typescript
interface CallReview {
  callId: string;
  timestamp: Date;
  question: string;
  aiAnswer: string;
  confidence: number;
  audioUrl: string;
  transcriptUrl: string;
  status: 'pending' | 'reviewed' | 'skipped';
}

// React Component
const CallReviewDashboard: React.FC = () => {
  const [calls, setCalls] = useState<CallReview[]>([]);
  
  useEffect(() => {
    // Fetch low confidence calls
    fetchLowConfidenceCalls().then(setCalls);
  }, []);
  
  const handleReview = async (callId: string, correctAnswer: string) => {
    await api.submitCorrection(callId, correctAnswer);
    // Update status
    setCalls(prev => prev.map(call => 
      call.callId === callId 
        ? {...call, status: 'reviewed'} 
        : call
    ));
  };
  
  return (
    <div>
      <h1>통화 리뷰 (Low Confidence)</h1>
      <Table data={calls} onReview={handleReview} />
    </div>
  );
};
```

---

### Epic 3.2: Shadowing Mode (신입 교육 도구)

#### Feature 3.2.1: Real-time Agent Assistance

**Feature ID**: `F3.2.1`  
**Priority**: P1 (Should Have)  
**Complexity**: High  
**Estimated Story Points**: 21

##### Functional Requirements

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| FR-3.2.1-01 | 상담원 통화 중 AI 가이드 제공 | ✅ 실시간으로 답변 가이드 표시 |
| FR-3.2.1-02 | 관련 지식 자동 검색 | ✅ 고객 질문 들으면 즉시 RAG 검색 |
| FR-3.2.1-03 | Script 제공 | ✅ "이렇게 답변하세요" 템플릿 |
| FR-3.2.1-04 | 상담원 수준별 가이드 조절 | ✅ 신입/경력에 따라 가이드 수준 변경 |
| FR-3.2.1-05 | 학습 효과 측정 | ✅ 가이드 따른 경우 vs. 안 따른 경우 비교 |

##### User Stories

**US-3.2.1-01**: 신입 상담원 실시간 지원
```gherkin
As a: 신입 상담원
I want to: 통화 중 AI가 실시간으로 답변 가이드를 제공해주기를 원합니다
So that: 막히지 않고 자신있게 고객을 응대할 수 있습니다

Acceptance Criteria:
- Given: 신입 상담원이 고객과 통화 중일 때
- When: 고객이 질문을 하면
- Then: AI가 자동으로 관련 지식을 검색해야 합니다
- And: 상담원 화면에 추천 답변이 표시되어야 합니다
- And: 답변 템플릿, 관련 정책, 과거 유사 사례가 함께 제공되어야 합니다
- And: 가이드는 2초 이내에 표시되어야 합니다

Example:
  Scenario: 신입 상담원 첫 통화
  
  [10:00:00] Customer: "배송비가 왜 이렇게 비싸요?"
  [10:00:01] AI Guidance (상담원 화면):
    
    💡 추천 답변:
    "죄송합니다. 현재 제주/도서산간 지역은 추가 배송비가 발생합니다.
     일반 지역은 3만원 이상 구매 시 무료배송입니다"
    
    📋 관련 정책:
    - 제주/도서산간: +3,000원
    - 일반 배송비: 3,000원
    - 무료배송 기준: 30,000원 이상
    
    🔍 유사 사례 (3건):
    - "배송비 환불 안되나요?" → "배송비는 환불 제외됩니다"
    - "도서산간이 아닌데 비싸요" → "주소 확인 후 수정 가능합니다"
    
    [이 답변 사용] [다른 답변 보기]
  
  [10:00:03] Agent (자신있게): "죄송합니다. 제주/도서산간 지역은..."
  [10:00:10] Customer: "그럼 환불 받을 수 있나요?"
  [10:00:11] AI Guidance:
    "배송비는 환불 대상에서 제외됩니다. 
     단, 상품 하자로 인한 반품 시에는 배송비도 환불됩니다"

Performance:
  - Customer question detected: 500ms
  - RAG search: 1,000ms
  - Guidance display: 1,500ms
  - Total: <2 seconds ✅
```

##### Technical Design

**Shadowing Mode Architecture**:
```
[Agent Softphone] → [STT Real-time] → [AI Guidance Engine]
                                            ↓
                                       [RAG Search]
                                            ↓
                                    [Agent Dashboard]
```

**Agent Dashboard**:
```typescript
interface GuidanceCard {
  question: string;
  suggestedAnswer: string;
  relatedPolicies: string[];
  similarCases: Array<{question: string, answer: string}>;
  confidence: number;
}

const AgentDashboard: React.FC = () => {
  const [currentCall, setCurrentCall] = useState<Call | null>(null);
  const [guidance, setGuidance] = useState<GuidanceCard | null>(null);
  
  // WebSocket: 실시간 통화 내용 수신
  useEffect(() => {
    const ws = new WebSocket(`ws://localhost:8000/ws/agent/${agentId}`);
    
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      
      if (data.type === 'customer_question') {
        // AI에게 가이드 요청
        fetchGuidance(data.question).then(setGuidance);
      }
    };
    
    return () => ws.close();
  }, []);
  
  return (
    <div className="agent-dashboard">
      <div className="call-info">
        <h2>통화 중: {currentCall?.customerId}</h2>
      </div>
      
      {guidance && (
        <div className="ai-guidance">
          <h3>💡 AI 추천 답변</h3>
          <p className="suggested-answer">{guidance.suggestedAnswer}</p>
          
          <h4>📋 관련 정책</h4>
          <ul>
            {guidance.relatedPolicies.map((policy, i) => (
              <li key={i}>{policy}</li>
            ))}
          </ul>
          
          <h4>🔍 유사 사례</h4>
          {guidance.similarCases.map((case, i) => (
            <div key={i} className="similar-case">
              <strong>Q: {case.question}</strong>
              <p>A: {case.answer}</p>
            </div>
          ))}
          
          <div className="actions">
            <button onClick={() => useThisAnswer(guidance.suggestedAnswer)}>
              이 답변 사용
            </button>
            <button onClick={() => fetchAlternatives()}>
              다른 답변 보기
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
```

---

## Phase 4: Agentic AI + Multi-Agent

### Epic 4.1: Tool-calling Agent

#### Feature 4.1.1: Autonomous Tool Execution

**Feature ID**: `F4.1.1`  
**Priority**: P2 (Nice to Have)  
**Complexity**: Very High  
**Estimated Story Points**: 34

##### Functional Requirements

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| FR-4.1.1-01 | AI가 자율적으로 Tool 선택 및 실행 | ✅ LangGraph Agent 기반 |
| FR-4.1.1-02 | 다단계 Tool Chaining | ✅ Tool A → Tool B → Tool C 순차 실행 |
| FR-4.1.1-03 | Tool 실행 권한 관리 | ✅ 읽기/쓰기 권한 분리, 승인 필요 |
| FR-4.1.1-04 | Rollback 기능 | ✅ Tool 실행 실패 시 이전 상태 복구 |
| FR-4.1.1-05 | Audit Trail | ✅ 모든 Tool 실행 이력 기록 |

##### User Stories

**US-4.1.1-01**: AI가 직접 시스템 조작
```gherkin
As a: 고객
I want to: AI가 직접 배송지를 변경해주기를 원합니다
So that: 상담원을 기다리지 않고 즉시 처리할 수 있습니다

Acceptance Criteria:
- Given: 고객이 "배송지 변경하고 싶어요"라고 요청할 때
- When: AI Agent가 실행되면
- Then: 다음 단계를 자동으로 수행해야 합니다:
  1. Tool: get_order_info() - 주문 정보 조회
  2. Tool: check_delivery_status() - 배송 상태 확인 (변경 가능 여부)
  3. Tool: update_delivery_address() - 배송지 변경 (쓰기 권한)
  4. Tool: send_confirmation_sms() - 변경 완료 문자 전송
- And: 각 Tool 실행 전 고객 확인 필요 (쓰기 작업)
- And: 전체 프로세스는 30초 이내에 완료되어야 합니다

Example:
  Customer: "배송지 변경하고 싶어요"
  
  AI Agent Workflow:
    Step 1: Intent = "update_delivery_address"
    Step 2: Slot Filling
      - AI: "주문번호 알려주시겠어요?"
      - Customer: "2024-0130-001"
    
    Step 3: Tool Execution (자동)
      [Tool 1] get_order_info("2024-0130-001")
        → Result: {status: "preparing", address: "서울 강남구..."}
      
      [Tool 2] check_delivery_status("2024-0130-001")
        → Result: {changeable: true, reason: "배송 전"}
      
      AI: "현재 배송 전 단계라 변경 가능합니다. 새 주소 알려주세요"
      Customer: "서울 서초구 123-45"
      
      [Tool 3] update_delivery_address("2024-0130-001", "서울 서초구 123-45")
        → Requires Approval: "배송지를 변경하시겠습니까? (Yes/No)"
        → Customer: "Yes"
        → Result: {success: true, new_address: "서울 서초구 123-45"}
      
      [Tool 4] send_confirmation_sms(customer_phone, "배송지 변경 완료")
        → Result: {sent: true}
    
    AI: "배송지가 서울 서초구 123-45로 변경되었습니다. 
         확인 문자 전송했습니다"

Timeline:
  - Slot Filling: 10s
  - Tool 1-2 (read): 3s
  - Customer confirmation: 5s
  - Tool 3-4 (write): 5s
  - Total: 23s ✅
```

##### Technical Design

**LangGraph Agent Workflow**:
```python
from langgraph.graph import StateGraph, END
from typing import TypedDict, List

class AgentState(TypedDict):
    messages: List[dict]
    intent: str
    slots: dict
    tool_results: List[dict]
    next_action: str

# Tool Definitions
tools = [
    {
        "name": "get_order_info",
        "description": "주문 정보 조회",
        "permission": "read",
        "function": crm_api.get_order
    },
    {
        "name": "update_delivery_address",
        "description": "배송지 변경",
        "permission": "write",  # 승인 필요
        "function": crm_api.update_address,
        "requires_approval": True
    }
]

# Graph 구성
workflow = StateGraph(AgentState)

# Nodes
workflow.add_node("classify_intent", classify_intent_node)
workflow.add_node("fill_slots", slot_filling_node)
workflow.add_node("select_tool", tool_selection_node)
workflow.add_node("execute_tool", tool_execution_node)
workflow.add_node("generate_response", response_generation_node)

# Edges
workflow.add_edge("classify_intent", "fill_slots")
workflow.add_conditional_edges(
    "fill_slots",
    lambda state: "complete" if state["slots_complete"] else "continue",
    {
        "complete": "select_tool",
        "continue": "fill_slots"
    }
)
workflow.add_edge("select_tool", "execute_tool")
workflow.add_conditional_edges(
    "execute_tool",
    lambda state: "more_tools" if state["needs_more_tools"] else "done",
    {
        "more_tools": "select_tool",
        "done": "generate_response"
    }
)
workflow.add_edge("generate_response", END)

# Compile
agent = workflow.compile()

# Run
result = await agent.ainvoke({
    "messages": [{"role": "user", "content": "배송지 변경하고 싶어요"}]
})
```

---

### Epic 4.2: Multi-Agent Collaboration

#### Feature 4.2.1: Agent Orchestration

**Feature ID**: `F4.2.1`  
**Priority**: P2 (Nice to Have)  
**Complexity**: Very High  
**Estimated Story Points**: 34

##### Functional Requirements

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| FR-4.2.1-01 | 여러 Agent가 협력하여 문제 해결 | ✅ Multi-Agent Orchestrator 구현 |
| FR-4.2.1-02 | Agent 간 Communication | ✅ Message Passing 메커니즘 |
| FR-4.2.1-03 | 병렬 실행 지원 | ✅ 독립적인 작업은 동시 실행 |
| FR-4.2.1-04 | Agent 우선순위 관리 | ✅ 중요도에 따라 실행 순서 조정 |
| FR-4.2.1-05 | 결과 통합 | ✅ 각 Agent 결과를 종합하여 최종 답변 생성 |

##### User Stories

**US-4.2.1-01**: 복잡한 요청 한 번에 해결
```gherkin
As a: 고객
I want to: 여러 개의 요청을 한 번에 처리하고 싶습니다
So that: 여러 번 전화하지 않아도 됩니다

Acceptance Criteria:
- Given: 고객이 복잡한 요청을 할 때
  예: "환불하고 재주문하려고 하는데, 쿠폰 사용 가능한지 알려줘"
- When: Multi-Agent System이 실행되면
- Then: 다음 Agent들이 협력해야 합니다:
  * Agent 1 (환불): 환불 가능 여부 및 절차
  * Agent 2 (주문): 재주문 가능 상품 목록
  * Agent 3 (프로모션): 쿠폰 사용 가능 여부
- And: 각 Agent의 결과를 통합하여 답변해야 합니다
- And: 전체 처리 시간은 45초 이내여야 합니다

Example:
  Customer: "환불하고 재주문하려고 하는데, 쿠폰 사용 가능한지도 알려줘"
  
  Multi-Agent Workflow:
    Orchestrator: 3개 Sub-task 식별
    
    [Agent 1: RefundAgent] (병렬 실행)
      Task: 환불 가능 여부 확인
      Tools: get_order_info(), check_refund_policy()
      Result: {
        "refundable": true,
        "reason": "30일 이내 주문",
        "process_time": "3-5일",
        "amount": 50000
      }
    
    [Agent 2: OrderAgent] (병렬 실행)
      Task: 재주문 가능 상품 확인
      Tools: get_product_info(), check_stock()
      Result: {
        "available": true,
        "stock": 15,
        "price": 50000
      }
    
    [Agent 3: PromoAgent] (병렬 실행)
      Task: 쿠폰 사용 가능 여부
      Tools: get_customer_coupons(), check_coupon_policy()
      Result: {
        "usable_coupons": [
          {"name": "신규회원 10%", "discount": 5000},
          {"name": "재구매 5000원", "discount": 5000}
        ],
        "restrictions": "환불 후 재주문 시 쿠폰 사용 가능"
      }
    
    [Orchestrator: Result Integration]
      Combine results from all agents:
      
      "네, 환불 가능합니다. 3-5일 소요되며 50,000원 환불됩니다.
       재주문하실 상품은 현재 재고 15개 있습니다.
       환불 완료 후 재주문 시 '신규회원 10%' 또는 '재구매 5000원' 쿠폰 사용 가능합니다.
       환불 진행하시겠습니까?"

Timeline:
  - Task decomposition: 2s
  - Agent 1-3 (parallel): 15s
  - Result integration: 3s
  - Total: 20s ✅
```

##### Technical Design

**Multi-Agent Architecture**:
```python
from typing import List, Dict
import asyncio

class Agent(BaseModel):
    name: str
    specialty: str
    tools: List[Tool]
    llm: ChatGoogleGenerativeAI
    
    async def execute(self, task: str) -> Dict:
        """Agent가 자신의 특화 작업 수행"""
        # 1. Task 분석
        # 2. Tool 선택 및 실행
        # 3. 결과 생성
        pass

class Orchestrator:
    def __init__(self):
        self.agents = {
            "refund": RefundAgent(),
            "order": OrderAgent(),
            "promo": PromoAgent(),
            "delivery": DeliveryAgent()
        }
    
    async def process(self, user_request: str):
        # 1. Task Decomposition
        tasks = await self.decompose_task(user_request)
        # Example: [
        #   {"agent": "refund", "task": "환불 가능 여부"},
        #   {"agent": "order", "task": "재주문 가능 상품"},
        #   {"agent": "promo", "task": "쿠폰 사용 가능"}
        # ]
        
        # 2. 병렬 실행 (독립적인 작업)
        results = await asyncio.gather(*[
            self.agents[task["agent"]].execute(task["task"])
            for task in tasks
        ])
        
        # 3. 결과 통합
        integrated_response = await self.integrate_results(results)
        
        return integrated_response
    
    async def decompose_task(self, request: str) -> List[Dict]:
        """LLM으로 복잡한 요청을 sub-task로 분해"""
        decompose_prompt = f"""
        다음 고객 요청을 여러 개의 sub-task로 분해하세요:
        "{request}"
        
        사용 가능한 Agent:
        - refund: 환불 관련
        - order: 주문 관련
        - promo: 쿠폰/프로모션 관련
        - delivery: 배송 관련
        
        Output (JSON):
        [
          {{"agent": "agent_name", "task": "task_description"}},
          ...
        ]
        """
        response = await self.llm.ainvoke(decompose_prompt)
        return json.loads(response.content)
```

---

## Phase 1 부록: AI 응대 모드 Configuration 및 API 명세

### Configuration

**설정 파일**: `config/config.yaml`

```yaml
sip:
  timers:
    no_answer_timeout: 10  # 초 (기본값: 10초)
    # 착신자가 이 시간 동안 응답하지 않으면 AI 모드 활성화

ai_attendant:
  enabled: true  # AI 응대 모드 활성화 여부
  default_away_message: "죄송합니다. 확인 후 별도로 안내드리겠습니다."
  
  # RAG 설정
  rag:
    top_k: 3  # 검색할 유사 질문 수
    similarity_threshold: 0.7  # 최소 유사도
    
  # LLM 설정
  llm:
    model: "gemini-2.5-flash"
    temperature: 0.7
    max_tokens: 500
    
  # STT/TTS 설정
  stt:
    provider: "google"
    language: "ko-KR"
    
  tts:
    provider: "google"
    voice: "ko-KR-Standard-A"
    speaking_rate: 1.0
```

### API Specification

#### 1. 운영자 상태 변경

**Endpoint**: `PUT /api/operator/status`

**Request**:
```http
PUT /api/operator/status
Content-Type: application/json
Authorization: Bearer {JWT_TOKEN}

{
  "status": "away",  # "available" | "away" | "busy" | "offline"
  "away_message": "회의 중입니다. AI 비서가 도와드리겠습니다."  # optional, status="away"일 때만
}
```

**Response** (200 OK):
```json
{
  "operator_id": "1004",
  "status": "away",
  "away_message": "회의 중입니다. AI 비서가 도와드리겠습니다.",
  "status_changed_at": "2026-02-05T10:00:02Z",
  "unresolved_hitl_count": 0
}
```

**Error Responses**:
- `401 Unauthorized`: JWT 토큰 없음 또는 만료
- `400 Bad Request`: 잘못된 status 값
- `500 Internal Server Error`: 서버 오류

#### 2. 운영자 상태 조회

**Endpoint**: `GET /api/operator/status`

**Request**:
```http
GET /api/operator/status
Authorization: Bearer {JWT_TOKEN}
```

**Response** (200 OK):
```json
{
  "operator_id": "1004",
  "status": "available",
  "away_message": null,
  "status_changed_at": "2026-02-05T09:00:00Z",
  "unresolved_hitl_count": 0
}
```

#### 3. AI 응대 모드 활성화 이벤트 (WebSocket)

**Endpoint**: `WS /ws/call/{call_id}`

**Message Types**:

**AI 모드 활성화 알림**:
```json
{
  "type": "ai_mode_activated",
  "call_id": "abc123",
  "reason": "no_answer_timeout",  # "no_answer_timeout" | "away_status"
  "callee": "1004",
  "timestamp": "2026-02-05T10:00:12Z"
}
```

**AI 응답 생성**:
```json
{
  "type": "ai_response",
  "call_id": "abc123",
  "question": "배송 조회하고 싶어요",
  "answer": "주문번호를 알려주시면 배송 상태를 확인해드리겠습니다",
  "confidence": 0.92,
  "timestamp": "2026-02-05T10:00:18Z"
}
```

### Testing Strategy

**Unit Tests**:
- [ ] 타이머 시작/취소 테스트
- [ ] 부재중 상태 확인 테스트
- [ ] AI 모드 활성화 로직 테스트
- [ ] API 엔드포인트 테스트

**Integration Tests**:
- [ ] 타이머 기반 AI 전환 E2E 테스트
- [ ] 수동 부재중 설정 → AI 응대 E2E 테스트
- [ ] 실시간 STT → RAG → LLM → TTS 파이프라인 테스트
- [ ] 통화 종료 후 지식 저장 테스트

**Performance Tests**:
- [ ] 타이머 정확도 측정 (±100ms)
- [ ] AI 전환 지연 측정 (<1s)
- [ ] End-to-end 대화 지연 측정 (<2.5s)
- [ ] 동시 100통화 처리 테스트

**Acceptance Test Scenarios**:

**Scenario 1: 타이머 기반 자동 전환**
```gherkin
Given: 서버가 실행 중이고 no_answer_timeout=10초로 설정되어 있을 때
When: 고객이 운영자(1004)에게 전화를 걸고
And: 운영자가 10초 동안 전화를 받지 않으면
Then: AI Voicebot이 자동으로 응답해야 합니다
And: 콘솔에 "⏰ No Answer Timeout!" 메시지가 표시되어야 합니다
And: 로그에 "ai_mode_activated" 이벤트가 기록되어야 합니다
```

**Scenario 2: 수동 부재중 설정**
```gherkin
Given: 운영자가 웹/앱에 로그인한 상태일 때
When: 운영자가 "부재중" 버튼을 클릭하고
And: 부재중 메시지를 입력한 후 저장하면
Then: API 응답으로 status="away"가 반환되어야 합니다
And: 이후 고객이 전화를 걸면
Then: AI Voicebot이 즉시 응답해야 합니다
And: 착신자 단말로 INVITE가 전송되지 않아야 합니다
```

**Scenario 3: 실시간 AI 대화**
```gherkin
Given: AI 응대 모드가 활성화된 상태일 때
When: 고객이 "배송 조회하고 싶어요"라고 말하면
Then: STT가 음성을 텍스트로 변환해야 합니다 (<500ms)
And: RAG가 VectorDB에서 유사 질문을 검색해야 합니다 (<100ms)
And: LLM이 답변을 생성해야 합니다 (<1s)
And: TTS가 답변을 음성으로 변환해야 합니다 (<1s)
And: 전체 프로세스는 2.5초 이내에 완료되어야 합니다
```

**Scenario 4: 통화 후 학습**
```gherkin
Given: AI 응대 모드로 통화가 진행되고 종료될 때
When: BYE 메시지가 수신되면
Then: 전체 Transcript가 생성되어야 합니다 (5초 이내)
And: LLM이 유용한 Q&A 쌍을 추출해야 합니다
And: 추출된 지식이 VectorDB에 저장되어야 합니다
And: 저장 후 3초 이내에 다음 통화에서 검색 가능해야 합니다
```

---

## Cross-cutting Concerns

### 성능 (Performance)

| Metric | Target | Measurement Method |
|--------|--------|-------------------|
| STT Latency | <500ms | RTP packet → Text 시간 |
| RAG Retrieval | <100ms | Query → Top-K results |
| LLM Response | <1s | Query → Generated response |
| End-to-End | <2s | 고객 질문 → AI 답변 (TTS 포함) |
| Throughput | 100 concurrent calls | Load test |
| Uptime | 99.9% | Prometheus monitoring |

### 보안 (Security)

| Requirement | Implementation |
|-------------|----------------|
| 통화 데이터 암호화 | AES-256 at rest, TLS 1.3 in transit |
| PII 마스킹 | 이름, 전화번호, 주소 자동 마스킹 |
| 접근 제어 | RBAC (Role-Based Access Control) |
| Audit Log | 모든 Tool 실행, Operator 개입 기록 |
| GDPR 준수 | Right to be forgotten (데이터 삭제 요청) |

### 확장성 (Scalability)

| Component | Scaling Strategy |
|-----------|------------------|
| SIP PBX | Horizontal (K8s StatefulSet, replicas: 3+) |
| Vector DB | Sharding by date (월별 분리) |
| LLM | Rate limiting + Caching (Redis) |
| WebSocket | Load balancer (sticky sessions) |
| Storage | S3 for recordings, RDS for metadata |

### 모니터링 (Monitoring)

```yaml
Metrics (Prometheus):
  - sip_pbx_active_calls: Gauge
  - rag_retrieval_latency_seconds: Histogram
  - llm_requests_total: Counter
  - confidence_score_distribution: Histogram
  - operator_intervention_rate: Gauge
  
Alerts:
  - HighLatency: RAG retrieval > 200ms for 5min
  - LowConfidence: >20% calls with confidence <60%
  - HighInterventionRate: Operator intervention > 15%
  - SystemDown: Uptime < 99%

Dashboards (Grafana):
  - Real-time Call Monitoring
  - AI Performance (Accuracy, Latency)
  - HITL Statistics
  - Cost Tracking (API usage)
```

---

## 부록: User Story 템플릿

### Standard User Story Template

```gherkin
As a: [Role - 시스템 관리자, 고객, 운영자, AI 시스템 등]
I want to: [Goal - 무엇을 원하는가]
So that: [Benefit - 왜 원하는가, 어떤 가치를 얻는가]

Acceptance Criteria:
- Given: [Precondition - 전제 조건]
- When: [Action - 어떤 행동을 할 때]
- Then: [Outcome - 예상되는 결과]
- And: [Additional conditions - 추가 조건]

Example:
  [Concrete example with input/output]

Performance:
  [Non-functional requirements - latency, throughput 등]

Dependencies:
  - [Dependent features, APIs, services]
```

### Epic Template

```markdown
### Epic [번호]: [Epic 이름]

#### 개요
[Epic의 목적과 범위를 1-2 문장으로 설명]

#### Business Value
[이 Epic이 제공하는 비즈니스 가치]

#### Features
- Feature [번호]: [Feature 이름]
- Feature [번호]: [Feature 이름]
...

#### Success Metrics
- [측정 가능한 성공 지표 1]
- [측정 가능한 성공 지표 2]

#### Timeline
- Start Date: [시작일]
- Target Completion: [목표 완료일]
- Dependencies: [의존성]
```

---

## 다음 단계

1. ✅ **Phase 1 Sprint Planning**
   - Epic 1.1-1.3을 2주 Sprint로 분할
   - Story Point 재조정
   - 개발자 할당

2. ⬜ **Technical Spike**
   - Vector DB 선택 (Pinecone vs. Qdrant) POC
   - LangGraph Agent 프로토타입
   - WebSocket 실시간 통신 테스트

3. ⬜ **Design Review**
   - UI/UX 디자인 (Shadowing Mode Dashboard)
   - API 설계 리뷰
   - 보안 아키텍처 검토

4. ⬜ **Stakeholder Approval**
   - 경영진 승인
   - 예산 확정
   - 팀 구성

---

**문서 버전 히스토리**:
- v2.0 (2026-01-30): Phase 1-4 상세 요구사항 및 User Story 작성
- v1.1 (2026-01-05): 기본 SIP PBX PRD
- v1.0 (2025-10-27): 초기 PRD 생성

**Maintained by**: Product Team  
**Last Updated**: 2026-01-30  
**Next Review**: 2026-02-15
