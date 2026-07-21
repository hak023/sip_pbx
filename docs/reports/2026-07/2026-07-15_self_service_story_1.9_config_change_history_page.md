# Story 1.9 (자동설정 변경 이력 프론트엔드 페이지) 구현 완료 보고서

**작성일**: 2026-07-15
**관련 문서**: [1.9.config-change-history-page.story.md](../../stories/1.9.config-change-history-page.story.md), [1.8.auto-config-write-tool.story.md](../../stories/1.8.auto-config-write-tool.story.md)
**상태**: 완료 (Story Status → Review) — **Epic 1(셀프서비스 AI 도우미) 전체 9개 Story 완료**

## 1. 문제 요약

Story 1.8까지 완성된 자동설정(쓰기) 기능은 AI가 대화로 실제 설정을 변경하지만, 관리자가 "AI가 방금 무엇을 바꿨는지" 화면으로 확인할 방법이 없었다. 이 Story는 Epic에서 유일하게 신규 REST 엔드포인트가 필요한 예외 Story다.

## 2. 사전 점검: PO/QA 검토에서 발견된 문서 불일치 수정

Story 1.9 착수 전, 직전 PO/QA 검토 세션에서 지적된 사항을 재확인한 결과 `docs/stories/1.8.auto-config-write-tool.story.md`의 **Tasks/Subtasks 체크박스 5개가 전부 미체크(`[ ]`) 상태로 되돌아가 있음**을 발견했다(Dev Agent Record·File List·Change Log는 정상적으로 완료 내용을 담고 있어 실제 작업 결과와 문서 표시가 불일치하는 상태였음). 실제 완료된 내용(코드·테스트로 이미 검증됨)에 맞춰 5개 Task와 하위 항목을 모두 `[x]`로 복원하고, Task 4에 PO/QA 검토에서 발견한 owner 강제 오버라이드 보안 수정 내역을 추가 기록했다.

## 3. 구현 내용

### 3.1 백엔드 REST 엔드포인트 (Task 1)

- `src/api/routers/self_service.py` 신규: `GET /api/self-service/config-changes?owner=...&limit=...`
- `src/common/self_service_config_change_db.py::list_config_changes()`(Story 1.8에서 이미 구현됨)를 그대로 호출하는 얇은 라우터 — 새 조회 로직을 만들지 않음(CR4)
- `src/api/main.py`에 라우터 등록

### 3.2 프론트엔드 페이지 (Task 2)

- `frontend/app/settings/ai-assistant/page.tsx` 신규
- Dev Notes가 참고 컴포넌트로 지목한 `settings/persona/page.tsx`는 실제로는 빈 리다이렉트 페이지였음을 확인 → 실제 데이터 로드 패턴을 가진 `settings/chat-relay/page.tsx`(`useState`/`useEffect` + `apiJson` + `getTenantOwner`)를 참고해 구현
- 도메인·필드·이전값→새값·변경 시각·call_id를 테이블로 표시, 도메인명은 한글 라벨로 매핑

### 3.3 네비게이션 통합 (Task 3)

- `frontend/components/AppHeader.tsx`의 `SETTINGS_NAV` 배열 끝에 "셀프서비스 AI 도우미" 섹션 + 링크 추가
- `SETTINGS_LINK_HREFS`/`settingsAreaActive`가 `SETTINGS_NAV`에서 자동 파생되는 구조라 기존 항목을 건드리지 않고 안전하게 추가(IV1 코드 구조상 보장)

### 3.4 테스트

`tests_new/unit/test_ai_voicebot/test_self_service_config_changes_api.py` 신규 5개: 실제 SQLite 파일로 owner 격리, `changed_at DESC` 정렬, 필드 포함 여부, 빈 이력 처리, limit 파라미터 전달 검증(Story 1.8의 통합 테스트 패턴 재사용).

## 4. 문서 동기화

- `docs/SYSTEM_OVERVIEW.md` §4.11에 "변경 이력 화면" 항목 및 Story 1.9 링크 추가
- `docs/INDEX.md` Dev Stories 표에서 1.9 상태를 Draft → Review로 갱신
- `docs/stories/1.8.auto-config-write-tool.story.md`의 Task 체크박스 불일치 수정(위 2절)

## 5. 검증 결과

```
python -m pytest tests_new/unit/test_ai_voicebot/test_self_service_config_changes_api.py -v --no-cov
→ 5 passed

python -m pytest tests_new/unit/test_ai_voicebot tests_new/unit/test_events -q --no-cov
→ 169 passed (Story 1.1~1.8 누적 164 + 신규 5), 회귀 없음
```

## 6. 변경 파일

- `src/api/routers/self_service.py` (신규)
- `src/api/main.py` (수정 — 라우터 등록)
- `frontend/app/settings/ai-assistant/page.tsx` (신규)
- `frontend/components/AppHeader.tsx` (수정 — 네비게이션 추가)
- `tests_new/unit/test_ai_voicebot/test_self_service_config_changes_api.py` (신규, 5 tests)
- `docs/stories/1.9.config-change-history-page.story.md` (Task 1~3 체크, Dev Agent Record/Change Log 갱신, Status → Review)
- `docs/stories/1.8.auto-config-write-tool.story.md` (Task 체크박스 불일치 복원)
- `docs/SYSTEM_OVERVIEW.md`, `docs/INDEX.md` (Story 1.9 반영)

## 7. Epic 1 최종 현황

**Story 1.1~1.9 전체 완료(Status=Review)**. 셀프서비스 AI 도우미(자기 호출 감지 → 대화 레인 → 매뉴얼 RAG → 온보딩 체크리스트 → 설정 조회/통계/자동설정 Tool → 변경 이력 화면)가 백엔드·프론트엔드 전 구간 구현되었다. 전체 회귀 테스트 169개 통과. 실제 배포 전 남은 작업은 실 LLM(Gemini bind_tools) 환경에서의 수동 통합 테스트뿐이다(PO/QA 리포트에 기 명시).

---
*최종 업데이트: 2026-07-15*
