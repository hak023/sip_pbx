# AI 응대 테스트 로그 분석 보고서

## 📋 개요

**작성일**: 2026-03-10  
**통화 ID**: `0IBsHSliVK`  
**테스트 시나리오**: AI 인사말 → 사용자 질문("오늘의 날씨를 알려주세요") → AI 응답  
**로그 파일**: `sip-pbx/logs/app.log`

---

## 🔍 문제점 분석

### 1. ⚠️ AI 인사말 TTS/RTP 전송 문제

#### 타임라인 분석

```
17:40:39.781 - AI 통화 연결 시작
17:40:40.154 - Caller RTP 첫 패킷 수신
17:40:40.156 - TTS 첫 오디오 청크 수신 ✅
17:40:40.531 - TTS 텍스트 입력: "안녕하세요." (6자)
17:40:40.531 - PCM 큐 대기 시간: 709.2ms ⚠️ (너무 김!)
17:40:41.318 - RTP 간격 위반 시작 (1차)
17:40:48.468 - Phase2 인사말 완료 (전체 8.07초)
```

#### 문제점

**1.1 PCM 큐 대기 시간 과도**
```json
{
  "timestamp": "2026-03-10T17:40:40.531",
  "event": "pcm_queue_wait_time",
  "wait_ms": 709.2,  // ⚠️ 700ms 이상 대기!
  "queue_size_before": 1
}
```

**원인**:
- TTS가 첫 오디오를 생성한 시점(`17:40:40.156`)과 PCM 큐에 넣은 시점(`17:40:40.531`) 사이에 **375ms 지연**
- RTP 발송 루프가 첫 PCM 데이터를 가져올 때까지 **709ms 대기**
- 총 1초 이상의 초기 지연 발생

**1.2 TTS 생성과 RTP 전송 타이밍 불일치**

```
17:40:40.156 - TTS 첫 오디오 수신
17:40:40.531 - "안녕하세요." 텍스트 → TTS 입력
17:40:40.531 - PCM 큐에서 709ms 대기 후 첫 RTP 전송 시작
```

**문제**: "안녕하세요."가 TTS 입력된 시점보다 **먼저** 오디오가 수신되었다는 로그 순서 모순
- 이는 Phase 1 인사말("안녕하세요.")과 Phase 2 인사말("저는 날씨 예보...") 로그가 섞인 것으로 추정

**1.3 RTP 간격 위반 다수 발생**

```json
// 초반 간격 위반 (첫 5개 패킷)
{
  "timestamp": "2026-03-10T17:40:41.318",
  "actual_ms": 7.8,    // ⚠️ 목표: 20ms
  "expected_ms": 20,
  "timing_error_ms": -10.34,
  "violation_count": 1
},
{
  "actual_ms": 14.0,   // ⚠️
  "timing_error_ms": -16.38,
  "violation_count": 2
},
{
  "actual_ms": 41.7,   // ⚠️ 너무 김!
  "timing_error_ms": 5.3,
  "violation_count": 3
},
{
  "actual_ms": 0.6,    // ⚠️ 너무 짧음!
  "timing_error_ms": -14.11,
  "violation_count": 4
}
```

**원인**:
- 절대 시간 기반 스케줄링을 적용했으나 초기 타이밍이 불안정
- PCM 큐 대기 시간(709ms)으로 인해 RTP base_time이 왜곡됨
- 첫 몇 개 패킷의 타이밍이 매우 불규칙 (0.6ms ~ 41.7ms)

#### 개선 방안

**1. PCM 큐 대기 시간 단축**
- TTS가 오디오를 생성하면 즉시 PCM 큐에 넣도록 보장
- Pipecat Pipeline의 Transport Output 처리 속도 개선
- 초기 버퍼링 로직 최적화

**2. RTP base_time 초기화 개선**
```python
# 현재: 첫 패킷 전송 시 base_time 설정
if not hasattr(self, '_rtp_base_time') or self._rtp_base_time is None:
    self._rtp_base_time = time.perf_counter()

# 개선: PCM 큐에서 첫 데이터를 가져온 직후 설정
pcm_data = await asyncio.wait_for(self._pipecat_pcm_queue.get(), timeout=1.0)
if self._rtp_base_time is None:
    self._rtp_base_time = time.perf_counter()
    logger.info("rtp_base_time_set", base_time=self._rtp_base_time)
```

**3. 초기 몇 개 패킷에 대한 타이밍 안정화**
- 첫 5-10개 패킷은 타이밍 보정을 더 엄격하게 적용
- `asyncio.sleep()` 대신 busy-wait + sleep 조합 사용

---

### 2. 🐌 STT 인식 지연 (24초 이상!)

#### 타임라인 분석

```
17:40:40.154 - Caller 음성 첫 RTP 패킷 수신 ✅
17:40:40.154~17:40:56.xxx - Caller 음성 계속 수신 중...
17:41:05.255 - STT 최종 결과 도달: "오늘의 날씨를 알려주세요." ⚠️ (25초 후!)
```

**문제**: 사용자가 말을 시작한 시점(`17:40:40.154`)부터 STT 최종 인식까지 **25.1초** 소요!

#### 원인 분석

**2.1 VAD(Voice Activity Detection) 지연**

로그에서 VAD 관련 이벤트가 보이지 않음:
- `vad_speech_start` (음성 시작 감지) 없음
- `vad_speech_end` (음성 종료 감지) 없음
- `StartInterruptionFrame` (barge-in) 없음

**추정**: 
- VAD가 인사말 TTS 중 caller 음성을 감지하지 못함
- Barge-in이 작동하지 않아 인사말이 모두 끝난 후에야 STT 처리 시작
- 인사말 Phase 2가 `17:40:48.468`에 완료되었으므, 그 이후에야 STT 활성화

**2.2 STT 큐 적체**

```json
{
  "timestamp": "2026-03-10T17:40:40.531~17:40:40.750",
  "stt_queue_size": 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7
}
```

- Caller 음성이 계속 들어오는데 STT 큐가 빠르게 증가
- 하지만 STT가 실제로 처리를 시작하지 않음 (최종 결과 없음)

**2.3 Google STT API 처리 지연**

로그에서 STT API 호출 관련 로그 없음:
- `stt_request_sent` 없음
- `stt_response_received` 없음
- `stt_interim_result` (중간 결과) 없음

**추정**: 
- VAD가 음성 종료를 감지하지 못해 STT API 호출이 지연됨
- 또는 TTS 송출 중 STT가 비활성화되어 있음

#### 개선 방안

**1. VAD 로깅 강화**
```python
# src/ai_voicebot/vad/vad_detector.py
async def process_frame(self, frame):
    if is_speech:
        logger.info("vad_speech_detected", 
                   call_id=self._call_id,
                   duration_ms=...,
                   note="음성 감지 시작")
    elif was_speech:
        logger.info("vad_speech_ended",
                   call_id=self._call_id,
                   duration_ms=...,
                   note="음성 감지 종료 → STT 전송")
```

**2. Barge-in 활성화 확인**
```python
# pipeline_builder.py에서 VAD 설정 확인
vad_config = {
    "enable_barge_in": True,  # ✅ 반드시 활성화
    "speech_threshold": 0.5,
    "min_speech_duration_ms": 300,
    "silence_duration_ms": 500
}
```

**3. STT 처리 타임아웃 설정**
```python
# Google STT 설정에 타임아웃 추가
stt_config = {
    "interim_results": True,  # 중간 결과 활성화
    "single_utterance": False,  # 연속 인식
    "max_alternatives": 1,
    "speech_contexts": [...],
    "timeout_ms": 5000  # 5초 타임아웃
}
```

---

### 3. ⚠️ RTP 간격 위반 (rtp_interval_violation)

#### 통계

```
총 위반 횟수: 1,300회 이상
총 전송 패킷: 1,504개
위반 비율: 86.5% ⚠️
```

#### 주요 패턴

**3.1 초반 불안정 (패킷 1-10)**
```
actual_ms: 7.8, 14.0, 41.7, 0.6, 39.5, ...
목표: 20ms
```
- 초기 타이밍이 매우 불규칙
- PCM 큐 대기 시간(709ms) 영향

**3.2 중반 안정화 (패킷 11-800)**
```
actual_ms: 32.7, 13.0, 9.8, ...
timing_error_ms: -2.55 ~ -17.42
```
- 상대적으로 안정화되었으나 여전히 오차 존재
- 누적 오차는 -2ms ~ -17ms 범위

**3.3 LLM 처리 중 극심한 지연 (패킷 800-1200)**
```
{
  "timestamp": "2026-03-10T17:41:25.048",
  "actual_ms": 27717.2,  // ⚠️ 27.7초!
  "expected_ms": 20,
  "timing_error_ms": 27700.35,
  "violation_count": 600
}
```

**원인**:
- LLM 처리 중 RTP 전송이 완전히 중단됨
- `17:41:05.255` (STT 인식) ~ `17:41:24.631` (TTS 시작) 사이 **19.4초 동안 RTP 전송 없음**
- 이 기간 동안 사용자는 침묵만 들음 (매우 나쁜 UX!)

#### 개선 방안

**1. LLM 처리 중 대기 음악/소리 재생**
```python
# rag_processor.py에서 LLM 호출 전
async def _process_with_agent(self, user_text: str):
    # LLM 처리 시작 알림
    await self.push_frame(TextFrame(text="잠시만 기다려 주세요..."))
    
    # 또는 대기 음악 재생
    # await self._play_hold_music()
    
    # LLM 호출
    response = await self._agent.process_utterance(...)
```

**2. RTP 타이밍 오차 누적 리셋**
```python
# LLM 처리 완료 후 RTP base_time 리셋
if timing_error_ms > 1000:  # 1초 이상 오차
    logger.warning("rtp_timing_drift_reset",
                  old_error=timing_error_ms,
                  note="누적 오차가 크므로 base_time 리셋")
    self._rtp_base_time = time.perf_counter()
    self._rtp_packets_sent_total = 0
```

**3. asyncio.sleep 정확도 개선**
```python
# 짧은 sleep은 busy-wait 사용
if sleep_needed < 0.005:  # 5ms 미만
    while time.perf_counter() < target_time:
        pass  # busy-wait
else:
    await asyncio.sleep(sleep_needed * 0.95)  # 95%만 sleep
    while time.perf_counter() < target_time:  # 나머지 busy-wait
        pass
```

---

### 4. ⚠️ DB Client 미설정 경고

```json
{
  "timestamp": "2026-03-10T17:41:20.502",
  "level": "warning",
  "event": "DB client not configured, skipping RAG logging"
},
{
  "event": "DB client not configured, skipping knowledge match logging"
}
```

#### 문제

- RAG 검색 결과가 데이터베이스에 저장되지 않음
- Knowledge match 로그가 누락되어 AI 학습/개선에 활용 불가

#### 원인

```python
# src/ai_voicebot/ai_pipeline/ai_logger.py
class AILogger:
    def __init__(self):
        self._db_client = None  # ⚠️ 미설정
    
    def log_rag_search(...):
        if not self._db_client:
            logger.warning("DB client not configured, skipping RAG logging")
            return
```

#### 개선 방안

**1. DB Client 설정**
```python
# main.py 또는 factory.py에서
from src.ai_voicebot.ai_pipeline.ai_logger import get_ai_logger
from src.database import get_database_client

ai_logger = get_ai_logger()
db_client = get_database_client()
ai_logger.set_db_client(db_client)
```

**2. 또는 로깅 비활성화 (불필요 시)**
```yaml
# config/config.yaml
ai:
  logging:
    enable_db_logging: false  # DB 로깅 비활성화
```

---

### 5. 🐌 LLM 처리 시간 지연 (19.4초!)

#### 타임라인

```
17:41:05.255 - STT 인식: "오늘의 날씨를 알려주세요."
17:41:08.760 - classify_intent 완료 (3.493s) ✅
17:41:20.377 - rewrite_query 완료 (5.228s) ⚠️
17:41:20.502 - RAG 검색 완료 (0.125s) ✅
17:41:24.444 - generate_response 완료 (3.942s) ✅
17:41:24.527 - LangGraph 전체 완료 (19.260s) ⚠️
17:41:24.631 - TTS 텍스트 전달 (19.358s total)
```

#### 문제점

**5.1 rewrite_query LLM 호출이 가장 느림 (5.228초)**

```json
{
  "timestamp": "2026-03-10T17:41:20.377",
  "event": "⏱️ [TIMING] rewrite_query (LLM)",
  "elapsed": "5.228s",  // ⚠️ 가장 느림!
  "original": "오늘의 날씨를 알려주세요.",
  "rewritten": "오늘의 날씨 정보"
}
```

**원인**:
- Query rewriting에 5.2초나 소요
- 이는 간단한 텍스트 변환에 비해 매우 느림
- Gemini API 호출 지연 또는 네트워크 문제 의심

**5.2 전체 LangGraph 처리 시간 과도 (19.26초)**

```
classify_intent:   3.493s (18%)
rewrite_query:     5.228s (27%) ⚠️ 가장 큼!
RAG search:        0.125s (1%)
generate_response: 3.942s (20%)
기타 오버헤드:      6.472s (34%) ⚠️
```

**기타 오버헤드 6.5초**는:
- Agent state 관리
- Memory 로딩/저장
- 로깅 및 모니터링
- Python asyncio 스케줄링

#### 개선 방안

**1. rewrite_query 최적화**

```python
# Option 1: 간단한 query는 rewrite 스킵
if len(query) < 20 and is_simple_query(query):
    logger.info("rewrite_query_skipped", reason="simple_query")
    rewritten_query = query
else:
    rewritten_query = await llm.rewrite_query(query)

# Option 2: rewrite_query를 더 작은 모델로 처리
rewrite_llm = LLMClient(model="gemini-1.5-flash")  # 더 빠른 모델
```

**2. LLM 호출 병렬 처리**

```python
# classify_intent와 rewrite_query를 병렬로
intent_task = asyncio.create_task(llm.classify_intent(query))
rewrite_task = asyncio.create_task(llm.rewrite_query(query))

intent, rewritten_query = await asyncio.gather(intent_task, rewrite_task)
# 시간 절약: 3.493 + 5.228 = 8.721s → max(3.493, 5.228) = 5.228s
```

**3. Gemini API 타임아웃 설정**

```python
# llm_client.py
class LLMClient:
    def __init__(self, ..., timeout=5.0):
        self.timeout = timeout
    
    async def generate_simple(self, prompt, ...):
        try:
            response = await asyncio.wait_for(
                self._model.generate_content_async(prompt),
                timeout=self.timeout
            )
        except asyncio.TimeoutError:
            logger.error("llm_timeout", prompt_len=len(prompt))
            return fallback_response
```

**4. 캐싱 활용**

이미 semantic_cache가 있지만 더 공격적으로:
```python
# 자주 나오는 질문은 미리 캐싱
common_questions = {
    "오늘의 날씨": "오늘의 날씨 정보",
    "내일 날씨": "내일의 날씨 정보",
    # ...
}

if query in common_questions:
    rewritten_query = common_questions[query]
    logger.info("rewrite_query_cached", elapsed="0.001s")
```

---

## 📊 종합 타이밍 분석

### 전체 통화 흐름

```
17:40:39.781  통화 연결
↓ 0.4초
17:40:40.154  Caller 첫 RTP 수신
↓ 0.7초 (PCM 큐 대기)
17:40:40.531  첫 RTP 전송 시작
↓ 8초 (인사말 Phase 1 + 2)
17:40:48.468  인사말 완료
↓ 16.8초 (VAD 대기 + STT 처리)
17:41:05.255  STT 인식 완료 ⚠️
↓ 19.4초 (LLM 처리)
17:41:24.631  TTS 시작 ⚠️
↓ 2.5초 (TTS 재생)
17:41:27.xxx  응답 완료
```

### 문제 구간

| 구간 | 시간 | 목표 | 비고 |
|------|------|------|------|
| 통화 연결 → 인사말 | 0.7초 | < 0.3초 | ⚠️ PCM 큐 대기 |
| 인사말 재생 | 8.0초 | 정상 | ✅ |
| 인사말 → STT 인식 | 16.8초 | < 2초 | 🚨 VAD 미작동 |
| STT → LLM 완료 | 19.4초 | < 5초 | 🚨 너무 느림 |
| LLM → TTS 시작 | 0.1초 | < 0.1초 | ✅ |

**총 응답 시간**: 45초 (목표: 10초 이내)

---

## ✅ 우선순위 개선 과제

### 🔴 긴급 (Critical)

1. **VAD/Barge-in 수정** (STT 16초 지연 해결)
   - VAD 로깅 추가
   - Barge-in 설정 확인
   - TTS 중 STT 활성화 확인

2. **LLM rewrite_query 최적화** (5.2초 → 1초)
   - 간단한 query는 rewrite 스킵
   - 더 빠른 모델 사용
   - 병렬 처리

3. **RTP 초기 타이밍 안정화** (PCM 큐 709ms → 100ms)
   - Transport Output 처리 속도 개선
   - RTP base_time 초기화 개선

### 🟡 중요 (High)

4. **LLM 처리 중 대기 안내**
   - "잠시만 기다려 주세요" 메시지
   - 또는 대기 음악 재생

5. **RTP 간격 위반 최소화** (86% → 10%)
   - asyncio.sleep + busy-wait 조합
   - 누적 오차 1초 이상 시 리셋

6. **DB Client 설정**
   - RAG 로깅 활성화
   - 또는 경고 로그 제거

### 🟢 일반 (Medium)

7. **LLM 호출 병렬화**
   - classify_intent + rewrite_query 동시 실행

8. **Gemini API 타임아웃 설정**
   - 5초 타임아웃
   - Fallback 응답 준비

---

## 📝 다음 단계

1. VAD/Barge-in 로깅 추가 및 테스트
2. LLM rewrite_query 최적화 적용
3. RTP 초기 타이밍 개선
4. 재테스트 및 로그 분석
5. 개선 결과 비교 (목표: 총 응답 시간 45초 → 10초)

---

**작성자**: AI Assistant  
**검토자**: (사용자 검토 필요)
