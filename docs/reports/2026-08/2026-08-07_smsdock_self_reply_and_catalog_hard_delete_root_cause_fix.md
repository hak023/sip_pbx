# SMS Dock 자기 채팅 무응답 + 카탈로그/화면 안내 "삭제 불가" 근본 원인 수정

- 작성일: 2026-08-07
- 버전: 1.0
- 상태: 완료(코드 수정 + 단위 검증), 실서버 재기동 후 라이브 검증 필요
- 관련 문서:
  - [2026-08-07_catalog_screen_graph_tenant_scope_gap_and_plan.md](./2026-08-07_catalog_screen_graph_tenant_scope_gap_and_plan.md)
  - [2026-08-07_catalog_screen_graph_tenant_scope_phase1_implementation.md](./2026-08-07_catalog_screen_graph_tenant_scope_phase1_implementation.md)

## 1. 문제 요약

사용자가 이전 리포트에서 "수정 완료"로 보고받았던 두 문제가 실제로는 해결되지 않은 채 재발했다고 지적함:

1. **SMS Dock(GlobalSmsDock)으로 자기 자신에게 질문을 보내도 AI 응답이 오지 않음.**
2. **설정 카탈로그/화면 안내 지식베이스에서 "전체 삭제"를 눌러도 "삭제 불가(시스템 공통)" 배지가 계속 남고, 실제로 아무것도 지워지지 않음.**

두 문제 모두 이전 세션에서 "수정했다"고 보고되었으나, 근본 원인이 아니라 표면적인 코드 변경(예: DB
스키마에 owner 컬럼만 추가)에 그쳤던 것이 재확인됨.

## 2. 근본 원인

### 2.1 SMS Dock 자기 채팅 무응답

`src/sip_core/sip_endpoint.py`의 `_deliver_chat_message_virtual()`가 셀프서비스 AI 자동 응답을
`chat_relay_settings.message_ai_reply_enabled`(테넌트 설정) 하나로만 게이팅하고 있었다. 이 설정은
원래 "실제 고객이 테넌트 번호로 문자를 보냈을 때 AI가 대신 응답할지"를 결정하는 **별개의 기능**을
위한 것인데, PRD FR34-E가 요구하는 "테넌트 관리자가 자기 자신에게 문자를 보내 셀프서비스 AI와
실제로 대화하는 테스트 패널" 기능까지 같은 플래그로 묶어버린 것이 원인이었다.

- 확인: curl로 owner=1001의 `chat_relay_settings.message_ai_reply_enabled`가 `false`임을 확인.
- 확인: `app.log`에서 자기 채팅 전송 시 `code: "delivered_web_notification"`만 반복되고
  `schedule_sip_message_ai_reply()` 호출 자체가 전혀 일어나지 않음을 확인.
- `_handle_sip_message_method()`(실제 SIP MESSAGE 데이터그램 경로)는 GlobalSmsDock이 타는
  경로가 아님(GlobalSmsDock → `/api/chat/send` → `send_chat_sip_message()` →
  `_deliver_chat_message_virtual()`, owner가 실제 REGISTER된 SIP 단말이 아니므로).

### 2.2 카탈로그/화면 안내 "삭제 불가"

두 단계의 원인이 겹쳐 있었다.

1. **설계 갭(이전에 이미 진단)**: `purge_owner_versions(owner)`는 owner 전용 행을 지울 뿐이고,
   지운 직후 `get_active_config(kind, owner)`는 owner 전용 활성 버전이 없으니 즉시
   `owner=''`(전역 기본값)로 폴백한다 — "삭제"가 시각적으로 아무 효과가 없었다.
2. **오늘 새로 발견한 진짜 차단 원인**: 위 갭을 고치기 위해 "삭제 후 owner 전용의 빈 활성
   버전을 새로 만든다"는 `clear_owner_catalog()`를 구현해 실제 DB에 테스트했더니
   ```
   UNIQUE constraint failed: self_service_catalog_config.config_kind,
   self_service_catalog_config.version_no
   ```
   로 저장 자체가 실패했다. 원인은 `self_service_catalog_config` 테이블이 애초에
   `UNIQUE(config_kind, version_no)`(owner 컬럼을 아예 모르는 옛 제약)로 생성되어 있었고,
   이전 세션에서 `ALTER TABLE ... ADD COLUMN owner`와 `CREATE UNIQUE INDEX
   idx_self_service_catalog_config_owner_version ON (...)`를 추가했지만, **SQLite는
   테이블 정의에 이미 컴파일된 UNIQUE 제약을 ALTER로 제거/변경할 수 없어** 옛 제약이 그대로
   살아있었다. 그래서 owner=1001이 전역과 같은 `version_no`(1, 2, ...)로 저장을 시도하면
   무조건 충돌해 저장이 실패했고, 실패는 로그 경고로만 남아 `get_active_config`가 조용히
   전역 값으로 폴백 — "삭제해도 그대로 보인다"는 증상의 진짜 원인이었다.

## 3. 수정 내용

### 3.1 SMS Dock 자기 채팅

`src/sip_core/sip_endpoint.py::_deliver_chat_message_virtual()`:
```python
should_reply = is_self_chat or (ai_reply_enabled and not suppress_ai_loop)
if should_reply and not suppress_ai_loop:
    ...schedule_sip_message_ai_reply(...)
```
`message_ai_reply_enabled`가 꺼져 있어도 자기 채팅(`is_self_chat`)이면 항상 셀프서비스 AI가
응답하도록 분리. 실제 고객 자동응답 기능(`message_ai_reply_enabled` 게이트)은 그대로 유지.

### 3.2 카탈로그/화면 안내 하드 삭제

1. **`src/booking/database.py`**: `_rebuild_self_service_catalog_config_table()` 신규 —
   `sqlite_master`에서 옛 `UNIQUE(config_kind, version_no)` 제약이 남아있는 테이블을 감지하면
   테이블을 재생성(`RENAME → CREATE(새 제약) → INSERT SELECT → DROP`)해 새 제약
   `UNIQUE(config_kind, owner, version_no)`으로 교체. `init_db()`에서 마이그레이션 직후 호출.
   멱등적(이미 새 스키마면 아무 것도 하지 않음).
2. **`src/common/self_service_catalog_config_db.py`**: `clear_owner_catalog(owner)` 신규 —
   `purge_owner_versions()`로 owner 전용 행을 지운 뒤, `catalog`/`screen_graph` 각각에
   대해 **빈 설정**(`{"domains": {}}` / `{"screens": {}}`)을 owner 전용 새 버전으로 저장·활성화.
   전역(`owner=''`) 데이터는 절대 건드리지 않음.
3. **`src/ai_voicebot/self_service/knowledge_documents.py::reset_knowledge_base()`**: 기존
   `purge_owner_versions()` 호출을 `clear_owner_catalog()`로 교체.

## 4. 검증 결과

- 구문 검사: `ast.parse()`로 3개 수정 파일 모두 통과.
- 단위 테스트: `pytest tests_new/unit/test_ai_voicebot -q` — 대상 모듈(카탈로그 설정 DB,
  knowledge_documents 등) 관련 테스트 전부 통과(무관한 사전 실패 1건은 아래 5절 참조).
- 실제 DB 마이그레이션 검증: `data/booking.db`에 대해 `init_db()` 실행 →
  `self_service_catalog_config` 테이블이 새 `UNIQUE(config_kind, owner, version_no)` 제약으로
  재생성되었고 기존 12행(전역 catalog/screen_graph 각 6버전)이 손실 없이 그대로 보존됨을 확인.
- 실제 DB 기능 검증: `clear_owner_catalog('1001')` 호출 →
  - `get_active_config('catalog', '1001')['config_json']['domains']` == `{}` (기존 폴백값
    대신 실제로 빈 값)
  - `get_active_config('screen_graph', '1001')['config_json']['screens']` == `{}`
  - `get_active_config('catalog', '')`(전역)는 기존 7개 도메인 그대로 유지 — 다른 테넌트에
    영향 없음 확인.

## 5. 남은 작업 / 알려진 이슈

- **실서버 재기동 필요**: 두 수정 모두 프로세스 재시작이 필요한 코드 변경(핫리로드 대상 아님).
  포트(8000/5060/8001) 재시작은 사용자 승인 후 진행 예정.
- **재기동 후 라이브 재검증 필요**:
  1. GlobalSmsDock으로 owner=1001 자기 채팅 전송 → 응답 코드가 `delivered_ai_self_service`이고
     실제 AI 답장이 채팅 스레드에 나타나는지 확인.
  2. `/settings/ai-assistant/docs`에서 owner=1001 "전체 삭제" 실행 → 카탈로그/화면 안내
     클러스터가 실제로 사라지는지(또는 0건) 확인, "삭제 불가" 배지 재검토.
- **무관한 사전 회귀 발견(이번 수정 범위 아님)**:
  `tests_new/unit/test_ai_voicebot/test_knowledge_documents_service.py::
  TestRegisterDocumentMarkdown::test_register_markdown_document_uses_manual_adapter`가
  현재 브랜치에서 실패(`content=None`을 마크다운 파서에 넘길 때 `expected string or
  bytes-like object, got 'NoneType'`). `git stash`로 이번 세션 전체 변경을 되돌린
  `origin/main` 상태에서는 통과함을 확인 — 이번 세션의 다른(이번 두 수정과 무관한) 변경으로
  발생한 회귀로 추정되며, 별도 조사·수정이 필요함.

*최종 업데이트: 2026-08-07*
