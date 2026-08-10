# 지식 업로드 탭 — 문서 목록 패널 "Failed to fetch" 및 중복 조회 수정

- 작성일: 2026-08-06
- 상태: 코드 수정 완료(서버 미기동 상태라 재기동 후 재현 검증 필요)
- 관련 문서: [2026-08-06_frontend_ia_and_kb_ux_review.md](./2026-08-06_frontend_ia_and_kb_ux_review.md)

## 증상 (사용자 보고)

1. 지식 업로드 자체는 백엔드 로그(`knowledge_document_registered`)상 성공 — 그러나 프론트
   어디서 성공 여부를 확인해야 하는지 알 수 없었음.
2. "업로드" 버튼 아래 다른 패널(업로드된 문서 목록 테이블)에서 `Failed to fetch` 발생.
3. `/api/knowledge-base/documents` GET이 의도치 않게 여러 번 호출됨.

## 근본 원인

`sip-pbx/frontend/app/settings/ai-assistant/docs/page.tsx`의 데이터 로드 `useEffect`
(구 995행 부근):

```tsx
if (tab === "kb" && owner && kbDocuments.length === 0 && !loadingKbDocuments) void loadKbDocuments();
if (tab === "upload" && uploadSection === "tenant" && owner) void loadKbDocuments();
```

`kb` 탭 조건에는 "이미 로드됐으면 재조회하지 않는다"는 가드(`kbDocuments.length === 0`)가
있지만, `upload` 탭 조건에는 이 가드가 빠져 있었다. 이 effect의 의존성 배열에
`kbDocuments.length`가 포함돼 있어 다음 순환이 발생한다:

1. 사용자가 문서를 업로드 → `handleUploadDocument`가 성공 시 자체적으로
   `loadKbDocuments()`를 호출(정상 동작).
2. `kbDocuments` state가 갱신되며 `.length`가 바뀜 → 의존성 배열 변경으로 effect가 재실행.
3. `upload` 탭 조건에는 가드가 없으므로 **effect가 다시 `loadKbDocuments()`를 호출** →
   방금 시작한(또는 방금 끝난) 요청과 겹치는 두 번째 GET이 발사됨.
4. 겹친 요청 중 하나가 취소되거나 응답이 무시되면 브라우저가 `TypeError: Failed to fetch`를
   던지고, 이는 `apiJson()`의 catch 블록을 거쳐 그대로 `kbDocumentsError`에 표시된다 —
   업로드는 성공했는데 바로 아래 목록 패널에는 네트워크 오류가 뜨는 현상의 원인.
5. 같은 이유로 탭을 오가거나 상태가 조금만 바뀌어도 매번 무가드로 재조회가 발생해
   "조회가 너무 많다"는 3번 증상과 직결된다.

## 수정

`upload` 탭 조건에도 `kb` 탭과 동일한 "최초 1회만 로드" 가드를 추가:

```tsx
if (tab === "upload" && uploadSection === "tenant" && owner && kbDocuments.length === 0 && !loadingKbDocuments) void loadKbDocuments();
```

`handleUploadDocument`가 업로드 성공 시 이미 명시적으로 `loadKbDocuments()`를 호출해 목록을
갱신하므로, effect는 "탭 진입 시 최초 1회"만 담당하면 충분하다 — 중복 트리거 경로 제거.

## 1번(어디서 확인?) 관련

업로드 성공 여부는 별도 화면을 찾을 필요 없이, **업로드 폼 바로 아래 "업로드된 지식 문서"
테이블**(같은 `upload` 탭)에 즉시 반영된다. 이번 수정 전에는 위 버그로 이 테이블 자체가
자주 오류를 표시해 확인이 불가능했던 것 — 수정 후에는 업로드 직후 이 테이블에 새 문서가
바로 나타나는 것으로 확인 가능하다(추가로 "지식베이스 현황" 탭에도 동일 문서가 상세 카드로
노출됨).

## 검증 상태

현재 프론트/백엔드 서버가 모두 기동되어 있지 않아(포트 3000/8000 확인 결과 리스닝 없음)
브라우저 실시간 재현은 하지 못했다 — **서버 재기동 여부를 사용자에게 확인 후** 진행 필요
(포트 충돌 자동 실행 금지 규칙).

## 남은 이슈 (별도 확인 필요)

- `sample_manual_qa.md` 업로드가 "안 되는 듯" 하다는 이전 보고는 이번 세션에서 재현 로그를
  받지 못해 미해결 — 서버 재기동 후 동일 파일로 재현 시 백엔드 로그(`knowledge_document_registered`
  이벤트 유무, 에러 스택)를 다시 확인해야 한다.

*최종 업데이트: 2026-08-06*
