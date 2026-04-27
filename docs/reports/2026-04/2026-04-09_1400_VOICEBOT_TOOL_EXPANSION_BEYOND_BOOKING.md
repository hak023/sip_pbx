# AI 보이스봇 Tool 확장 기획 리서치 — 예약 외 신규 기능

| 항목 | 내용 |
|---|---|
| 작성일 | 2026-04-09 |
| 상태 | 리서치 완료 |
| 리서치 범위 | GitHub, Bolna/Vapi/Retell/SIPTEL/SIP2AI/Siperb, microsoft/call-center-ai, SalesGPT, LangGraph 오픈소스 |
| 관련 파일 | `src/ai_voicebot/langgraph/tools/booking_tools.py`, `src/ai_voicebot/langgraph/nodes/booking_agent.py` |

---

## 1. 현재 구현된 Tool 현황 (기준선)

| Tool | 기능 |
|---|---|
| `check_available_slots` | 날짜·인원으로 가용 슬롯 조회 |
| `get_booking_info` | 예약 ID로 상세 조회 |
| `create_booking_tool` | 예약 생성 |
| `cancel_booking_tool` | 예약 취소 |
| `get_booking_settings` | 도메인 설정 조회 |
| `update_booking_tool` | 예약 수정 (날짜·시간·인원) |
| `search_my_bookings` | 발신 번호로 미래 예약 검색 |
| `send_booking_sms` | SIP MESSAGE SMS 발송 |

---

## 2. 리서치 요약 — 글로벌 트렌드

### GitHub 주요 레퍼런스

| 프로젝트 | Stars | 핵심 Tool 패턴 |
|---|---|---|
| `microsoft/call-center-ai` | 6,428 | 보험 클레임 처리·IT 지원·CRM 리마인더·SMS 알림 |
| `filip-michalsky/SalesGPT` | 2,557 | 영업 단계 인식·Stripe 결제 링크 생성·Calendly 미팅 링크 |
| `kaymen99/sales-outreach-automation-langgraph` | 264 | HubSpot/Airtable CRM 생성·업데이트·리드 스코어링 |
| `Rajathbharadwaj/voice-agent` | - | `add_note`, `end_call`, `request_callback` (SDR 패턴) |
| `yerdaulet-damir/langgraph-sales-agent` | - | `search_products`, `get_promotions`, Stripe 결제 링크 |

### 서비스 플랫폼 주요 Tool 패턴

| 플랫폼 | 제공 Tool 패턴 |
|---|---|
| **Bolna** | 슬롯 조회·예약·호전환·커스텀 API 4종 |
| **SIP2AI** | query_tool(지식베이스)·callback·transfer·hangup |
| **SIPTEL** | 리드 자격 평가·부동산 시청·법률 클라이언트 스크리닝 |
| **Vapi/Retell** | 병렬 Tool 호출·비동기 장시간 작업·CRM 웹훅 |
| **Siperb (AstriCon 2026)** | 채널 통합(SIP+채팅+이메일)·컨텍스트 공유 |
| **AISAX** | AI Voice Survey Agent — 설문 수집·NPS·CRM 연동 |

---

## 3. 예약 외 신규 Tool 기획 후보

### ── 카테고리 A: CRM / 리드 관리 ──

#### A-1. `create_crm_contact` — 통화 중 CRM 고객 등록

```
전화 수신 → 신규 고객으로 판단 → CRM에 연락처 자동 생성
```

- **입력**: `name`, `phone`, `email`(선택), `source`("inbound_call"), `owner`
- **동작**: 내부 CRM(또는 HubSpot/Airtable 웹훅) → contacts 테이블 INSERT
- **보이스봇 활용**:
  > "처음 전화 주신 것 같네요. 성함이 어떻게 되세요?"
  > → [create_crm_contact] → 이후 예약 연계 시 고객 ID 자동 활용
- **난이도**: ★★☆☆☆ (contacts 테이블 + 서비스 함수 추가)
- **참고**: microsoft/call-center-ai, kaymen99/sales-outreach-automation-langgraph

---

#### A-2. `add_call_note` — 통화 메모 자동 기록

```
통화 중 주요 내용 → 통화 종료 전 CRM/DB에 노트 저장
```

- **입력**: `call_id`, `note`, `category`("inquiry"/"complaint"/"request")
- **동작**: `call_notes` 테이블 INSERT, `call_history` 연계
- **보이스봇 활용**:
  > 고객: "다음에는 2층 창가 자리로 부탁해요."
  > → [add_call_note(note="창가 자리 선호", category="preference")]
  > → 다음 예약 시 메모 자동 표시
- **난이도**: ★★☆☆☆ (call_notes 테이블 신규)
- **참고**: Rajathbharadwaj/voice-agent `add_note` Tool

---

#### A-3. `qualify_lead` — 리드 자격 평가

```
아웃바운드 콜에서 질문 응답 수집 → 점수 계산 → CRM 업데이트
```

- **입력**: `call_id`, `answers: dict`, `criteria: list`
- **동작**: 미리 정의된 기준(예산·필요 시기·의사결정권자 여부)으로 점수 계산 → `leads` 테이블 저장
- **보이스봇 활용** (아웃바운드):
  > AI: "혹시 현재 예산 범위가 어떻게 되시나요?"
  > → [qualify_lead(answers={"budget": "500만원", "timeline": "이번 달"})]
  > → 점수 8/10 → 영업팀 알림
- **난이도**: ★★★☆☆ (scoring 로직 + leads 테이블)
- **참고**: VICIdial AI Use Case, kaymen99/langgraph-sales-outreach, SalesGPT

---

### ── 카테고리 B: 고객 서비스 / 지식 응대 ──

#### B-1. `search_faq` — FAQ/지식베이스 직접 검색 Tool

```
현재: RAG는 별도 노드(adaptive_rag)를 경유 — 예약 대화 중 FAQ 질문 처리 불가
개선: booking_agent 내에서 LLM이 필요 시 직접 KB 검색
```

- **입력**: `query`, `owner`, `category`(선택)
- **동작**: ChromaDB 벡터 검색 → 상위 3개 문서 요약 반환
- **보이스봇 활용**:
  > 고객: "예약하려는데 주차는 되나요?"
  > → [search_faq(query="주차")] → "지하 1층 무료 주차 가능합니다."
  > → 이후 예약 흐름 계속
- **난이도**: ★★★☆☆ (기존 RAG 엔진을 Tool로 래핑)
- **참고**: C-2(이전 리서치), Bolna의 query_tool 패턴

---

#### B-2. `get_product_info` — 상품·서비스 정보 조회

```
메뉴·상품·서비스 항목을 DB에서 실시간 조회
```

- **입력**: `owner`, `category`(선택), `item_name`(선택)
- **동작**: `products` 테이블 또는 JSON 카탈로그 조회
- **보이스봇 활용** (레스토랑):
  > 고객: "파스타 메뉴 있나요?"
  > → [get_product_info(category="파스타")] → "까르보나라 18,000원, 봉골레 17,000원"
- **도메인 확장**: 부동산(매물 정보), 병원(진료 항목·비용), 쇼핑몰(재고)
- **난이도**: ★★☆☆☆ (products 테이블 신규)
- **참고**: yerdaulet-damir/langgraph-sales-agent의 `search_products`

---

#### B-3. `check_order_status` — 주문/서비스 처리 현황 조회

```
고객이 주문번호·전화번호로 현재 처리 상태를 확인
```

- **입력**: `order_id` 또는 `customer_phone`, `owner`
- **동작**: `orders` 테이블 조회 → 상태(접수/처리중/배송중/완료) 반환
- **보이스봇 활용** (배달·AS·B2B):
  > 고객: "제 주문 언제 도착하나요?"
  > → [check_order_status(phone="010-1111-2222")] → "오늘 오후 3시~5시 사이 배송 예정"
- **난이도**: ★★☆☆☆ (orders 테이블 신규 또는 외부 API 연동)
- **참고**: SIPTEL E-commerce 패턴, VICIdial Use Case 4

---

### ── 카테고리 C: 결제 / 알림 ──

#### C-1. `send_payment_reminder` — 결제 알림 아웃바운드

```
미납 고객에게 아웃바운드 통화로 결제 안내
```

- **입력**: `customer_phone`, `amount`, `due_date`, `invoice_id`, `owner`
- **동작**: 아웃바운드 통화 트리거 → LLM이 결제 안내 대화 → 고객 확인 시 SMS로 결제 링크 발송
- **보이스봇 활용**:
  > AI(아웃바운드): "안녕하세요. 이번 달 청구금액 30,000원이 미납 상태입니다..."
  > → [send_payment_reminder SMS] → "결제 링크를 문자로 보내드렸습니다."
- **난이도**: ★★★☆☆ (기존 outbound_manager + SMS Tool 연계)
- **참고**: VICIdial Payment Reminder Use Case, 금융권 보이스봇 패턴

---

#### C-2. `generate_payment_link` — 결제 링크 생성·SMS 발송

```
전화 통화 중 구두 결제보다 SMS 링크 전송이 더 신뢰성 있음
```

- **입력**: `customer_phone`, `amount`, `description`, `expiry_hours`
- **동작**: 내부 결제 URL 생성(또는 PG사 API) → SIP SMS로 발송
- **보이스봇 활용** (SalesGPT 패턴):
  > 고객: "그럼 결제할게요."
  > → [generate_payment_link] → "결제 링크를 문자로 보내드렸습니다. 10분 이내 유효합니다."
- **난이도**: ★★★★☆ (PG 연동 필요, 내부 구현 시 ★★★☆)
- **참고**: SalesGPT Stripe 링크 생성, Rajathbharadwaj의 `send_booking_link`

---

### ── 카테고리 D: 설문 / 피드백 ──

#### D-1. `run_post_call_survey` — 통화 후 만족도 조사

```
통화 종료 직전 또는 아웃바운드로 서비스 만족도 수집
```

- **입력**: `call_id`, `questions: list`, `owner`
- **동작**: LLM이 질문 목록을 순서대로 물어봄 → 응답 수집 → `survey_responses` 테이블 저장
- **보이스봇 활용**:
  > AI: "마지막으로 오늘 서비스에 대해 1~5점으로 평가해 주시겠어요?"
  > → [run_post_call_survey] → 응답 저장 → 분석 대시보드 연계
- **통계 활용**: NPS 계산, 불만 키워드 자동 태깅, 개선 포인트 추출
- **난이도**: ★★★☆☆ (survey_responses 테이블 + 아웃바운드 연동)
- **참고**: AISAX AI Voice Survey Agent, Tars 레스토랑 피드백 AI

---

#### D-2. `collect_complaint` — 불만/민원 자동 접수

```
고객 불만을 구조화된 폼으로 수집 → 담당자 이메일/알림 발송
```

- **입력**: `call_id`, `category`, `description`, `priority`("low"/"medium"/"high")
- **동작**: `complaints` 테이블 INSERT → 담당자 Slack/이메일 알림 웹훅 트리거
- **보이스봇 활용**:
  > 고객: "지난번 서비스가 너무 불만족스러웠어요."
  > → [collect_complaint(category="서비스 품질", priority="high")]
  > → 담당자 알림 → "불만사항이 접수되었습니다. 24시간 내 담당자가 연락드립니다."
- **난이도**: ★★★☆☆ (complaints 테이블 + 웹훅)
- **참고**: microsoft/call-center-ai의 클레임 처리 패턴

---

### ── 카테고리 E: 통화 제어 / 운영 ──

#### E-1. `transfer_to_department` — 부서별 스마트 호전환

```
현재: HITL은 단일 운영자 대기 큐만 존재
개선: "법무팀으로 연결", "기술지원팀으로 연결" 등 부서 키워드로 직접 전환
```

- **입력**: `department`("sales"/"support"/"billing"/"manager"), `reason`, `call_id`
- **동작**: 부서별 내선 번호 매핑 → SIP REFER 트리거 → 호전환 완료
- **보이스봇 활용**:
  > 고객: "결제 관련해서 담당자 연결해주세요."
  > → [transfer_to_department(department="billing")] → 내선 1004로 전환
- **난이도**: ★★★★☆ (기존 SIP transfer + 부서 매핑 테이블)
- **참고**: SIP2AI의 transfer 내장 Tool, Bolna의 Transfer Calls

---

#### E-2. `schedule_callback` — 콜백 예약

```
통화 중 "나중에 다시 연락해주세요" 요청 → 지정 시간에 자동 아웃바운드
```

- **입력**: `customer_phone`, `preferred_time`, `reason`, `owner`
- **동작**: `callback_queue` 테이블 INSERT → 스케줄러가 지정 시간에 아웃바운드 트리거
- **보이스봇 활용**:
  > 고객: "지금 바빠서요, 내일 오후 2시에 다시 연락해주세요."
  > → [schedule_callback(time="2026-04-10 14:00", reason="상품 문의")]
  > → 내일 14:00 자동 아웃바운드 콜
- **난이도**: ★★★☆☆ (callback_queue + 스케줄러)
- **참고**: Rajathbharadwaj의 `request_callback` Tool, SIP2AI의 callback Tool

---

#### E-3. `end_call_with_outcome` — 통화 결과 기록 후 종료

```
통화 종료 시 결과를 구조화하여 저장
```

- **입력**: `call_id`, `outcome`("booking_made"/"cancelled"/"transferred"/"info_given"/"no_answer"/"complaint"), `summary`
- **동작**: `call_results` 테이블 저장 → CDR 연계 → 운영 대시보드 표시
- **보이스봇 활용**:
  > 예약 완료 후: [end_call_with_outcome(outcome="booking_made", summary="홍길동 4/10 14:00 예약")]
- **난이도**: ★★☆☆☆ (call_results 테이블 + CDR 연계)
- **참고**: Rajathbharadwaj `end_call` Tool, microsoft/call-center-ai 리포트 패턴

---

### ── 카테고리 F: 외부 서비스 연동 ──

#### F-1. `lookup_address` — 주소·지도 정보 조회

```
"위치가 어디예요?", "거기까지 어떻게 가요?" 질문 처리
```

- **입력**: `owner` (또는 `address` 직접)
- **동작**: `booking_settings.address` 또는 Google Maps API 조회 → 경로 안내
- **보이스봇 활용** (레스토랑·병원·부동산):
  > 고객: "주소 알려주시겠어요?"
  > → [lookup_address] → "서울시 강남구 테헤란로 123, 지하철 2호선 강남역 3번 출구"
- **난이도**: ★★☆☆☆ (settings에서 가져오면 ★★, Maps API면 ★★★)

---

#### F-2. `check_weather` — 날씨 조회 (예약 관련 컨텍스트)

```
야외 행사·골프·피크닉 예약 시 날씨 정보 함께 제공
```

- **입력**: `location`, `date`
- **동작**: 외부 날씨 API(OpenWeatherMap 등) 조회
- **보이스봇 활용** (골프장·야외 행사장):
  > AI: "참고로 예약하신 날 예보는 맑음, 기온 22°C입니다."
- **난이도**: ★★☆☆☆ (외부 API 호출)
- **참고**: SIP2AI 데모 ("Amsterdam 날씨")

---

#### F-3. `get_realtime_wait_time` — 현재 대기 시간 조회

```
"지금 얼마나 기다려야 해요?" 문의에 실시간 대기 정보 제공
```

- **입력**: `owner`, `service_type`
- **동작**: 현재 활성 예약 수 + 평균 서비스 시간으로 대기 계산
- **보이스봇 활용** (병원·음식점):
  > 고객: "지금 가면 얼마나 기다려야 하나요?"
  > → [get_realtime_wait_time] → "현재 대기 3팀, 약 25분 예상입니다."
- **난이도**: ★★★☆☆ (booking DB에서 실시간 집계)

---

## 4. 현재 시스템 통합 방식

모든 신규 Tool은 기존 인프라를 그대로 활용합니다.

```
[현재 booking_agent 흐름 — 변경 없음]
classify_intent → (booking/service keyword) → booking_agent_node
                                                    ↓
                                          llm_with_tools.bind(BOOKING_TOOLS + NEW_TOOLS)
                                                    ↓
                                            Tool 루프 (최대 5~8회)
```

**추가 방법 (예시)**:
```python
# booking_tools.py 하단에 추가
from src.ai_voicebot.langgraph.tools.crm_tools import create_crm_contact, add_call_note
from src.ai_voicebot.langgraph.tools.survey_tools import run_post_call_survey

BOOKING_TOOLS = [
    ...기존 8개...,
    create_crm_contact,   # A-1
    add_call_note,        # A-2
    search_faq,           # B-1
    check_order_status,   # B-3
    schedule_callback,    # E-2
    end_call_with_outcome, # E-3
]
```

intent 분류 확장이 필요한 Tool (별도 에이전트 노드 고려):
- `qualify_lead` → `outbound_sales` intent
- `run_post_call_survey` → `survey` intent 또는 통화 종료 훅

---

## 5. 도메인별 추천 Tool 조합

| 도메인 | 핵심 Tool 조합 |
|---|---|
| **레스토랑** | 예약 8종 + `get_product_info`(메뉴) + `get_realtime_wait_time` + `run_post_call_survey` |
| **병원·클리닉** | 예약 8종 + `search_faq`(진료 안내) + `get_realtime_wait_time` + `add_call_note`(증상 메모) |
| **부동산** | 예약 8종 + `get_product_info`(매물) + `qualify_lead` + `schedule_callback` |
| **법률·컨설팅** | 예약 8종 + `collect_complaint` + `add_call_note` + `transfer_to_department` |
| **이커머스·배달** | `check_order_status` + `send_payment_reminder` + `generate_payment_link` + `collect_complaint` |
| **영업(SDR)** | `qualify_lead` + `create_crm_contact` + `schedule_callback` + `end_call_with_outcome` |
| **콜센터** | `search_faq` + `collect_complaint` + `transfer_to_department` + `add_call_note` + `run_post_call_survey` |

---

## 6. 구현 우선순위 (난이도 × 효과)

| 순위 | Tool | 카테고리 | 난이도 | 기대 효과 | 예상 소요 |
|---|---|---|---|---|---|
| 1 | `add_call_note` | CRM | ★★ | 고객 맥락 누적·재방문 UX | 2~3시간 |
| 2 | `end_call_with_outcome` | 통화 제어 | ★★ | 운영 통계 기반 마련 | 2~3시간 |
| 3 | `search_faq` | 지식 응대 | ★★★ | 예약+FAQ 혼합 질문 처리 | 4~6시간 |
| 4 | `schedule_callback` | 통화 제어 | ★★★ | 아웃바운드 자동화 | 4~6시간 |
| 5 | `get_product_info` | 고객 서비스 | ★★ | 도메인 확장 (메뉴·매물) | 3~4시간 |
| 6 | `create_crm_contact` | CRM | ★★ | 신규 고객 자동 등록 | 3~4시간 |
| 7 | `collect_complaint` | 피드백 | ★★★ | 민원 자동 접수·에스컬레이션 | 5~8시간 |
| 8 | `check_order_status` | 고객 서비스 | ★★ | 배달·AS 도메인 확장 | 4~6시간 |
| 9 | `run_post_call_survey` | 피드백 | ★★★ | NPS·만족도 자동 수집 | 6~8시간 |
| 10 | `qualify_lead` | CRM | ★★★ | 아웃바운드 SDR 자동화 | 6~10시간 |
| 11 | `transfer_to_department` | 통화 제어 | ★★★★ | 부서별 호전환 | 8~12시간 |
| 12 | `generate_payment_link` | 결제 | ★★★★ | 전화 중 결제 완료 | 8~16시간 |

---

## 7. 신규 Tool 구조 템플릿

현재 `booking_tools.py` 패턴을 그대로 따릅니다.

```python
# src/ai_voicebot/langgraph/tools/crm_tools.py

from src.ai_voicebot.langgraph.tools.booking_tools import _make_tool
import json, logging

logger = logging.getLogger(__name__)

def _add_call_note(call_id: str, note: str, category: str = "general") -> str:
    """
    통화 중 주요 내용을 메모로 저장합니다.

    Args:
        call_id: 통화 ID
        note: 메모 내용
        category: 메모 분류 (general / preference / complaint / request)

    Returns:
        JSON 문자열: 저장 결과
    """
    try:
        # TODO: call_notes DB 저장
        logger.info("call_note_added", call_id=call_id, category=category)
        return json.dumps({"success": True, "message": "메모가 저장되었습니다."}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)

add_call_note = _make_tool(_add_call_note)
```

---

## 8. 단기 구현 권장 (3개 Tool, 0.5일 작업)

현재 인프라에서 즉시 구현 가능한 고효과 Tool:

1. **`add_call_note`** — call_notes 테이블 추가 → booking_agent에서 특이사항 메모 가능
2. **`end_call_with_outcome`** — 통화 결과 구조화 → 운영 리포트 기반
3. **`search_faq`** — 기존 RAG 엔진을 Tool로 래핑 → 예약 대화 중 FAQ 처리

세 Tool 모두:
- 기존 SQLite·ChromaDB·SIP 인프라 그대로 활용
- `booking_tools.py` 패턴 동일하게 구현
- `BOOKING_TOOLS` 리스트에 append만으로 즉시 적용
- `booking_agent_node` 코드 수정 불필요
