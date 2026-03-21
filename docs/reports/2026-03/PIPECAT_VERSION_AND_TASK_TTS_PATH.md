# Pipecat 버전 및 Task → TTS 경로 점검

**점검일**: 2026-03-12

---

## 1. Pipecat 버전

| 항목 | 값 |
|------|-----|
| **설치 버전** | **0.0.102** (`pip show pipecat-ai`) |
| **요구 버전** | `requirements-ai.txt`: `pipecat-ai[google,silero]>=0.0.85` |
| **패키지 위치** | `...\Python311\site-packages\pipecat` |

---

## 2. Task → TTS 경로 (InterruptionFrame 유입)

### 2.1 InterruptionTaskFrame → InterruptionFrame 변환 (task.py)

Pipecat `PipelineTask`의 **Source 쪽**에서 업스트림 프레임을 처리할 때:

```python
# task.py _source_push_frame() (라인 889-895)
elif isinstance(frame, InterruptionTaskFrame):
    # push queue를 거치지 않고 직접 pipeline에 InterruptionFrame 주입
    logger.debug(f"{self}: received interruption task frame {frame}")
    await self._pipeline.queue_frame(InterruptionFrame())
```

- **누가 보내나**: 파이프라인 안 어떤 프로세서(예: STT, VAD)가 **업스트림**으로 `InterruptionTaskFrame`을 푸시하면, 그 프레임은 파이프라인 **시작 쪽(Source)**에 도달.
- **Task 동작**: Source에서 `InterruptionTaskFrame` 수신 시, **`InterruptionFrame()`을 만들어 `_pipeline.queue_frame(InterruptionFrame())`으로 큐잉**.  
  주석대로 push queue를 우회해 바로 pipeline에 넣어, “파이프 종료 프레임 대기로 블로킹된 push 태스크”와 무관하게 인터럽션을 넣음.

### 2.2 InterruptionFrame이 흐르는 방향 (pipeline.py)

- `queue_frame(frame)` 에서 direction을 안 주면 기본은 **DOWNSTREAM**.
- `Pipeline.process_frame()`:
  - DOWNSTREAM → `_source.queue_frame(frame, DOWNSTREAM)`  
  즉, **파이프라인 맨 앞 프로세서(Source)부터** 다운스트림으로 한 칸씩 전달.
- 우리 빌드에서 파이프라인 순서는 대략:
  - `[ PipelineSource, (RTVI?), transport.input(), rec_input, vad_wrapped, barge_in_suppress, stt, rag_llm, barge_in_suppress_before_tts, tts, ..., PipelineSink ]`
- 따라서 Task가 `InterruptionFrame()`을 넣으면:
  1. **Source** → 2. **transport.input()** → … → **barge_in_suppress** → … → **barge_in_suppress_before_tts** → **tts** → … → **Sink**  
  **같은 선형 체인을 따라** TTS까지 내려감.  
  즉, **Task가 “TTS로만” 직접 넣는 별도 경로는 없고**, 반드시 우리가 둔 `BargeInSuppressProcessor` 두 개(바로 다음 단계들)를 **둘 다** 거침.

### 2.3 결론 (이론상)

- **InterruptionFrame**은 Task가 **파이프라인 맨 앞(Source)**에 넣고, **다운스트림만** 사용.
- 따라서 **barge_in_suppress** → … → **barge_in_suppress_before_tts** 를 반드시 통과하고, 우리가 여기서 Interruption* 를 흡수하면 TTS에는 도달하지 않아야 함.
- “Task가 TTS로 직접 넣어서 BargeInSuppress를 우회한다”는 경로는 **Pipecat 0.0.102 소스상 존재하지 않음**.

---

## 3. "Barge-in detected, stopping TTS" 로그 출처

- Pipecat GitHub 메인 브랜치 코드에서 **"Barge-in detected"** / **"stopping TTS"** 문자열 **검색 결과 없음** (0 files).
- 우리 쪽 문서(`BARGE_IN_STOPPING_TTS_ROOT_CAUSE.md`, `PHASE2_STT_DB_LOG_ANALYSIS.md` 등)에서는 **사용자 로그에 나온 문구**로 인용하고 있음.
- 가능한 출처:
  1. **과거 Pipecat 버전** 또는 **다른 브랜치/패키지**의 로그 메시지
  2. **TTS 구현체**(예: Google TTS 서비스 래퍼) 내부의 로그
  3. **loguru** 등 로거의 포맷/메시지 가공 결과

현재 설치된 Pipecat 소스만으로는 해당 정확 문구의 발생 위치는 특정되지 않음.  
다만 **TTS 서비스** (`tts_service.py`) 에서는 `InterruptionFrame` 수신 시 `_handle_interruption()` 호출 후 **그대로 `push_frame(frame, direction)`** 하므로, InterruptionFrame이 TTS까지 도달하면 “인터럽션 처리 + TTS 중단” 동작은 발생함.

---

## 4. 권장 사항

1. **현재 방어 로직 유지**
   - **BargeInSuppressProcessor** 2단 (VAD 다음, TTS 직전): Interruption* + `"Interruption" in type(frame).__name__` 차단.
   - **SIPPBXOutputTransport**: Interruption* 수신 시 하류로 전달하지 않고 흡수.
   - 이렇게 하면 Task가 Source에 넣은 InterruptionFrame도 **반드시** 위 두 구간 중 하나에서 걸러져야 함.

2. **여전히 "Barge-in detected, stopping TTS" 가 나올 때**
   - 로그에 **프레임 타입/방향**을 남기면 좋음 (예: `vad_barge_in_suppressed`, `output_interruption_frame_absorbed`).
   - 위 로그가 찍히는데도 TTS 중단 로그가 나온다면:
     - Pipecat **0.0.102** 와 **실제 설치된 pipecat 패키지 디렉터리**의 `task.py` / `pipeline.py` 가 위 설명과 동일한지 확인.
     - 사용 중인 **TTS 서비스 클래스**(Google 등) 내부에서 "Barge-in detected" / "stopping TTS" 문자열 검색해 로그 발생 위치 특정.

3. **버전 고정**
   - 재현/분석을 위해 `requirements-ai.txt` 에 `pipecat-ai[google,silero]==0.0.102` 로 명시해 두면 이후 버전 변경 시 경로 비교가 수월함.

---

## 5. 참고: Pipecat task.py 요약

- **InterruptionTaskFrame** 수신: **Source** (`_source_push_frame`) 에서만 처리.
- 수신 시 **`await self._pipeline.queue_frame(InterruptionFrame())`** 한 번 호출 → InterruptionFrame은 **파이프라인 앞단(Source)에 DOWNSTREAM으로** 들어감 → 선형 체인 따라 **모든 프로세서를 거쳐** Sink(및 TTS) 방향으로 전달됨.
