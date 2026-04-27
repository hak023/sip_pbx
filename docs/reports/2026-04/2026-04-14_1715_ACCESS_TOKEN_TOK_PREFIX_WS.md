# access_token 미인식·콜도크 미구독 — 원인 및 수정

- **작성일(로컬)**: 2026-04-14
- **상태**: 구현 완료

## 개요

로그인 시 `localStorage.access_token`에 값이 들어가도 `useWebSocket`이 연결하지 않아 콜도크가 `call_started`를 못 받는 문제를 점검했다. 원인은 **백엔드 `/api/auth/login`이 발급하던 불투명 토큰이 프론트 `isAcceptableWebSocketToken` 조건(JWT 또는 `tok_*`)을 만족하지 않아 곧바로 삭제되던 것**과, **루트 레이아웃에 고정된 `useWebSocket` effect가 `[]` 의존성이라 로그인 직후 라우트만 바뀌면 재연결하지 않던 것**이었다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `sip-pbx/src/api/routers/auth_compat.py` | 수정 | `access_token`을 `tok_{secrets.token_urlsafe(32)}` 형식으로 발급 | WS 게이트와 주석 정합 |
| `sip-pbx/frontend/hooks/useWebSocket.ts` | 수정 | `usePathname` 의존으로 라우트 전환 시 토큰 재평가·연결; 무효 토큰 시 `disconnect` | `'use client'` 선언 |
| `sip-pbx/frontend/app/login/page.tsx` | 수정 | API 베이스를 `getApiUrl()`로 통일(동일 출처 `/api` 프록시 지원) | 테넌트·로그인 fetch |

## 주요 결정 사항

- 토큰 형식은 **기존 Socket.IO·프론트 규약(`tok_*`)에 맞춤**; 별도 “콜도크 전용 토큰”은 두지 않음.
- 로그인 페이지의 `localStorage.setItem('access_token', …)` 로직은 이미 올바르며 **저장 누락이 아닌 값 형식 문제**였음.

## 잔여 과제 (선택)

- 장기적으로 JWT 표준만 쓸 경우 `isAcceptableWebSocketToken`과 백엔드를 한줄로 정리.
