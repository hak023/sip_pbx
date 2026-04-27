# AI 폴백 모드 설정 및 지식베이스 호 전환 개선 보고서

- **작성일**: 2026-04-09 23:30
- **상태**: 완료
- **관련 경로**: `sip-pbx/src/ai_voicebot/`, `sip-pbx/src/api/routers/`, `sip-pbx/src/sip_core/`, `sip-pbx/frontend/components/`, `sip-pbx/frontend/app/knowledge/`

---

## 개요

다섯 가지 개선 작업을 완료했다.

1. `organization_info.py`에서 하드코딩된 `business_hours` 시스템 컨텍스트 제거 → KB RAG으로 응답
2. HITL / 상담원 연결 모드 선택기를 전역 헤더로 이동 + 툴팁
3. 응대가능/자리비움 토글에 툴팁 추가
4. 지식베이스 호 전환 카테고리에 착신번호 필드 추가
5. `ai_fallback_mode` 백엔드 영속화 (OperatorStatusManager + API)

---

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `src/ai_voicebot/knowledge/organization_info.py` | 수정 | `get_organization_context()`에서 `business_hours` 줄 제거 | KB RAG으로 대체 |
| `frontend/components/AppHeader.tsx` | 수정 | `AIFallbackModeSelector` 컴포넌트 추가, HITL↔상담원 토글+툴팁 | 기존 동작 제거 없음 |
| `frontend/components/OperatorAvailabilityToggle.tsx` | 수정 | 호버 시 툴팁 추가 (응대가능/자리비움 설명) | 기존 동작 제거 없음 |
| `frontend/app/knowledge/add/page.tsx` | 수정 | `transfer` 카테고리 선택 시 착신번호·부서명 필드 추가 | 기존 contact 필드와 동일 패턴 |
| `src/api/routers/operator_status_api.py` | 수정 | `ai_fallback_mode` 필드 수신/반환, `available` 필드 선택적으로 변경 | 하위 호환 유지 |
| `src/sip_core/operator_status.py` | 수정 | `_fallback_modes` 딕셔너리, `set_fallback_mode`, `get_fallback_mode`, `_load`/`_save`/`get_status_info` 업데이트 | 파일 영속화 포함 |

---

## 파일별 변경 상세

### `src/ai_voicebot/knowledge/organization_info.py`
- **변경 유형**: 수정
- **변경 내용**: `get_organization_context()`에서 `- 운영시간: {business_hours}` 한 줄 제거.  
  영업시간은 이제 KB(ChromaDB)에 등록된 내용을 RAG 검색으로 응답.
- **기존 동작 제거**: 있음 — `tenant_config.business_hours` 기반 정적 안내 제거
- **설계 대비**: 설계대로 (사용자 요청에 따른 방향 전환)

### `frontend/components/AppHeader.tsx`
- **변경 유형**: 수정
- **변경 내용**:
  - `AIFallbackModeSelector` 컴포넌트 신규 추가. HITL(분홍) / 상담원 연결(인디고) 토글 버튼.
  - localStorage + 백엔드 API 양방향 동기화.
  - 마운트 시 백엔드에서 최신 `ai_fallback_mode` 조회하여 초기화.
  - 각 모드 호버 시 툴팁 표시.
  - 헤더 우측에 `AIFallbackModeSelector` → 구분선 → `OperatorAvailabilityToggle` → 로그아웃 순으로 배치.

### `frontend/components/OperatorAvailabilityToggle.tsx`
- **변경 유형**: 수정
- **변경 내용**: 토글 버튼 래핑 `div`에 `onMouseEnter/Leave`로 툴팁 표시.
  - 응대 가능: "응대 가능 상태입니다. AI가 모르는 내용이 있을 때 HITL 또는 상담원 연결이 작동합니다."
  - 자리 비움: "자리 비움 상태입니다. AI가 단독으로 응대하며 HITL 요청이 오더라도 즉시 처리되지 않습니다."

### `frontend/app/knowledge/add/page.tsx`
- **변경 유형**: 수정
- **변경 내용**: `transfer` 카테고리 선택 시 파란 박스 내에 추가 필드 노출.
  - **착신번호(내선/외선)** — 필수. 예: `1001`, `010-1234-5678`. API body에 `transfer_to`로 전달.
  - **상담 부서/담당자명** — 선택. `department_name`으로 전달.
  - 내용 입력란은 RAG 검색 트리거 문장 안내 추가.

### `src/api/routers/operator_status_api.py`
- **변경 유형**: 수정
- **변경 내용**:
  - `OperatorStatusUpdate.available`을 `bool | None`으로 변경 → `ai_fallback_mode`만 업데이트할 때 상태 변경 없이 저장 가능.
  - `ai_fallback_mode: str | None` 필드 추가.
  - POST: `body.ai_fallback_mode`가 `hitl|transfer`이면 `mgr.set_fallback_mode()` 호출.
  - GET/POST 응답에 `ai_fallback_mode` 포함.

### `src/sip_core/operator_status.py`
- **변경 유형**: 수정
- **변경 내용**:
  - `_fallback_modes: Dict[str, str]` 인메모리 딕셔너리 추가.
  - `_load()`: 파일에서 `ai_fallback_mode` 복원.
  - `_save()`: 파일에 `ai_fallback_mode` 저장.
  - `set_fallback_mode(user_id, mode)`: 모드 저장 후 파일 반영.
  - `get_fallback_mode(user_id)`: 조회 (기본값: `"hitl"`).
  - `get_status_info()` 반환 딕셔너리에 `ai_fallback_mode` 포함.

---

## 호 전환(transfer) 동작 구조 확인

AI 오케스트레이터(`ai_orchestrator.py`)에는 이미 완전한 호 전환 파이프라인이 존재한다.

```
사용자: "상담원 연결해줘"
  → RAG 검색 → response_type == "transfer" && score >= 0.75
  → _handle_transfer_intent(user_text, rag_result)
    → metadata["transfer_to"] (착신번호)
    → TransferManager.initiate_transfer(...)
```

KB에 `category=transfer`, `transfer_to=착신번호` 메타데이터가 있으면 자동으로 동작한다.

---

## 주요 결정 사항

- **`ai_fallback_mode` 저장 위치**: booking_settings DB 대신 기존 `OperatorStatusManager` JSON 파일에 통합. 이미 tenant별 영속화 인프라가 있으므로 추가 DB 없이 일관성 유지.
- **헤더 모드 선택기**: `/booking/settings` 별도 페이지 대신 전역 헤더에 인라인 토글로 배치하여 통화 중에도 즉시 전환 가능.
- **`available` 필드 선택적**: 기존 POST body 호환을 깨지 않으면서 `ai_fallback_mode`만 업데이트하는 경우를 지원하기 위해 `Optional` 처리.

---

## 잔여 과제

- `ai_fallback_mode == "transfer"` 일 때 AI가 HITL을 시도하지 않고 바로 전환하도록 `ai_orchestrator.py`의 `request_human_help` 분기 처리 추가 필요 (현재는 KB에서 transfer intent를 감지해야만 전환됨 — 기존 동작 유지).
- KB `transfer` 카테고리 등록 UI가 완성됐으므로 실제 번호 등록 후 end-to-end 테스트 필요.
