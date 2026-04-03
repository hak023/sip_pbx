# Call bsn9Yr4gSC — 종합 점검 리포트

| 항목 | 내용 |
|------|------|
| 작성일 | 2026-04-03 12:00 |
| 대상 call_id | `bsn9Yr4gSC` |
| 통화 시간 | 10:16:41 ~ 10:19:12 (약 2분 31초) |
| 로그 | `call_data_record_20260403.log` |
| RTP dump | `rtp_tx_bsn9Yr4gSC.tsv` |

---

## 발화 타임라인 요약

| seq | 발화 | stt_final | tts_pushed | agent_graph | 주요 병목 | 비고 |
|-----|------|-----------|------------|-------------|-----------|------|
| — | (인사) | — | 10:16:42 / 10:16:46 | — | — | — |
| 1 | 기상 감정서 가입하는 방법 | 10:17:05.711 | 10:17:10.497 | **4.775s** | check_cache 0.71s + generate 3.99s | ✅ 정상 응답 |
| 2 | 태풍 정보 어디서 확인 | 10:17:32.339 | 10:17:35.780 | 3.438s | generate 3.40s | ✅ 정상 응답 |
| 3 | 내일 서울 날씨 알려주세요 | 10:17:55.156 | 10:17:59.508 | 4.347s | generate 4.26s | ✅ 정상 응답 (HITL 지식 히트) |
| 4 | 꽃이 많이 폈더라고. | 10:18:18.150 | 10:18:29.337 | **11.176s** | classify 1.64s + step_back 2.60s + generate 6.88s | ⚠ JSON TTS 송출 + 오분류 |

---

## 이슈 1: seq 4 — agent_graph 11.176초 병목 분석

### 노드별 소요 시간

```
classify_intent:  1.638s  ← LLM 분류 (키워드 미매칭)
step_back:        2.596s  ← Step-Back RAG 추가 검색 (LLM 호출)
adaptive_rag:     0.057s  ← 양호
check_cache:      0.005s  ← 양호
generate_response: 6.877s ← LLM 응답 생성
total:           11.176s
```

### 병목 1-A: classify_intent 1.638s (path: llm_merged)

`"꽃이 많이 폈더라고."` — 이 발화는:
- 키워드 매칭 실패 → LLM 분류 (1.64s)
- LLM이 `intent: "question"` 으로 분류 → **오분류**

**올바른 intent**: `chitchat` (날씨/계절 잡담, AI 기상청 봇 업무 범위 외)

`classify_intent`의 LLM 분류 프롬프트가 "꽃이 폈다"를 날씨/기상 관련 question으로 해석한 것으로 추정.

### 병목 1-B: step_back 2.596s

`intent: question` + `low_quality_filtered: true` (top score 0.0959 < 0.12) 조합에서
Step-Back RAG가 실행되어 별도 LLM 검색 쿼리를 생성하고 재검색(2.6s).

step_back 결과로 반환된 문서도 기상청 상담원, 특보 안내 등으로 꽃이 핀 것과 무관.

### 병목 1-C: generate_response 6.877s

rag_hit_count: 3 (step_back 결과), 응답 len: 52자

LLM이 전달받은 컨텍스트가 발화 `"꽃이 많이 폈더라고."`와 전혀 무관한 기상 문서였기 때문에,
오랜 추론 끝에 JSON 형식으로 잘못된 응답을 생성.

---

## 이슈 2: seq 4 — JSON이 TTS로 송출됨

### 증거

```json
tts_text_pushed.text = "{\"intent\": \"chitchat\", \"search_query\": \"꽃이 많이 폈더라고\"}"
```

### 원인 분석

`generate_response.py`의 `_strip_json_and_markdown_for_tts()`가 이미 적용되어 있으나,
이 경우는 응답이 **완전한 JSON 구조 `{...}`** 이며 `response` 키가 없어 raw 전체를 반환했다.

```python
# 현재 코드 경로 (JSON 전체인 경우):
if brace_start == 0 and not after_json:
    data = _json.loads(json_block)
    if isinstance(data, dict) and data.get("response"):  # ← "response" 키 없으면
        ...
    return cleaned  # ← cleaned = JSON 원문 그대로 반환됨
```

LLM이 `{"intent": "chitchat", "search_query": "..."}` 를 반환했는데,
이 구조에는 `response` 키가 없으므로 JSON 원문이 TTS로 나감.

### 수정 필요 사항

`_strip_json_and_markdown_for_tts()`에서 `response` 키가 없는 JSON인 경우
다음 폴백 처리를 추가해야 한다:

1. `intent`, `search_query` 등 메타 필드만 있는 JSON → 빈 문자열 처리 후 fallback 멘트 사용
2. 또는 분류 결과 JSON이 응답으로 나오지 않도록 프롬프트 강화

---

## 이슈 3: 전체 오류 목록

| 유형 | 발생 위치 | 내용 |
|------|-----------|------|
| 의도 오분류 | seq 4 classify_intent | "꽃이 많이 폈더라고." → question (실제: chitchat) |
| JSON TTS 송출 | seq 4 tts_text_pushed | `{"intent":"chitchat",...}` 그대로 고객에게 송출 |
| step_back 낭비 | seq 4 step_back | 잡담 발화에 2.6s RAG step-back 실행 |
| 과도한 generate | seq 4 generate_response | 무관 컨텍스트로 LLM 6.9s 소비 |
| silence 구간 178ms 갭 | 10:17:05.914 | seq=35243, STT 입력 직후 silence 전송 간격 |

seq 1의 `check_cache: 0.71s` — 이전보다 개선됨(이전 Tu48lwdl6s seq1: 3.94s).
`run_in_executor` 적용 후 timeout이 정상 동작하고 있음.

---

## 이슈 4: RTP 전송 관점 분석

### 전체 패킷 통계

| 항목 | 값 |
|------|-----|
| 총 패킷 | 7,272개 |
| media 패킷 | 2,500개 |
| silence 패킷 | 4,772개 |
| 전체 interval 평균 | 20ms (G.711 정상) |
| media interval 최대 | **23.6ms** |
| silence interval 최대 | **178.5ms** (1건) |
| 200ms 초과 갭 | **0건** |

### TTS 송출 구간 vs CDR 대조

| 구간 | RTP media 시작 | RTP media 종료 | 재생 시간(추정) | CDR tts_pushed | 대응 발화 |
|------|---------------|---------------|----------------|----------------|-----------|
| [0] | 10:16:43.525 | 10:16:58.380 | ~14.88s | 10:16:42.339 + 10:16:46.142 | 인사 phase1+2 |
| [1] | 10:17:11.380 | 10:17:24.459 | ~13.10s | 10:17:10.497 | seq1 응답 |
| [2] | 10:17:36.779 | 10:17:45.919 | ~9.16s | 10:17:35.780 | seq2 응답 |
| [3] | 10:18:00.398 | 10:18:08.658 | ~8.28s | 10:17:59.508 | seq3 응답 |
| [4] | 10:18:30.137 | 10:18:34.697 | ~4.58s | 10:18:29.337 | seq4 JSON 응답 |

**CDR tts_pushed → RTP media 시작 지연 (모든 구간)**:

| 구간 | tts_pushed | media 시작 | 지연 |
|------|-----------|------------|------|
| seq1 | 10:17:10.497 | 10:17:11.380 | **0.88s** |
| seq2 | 10:17:35.780 | 10:17:36.779 | **0.99s** |
| seq3 | 10:17:59.508 | 10:18:00.398 | **0.89s** |
| seq4 | 10:18:29.337 | 10:18:30.137 | **0.80s** |

→ TTS API 호출 → 오디오 수신 → RTP 패킷화까지 약 **0.8~1.0s** 고정 지연. 정상 범위.

### RTP 품질 평가

| 항목 | 평가 | 비고 |
|------|------|------|
| 패킷 간격 안정성 | ✅ 양호 | media avg=20ms ±3ms, G.711 20ms 규격 준수 |
| 대형 갭 (>200ms) | ✅ 없음 | 끊김 없음 |
| silence 178ms 갭 | ⚠ 경미 | 10:17:05.914 seq=35243, STT 처리 직후 1회 발생 |
| queue_depth | ✅ 0 유지 | 버퍼 적재 없음, 실시간 송출 |
| seq4 media 재생 시간 | ⚠ 4.58s | JSON 텍스트를 TTS로 읽은 시간 (약 52자 × JSON 구문 포함) |

### seq 4 JSON TTS 재생 확인

RTP 구간 [4] `10:18:30.137 ~ 10:18:34.697` (4.58초)에서
`{"intent": "chitchat", "search_query": "꽃이 많이 폈더라고"}` 52자가 실제로 음성 송출됨.
고객이 이 JSON 문자열을 음성으로 들었을 것으로 확인.

---

## 수정 사항

### 즉시 수정 필요 (코드)

#### 1. `_strip_json_and_markdown_for_tts()` 메타 전용 JSON 처리 추가

```python
# generate_response.py
# JSON은 있지만 'response' 키가 없고 'intent'/'search_query' 같은 메타 키만 있는 경우
META_ONLY_KEYS = {"intent", "search_query", "query", "action", "category"}
if isinstance(data, dict) and not data.get("response"):
    data_keys = set(data.keys())
    if data_keys and data_keys.issubset(META_ONLY_KEYS | {"confidence", "slots"}):
        logger.warning("tts_response_meta_json_blocked", keys=list(data_keys))
        return ""  # 빈 문자열 → 상위에서 fallback 멘트 사용
```

#### 2. chitchat 발화 키워드 확장 (`classify_intent.py`)

계절/날씨 감상 잡담 패턴을 chitchat에 추가:

```python
"chitchat": [
    ...,
    # 계절/자연 감상 잡담
    "꽃이", "벚꽃", "단풍", "봄이", "여름이", "가을이", "겨울이",
    "날씨 좋다", "날씨 좋네", "날씨가 좋", "날씨 참",
    "춥네", "덥네", "선선하", "따뜻하", "쌀쌀하",
],
```

---

## 요약

| 번호 | 이슈 | 심각도 | 수정 상태 |
|------|------|--------|-----------|
| 1 | seq4 agent_graph 11.176s (chitchat → question 오분류) | 🔴 높음 | 키워드 추가 필요 |
| 2 | seq4 JSON `{"intent":...}` TTS 송출 | 🔴 높음 | `_strip_json_and_markdown_for_tts` 수정 필요 |
| 3 | step_back 2.6s 낭비 (chitchat 발화에 RAG 추가 검색) | 🟡 중간 | 오분류 수정 시 자동 해결 |
| 4 | generate_response 6.9s (무관 컨텍스트) | 🟡 중간 | 오분류 수정 시 자동 해결 |
| 5 | RTP silence 178ms 갭 (10:17:05, seq=35243) | 🟢 낮음 | 1회성, 모니터링 |
| 6 | TTS → RTP 지연 0.8~1.0s | 🟢 낮음 | TTS API cold 정상 범위 |
