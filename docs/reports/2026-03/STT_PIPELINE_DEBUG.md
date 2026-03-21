# STT 파이프라인 점검 — 말했는데 STT 결과가 한 번만 나올 때

**증상**: 실제로 여러 번 말했는데, 실시간 STT 결과(`rag_llm_user_input` / `transcription_frame_received`)가 한 번만 찍힘.

---

## 1. 파이프라인 경로

```
RTP(caller) → Input Transport → rec_input → VAD → STT(Google) → RAG → TTS → Output → RTP(caller)
                    ↑                              ↑
              input_audio_frame_to_pipeline   TranscriptionFrame
              (오디오는 계속 유입)              (최종 결과만 여기서 1회씩)
```

- **입력**: `input_audio_frame_to_pipeline` — caller PCM이 파이프라인에 들어가는 시점. 이 로그가 100/200/… 프레임마다 찍히면 **오디오는 STT 직전까지 전달되고 있음**.
- **STT 출력**: Pipecat `GoogleSTTService`가 **최종 인식이 끝날 때마다** `TranscriptionFrame` 1개를 내보냄. 이 프레임이 RAG에 도달할 때마다 **`transcription_frame_received`** 로그가 찍힘 (`seq` 1, 2, 3…).
- **RAG**: `TranscriptionFrame` 수신 시 `_process_with_agent()`를 **await** 하므로, 해당 발화에 대한 LLM 응답이 끝날 때까지 **다음 프레임을 처리하지 않음**. 즉, 두 번째 발화의 `TranscriptionFrame`은 첫 번째 응답이 다 나간 뒤에 처리됨.

---

## 2. 로그로 확인할 것

| 확인 항목 | 로그 이벤트 | 해석 |
|-----------|-------------|------|
| 오디오가 파이프라인까지 들어오는지 | `input_audio_frame_to_pipeline` (frame_count 100, 200, …) | 계속 증가하면 RTP → Input → VAD → STT **입력**까지는 정상. |
| 최종 STT가 몇 번 RAG까지 왔는지 | **`transcription_frame_received`** (seq=1, 2, …) | **seq가 1만 있으면** "말했는데 결과 없음"은 **STT가 두 번째 최종 결과를 안 보낸 것**에 가깝다. |
| 필터로 빠진 건지 | `stt_post_filter_dropped` | 두 번째 발화가 여기서 걸리면 text_preview, reason 확인. |
| STT 입력 큐 문제 | `stt_input_queue_full_dropping` | 나오면 STT로 가는 오디오가 드롭되고 있는 것. |

---

## 3. 가능 원인 (말했는데 STT 결과가 한 번만 나올 때)

1. **STT가 최종 결과를 한 번만 내보냄**  
   - Google 스트리밍 STT는 "발화 종료(침묵)" 구간 뒤에 `is_final` 결과를 보냄.  
   - 스트림 타임아웃(예: 409), 재연결, 또는 침묵 구간 설정에 따라 **두 번째 발화가 "최종"으로 나오기 전에** 스트림이 끊기거나 다음 발화가 하나의 긴 발화로 묶일 수 있음.  
   - **조치**: Pipecat `GoogleSTTService` 버전/옵션 확인, 스트림 유지/재연결 정책, 필요 시 `stt_ttfb_timeout` 등 관련 파라미터 검토.

2. **RAG 처리 지연으로 "체감"만 한 번처럼 보이는 경우**  
   - 첫 번째 발화 처리(LLM + TTS)가 길면, 두 번째 `TranscriptionFrame`은 그 **이후**에 처리됨.  
   - **조치**: `transcription_frame_received`의 `seq`와 타임스탬프로, 두 번째 발화가 **언제** RAG에 도달했는지 확인.

3. **두 번째 발화가 후처리 필터에 걸림**  
   - 짧은 말, 감탄사만 있으면 `stt_post_filter_dropped`로 LLM까지 안 넘어감.  
   - **조치**: `stt_post_filter_dropped` 로그의 `text_preview`, `reason` 확인.

4. **STT 입력 큐 가득 참**  
   - `stt_input_queue_full_dropping`이 있으면 caller 오디오가 버려짐.  
   - **조치**: 구간별 지연/백프레셔 확인, 큐 크기·소비 속도 조정.

다음 통화부터는 **`transcription_frame_received`** 의 `seq`가 2 이상 나오는지 보면, "말한 만큼 최종 STT가 RAG까지 오는지" 바로 구분할 수 있습니다.
