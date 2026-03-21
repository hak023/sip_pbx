# AI 응대 긴급 개선 작업 진행 상황

## 📋 개요

**작성일**: 2026-03-10  
**목적**: AI 응대 테스트에서 발견된 긴급 문제 해결  
**관련 문서**: `AI_CALL_TEST_LOG_ANALYSIS.md`

---

## ✅ 완료된 작업

### 1. VAD/Barge-in 로깅 추가 (진행중)

**파일**: `sip-pbx/src/ai_voicebot/pipecat/processors/vad_wrapper.py` (신규 생성)

**구현 내용**:
- VAD 프로세서를 래핑하는 `VADWrapperProcessor` 클래스 생성
- 음성 감지 시작/종료 상세 로깅
- Barge-in 이벤트 로깅
- VAD 상태 추적 및 통계

**주요 로그**:
```python
logger.info("vad_speech_started", ...)  # 👤 사용자 음성 감지 시작
logger.info("vad_speech_stopped", ...)  # 👤 음성 종료 → STT 처리
logger.warning("vad_barge_in_start", ...)  # 🛑 TTS 중단
logger.info("vad_barge_in_stop", ...)  # ▶️ TTS 재개 가능
```

**Pipeline 통합**:
- `sip-pbx/src/ai_voicebot/pipecat/pipeline_builder.py` 수정
- `wrap_vad_with_logging()` 함수로 VAD 래핑
- 모든 VAD 이벤트가 이제 로그에 기록됨

**예상 효과**:
- VAD 작동 여부 실시간 모니터링
- Barge-in 실패 원인 파악 가능
- STT 16초 지연 문제의 root cause 진단 가능

---

## 🔄 진행 중인 작업

### 2. LLM rewrite_query 최적화

**현재 상황**:
- rewrite_query는 LangGraph Agent 내부에서 실행 (외부 패키지)
- 직접 수정이 어려움

**계획된 최적화 방안**:

#### A. 간단한 query rewrite 스킵
```python
def should_skip_rewrite(query: str) -> bool:
    """간단한 query는 rewrite 스킵"""
    # 짧은 query
    if len(query) < 15:
        return True
    
    # 특정 패턴 (직접적인 질문)
    if any(keyword in query for keyword in ["날씨", "예보", "기온", "강수", "특보"]):
        return True
    
    return False

# Agent 호출 전 체크
if should_skip_rewrite(user_text):
    # rewrite 스킵하고 바로 RAG 검색
    pass
```

#### B. 병렬 처리
```python
# classify_intent와 rewrite_query를 동시 실행
intent_task = asyncio.create_task(agent.classify_intent(query))
rewrite_task = asyncio.create_task(agent.rewrite_query(query))

intent, rewritten = await asyncio.gather(intent_task, rewrite_task)
# 시간 절약: 3.5초 + 5.2초 = 8.7초 → max(3.5, 5.2) = 5.2초
```

#### C. 캐싱
```python
# 자주 나오는 query는 미리 캐싱
COMMON_REWRITES = {
    "오늘의 날씨를 알려주세요": "오늘의 날씨 정보",
    "내일 날씨 어때요": "내일의 날씨 정보",
    "비 올까요": "강수 확률 정보",
    # ...
}
```

### 3. RTP 초기 타이밍 안정화

**문제**:
- PCM 큐 대기 시간: 709ms (목표: 100ms)
- RTP base_time 초기화 시점 문제

**계획된 개선**:

#### A. RTP base_time 초기화 개선
```python
# 현재: 첫 패킷 전송 시 base_time 설정
if not hasattr(self, '_rtp_base_time') or self._rtp_base_time is None:
    self._rtp_base_time = time.perf_counter()

# 개선: PCM 큐에서 첫 데이터를 가져온 직후 설정
pcm_data = await asyncio.wait_for(self._pipecat_pcm_queue.get(), timeout=1.0)
if self._rtp_base_time is None:
    self._rtp_base_time = time.perf_counter()
    logger.info("rtp_base_time_initialized",
               call_id=self.media_session.call_id,
               note="첫 PCM 데이터 수신 시점으로 base_time 설정")
```

#### B. Transport Output 처리 속도 개선
- TTS 오디오 프레임을 받으면 즉시 PCM 큐에 넣기
- 중간 버퍼링 제거

### 4. LLM 처리 중 대기 안내 메시지

**구현 계획**:

#### A. RAG Processor에 대기 메시지 추가
```python
# rag_processor.py
async def _process_with_agent(self, user_text: str):
    # ✅ LLM 처리 시작 알림
    await self.push_frame(TextFrame(text="잠시만 기다려 주세요..."))
    
    # LLM 호출 (19초)
    agent_start = time.time()
    result = await self._agent.process_utterance(user_text, ...)
    agent_elapsed = time.time() - agent_start
    
    # 응답 처리
    response = result.get("response", "")
    await self.push_frame(TextFrame(text=response))
```

#### B. 타임아웃 처리
```python
# 5초 이상 걸리면 중간 안내
async def _process_with_agent_with_timeout(self, user_text: str):
    done = asyncio.Event()
    
    async def wait_and_notify():
        await asyncio.sleep(5.0)
        if not done.is_set():
            await self.push_frame(TextFrame(text="정보를 찾고 있습니다..."))
    
    notify_task = asyncio.create_task(wait_and_notify())
    
    try:
        result = await self._agent.process_utterance(user_text, ...)
    finally:
        done.set()
        notify_task.cancel()
    
    return result
```

### 5. DB Client 설정

**문제**:
```json
{"event": "DB client not configured, skipping RAG logging"}
```

**해결 방법 A: DB Client 설정** (권장)
```python
# main.py 또는 factory.py
from src.ai_voicebot.ai_pipeline.ai_logger import get_ai_logger
from src.database import get_database_client

# DB 클라이언트 생성
db_client = get_database_client()

# AI Logger에 주입
ai_logger = get_ai_logger()
ai_logger.set_db_client(db_client)

logger.info("ai_logger_db_client_configured")
```

**해결 방법 B: 로깅 비활성화** (간단)
```python
# ai_logger.py
class AILogger:
    def log_rag_search(...):
        if not self._db_client:
            # ⚠️ 경고 대신 debug 레벨로 변경
            logger.debug("DB client not configured, skipping RAG logging")
            return
```

---

## 📊 예상 개선 효과

| 개선 사항 | 현재 | 목표 | 예상 효과 |
|---------|------|------|----------|
| **VAD 로깅** | 없음 | 상세 | STT 지연 원인 파악 |
| **rewrite_query** | 5.2초 | 1초 | -81% |
| **RTP 초기 지연** | 709ms | 100ms | -86% |
| **LLM 대기 안내** | 침묵 19초 | 안내 메시지 | UX 개선 |
| **DB Client** | 경고 | 정상 | 로그 정리 |

---

## 🎯 다음 단계

### 즉시 테스트 가능 (VAD 로깅)

1. **서버 재시작**:
   ```bash
   # 변경사항 적용
   cd sip-pbx
   python -m src.main
   ```

2. **AI 통화 테스트**:
   - 1003 → 1004 통화
   - AI 인사말 중 말 걸기 (barge-in 테스트)
   - "오늘의 날씨를 알려주세요" 질문

3. **로그 확인**:
   ```bash
   # VAD 이벤트 확인
   Select-String -Path "sip-pbx/logs/app.log" -Pattern "vad_speech_|vad_barge_in"
   
   # STT 인식 시간 확인
   Select-String -Path "sip-pbx/logs/app.log" -Pattern "timing_stt_final_to_rag"
   ```

### 추가 구현 필요

4. **rewrite_query 최적화** 적용
5. **RTP 타이밍 안정화** 적용
6. **LLM 대기 안내** 추가
7. **DB Client 설정** 또는 경고 제거

---

## 📝 TODO 업데이트

- [x] VAD 래퍼 프로세서 생성
- [x] Pipeline에 VAD 래퍼 통합
- [ ] 테스트 및 로그 분석
- [ ] rewrite_query 최적화 코드 작성
- [ ] RTP 타이밍 개선 코드 작성
- [ ] LLM 대기 안내 메시지 추가
- [ ] DB Client 설정 또는 경고 제거

---

**작성자**: AI Assistant  
**상태**: 진행 중 (VAD 로깅 완료, 테스트 대기)
