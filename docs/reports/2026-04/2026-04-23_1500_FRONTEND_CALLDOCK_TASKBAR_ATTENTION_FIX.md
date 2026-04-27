## 개요

인입 시 **Chrome 작업표시줄 깜빡임(탭 제목 교차)** 과 **CID Call Dock 표시**가 함께 되어야 하는데, 실제로는 Call Dock UI의 `animate-pulse`만 두드러지고 작업표시줄 알림이 잘 안 느껴지는 현상을 코드 기준으로 점검하고, 타이틀 알림 조건을 보강하며 Dock 쪽 과한 펄스를 제거했다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|------------|------|------|
| `sip-pbx/frontend/components/ActiveCallDockProvider.tsx` | 수정 | 탭 제목 깜빡임: `document.hidden` 외 `document.hasFocus()` + `window` blur/focus 반영 | 설계 의도(백그라운드 알림) 보강 |
| `sip-pbx/frontend/components/GlobalCallDock.tsx` | 수정 | Call Dock 강조에서 `animate-pulse` 제거, 정적 링만 유지 | Dock만 “깜빡이는” 체감 완화 |
| `sip-pbx/frontend/components/GlobalCallDock.tsx` | 수정 | 설정 라벨 문구: 다른 탭·백그라운드 창 + 작업표시줄 명시 | UX 설명 |

## 주요 결정 사항

1. **원인**: `startIncomingCallTitleAlert`는 `visibilitychange` 기준으로 `document.hidden`일 때만 동작. Chrome에서 **다른 앱으로 포커스만 이동**하고 동일 탭이 화면에 남는 등의 경우 `hidden`이 계속 `false`인 빈틈이 있어, 타이틀 교차가 안 돌아가 작업표시줄 플래시가 없을 수 있음. 한편 `flashDockAttention`은 `phase === "active"`이면 **포그라운드에서도** `animate-pulse`로 Dock 전체가 깜빡여, 사용자는 “Dock만 깜빡임”으로 인지하기 쉬움.

2. **조치**: (a) `document.hidden || !document.hasFocus()`일 때 타이틀 알림 시작, `window` `blur`/`focus`로 동기화. (b) Dock 강조는 **정적 ring/shadow**만 사용해 통화 중 시각적 앵커는 유지하되 애니메이션 깜빡임은 제거.

## 잔여 과제

- OS·브라우저 조합에 따라 `hasFocus`/`blur` 타이밍 차이가 있을 수 있음. 현장에서 한 번 확인 권장.
- `Notification` 권한이 없으면 데스크톱 알림은 여전히 비활성(기존과 동일).
