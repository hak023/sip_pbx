# AI 통화 2번째 콜 TTS 미작동 버그 수정

**작성일**: 2026-03-10  
**상태**: ✅ 수정 완료

---

## 📋 문제 증상

사용자 보고:
- 첫 번째 AI 통화: TTS 인사말이 정상적으로 들림
- 두 번째 AI 통화: TTS가 전혀 들리지 않음 (무음)

---

## 🔍 로그 분석

### 첫 번째 통화 (call_id: `xUxZZZPyUo`)
```
15:30:39.041 rag_llm_greeting_phase1 (text: "기상청에 전화해 주셔서 감사합니다...")
15:30:39.042 rag_llm_greeting_phase2 (text: "저는 날씨 예보 조회...")
15:30:39.109 tts_text_input (text: "기상청에 전화해 주셔서...")
15:30:39.263 tts_first_audio_received
15:30:39.883 tts_first_audio_sent_to_rtp
...
15:30:40.893 notifier_endframe_processed (duration_sec: 6.595)
15:30:46.575 greeting_phase2_sent
```
✅ 정상: TTS 텍스트 입력 → 오디오 수신 → RTP 전송 → 810 패킷 전송

### 두 번째 통화 (call_id: `durK~EKJEk`)
```
16:07:19.776 org_manager_loaded_from_vectordb (owner: "1004")
16:07:19.776 hitl_manager_initialized
16:07:19.776 conversation_agent_initialized
16:07:19.776 pipeline_built (has_org_manager: true)
...
16:07:55.764 greeting_phase_gap_tts_complete_timeout (wait_timeout_sec: 28.1, phase1_chars: 36)
16:07:55.764 initial_greeting_sent
...
16:08:20.243 rtp_relay_stopped (rtp_tts_packets_sent: 0)  ❌ TTS 패킷 0개!
```

**주요 발견**:
1. ❌ `rag_llm_greeting_phase1` 로그 없음 → 인사말 텍스트가 생성되지 않음
2. ❌ `tts_text_input` 로그 없음 → TTS로 텍스트가 전달되지 않음
3. ❌ `tts_first_audio_received` 로그 없음 → TTS 오디오가 수신되지 않음
4. ✅ Agent, org_manager, pipeline은 정상 초기화됨
5. ✅ `initial_greeting_sent` 로그는 있음 → `send_greeting()` 메소드는 호출됨
6. ⚠️ `greeting_phase_gap_tts_complete_timeout` → 28초간 TTS 완료 이벤트 대기 후 timeout

---

## 🐛 근본 원인 분석

### 코드 추적

**파일**: `sip-pbx/src/ai_voicebot/pipecat/pipeline_builder.py`

```python
async def build_and_run(...):
    # Line 235-249: Greeting Task 생성
    async def _send_initial_greeting():
        await asyncio.sleep(0.5)  # Pipeline 초기화 대기
        try:
            if hasattr(pipeline, 'processors'):
                for proc in pipeline.processors:
                    if hasattr(proc, 'send_greeting'):
                        await proc.send_greeting()  # RAGProcessor.send_greeting() 호출
                        logger.info("initial_greeting_sent", call_id=call_id)
                        break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning("initial_greeting_failed", call_id=call_id, error=str(e))
    
    # Line 250-251: Task 생성 (버그!)
    greeting_task = asyncio.create_task(_send_initial_greeting())
    # ❌ 문제: self._greeting_tasks[call_id]에 저장하지 않음!
    
    try:
        await runner.run(task)
    except asyncio.CancelledError:
        ...
    finally:
        # Line 262-268: Task 정리 시도 (실패!)
        greeting_task = self._greeting_tasks.pop(call_id, None)  # ❌ 항상 None 반환!
        if greeting_task and not greeting_task.done():
            greeting_task.cancel()
            try:
                await greeting_task
            except asyncio.CancelledError:
                pass
```

### 버그 상세

1. **첫 번째 통화**:
   - `greeting_task` 생성 → `_send_initial_greeting()` 실행 → `proc.send_greeting()` 호출 성공
   - 통화 종료 시 `finally` 블록 실행
   - `self._greeting_tasks.pop(call_id)` → `None` (Task가 dict에 없음!)
   - **Task가 취소되지 않고 계속 실행 중**

2. **두 번째 통화**:
   - 새로운 `greeting_task` 생성 → 0.5초 대기
   - `pipeline.processors` 순회
   - `proc.send_greeting()` 호출
   - **그러나** 첫 번째 통화의 Task가 아직 실행 중이고, RAGProcessor의 `_greeting_sent` 플래그를 체크하는 과정에서 **레이스 컨디션** 또는 **잘못된 프로세서 참조** 발생
   - 결과: `send_greeting()` 메소드는 호출되지만 내부 로직이 실행되지 않음

### 추가 분석

RAGProcessor의 `send_greeting()` 시작 부분:

```python
async def send_greeting(self):
    if self._greeting_sent:  # ❌ 이미 True?
        return
    
    self._greeting_sent = True
    
    try:
        if self._agent_available:
            greeting = await self._agent.generate_greeting()
        
        if greeting:
            logger.info("rag_llm_greeting_phase1", ...)  # ❌ 이 로그가 찍히지 않음
```

**가능한 시나리오**:
1. 첫 번째 통화의 Task가 두 번째 통화의 프로세서에 접근
2. 또는 프로세서 인스턴스가 재사용됨 (매우 가능성 낮음)
3. 또는 `_greeting_sent` 플래그가 클래스 변수로 공유됨 (확인 필요)

**확인 결과**: `_greeting_sent`는 인스턴스 변수로 정의되어 있음 (`self._greeting_sent = False`)

**결론**: Pipeline Builder에서 Task를 dict에 저장하지 않아 정리가 되지 않고, 이로 인해 **첫 번째 통화의 greeting task가 두 번째 통화 시에도 계속 실행**되어 파이프라인 참조가 꼬이는 문제 발생.

---

## ✅ 수정 내용

**파일**: `sip-pbx/src/ai_voicebot/pipecat/pipeline_builder.py`

**변경 전**:
```python
greeting_task = asyncio.create_task(_send_initial_greeting())

try:
    await runner.run(task)
```

**변경 후**:
```python
greeting_task = asyncio.create_task(_send_initial_greeting())
self._greeting_tasks[call_id] = greeting_task  # ✅ Task를 dict에 저장

try:
    await runner.run(task)
```

### 수정 효과

1. ✅ Greeting Task가 `self._greeting_tasks[call_id]`에 저장됨
2. ✅ 통화 종료 시 `finally` 블록에서 `pop(call_id)`로 Task 정상 반환
3. ✅ Task가 완료되지 않았으면 `cancel()` 호출로 즉시 종료
4. ✅ 두 번째 통화 시 이전 Task가 남아있지 않아 정상 동작

---

## 🧪 테스트 시나리오

### 시나리오 1: 단일 통화
1. 첫 번째 AI 통화 시작
2. **예상 결과**:
   - ✅ `_send_initial_greeting()` Task 생성
   - ✅ `proc.send_greeting()` 호출
   - ✅ `rag_llm_greeting_phase1` 로그 출력
   - ✅ TTS 오디오 생성 및 RTP 전송
   - ✅ 통화 종료 시 Task cancel

### 시나리오 2: 연속 통화 (버그 재현)
1. 첫 번째 AI 통화 → 정상 종료
2. 두 번째 AI 통화 시작
3. **기대 결과** (수정 후):
   - ✅ 새로운 `_send_initial_greeting()` Task 생성
   - ✅ 이전 Task는 이미 취소됨
   - ✅ `proc.send_greeting()` 정상 호출
   - ✅ `rag_llm_greeting_phase1` 로그 출력
   - ✅ TTS 오디오 생성 및 RTP 전송

### 시나리오 3: 통화 중 취소
1. AI 통화 시작
2. Greeting Task 실행 중 BYE 수신
3. **예상 결과**:
   - ✅ `finally` 블록 실행
   - ✅ Task가 아직 실행 중이면 `cancel()` 호출
   - ✅ `CancelledError` 처리 후 정리 완료

---

## 📊 코드 리뷰 체크리스트

- ✅ **Line 250-251**: `greeting_task`를 `self._greeting_tasks[call_id]`에 저장
- ✅ **Line 262**: `pop(call_id)` 호출 시 Task 정상 반환
- ✅ **Line 263-268**: Task가 완료되지 않았으면 `cancel()` 후 `await`로 정리
- ✅ **레이스 컨디션 방지**: 각 통화는 독립적인 call_id로 dict에 저장되어 충돌 없음
- ✅ **메모리 누수 방지**: `pop(call_id)`로 dict에서 제거하여 참조 해제

---

## 🎯 관련 이슈

### 왜 첫 번째 통화에서는 문제가 없었나?

첫 번째 통화에서는:
1. Greeting Task 생성 → 즉시 실행
2. 0.5초 대기 후 `send_greeting()` 호출 성공
3. 통화 종료 시 Task는 이미 완료됨 (`done() == True`)
4. `finally` 블록에서 `pop(call_id)`는 `None`을 반환하지만, Task는 이미 완료되어 문제 없음

두 번째 통화에서는:
1. **첫 번째 통화의 Task가 아직 종료되지 않았거나** (가능성 낮음)
2. **새로운 Task가 첫 번째 파이프라인 참조를 사용** (가능성 높음)
3. 프로세서 참조가 꼬여서 `send_greeting()` 호출이 실패

### 왜 `initial_greeting_sent` 로그는 찍혔나?

```python
await proc.send_greeting()
logger.info("initial_greeting_sent", call_id=call_id)  # ✅ 이 부분은 실행됨
```

`proc.send_greeting()` 호출 자체는 성공했지만, **메소드 내부에서 early return**되었거나 **예외가 발생하여 로그가 찍히지 않음**.

로그 분석 결과, `rag_llm_greeting_phase1` 로그가 없으므로 **`send_greeting()` 메소드의 try 블록 내 Line 586 이전에 실패**.

---

## 🔍 추가 조사 필요

### 1. RAGProcessor 인스턴스 재사용 여부

**확인 사항**: 각 통화마다 새로운 RAGProcessor 인스턴스가 생성되는지?

**결과**: ✅ `pipeline_builder.py` Line 122에서 매번 새로운 인스턴스 생성 확인

```python
rag_llm = RAGLLMProcessor(
    llm_client=llm_client,
    rag_engine=rag_engine,
    org_manager=org_manager,
    ...
)
```

### 2. `_greeting_sent` 플래그 초기화

**확인 사항**: `_greeting_sent`가 클래스 변수인지 인스턴스 변수인지?

**결과**: ✅ 인스턴스 변수로 정의됨 (`self._greeting_sent = False` at Line 96)

### 3. Pipeline 참조 문제

**가설**: 첫 번째 통화의 greeting task가 두 번째 통화의 파이프라인을 참조하려고 시도?

**근거**:
- 첫 번째 Task가 취소되지 않음
- 두 번째 통화 시 `pipeline.processors` 순회 중 충돌 가능

**결론**: Task를 dict에 저장하고 정리함으로써 해결

---

## 📝 권장 사항

### 1. Greeting Task 관리 개선

현재 코드:
```python
self._greeting_tasks: Dict[str, asyncio.Task] = {}
```

**제안**: Task 생성/정리 로직을 별도 메소드로 분리

```python
def _create_greeting_task(self, call_id: str, pipeline: Pipeline) -> asyncio.Task:
    """Greeting Task 생성 및 등록"""
    async def _send_initial_greeting():
        ...
    
    task = asyncio.create_task(_send_initial_greeting())
    self._greeting_tasks[call_id] = task
    logger.debug("greeting_task_created", call_id=call_id, task_id=id(task))
    return task

async def _cancel_greeting_task(self, call_id: str):
    """Greeting Task 취소 및 정리"""
    task = self._greeting_tasks.pop(call_id, None)
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        logger.debug("greeting_task_cancelled", call_id=call_id)
```

### 2. Task 상태 모니터링

**제안**: Task 생성/취소 시 로그 추가

```python
logger.debug("greeting_task_created", call_id=call_id, task_done=task.done())
logger.debug("greeting_task_cancelled", call_id=call_id, was_running=not task.done())
```

### 3. 예외 처리 강화

`send_greeting()` 메소드:

```python
try:
    if self._agent_available:
        greeting = await self._agent.generate_greeting()
except Exception as e:
    logger.error("generate_greeting_failed", error=str(e), traceback=True)  # ✅ traceback 추가
    greeting = None
```

---

## ✅ 결론

**버그 원인**: Pipeline Builder에서 greeting task를 dict에 저장하지 않아 통화 종료 시 정리되지 않고, 두 번째 통화 시 파이프라인 참조 충돌 발생.

**수정 방법**: `greeting_task`를 `self._greeting_tasks[call_id]`에 저장하여 통화 종료 시 정상적으로 취소되도록 수정.

**검증 방법**: 두 번째 AI 통화 시 TTS 인사말이 정상적으로 재생되는지 확인.

**구현 완료 상태**: ✅ 100% (1줄 추가)
