# 셀프서비스 AI 도우미 — 자동설정(쓰기) 범위 확장 가능성 검토 리포트

**작성일**: 2026-07-20
**요청 배경**: 2026-07-20 점검 리포트에서 "설정 카탈로그 7개 도메인 중 3개(persona/ai-escalation/chat-relay)만
실제 쓰기 지원, 나머지 4개(call-control/contacts/general/integrations)는 update_fn 자체가 없어
자동설정 불가"라는 갭이 발견됨 — PRD FR6/FR11/NFR4("제외 목록 방식 — 카탈로그 등록 항목은
기본적으로 자동설정 가능해야 한다")의 원래 취지와 괴리. 본 리포트는 **AI가 실제로 자동설정을
수행할 수 있는 방향**으로 4개 도메인을 코드 레벨로 재조사하여 실현 가능성·구현 방향·리스크를
정리한다.
**관련 문서**: [self-service-ai-assistant-prd.md](../../product/self-service-ai-assistant-prd.md) FR6/FR11/NFR4,
[settings_catalog.py](../../../src/ai_voicebot/self_service/settings_catalog.py),
[self_service_exclusions.yaml](../../../config/self_service_exclusions.yaml)

---

## 1. 요약 판정

| 도메인           | 현재 상태      | 자동설정 확장 가능성                     | 권장 조치                           |
| ---------------- | -------------- | ---------------------------------------- | ----------------------------------- |
| **call-control** | update_fn 없음 | ✅ **가능** (기존 ID 기반 CRUD 함수 존재) | 신규 Story로 "항목 지정형" 자동설정 |
| **contacts**     | update_fn 없음 | ✅ **가능** (기존 ID 기반 CRUD 함수 존재) | 신규 Story로 "항목 지정형" 자동설정 |
| **integrations** | update_fn 없음 | ⚠️ **부분 가능** (연동 해제만)            | "연동 해제" 액션형 Tool 1개만 추가  |
| **general**      | update_fn 없음 | ❌ **현재 구조로는 불가능**               | 읽기 전용 유지 + PRD에 사유 명시    |

**결론**: 4개 중 3개는 자동설정 확장이 실제로 가능하지만, 현재의 "단일 필드=값" 갱신 모델
(`update_fn(owner, field, value)`)로는 부족하고 **"목록에서 항목을 지정 → 그 항목을 변경/생성/삭제"**
하는 새로운 상호작용 모델이 필요하다. 이는 `settings_catalog.py`를 확장 수정하는 수준이 아니라
**후속 Story(별도 설계·확인 발화 플로우 필요)로 분리**하는 것이 적절하다.

---

## 2. 도메인별 상세 분석

### 2.1 call-control — ✅ 가능, 단 모델 확장 필요

**코드 확인 결과** (`src/call_control/db.py`):
```python
def list_rules(owner: str) -> List[Dict[str, Any]]
def get_rule(rule_id: str) -> Optional[Dict[str, Any]]
def create_rule(data: Dict[str, Any]) -> Dict[str, Any]
def update_rule(rule_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]
def delete_rule(rule_id: str) -> bool
def update_rule_priority(rule_id: str, priority: int) -> Optional[Dict[str, Any]]
def update_announcement(announcement_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]
```
ID 기반 CRUD가 이미 전부 존재한다 — **백엔드 함수 자체는 자동설정에 쓰기 충분**하다.

**막힌 이유**: `settings_catalog.DomainEntry.update_fn`은 `(owner, field, value)` 시그니처,
즉 "이 테넌트의 이 필드를 이 값으로" 모델이다. 그런데 착신 규칙은 **목록(list)** 이라
"어떤 규칙을(rule_id)" 지정하는 단계가 먼저 필요하다. 사용자는 내부 rule_id를 모르므로
("무응답 규칙 켜줘" 같은 발화만 가능), LLM이 먼저 `list_rules`로 규칙 이름/설명을 보고
대상을 특정해야 한다.

**구현 방향(제안)**:
1. `settings_catalog.py`에 "목록형 도메인" 개념 추가 — `update_fn` 대신 `item_update_fn(owner, item_id, field, value)` +
   `item_create_fn(owner, data)` + `item_delete_fn(owner, item_id)`를 등록할 수 있게 `DomainEntry` 확장.
2. 신규 Tool: `list_call_control_rules(owner)`(이미 조회 Story 1.4/1.6에 존재), `update_call_control_rule(owner, rule_name_or_id, field, value)` —
   내부에서 이름으로 먼저 매칭 시도 후 모호하면 "어떤 규칙을 말씀하시는지 확인 발화"로 되묻는다(신규 UX 패턴).
3. **되돌리기 쉬움**: 규칙 활성/비활성(`enabled` 필드) 토글 정도는 안전하게 자동화 가능. 규칙 생성/삭제·우선순위 재배열은
   전화 라우팅에 직접 영향을 주므로 1차로는 "기존 규칙의 단일 필드 토글"만 자동설정 허용 대상으로 좁히는 것을 권장(단계적 확대).
4. `self_service_exclusions.yaml`에서 `call-control: fields: ["*"]`를 제거하고, 위험도가 낮은 필드(`enabled`)만
   writable_fields로 등록 — 우선순위 변경(`priority`)·규칙 생성/삭제는 당분간 제외 목록에 유지.

**리스크/고려사항**:
- 이름 기반 매칭은 모호성 문제가 있다(같은 이름의 규칙이 여러 개면 오작동 위험) — 반드시 "정확히 1건 매칭 시에만 진행,
  2건 이상이면 사용자에게 재질문" 원칙 필요.
- 전화 라우팅은 실제 서비스 가용성에 직결되므로, `booking_agent`보다 더 엄격한 확인 발화(예: "지금 [규칙명] 규칙을
  끄면 오늘 이후 걸려오는 전화는 [대체 동작]으로 처리됩니다. 진행할까요?")가 필요 — 단순 "네/아니오"보다 영향 범위를
  명시하는 문구 설계가 선행되어야 한다.

### 2.2 contacts — ✅ 가능, call-control과 동일한 패턴

**코드 확인 결과** (`src/common/caller_contact_db.py`):
```python
def get_caller_contact(owner: str, canonical_phone: str) -> Optional[Dict[str, Any]]
def list_caller_contacts(...) -> ...
def update_caller_contact(...) -> ...
def delete_caller_contact(*, contact_id: str, owner: str) -> bool
```
연락처도 ID(또는 전화번호) 기반 CRUD가 이미 존재한다.

**구현 방향(제안)**: call-control과 동일하게 "목록형 도메인" 확장을 재사용. 예: "김철수 연락처에 메모 추가해줘" →
`list_caller_contacts`로 이름 매칭 → 1건이면 `update_caller_contact` 호출 → 확인 발화 후 실행.

**리스크/고려사항**:
- 연락처는 개인정보 성격이 있어(이름·전화번호), 삭제(`delete_caller_contact`)는 되돌리기 어려운 축에 속하므로
  1차로는 **조회 + 필드 갱신(메모·폴더 등)만 자동설정 허용**, 삭제는 제외 목록에 유지 권장.
- 이름 매칭 모호성 문제는 call-control과 동일하게 적용됨.

### 2.3 integrations (Google Calendar) — ⚠️ 부분 가능

**코드 확인 결과**:
- `src/services/gcal_service.py::get_oauth_status(owner)` — 조회만 가능(기존대로 유지).
- `src/services/gcal_service.py::delete_token(owner)` + `src/api/routers/google_calendar.py::connection_disconnect(owner)` —
  **"연동 해제" 액션은 이미 존재하는 단순 함수 호출**이다(OAuth 재인증 불필요, 그냥 저장된 토큰 삭제).
- 반면 "연동"(최초 연결)은 Google OAuth 브라우저 리디렉션이 필수라 **대화형으로는 원천적으로 자동화 불가**
  (사용자가 직접 브라우저에서 로그인·동의해야 함 — 이 부분은 PRD도 이미 이렇게 명시하고 있어 정합적임).

**구현 방향(제안)**: `integrations` 도메인에 `update_fn` 대신 "액션형" Tool 1개만 추가:
```python
async def disconnect_calendar_integration(owner: str) -> dict:
    from src.services.gcal_service import delete_token
    delete_token(owner)
    return {"ok": True}
```
`field="connected", value=False`로 들어오면 이 함수를 호출하도록 매핑하고, `value=True`(연동 시도)는
"브라우저에서 직접 연동해야 합니다. 설정 > 일반 화면 안내" 응답으로 명시적으로 거부(자동화 대상 아님을 알림).

**리스크/고려사항**:
- 연동 해제는 예약 캘린더 동기화 파이프라인에 영향(브리프 §Risk 참고) — "해제하면 이후 예약이 캘린더에 자동 반영되지
  않는다"는 부작용 안내를 확인 발화에 반드시 포함해야 한다(매뉴얼에 이미 있는 문구 재사용 가능).
- 원래 `destructive=True`로 등록되어 있었던 이유(파급 범위 불확실)와 상충되지 않도록, "연동 해제"만 예외적으로
  허용하고 그 외 필드는 계속 제외 상태 유지.

### 2.4 general (테넌트 프로필) — ❌ 현재 구조로는 불가능

**코드 확인 결과**: `src/api/routers/tenants.py::TENANTS_DATA`는 파이썬 리스트에 하드코딩된 시드 데이터이며,
**어떤 라우터에도 PATCH/PUT 갱신 엔드포인트가 없다**(GET만 존재). 즉 대시보드 화면 자체도 이 값을 바꿀 수
있는 UI/API가 없는 것으로 보인다(프론트엔드에서 실제로 편집 가능한지 별도 확인 필요하나, 백엔드에 쓰기
경로가 없는 것은 확실).

**결론**: 이 도메인은 "AI가 아직 자동설정을 못 지원"하는 게 아니라, **애초에 프론트엔드/백엔드 어디에도
쓰기 기능 자체가 없는 정적 데이터**다. 따라서 FR6("프론트엔드에서 API로 설정 가능한 항목은 AI로도 설정
가능해야 한다")의 전제(= "프론트에 쓰기가 존재한다")가 이 도메인에는 성립하지 않는다.

**구현 방향(제안, 선택 사항)**: 정말 필요하다면 (a) `TENANTS_DATA`를 SQLite 테이블로 이전하고 (b) 프론트엔드에
편집 UI/API를 먼저 만든 뒤에야 (c) `settings_catalog`에 update_fn을 등록할 수 있다 — 이는 셀프서비스 Epic의
범위를 넘는 **별도의 선행 백엔드 작업**이므로 이번 확장 대상에서 제외하고 읽기 전용으로 유지할 것을 권장한다.

---

## 3. 권장 다음 단계

1. **PRD 갱신**: FR6/FR11을 "카탈로그 등록 도메인 = 자동설정 가능 후보"로 유지하되, `general`은 각주로
   "프론트엔드에도 쓰기 경로가 없는 정적 데이터라 자동설정 대상에서 구조적으로 제외"라고 명시해 갭이 아닌
   **의도된 제약**으로 문서화.
2. **신규 Story 제안**(본 리포트 범위 밖, 별도 착수 필요): "Story 1.14 목록형 도메인 자동설정 확장"
   — call-control(규칙 on/off) + contacts(연락처 필드 갱신) 대상, 이름 기반 항목 매칭 + 모호성 재질문 +
   영향 범위 안내 포함 확인 발화 설계.
3. **소규모 즉시 적용 가능 항목**: `integrations`의 "연동 해제" 액션은 새로운 상호작용 모델 없이 기존
   `update_fn(owner, field, value)` 시그니처에 그대로 끼워 넣을 수 있으므로(단일 액션이라 목록 조회가
   불필요), 원하면 별도 Story 없이 소규모 패치로 바로 추가 가능.

*본 리포트는 검토·방향 제시 목적이며, 이번 세션에서는 코드 변경을 수행하지 않았다(사용자 확인 후 착수 권장).*

*최종 업데이트: 2026-07-20*
