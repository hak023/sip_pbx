# 도메인 비종속 지식베이스 & IntelliDecision 플랫폼 — 설계 재작성 완료 리포트

**작성일**: 2026-08-04
**작업 유형**: 설계 문서 재작성 + BMAD 증분(PRD/architecture/Story), 코드 변경 없음
**관련 문서**:
- [SELF_SERVICE_RAG_INTELLIDECISION_ADVANCEMENT_RESEARCH.md](../../design/SELF_SERVICE_RAG_INTELLIDECISION_ADVANCEMENT_RESEARCH.md) v2.0(재작성됨)
- [self-service-ai-assistant-prd.md](../../product/self-service-ai-assistant-prd.md) FR32
- [self-service-ai-assistant-architecture.md](../../architecture/self-service-ai-assistant-architecture.md) v0.14
- [1.26.knowledge-base-document-crud-and-upload.story.md](../../stories/1.26.knowledge-base-document-crud-and-upload.story.md)

## 문제 요약

사용자가 2026-07-30 리서치(셀프서비스 매뉴얼 규모 전제)의 범위를 넘어서는 요구사항을 제시:
①도메인 비종속 ②웹 업로드 데이터 투입(포맷 정의 필요) ③지식베이스 CRUD ④IntelliDecision과
연계된 관계형 지식·hop 확장 ⑤⑥사전 예측 가능한 투명성(필요 시 시뮬레이션 기능) ⑦유형별 매칭 구조
투명 노출 ⑧⑨실사용 사례·연구자료 레퍼런스 조사 및 시스템 적용 방향 수립 ⑩문서 초안 재작성.

## 근본 원인/현황 진단

코드베이스를 직접 추적해 확인한 핵심 격차:
- `SourceAdapter` 프로토콜(Story 1.25)은 있으나 구현체가 `MarkdownManualAdapter` 하나뿐.
- `knowledge_graph.py::traverse()`는 `max_hops` 파라미터를 받지만 실제로는 고정 3단 체인만 순회
  — 진짜 n-hop 일반화가 아님.
- REST API 8종은 전부 읽기 전용 조회 또는 카탈로그 설정 관리 — 지식 콘텐츠 자체의 업로드/수정/
  삭제 API가 전혀 없음. 매뉴얼은 `.md` 파일 직접 편집 후 재색인만 가능(개발자 전용).
- "이 질문에 KB가 어떻게 응답할지" 실행 전 확인 방법이 없음 — 실제 대화를 태워봐야만 알 수 있는
  상태(사용자가 명시적으로 지적한 문제).

## 수행 내용

1. **레퍼런스 리서치**: Anthropic Contextual Retrieval(실증치 재확인, 청크 실패율 최대 67%↓),
   Intercom Fin(12,000+ 고객 실사용 — §10 노코드 지식 구성, §14 라이브 전 테스트 시뮬레이션, §13
   다단계 Procedures), Glean(Context Graph — 벡터+그래프 결합이 업계 표준 방향)을 링크·발췌와 함께
   조사하고 각각을 "우리 시스템 적용 방향"과 1:1 대응표로 정리.
2. **설계 문서 전면 재작성**: `SELF_SERVICE_RAG_INTELLIDECISION_ADVANCEMENT_RESEARCH.md`를 v2.0으로
   재작성(제목도 "도메인 비종속 지식베이스 & IntelliDecision 플랫폼 설계"로 변경) — 목표 재정의(6대
   목표), 현황 진단, 레퍼런스 비교표, 업로드/CRUD 설계(포맷 정의 포함), n-hop 그래프 일반화 방향,
   응답 시뮬레이터 설계(사용자 결정: 실제 LLM 응답까지 생성), Non-Goal 재확인, 로드맵(Story
   1.26~1.29)을 신설. 2026-07-30 원본 내용은 부록 A로 요약 대체.
3. **PRD 증분**: FR32(A~D 하위 요구사항) 신설, 버전 1.2→1.3, NFR8(업로드 격리·시뮬레이터 실행
   경로 분리 요건) 추가.
4. **Architecture 증분**: 버전 0.13→0.14, Change Log 행 추가, "도메인 비종속 지식베이스 플랫폼"
   신규 섹션(Story 1.26~1.29 설계 요약 포인터) 추가.
5. **Story 1.26 신규 작성**(Draft): 지식 문서 CRUD API + 업로드 프론트엔드, `PdfDocumentAdapter`/
   `OpenApiSpecAdapter` 신규 구현 포함 — 1단계부터 PDF/OpenAPI를 지원하기로 한 사용자 결정 반영.
6. `INDEX.md`의 해당 리서치 문서 행 갱신.

## 사용자 결정 사항 (확정, Story 작성에 반영)

- 업로드 포맷: 1단계부터 PDF/OpenAPI 포함(마크다운/텍스트로 축소 안 함).
- 응답 시뮬레이터: dry-run(매칭 문서만 미리보기)이 아니라 실제 LLM 호출로 최종 응답까지 생성.

## 검증

문서/계획 작업이라 코드 테스트는 해당 없음. 재작성된 설계 문서의 섹션 헤더를 grep으로 확인해
이전 버전의 중복/잔재 내용이 남지 않았음을 검증 완료.

## 남은 작업 (다음 세션)

- Story 1.26 Task 1(설계 스파이크)부터 실제 구현 착수.
- Story 1.27(응답 시뮬레이터)~1.29(Contextual Retrieval 스파이크)는 아직 Story 파일 자체가
  없으므로, Story 1.26 완료 후 순서대로 작성·착수할 것.

---

*최종 업데이트: 2026-08-04*
