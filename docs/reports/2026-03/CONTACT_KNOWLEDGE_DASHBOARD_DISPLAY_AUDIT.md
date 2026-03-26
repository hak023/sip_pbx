# 연락처(호 전환) 지식 — owner vs 전화번호·화면 표시 점검

- **작성일**: 2026-03-23  
- **상태**: 코드·UI 점검 완료  

---

## 1. 질의 요약

대시보드 지식 페이지에서 **카테고리「연락처 (호 전환)」**로  
전화번호 `1004`, 부서 `상담원`, 내용 `기상청 상담원`을 넣었을 때:

1. **1004로 호 전환이 되는가?**  
2. **목록에 보이는 값(예: owner=1004, doc_type=지식, source=대시 입력)이 입력과 어긋나 보이는데 괜찮은가?**

---

## 2. 결론

| 항목 | 결과 |
|------|------|
| **1. 1004 전환** | **카테고리가 실제로 `contact`로 저장되고**, 메타에 **`phone_number=1004`**가 있으면 `ContactKnowledgeExtractor`가 후보로 잡을 수 있으며, 유사도 상위 결과에 들면 **`initiate_call_transfer(..., target_number="1004")`가 호출될 수 있다.** (SIP/TransferManager 쪽 설정은 별도.) |
| **2. 화면과 입력의 차이** | **대부분 정상 동작에 맞는 표시다.** 다만 **목록에 `phone_number`/`department` 컬럼이 없어** 사용자가 **owner 열을 “내가 넣은 전화번호”로 오해하기 쉽다.** → **프론트 목록에「전화번호」「부서」열 추가(2026-03-23 반영).** |

---

## 3. 필드 의미 (백엔드)

- **`owner`**: 테넌트(착신 내선·로그인 tenant). **항상 폼의「착신」**. 전화번호 입력란과 **다른 필드**. 값이 우연히 같아도 의미는 다름.  
- **`phone_number`**: 연락처 카테고리 전용 메타. **호 전환 대상 번호**.  
- **`department`**: 멘트·로그용 부서명.  
- **`documents` 텍스트(내용)**: 벡터 검색용 본문. 예: `기상청 상담원`.  
- **`doc_type`**: 기본 선택값이 `knowledge`인 경우가 많음. **연락처 검색은 `category=contact`만 필터**하므로 `doc_type=knowledge`여도 **전환 퀵 경로에 포함 가능**.  
- **`source: api`**: API 저장 시 고정. UI 라벨은 **`대시 입력`**으로 매핑됨(`KNOWLEDGE_SOURCES`).

---

## 4. 관련 코드

- 저장: `src/ai_voicebot/knowledge/knowledge_service.py` — `add_knowledge`, `contact` 시 `phone_number`/`department` 메타  
- 전환 검색: `src/ai_voicebot/knowledge/contact_extractor.py` — `where: owner + category=contact`  
- 프론트 폼: `frontend/app/knowledge/page.tsx` — `category === 'contact'`일 때 `phone_number`, `department` 전송  

---

## 5. UI 변경 요약

- `frontend/app/knowledge/page.tsx` 지식 목록 테이블에 **전화번호**, **부서** 열 추가.  
- `frontend/types/index.ts` `KnowledgeItem.metadata`에 `phone_number`, `department`, `name` 선택 필드 명시.
