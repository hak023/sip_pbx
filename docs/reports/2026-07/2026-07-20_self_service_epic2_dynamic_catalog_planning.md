# 셀프서비스 AI 도우미 — Epic 2 기획 완료 보고서 (설정 카탈로그/Screen Graph 동적화)

**작성일**: 2026-07-20
**상태**: 기획(설계) 완료 — **구현은 착수하지 않음**, 모든 Story는 Status=Draft
**관련 문서**:
- [self-service-ai-assistant-brief.md](../../product/self-service-ai-assistant-brief.md) §Phase 2
- [self-service-ai-assistant-prd.md](../../product/self-service-ai-assistant-prd.md) §Epic 2
- [self-service-ai-assistant-architecture.md](../../architecture/self-service-ai-assistant-architecture.md) §Epic 2 Component Architecture
- [docs/stories/2.1~2.8.*.story.md](../../stories/)

---

## 1. 요청 요약

사용자가 지적한 3가지 구조적 문제:
1. 설정 카탈로그·Screen Graph가 Python 하드코딩 레지스트리라, 신규 기능이 생길 때마다 백엔드
   코드 배포가 필요함 — 프론트엔드에서 설정을 보여주고 다운로드/업로드해 문서 기반으로 동적
   제공되도록 개선 검토.
2. IntelliDecision(Story 1.10)이 정규식 키워드 매칭으로 힌트를 만드는데, STT 오인식·말의
   부정확성으로 오동작 위험이 있어 LLM 기반 판단으로 전환 검토.
3. 1번과 관련해 지식베이스든 DB든 실제로 "동적 구성"이라 부를 수 있는지 기능 체크 필요.

요청은 "BMAD 기반으로 설계/개발/QA 되도록 기획해달라"였다. 본 세션에서는 **기획(Brief/PRD/
Architecture/Story) 산출까지 완료**했고, 실제 코드 구현은 착수하지 않았다 — 이유는 §5 참고.

## 2. 하드코딩 실태 전수 조사 결과

| 파일                                    | 하드코딩 내용                                                        | 동적화 가능 여부                                                                                         |
| --------------------------------------- | -------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `settings_catalog.py::_CATALOG`         | 7개 도메인의 스키마·writable_fields·field_allowed_values·destructive | ✅ 메타데이터는 가능(단, get_fn/update_fn 실행 로직은 코드 유지)                                          |
| `screen_graph.py::_SCREEN_REGISTRY`     | 6개 화면의 route·title·description·nav_hint·UI 필드                  | ✅ 전부 순수 데이터라 100% 동적화 가능                                                                    |
| `config/self_service_exclusions.yaml`   | 제외 목록                                                            | 이미 YAML(파일 편집만으로 반영) — 기존 방식이 부분적으로 이미 동적, Epic 2 착수 시 통합 여부 결정(CR6)   |
| `intent_tier.py`                        | 탐색성/실행성 판별 정규식                                            | 데이터화 대상 아님 — **제거**가 답(§3)                                                                   |
| `onboarding.py::_CHECKS`                | 온보딩 체크 대상 3개 + 판정 함수                                     | 판정 로직(코드) + 문구(데이터) 혼재 — 이번 Epic 범위에는 포함하지 않음(영향도 낮다고 판단, 필요 시 후속) |
| `manual_indexer.py::_SECTION_TO_DOMAIN` | 매뉴얼 섹션 제목 키워드 → 도메인 매핑                                | ✅ 매뉴얼 문서 자체의 태그로 대체 가능(Story 2.8, 낮은 우선순위)                                          |

## 3. 핵심 설계 결정

### 3-1. "메타데이터 동적화" vs "완전 노코드" — 명확히 구분

`get_fn`/`update_fn`이 호출하는 실제 서비스 함수(예: `persona_service.save_persona`)는 여전히
Python 코드로 존재해야 한다. **DB에 임의 Python 표현식을 저장해 실행하는 구조는 채택하지
않는다**(RCE 위험). 대신:
- 코드에는 "함수 이름 문자열 → 콜러블" **화이트리스트 레지스트리**만 유지.
- DB(동적 저장소)에는 스키마·라벨·허용값·화면 안내 문구 등 **서술 메타데이터**만 저장, 함수는
  이름으로만 참조.
- 완전히 새로운 도메인(신규 비즈니스 로직)은 여전히 코드 배포가 필요함을 PRD·Story에 명시적으로
  문서화(FR22) — "왜 업로드만으로 안 되냐"는 오해를 방지.

### 3-2. IntelliDecision 키워드 힌트 — 대체 방안 비교 후 "제거" 권장

| 방안                             | 설명                                          | 채택 여부    |
| -------------------------------- | --------------------------------------------- | ------------ |
| A. 힌트 제거, LLM 단일 호출 유지 | 기존 메인 LLM 호출의 few-shot 지시만으로 판단 | ✅ 권장(채택) |
| B. 전용 분류 LLM 호출 추가       | 힌트 산출을 위해 별도 LLM 호출 추가           | ❌ 기각       |

이유: 힌트는 이미 "참고 신호일 뿐 최종 판단 아님"으로 설계돼 있고, 2026-07-16 QA
([1.10 실행 결과](../2026-07/2026-07-16_self_service_story_1.10_qa_execution_result.md) §4-1)에서
힌트가 틀려도 LLM이 항상 올바르게 판단함이 이미 실증됐다. 즉 힌트는 실질적 이득 없이 STT
오인식 시 "잘못된 참고 신호"라는 리스크만 추가하는 상태다. 방안 B는 NFR1(응답 지연 예산)을
해치면서까지 얻을 이득이 없다고 판단해 기각했다. → **Story 2.6에서 완전 제거**를 권장(단,
베이스라인 확보 후 제거·재검증 순서를 반드시 지키도록 Task 순서에 명시).

### 3-3. 저장소 선택 — SQLite(booking.db 공유) vs ChromaDB

카탈로그/Screen Graph 설정은 구조화 데이터(키-값, 스키마)이며 벡터 유사도 검색이 필요 없다.
`self_service_config_changes`(Story 1.9)와 동일한 SQLite 공유 파일에 신규 테이블을 추가하는
쪽을 권장(기존 컨벤션 재사용, 신규 인프라 없음).

## 4. 산출물

| 문서                          | 변경 내용                                                                                   |
| ----------------------------- | ------------------------------------------------------------------------------------------- |
| brief (v0.4)                  | §Phase 2 신설 — 문제 인식·목표·명시적 범위 제외                                             |
| PRD (v0.5)                    | Epic 2 신설 — FR16~24, NFR6~8, CR5~6, Story 2.1~2.8                                         |
| architecture (v0.4)           | §Epic 2 Component Architecture 신설 — 저장소·로더·화이트리스트·API·프론트엔드 컴포넌트 설계 |
| Story 2.1~2.8                 | 신규 8개 파일(전부 Status=Draft)                                                            |
| INDEX.md / SYSTEM_OVERVIEW.md | Epic 2 참조 반영(구현 전임을 명시)                                                          |

## 5. 이번 세션에서 구현을 착수하지 않은 이유

Epic 2는 **이미 프로덕션에서 검증되어 동작 중인 Epic 1(Story 1.1~1.13) 전체의 기반 모듈
(`settings_catalog.py`, `screen_graph.py`)을 리팩터링**하는 작업이다. 회귀 위험이 Epic 1 전체
기능(설정 조회·자동설정·온보딩·Screen Graph 안내)에 걸쳐 있어, 계획 없이 바로 착수하면 검증되지
않은 대규모 변경이 된다. BMAD 하네스 원칙(PRD→architecture→story→구현→테스트→QA)에 따라
Story 단위로 순차 착수하는 것이 안전하며, 사용자가 우선순위·순서(예: Story 2.1부터 시작할지,
Story 2.6 IntelliDecision부터 먼저 볼지)를 확인한 뒤 진행하는 것을 권장한다.

## 6. 다음 단계 제안

1. Story 2.1(저장소 설계) → 2.2/2.3(로더 동적화, 순수 리팩터링) → 2.4/2.5(프론트엔드
   다운로드/업로드) → 2.6(IntelliDecision 힌트 제거) → 2.7(통합 QA) 순으로 착수 권장.
2. Story 2.8(매뉴얼-도메인 매핑 동적화)은 우선순위가 낮아 여유가 있을 때 진행.
3. 사용자 확인 필요 사항: (a) 파일 포맷은 JSON/YAML 중 무엇을 선호하는지, (b) 업로드 권한을
   어떤 기준으로 제한할지(NFR8, 현재 프론트엔드에 별도 role 체계가 있는지 확인 필요), (c) Epic 2
   착수를 이번 계획대로 진행해도 될지.

*최종 업데이트: 2026-07-20*
