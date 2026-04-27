## 개요

착신 제어(Call Control) 기능을 체계적으로 재설계·구현하였다. 기존에 `config.yaml`의 `no_answer_timeout`과 대시보드 헤더의 자리비움 토글에 분산되어 있던 착신 동작 설정을 **착신 라우팅 규칙 + 시간 스케줄 + 안내멘트**의 3요소 체계로 통합하고, `/settings/call-control` 설정 페이지에서 운영자가 직접 관리할 수 있도록 하였다.

---

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|---|---|---|---|
| `sip-pbx/src/call_control/__init__.py` | 추가 | 모듈 패키지 초기화 | 신규 |
| `sip-pbx/src/call_control/models.py` | 추가 | RoutingRule, Schedule, AnnouncementProfile, RingGroup, CallerFilter, OverflowPolicy Pydantic 모델 | 신규 |
| `sip-pbx/src/call_control/db.py` | 추가 | SQLite CRUD (5개 테이블: call_routing_rules, call_schedules, announcement_profiles, call_ring_groups, call_caller_filters, call_overflow_policies) | 신규 |
| `sip-pbx/src/call_control/routing_engine.py` | 추가 | 현재 시각·스케줄 매칭, 공휴일 체크, 발신자 필터 매칭 | 신규 |
| `sip-pbx/src/api/routers/call_control_api.py` | 추가 | REST API 라우터 (rules/schedules/announcements/ring-groups/caller-filters/overflow) | 신규 |
| `sip-pbx/src/api/main.py` | 수정 | call_control_api 라우터 등록, init_call_control_db 호출 추가 | 설계대로 |
| `sip-pbx/src/sip_core/sip_endpoint.py` | 수정 | `_handle_invite_b2bua` — 발신자 필터 → 스케줄 규칙 → operator_status 순 라우팅 결정, 안내멘트 조회, `_effective_no_answer_timeout` 적용 | 설계대로 |
| `sip-pbx/src/sip_core/call_manager.py` | 수정 | `handle_no_answer_timeout`에 `greeting_override` 파라미터 추가, Pipecat builder에 전달 | 설계대로 |
| `sip-pbx/src/ai_voicebot/pipecat/pipeline_builder.py` | 수정 | `build_and_run`에 `greeting_override` 파라미터 추가, 안내멘트 텍스트로 TTS 인사말 대체 | 설계대로 |
| `sip-pbx/frontend/app/settings/call-control/page.tsx` | 추가 | 착신 제어 설정 페이지 (착신 규칙·스케줄·안내멘트·착신 그룹·발신자 필터 탭) | 신규 |
| `sip-pbx/frontend/components/AppHeader.tsx` | 수정 | 헤더의 OperatorAvailabilityToggle·AIFallbackModeSelector 제거, 현재 착신 정책 상태 배지(`CallControlStatusBadge`) + 네비 항목 '착신 제어' 추가 | 기존 기능 이전 |

---

## 주요 결정 사항

### 1. 라우팅 우선순위 체계
착신 발생 시 아래 순서로 평가한다.
```
발신자 필터 (CallerFilter, VIP/차단) 
  → 시간 스케줄 기반 규칙 (RoutingRule + Schedule)
  → operator_status.py (기존 away mode) 폴백
  → 기본 직접 연결
```
기존 `operator_status` 코드는 삭제하지 않고 Call Control 규칙이 없을 때의 폴백으로 유지하여 이전 호환성을 보장한다.

### 2. 5가지 착신 동작 모드
- `direct`: A→B 직접 연결 (기본)
- `no_answer_ai`: N초(10/20/30) 무응답 시 AI 응대
- `immediate_ai`: 항상 즉시 AI 응대 (기존 away mode 대체)
- `forward`: 지정 내선/SIP URI로 착신전환
- `ring_group`: 착신 그룹 (모델 정의 완료, SIP 구현은 다음 버전)

### 3. DB 위치
`data/call_control.db` (환경변수 `CALL_CONTROL_DB_PATH`로 재정의 가능). 기존 `calls.db`, `booking.db`와 분리하여 책임을 명확히 한다.

### 4. 안내멘트 연동
착신 규칙에 `announcement_id`가 설정된 경우 `AnnouncementProfile.text`를 조회하여 Pipecat 파이프라인의 초기 인사말(`send_greeting`)에 `greeting_override`로 주입한다. TTS 생성은 기존 파이프라인이 담당한다.

### 5. 헤더 UI 단순화
기존 헤더의 자리비움 토글·HITL/상담원 모드 스위치를 제거하고 `/settings/call-control` 페이지로 이전하였다. 헤더에는 현재 적용 중인 착신 정책 이름을 보여주는 읽기 전용 배지만 남겨 간결함을 유지한다.

### 6. 공휴일 지원
`holidays` Python 패키지를 선택적 의존성으로 사용한다. 패키지가 없어도 공휴일 조건만 비활성화될 뿐 나머지 기능은 정상 동작한다.

---

## 추가 기획된 편의기능 (모델·DB 정의 완료, UI/SIP 구현 예정)

| 기능 | 현황 |
|------|------|
| 착신 그룹 (RingGroup) | 모델·DB·API 완료. SIP 순차/동시 링 구현 필요 |
| 발신자 필터 (CallerFilter) | 모델·DB·API·SIP 연동 완료 |
| 통화량 오버플로우 (OverflowPolicy) | 모델·DB·API·UI 완료. SIP에서 활성 통화 수 체크 구현 필요 |
| DND (방해 금지) | 설계에서 언급, 구현 미착수 |
| 콜백 예약 | 기존 booking 기능과 연동 설계, 구현 미착수 |

---

## 잔여 과제

1. `RoutingAction.RING_GROUP` 및 `RoutingAction.FORWARD`에 대한 `sip_endpoint.py` 분기 처리 (현재 forward_to 저장만, SIP REFER/재-INVITE 구현 필요)
2. OverflowPolicy에서 실시간 활성 통화 수를 `CallManager`에서 조회하는 연동
3. 착신 그룹(RingGroup)의 SIP 동시/순차 링 구현
4. 안내멘트의 `audio_file` 업로드 및 파일 기반 재생 구현
5. `holidays` 패키지 `requirements.txt` 추가 (선택)
