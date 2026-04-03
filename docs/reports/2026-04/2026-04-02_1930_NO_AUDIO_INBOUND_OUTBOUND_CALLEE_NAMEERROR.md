# No Audio — Inbound/Outbound 공통 무음 장애 분석 및 수정

| 항목 | 내용 |
|------|------|
| 작성일 | 2026-04-02 19:30 |
| 상태 | **수정 완료 (서버 재시작 필요)** |
| 관련 파일 | `sip-pbx/src/ai_voicebot/pipecat/pipeline_builder.py` |
| 관련 이슈 | inbound/outbound 모두 아무 소리 없음 |

---

## 1. 증상

- Inbound, Outbound 모두 통화 연결은 되지만 AI 쪽에서 **아무 음성도 출력되지 않음**
- 사용자 발화도 STT 처리 없이 무시됨

---

## 2. 로그 근거

### 결정적 로그 패턴 (인바운드 `OlBGrgbs4m`, 아웃바운드 `outbound-ob-23e4d606-11319993` 공통)

```
pipeline_runner_about_to_start  ← 파이프라인 시작 직전
outbound_pipecat_pipeline_done  ← 즉시 done (정상이면 통화 종료 후)
```

→ `runner.run(task)` 호출 전에 예외 발생으로 파이프라인 태스크가 즉시 종료됨.

```
rag_llm_pipecat_start_timeout  context=send_greeting  timeout_sec=60.0
send_greeting_aborted_no_startframe
```

→ `RAGLLMProcessor`가 `StartFrame`을 60초 대기했으나 수신하지 못해 인사 TTS 생략.

### Pipecat 내부 stderr (터미널 직접 출력)

```
SIPPBXInput Trying to process InputAudioRawFrame but StartFrame not received yet
```

→ `SIPPBXInputTransport`도 `StartFrame`을 받지 못해 오디오 프레임을 모두 드롭.

---

## 3. 근본 원인 분석

### 원인: `NameError: name 'callee' is not defined`

**이전 대화에서 `build_and_run` 파라미터명을 `callee → owner`로 변경**했으나,  
함수 본문 내 3곳에서 **`callee` 변수를 그대로 참조**하고 있었음.

| 줄 | 코드 |
|----|------|
| 421 | `log_call_data(call_id, "call_event", "call_connected", callee=callee or "")` |
| 424 | `register_active_call(call_id, callee=callee or "", is_ai_handled=True)` |
| 474 | `log_call_data(call_id, "call_event", "call_ended", callee=callee or "")` |

### 오류 전파 경로

1. `call_manager.py`에서 `build_and_run(owner, ...)` 코루틴을 `asyncio.create_task`로 실행
2. 코루틴 내부 421번 줄에서 `NameError: name 'callee' is not defined` 발생
3. 421번이 `try: await runner.run(task)` 블록(427번) **밖**에 있으므로 `except Exception`에서 미처리
4. 예외가 코루틴 밖으로 전파 → `finally` 실행 후 태스크 종료
5. `done_callback` → `outbound_pipecat_pipeline_done` 즉시 로그
6. `PipelineRunner.run()`이 호출되지 않아 `StartFrame`이 파이프라인에 전달되지 않음
7. 모든 프로세서가 `StartFrame` 미수신 상태로 대기 → 오디오 드롭, 인사 TTS 타임아웃

---

## 4. 수정 내용

파일: `sip-pbx/src/ai_voicebot/pipecat/pipeline_builder.py`

### Before (3곳)

```python
log_call_data(call_id, "call_event", "call_connected", callee=callee or "")
register_active_call(call_id, callee=callee or "", is_ai_handled=True)
log_call_data(call_id, "call_event", "call_ended", callee=callee or "")
```

### After

```python
log_call_data(call_id, "call_event", "call_connected", callee=owner or "")
register_active_call(call_id, callee=owner or "", is_ai_handled=True)
log_call_data(call_id, "call_event", "call_ended", callee=owner or "")
```

※ `callee=` 키워드 인자 이름 자체는 함수 시그니처이므로 유지, 값만 `callee → owner` 변수로 교정.

---

## 5. 영향 범위

| 기능 | 영향 |
|------|------|
| Inbound AI 통화 | 수정 전: 모두 무음 (파이프라인 즉시 종료) |
| Outbound AI 통화 | 수정 전: 모두 무음 (동일) |
| `log_call_data` CDR 기록 | 수정 전: call_connected/call_ended 미기록 |
| `register_active_call` | 수정 전: 활성 통화 등록 실패 |

---

## 6. 조치

- [x] `pipeline_builder.py` 3곳 `callee → owner` 변수 참조 수정
- [ ] **서버 재시작 필요** (수정 반영)
- [ ] 재시작 후 inbound/outbound 통화 테스트 확인
