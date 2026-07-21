# Story 1.4 (설정 카탈로그 읽기 전용 등록) 구현 완료 보고서

**작성일**: 2026-07-15
**관련 문서**: [1.4.settings-catalog-readonly.story.md](../../stories/1.4.settings-catalog-readonly.story.md), [self-service-ai-assistant-architecture.md](../../architecture/self-service-ai-assistant-architecture.md)
**상태**: 완료 (Story Status → Review)

## 1. 문제 요약

셀프서비스 AI 도우미가 이후 온보딩 안내(Story 1.5)·설정 조회 Tool(Story 1.6)·자동설정(Story 1.8)에서 "어떤 설정이 존재하는지"를 알 수 있으려면, 모든 설정 도메인을 한 곳에 등록한 카탈로그가 선행되어야 한다. Architecture 문서는 7개 도메인 중 3개(chat-relay, persona 추정, call-control 부분)만 확인했고 나머지 4개(ai-escalation, contacts, general, integrations)는 후보만 나열한 상태였다.

## 2. Task 0 — 백엔드 함수 확정 (사전 조사)

실제 코드를 조사해 7개 도메인의 백엔드 조회 함수를 모두 확정했다.

| 도메인          | 확정 함수                                                                           | 비고                                                                                    |
| --------------- | ----------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| `persona`       | `persona_service.PersonaService.get_persona(owner)` (async)                         |                                                                                         |
| `ai-escalation` | 동일 `get_persona(owner)`의 `escalation_mode`/`transfer_extension` 필드             | 프론트 `/settings/ai-escalation`도 `/api/persona/{owner}`를 그대로 사용함을 코드로 확인 |
| `call-control`  | `src/call_control/db.py::list_rules/list_schedules/list_announcements(owner)`       | 라우터가 아닌 데이터 접근 계층을 직접 호출(FastAPI Query 의존성 우회)                   |
| `chat-relay`    | `src/services/chat_relay_service.py::get_chat_relay_settings(owner)`                |                                                                                         |
| `contacts`      | `caller_contact_db.list_caller_contacts` + `contact_folder_db.list_contact_folders` | 프론트 `/settings/contacts`는 `/contacts`로 리다이렉트되지만 데이터 자체는 유효         |
| `general`       | `src/api/routers/tenants.py::TENANTS_DATA`(정적 하드코딩)                           |                                                                                         |
| `integrations`  | `src/services/gcal_service.py::get_oauth_status(owner)`                             | 프론트 `/settings/integrations`는 `/settings/general`로 리다이렉트                      |

**중요 발견**: 프론트엔드 조사 중 `integrations`→`general`, `contacts`(settings)→`/contacts` 리다이렉트를 발견했다. 즉 프론트 UI 탭은 이미 통합되어 있지만, 카탈로그 관점에서는 "테넌트 프로필"(general)과 "외부 연동"(integrations)이 자동설정 시 서로 다른 destructive 판단이 필요한 별개 개념이므로 AC1이 명시한 7개 도메인을 그대로 유지하기로 판단했다(디자인 판단, Story에 근거 기록).

## 3. 구현 내용

### 3.1 `src/ai_voicebot/self_service/settings_catalog.py` (신규)

- `DomainEntry` dataclass(`name`, `get_fn`, `schema`, `destructive`) + 모듈 레벨 `_CATALOG` 레지스트리
- 7개 도메인 전부 `async def` wrapper로 통일 등록 — `persona`만 실제 비동기 I/O이고 나머지는 내부적으로 동기 호출이지만, `get_domain_value()`가 sync/async 분기 없이 `inspect.isawaitable()`로 통일 처리하도록 인터페이스를 단순화
- `list_domains()`, `get_domain_schema(domain)`, `get_domain_value(domain, owner)` 3개 공개 API 구현
- `destructive` 기본값은 `True`(안전측). 명시적으로 안전하다고 판단한 `persona`(조직 소개 열람)·`contacts`(연락처 열람, 본 Story는 생성/수정/삭제 미포함)만 `False`로 지정
- 미등록 도메인 조회 시 `get_domain_schema` → 빈 dict, `get_domain_value` → `{"error": "unregistered_domain: ..."}`
- `get_fn` 예외는 `{"error": str(e)}`로 흡수해 부작용 없이 반환(IV1 보장)

### 3.2 테스트 (`tests_new/unit/test_ai_voicebot/test_settings_catalog.py`, 신규)

14개 테스트:
- `list_domains()`가 정확히 7개 도메인 반환
- `get_domain_schema()` 정상/미등록 케이스, destructive 기본값 확인
- `get_domain_value()` 미등록 도메인 오류, `get_fn` 예외 흡수
- 7개 도메인 각각 조회 왕복 테스트(IV2) — `general` 도메인은 정적 데이터라 실제 값으로 직접 검증, 나머지 6개는 하위 I/O 함수를 monkeypatch해 카탈로그 배선을 검증

## 4. 검증 결과

```
python -m pytest tests_new/unit/test_ai_voicebot/test_settings_catalog.py -v --no-cov
→ 14 passed

python -m pytest tests_new/unit/test_ai_voicebot tests_new/unit/test_events -q --no-cov
→ 74 passed (Story 1.1~1.4 누적 + 이벤트), 회귀 없음
```

## 5. 변경 파일

- `src/ai_voicebot/self_service/settings_catalog.py` (신규)
- `tests_new/unit/test_ai_voicebot/test_settings_catalog.py` (신규, 14 tests)
- `docs/stories/1.4.settings-catalog-readonly.story.md` (Task 0~3 체크, 백엔드 함수 확정 표, Dev Agent Record/Change Log 갱신, Status → Review)

## 6. 후속 작업

- Story 1.4는 **읽기 전용 조회**만 다룬다. 설정 변경(자동설정 실행)과 `destructive` 플래그의 실제 집행 로직은 Story 1.8에서 구현 예정.
- Story 1.5(온보딩 체크리스트) 착수 예정 — 본 카탈로그의 `list_domains()`/`get_domain_value()`를 활용해 미설정 항목을 판단.

---
*최종 업데이트: 2026-07-15*
