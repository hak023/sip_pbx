# 셀프서비스 AI 도우미 핵심 기능(Story 1.1~1.7) 외부 레퍼런스 리서치 완료 보고

**작성일**: 2026-07-29
**작업 유형**: 순수 리서치(코드 변경 없음)

## 요약

사용자가 이전 응답에서 승인한 우선순위(IntelliDecision → RAG → Tool-calling → 설정 카탈로그 →
온보딩 체크리스트 → 통계 자연어 질의 → 셀프콜 감지)에 따라, 셀프서비스 AI 도우미 Epic 1의
핵심 기능 7개 각각에 대해 학술 연구자료·산업 적용 사례·상용 레퍼런스·대안 비교·장단점을
정리했다.

## 산출물

- [SELF_SERVICE_CORE_FEATURES_EXTERNAL_RESEARCH.md](../../design/SELF_SERVICE_CORE_FEATURES_EXTERNAL_RESEARCH.md)
  신규 작성(`docs/design/`).
- `docs/INDEX.md`에 신규 문서 인덱스 반영.

## 조사 방법

웹 리서치(arXiv 원 논문, Google/Anthropic 공식 문서, Wikipedia)와 저장소 내 기존 리서치 문서
(`SELF_SERVICE_INTELLIDECISION_KNOWLEDGE_STRUCTURING_RESEARCH.md`,
`2026-07-23_intellidecision_enhancement_research.md`)를 교차 참조했다. 주요 인용 자료:

- Stolcke et al. (2000), *Dialogue Act Modeling...*, Computational Linguistics — 대화행위 태깅 학술 근거
- Lewis et al. (2020), *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks*
  (NeurIPS 2020, arXiv:2005.11401) — RAG 원 논문
- Askari et al. (NAACL 2025, arXiv:2402.11633) — LLM 기반 의도 인식 데이터 생성 최신 연구
- Anthropic, *Building Effective Agents* (2024-12) — Routing 워크플로/Tool 설계 원칙
- Google, Gemini API 함수 호출 공식 문서 — Tool-calling 표준 흐름·권장사항

## 핵심 발견

1. IntelliDecision(발화 유형 판단)은 LLM 기반 의도 분류라는 최신 연구 흐름과 정합하나, Dialogflow
   CX 등 상용 제품 대비 "판단 근거 로깅(설명가능성)"이 유일한 개선 여지로 확인됨 — 후속 Story
   후보로 리서치 문서에 명시.
2. RAG(경량 벡터검색)/설정 카탈로그(메타데이터 화이트리스트)는 이미 업계 표준 패턴을 따르고
   있으며, Full GraphRAG·완전 노코드 등 과설계 대안은 재차 기각이 타당함이 재확인됨.
3. Tool-calling은 벤더 SDK 마이그레이션 리스크(google-generativeai→google-genai 실사례)가
   실존하나, MCP 표준화는 현재 규모에서 비용 대비 이득이 낮아 보류가 합리적.
4. 통계 자연어 질의는 "LLM 직접 SQL 생성" 업계 트렌드보다 "Tool 화이트리스트 + 결과 요약"이라는
   현재 보안 우선 설계가 멀티테넌트 환경에 더 적합함이 재확인됨.

## 후속 조치 필요 여부

코드 변경 없음. 사용자가 위 개선 제안(특히 IntelliDecision 판단 근거 로깅) 중 착수를 원하면
BMAD 절차(PRD 갱신 → architecture → story)로 후속 진행 필요.

*최종 업데이트: 2026-07-29*
