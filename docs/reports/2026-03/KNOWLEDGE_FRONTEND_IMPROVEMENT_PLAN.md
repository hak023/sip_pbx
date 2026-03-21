---
title: 지식베이스 Frontend 개선 계획
date: 2026-03-11
type: implementation_plan
status: PLANNED
---

# 지식베이스 Frontend 개선 계획

## 🎯 목표

**현재**: Frontend가 "연락처 관리"만 표시
**개선**: 통합 지식베이스 대시보드 (통화 지식 + 연락처 + 통계)

---

## 📋 구현 체크리스트

### Phase 1: Backend API 추가 ✅

#### 1.1 지식 목록 조회 API

**엔드포인트**: `GET /api/knowledge`

**요청**:
```
?tenant_id=1004&page=1&limit=20
```

**응답**:
```json
{
  "total": 123,
  "page": 1,
  "limit": 20,
  "items": [
    {
      "id": "abc-123_chunk_0_0",
      "text": "영업시간은 평일 9시부터 6시까지입니다.",
      "category": "영업시간",
      "keywords": ["시간", "운영"],
      "confidence": 0.85,
      "call_id": "abc-123",
      "created_at": "2026-03-10T14:30:00Z"
    }
  ]
}
```

**구현 위치**: `src/api/routers/knowledge.py`

---

#### 1.2 지식 통계 API

**엔드포인트**: `GET /api/knowledge/stats`

**요청**:
```
?tenant_id=1004
```

**응답**:
```json
{
  "total_knowledge": 1234,
  "this_week": 45,
  "categories": {
    "영업시간": 234,
    "배송": 189,
    "반품": 145,
    "기타": 666
  },
  "avg_confidence": 0.82,
  "recent_extractions": [
    {
      "call_id": "abc-123",
      "extracted_count": 3,
      "timestamp": "2026-03-10T14:30:00Z"
    }
  ]
}
```

**구현 위치**: `src/api/routers/knowledge.py`

---

#### 1.3 지식 검색 API

**엔드포인트**: `POST /api/knowledge/search`

**요청**:
```json
{
  "tenant_id": "1004",
  "query": "영업시간이 어떻게 되나요?",
  "top_k": 10
}
```

**응답**:
```json
{
  "query": "영업시간이 어떻게 되나요?",
  "results": [
    {
      "id": "abc-123_chunk_0_0",
      "text": "영업시간은 평일 9시부터 6시까지입니다.",
      "score": 0.92,
      "category": "영업시간",
      "metadata": {
        "call_id": "abc-123",
        "speaker": "callee"
      }
    }
  ]
}
```

**구현 위치**: `src/api/routers/knowledge.py`

---

### Phase 2: Frontend 탭 구조 개선

#### 2.1 페이지 구조 변경

**현재**: `frontend/app/knowledge/page.tsx` (연락처만)

**개선**: 탭 기반 통합 UI

```tsx
export default function KnowledgePage() {
  const [activeTab, setActiveTab] = useState<'knowledge' | 'contacts' | 'stats'>('knowledge');
  
  return (
    <div className="min-h-screen bg-gray-100 p-6">
      <div className="max-w-7xl mx-auto">
        {/* 헤더 */}
        <h1 className="text-3xl font-bold text-gray-900 mb-6">
          지식베이스 관리
        </h1>
        
        {/* 탭 네비게이션 */}
        <div className="bg-white rounded-lg shadow-md mb-6">
          <div className="border-b border-gray-200">
            <nav className="flex space-x-8 px-6">
              <button
                onClick={() => setActiveTab('knowledge')}
                className={`py-4 px-1 border-b-2 font-medium ${
                  activeTab === 'knowledge'
                    ? 'border-blue-500 text-blue-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700'
                }`}
              >
                📚 통화 지식
              </button>
              <button
                onClick={() => setActiveTab('contacts')}
                className={`py-4 px-1 border-b-2 font-medium ${
                  activeTab === 'contacts'
                    ? 'border-blue-500 text-blue-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700'
                }`}
              >
                📞 연락처
              </button>
              <button
                onClick={() => setActiveTab('stats')}
                className={`py-4 px-1 border-b-2 font-medium ${
                  activeTab === 'stats'
                    ? 'border-blue-500 text-blue-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700'
                }`}
              >
                📊 통계
              </button>
            </nav>
          </div>
        </div>
        
        {/* 탭 컨텐츠 */}
        {activeTab === 'knowledge' && <KnowledgeListTab tenantId={tenantId} />}
        {activeTab === 'contacts' && <ContactsTab tenantId={tenantId} />}
        {activeTab === 'stats' && <StatsTab tenantId={tenantId} />}
      </div>
    </div>
  );
}
```

---

#### 2.2 통화 지식 탭 (`KnowledgeListTab`)

**기능**:
- 저장된 지식 목록 표시
- 페이지네이션
- 카테고리별 필터링
- 검색 기능

**UI 구성**:
```tsx
export function KnowledgeListTab({ tenantId }: { tenantId: string }) {
  const [knowledge, setKnowledge] = useState<Knowledge[]>([]);
  const [page, setPage] = useState(1);
  const [searchQuery, setSearchQuery] = useState('');
  
  return (
    <div className="bg-white rounded-lg shadow-md p-6">
      {/* 검색 바 */}
      <div className="mb-6">
        <div className="flex gap-4">
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="지식 검색..."
            className="flex-1 px-4 py-2 border rounded-lg"
          />
          <button
            onClick={handleSearch}
            className="px-6 py-2 bg-blue-600 text-white rounded-lg"
          >
            검색
          </button>
        </div>
      </div>
      
      {/* 지식 목록 */}
      <div className="space-y-4">
        {knowledge.map((item) => (
          <div key={item.id} className="border rounded-lg p-4">
            <div className="flex justify-between items-start mb-2">
              <div>
                <span className="px-2 py-1 text-xs bg-blue-100 text-blue-800 rounded">
                  {item.category}
                </span>
                <span className="ml-2 text-sm text-gray-500">
                  신뢰도: {(item.confidence * 100).toFixed(0)}%
                </span>
              </div>
              <span className="text-sm text-gray-500">
                {new Date(item.created_at).toLocaleDateString('ko-KR')}
              </span>
            </div>
            <p className="text-gray-800">{item.text}</p>
            <div className="mt-2 flex gap-2">
              {item.keywords.map((kw, idx) => (
                <span key={idx} className="text-xs text-gray-600">
                  #{kw}
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
      
      {/* 페이지네이션 */}
      <div className="mt-6 flex justify-center gap-2">
        <button
          onClick={() => setPage(page - 1)}
          disabled={page === 1}
          className="px-4 py-2 border rounded-lg disabled:opacity-50"
        >
          이전
        </button>
        <span className="px-4 py-2">{page}</span>
        <button
          onClick={() => setPage(page + 1)}
          className="px-4 py-2 border rounded-lg"
        >
          다음
        </button>
      </div>
    </div>
  );
}
```

---

#### 2.3 연락처 탭 (`ContactsTab`)

**기존 코드 이동**:
현재 `page.tsx`의 연락처 관리 코드를 `ContactsTab` 컴포넌트로 분리

```tsx
export function ContactsTab({ tenantId }: { tenantId: string }) {
  // 기존 page.tsx의 연락처 관리 로직 이동
  // ...
}
```

---

#### 2.4 통계 탭 (`StatsTab`)

**기능**:
- 전체 지식 개수
- 이번 주 추가된 지식
- 카테고리별 분포
- 최근 추출 내역

**UI 구성**:
```tsx
export function StatsTab({ tenantId }: { tenantId: string }) {
  const [stats, setStats] = useState<Stats | null>(null);
  
  useEffect(() => {
    fetch(`http://localhost:8000/api/knowledge/stats?tenant_id=${tenantId}`)
      .then(res => res.json())
      .then(setStats);
  }, [tenantId]);
  
  if (!stats) return <div>로딩 중...</div>;
  
  return (
    <div className="space-y-6">
      {/* 전체 통계 카드 */}
      <div className="grid grid-cols-3 gap-6">
        <div className="bg-white rounded-lg shadow-md p-6">
          <div className="text-sm text-gray-500 mb-2">총 지식</div>
          <div className="text-3xl font-bold text-gray-900">
            {stats.total_knowledge.toLocaleString()}
          </div>
        </div>
        <div className="bg-white rounded-lg shadow-md p-6">
          <div className="text-sm text-gray-500 mb-2">이번 주 추가</div>
          <div className="text-3xl font-bold text-blue-600">
            +{stats.this_week}
          </div>
        </div>
        <div className="bg-white rounded-lg shadow-md p-6">
          <div className="text-sm text-gray-500 mb-2">평균 신뢰도</div>
          <div className="text-3xl font-bold text-green-600">
            {(stats.avg_confidence * 100).toFixed(0)}%
          </div>
        </div>
      </div>
      
      {/* 카테고리별 분포 */}
      <div className="bg-white rounded-lg shadow-md p-6">
        <h3 className="text-lg font-bold mb-4">카테고리별 분포</h3>
        <div className="space-y-3">
          {Object.entries(stats.categories).map(([category, count]) => (
            <div key={category} className="flex items-center">
              <div className="w-24 text-sm text-gray-600">{category}</div>
              <div className="flex-1 bg-gray-200 rounded-full h-6 relative">
                <div
                  className="bg-blue-500 h-6 rounded-full"
                  style={{
                    width: `${(count / stats.total_knowledge) * 100}%`
                  }}
                />
                <span className="absolute inset-0 flex items-center justify-center text-xs font-medium">
                  {count}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>
      
      {/* 최근 추출 내역 */}
      <div className="bg-white rounded-lg shadow-md p-6">
        <h3 className="text-lg font-bold mb-4">최근 지식 추출</h3>
        <div className="space-y-2">
          {stats.recent_extractions.map((extraction, idx) => (
            <div key={idx} className="flex justify-between items-center py-2 border-b">
              <div>
                <span className="text-sm font-medium">통화 {extraction.call_id}</span>
                <span className="ml-2 text-sm text-gray-500">
                  {extraction.extracted_count}개 추출
                </span>
              </div>
              <span className="text-sm text-gray-500">
                {new Date(extraction.timestamp).toLocaleString('ko-KR')}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
```

---

## 📦 파일 구조

### 변경 전
```
frontend/app/knowledge/
└── page.tsx  (연락처만)
```

### 변경 후
```
frontend/
├── app/knowledge/
│   └── page.tsx  (탭 네비게이션)
├── components/knowledge/
│   ├── KnowledgeListTab.tsx
│   ├── ContactsTab.tsx
│   └── StatsTab.tsx
└── types/
    └── knowledge.ts  (타입 정의)
```

---

## 🎨 TypeScript 타입 정의

```typescript
// frontend/types/knowledge.ts

export interface Knowledge {
  id: string;
  text: string;
  category: string;
  keywords: string[];
  confidence: number;
  call_id: string;
  created_at: string;
}

export interface KnowledgeStats {
  total_knowledge: number;
  this_week: number;
  categories: Record<string, number>;
  avg_confidence: number;
  recent_extractions: Array<{
    call_id: string;
    extracted_count: number;
    timestamp: string;
  }>;
}

export interface Contact {
  id: string;
  tenant_id: string;
  department: string;
  keywords: string[];
  phone_number: string;
  description: string;
  available_hours: string;
  auto_transfer: boolean;
  priority: string;
}
```

---

## ✅ 최종 체크리스트

### Backend
- [ ] `GET /api/knowledge` 구현
- [ ] `GET /api/knowledge/stats` 구현
- [ ] `POST /api/knowledge/search` 구현
- [ ] ChromaDB 조회 로직 추가
- [ ] API 테스트

### Frontend
- [ ] 타입 정의 추가 (`types/knowledge.ts`)
- [ ] 탭 네비게이션 구현 (`page.tsx`)
- [ ] `KnowledgeListTab` 컴포넌트 생성
- [ ] `ContactsTab` 컴포넌트 분리
- [ ] `StatsTab` 컴포넌트 생성
- [ ] API 연동
- [ ] UI 테스트

---

## 🚀 구현 우선순위

### P0 (필수)
1. Backend API 3개 구현
2. 탭 네비게이션 추가
3. 통화 지식 탭 기본 기능

### P1 (권장)
1. 통계 탭
2. 검색 기능

### P2 (선택)
1. 카테고리 필터링
2. 지식 상세 보기
3. 수동 지식 추가/수정/삭제

---

**작성일**: 2026-03-11  
**상태**: 🟡 **계획 단계 - 구현 대기 중**
