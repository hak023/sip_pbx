# API 서버 기준 Frontend 연동 점검 보고서

**작성일**: 2026-03  
**목적**: API 서버에 존재하는 엔드포인트 중 Frontend에서 사용하지 않거나 변경/누락된 항목 점검

**구현·UI/UX 제안**: [API_FRONTEND_GAP_IMPLEMENTATION_PROPOSAL.md](./API_FRONTEND_GAP_IMPLEMENTATION_PROPOSAL.md) (미연동 항목 전체 반영)

---

## 1. API 서버 엔드포인트 목록 (기준)

| 라우터 | Method | 경로 | 설명 |
|--------|--------|------|------|
| **auth** | POST | `/api/auth/login` | 로그인 (extension) |
| **tenants** | GET | `/api/tenants` | 테넌트 목록 |
| **call_history** | GET | `/api/call-history` | 통화 이력 목록 (page, limit, callee) |
| **call_history** | GET | `/api/call-history/follow-ups` | 확인 필요(후처리) 목록 (callee, status) |
| **call_history** | PATCH | `/api/call-history/follow-ups/{id}` | 확인 필요 상태 업데이트 |
| **calls** | GET | `/api/calls/active` | 활성 통화 목록 (대시보드용) |
| **metrics** | GET | `/api/metrics/dashboard` | 대시보드 메트릭 (owner 쿼리 필수) |
| **operator** | GET | `/api/operator/status` | 운영자 상태 조회 (tenant_id) |
| **operator** | POST | `/api/operator/status` | 운영자 상태 변경 (available, tenant_id) |
| **outbound** | POST | `/api/outbound` | 아웃바운드 발신 요청 생성 |
| **outbound** | GET | `/api/outbound` | 아웃바운드 목록 (state 필터) |
| **outbound** | GET | `/api/outbound/stats` | 아웃바운드 통계 |
| **outbound** | POST | `/api/outbound/{id}/cancel` | 아웃바운드 취소 |
| **knowledge** | GET | `/api/knowledge` | 지식 목록 (owner, category, doc_type, source 등) |
| **knowledge** | POST | `/api/knowledge` | 지식 추가 |
| **knowledge** | DELETE | `/api/knowledge/{doc_id}` | 지식 1건 삭제 |

---

## 2. Frontend 현재 사용 현황

| 페이지/기능 | 사용 API | 비고 |
|-------------|----------|------|
| **로그인** | GET `/api/tenants`, POST `/api/auth/login` | ✅ 사용 중 |
| **지식베이스** | GET/POST/DELETE `/api/knowledge` | ✅ 사용 중 |
| **통화이력** | GET `/api/call-history` | ✅ 목록만 사용 |
| **대시보드** | (REST 없음, WebSocket만 사용) | ⚠️ 아래 참고 |

---

## 3. 없어졌거나 사용하지 않는 항목 (API는 있는데 Frontend 미연동)

### 3.1 통화 이력 (call_history)

| API | 상태 | 설명 |
|-----|------|------|
| GET `/api/call-history/follow-ups` | **미사용** | "확인 필요(후처리)" 목록. AI가 모르는 내용으로 응답한 건을 운영자가 나중에 처리하기 위한 목록. |
| PATCH `/api/call-history/follow-ups/{id}` | **미사용** | 위 목록 항목의 상태 업데이트 (pending → noted / contacted / resolved, operator_note). |

**영향**: 통화이력 페이지에 "확인 필요" 탭/섹션이 없어서, HITL로 쌓인 후처리 건을 조회·상태 변경할 수 없음.

---

### 3.2 활성 통화 (calls)

| API | 상태 | 설명 |
|-----|------|------|
| GET `/api/calls/active` | **미사용** | REST로 활성 통화 목록 조회. |

**현재**: 대시보드는 WebSocket(`call_started`, `call_ended`)만 사용.  
**영향**: WebSocket 연결 끊김 시 활성 통화 목록을 REST로 복구할 수 없음. (폴링 백업으로 사용 가능)

---

### 3.3 메트릭 (metrics)

| API | 상태 | 설명 |
|-----|------|------|
| GET `/api/metrics/dashboard?owner=...` | **미사용** | 대시보드용 메트릭 (hitl_queue_size, today_calls_count, knowledge_base_size 등). |

**영향**: 대시보드에 "오늘 통화 수", "HITL 대기 수", "지식베이스 크기" 등 요약 메트릭이 표시되지 않음.

---

### 3.4 운영자 상태 (operator)

| API | 상태 | 설명 |
|-----|------|------|
| GET `/api/operator/status` | **미사용** | 운영자 자리 비움/재개 상태 조회. |
| POST `/api/operator/status` | **미사용** | 운영자 상태 변경 (available, tenant_id). |

**영향**: "자리 비움 모드" 등 운영자 상태 토글 UI가 없음. (과거 OperatorStatusToggle 등이 삭제된 것으로 추정)

---

### 3.5 아웃바운드 (outbound)

| API | 상태 | 설명 |
|-----|------|------|
| POST `/api/outbound` | **미사용** | 발신 요청 생성. |
| GET `/api/outbound` | **미사용** | 발신 목록 조회. |
| GET `/api/outbound/stats` | **미사용** | 발신 통계. |
| POST `/api/outbound/{id}/cancel` | **미사용** | 발신 취소. |

**영향**: 아웃바운드 발신 요청/목록/취소를 할 수 있는 화면이 없음.

---

## 4. 참고: 메인 docstring vs 실제 라우터

- **recordings** 라우터는 `src/api/routers/recordings.py`에 구현되어 `main.py`의 `_load_routers()`에 포함됨.
- 상세: [RECORDINGS_API_IMPLEMENTATION.md](./RECORDINGS_API_IMPLEMENTATION.md)

---

## 5. 요약 표

| 구분 | API 개수 | Frontend 사용 | 미사용 |
|------|----------|----------------|--------|
| auth | 1 | 1 | 0 |
| tenants | 1 | 1 | 0 |
| call_history | 3 | 1 | **2** (follow-ups 조회/업데이트) |
| calls | 1 | 0 | **1** (active) |
| metrics | 1 | 0 | **1** (dashboard) |
| operator | 2 | 0 | **2** (status GET/POST) |
| outbound | 4 | 0 | **4** (전부) |
| knowledge | 3 | 3 | 0 |

**미연동 합계**: **10개** 엔드포인트 (follow-ups 2, calls/active 1, metrics 1, operator 2, outbound 4)

---

## 6. 권장 조치 (우선순위)

1. **통화 이력**:  
   - `GET /api/call-history/follow-ups` 연동하여 "확인 필요" 목록 탭/섹션 추가.  
   - `PATCH /api/call-history/follow-ups/{id}` 연동하여 상태/메모 업데이트 가능하게 처리.

2. **대시보드**:  
   - 선택: `GET /api/metrics/dashboard` 연동하여 요약 메트릭 표시.  
   - 선택: WebSocket 장애 시 `GET /api/calls/active` 폴링으로 활성 통화 복구.

3. **운영자 상태**:  
   - 필요 시 `GET/POST /api/operator/status` 연동하여 자리 비움 토글 등 UI 복구.

4. **아웃바운드**:  
   - 발신 기능이 필요하면 전용 화면에서 POST/GET/cancel/stats 연동.

5. **녹음(recordings)**:  
   - 라우터가 현재 없으므로, 녹음 재생/다운로드가 필요하면 API 추가 후 Frontend 연동.

이 문서는 **API 서버를 기준**으로, 없어졌거나 변경된 Frontend 연동을 점검한 결과입니다.
