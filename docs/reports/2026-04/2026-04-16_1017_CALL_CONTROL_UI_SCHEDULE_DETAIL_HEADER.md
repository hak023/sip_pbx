## 개요

착신 제어 화면에서 착신 규칙 목록의 시간 조건을 이름 대신 **요일·시간·공휴일·타임존** 상세로 표시하고, 규칙·스케줄 **이름 입력란을 제거**한 뒤 저장 시 자동 이름을 부여한다. 규칙 카드에서는 **착신 동작 요약**을 크게 강조한다. 상단 헤더 배지와 페이지 내 «현재 적용 중» 문구는 **`{로그인 owner} : {동작 설명}`** 형식으로 통일한다(API 설명에 붙던 `규칙이름:` 접두는 첫 `:` 기준으로 제거).

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `sip-pbx/frontend/lib/call-control-display.ts` | 추가 | 스케줄 상세/한 줄 요약, 상태 줄, 규칙·스케줄 자동 이름 유틸 | 설계대로 |
| `sip-pbx/frontend/app/settings/call-control/page.tsx` | 수정 | 규칙 카드 UI, 모달에서 이름 필드 제거, 스케줄 탭·셀렉트 표기, 현재 적용 문구 | 설계대로 |
| `sip-pbx/frontend/components/AppHeader.tsx` | 수정 | 착신 상태 배지에 `formatCallControlStatusLine` 적용 | 설계대로 |

## 주요 결정 사항

- API `description`이 `규칙명: 동작` 패턴일 때 **첫 번째 `:` 뒤**만 동작으로 간주해 `{owner} : …`로 재구성한다. 콜론이 없으면 전체 문자열을 동작으로 둔다.
- 규칙/스케줄 DB `name`은 여전히 필요할 수 있어, 저장 시 **동작 요약·스케줄 한 줄 요약**으로 자동 채운다(사용자 입력 제거).
- 테넌트 표시는 로그인 시 쓰는 **`tenant_id` / `tenant.owner`**(`getTenantOwner()`)를 사용한다. 사용자 예시가 `1003` 형태였다.

## 잔여 과제 (선택)

- 백엔드가 `description`을 구조화 필드(`action_text`, `rule_label` 등)로 내려주면, 콜론 휴리스틱 없이 헤더 문구를 더 안정적으로 맞출 수 있다.

---

- 작성일: 2026-04-16 (로컬)
- 관련 경로: `app/settings/call-control`, `components/AppHeader`, `lib/call-control-display`
