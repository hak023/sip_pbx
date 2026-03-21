# API–Frontend 갭 연동 구현 완료 보고

**완료일**: 2026-03  
**설계 근거**: [API_FRONTEND_GAP_IMPLEMENTATION_PROPOSAL.md](./API_FRONTEND_GAP_IMPLEMENTATION_PROPOSAL.md)  
**P5 녹음**: [RECORDINGS_API_IMPLEMENTATION.md](./RECORDINGS_API_IMPLEMENTATION.md) 참고

---

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `src/api/routers/call_history.py` | 수정 | follow-ups 목록 필터를 `callee_id` 포함하도록 수정 | HITL 저장 필드와 쿼리 불일치 버그 수정 |
| `src/api/routers/operator.py` | 수정 | `GET /status`의 `tenant_id`를 `Query`로 명시 | 프론트 쿼리 파라미터 안정화 |
| `frontend/lib/api.ts` | 추가 | `getApiUrl`, `authHeaders`, `apiJson` | 공통 REST |
| `frontend/lib/tenant.ts` | 추가 | `getTenantOwner()` | 테넌트 owner 일원화 |
| `frontend/lib/normalizeActiveCall.ts` | 추가 | REST 활성 통화 → 대시보드 카드 모델 정규화 | 설계대로 |
| `frontend/types/api.ts` | 추가 | 메트릭·follow-up·아웃바운드 타입 | 설계대로 |
| `frontend/components/OperatorAvailabilityToggle.tsx` | 추가 | 운영자 응대 가능/자리 비움 토글 | operator API |
| `frontend/components/AppHeader.tsx` | 수정 | 발신 관리 링크 + 토글 배치 | 설계대로 |
| `frontend/app/call-history/page.tsx` | 수정 | 탭(전체/확인 필요), follow-ups PATCH 모달 | 설계대로 |
| `frontend/app/dashboard/page.tsx` | 수정 | 메트릭 4카드, `/api/calls/active` 시드·폴링, 인디고 톤 정리 | 설계대로 |
| `frontend/app/outbound/page.tsx` | 추가 | 통계·폼·목록·취소 (outbound 4 API) | 설계대로 |
| `src/api/utils/recording_paths.py` | 추가 | 녹음 디렉터리·오디오 목록·경로 검증 | P5 |
| `src/api/routers/recordings.py` | 추가 | 녹음 info/media/download API | P5 |
| `frontend/lib/recordings.ts` | 추가 | 녹음 fetch·다운로드 (Bearer) | P5 |
| `frontend/app/call-history/page.tsx` | 수정 | 녹음 재생 모달·저장 | P5 |
| `src/api/utils/transcript_parser.py` | 수정 | transcript 경로를 `find_call_directory`로 통일 | P5 |
| `src/api/routers/call_history.py` | 수정 | `has_recording` 실파일 기준, `RECORDINGS_DIR` | P5 |

---

## 구현 요약

1. **통화이력**: `전체 이력` / `확인 필요` 탭, 모달에서 상태·메모 저장 후 `PATCH`; 오디오 있으면 **재생·저장**(recordings API).
2. **대시보드**: `GET /api/metrics/dashboard?owner=`, 마운트·재연결 시 메트릭 갱신; `GET /api/calls/active`로 초기 시드; WebSocket `disconnected` 시 20초 폴링으로 목록 대체.
3. **운영자**: 헤더에 토글, `GET/POST /api/operator/status`.
4. **발신**: `/outbound` 페이지, stats·생성·목록·state 필터·취소.
5. **녹음(P5)**: `GET .../info|media|download`, `RECORDINGS_DIR`·실파일 기준 `has_recording`.
6. **환경 변수**: WebSocket `NEXT_PUBLIC_WS_URL` (기본 `http://localhost:8001`), REST `NEXT_PUBLIC_API_URL` (기본 `http://localhost:8000`).

---

## 파일별 상세 (백엔드)

### `src/api/routers/call_history.py`
- **변경 유형**: 수정
- **변경 내용**: `get_follow_ups`에서 `callee` 쿼리 시 `item.get("callee_id")`와 `callee` 모두 비교. `record_hitl_request`는 `callee_id`만 저장하므로 기존에는 필터가 동작하지 않았음.
- **기존 동작 제거 여부**: 없음
- **설계 대비**: 버그 수정 (프론트 필터와 무관하게 API 정합성)

### `src/api/routers/operator.py`
- **변경 유형**: 수정
- **변경 내용**: `tenant_id`를 `Query(None)`으로 선언.
- **기존 동작 제거 여부**: 없음
- **설계 대비**: 설계대로

---

## 코드베이스 점검 결과 (정적 대조, 2026-03)

소스 트리만으로 **라우터 등록·경로·프론트 호출** 일치 여부를 확인한 결과이다. (실제 HTTP/E2E는 별도 수행)

### 백엔드: `main.py` 로드 라우터

| 이름 | prefix / 비고 | 주요 엔드포인트 |
|------|----------------|-----------------|
| auth | `/api/auth` | `POST /login`, `POST /logout`, `GET /me` |
| tenants | `/api/tenants` | `GET /api/tenants`, `GET /api/tenants/{tenant_id}` |
| call_history | `/api/call-history` | `GET /api/call-history/follow-ups`, `PATCH .../follow-ups/{id}`, `GET /api/call-history` |
| calls | `/api/calls` | `GET /active` |
| metrics | `/api/metrics` | `GET /dashboard` |
| operator | `/api/operator` | `GET /status`, `POST /status` |
| outbound | `/api/outbound` | `POST /`, `GET /`, `GET /stats`, `POST /{id}/cancel` |
| recordings | `/api/recordings` | `GET /calls/{call_id}/info`, `/media`, `/download` |
| knowledge | `include_router(..., prefix="/api")` | `POST/GET /knowledge`, `DELETE /knowledge/{doc_id}` |

- **확인**: 위 9개가 `_load_routers` + `knowledge_router` 조합으로 등록되도록 코드에 반영됨.

### 프론트엔드: 페이지 ↔ API 매핑

| 화면 | 사용 API / 통신 | 점검 |
|------|------------------|------|
| `/login` | `GET /api/tenants`, `POST /api/auth/login` | 일치 |
| `/dashboard` | `GET /api/calls/active`, `GET /api/metrics/dashboard?owner=`, Socket.IO `NEXT_PUBLIC_WS_URL` | 일치 |
| `/knowledge` | `GET/POST/DELETE /api/knowledge` | 일치 |
| `/call-history` | `GET /api/call-history`, `GET/PATCH .../follow-ups`, `GET .../recordings/calls/{id}/info` + media (Bearer) | 일치 |
| `/outbound` | `GET /stats`, `GET /`, `POST /`, `POST /{id}/cancel` | 일치 |
| `AppHeader` | `OperatorAvailabilityToggle` → `GET/POST /api/operator/status` | 일치 |
| 공통 | `lib/api.ts` (`apiJson`, `authHeaders`, `getApiUrl`) | 일치 |

### 알려진 제한·수동 검증 포인트

| 항목 | 내용 |
|------|------|
| **follow-ups 목록** | `_follow_ups`는 인메모리; `record_hitl_request` 호출 전까지 목록이 비어 있을 수 있음 → E2E 시 실제 HITL 발생 후 확인. |
| **메트릭** | `metrics/dashboard`는 구현상 더미/0일 수 있음 → UI에 숫자만 나오는지 확인. |
| **활성 통화** | `CallManager` 미주입 시 `calls` 레지스트리·아웃바운드 등록분만 표시 → 시나리오별 확인. |
| **녹음** | `recordings/` 아래 세션 폴더에 지원 확장자 오디오가 있어야 `has_recording`·재생 가능. |
| **녹음 API 인증** | 현재 Bearer 없이도 서빙 가능할 수 있음 → 외부 노출 시 보강 권장(RECORDINGS 문서 참고). |
| **로컬 import** | Windows cp949 콘솔에서 `knowledge_router` 모듈 로드 시 이모지 로그로 `UnicodeEncodeError` 가능 → 서버는 UTF-8 터미널 또는 로그 설정 권장. |

### 수동 E2E 검증 체크리스트

- [ ] 로그인 후 **대시보드**: 메트릭 4카드 표시, 활성 통화(REST) 또는 WS 이벤트 반영, 연결 끊김 시 **동기화(폴링)** 문구·주기 갱신.
- [ ] **통화이력 → 전체 이력**: 테이블·페이지네이션; `has_recording` 행에서 **재생** 모달·**저장** 다운로드.
- [ ] **통화이력 → 확인 필요**: 목록(데이터 있을 때)·처리 모달·PATCH 후 목록 갱신.
- [ ] **헤더**: 응대 가능/자리 비움 토글, 새로고침 후 상태 유지(서버 인메모리면 서버 재시작 시 초기화).
- [ ] **발신 관리**: 통계 카드, 폼 등록, 목록·state 필터, queued 등에서 **취소**.
- [ ] **지식베이스**: 목록·등록·삭제(임베더·Chroma 기동 전제).
- [ ] **로그아웃** 후 보호 페이지 리다이렉트.
