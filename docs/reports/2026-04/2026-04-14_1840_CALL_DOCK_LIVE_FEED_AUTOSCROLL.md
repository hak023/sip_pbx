## 개요

콜도크(GlobalCallDock)의 **실시간 대화(STT/TTS)** 영역에 스크롤이 생길 때, 새 줄·갱신 시 **맨 아래로 자동 스크롤**되도록 했다. 사용자가 위로 스크롤해 과거를 읽는 중에는 **끌어올리지 않도록** 하단 72px 이내일 때만 적용한다. 통화 ID가 바뀌면 다시 하단 고정으로 리셋한다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `sip-pbx/frontend/components/GlobalCallDock.tsx` | 수정 | `liveFeedScrollRef` + `onScroll`으로 하단 근접 여부 추적, `useLayoutEffect`로 `scrollTop` 동기화, `activeCallId` 변경 시 핀 리셋 | 설계대로 |

## 주요 결정 사항

- **`useLayoutEffect`**: DOM 반영 직후 스크롤해 깜빡임을 줄임.
- **하단 근접 임계 72px**: 일반적인 “채팅 앱” 패턴과 동일하게, 위로 읽는 중 자동 스크롤로 방해하지 않음.
- **`dockExpanded` 의존성**: 접었다 펼칠 때 피드가 다시 보이면, 핀이 켜져 있으면 최신으로 맞춤.

## 메타

- 작성일: 2026-04-14
- 관련: `useActiveCallDockStore` → `liveFeedLines` (병합 시마다 새 배열 참조)
