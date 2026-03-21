---
title: 지식베이스 설계 점검 및 개선 방안
date: 2026-03-11
type: architecture_review
severity: HIGH
status: NEEDS_IMPROVEMENT
---

# 지식베이스 설계 점검 및 개선 방안

## 🎯 지식베이스의 진짜 목적

### 핵심 개념

**지식베이스 = RAG (Retrieval Augmented Generation) 기반 테넌트별 지식 관리 시스템**

1. **일반 유저간 통화 → 지식 저장**
   - 통화 내용을 LLM으로 분석
   - 유용한 정보 추출
   - 청킹 + 임베딩
   - ChromaDB에 저장 (테넌트별 분리)

2. **AI 응대 → 지식 활용**
   - 사용자 질문 수신
   - 임베딩 + 벡터 검색 (ChromaDB)
   - 관련 지식 조회 (테넌트별)
   - LLM에 컨텍스트 제공 → 정확한 응답

3. **추가 기능: 연락처 관리**
   - 호 전환용 연락처 정보
   - 지식베이스의 **일부 기능**

---

## ✅ 현재 구현 상태

### 1. 백엔드 - 지식 추출 (Knowledge Extractor) ✅

**파일**: `src/ai_voicebot/knowledge/knowledge_extractor.py`

**기능**:
- ✅ 통화 전사 텍스트 로드
- ✅ 화자별 필터링
- ✅ LLM 지식 정제 (유용성 판단)
- ✅ 텍스트 청킹
- ✅ 임베딩 생성
- ✅ ChromaDB 저장 (테넌트별 메타데이터 포함)

**워크플로우**:
```python
# 통화 종료 후 자동 실행
await knowledge_extractor.extract_from_call(
    call_id=call_id,
    transcript_path=transcript_path,
    owner_id=owner_id,  # 테넌트 ID
    speaker="callee"    # 착신자 발화
)
```

**저장 메타데이터**:
```json
{
  "call_id": "abc-123",
  "owner": "1004",          // ⭐ 테넌트별 분리
  "speaker": "callee",
  "category": "영업시간",
  "keywords": ["시간", "운영"],
  "chunk_index": 0,
  "confidence": 0.85,
  "contains_pii": false,
  "extraction_source": "call"
}
```

### 2. 백엔드 - 지식 검색 (RAG Engine) ✅

**파일**: `src/ai_voicebot/ai_pipeline/rag_engine.py`

**기능**:
- ✅ 사용자 질문 임베딩
- ✅ ChromaDB 벡터 검색
- ✅ 테넌트별 필터링 (`owner` 메타데이터)
- ✅ 관련 지식 조회
- ✅ LLM 컨텍스트 구성

**워크플로우**:
```python
# AI 응대 중 실시간 실행
context = await rag_engine.retrieve(
    query="영업시간이 어떻게 되나요?",
    tenant_id="1004",  # ⭐ 테넌트별 검색
    top_k=3
)
# → ChromaDB에서 테넌트 1004의 지식만 검색
# → LLM에 컨텍스트 제공
```

### 3. 백엔드 - 연락처 관리 (Contact Extractor) ✅

**파일**: `src/ai_voicebot/knowledge/contact_extractor.py`

**기능**:
- ✅ 연락처 인덱싱 (JSON → ChromaDB)
- ✅ 연락처 검색 (키워드/벡터)
- ✅ AI 호 전환용

**목적**: **지식베이스의 일부 - 호 전환 전용**

### 4. Frontend - 문제 발견! ❌

**파일**: `frontend/app/knowledge/page.tsx`

**현재 상태**:
```tsx
<h1>지식베이스 - 연락처 관리</h1>
// ❌ 연락처 관리만 표시
// ❌ RAG 지식 조회/관리 기능 없음
```

**문제점**:
1. ❌ **페이지 제목이 잘못됨**: "연락처 관리"가 전부로 보임
2. ❌ **RAG 지식 조회 기능 없음**: 저장된 지식 확인 불가
3. ❌ **지식 통계 없음**: 얼마나 많은 지식이 저장되었는지 확인 불가
4. ❌ **테넌트별 지식 관리 UI 없음**: 테넌트 특성 확인 불가

---

## 🔍 점검 결과

### 1. 일반 유저간 통화 시 Knowledge 저장 ✅

**점검 항목**:
- ✅ 통화 종료 시 `knowledge_extractor.extract_from_call()` 호출되는가?
- ✅ LLM이 유용성을 판단하는가?
- ✅ ChromaDB에 저장되는가?
- ✅ 테넌트별로 분리 저장되는가?

**실제 구현 확인**:

1. **통화 종료 시점** (`sip_endpoint.py:2238-2244`):
```python
if recording_dir_name and has_transcript and not is_ai_call:
    # 일반 SIP 통화 + transcript 존재 시에만 Knowledge Extraction 수행
    await self._call_manager.trigger_knowledge_extraction(
        call_id=original_call_id,
        recording_dir_name=recording_dir_name,
        callee_username=call_info.get('callee_username', 'unknown')
    )
```

2. **지식 추출 실행** (`call_manager.py:1207-1211`):
```python
await self.knowledge_extractor.extract_from_call(
    call_id=call_id,
    transcript_path=str(transcript_path),
    owner_id=callee_id,  # ⭐ 테넌트 ID (sip:1004@unknown)
    speaker="both"  # ✅ 발신자+착신자 모두 추출
)
```

3. **LLM 유용성 판단** (`knowledge_extractor.py:150-154`):
```python
judgment = await self.llm.judge_usefulness(
    transcript=transcript,
    speaker=speaker,
    call_id=call_id,
)
```

4. **ChromaDB 저장** (`knowledge_extractor.py:266-271`):
```python
await self.vector_db.upsert(
    doc_id=doc_id,
    embedding=embedding,
    text=chunk,
    metadata={
        "call_id": call_id,
        "owner": owner_id,  # ⭐ 테넌트별 분리
        "speaker": speaker,
        "category": category,
        ...
    }
)
```

**결론**: ✅ **완벽하게 작동 중**

---

### 2. AI 응대 시 RAG 활용 ✅

**점검 항목**:
- ✅ AI 응대 중 사용자 질문 수신 시 RAG Engine 호출되는가?
- ✅ 테넌트별로 지식 검색되는가?
- ✅ LLM에 컨텍스트가 제공되는가?

**실제 구현 확인**:

1. **LangGraph Agent 초기화** (`rag_processor.py:113-122`):
```python
from src.ai_voicebot.langgraph.agent import ConversationAgent
self._agent = ConversationAgent(
    llm_client=llm_client,
    rag_engine=rag_engine,  # ⭐ RAG Engine 주입
    embedder=embedder,
    vector_db=vector_db,
    org_manager=org_manager,
    owner=owner,  # ⭐ 착신번호 (테넌트 ID)
)
```

2. **LangGraph 워크플로우** (`agent.py:160-174`):
```python
# classify_intent → check_cache → rewrite_query → adaptive_rag
graph.add_edge("rewrite_query", "adaptive_rag")

# adaptive_rag → generate_response
graph.add_conditional_edges(
    "adaptive_rag",
    _route_after_rag,
    {
        "step_back": "step_back",
        "generate_response": "generate_response",
    },
)
```

3. **Adaptive RAG 검색** (`adaptive_rag.py:45-52`):
```python
# 1단계: Small (Sentence) Retrieval (owner_filter로 테넌트 격리)
search_results = await rag_engine.search(
    query,
    owner_filter=owner,  # ⭐ 테넌트별 검색
    call_id=call_id or None,
    top_k_override=SENTENCE_TOP_K,
)
```

4. **RAG Engine 검색** (`rag_engine.py:88-94`):
```python
# 2. Vector DB 검색
effective_top_k = top_k_override if top_k_override else self.top_k
filter_dict = {"owner": owner_filter} if owner_filter else None  # ⭐ 테넌트 필터
search_results = await self.vector_db.search(
    vector=query_embedding,
    top_k=effective_top_k * 2,
    filter=filter_dict  # ⭐ 테넌트별 격리 검색
)
```

5. **LLM 컨텍스트 제공** (`generate_response.py:30-40`):
```python
# RAG 결과를 LLM 프롬프트에 포함
rag_results = state.get("rag_results", [])
if rag_results:
    context_text = "\n\n".join([
        f"- {doc['text']}" for doc in rag_results
    ])
    prompt = f"""
사용자 질문: {user_query}

관련 지식:
{context_text}

위 지식을 활용하여 답변하세요.
"""
```

**결론**: ✅ **완벽하게 작동 중**

---

## ❌ 개선 필요 사항

### 1. Frontend 페이지 개선

**현재**: 연락처 관리만

**개선안**: **통합 지식베이스 대시보드**

```
┌─────────────────────────────────────────┐
│ 지식베이스 관리                         │
├─────────────────────────────────────────┤
│ [통화 지식] [연락처] [통계]            │  ← 탭
├─────────────────────────────────────────┤
│                                         │
│ 📊 지식 통계                            │
│   • 총 지식: 1,234개                   │
│   • 이번 주: +45개                     │
│   • 카테고리: 영업시간(234), ...       │
│                                         │
│ 🔍 지식 검색                            │
│   [검색어 입력...]                      │
│                                         │
│ 📚 최근 저장된 지식                     │
│   1. "영업시간은 9시부터 ..." (2026-03-10) │
│   2. "배송은 영업일 기준 ..." (2026-03-09) │
│                                         │
└─────────────────────────────────────────┘
```

### 2. 지식 조회 API 추가

**필요한 엔드포인트**:
```python
# src/api/routers/knowledge.py

@router.get("/knowledge")
async def get_knowledge_list(
    tenant_id: str,
    page: int = 1,
    limit: int = 20
):
    """테넌트의 저장된 지식 목록 조회"""
    # ChromaDB에서 조회
    pass

@router.get("/knowledge/stats")
async def get_knowledge_stats(tenant_id: str):
    """테넌트의 지식 통계"""
    # 총 개수, 카테고리별 개수, 최근 추가된 지식 등
    pass

@router.post("/knowledge/search")
async def search_knowledge(
    tenant_id: str,
    query: str,
    top_k: int = 10
):
    """지식 검색 (벡터 검색)"""
    # RAG Engine 활용
    pass
```

### 3. Frontend 탭 구조 개선

```tsx
// frontend/app/knowledge/page.tsx

export default function KnowledgePage() {
  const [activeTab, setActiveTab] = useState<'knowledge' | 'contacts' | 'stats'>('knowledge');
  
  return (
    <div>
      <h1>지식베이스 관리</h1>
      
      {/* 탭 */}
      <Tabs value={activeTab} onChange={setActiveTab}>
        <Tab value="knowledge">통화 지식</Tab>
        <Tab value="contacts">연락처</Tab>
        <Tab value="stats">통계</Tab>
      </Tabs>
      
      {/* 컨텐츠 */}
      {activeTab === 'knowledge' && <KnowledgeList />}
      {activeTab === 'contacts' && <ContactsList />}
      {activeTab === 'stats' && <KnowledgeStats />}
    </div>
  );
}
```

---

## 📋 최종 체크리스트

### ✅ 이미 완성된 기능

- [x] 일반 통화 → 지식 추출 → ChromaDB 저장
- [x] 테넌트별 지식 분리 저장
- [x] AI 응대 → RAG 기반 지식 검색
- [x] 테넌트별 지식 검색
- [x] LLM 컨텍스트 제공
- [x] 연락처 관리 (호 전환용)

### ❌ 개선 필요

- [ ] Frontend: 지식 조회 UI
- [ ] Frontend: 지식 통계 UI
- [ ] Frontend: 지식 검색 UI
- [ ] Backend API: 지식 목록 조회
- [ ] Backend API: 지식 통계
- [ ] Backend API: 지식 검색

---

## 🎯 결론

### 백엔드 아키텍처: ✅ 완벽

- Knowledge Extractor ✅
- RAG Engine ✅
- Contact Extractor ✅
- ChromaDB 통합 ✅
- 테넌트별 분리 ✅

### Frontend: ❌ 개선 필요

**현재**: 연락처 관리만 표시
**필요**: 통합 지식베이스 대시보드

**다음 단계**:
1. 지식 조회 API 구현
2. Frontend 탭 구조 추가
3. 지식 통계 대시보드 구현

---

**작성일**: 2026-03-11  
**상태**: 🟡 **백엔드 완성, Frontend 개선 필요**
