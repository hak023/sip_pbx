# 페르소나 설정 UI 축소 — AI 에스컬레이션 전용

- **작성일**: 2026-04-14 (로컬)
- **상태**: 구현 완료

## 개요

조직 문구·키워드는 지식 베이스에서 관리하므로, 설정 메뉴의 페르소나 CRUD UI를 제거하고 **AI 한계 도달 시 에스컬레이션(HITL / SIP 호전환)** 만 설정하도록 바꿨다. 네비게이션 명칭은 **AI 에스컬레이션**이며 경로는 `/settings/ai-escalation`이다. `/settings/persona` 는 신규 경로로 리다이렉트한다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 |
|-----------|------------|------|
| `sip-pbx/frontend/app/settings/ai-escalation/page.tsx` | 추가 | 단일 테넌트(owner) 기준 에스컬레이션 UI·저장 |
| `sip-pbx/frontend/app/settings/persona/page.tsx` | 수정 | `/settings/ai-escalation` 리다이렉트만 |
| `sip-pbx/frontend/components/AppHeader.tsx` | 수정 | 링크·라벨 `AI 에스컬레이션` |
| `sip-pbx/src/api/routers/persona.py` | 수정 | `PUT /api/persona/{owner}/escalation` — 플레이스홀더로 시드 후 에스컬레이션만 갱신 |
| `sip-pbx/src/config/models.py` | 수정 | `OrganizationPersona` docstring 정리 |

## 주요 결정 사항

- 저장 API를 분리해 프론트가 name/description 없이 **에스컬레이션 필드만**내도 되게 했다. 최초 저장 시 서버가 플레이스홀더 name/description 으로 한 건 생성한다.
- 기존 `GET/POST/PUT/DELETE /api/persona/...` 는 다른 클라이언트·테스트용으로 유지한다.

## 잔여 과제

- 완전히 Persona REST를 숨기려면 관리용 목록·check-relevance 엔드포인트 정리(권한·문서)를 별도 검토할 수 있다.
