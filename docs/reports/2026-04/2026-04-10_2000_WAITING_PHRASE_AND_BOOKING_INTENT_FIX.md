# 대기 안내 멘트 중복 방지 & 예약 인텐트 분류 오류 수정

작성일: 2026-04-10 20:00  
상태: 완료  
관련 call_id: `5wOmeXlXIV` (예약 의도 → RAG 검색 오라우팅 확인)

---

## 개요

두 가지 문제를 분석하고 수정했다.

1. **대기 안내 멘트 중복 발화**: TTS RTP가 이미 전송 중임에도 대기 안내 멘트가 발화되어 고객이 두 음성을 동시에 듣는 상황 발생.
2. **예약 인텐트 RAG 오라우팅**: "예약하려고 합니다." 발화가 `booking`이 아닌 `question`으로 분류되어 tool 호출 없이 RAG 검색만 수행됨.

---

## 문제1 — 대기 안내 멘트 TTS 중복 발화

### 원인

`send_waiting_phrase_now()` 실행 전 조건 체크가 `_waiting_phrase_active`(이미 발화된 경우) + 아웃바운드 모드만 있었고, **현재 TTS RTP가 전송 중인지 여부는 체크하지 않았다.**

TTS RTP 전송은 두 단계로 이루어진다:
1. `LLMFullResponseStartFrame ~ LLMFullResponseEndFrame`: `_tts_active=True` (rtp_transport.py 설정)
2. `LLMFullResponseEndFrame` 이후: `_tts_active=False`로 초기화되지만, PCM 큐(`_pipecat_pcm_queue`)에 데이터가 남아 RTP 실제 전송이 계속됨

따라서 `_tts_active=False`이더라도 PCM 큐에 잔량이 있으면 고객은 여전히 오디오를 듣고 있다.

### 수정

**`rtp_transport.py` (`SIPPBXOutputTransport.__init__`)**
- `_tts_sync_context["_rtp_worker_ref"] = rtp_worker` 등록: rag_processor에서 PCM 큐 참조 가능하게 함

**`rag_processor.py` (대기 안내 멘트 발화 조건)**
```
기존: 아웃바운드 or _waiting_phrase_active 이면 스킵
변경: + TTS RTP 전송 중(_tts_active=True or PCM 큐 잔량>3) 이면 스킵
```

구체적으로 3가지를 OR 조건으로 확인:
1. `_tts_active`: `LLMFullResponseEndFrame` 이전, TTS 프레임 처리 중
2. `_tts_pending_pcm_bytes > 0`: EndFrame 이전까지 누적 바이트 (보조 지표)
3. `_pipecat_pcm_queue.qsize() > 3`: EndFrame 이후 PCM 큐에 실제 잔량 있음

PCM 큐 임계값 3은 약 60ms(3 * 20ms 패킷) 수준으로, 실질적으로 재생 중인 상태를 의미한다. 1~2개는 스케줄링 오차로 볼 수 있어 >3 채택.

로그 키: `llm_waiting_phrase_skip_tts_busy`

---

## 문제2 — 예약 인텐트 RAG 오라우팅

### 원인 분석 (`5wOmeXlXIV` 로그 기반)

```
"예약하려고 합니다." → classify_intent 0.012초 → intent=question
→ adaptive_rag 5.3초 → RAG 검색 결과: "예약은 어떻게 해요?" FAQ 문서
→ generate_response: "영업시간 중 전화로 예약하실 수 있습니다."
```

`classify_intent` 0.012초는 LLM 3차 분류(~300ms)에 도달하지 않았음을 의미한다.
페르소나 유사도 2차 단락에서 `is_relevant=True` → 즉시 `question` 반환한 것이 원인.

**"예약하려고 합니다"는 페르소나(비스트로 벨라 레스토랑)와 관련된 발화**이므로 유사도 체크가 `is_relevant=True`를 반환하고, LLM 3차 분류 없이 바로 `question`으로 종료된다.

scope_keywords 매칭(1차)도 동일한 구조적 문제를 가진다.

### 수정

**`classify_intent.py`**

`_BOOKING_ACTION_PATTERNS` 튜플 추가:
- "예약하려고", "예약하고 싶", "예약해줘" 등 **동사 결합 패턴** (명사 "예약"만은 제외)
- 취소·변경·조회·가용 슬롯 확인 패턴 포함

**적용 지점 2곳:**
1. **1차 scope_keywords 매칭** — 패턴 감지 시 LLM 3차로 fall-through (return 없이 통과)
2. **2차 페르소나 유사도 `is_relevant=True`** — 패턴 감지 시 LLM 3차로 fall-through

LLM 3차에는 `booking` 인텐트 프롬프트 예시가 이미 포함되어 있으므로 정확히 분류된다.

### 처리 흐름 (수정 후)

```
"예약하려고 합니다."
  → 1차 scope_keywords: "예약" 매칭 → booking 동작 패턴("예약하려고") 감지 → LLM 3차로 위임
  → LLM 3차: {"intent": "booking", "search_query": "예약"} 
  → route_utterance: booking_agent 직행
  → booking_agent: 날짜/시간/인원 수집 시작
```

---

## 변경 이력

| 파일 경로 | 변경 유형 | 요약 |
|---|---|---|
| `src/ai_voicebot/pipecat/rtp_transport.py` | 수정 | `SIPPBXOutputTransport.__init__`에서 `_rtp_worker_ref` tts_sync_context 등록 |
| `src/ai_voicebot/pipecat/processors/rag_processor.py` | 수정 | 대기 안내 멘트 발화 전 TTS RTP 전송 중 여부 3단계 확인 조건 추가 |
| `src/ai_voicebot/langgraph/nodes/classify_intent.py` | 수정 | `_BOOKING_ACTION_PATTERNS` 추가, scope_keyword·유사도 단락에서 booking 동작 패턴 감지 시 LLM 3차로 위임 |

---

## 주요 결정 사항

- **PCM 큐 임계값 >3**: 스케줄링 지터 무시, 실제 재생 중 상태만 포착
- **booking 동작 패턴을 명사가 아닌 동사 결합으로 정의**: "예약이 가능한가요?"(question)와 "예약하고 싶어요"(booking) 구별
- **LLM 3차 위임 방식 선택**: 키워드 직접 분류(`return booking`) 대신 fall-through → LLM이 맥락 포함 최종 판단 (오작동 최소화)

---

## 잔여 과제

- `_BOOKING_ACTION_PATTERNS` 패턴은 운영 중 오분류 사례 발생 시 보완 필요
- PCM 큐 임계값(>3)은 네트워크 지연 환경에서 튜닝 가능
