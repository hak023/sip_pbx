# 통화 지식 추출 `stored: 0` — 프론트 검색 불가 점검 (~AuVUsapcs)

- **작성일**: 2026-03-28 (로컬)
- **상태**: 로그 분석 + 코드 수정(환각 검증 입력)
- **관련 로그**: `app.log` 6256–6267 근처
- **코드**: `extraction_pipeline.py`, `hallucination_checker.py`, `rag_knowledge_text.py`

## 1. 결론 (프론트 이슈가 아님)

로그 마지막 줄:

- `"stored": 0` → **VectorDB에 한 건도 upsert 되지 않음**
- `"skipped_halluc": 3`, `"verified": 0` → Stage 3 품질 검증에서 **환각 검사 미통과 3건**으로 전부 제외

따라서 **지식이 저장된 것이 아니라**, 프론트 지식베이스 검색이 안 되는 것은 정상 동작에 가깝다.

## 2. 파이프라인 단계 요약

1. Stage 2: `judge_usefulness` → `is_useful: true`, `extracted_info` 3건 (LLM 판단 완료)
2. Stage 3: 항목마다 `HallucinationChecker.check(extracted, transcript)` — **여기서 3건 모두 탈락**
3. Stage 4: `verified_items`가 비어 **저장 루프 미실행**

## 3. 탈락 원인(코드): RAG 접두 + 환각 구문 검증

서술형 지식(`doc_type=knowledge`)은 저장 전에 `apply_rag_knowledge_prefix`로  
`고객이 알 수 있어야 할 정보: ` 접두가 붙는다.

환각 검증 1단계(`hallucination_checker._syntactic_check`)는 **추출 텍스트의 토큰**이 **전사**에 얼마나 있는지 비율로 본다.  
접두어 토큰(예: 고객이, 있어야, 정보 …)은 **전사에 없음** → 매칭 비율이 떨어져 `SYNTACTIC_THRESHOLD`(0.4) 미만으로 **전 건 실패**할 수 있다.

## 4. 조치 (구현)

- `rag_knowledge_text.strip_rag_knowledge_prefix()` 추가
- `ExtractionPipeline` Stage 3에서 `doc_type == "knowledge"`일 때만 환각 검증 입력을 **접두 제거 후** `check()`에 전달 (저장용 `item.text`는 접두 유지)

## 5. 재실행 시 유의

- 동일 통화에 대해 **후처리 재추출**을 다시 돌리면, 위 수정 후에는 구문 검증이 전사와 맞을 가능성이 높아진다.
- 전사에 **STT 오인식 문장**(예: 기상청·화장품 혼재)이 그대로 있으면, LLM이 그 “원문”을 추출해 `is_useful: true`로 줄 수 있다. 함의 검증은 `confidence >= 0.9`일 때 생략되므로, **내용 품질**은 별도 정책(프롬프트·품질 게이트)으로 다루는 것이 좋다.

## 6. 프론트에서 확인할 때

- API/검색이 **owner(착신자)·컬렉션·review_status** 필터를 쓰는지 확인 (저장된 문서만 노출 등).
- 본 케이스는 **저장 자체가 0**이므로 검색 결과 없음이 맞다.
