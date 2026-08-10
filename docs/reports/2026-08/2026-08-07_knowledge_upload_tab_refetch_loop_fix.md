# 지식 업로드 탭 `/api/knowledge-base/documents` 반복 재조회 구조 개선

- 작성일: 2026-08-07
- 버전: v1.0
- 관련 문서: [self-service-ai-assistant-architecture.md](../../architecture/self-service-ai-assistant-architecture.md)

## 1. 증상

`/settings/ai-assistant/docs` 페이지의 "지식 업로드" 탭에서 `/api/knowledge-base/documents` 조회가
비정상적으로 여러 번 반복 발생하며 화면이 계속 갱신되는 현상.

## 2. 근본 원인

`frontend/app/settings/ai-assistant/docs/page.tsx`에 `items`/`catalog`/`screens`/`intentTypes`/
`manualCases`/`decisionSessions`/`kbInventory`/`kbDocuments`/`loadingKbDocuments`를 전부 의존성
배열에 묶은 **거대한 단일 `useEffect`** 하나가 8개 탭의 데이터 로딩을 모두 담당하고 있었다. 이
구조에 두 가지 결함이 있었다:

1. **"배열 길이 === 0"을 "아직 로드 안 함"으로 오판**: 테넌트가 실제로 문서를 0개 업로드한
   상태(신규 테넌트 등)라면 `kbDocuments.length`가 영원히 0이므로, 이 조건은 절대 참을 벗어나지
   못한다.
2. **무관한 탭의 로더 완료가 전체 effect를 재실행시킴**: 의존성 배열에 8개 상태가 전부 묶여
   있어서, 예를 들어 "list"(통합 리스트) 탭에서 `loadCatalog()`가 끝나 `catalog.length`가
   0→N으로 바뀌기만 해도 이 effect 전체가 재실행되며, 그 안에 있던 "지식 업로드" 탭 조건까지
   다시 평가된다.

두 조건이 겹치면, 실제 업로드 문서가 없는 테넌트로 "지식 업로드" 탭에 들어갔을 때 다른 탭들의
백그라운드 로딩이 끝날 때마다 `loadKbDocuments()`가 계속 재호출되어 사용자에게는 "페이지가 계속
갱신되는" 것처럼 보였다.

## 3. 수정 내용

`frontend/app/settings/ai-assistant/docs/page.tsx`:

- 8개 자원 로딩을 각각 독립된 `useEffect`로 분리(qa/catalog/screen/policy/manualCases/
  decisionSessions/kbInventory/kbDocuments).
- "배열 길이" 대신 **"이미 시도했는가"를 `useRef`로 직접 추적**하도록 변경:
  - 테넌트 무관 자원(catalog/screen/policy): `useRef<boolean>` — 최초 1회만 로드.
  - 테넌트별 자원(qa/manualCases/decisionSessions/kbInventory/kbDocuments): `useRef<string | null>`에
    owner 값 자체를 저장 — owner가 바뀔 때만 재조회, 결과가 빈 배열이어도 재조회하지 않음.
- kb 탭과 upload 탭(tenant 세그먼트)이 공유하던 `kbDocuments` 로딩은 하나의 effect로 통합해
  중복 조회를 원천 제거.
- 각 effect의 의존성 배열을 `[tab, owner, ...]`처럼 최소화해, 무관한 탭의 상태 변화가 다른
  탭의 로더를 더 이상 재트리거하지 않는다.

## 4. 검증

- `npx tsc --noEmit` 0에러, `npx eslint app/settings/ai-assistant/docs/page.tsx` 0에러(프론트엔드는
  jest 없음 — 2026-08-06 Story 1.41 메모에 기록된 대로 정적 검증으로 대체).
- 실서버 브라우저 확인(네트워크 탭에서 `/api/knowledge-base/documents` 호출 횟수)은 다음 세션에서
  사용자가 직접 확인 권장.

*최종 업데이트: 2026-08-07*
