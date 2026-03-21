# 발신자별 통화 기억(Caller Memory) — 타당성 검토·리서치·설계

## 개요

LLM에 질의할 때 **발신자(caller)별로 이전 통화 내용을 기억**해, 재통화 시 맥락을 이어가도록 하는 로직에 대한 타당성 검토, 업계 사례 리서치, 유저스토리, 설계 방향, ChromaDB 성능 고려를 정리한 문서다.

---

## 1. 타당성 검토

### 1.1 왜 유용한가

- **현재**: `RAGLLMProcessor`는 `_messages`로 **당일 통화 내** 최근 N턴만 유지(`_format_history()`). 통화가 끝나면 세션이 사라져 다음 통화에서 “이전에 문의하신 내용”을 LLM이 알 수 없다.
- **발신자별 기억**: 동일 발신번호(caller_id)가 같은 착신(테넌트)에 다시 걸면, **과거 통화 요약·결과·선호**를 프롬프트에 넣어 주면:
  - “지난번에 예약 변경 요청하셨는데, 이번엔 취소인가요?” 같은 **연속성** 제공
  - 반복 설명 감소, 체감 품질·만족도 향상

### 1.2 타당성 결론

- **타당함.** 고객 지원·콜센터·예약/문의 봇에서 “반복 발신자 맥락 유지”는 보편적 요구사항이며, 업계에서도 **세션 간 메모리(Cross-session memory)** 로 정립된 패턴이다.

---

## 2. 리서치 요약 (GitHub·문서·사례)

### 2.1 Voice AI 메모리 아키텍처 (Mem0 등)

- **두 시점**: (1) **LLM 호출 전** — 관련 메모리 검색 후 프롬프트에 주입, (2) **응답 전달 후** — 새 정보 추출해 **비동기 저장** (음성 지연에 영향 없게).
- **저장 시점**: 턴마다 저장(per-round) vs 세션 종료 시 일괄(per-session). 턴마다 저장이 중간 끊김에 강하고, 추출 품질도 좋은 편.
- **검색 전략**:  
  - **Pre-loaded**: 세션 시작 시 한 번만 로드 → 턴당 지연 없음.  
  - **Semantic search**: 매 턴 유사 검색 → 50–200ms 추가, 관련도 높음.  
  - **Hybrid**: 기본은 pre-load, 주제 전환 시에만 검색.
- **처리 위치**: 인라인(간단, 지연 영향) / 병렬 메모리 에이전트(지연 분리, 복잡) / 세션 종료 후 배치(구현 단순, 당일 통화 중에는 기억 없음).

참고: [Mem0 – Memory for Voice Agents](https://mem0.ai/blog/ai-memory-for-voice-agents), [Voiceflow Memory](https://docs.voiceflow.com/docs/memory), [Context Retention in Voice AI (dev.to)](https://dev.to/callstacktech/how-to-implement-context-retention-in-voice-ai-applications-4kgk).

### 2.2 GitHub·오픈소스 사례

- **microsoft/call-center-ai**: 대화 저장·재연결 후 이어하기, **과거 대화·상호작용 이력**을 LLM 맥락에 활용.
- **Hannah Voice Assistant**: 메모리 기능 + **통화 이력 로깅**으로 이력 기반 맥락 유지.
- **Twilio Call-GPT, Deepgram Voice Agent 등**: 스트리밍·함수 호출 위주이나, “이전 대화 맥락”은 보통 **서버 측 상태 또는 DB에 저장 후 프롬프트에 주입**하는 방식으로 확장한다.

### 2.3 벡터 DB vs 관계형 DB

- **관계형 DB**: `(caller_id, tenant_id, timestamp)` 등 **정확한 키/필터/트랜잭션**에 적합. “이 발신자의 최근 N건 통화 요약” 같은 조회에 적합.
- **벡터 DB(Chroma 등)**: **의미 유사도 검색**(“지난번 예약 변경 이야기와 비슷한 맥락”)에 적합. RAG·메모리 검색에 많이 씀.
- **실무**: **하이브리드**가 많음 — 메타데이터·요약·타임스탬프는 SQL, 임베딩+유사도 검색은 벡터 DB. 대화 원문은 SQL/오브젝트 스토어에 두고, 벡터 DB에는 요약/핵심 문장만 인덱싱하는 패턴이 일반적.

---

## 3. 유저스토리 (언제 이 로직이 유용한지)


| ID       | 사용자         | 가치                                    | 인수(Acceptance)                                                                |
| -------- | ----------- | ------------------------------------- | ----------------------------------------------------------------------------- |
| **US-1** | 반복 문의 고객    | 이전 통화를 알고 있어 “또 전화했을 때” 맥락이 이어진다.     | 같은 발신자가 같은 번호에 재통화 시, 이전 통화 요약/결과가 LLM 프롬프트에 포함되어, “지난번에 ~하셨는데” 수준의 언급이 가능하다. |
| **US-2** | 예약/변경/취소 고객 | 예약·변경·취소가 여러 통화에 걸쳐 있어도 흐름을 이해한다.     | “지난 통화에서 예약 변경 요청하셨고, 오늘은 취소 요청”처럼 **통화 간 상태**를 반영한 응답이 나온다.                  |
| **US-3** | 민원/불만 고객    | 같은 이슈를 여러 번 말해도 “이미 말씀하신 내용”을 인정해 준다. | 이전 통화에서의 불만/요청 요약이 있어, “앞서 말씀하신 ~ 사항을 기억하고 있습니다” 수준의 응답이 가능하다.                |
| **US-4** | 상담원(운영자)    | HITL·후처리 시 “이 발신자 과거 이력”을 참고할 수 있다.   | 통화 이력 API/대시에서 **발신자 기준 과거 통화·요약**을 볼 수 있거나, HITL 컨텍스트에 포함된다.                 |
| **US-5** | 테넌트(사업자)    | 발신자별 통화 패턴·선호를 분석·활용하고 싶다.            | (선택) 발신자별 메모리/요약이 분석·리포트에 쓰이거나, 프라이버시 정책 하에 보관 기간이 관리된다.                      |


---

## 4. 설계 방향

### 4.1 “무엇을” 기억할지

- **저장 후보**
  - 통화별 **요약**(1–3문장): “예약 변경 요청, 3/15로 변경 완료.”
  - **핵심 사실**: 문의 유형, 처리 결과, “다음에 연락 드릴까요?” 응답 등.
  - (선택) **구조화 스키마**: `intent`, `resolution`, `follow_up` 등 도메인 필드.
- **저장하지 않을 것**
  - 인사· filler·일반적 멘트는 제외하거나 최소화해 노이즈 축적을 막는다.

### 4.2 키 구조

- **발신자별**이므로 `**(tenant_id, caller_id)`** 로 묶는다.
  - `tenant_id`: 착신(owner/extension), `caller_id`: SIP From 등에서 추출한 발신자 식별자.
- 통화 단위는 `call_id`; “이 발신자의 과거 통화들”은 `(tenant_id, caller_id)` + `call_id`/timestamp로 조회.

### 4.3 ChromaDB에 통화 이력을 저장해야 할까?

- **권장: 하이브리드**
  - **관계형 DB(또는 기존 call_history 확장)**  
    - 통화 메타: `call_id`, `caller_id`, `callee_id`(tenant), `start_time`, `end_time`, **요약 텍스트**, (선택) `intent`/`resolution` 등.  
    - “이 발신자의 최근 N건” 같은 **정확한 시간순/키 조회**는 여기서 수행.
  - **ChromaDB(또는 기존 벡터 스토어)**  
    - **의미 검색**이 필요할 때만 사용: 예) “이 발신자 과거 통화 중 ‘예약 변경’과 유사한 맥락” 검색.  
    - 저장 단위: 통화 **요약 문장** 또는 핵심 발화 청크 + 메타데이터(`tenant_id`, `caller_id`, `call_id`, `timestamp`).  
    - 전체 트랜스크립트를 통째로 벡터에 넣기보다는 **요약/핵심만** 넣어 용량·비용·검색 품질을 관리한다.

즉, **“전화 이력 저장” 자체는 RDB(또는 기존 이력 저장소)**, **“그중 어떤 내용을 LLM에 넣을지 검색”**할 때 ChromaDB를 쓸지 결정하면 된다.  
단순히 “최근 N통화 요약만 시간순으로 넣기”라면 **RDB만으로도 가능**하고, “지금 발언과 의미적으로 비슷한 과거 통화 찾기”가 필요하면 ChromaDB(또는 벡터 검색)를 추가하는 구성이 적절하다.

### 4.4 파이프라인 연동

- **통화 시작 시**
  - `caller_id`가 있으면 `(tenant_id, caller_id)` 기준으로:
    - **Pre-loaded**: 최근 K건 통화 요약을 RDB(또는 메모리 저장소)에서 조회해 시스템 프롬프트 또는 `[이전 통화 맥락]` 블록으로 주입.
    - (선택) ChromaDB가 있으면, 현재 발화와 유사한 과거 맥락만 추가 검색해 주입.
- **통화 중**
  - 기존처럼 **당일 세션** `_messages` 기반 `[대화 기록]` 유지.
- **통화 종료 시**
  - **비동기**로:
    - 트랜스크립트(또는 이미 쌓인 메시지)에서 **요약/핵심 추출**(LLM 또는 규칙).
    - RDB에 `call_id`, `caller_id`, `tenant_id`, 요약, timestamp 저장.
    - (선택) ChromaDB에 요약/청크 임베딩 + 메타데이터 저장.

발신자 식별은 **SIP From / CDR**에서 채우고, 파이프라인 초기화 시 `caller_id`를 넘겨 주어야 한다. 현재 `call_history`에 `caller_id`가 optional로 있으므로, AI 파이프라인까지 전달되도록 한 경로를 확장하면 된다.

---

## 5. ChromaDB 성능·규모 고려

### 5.1 ChromaDB에 “많은” 내용이 들어갈 때

- **용량**
  - 벡터 수가 많을수록 **메모리** 사용 증가.  
  - 대략: `RAM(GiB) ≈ (벡터 수 × 차원 × 4 bytes) / 1024³`  
  - 예: 1536차원, 100만 벡터 → 약 5.7GiB (벡터만), 인덱스·오버헤드로 2~4배 더 쓸 수 있음.
- **Chroma Cloud 제한(참고)**
  - 컬렉션당 최대 500만 레코드, 쓰기당 300건, 조회 결과 300건 등. 셀프 호스팅은 상한이 다름.
- **디스크**
  - 벡터+메타+인덱스로 **벡터 payload의 2~4배** 정도. WAL이 무한히 커질 수 있으므로 **WAL pruning(vacuum)** 주기적으로 필요.

### 5.2 예상 규모 (참고)

- **발신자당 통화 요약만** 저장한다고 가정:
  - 통화 1건 ≈ 요약 1~~3개 청크 → 벡터 1~~3개.
  - 발신자 10만 명 × 과거 20통화 × 2 청크 ≈ 400만 벡터 → 위 공식대로면 수 GB~수십 GB 메모리·디스크.
- **소규모~중규모**(수천~수만 발신자, 통화당 요약만): 단일 ChromaDB 노드로 충분한 경우가 많고, **pre-loaded로 최근 N건만 RDB에서 가져오면** ChromaDB 부하는 더 줄일 수 있다.
- **대규모**: 샤딩·전용 벡터 서비스 검토, 또는 “의미 검색”을 일부 구간(예: 최근 1달)으로 제한하는 정책이 필요하다.

### 5.3 지연

- **의미 검색 1회**: 벡터 스토어·인프라에 따라 **50–200ms** 정도 예상.
- 음성 에이전트는 **1초 이내** 응답이 관례이므로:
  - **Pre-loaded**(세션 시작 시 한 번만) → 턴당 추가 지연 없음.
  - **매 턴 semantic search** → 50–200ms가 그대로 추가되므로, 필요 시에만(예: 주제 전환 감지) 쓰는 hybrid가 안전하다.

### 5.4 정리

- ChromaDB에 **전체 트랜스크립트를 무제한** 넣기보다는 **요약/핵심 청크만** 넣고, **시간·발신자 필터**를 메타데이터로 두는 것이 성능과 비용에 유리하다.
- “발신자별 이전 통화 기억”의 **1차 구현**은 **RDB(또는 기존 이력)에 요약 저장 + 세션 시작 시 pre-loaded로 최근 N건만 프롬프트에 주입**으로 시작하고, **의미 검색이 필요해질 때** ChromaDB(또는 기존 벡터 DB)에 요약/청크만 인덱싱하는 단계를 추가하는 것을 권장한다.

---

## 6. SQLite 스키마 및 연동 (구현 사양)

### 6.1 테이블 정의

**call_history** (기존 in-memory 이력과 1:1 대응)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | INTEGER PK | 자동 증가 |
| call_id | TEXT UNIQUE NOT NULL | 통화 ID |
| caller_id | TEXT | 발신자 식별 (SIP From 등) |
| callee_id | TEXT | 착신(테넌트 owner) |
| start_time | TEXT | ISO 8601 |
| end_time | TEXT | NULL 가능 |
| hitl_status | TEXT | pending / resolved / unresolved |
| user_question | TEXT | HITL 시 사용자 질문 |
| ai_confidence | REAL | HITL 시 AI 신뢰도 |
| is_ai_handled | INTEGER | 0/1 |
| resolved | INTEGER | 0/1 |
| operator_note | TEXT | 운영자 메모 |
| follow_up_required | INTEGER | 0/1 |
| follow_up_phone | TEXT | 후속 연락처 |
| transcripts | TEXT | JSON 배열 문자열 |
| created_at | TEXT | 레코드 생성 시각 |

**call_summaries** (발신자별 통화 요약 — LLM 맥락용)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | INTEGER PK | 자동 증가 |
| tenant_id | TEXT NOT NULL | callee_id(착신) |
| caller_id | TEXT NOT NULL | 발신자 |
| call_id | TEXT NOT NULL | 통화 ID |
| summary_text | TEXT NOT NULL | 1~3문장 요약 |
| created_at | TEXT | 생성 시각 |

인덱스: `(tenant_id, caller_id)`, `(created_at DESC)` (발신자별 최근 K건 조회용).

### 6.2 연동 지점

- **append_call_history(entry)** → DB INSERT (call_id 없으면 INSERT, 있으면 무시 또는 UPDATE는 record_hitl에서).
- **record_hitl_request(...)** → call_id로 행 있으면 UPDATE, 없으면 INSERT (기존과 동일 의미).
- **mark_hitl_resolved(call_id)** → UPDATE hitl_status='resolved', resolved=1.
- **mark_pending_hitl_unresolved(call_id)** → UPDATE hitl_status='unresolved' (조건: pending이고 resolved=0).
- **list_call_history / get_call_detail / save_note / resolve_call** → DB SELECT/UPDATE.
- **통화 종료 시**: `emit_call_ended` 내부에서 `end_call_and_save_summary(call_id)` 호출 → end_time 갱신 + call_summaries INSERT (요약은 user_question 또는 "통화 완료").
- **RAGLLMProcessor**: 생성 시 `caller_id` 전달 시 `(owner, caller_id)`로 `get_recent_summaries(tenant_id, caller_id, K)` 조회 후 시스템 프롬프트에 `[이전 통화 맥락]` 블록 추가.
- **AI 통화 시작 시**: 이력 행이 없으면 통화 종료 시 요약이 저장되지 않음. **AI 통화를 시작하는 쪽**(예: `run_ai_voice_pipeline` 호출 직후)에서 `append_call_history({"call_id": ..., "caller_id": ..., "callee_id": ..., "start_time": ..., "is_ai_handled": True})` 호출을 권장하면, HITL이 없던 통화도 요약이 남음.

### 6.3 환경 변수

- `SQLITE_DB_PATH`: DB 파일 경로 (기본: `data/calls.db`). 디렉터리는 없으면 생성.

---

## 6.4 다음 단계 제안

1. **caller_id 전달 경로 확정**: SIP → CDR/오케스트레이터 → `run_ai_voice_pipeline` / `RAGLLMProcessor`까지 `caller_id` 전달.
2. **저장소 선택**:
  - 1단계: 기존 `call_history`(또는 RDB)에 `call_summary`, `caller_id` 필드 추가하고, 통화 종료 시 요약 비동기 저장.  
  - 2단계: 세션 시작 시 `(tenant_id, caller_id)`로 최근 K건 요약 조회해 시스템 프롬프트에 `[이전 통화 맥락]` 추가.  
  - 3단계(선택): “의미 기반 검색”이 필요하면 ChromaDB에 요약/청크만 저장·조회하는 레이어 추가.
3. **요약 추출**: 통화 종료 후 배치/비동기로 트랜스크립트 → LLM 또는 템플릿 기반 1~3문장 요약 생성.
4. **프라이버시·보관 기간**: 발신자별 메모리 보관 기간, 삭제 정책, 개인정보 처리 방침 반영.

---

## 7. 관계형 DB 도입 방향 (현재 RDB 미사용 시)

현재 프로젝트는 **관계형 DB를 쓰지 않고** `call_history`, `tenants` 모두 in-memory(`_store`)만 사용 중이며, 서버 재시작 시 데이터가 사라진다. 발신자별 통화 기억을 위해 **어떤 RDB를 쓸지**와 **사용 시 유의점**을 정리한다.

### 7.1 어떤 관계형 DB를 쓸지

| 옵션 | 장점 | 단점 | 적합한 경우 |
|------|------|------|-------------|
| **SQLite** | 서버 불필요, 설정 없음, 단일 파일로 백업/이동 쉬움. Python 내장 지원. | 동시 쓰기 시 한 번에 한 프로세스만(Writer). 다중 노드 분산에는 부적합. | 단일 노드·소규모·개발/스테이징, 또는 첫 도입 단계. |
| **PostgreSQL** | 동시 쓰기·다중 연결·스케일에 유리. 운영 표준에 가까움. | DB 서버 설치·실행·백업 정책 필요. | 다중 워커·다중 노드·운영 규모가 커질 때. |

**권장**: **우선 SQLite로 시작**하고, 나중에 워커/노드가 늘거나 동시 쓰기 이슈가 나면 **PostgreSQL로 전환**하는 흐름이 부담이 적다.

- **SQLite**  
  - DB 파일 하나(예: `data/calls.db`)만 두면 되고, 별도 데몬이 필요 없다.  
  - 통화 이력·발신자별 요약·테넌트 설정 같은 **읽기 비중이 크고 쓰기는 통화 종료/이벤트 시점**이면, 단일 프로세스 API 서버에서 SQLite로 충분한 경우가 많다.  
  - 파일 위치는 환경 변수(예: `SQLITE_DB_PATH`)로 두고, 백업은 해당 파일 복사 또는 `sqlite3 .backup`으로 처리 가능.
- **PostgreSQL**  
  - uvicorn 워커 여러 개, 또는 API와 AI 파이프라인이 다른 프로세스에서 동시에 같은 DB를 쓸 때, 또는 나중에 대시보드·리포트 전용 읽기 전용 복제를 둘 때 유리하다.  
  - 전환 시 **테이블·스키마를 그대로 옮기고 연결 문자열만 바꾸면** 되도록, 처음부터 SQLAlchemy 등으로 추상화해 두면 좋다.

### 7.2 사용 시 문제 없도록 할 점

- **연결/라이브러리**  
  - **SQLite**: Python 표준 라이브러리 `sqlite3`만으로 가능. 비동기 사용 시 `aiosqlite` 추가.  
  - **PostgreSQL**: `asyncpg` 또는 `psycopg2` + SQLAlchemy 등.  
  - 공통: **연결 풀** 사용(특히 Postgres), 타임아웃·재시도 정책 두기.
- **마이그레이션**  
  - 스키마 변경을 코드와 맞추기 위해 **마이그레이션 도구**를 쓰는 것을 권장한다.  
  - 예: **Alembic**(SQLAlchemy와 함께 많이 사용), 또는 단순 스키마라면 `CREATE TABLE IF NOT EXISTS` + 버전 테이블로 수동 관리.  
  - 첫 도입 시 `call_history`용 테이블, `caller_memory`(발신자별 요약)용 테이블을 정의하고, 기존 in-memory `_store`와 **동일한 필드/의미**를 유지하면 이후 라우터만 저장소를 DB로 바꾸면 된다.
- **기존 in-memory와의 공존**  
  - 1단계: **새 기능(발신자별 기억)** 만 SQLite에 저장하고, 기존 `call_history`·`tenants`는 당분간 in-memory 유지 가능.  
  - 2단계: call_history API를 DB로 이전(append → INSERT, 목록/상세 → SELECT). tenants도 동일하게 테이블 추가 후 라우터만 교체.  
  - 이렇게 하면 “한 번에 다 바꾸기” 없이 단계적으로 RDB로 옮길 수 있다.
- **백업·디스크**  
  - SQLite: DB 파일이 있는 디렉터리 권한·디스크 공간 모니터링. 정기 백업(파일 복사 또는 `.backup`) 권장.  
  - Postgres: pg_dump / PITR 등 운영 정책에 맞게 설정.
- **성능**  
  - 발신자별 “최근 K건 요약” 조회는 `(tenant_id, caller_id)` + `ORDER BY created_at DESC LIMIT K` 수준이면, 인덱스만 있으면 부담 거의 없음.  
  - SQLite도 이런 읽기 위주 워크로드에서는 수십만 행까지 무리 없이 동작하는 경우가 많다.

### 7.3 정리

- **어떤 RDB**: **먼저 SQLite**, 필요해지면 **PostgreSQL**로 전환.  
- **사용에 문제 없게**: 연결(풀)·타임아웃, 스키마 마이그레이션(Alembic 등), 기존 in-memory와 단계적 이전, 백업 정책만 두면 된다.  
- 현재처럼 RDB를 쓰지 않는 상태에서 SQLite 한 개 파일로 시작해도, 이 프로젝트 규모와 통화 이력/발신자 기억 용도에서는 **사용에 무리가 없는 선택**이다.

---

## 참고 자료

- [Mem0 – Memory for Voice Agents: A Guide to AI Memory Architecture](https://mem0.ai/blog/ai-memory-for-voice-agents)
- [Voiceflow – Automatically Managed Memory](https://docs.voiceflow.com/docs/memory)
- [How to Implement Context Retention in Voice AI Applications (dev.to)](https://dev.to/callstacktech/how-to-implement-context-retention-in-voice-ai-applications-4kgk)
- [Chroma – Resource Requirements / Quotas](https://docs.trychroma.com/cloud/quotas-limits), [Chroma Cookbook – Resources](https://cookbook.chromadb.dev/core/resources)
- [Microsoft Call Center AI (GitHub)](https://github.com/microsoft/call-center-ai) — 대화 저장·이력·맥락 활용
- [Vector DB vs SQL decision framework (Medium)](https://medium.com/@bhagyarana80/vector-db-or-just-use-sql-a-decision-framework-735503e8cc3e)

