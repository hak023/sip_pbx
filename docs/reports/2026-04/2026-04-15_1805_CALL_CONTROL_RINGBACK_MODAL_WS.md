## 메타

- 작성일: 2026-04-15
- 상태: 완료
- 관련: `frontend/app/settings/call-control/page.tsx`, `frontend/hooks/useWebSocket.ts`

## 개요

통화 연결음 저장 후 모달이 열린 채로 남던 문제는 스케줄/규칙과 달리 `saveRingbackAssignment` 가 모달을 닫지 않고 `setEditingRingbackAssignment` 만 갱신했기 때문이다. Suno 완료 후에도 목록이 `pending` 에 고정된 것은 이 페이지에서 `wsClient.on` 만 등록하고 **`useWebSocket()` 으로 connect 가 호출되지 않아** `ringback_music_ready` 를 받지 못했기 때문이다. 보조로 Suno `pending` 인 동안 10초 간격 `loadAll` 폴링을 추가했다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----|-----|---|---|
| `sip-pbx/frontend/app/settings/call-control/page.tsx` | 수정 | 저장 성공 시 모달 닫기; `useWebSocket()`; pending Suno 시 10초 폴링 | 스케줄 `saveSchedule` 패턴과 정렬 |
| `sip-pbx/docs/reports/2026-04/2026-04-15_1805_CALL_CONTROL_RINGBACK_MODAL_WS.md` | 추가 | 본 리포트 | |

## 주요 결정 사항

- 착신 제어 페이지 진입 시 토큰이 있으면 WS 연결을 보장해 ringback 이벤트 수신.
- 폴링은 WS 이중 안전망이며, `pending` 이 없으면 interval 정리.

## 잔여 과제 (선택)

- 다내선·다 탭에서 동시 `useWebSocket` 호출은 싱글톤이므로 무방.
