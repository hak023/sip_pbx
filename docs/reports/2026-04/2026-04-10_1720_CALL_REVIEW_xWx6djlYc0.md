# 호 리뷰 리포트 — call_id: xWx6djlYc0

- **작성일**: 2026-04-10 17:20
- **로그 파일**: `sip-pbx/logs/call_data_record_20260410.log`
- **RTP TSV**: `sip-pbx/logs/rtp_tx_xWx6djlYc0.tsv`
- **테넌트 (owner)**: 1003 (이탈리안 레스토랑 비스트로 벨라)
- **상태**: 분석 완료

---

## 개요

2026-04-10 16:55~16:59에 걸쳐 약 4분간 진행된 인바운드 호에 대한 로그 기반 리뷰.  
고객은 예약, 상담원 연결, 영업시간 문의 등 다양한 의도를 가지고 발화했으나, **모든 발화에서 AI가 정상 응답하지 못하고 "일시적인 오류" 메시지만 반복 출력**했다.  
또한 상담원 연결 요청이 2회 발생했으나 두 경우 모두 대상을 찾지 못해 전환에 실패했다.

---

## 이벤트 타임라인

| 시각 | seq | 이벤트 | 내용 |
|------|-----|--------|------|
| 16:55:27 | — | `call_connected` | 수신 (callee: 1003) |
| 16:55:27 | — | `greeting_phase1_sent` | "안녕하세요, 이탈리안 레스토랑 비스트로 벨라입니다." |
| 16:55:30 | — | `greeting_phase2_sent` | "비스트로 벨라에 전화 주셔서 감사합니다. 무엇을 도와드릴까요?" |
| 16:55:39 | 1 | STT | "예약하려고 합니다." |
| 16:55:50 | 1 | `llm_exchange` | **invoke_error** / agent_elapsed **10.573s** → "죄송합니다. 일시적인 오류" |
| 16:56:02 | 2 | STT | "뭐 가능한 예약사가 있을까요?" |
| 16:56:21 | 2 | `llm_exchange` | **invoke_error** / agent_elapsed **18.987s** → "죄송합니다. 일시적인 오류" |
| 16:56:31 | 3 | STT | "오늘 예약하려고 합니다." (쿼리 리라이트: "2026년 4월 10일 예약하려고 합니다.") |
| 16:56:50 | 3 | `llm_exchange` | **invoke_error** / agent_elapsed **18.436s** → "죄송합니다. 일시적인 오류" |
| 16:57:13 | 4 | STT | "어떤 걸 알려줄 수 있을까요?" |
| 16:57:35 | 4 | `llm_exchange` | **invoke_error** / agent_elapsed **21.850s** → "죄송합니다. 일시적인 오류" |
| 16:57:48 | 5 | STT | "혹시 영업시간은 어떻게 되나요?" (RAG confidence 0.353, soft_fallback=false) |
| 16:57:57 | 5 | `llm_exchange` | **invoke_error** / agent_elapsed **9.227s** → "죄송합니다. 일시적인 오류" |
| 16:58:07 | 6 | STT | "현금은 연결해 주세요." (STT 오인식 추정: "직원을 연결해 주세요") |
| 16:58:07 | — | `transfer_request_detected` | 전환 요청 탐지 |
| 16:58:07 | — | `transfer_contact_not_found` | 전환 대상 미설정 → 전환 실패 |
| 16:58:42 | 7 | STT | "너는 누구니?" |
| 16:58:53 | 7 | `llm_exchange` | **invoke_error** / agent_elapsed **11.218s** → "죄송합니다. 일시적인 오류" |
| 16:59:02 | 8 | STT | "상담원 연결해 주세요." |
| 16:59:02 | — | `transfer_request_detected` | 전환 요청 탐지 |
| 16:59:02 | — | `transfer_contact_not_found` | 전환 대상 미설정 → 전환 실패 |
| 16:59:17 | 9 | STT | "감사합니다." |
| 16:59:26 | 9 | `llm_exchange` | **invoke_error** / agent_elapsed **8.435s** → "죄송합니다. 일시적인 오류" |
| 16:59:37 | — | `call_ended` | 통화 종료 |

---

## LLM 응답 지연 요약

| seq | 발화 | agent_elapsed | 결과 |
|-----|------|--------------|------|
| 1 | 예약하려고 합니다. | **10.573s** | invoke_error |
| 2 | 뭐 가능한 예약사가 있을까요? | **18.987s** | invoke_error |
| 3 | 오늘 예약하려고 합니다. | **18.436s** | invoke_error |
| 4 | 어떤 걸 알려줄 수 있을까요? | **21.850s** | invoke_error |
| 5 | 혹시 영업시간은 어떻게 되나요? | **9.227s** | invoke_error |
| 7 | 너는 누구니? | **11.218s** | invoke_error |
| 9 | 감사합니다. | **8.435s** | invoke_error |

**전체 7회 발화 중 7회 전부 invoke_error** — 단 1건도 정상 응답 없음.

---

## RTP 전송 품질

| 항목 | 값 |
|------|-----|
| 총 전송 패킷 | 12,233 |
| 평균 전송 간격 | 20 ms (정상, G.711 기준 20ms) |
| 최대 전송 간격 | 993 ms (1회 스파이크, 순간적) |
| 50ms 초과 패킷 | 10개 (0.1%) |
| 100ms 초과 패킷 | 6개 (0.0%) |

RTP 자체는 안정적이며, 문제는 네트워크 레이어가 아닌 **AI 처리 레이어**에 집중됨.

---

## 문제점 분석

### P1 (Critical) — LLM invoke_error 연속 발생

**현상**: 모든 발화에서 `llm_rag_context_source: "invoke_error"`, `intent: "unknown"`, `confidence: 0.0` 반환.  
**영향**: 고객은 한 번도 유의미한 응답을 받지 못하고 "죄송합니다. 일시적인 오류" 7번 청취 후 종료.  
**가능 원인 추정**:
- LangGraph 에이전트 내부 예외 (API 키 만료, LLM provider 장애, 타임아웃 누적)
- langgraph invoke() 호출 중 unhandled exception 발생 → fallback 분기로 이동
- `llm_generate_response`가 각 발화에서 **2~4회씩 반복 호출**되는 점이 수상함 (seq 1: 3회, seq 2: 4회, seq 3: 4회, seq 5: 3회) — langgraph 내 retry 루프 또는 중복 호출 버그 가능성

**확인 필요**: `app.log`에서 같은 시각대의 예외 스택 트레이스 검색 (`invoke_error`, `Exception`, `LangGraph`)

---

### P2 (Critical) — LLM 중복 호출 버그 의심

**현상**: 단일 STT 발화에 대해 `llm_generate_response` 이벤트가 2~4회 연속 발생 (동일 query_preview로 반복).

| seq | 발화 | llm_generate_response 호출 횟수 |
|-----|------|-------------------------------|
| 1 | 예약하려고 합니다. | 3회 |
| 2 | 뭐 가능한 예약사가 있을까요? | 4회 |
| 3 | 오늘 예약하려고 합니다. | 4회 |
| 5 | 혹시 영업시간은 어떻게 되나요? | 3회 |
| 7 | 너는 누구니? | 3회 |
| 9 | 감사합니다. | 3회 |

각 호출은 수 초 지연 후 모두 실패. 이는 LangGraph 라우팅 루프 혹은 STT 메시지가 여러 파이프라인 구독자에게 중복 전달되는 문제일 수 있음.  
**직전 리뷰(ZNh~RK-IOg)에서도 유사 패턴이 관찰된 바 있음.**

---

### P3 (High) — 상담원 전환 실패 후 고객 안내 없음

**현상**: seq 6("현금은 연결해 주세요."), seq 8("상담원 연결해 주세요.") 두 경우 모두 `transfer_contact_not_found` → 이후 어떤 응답도 TTS로 출력되지 않음.  
**영향**: 고객은 전환 시도 여부조차 알 수 없는 상태로 방치됨.  
**권장 조치**: 전환 실패 시 "현재 상담원 연결이 어렵습니다. 잠시 후 다시 시도하시거나 [번호]로 연락 주시면 안내해 드리겠습니다." 같은 안내 TTS 필수.

> 참고: seq 6의 발화 "현금은 연결해 주세요."는 STT 오인식 추정. 원의도는 "직원을" 또는 "상담원을"일 가능성 높음.

---

### P4 (High) — 전환 대상 미설정 (운영 설정 문제)

**현상**: `transfer_contact_not_found` — owner 1003의 테넌트에 전환 대상 번호/내선이 등록되지 않음.  
**영향**: 상담원 연결 요청 시 전환 불가.  
**권장 조치**: 관리자 페이지에서 전환 대상 번호를 등록해야 함.

---

### P5 (Medium) — RAG soft_fallback 전적 의존

**현상**: 예약 관련 쿼리들의 RAG confidence가 0.201~0.241 수준이며 모두 `soft_fallback_applied: true`.  
유일한 예외는 "영업시간" 쿼리 (confidence 0.353, `soft_fallback: false`) 인데, 이 역시 LLM invoke_error로 정상 응답 실패.  
**원인**: 지식베이스에 "예약 방법", "가능한 예약 날짜", "AI 안내 가능 항목" 등 관련 문서가 부족함.  
**권장 조치**: KB에 예약 관련 Q&A를 보강하여 RAG confidence를 임계치(0.28) 이상으로 높여야 함.

---

### P6 (Low) — "감사합니다" 발화의 chitchat 분류 후 invoke_error

**현상**: seq 9 "감사합니다."가 chitchat으로 분류됐으나 invoke_error로 처리됨.  
**기대 동작**: farewell 키워드로 빠르게 처리되거나, 간단 인사 캐시 응답 활용.  
**현황**: P1의 전체적인 invoke_error 문제가 해소되면 자연히 개선될 가능성 높음.

---

## 최우선 대응 항목 (Action Items)

| 우선순위 | 항목 | 조치 |
|---------|------|------|
| P1 | LLM invoke_error 원인 규명 | `app.log`에서 16:55~16:59 구간 exception 스택 트레이스 확인. LLM API 키 상태, provider 장애 이력 점검 |
| P2 | 중복 LLM 호출 버그 | LangGraph 라우팅 중 동일 utterance에 대한 중복 호출 경로 확인 및 차단 |
| P3 | 전환 실패 안내 TTS 추가 | `transfer_contact_not_found` 이벤트 발생 시 사용자에게 실패 안내 발화 출력 |
| P4 | 전환 대상 등록 | 관리자 페이지에서 owner 1003의 전환 대상 번호 설정 |
| P5 | KB 보강 | 예약 관련 Q&A 항목 추가 (날짜/시간 조회, AI 안내 범위 등) |

---

## 결론

이번 호는 **AI 시스템 전반의 장애 상황** 하에 발생한 통화로, 고객은 단 한 번의 유의미한 응답도 받지 못하고 통화를 종료했다. P1(invoke_error)와 P2(중복 호출) 문제가 해소되지 않는 한 다른 문제는 점검조차 어렵다. RTP 품질은 정상이므로 장애 원인은 AI 파이프라인(LangGraph/LLM 호출 계층)에 있다.
