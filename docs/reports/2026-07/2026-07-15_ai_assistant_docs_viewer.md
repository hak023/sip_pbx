# AI 도우미 도움말 문서 열람 기능 구현

**작성일**: 2026-07-15
**버전**: 1.0
**상태**: 완료
**관련 문서**: `sip-pbx/docs/product/self-service-manual-content.md`, `sip-pbx/docs/guides/USER_MANUAL.md`, `sip-pbx/docs/guides/AI_QUICKSTART.md`

---

## 1. 요약

셀프서비스 AI 도우미 설정 화면(`settings/ai-assistant`)에서 관련 도움말 문서를 원문(Raw Markdown) 그대로 열람할 수 있는 기능을 구현했다. 읽기 전용이며 문서 수정·입력은 지원하지 않는다.

---

## 2. 노출 대상 문서

| slug                  | 파일 경로                                     | 설명                                              |
| --------------------- | --------------------------------------------- | ------------------------------------------------- |
| `self-service-manual` | `docs/product/self-service-manual-content.md` | 서비스 이용 매뉴얼 (RAG 지식 소스 원본, Q&A 구조) |
| `user-manual`         | `docs/guides/USER_MANUAL.md`                  | 시스템 전체 사용 매뉴얼                           |
| `ai-quickstart`       | `docs/guides/AI_QUICKSTART.md`                | AI 보이스봇 빠른 시작 가이드                      |

---

## 3. 구현 내용

### 3-1. 백엔드 API — `src/api/routers/settings_ai_assistant.py` (신규)

| 엔드포인트                                   | 설명                                                      |
| -------------------------------------------- | --------------------------------------------------------- |
| `GET /api/settings/ai-assistant/docs`        | 노출 문서 목록 반환 (slug, title, description, file_name) |
| `GET /api/settings/ai-assistant/docs/{slug}` | slug에 해당하는 문서 원문(Raw Markdown) 반환              |

- 정적 카탈로그(`_DOCS`) 방식 — DB 불필요
- 경로는 서버 CWD(`sip-pbx/`) 기준 상대경로로 해석
- 파일 미존재 시 503, 슬러그 미매칭 시 404 반환

### 3-2. `src/api/main.py` 수정

`settings_ai_assistant_router` 임포트 및 `app.include_router()` 등록 추가.

### 3-3. 프론트엔드 — `frontend/app/settings/ai-assistant/docs/page.tsx` (신규)

- 좌측 사이드바: 문서 목록(제목+설명)
- 우측 본문: Raw Markdown을 `<pre>` 블록으로 표시
- 첫 번째 문서 자동 선택
- `apiJson()` 유틸 재사용, 로딩/에러 상태 처리

### 3-4. 기존 페이지 수정 — `frontend/app/settings/ai-assistant/page.tsx`

헤더 영역에 "도움말 문서" 버튼(아이콘 포함) 추가 → `/settings/ai-assistant/docs`로 이동.

---

## 4. 검증

- 백엔드 임포트 오류 없음 (`python -c "from src.api.main import app; ..."`)
- 라우트 등록 확인: `['/api/settings/ai-assistant/docs', '/api/settings/ai-assistant/docs/{slug}']`
- 프론트엔드 TypeScript 오류 없음

*최종 업데이트: 2026-07-15*
