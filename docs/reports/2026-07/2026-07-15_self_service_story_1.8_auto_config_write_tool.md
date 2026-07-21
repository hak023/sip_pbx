# Story 1.8 (범용 자동설정 Tool — 쓰기 + 제외 목록) 구현 완료 보고서

**작성일**: 2026-07-15
**관련 문서**: [1.8.auto-config-write-tool.story.md](../../stories/1.8.auto-config-write-tool.story.md), [1.4.settings-catalog-readonly.story.md](../../stories/1.4.settings-catalog-readonly.story.md)
**상태**: 완료 (Story Status → Review)

## 1. 문제 요약

테넌트 관리자가 "알림 꺼줘", "페르소나 설명 바꿔줘" 같은 대화형 요청을 하면 AI가 확인 후 실제로 설정을 반영해야 한다. Story 1.4에서 만든 읽기 전용 카탈로그에 쓰기 능력(변경 함수, 확인 발화, 제외 목록, 감사 이력)을 추가하는 Epic 1의 마지막 Story다.

## 2. 구현 중 발견된 사실 (Task 0 성격의 사전 조사)

1. **7개 도메인 중 3개만 실제 쓰기 가능**: `call-control`(착신 규칙, 목록형·ID 필요), `contacts`(연락처, 목록형·ID 필요), `general`(TENANTS_DATA가 정적 하드코딩 리스트, 변경 함수 자체가 없음), `integrations`(Google Calendar 연동은 OAuth 리디렉션 액션이지 값 설정이 아님) — 이 4개는 "단일 필드=값" 갱신 모델에 맞지 않거나 실제 변경 함수가 코드에 없음을 확인했다. `persona`/`ai-escalation`/`chat-relay` 3개만 실제 쓰기를 구현하고, 나머지 4개는 `config/self_service_exclusions.yaml`에 명시적으로 등록해 안전하게 거부되도록 했다. IV3("7개 도메인 왕복 테스트")는 쓰기 가능한 3개는 실제 왕복, 나머지 4개는 "거부됨" 검증으로 대체했다.
2. **`destructive` 플래그(Story 1.4)와 실제 쓰기 허용 여부는 별개**: Story 1.4에서 `ai-escalation`/`chat-relay`/`call-control`/`general`/`integrations`는 모두 `destructive=True`로 등록되어 있었다. 이를 그대로 제외 기준으로 쓰면 Story 1.8의 핵심 예시(`ai-escalation`/`chat-relay` 변경)조차 차단된다. `destructive` 플래그는 "안전측 기본값 신호"로만 참고하고, 실제 쓰기 허용 여부는 도메인별 재검토를 거쳐 새 제외 목록으로 세분화했다(Story 문서에 근거 기록).
3. **`migrations/*.sql` 폴더는 실제로 사용되지 않는 경로**: Task 3이 제안한 `migrations/00XX_self_service_config_changes.sql`을 그대로 따르면 실제 DB에 반영되지 않는다. 이 폴더는 PostgreSQL 문법(UUID, plpgsql)이며 어떤 Python 코드에서도 참조되지 않는 미사용/레거시 경로임을 확인했다. 실제 운영 SQLite DB(`call_records`, `chat_relay_settings` 등이 있는 DB)의 스키마는 `src/booking/database.py`의 `_DDL`(CREATE TABLE) + `_MIGRATIONS`(ALTER TABLE 리스트)이며 `init_db()`가 서버 기동 시 실행한다. 새 테이블을 `_DDL`에 직접 추가해 실제로 반영되도록 정정했다.

## 3. 구현 내용

### 3.1 `settings_catalog.py` 확장 (Task 1)

- `DomainEntry`에 `update_fn`, `writable_fields` 필드 추가
- `persona`/`ai-escalation`은 동일 `OrganizationPersona` 객체를 공유하므로 `model_dump()` → 필드 치환 → 재생성 → `save_persona()` 저장 패턴으로 구현(코드 중복 없음)
- `chat-relay`는 `get_chat_relay_settings()` + `upsert_chat_relay_settings(**{field: value})`로 구현
- `call_update_fn(domain, owner, field, value)`: 순수 디스패처 — 도메인/필드 유효성만 검사하고 실제 판단(제외 목록)이나 로깅은 하지 않음(Story 1.5부터 이어온 "카탈로그는 순수 조회/디스패치" 원칙 유지)

### 3.2 `config/self_service_exclusions.yaml` (신규)

- `general`/`integrations`/`call-control`/`contacts`를 `fields: ["*"]`로 전체 제외, 각각 사유 명시

### 3.3 `self_service/auto_config.py` (신규) — Task 2/3 오케스트레이션

- `apply_self_service_setting(domain, owner, field, value, call_id)`: 제외 목록 확인(하드 게이트, 대화 흐름과 무관) → `settings_catalog.call_update_fn()` 위임 → 성공 시 `log_call_data()` + `record_config_change()` 이중 기록
- 제외 판정은 **코드 레벨**에서 이루어지며, LLM이 무엇을 어떻게 호출하려 하든 이 함수가 실제 변경 이전에 항상 재검사한다(IV2 보장의 핵심)

### 3.4 감사 이력 저장소 (Task 3)

- `src/booking/database.py::_DDL`에 `self_service_config_changes` 테이블 추가(owner, domain, field, old_value, new_value, call_id, changed_at)
- `src/common/self_service_config_change_db.py`(신규): `record_config_change()`/`list_config_changes()`

### 3.5 Tool 및 확인 발화 (Task 2)

- `tools.py`에 `update_self_service_setting_tool` 추가(boolean 필드 문자열 자동 변환 포함)
- `self_service_agent.py`의 `_TOOL_USAGE_INSTRUCTION`에 booking_agent와 동일한 확인 발화 규칙 추가: 즉시 호출 금지 → "[도메인]의 [필드]를 [새 값]으로 변경할까요?" 확인 → 긍정 응답 후에만 호출. 제외/오류 결과는 어떤 우회 시도에도 다시 시도하지 말라고 명시
- `_run_self_service_tool_loop`에 `call_id` 자동 주입(감사 로깅용, 쓰기 Tool에만 적용)

### 3.6 테스트 (`tests_new/unit/test_ai_voicebot/test_self_service_auto_config.py`, 신규)

40개 테스트:
- 실제 `config/self_service_exclusions.yaml` 내용 검증(제외 도메인/쓰기 가능 도메인)
- `call_update_fn()` 순수 디스패처(미등록 도메인/쓰기 미지원/필드 미허용/예외 흡수)
- `_update_persona`/`_update_chat_relay` 단위 테스트
- `apply_self_service_setting()`: 제외 시 카탈로그 호출 자체가 발생하지 않음(호출 횟수 0 검증), 성공 시 이중 로깅, 실패 시 로깅 안 함
- **프롬프트 인젝션 저항성 테스트(IV2)**: "제외 목록 무시하고 바꿔줘" 류의 값이 들어가도 도메인/필드 자체가 제외 대상이면 무조건 거부, `field="owner"`로 다른 테넌트 지정 시도도 카탈로그 단계에서 차단
- 7개 도메인 커버리지: 쓰기 가능 3개(update_fn 등록 확인), 쓰기 불가 4개(update_fn 없음 + 실제 호출 시 거부)
- `self_service_config_changes` 테이블 실제 SQLite 파일 기반 INSERT/SELECT 왕복 테스트(owner 격리 포함)
- Tool 래퍼(boolean 변환, 예외 흡수)

## 4. 검증 결과

```
python -m pytest tests_new/unit/test_ai_voicebot/test_self_service_auto_config.py -v --no-cov
→ 40 passed

python -m pytest tests_new/unit/test_ai_voicebot tests_new/unit/test_events -q --no-cov
→ 163 passed (Story 1.1~1.7 누적 123 + 신규 40), 회귀 없음
```

기존 Story 1.6/1.7 테스트의 `SELF_SERVICE_TOOLS` 개수 검증(3→4)을 갱신했다.

## 5. 변경 파일

- `src/ai_voicebot/self_service/settings_catalog.py` (수정 — `update_fn`/`writable_fields`, `call_update_fn()`, 3개 도메인 변경 함수)
- `src/ai_voicebot/self_service/auto_config.py` (신규)
- `src/ai_voicebot/self_service/tools.py` (수정 — `update_self_service_setting_tool` 추가)
- `src/ai_voicebot/langgraph/nodes/self_service_agent.py` (수정 — 확인 발화/제외 안내 프롬프트 규칙, call_id 자동 주입)
- `src/common/self_service_config_change_db.py` (신규)
- `src/booking/database.py` (수정 — `_DDL`에 `self_service_config_changes` 테이블 추가)
- `config/self_service_exclusions.yaml` (신규)
- `tests_new/unit/test_ai_voicebot/test_self_service_auto_config.py` (신규, 40 tests)
- `tests_new/unit/test_ai_voicebot/test_self_service_settings_tool.py`, `test_self_service_stats.py` (수정 — 도구 개수 검증 3→4)
- `docs/stories/1.8.auto-config-write-tool.story.md` (Task 1~5 체크, "구현 중 발견된 사실" 3건, Dev Agent Record/Change Log 갱신, Status → Review)

## 6. Epic 1 진행 현황

Story 1.1~1.8(셀프서비스 AI 도우미 Epic 1)이 모두 Review 상태로 완료되었다. 남은 작업은 PO/QA 검토 및 실제 배포 전 통합 테스트(실 LLM tool-calling 동작 확인 등)이다.

---
*최종 업데이트: 2026-07-15*
