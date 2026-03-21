# Frontend UI 개선사항 보고서

작성일: 2026-03-06  
대상: `sip-pbx/frontend` (Next.js 14 App Router)

---

## 1. 전체 구조 현황

| 경로 | 설명 | 상태 |
|------|------|------|
| `/login` | 테넌트 선택 로그인 | ✅ 정상 |
| `/dashboard` | 메인 대시보드 | ⚠️ 개선 필요 |
| `/call-history` | 통화 이력 | ⚠️ 개선 필요 |
| `/capabilities` | AI 서비스 관리 | ⚠️ 개선 필요 |
| `/knowledge` | 지식 베이스 | ✅ 양호 |
| `/transfers` | 호 전환 이력 | ⚠️ 개선 필요 |
| `/extractions` | 지식 추출 | 미확인 |
| `/outbound` | AI 발신 | 미확인 |

---

## 2. 실제 출력(데이터) 점검

### 2-1. 활성 통화 (실시간 통화 카드)

**현재 출력 흐름:**
```
GET /api/calls/active (1초 폴링) + WebSocket call_started / call_ended
```

**문제점:**
- `caller.name` / `caller.number`가 SIP URI 그대로 표시됨  
  예: `sip:1004@192.168.1.1` → 표시는 `1004`이나, URI 파싱 실패 시 전체 URI 노출
- `is_ai_handled` 필드가 `false`이면 항상 "일반" 표시 — AI 응대 여부 구분이 시각적으로 약함
- 실시간 대화(STT/TTS)가 WebSocket 연결이 끊기면 전혀 표시 안 됨 (fallback 없음)
- `call_id`가 카드에 작게 표시되어 있어 모바일/작은 화면에서 가독성 저하

**권장 수정:**
```typescript
// extractExtensionFromUri 실패 시 fallback 처리
const callerDisplay = call.caller?.name && call.caller.name !== call.caller.uri
  ? call.caller.name
  : call.caller?.number ?? call.caller?.uri ?? '알 수 없음';
```

---

### 2-2. HITL 대기 카운트 (메트릭 카드)

**현재 출력 흐름:**
```
metrics.hitlQueueSize  ← API /api/metrics/dashboard
hitlRequests.length    ← WebSocket hitl_requested 이벤트 누적
```

**문제점:**
- MetricCard의 `HITL 대기` 값은 `hitlRequests.length` (WebSocket)를 쓰지만,  
  실제 `metrics.hitlQueueSize`는 API 값으로 별도 관리됨 → **두 값이 불일치할 수 있음**
- 페이지 새로고침 시 WebSocket 누적 목록이 초기화되어 0으로 표시됨 (API와 동기화 없음)

**권장 수정:**  
페이지 진입 시 `GET /api/hitl/pending` 또는 `GET /api/metrics/dashboard`를 호출해  
WebSocket 초기 상태를 서버 값으로 동기화.

---

### 2-3. AI 신뢰도 (메트릭 카드)

**현재 출력:**
```typescript
value={metrics.avgAIConfidence > 0 ? `${metrics.avgAIConfidence}%` : '-'}
```

**문제점:**
- 데이터가 없으면 `-`만 표시 — 사용자가 API 연동 실패인지, 데이터 없음인지 구분 불가
- `avgAIConfidence`가 소수(예: 0.87)로 오면 `87%`가 아닌 `0.87%`로 표시될 수 있음  
  ← API 응답값이 `0~1` 또는 `0~100` 중 어느 것인지 명확히 문서화 필요

---

### 2-4. 확인 필요(후처리) 목록

**현재 출력 흐름:**
```
GET /api/call-history/follow-ups?callee={owner}&status={filter} (15초 폴링)
```

**문제점:**
- 테이블 컬럼 `통화 ID`가 `font-mono text-xs`로 매우 작게 표시됨  
  → 긴 UUID가 잘리지 않아 가로 스크롤 발생
- `user_question` / `ai_response` 컬럼이 `max-w-[200px] truncate`로 잘림  
  → hover `title` 속성으로 full text 볼 수 있으나, 클릭해서 상세 팝업 여는 기능 없음
- 상태 변경 버튼(`메모`, `연락 완료`, `처리 완료`)이 현재 상태와 같으면 숨겨지지만,  
  조건이 복잡해 UX가 직관적이지 않음

---

### 2-5. 통화 이력 페이지 (`/call-history`)

**현재 출력 흐름:**
```
GET /api/call-history?page=1&limit=50&callee={owner}&unresolved_hitl={filter}
```

**문제점:**
- `start_time`이 ISO string이 아닌 경우 `format(new Date(null), ...)` 에러 발생 가능  
  → `try-catch` 또는 optional chaining 처리 필요
- 녹음 파일 재생(`<audio>` 태그)에서 파일 없음 처리를 DOM 직접 조작으로 구현:
  ```typescript
  (e.target as HTMLAudioElement).style.display = 'none';
  const msg = parent?.querySelector('.recording-unavailable');
  if (msg) (msg as HTMLElement).style.display = 'block';
  ```
  → React 방식(`useState`로 `hasError` 상태 관리)으로 교체 권장
- 페이지네이션 없음 — `limit=50`으로 고정되어 있어 대량 데이터 시 누락 발생
- 헤더 네비게이션이 `dashboard`에만 있고 `call-history`에는 없음 → 뒤로가기 버튼 없음

---

### 2-6. 호 전환 이력 (`/transfers`)

**현재 출력 흐름:**
```
GET /api/transfers/?state={filter} + GET /api/transfers/stats (5초 폴링)
```

**문제점:**
- 인증 헤더 없이 API 호출:
  ```typescript
  // ❌ axios.get 에 Authorization 헤더 없음
  const [transfersRes, statsRes] = await Promise.all([
    axios.get(`${API_BASE}/api/transfers/${stateParam}`),
    axios.get(`${API_BASE}/api/transfers/stats`),
  ]);
  ```
  → 백엔드가 인증을 요구하면 401 에러로 데이터 미출력
- 헤더 네비게이션에 `AI 발신`, `지식 추출` 메뉴 누락 (대시보드에는 있음)
- 에러 발생 시 사용자에게 아무런 피드백 없음 (`console.error`만 호출)

---

### 2-7. 운영자 상태 토글 (`OperatorStatusToggle`)

**현재 출력 흐름:**
```
GET /api/operator/status (마운트 시 1회) → Zustand store 업데이트
```

**문제점:**
- `useOperatorStore`에서 `localStorage.getItem('token')`을 사용하나,  
  로그인 시 `access_token`과 `token` 두 키에 모두 저장함 → 일관성 문제 없으나 혼용은 위험
- `BUSY` / `OFFLINE` 상태에 대한 UI 처리 없음 — 토글은 `AVAILABLE ↔ AWAY`만 지원
- 상태 변경 성공 후 `fetchStatus()` 재호출 없음 → `unresolvedHITLCount`가 낡은 값일 수 있음

---

## 3. 디자인 개선사항

### 3-1. 전역 네비게이션 일관성 문제

**현재 상황:**
- `dashboard/page.tsx`: 전체 네비게이션(7개 메뉴) + 테넌트 정보 + 연결 상태 + 로그아웃
- `transfers/page.tsx`: 부분 네비게이션(6개 메뉴, `AI 발신` 누락), 테넌트 정보 없음
- `knowledge/page.tsx`: 네비게이션 없음 (헤더에 페이지 제목만)
- `capabilities/page.tsx`: 네비게이션 없음 (`대시보드` 뒤로가기 버튼만)
- `call-history/page.tsx`: 네비게이션 없음

**권장 수정:**  
공통 레이아웃 컴포넌트 `components/AppLayout.tsx`를 만들어 `app/layout.tsx`에서 활용하거나,  
각 페이지 헤더에 동일한 `<nav>` 구조를 적용.

```typescript
// components/AppLayout.tsx (신규 작성 권장)
export function AppLayout({ children, currentPath }: { children: React.ReactNode; currentPath: string }) {
  return (
    <>
      <AppHeader currentPath={currentPath} />
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {children}
      </main>
    </>
  );
}
```

---

### 3-2. 메트릭 카드 디자인

**현재:** 카드 배경이 색상(`bg-blue-50`, `bg-orange-50` 등)이고 섀도우도 동일  
**문제:** HITL 긴급 시 `animate-pulse`가 카드 전체에 적용되어 화면 깜빡임이 과함

**권장:** 긴급 표시는 카드 테두리 + 아이콘에만 pulse 적용

```typescript
// 현재
orange: urgent ? 'bg-orange-50 text-orange-600 animate-pulse' : 'bg-orange-50 text-orange-600',

// 권장
<div className={`rounded-lg shadow p-6 ${urgent ? 'ring-2 ring-orange-500' : ''} ${colorClasses[color]}`}>
  {urgent && <span className="w-2 h-2 rounded-full bg-orange-600 animate-pulse absolute top-3 right-3" />}
```

---

### 3-3. 실시간 통화 카드 대화 UI

**현재:** 대화 말풍선이 `bg-blue-100 text-blue-900` (발신) / `bg-green-100 text-green-900` (AI)  
배경색 대비가 낮아 긴 텍스트에서 가독성 저하

**권장:**
- 발신자: `bg-blue-500 text-white` (LiveCallMonitor와 동일하게)
- AI: `bg-emerald-500 text-white`
- 타임스탬프 표시 추가 (현재 dashboard 카드 내 대화에는 타임스탬프 없음)

---

### 3-4. 빈 상태(Empty State) UI

**현재:**  
```jsx
<p className="text-gray-500 text-center py-8">현재 활성 통화가 없습니다</p>
```

**문제:** 텍스트만 있어 UI가 허전하고 상태가 "정상적으로 빈 것"인지 "로딩 중"인지 불분명

**권장:** 아이콘 + 설명 텍스트 조합으로 개선

```jsx
<div className="text-center py-12">
  <div className="text-4xl mb-3">📵</div>
  <p className="text-gray-600 font-medium">현재 활성 통화가 없습니다</p>
  <p className="text-gray-400 text-sm mt-1">새 통화가 시작되면 자동으로 표시됩니다</p>
</div>
```

---

### 3-5. 로딩 상태

**현재:**  
`call-history`, `knowledge`, `capabilities` 모두 `로딩 중...` 텍스트만 표시

**권장:** Skeleton 컴포넌트(`components/ui/skeleton.tsx`) 활용

```jsx
// 예: 통화 이력 로딩 시
{isLoading && (
  <div className="space-y-3">
    {[1,2,3].map(i => (
      <Skeleton key={i} className="h-16 w-full rounded-lg" />
    ))}
  </div>
)}
```

---

### 3-6. 모바일 반응형

**현재 문제:**
- 메트릭 카드: `grid-cols-4` 고정 → 모바일에서 카드가 너무 작아짐  
  (사실 `grid-cols-1 md:grid-cols-2 lg:grid-cols-4`로 이미 처리되어 있으나 확인 필요)
- capabilities 목록 테이블 헤더: `grid-cols-12` 고정 → 모바일 깨짐
- transfers 테이블: `min-w-full`만 설정 → 가로 스크롤 컨테이너 필요  
  ```jsx
  // 현재: <div className="bg-white rounded-lg shadow overflow-hidden">
  // 권장: <div className="bg-white rounded-lg shadow overflow-x-auto">
  ```

---

## 4. 코드 품질 이슈

### 4-1. 타입 안정성

| 위치 | 문제 |
|------|------|
| `LiveCallMonitor.tsx:36` | `data: any` 타입 사용 |
| `LiveCallMonitor.tsx:56` | `data: any` 타입 사용 |
| `HITLDialog.tsx:105` | `msg: any` 타입 사용 |
| `useHITL` 훅 | `requests: any[]` 타입 사용 |

**권장:** `types/index.ts`에 정의된 타입을 활용하고 `any` 제거

---

### 4-2. 중복 코드: 헤더 네비게이션

`dashboard/page.tsx`와 `transfers/page.tsx`에 동일한 `<header>` + `<nav>` 구조가 중복.  
**권장:** `components/AppHeader.tsx` 공통 컴포넌트 추출

---

### 4-3. API URL 환경변수

`dashboard/page.tsx`: `const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';`  
일부 페이지는 컴포넌트 내부, 일부는 모듈 최상단에 선언됨 → `lib/api.ts`로 통합 권장

---

### 4-4. fetchActiveCalls 경쟁 조건

`dashboard/page.tsx`의 `fetchActiveCalls`에서:
```typescript
// API 빈 배열 시 기존 목록 유지 (의도적)
if (items.length === 0) return prev;
```
→ 실제 통화가 모두 종료되어 빈 배열이 와도 목록이 지워지지 않는 문제.  
`call_ended` WebSocket 이벤트와 폴링이 모두 작동하면 무관하나,  
WebSocket 끊김 상태에서는 종료된 통화가 계속 표시될 수 있음.

---

## 5. 우선순위별 정리

### 즉시 수정 (버그 수준)

| # | 위치 | 문제 | 난이도 |
|---|------|------|--------|
| 1 | `transfers/page.tsx` | Authorization 헤더 누락 → 401 에러로 데이터 미출력 | 낮음 |
| 2 | `call-history/page.tsx` | `new Date(null)` 에러 위험 (start_time 없을 때) | 낮음 |
| 3 | `call-history/page.tsx` | 녹음 오류 처리 DOM 직접 조작 → React 상태 관리로 교체 | 낮음 |
| 4 | Dashboard | HITL 카운트 불일치 (WebSocket vs API 값) | 중간 |

### 중요 개선 (UX)

| # | 위치 | 문제 | 난이도 |
|---|------|------|--------|
| 5 | 전체 페이지 | 공통 헤더/네비게이션 컴포넌트 부재 | 중간 |
| 6 | Dashboard | 실시간 대화 말풍선 대비 개선 | 낮음 |
| 7 | 전체 | 로딩 상태 Skeleton UI | 낮음 |
| 8 | 전체 | 빈 상태 UI 개선 (아이콘 + 설명) | 낮음 |
| 9 | `call-history/page.tsx` | 페이지네이션 추가 | 중간 |

### 장기 개선

| # | 위치 | 문제 | 난이도 |
|---|------|------|--------|
| 10 | 전체 | `any` 타입 제거 → 명시적 타입 지정 | 중간 |
| 11 | `dashboard/page.tsx` | WebSocket 끊김 시 폴링 fallback 강화 | 중간 |
| 12 | 모바일 | Capabilities / Transfers 테이블 반응형 개선 | 중간 |
| 13 | Dashboard | `avgAIConfidence` 단위 명확화 (0~1 vs 0~100) | 낮음 |

---

## 6. 출력이 정말 되는지 점검 결과

| 기능 | WebSocket 연결 | WebSocket 끊김 | 비고 |
|------|---------------|----------------|------|
| 활성 통화 목록 | ✅ 실시간 | ✅ 1초 폴링 | 정상 |
| 실시간 대화(STT/TTS) | ✅ 실시간 | ❌ 표시 안 됨 | fallback 없음 |
| HITL 대기 목록 | ✅ 실시간 | ❌ 재로드 시 초기화 | 서버 동기화 필요 |
| 운영자 상태 | ✅ API 폴링 | ✅ API 폴링 | 정상 |
| 통화 이력 | ✅ API | ✅ API | 페이지네이션 없음 |
| 호 전환 이력 | ✅ 5초 폴링 | ✅ 5초 폴링 | **인증 헤더 없음 → 실제 출력 안 될 수 있음** |
| 지식 베이스 | ✅ API | ✅ API | 정상 |
| AI 서비스 | ✅ API | ✅ API | 정상 |
| 녹음 재생 | ✅ `<audio>` | ✅ `<audio>` | 에러 처리 방식 개선 필요 |
| AI 신뢰도 | ⚠️ 미연결 시 `-` | ⚠️ 미연결 시 `-` | 단위 불명확 |

---

## 부록: 스크린샷 기준 현재 UI 상태

현재 `localhost:3000/dashboard` 스크린샷에서 확인된 표시 항목:

- **기상청(1004)** 테넌트로 로그인됨 ✅
- **활성 통화: 0**, **HITL 대기: 0**, **AI 신뢰도: -**, **오늘 통화: 0** ✅ (초기 상태 정상)
- **WebSocket: 연결됨** 표시 ✅
- **운영자 상태: 대기중** ✅
- **실시간 통화 영역**: `WebSocket 연결됨 — 각 카드에 실시간 대화(STT·AI 응답)가 바로 표시됩니다` 텍스트 표시 ✅
- **도움 요청**: `대기 중인 요청이 없습니다` ✅
- **확인 필요(후처리)**: `확인 필요 건이 없습니다` ✅

**결론: 현재 UI는 초기 상태에서 정상 출력됨. 다만 실제 통화 데이터 입력 시 위 점검 항목들의 문제가 노출될 수 있음.**
