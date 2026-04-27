## 개요

CID Call Dock을 연락처 Dock과 같이 **통화가 없을 때도** 우하단에 항상 접근 가능한 필(버튼)을 두고, 펼치면 알림 설정·안내·대시보드 링크를 쓸 수 있게 했다. 사용자 질의에 따라 **웹 밖(다른 프로그램 위)에 Dock을 띄우는 것은 순수 웹앱 한계**임을 UI 문구로 짧게 안내했다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|------------|------|------|
| `sip-pbx/frontend/store/useActiveCallDockStore.ts` | 수정 | `idleLauncherMinimized`, `setIdleLauncherMinimized` 추가, `dismiss` 시 필로 복귀 | 기본 true |
| `sip-pbx/frontend/components/GlobalCallDock.tsx` | 수정 | `phase===idle`일 때 필·대기 패널, 설정 블록 `CallDockSettingsPanel` 공통화 | 연락처 Dock UX 정렬 |

## 주요 결정 사항

1. **항시 UI**: `phase === "idle"`에서 `null` 반환을 제거하고, 기본은 **「통화 · CID」** 원형 필(우하단). 클릭 시 패널 펼침.
2. **대기 패널**: 인입 없음 안내, Dock이 **브라우저 페이지 내부**에만 존재한다는 설명, `/dashboard` 링크, 기존과 동일한 알림·소리 설정.
3. **작업표시줄/별도 창**: 표준 웹만으로는 OS 전역 오버레이·다른 프로세스 위 항상 표시 불가. 선택지는 **PWA 설치(여전히 브라우저 엔진)**, **Electron/Tauri 등 데스크톱 래퍼**, **별도 네이티브 앱** — 구현 범위 밖이면 문서·기획 단계에서 결정.

## 잔여 과제

- PWA(`manifest`)로 “앱처럼” 작업표시줄 고정을 원하면 별도 작업.
- Electron 래퍼 시 `call_started`를 네이티브 트레이/플로팅 창으로 넘기는 설계 가능.
