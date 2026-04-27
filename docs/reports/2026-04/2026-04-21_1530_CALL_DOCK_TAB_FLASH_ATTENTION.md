## 메타

- **작성일**: 2026-04-21
- **상태**: 구현 완료
- **관련**: Call Dock 인입 알림

## 개요

전화 인입 시 사용자 주목을 위해 (1) **다른 탭**이면 브라우저 **탭 제목 교차 표시**, (2) **통화 진행(active)** 동안 Call Dock 카드·최소화 버튼에 **펄스·링 강조**를 적용한다. 기존 데스크톱 알림·벨과 병행되며, Dock 설정에서 각각 끌 수 있다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `frontend/lib/incomingCallAttention.ts` | 추가 | `startIncomingCallTitleAlert` / `stopIncomingCallTitleAlert` | 900ms 교차 |
| `frontend/components/ActiveCallDockProvider.tsx` | 수정 | `visibilitychange` + phase/callId로 탭 제목 동기화 | 백그라운드에서만 깜빡임 |
| `frontend/store/useActiveCallDockStore.ts` | 수정 | `flashTabTitle`·`flashDockAttention` 설정, persist `merge`로 구버전 스토리지 호환 | |
| `frontend/components/GlobalCallDock.tsx` | 수정 | 진행 중 Dock·미니 버튼 Tailwind 강조, 설정 체크박스 2개 | |

## 주요 결정 사항

- **탭 제목**: `document.hidden` 일 때만 교차 표시. 탭으로 돌아오면 즉시 원 제목 복구(동일 탭에서 깜빡 방지).
- **Dock 강조**: `phase === "active"` 일 때만(종료·요약 단계는 기본 스타일).
- **`window.focus()`**: 브라우저가 막는 경우가 많아 자동 호출은 하지 않음(기존 알림 클릭 시 `focus` 유지).

## 잔여 과제

- 없음(선택: `navigator.wakeLock` 등은 정책·배터리 이슈로 미적용).
