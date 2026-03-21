# API–Frontend 갭 전면 연동 구현 제안 (UI/UX 포함)

**작성일**: 2026-03  
**근거**: [API_FRONTEND_GAP_INSPECTION.md](./API_FRONTEND_GAP_INSPECTION.md)  
**목표**: 점검 문서의 **미연동 10개 엔드포인트**를 모두 반영하고, 기존 프론트(인디고·화이트·카드형)와 맞는 **일관된 UI/UX**로 구성한다.

---

## 1. 설계 원칙 (깔끔한 UI/UX)

| 원칙 | 적용 |
|------|------|
| **한 앱 셸** | `AppShell` + `AppHeader` 유지. 새 기능은 **같은 헤더·여백·max-w-7xl** 안에 배치. |
| **색·타이포** | 기존: `indigo-600/50/700`, `gray-50~900`, `rounded-lg`, `shadow`. 새 화면도 동일 토큰 사용. |
| **정보 위계** | 페이지 제목 `text-2xl font-bold` → 섹션 `text-lg font-semibold` → 보조 `text-sm text-gray-600`. |
| **상태 피드백** | 로딩: 스켈레톤 또는 `animate-pulse` 블록. 빈 목록: 일러스트 없이 **한 줄 안내 + CTA**(선택). 에러: `border-red-200 bg-red-50` 박스. |
| **밀도** | 운영 도구이므로 **테이블 + 카드 혼합**: 요약은 카드, 목록은 테이블(모바일에서 가로 스크롤 `overflow-x-auto`). |
| **접근성** | 주요 버튼에 `type="button"` 명시, 토글에 시각적 on/off, 링크는 `Link` 사용. |

---

## 2. 정보 구조(IA) — 네비게이션 확장

현재: 대시보드 · 지식베이스 · 통화이력 · 로그아웃.

| 메뉴 | 경로 | 비고 |
|------|------|------|
| 대시보드 | `/dashboard` | 메트릭 + 실시간 통화 + HITL + (선택) 아웃바운드 요약 링크 |
| 지식베이스 | `/knowledge` | 유지 |
| 통화이력 | `/call-history` | **탭**: `전체 이력` / `확인 필요` |
| **발신 관리** | `/outbound` | **신규** — 아웃바운드 전용 (또는 대시보드 하위 섹션으로 시작 후 분리) |

**헤더 우측(로그아웃 왼쪽)**  
- **운영자 상태 토글**: “응대 가능” / “자리 비움” (operator API).  
- 짧은 라벨 + 스위치 형태로 두어 헤더 높이(`h-14`) 유지.

---

## 3. 기능별 구현 제안 (점검 문서 전 항목)

### 3.1 통화 이력 — follow-ups (필수)

**API**: `GET /api/call-history/follow-ups`, `PATCH /api/call-history/follow-ups/{id}`

**UI**  
- `/call-history` 상단에 **세그먼트 탭** (pill 스타일, `indigo` 활성):  
  - **전체 이력** — 기존 테이블 유지.  
  - **확인 필요** — follow-ups 전용 테이블.  
- 컬럼 예: 통화 ID, 질문 요약, 상태 배지(`pending` 주황, `resolved` 초록 등), 생성일, **상세/처리** 버튼.  
- **처리** 클릭 시 **모달** 또는 **인라인 확장 행**:  
  - 상태 선택: `pending` | `noted` | `contacted` | `resolved`  
  - `operator_note` 텍스트 영역  
  - 저장 → `PATCH` 호출 후 목록 갱신.

**UX**  
- `callee`는 로그인 테넌트 `owner`와 동일하게 쿼리.  
- 빈 목록: “확인 필요한 건이 없습니다.”

---

### 3.2 활성 통화 — REST 백업 (필수 권장)

**API**: `GET /api/calls/active`  
**Bearer**: 선택적(백엔드 `HTTPBearer(auto_error=False)`).

**UI/로직**  
- 대시보드 마운트 시 **1회** `GET /api/calls/active`로 시드.  
- WebSocket `call_started` / `call_ended`와 **동일한 상태 모델**로 merge:  
  - `call_id` 기준 Map/Set으로 중복 제거.  
- **폴링**: WebSocket이 `disconnected`일 때만 `15~30초` 간격 폴링(배터리·부하 고려). 연결되면 폴링 중지.  
- 스키마 차이 보정: REST는 `caller`/`callee` 객체일 수 있음 → 대시보드 카드용 `caller_number` 등으로 normalize하는 **작은 유틸** `lib/normalizeActiveCall.ts`.

**UX**  
- 연결 배지 옆에 “실시간” / “동기화 중(폴링)” 같은 **작은 텍스트** (선택).

---

### 3.3 대시보드 메트릭 (필수 권장)

**API**: `GET /api/metrics/dashboard?owner={tenant.owner}`

**UI**  
- 대시보드 **최상단**에 **4칸 그리드** (`grid grid-cols-2 md:grid-cols-4 gap-4`):  
  - 오늘 통화 수  
  - HITL 대기(큐 크기)  
  - 평균 AI 신뢰도(표시 형식 `0.85 → 85%`)  
  - 지식베이스 크기(또는 평균 응답시간 — API 필드에 맞춤)  
- 각 카드: `bg-white rounded-lg shadow p-4`, 큰 숫자 `text-2xl font-bold text-gray-900`, 라벨 `text-xs text-gray-500 uppercase tracking-wide`.  
- 로그인 없이는 호출 생략(이미 대시보드는 테넌트 의존).

**백엔드 참고**  
- 현재 API는 더미일 수 있음 → 프론트는 필드 없을 때 `—` 표시.

---

### 3.4 운영자 상태 (필수 권장)

**API**: `GET /api/operator/status?tenant_id=`, `POST /api/operator/status` body `{ available, tenant_id }`

**UI**  
- `AppHeader` 우측: **토글** “응대 가능”(ON, 초록/인디고) / “자리 비움”(OFF, 회색).  
- 마운트 시 `GET`으로 초기값 동기화. 변경 시 `POST`.  
- 실패 시 토스트 또는 인라인 에러, 이전 상태로 롤백.

**UX**  
- 자리 비움 시에도 **로그아웃은 가능**. (정책은 백엔드와 합의)

---

### 3.5 아웃바운드 (4개 API 전부)

**API**:  
`POST /api/outbound`, `GET /api/outbound`, `GET /api/outbound/stats`, `POST /api/outbound/{id}/cancel`

**UI** — 전용 페이지 `/outbound` 권장.

1. **상단**: `stats` API로 카드 2~3개 (대기/진행/완료 등 응답 스키마에 맞춤).  
2. **발신 폼** (카드): 발신번호·착신번호 입력, 제출 → `POST`. 성공 시 목록 갱신.  
3. **목록 테이블**: `GET ?state=` 필터(드롭다운), 행마다 **취소** → `POST .../cancel` (확인 다이얼로그).  
4. 빈 목록·로딩·에러 패턴은 통화이력과 동일.

**네비**  
- `AppHeader`의 `NAV_ITEMS`에 `{ href: '/outbound', label: '발신 관리' }` 추가.

---

### 3.6 녹음 (recordings) — 점검 문서 4절

**구현 완료**: [RECORDINGS_API_IMPLEMENTATION.md](./RECORDINGS_API_IMPLEMENTATION.md)

- 백엔드: `/api/recordings/calls/{call_id}/info|media|download`
- 프론트: 통화이력 **재생**(Blob+모달) / **저장**(다운로드)
- `RECORDINGS_DIR` 환경변수로 녹음 루트 지정 가능

---

## 4. 공통 기술 제안

| 항목 | 제안 |
|------|------|
| **API 베이스** | `lib/api.ts`: `getApiUrl()`, `authHeaders()` — `access_token`/`token` 일원화. |
| **테넌트** | `lib/tenant.ts`: `getTenantOwner()` — `tenant` JSON 파싱 + `tenant_id` 폴백. |
| **타입** | `types/api.ts`에 `FollowUpItem`, `OutboundRequest`, `DashboardMetrics`, `ActiveCallRest` 등 정의. |
| **에러 처리** | `fetch` 래퍼에서 `!res.ok` 시 `detail` 파싱해 일관 메시지. |

---

## 5. 구현 단계 (권장 순서)

| 단계 | 범위 | 산출물 |
|------|------|--------|
| **P1** | follow-ups 탭 + PATCH 모달 | `call-history/page.tsx` 확장 또는 `FollowUpsPanel.tsx` |
| **P2** | metrics 카드 + active merge/폴링 | `dashboard/page.tsx`, `useActiveCallsSync.ts` |
| **P3** | operator 토글 | `AppHeader.tsx` 또는 `OperatorAvailabilityToggle.tsx` |
| **P4** | outbound 페이지 전체 | `app/outbound/page.tsx`, 헤더 링크 |
| **P5** | recordings | 백엔드 라우터 + 통화이력 행 액션 |

---

## 6. 화면 와이어 요약 (텍스트)

```
[헤더] 로고 | 대시보드 지식베이스 통화이력 발신관리 | [응대가능 토글] 로그아웃

/dashboard
  [메트릭 4카드]
  [연결상태] 
  [실시간 통화 그리드]
  [HITL 요청]

/call-history
  [탭: 전체 이력 | 확인 필요]
  [테이블 + 페이지네이션]
  (확인 필요) [행 확장 또는 모달: 상태·메모·저장]

/outbound
  [통계 카드]
  [발신 폼]
  [목록 + state필터 + 취소]
```

---

## 7. 변경 이력 (구현 완료 시)

구현 후에는 [implementation-report-changelog.mdc](../../../.cursor/rules/implementation-report-changelog.mdc)에 따라 **파일별 변경 이력 표**를 별도 구현 보고서에 남긴다.

---

## 8. 요약

- **구현 완료 보고**: [API_FRONTEND_GAP_IMPLEMENTATION_COMPLETE.md](./API_FRONTEND_GAP_IMPLEMENTATION_COMPLETE.md) (P1~P4, recordings 제외)

- 점검 문서의 **미연동 API는 모두** 위 단계(P1~P5)에 매핑했다.  
- **UI**는 기존 인디고·카드·테이블 스타일을 유지하고, **탭·메트릭 스트립·헤더 토글·발신 전용 페이지**로 정보 과밀을 피한다.  
- **recordings**만 백엔드 선행 작업이 필요하다.

이 문서는 “어떻게 구현하면 좋은지”에 대한 **제안**이며, 실제 구현 시 API 응답 스키마를 한 번 더 확인해 타입을 맞추면 된다.
