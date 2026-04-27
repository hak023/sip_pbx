# CID 미표시·음성 예약 미처리 점검 (call 0EpX8dB6Qi)

- **작성일**: 2026-04-20 (로컬)
- **상태**: 분석 완료
- **근거 로그**: `sip-pbx/logs/call_data_record_20260420.log` (L12–42), `sip-pbx/logs/app.log` (해당 call_id 구간)

---

## 1. CID가 프론트에 안 보인 경우 — 로그 기반 결론

### 1.1 백엔드는 발신 정보를 알고 있고, Socket.IO `call_started`도 발행됨

`app.log`에서 본 통화는 **Call Control `no_answer_ai`**(10초 무응답 후 AI 인수) 경로다.

| 시각(대략) | 이벤트 | 의미 |
|------------|--------|------|
| 14:00:32.710 | `b2bua_invite_received` | caller **1004** → callee **1003** |
| 14:00:32.710 | `b2bua_ws_emit_call_started_scheduled` | `caller`: `sip:1004@10.2.5.57`, `callee`: `sip:1003@10.2.5.58`, `sip_phase`: **inviting** |
| 14:00:42.714 | `ai_call_started_event_emitted` | `handle_no_answer_timeout` 안에서 **`emit_call_started` 완료** 로그 (`call_manager.py`) |

즉 **서버 측에서는** GlobalCallDock용으로 의도된 `call_started` 브로드캐스트가 **INVITE 직후 1회 + AI 전환 후 1회** 나가도록 되어 있고, 해당 통화에 대해 **`ai_call_started_event_emitted`까지 기록**되어 있다. “백엔드가 caller를 모른다” 수준의 문제는 아니다.

### 1.2 `call_data_record`만 보면 CID(발신)가 안 보이는 이유

`call_data_record_20260420.log` L12의 `call_event` / `call_connected`에는 **`callee`: "1003"만 있고 `caller`/`caller_id` 필드가 없다.**  
이 파일은 **실시간 STT·TTS·RAG·LLM** 위주로 쌓이며, **인입 CID를 한 줄에 반드시 넣는 스키마가 아니다.** Dock용 정보는 원래 **Socket.IO `call_started` 페이로드**와 별도다.

→ **CDR만으로 “프론트 CID 미표시”를 역추적하기엔 필드가 부족**하다. 원인 분리는 브라우저 쪽 `call_started_ws` / `caller_context_*` 로그(구현되어 있다면)와 `app.log`의 위 이벤트를 같이 보면 된다.

### 1.3 프론트에서 여전히 안 보일 때 우선 의심할 것 (코드베이스 상태 포함)

1. **브라우저가 Socket.IO에 연결되어 있었는지**  
   같은 시각에 대시보드 탭이 열려 있지 않거나 WS URL/포트 불일치면 이벤트를 못 받는다.

2. **`ActiveCallDockProvider`가 실제 `layout`에 마운트되는지**  
   현재 워크스페이스 검색상 `ActiveCallDockProvider`는 컴포넌트 파일만 존재하고 **앱 트리에서 import/사용처가 검색되지 않는다.**  
   Provider·Dock UI가 루트에 없으면 **`call_started`를 받아도 화면에 CID가 없다**가 정상이다.

3. **테넌트 owner (`getTenantOwner`)**  
   Dock은 `caller-context` API를 부를 때 `owner`가 필요하다. `localStorage`의 `tenant.owner`가 비어 있으면 **이전 통화 요약(CID 보조)** 쪽 fetch가 스킵될 수 있다. (발신 번호 자체 표시는 `caller` SIP URI로도 가능하지만, 제품 UX상 “CID”를 연락처 맥락으로 기대했다면 여기서 빈 느낌이 난다.)

**요약**: 이 통화에 한해 **백엔드가 `call_started`를 안 쏜 것은 로그상 아니다.** 미표시는 **프론트 미연결·미마운트·tenant 설정** 쪽을 먼저 보라.

---

## 2. “예약이 실제로 되지 않았다” — 무엇이 문제인지

### 2.1 제품 기능 관점: 음성 봇 경로는 **예약 DB 커밋이 없음**

- 대화 로그상 에이전트는 **RAG(지식)** + **LLM 응답**으로만 “예약 방법 안내” 또는 “가능하다”는 **자연어**를 생성한다.
- 코드 검색상 **`ai_voicebot` 쪽에서 `bookings` INSERT/예약 API 호출 흐름이 없다.**  
  예약 테이블·API(`call_history`의 `has_booking` 등)는 있으나, **이번 음성 대화와 연동되는 자동 예약 확정 노드가 아니다.**

→ 사용자가 기대한 **“통화 중 실제 예약 확정”**은 현재 아키텍처에 **없거나 별도 구현이 필요**하다. LLM이 “가능합니다”라고 말한 것은 **캘린더/좌석을 잠근 것이 아니다.**

### 2.2 이번 세션에서의 구체적 리스크 (로그 내용)

1. **첫 발화가 `chitchat`으로 분류**되어(약 4.7초 분류) 업무 의도와 어긋난 안내가 나갔다.  
   이후 “예약하려고 하는데요”에서야 `question`으로 정상화.

2. **RAG 유사도가 낮고(`confidence` 0.205 등) soft_fallback**에 의존한 구간이 있다.  
   지식은 “전화로 예약 규칙” 안내 수준이지 **슬롯 점유**가 아니다.

3. **“오늘 7시 예약” 질의**에서 상위 히트로 **다른 날짜의 HITL 스타일 짧은 답변**(“2026년 4월 11일 예약 되는지… 되죠. 오세요.”)이 섞였고, LLM은 **“2026년 4월 20일 7시 예약 가능합니다”**라고 **구두 확정**에 가깝게 응답했다.  
   동시에 다른 히트(“오늘 손님이 한 분도 없어서…”)와 **내용상 충돌**할 수 있는 문맥이다.

4. **의미상 “예약 완료”**가 되려면 최소한 **인원·연락처·테이블 가용·중복 예약 방지** 같은 **구조화 슬롯 + DB/HITL**이 필요하다. 현재 로그에는 그 단계가 없다.

---

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `sip-pbx/docs/reports/2026-04/2026-04-20_1600_CID_DOCK_AND_VOICE_RESERVATION_GAP.md` | 추가 | CID·예약 갭 분석 리포트 | 설계대로 동작한 부분 vs 기대 이탈 구분 |

---

## 주요 결정 사항

- **CID 이슈**: “서버 미발행”이 아니라 **클라이언트 수신·UI 마운트·tenant**를 우선 검증하는 것이 맞다.
- **예약 이슈**: **정보 응답(RAG+LLM)**과 **거래(예약 확정)**를 분리해 설계하지 않으면, 사용자는 음성만으로 예약이 된 것으로 오해하기 쉽다.

---

## 잔여 과제 (권장)

1. ~~루트 레이아웃에 **`ActiveCallDockProvider` + 실제 Dock UI** 연결~~ → **구현됨** (`app/layout.tsx`, `AppShell`에서 중복 제거). 상세: `2026-04-20_1715_CALL_DOCK_ROOT_LAYOUT_CLIENT_LOG.md`.
2. ~~`call_started` 수신 시 **client-log**~~ → **`source=call-dock`** 으로 `call_started_received` / `call_started_dock_store_applied` 등 서버 `app.log` 기록. 동일 리포트 참고.
3. 예약 의도(`question` + 시간/인원 엔티티)에 대해 **HITL 또는 `bookings` API**를 타는 그래프 노드·툴콜 추가 검토.
4. 날짜 특정 질의에서 **날짜 불일치 HITL 문서**가 상위로 올라오면 LLM에 **“확정 불가, 확인 필요”** 정책을 강제하는 RAG 후처리.
