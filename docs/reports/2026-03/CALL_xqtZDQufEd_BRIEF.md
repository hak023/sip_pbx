# call_id: xqtZDQufEd 통화 분석 리포트

**작성일**: 2026-03-16  
**통화 시각**: 2026-03-16 19:22:11 ~ 19:24:05  
**발신자**: 1003  
**착신자**: 1004  
**AI 응대 여부**: O (No Answer Timeout 후 AI 전환)

---

## 📌 요약

| 항목 | 내용 |
|------|------|
| 통화 시작 | 19:22:11 |
| AI 전환 시각 | 19:22:21 (No Answer Timeout 10초) |
| 첫 TTS 출력 | 19:22:22.527 (AI 전환 후 약 1.5초) |
| 첫 사용자 RTP | 19:22:22.523 |
| 통화 종료 | 19:24:05 (약 1분 54초) |
| Transcript 저장 | recordings\20260316_192211_1003_to_1004\transcript.txt |

---

## 🔍 주요 문제점

### 1. **지식베이스 인사말이 실제 AI 응대에 반영되지 않음** ❌

#### 현상
- **지식베이스 데이터** (사용자 제공 이미지 참조):
  - `kb_0846118cd7084548`: "안녕하세요 AI입니다."
  - `kb_416d6c8d32d74ce6`: "날씨가 궁금하시군요? 환영합니다"

- **실제 AI 응답** (로그 분석):
  ```
  19:22:22.717 - TTS: "안녕하세요."
  19:22:23.477 - TTS: "안녕하세요."
  19:22:23.477 - TTS: "기상청 AI 통화 비서입니다."
  19:22:24.127 - TTS: "기상청 AI 통화 비서입니다."
  ```

- **Transcript 결과**:
  ```
  착신자: 안녕하세요 기 상 청 ai 통합 비 서 입니다 무엇을 도와 드릴 까요 
          어떤 내용이 궁금 하시면 편하게 말씀 해 주세요 정보를 찾 고 있습니다 잠시만
  ```

#### 원인 분석

##### 1.1 로그 기반 추적

```json
// 19:22:22.568 - send_greeting 진입
{"event": "send_greeting_started", "owner": "1004"}

// TTS 출력 (KB 데이터와 불일치)
{"event": "tts_text_input", "text_chunk_0": "안녕하세요."}
{"event": "tts_text_input", "text_chunk_0": "기상청 AI 통화 비서입니다."}
```

##### 1.2 지식베이스 검색 로그 누락

`send_greeting_started` 이벤트 후:
- **RAG 검색 로그 없음**: `rag_search_completed`, `search_knowledge`, `kb_search` 등 이벤트가 전혀 발생하지 않음
- **Embedder 로그 없음**: 지식베이스 쿼리를 위한 임베딩 생성 로그 없음

##### 1.3 RAG Engine 설계 검토

`rag_engine.py` (Line 64):
```python
INTENT_CATEGORY_MAP = {
    "greeting": ["greeting_phase1", "greeting_phase2"],
    ...
}
```

- RAG는 `intent="greeting"`일 때 `category: greeting_phase1`, `greeting_phase2`로 필터링
- 하지만 **실제 KB 데이터의 category는 다름**:
  - `kb_0846118cd7084548`: category가 **"인사 (시작)"**으로 추정 (이미지 기준)
  - **Category 불일치로 검색 실패 가능성 높음**

##### 1.4 Hardcoded Greeting 의심

로그에서 확인된 "기상청 AI 통화 비서입니다" 문구:
- KB에는 존재하지 않는 텍스트
- 코드 내 하드코딩된 인사말일 가능성:
  ```python
  # 추정되는 코드 (실제 확인 필요)
  phase1_text = "안녕하세요."
  phase2_text = f"{org_name} 통화 비서입니다. 무엇을 도와 드릴까요? ..."
  ```

##### 1.5 결론

**지식베이스 인사말이 전혀 조회되지 않았으며, 하드코딩된 기본 인사말이 사용됨**

#### 권장 조치

1. **RAG 검색 로직 강화**:
   - `send_greeting()` 함수에서 KB 검색 전·후 로그 추가:
     ```python
     logger.info("kb_greeting_search_start", owner=owner, category="greeting_phase1")
     results = await rag_engine.search("", owner_filter=owner, intent="greeting", ...)
     logger.info("kb_greeting_search_done", results_count=len(results), top_text=results[0].text if results else "")
     ```

2. **Category 매핑 수정**:
   - KB 데이터의 실제 category 확인 후 `INTENT_CATEGORY_MAP["greeting"]` 업데이트
   - 또는 KB 데이터의 category를 `greeting_phase1`/`greeting_phase2`로 통일

3. **Fallback 로직 명시화**:
   - KB 검색 실패 시 hardcoded greeting 사용 로그:
     ```python
     if not greeting_results:
         logger.warning("kb_greeting_not_found_using_hardcoded", owner=owner)
     ```

---

### 2. **Transcript 품질 문제 (별도 수정 완료)** ⚠️

#### 현상
```
착신자: 안녕하세요 기 상 청 ai 통합 비 서 입니다
```
→ 단어 간 불필요한 공백 발생 (STT 결과 후처리 개선 필요)

#### 조치
- **이전 요청에서 이미 수정 완료** (`sip_call_recorder.py` 발화 그룹화 로직 개선)
- 본 건과는 별개 이슈

---

## 📊 타임라인 분석

| 시각 | 이벤트 | 세부 내용 |
|------|--------|-----------|
| 19:22:11.638 | INVITE 수신 | 1003 → 1004 |
| 19:22:11.648 | Call Setup | B2BUA 모드 시작 |
| 19:22:11.655 | RTP Relay 시작 | Caller/Callee 포트 할당 |
| 19:22:11.662 | 녹음 시작 | `recordings\20260316_192211_1003_to_1004\` |
| 19:22:21.668 | **AI Takeover** | No Answer Timeout (10초) |
| 19:22:21.671 | AI Mode 활성화 | Pipecat 파이프라인 시작 |
| 19:22:22.089 | Pipeline 준비 완료 | Processor chain 구성 |
| 19:22:22.523 | **첫 Caller RTP** | 사용자 음성 입력 시작 |
| 19:22:22.568 | **send_greeting 진입** | Phase1/2 인사말 생성 시작 |
| 19:22:22.717 | **Phase1 TTS** | "안녕하세요." |
| 19:22:23.477 | **Phase2 TTS** | "기상청 AI 통화 비서입니다." |
| 19:22:24.595 | Phase1 TTS 완료 | 7.155초 오디오 |
| 19:22:24.851 | Phase1→Phase2 Gap | 2.95초 Sleep |
| 19:22:27.827 | **initial_greeting_sent** | 인사말 송출 완료 (총 5.259초) |
| 19:22:28.635 | Phase2 TTS 완료 | 3.4초 오디오 |
| 19:24:05.668 | Transcript 저장 | 211자, 9개 발화 |

---

## 🔬 기술적 세부 사항

### AI 파이프라인 구성
```python
processor_chain = [
    "transport.input()",
    "rec_input",
    "vad_wrapped",
    "stt",
    "rag_llm",  # ← 여기서 greeting 생성
    "tts",
    "tts_complete_notifier",
    "rec_output",
    "transport.output()"
]
```

### Phase1 인사말 특성
- **응답 시간**: AI 전환 후 약 1.5초
- **오디오 길이**: 7.155초
- **RTP 바이트**: 166,436 (예상 96,000, 실제 1.73배)
- **2문장 구성**: "안녕하세요." + "기상청 AI 통화 비서입니다. ..."

### Phase2 갭 타이밍
- **갭 시간**: 2.95초 (Phase1→Phase2 자연스러운 간격)
- **목적**: 사용자 반응 대기 + 바지인(Barge-in) 허용

---

## 🎯 권장 사항

### 즉시 조치 (High Priority)
1. ✅ **classify_intent 로그 강화** → 이미 완료 (llm_request_sent/received)
2. ✅ **generate_response 로그 강화** → 이미 완료 (llm_request_sent/received)
3. ✅ **step_back 로그 강화** → 이미 완료 (llm_request_sent/received)
4. ❌ **send_greeting KB 검색 로그 추가** → **미완료, 시급**

### 단기 개선 (Medium Priority)
- KB category 일관성 검증 (`greeting_phase1` vs 실제 데이터)
- Hardcoded greeting 제거 또는 명시적 fallback 처리
- `org_name` 추출 로직 개선 ("기상청 AI" → KB에서 조회)

### 장기 개선 (Low Priority)
- Greeting 개인화 (발신자별 맞춤 인사말)
- Phase2 동적 생성 (LLM 기반, 상황에 맞는 안내)

---

## 📋 체크리스트

### 문제 재현 단계
1. ✅ 1003 → 1004 통화
2. ✅ 10초 No Answer 대기
3. ✅ AI 전환 확인
4. ✅ 인사말 청취: "안녕하세요. 기상청 AI 통화 비서입니다. ..."
5. ❌ **KB 조회 로그 확인** → **누락됨**

### 디버깅 로그 수집
```bash
# send_greeting 함수 호출 추적
Select-String -Path "app.log" -Pattern "send_greeting|kb_greeting|greeting_phase"

# RAG 검색 (owner=1004, intent=greeting)
Select-String -Path "app.log" -Pattern "rag_search_completed.*greeting"

# Embedder 호출 (인사말 쿼리 임베딩)
Select-String -Path "app.log" -Pattern "embedder.*greeting"
```

### 예상 로그 (정상 케이스)
```json
{"event": "send_greeting_started", "owner": "1004"}
{"event": "kb_greeting_search_start", "category": "greeting_phase1"}
{"event": "rag_search_completed", "query": "", "results_count": 2, "top_doc_preview": "안녕하세요 AI입니다."}
{"event": "kb_greeting_found", "phase1_text": "안녕하세요 AI입니다.", "phase2_text": "날씨가 궁금하시군요? ..."}
{"event": "tts_text_input", "text_chunk_0": "안녕하세요 AI입니다."}
```

---

## 🔗 관련 파일

### 코드
- `src/ai_voicebot/ai_pipeline/rag_engine.py` (Line 64: INTENT_CATEGORY_MAP)
- `src/ai_voicebot/langgraph/nodes/classify_intent.py` ✅ 로그 추가 완료
- `src/ai_voicebot/langgraph/nodes/generate_response.py` ✅ 로그 추가 완료
- `src/ai_voicebot/langgraph/nodes/step_back_prompt.py` ✅ 로그 추가 완료
- `[미확인]` send_greeting() 함수 위치 (pipecat builder 또는 agent.py 예상)

### 데이터
- KB ID: `kb_0846118cd7084548` (owner=1004, category=?, text="안녕하세요 AI입니다.")
- KB ID: `kb_416d6c8d32d74ce6` (owner=1004, category=?, text="날씨가 궁금하시군요? 환영합니다")

### 로그
- `logs/app.log` (Line 1467-2004: call_id=xqtZDQufEd 전체 로그)
- `recordings/20260316_192211_1003_to_1004/transcript.txt` (9줄, 211자)

---

## 📌 결론

**call_id: xqtZDQufEd**는 정상적으로 AI 응대로 전환되었으나, **지식베이스에 등록된 인사말 데이터가 실제 응답에 반영되지 않았습니다**. 

로그 분석 결과:
- ✅ AI 전환, TTS 출력, 파이프라인 흐름은 정상
- ❌ **KB 검색 로그 완전 누락** → RAG 호출 자체가 없었거나 실패
- ❌ Hardcoded 기본 인사말 사용 → "기상청 AI 통화 비서입니다" (KB에 없는 텍스트)

**시급 조치**: `send_greeting()` 함수 내 RAG 검색 로직에 상세 로그 추가 후 재현 테스트 필요.
