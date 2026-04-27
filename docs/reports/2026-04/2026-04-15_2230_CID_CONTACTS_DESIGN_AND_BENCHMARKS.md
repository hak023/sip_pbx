## 메타

- **작성일(로컬)**: 2026-04-15
- **상태**: 기획·설계안 (구현 전)
- **관련 코드**: `src/api/routers/call_history.py`, `recordings/**/metadata.json`·`call_insights.json`, `rag_processor.py` (`_get_caller_context_sync` / 요약 파이프라인), 실제 대시보드는 `sip-pbx/frontend` 기준으로 확장 권장

## 개요

인입 통화 시 대시보드 CID(발신 식별·맥락)를 강화하고, 테넌트 단위 **연락처(고객 카드)** 를 두어 이름·메모·통화 이력을 관리한다. 통화 종료 후 기존 요약 로직 훅에서 **연락처가 없을 때만** LLM으로 표시용 이름·특징(전화 끝 4자리 포함)을 추정해 자동 저장한다. 아래는 요구사항 정합 설계와, CTI·CRM·오픈소스 사례에서 뽑은 **추가 제안**이다.

---

## 1. 요구사항 대응 (기능 매핑)

### 1.1 대시보드 CID 강화 (인입 직후)

| 요구 | 설계 |
|------|------|
| 최근 통화 1건 일시 | `caller` 정규화 번호 + `owner`(착신/테넌트) 기준으로 **직전 종료 통화 1건** 조회. 소스는 기존과 동일하게 `call_history` 목록 API가 쓰는 **녹음 루트 스캔 + 메타 병합** 또는 향후 SQLite 인덱스(선택). 표시는 테넌트 로컬 타임존 권장. |
| 해당 통화 요약 | `call_insights.json` 등에 이미 쌓이는 요약 필드(또는 `metadata.json`의 AI 관련 필드)를 **call_id 단위**로 1건 조회해 카드 상단에 짧게(예: 2~4줄 + “더보기”). |
| 고객 이름 | (1) `contacts`에 매칭 행 있으면 **표시명** (2) 없으면 UI 라벨 **「첫 통화」** (3) 자동 생성 연락처는 아래 1.3 규칙. |

**인입 이벤트 연동**: SIP/WebSocket에서 `caller_id` + `callee`(owner)가 확정되는 시점에 `GET /api/.../caller-context?owner=&from=` 같은 경량 API 또는 WS 페이로드 `caller_context`를 푸시해 **첫 3초 안**에 카드 갱신(스크린 팝 UX)을 목표로 한다.

### 1.2 연락처 관리

| 항목 | 설계 |
|------|------|
| 필드 | `display_name`, `phones[]`(정규화 키), `memo`, `tenant_id`/`owner`, `created_at`, `updated_at`, `source`(`manual` \| `auto_llm` \| `import`), `auto_confidence`(선택), `blocked`(선택). |
| 통화 이력 | 카드 안에서는 **요약 + 일시 리스트**(최근 N건, 페이지네이션). 상세는 기존 통화 상세(녹음·트랜스크립트)로 링크. |
| 프론트 | `sip-pbx/frontend`에 `/contacts` (또는 설정 하위) — **생성·수정·삭제** + 검색(번호/이름). |

**식별 키**: 테넌트당 `E.164` 또는 “국가코드+국번 가정” 하의 **단일 canonical_phone** 로 인덱스. 표시는 사용자 친화 포맷.

### 1.3 통화 종료 후 LLM 자동 연락처 (조건부)

- **조건**: 해당 `canonical_phone` + `owner`에 **연락처 행이 없을 때만** 실행.
- **입력**: 통화 요약 + (가능하면) 짧은 발화 하이라이트 + **끝자리 4자리** `****1234` 형태로 프롬프트에 고정 포함(PII 최소화·충돌 완화).
- **출력**: JSON 스키마 고정 예: `{ "suggested_display_name": "...", "short_descriptor": "...", "confidence": 0.0-1.0 }` — `short_descriptor`는 내부용/메모 초안.
- **저장 정책**: `confidence >= 임계값` 이고 이름이 비어 있지 않을 때만 insert; 실패 시 무시 + 로그.
- **인간 우선**: 수동 연락처가 생기면 자동 레코드는 덮어쓰지 않음(또는 `source=auto_llm`만 갱신 가능하게 분리).

기존 `rag_processor`의 요약·인사이트 저장 지점(통화 종료 파이프라인)에 **비동기 태스크**로 붙이면 통화 지연을 피하기 좋다.

---

## 2. 데이터 모델 (초안)

```text
contacts
  id, owner (tenant), canonical_phone, display_name, memo,
  source, llm_confidence, created_at, updated_at

contact_call_links  (선택 — 정규화)
  contact_id, call_id, summary_snippet, call_started_at
```

간단 구현은 `contacts`만 두고 통화는 기존 `call_history` API로 `caller` 필터 조회해 합성해도 된다.

---

## 3. API·권한

- `GET/POST/PATCH/DELETE /api/contacts` — JWT + `owner` 스코프.
- `GET /api/contacts/lookup?phone=` — 대시보드 CID용 (요약 1건 + 연락처 요약).
- 자동 생성은 **서버 내부**에서만 호출(클라이언트 노출 X).

---

## 4. 코드베이스와의 정합 메모

- 통화 목록·요약: `call_history` 라우터가 `metadata.json` / `call_insights.json`을 병합하는 방향이 이미 문서화되어 있음 — CID도 동일 소스를 재사용하면 **단일 진실**이 유지된다.
- 발신자 메모리: `_get_caller_context_sync` → `get_recent_summaries_by_caller` — 연락처 테이블 도입 후 **“연락처 표시명 + 최근 요약 1줄”** 을 여기에 주입하는 확장을 검토할 수 있다(프롬프트 토큰 관리 필요).

---

## 5. 업계·자료 기반 추가 제안 (리서치)

### 5.1 CTI 스크린 팝 UX (비 기술 문서 위주)

- **첫 3초 원칙**: [ActiveCalls — CTI Screen Pop Design Guide 2026](https://activecalls.com/cti-screen-pop-design-guide-2026-what-to-show-in-the-first-3-seconds-of-a-call/) 에서처럼, 상단에 **이름(또는 “첫 통화”) + 번호 + 최근 한 줄 요약 + 리스크/미해결 배지** 정도로 제한하고 나머지는 접는다.
- **미식별 번호 UX**: [Mitel — Screen Pop in Contact Centers](https://www.mitel.com/article/understanding-screen-pop-contact-centers), [VoiceSpin — What is Screen Pop](https://www.voicespin.com/glossary/what-is-contact-center-screen-pop/) 에 공통적으로 나오듯, CRM 조회 실패 시에도 **빈 화면 대신** “신규 / 메모 없음 / 빠른 메모 입력” 흐름을 제공한다.
- **ANI vs DNIS**: [Nextiva — DNIS](https://www.nextiva.com/blog/what-is-dnis.html), [PureCallerID — DNIS and ANI](https://purecallerid.com/2023/05/dnis-and-ani-understanding-these-vital-cogs-in-the-telephony-system/) — 인입 카드에 **발신(ANI)** 와 **착신 라인(DNIS)** 을 같이 두면 멀티 번호 테넌트에서 라우팅·의도 맥락이 좋아진다.

### 5.2 전화번호·중복 (GitHub·제품 사례)

- **E.164 정규화 + 중복 탐지**: [dzhng/crm.cli](https://github.com/dzhng/crm.cli) 는 입력 시 전화를 E.164로 통일하고, 동일 번호 중복 추가를 막는 방식을 명시한다 — SIP URI에서 나온 각기 다른 문자열(`010`, `+82` 등) 문제에 그대로 응용 가능.
- **연락처 병합 이슈**: [monicahq/monica#1687](https://github.com/monicahq/monica/issues/1687) 등에서 보듯, 시간이 지나면 **중복 카드**가 쌓이므로 “나중에 병합” UX를 초기부터 설계 여지를 두는 것이 좋다.
- **유니크 필드 병합 규칙**: [mautic/mautic#9452](https://github.com/mautic/mautic/pull/9452) — 여러 고유키(이메일·전화 등)를 쓸 경우 **OR/AND 병합 정책**을 문서화해 오인 병합을 막는다.

### 5.3 제품·운영 (추천 기능 목록)

| 제안 | 이유 |
|------|------|
| **자동 연락처에 “미검증” 배지** | LLM 표시명 오류 시 상담원 신뢰 하락 방지 (업계 스크린 팝에서 identity verification 강조). |
| **빠른 메모 + 다음 통화 플래그** | 첫 통화 중 상담원이 10초 안에 태그를 남기면 다음 인입 CID가 즉시 개선된다. |
| **DNC/수신거부 플래그** | 콜센터 규제·이탈 고객 처리에 유리. |
| **통화 요약 버전 필드** | 요약 재생성 시 “어느 버전이 카드에 노출되는지” 추적. |
| **감사 로그** | 자동 생성·수정·삭제를 `who/when`으로 남김. |
| **PII 최소화 프롬프트** | 전체 번호 대신 끝 4자리 + 요약만 LLM에 넣기(요구사항과 정합). |

---

## 6. 잔여 과제 (구현 단계에서)

1. `sip-pbx/frontend`에 대시보드·연락처 라우트 실제 배치(루트 `frontend/`는 미사용 주석 존재).
2. SQLite 마이그레이션 스크립트 및 `get_recent_summaries_by_caller` 정의 위치 정리(현재 import 경로와 실제 모듈 일치 여부 점검).
3. 통화 종료 훅 단일 진입점 문서화(요약 저장 직후 `schedule_contact_autofill` 패턴).

---

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `sip-pbx/docs/reports/2026-04/2026-04-15_2230_CID_CONTACTS_DESIGN_AND_BENCHMARKS.md` | 추가 | CID·연락처 기획 및 외부 자료 제안 | 기획 전용 |
