## 메타

- **작성일(로컬)**: 2026-04-16
- **상태**: 기능 검증 정리 + UI 소수정(라벨)
- **참고 리포트**: `2026-04-16_0930_GLOBAL_CALL_DOCK_AND_CALLER_CONTEXT_API.md`

## 개요

리포트에 적힌 CID·GlobalCallDock 기능이 **코드상 존재**하나, 사용자가 “변화 없음”으로 느끼기 쉬운 **전제 조건**이 많다. 아래 검증 절차대로 확인하면 동작 여부를 구분할 수 있다.

---

## 실제로 구현된 것 (코드 기준)

| 기능 | 위치 | 동작 조건 |
|------|------|-----------|
| 전역 플로팅 독 | `AppShell` → `GlobalCallDock` | 로그인 **이후** 페이지. `call_started` 수신 시 `phase !== idle` |
| Socket 구독 | `ActiveCallDockProvider` | `useWebSocket` → **유효 JWT/tok_** 있을 때만 `wsClient` 연결. 연결 전이면 리스너 미등록 |
| CID REST | `GET /api/call-history/caller-context` | `localStorage.tenant.owner` 또는 `tenant_id`로 **owner** 확보 + 발신 문자열에 **숫자 4자 이상** |
| 독 내 CID 문구 | `GlobalCallDock` | API 성공 시 `첫 통화` / `재방문` + 직전 일시·요약 |
| OS 알림 | `Notification` | 브라우저 **권한 허용** + 설정에서 데스크톱 알림 켬. “백그라운드만”이면 `document.hidden`일 때만 |
| 대시보드 딥링크 | `/dashboard?call_id=` | 독 버튼 또는 알림 클릭. 대시보드는 **활성 통화 목록에 해당 call_id가 있을 때** 피드 선택 우선 |

---

## “변화가 없다”로 보이는 대표 원인

1. **로그인 페이지만 사용**  
   `AppShell`이 독을 감싸지 않음 → 독 없음.

2. **토큰 없음 / 만료**  
   `useWebSocket`이 연결하지 않음 → `call_started` 미수신 → **독 영원히 미표시**.

3. **`tenant` JSON에 `owner` 없고 `tenant_id`도 비움**  
   `getTenantOwner()`가 빈 문자열 → **caller-context 호출 자체를 스킵**. (수정 전에는 `callerContext == null` 인데도 독에 “첫 통화”로 보일 수 있었음 → **“이전 통화 조회 중…”** 으로 표시 보강)

4. **인입 시 브라우저가 대시보드에만 있고 우하단을 안 봄**  
   독은 **우측 하단 고정**이라 기존 대시보드 레이아웃과 겹쳐 눈에 덜 띌 수 있음.

5. **`NEXT_PUBLIC_WS_URL` / 8001**  
   브라우저에서 Socket.IO가 실제 PBX와 붙지 않으면 이벤트 없음(Next `rewrites`는 **HTTP**용이며 WS URL은 별도).

6. **`call_records` DB 비어 있음**  
   CID API는 `has_prior_call: false` 정상 응답 → 독에는 “첫 통화” + “이전 통화 없음” 문구.

---

## 권장 검증 절차 (수동)

### A. REST만 (백엔드)

```http
GET /api/call-history/caller-context?owner=<착신내선>&caller=sip:01012345678@x&exclude_call_id=
```

- `200` + JSON에 `has_prior_call`, `prior_summary` 등 오면 API 정상.
- `400` + `owner and caller` → 쿼리 누락.
- `400` + `no dialable digits` → `caller`에 숫자 없음(SIP user에 번호 포함 필요).

### B. 독 + CID (프론트)

1. `sip-pbx/frontend` 기준으로 로그인 후 **대시보드가 아닌 페이지**(예: 지식베이스 `/knowledge`)를 연다.  
2. 개발자 도구 → Application → `tenant`에 **`owner` 문자열** 있는지 확인.  
3. 실제 인입 통화를 걸어 **`call_started`** 가 나가게 한다.  
4. 우하단에 카드가 뜨는지, CID 블록에 **“이전 통화 조회 중…” → 이후 “첫 통화” 또는 “재방문”** 으로 바뀌는지 확인.  
5. 탭을 다른 앱으로 가린 뒤 인입 → OS 알림(권한·설정 충족 시).

### C. 대시보드 `call_id`

1. 독에서 “대시보드에서 열기” 클릭 → URL에 `?call_id=` 포함.  
2. 해당 통화가 **활성 목록에 있을 때** 실시간 피드가 그 `call_id`로 맞춰지는지 확인.

---

## 변경 이력 (이번 검증 문서)

| 파일 경로 | 변경 유형 | 요약 |
|-----------|-----------|------|
| `sip-pbx/frontend/components/GlobalCallDock.tsx` | 수정 | `callerContext == null` 일 때 “이전 통화 조회 중…” (오인 “첫 통화” 방지) |
| `sip-pbx/docs/reports/2026-04/2026-04-16_1430_CID_GLOBAL_DOCK_VERIFICATION.md` | 추가 | 본 검증 리포트 |

## 잔여 과제

- 운영 가이드에 **tenant.owner 필수**·**WS URL**·**알림 권한**을 한 페이지에 적어 두면 재문의 감소에 유리함.
