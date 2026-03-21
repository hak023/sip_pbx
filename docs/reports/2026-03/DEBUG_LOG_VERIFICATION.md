# 디버깅 로그 점검표 — 테스트 후 동작 여부 확인

통화 테스트 후 `app.log`에서 아래 이벤트를 **call_id**로 걸러 확인하면, 생각한 대로 동작하는지 점검할 수 있다.

---

## 1. STT 경로 (사용자 발화가 STT → RAG까지 도달하는지)

### 이벤트 순서 (같은 call_id 기준 시간순)

| 순서 | 이벤트 | 의미 |
|------|--------|------|
| 1 | **stt_path_rtp_first** | RTP → STT 입력 큐 첫 투입. 이 로그가 있어야 경로 시작. |
| 2 | **stt_path_queue_first** | 큐 → Input 첫 소비. 파이프라인이 큐를 읽기 시작. |
| 3 | **stt_path_input_first** | Input → 파이프라인 첫 프레임. VAD/STT 구간으로 들어감. |
| 4 | stt_path_rtp_to_queue (200마다) | RTP가 계속 큐에 쌓이는지. |
| 5 | stt_path_queue_to_consumer (200마다) | 큐가 계속 소비되는지. |
| 6 | stt_path_input_to_pipeline (200마다) | Input이 계속 프레임을 push 하는지. |
| 7 | **stt_path_stt_first** | **통화 중 STT → RAG 첫 도달.** 이 로그가 있으면 실시간 STT가 한 번이라도 동작한 것. |
| 8 | stt_path_stt_to_rag | 이후 발화마다. seq 증가하면 여러 발화 인식됨. |
| 종료 | stt_path_input_total | Input 종료 시까지 넣은 총 프레임 수. |

### 점검 방법 (동작했는지)

- **실시간 STT가 동작했다**: `stt_path_stt_first` 또는 `stt_path_stt_to_rag` 가 해당 통화에서 **최소 1회** 나온다.
- **말했는데 인식 안 됐다**: `stt_path_rtp_first` ~ `stt_path_input_to_pipeline` 은 나오는데 `stt_path_stt_first` / `stt_path_stt_to_rag` 가 **한 번도 없음** → RTP→큐→Input까지는 오고, STT 또는 그 이후에서 끊긴 것.
- **큐가 막혔다**: `stt_path_queue_full_drop` 이 나오면 큐가 가득 찼고, caller PCM이 드롭된 것. 파이프라인 소비 지연 의심.
- **큐 소비가 안 됐다**: `stt_path_rtp_to_queue` 는 늘어나는데 `stt_path_queue_first` / `stt_path_queue_to_consumer` 가 없거나 멈춤 → Input이 큐를 안 읽는 것 (파이프라인 블로킹 등).

### grep 예시

```bash
# 특정 통화의 STT 경로만
grep "call_id.*<call_id>" app.log | grep "stt_path_"
```

---

## 2. Barge-in (Interruption은 막고, 사용자 발화 인식은 유지)

### 이벤트 의미

| 이벤트 | 의미 |
|--------|------|
| **barge_in_suppress_blocked** | Interruption* 프레임을 중간에서 차단함. TTS로 안 보냄 → STOP TTS가 실행되지 않음 (의도한 동작). |
| **barge_in_suppress_passed** | Interruption이 아닌 프레임을 TTS 방향으로 전달. 1회 + 500개마다. 정상 흐름. |
| **vad_interruption_absorbed** | enable_barge_in=False 일 때 VAD 래퍼에서 Interruption* 흡수. |
| **output_interruption_frame_absorbed** | Output Transport에서 Interruption* 흡수. (중간에서 막혀도 다른 경로로 올 수 있어 여기서 한 번 더 막음) |
| **barge_in_suppress_interruption_passed** | BUG. Interruption* 이 TTS로 전달된 경우. 나오면 안 됨. |

### 점검 방법 (올바르게 동작했는지)

- **의도대로 동작**: TTS 재생 중 사용자가 말해도 **"Barge-in detected, stopping TTS"** 가 나오지 않거나, 나와도 실제로 TTS가 끊기지 않도록 하려는 경우:
  - **barge_in_suppress_blocked** 가 찍히면 → 우리 파이프라인 경로로 들어온 Interruption* 은 막은 것.
  - **output_interruption_frame_absorbed** 가 찍히면 → 중간을 지나쳐 온 Interruption* 을 Output에서 흡수한 것.
- **여전히 TTS가 끊긴다**: "Barge-in detected, stopping TTS" 가 나오는데 **barge_in_suppress_blocked** / **vad_interruption_absorbed** / **output_interruption_frame_absorbed** 가 **그 통화에서 전혀 없음** → Interruption이 우리가 로그 찍는 경로가 아닌 다른 경로(예: TTS 내부)에서 발생한 것. 추가 추적 필요.
- **버그**: **barge_in_suppress_interruption_passed** 가 한 번이라도 나오면 차단 로직을 점검해야 함.

### grep 예시

```bash
grep "call_id.*<call_id>" app.log | grep -E "barge_in_suppress_|vad_interruption_|output_interruption_"
```

---

## 3. 요약 체크리스트 (테스트 후)

- [ ] **STT 경로**: `stt_path_rtp_first` → `stt_path_queue_first` → `stt_path_input_first` 순서로 나오는가?
- [ ] **STT 동작**: 사용자가 말했을 때 `stt_path_stt_first` 또는 `stt_path_stt_to_rag` 가 해당 call_id에 나오는가?
- [ ] **Barge-in 차단**: TTS 중 끊기지 않게 하려는 설정이면 `barge_in_suppress_blocked` 또는 `output_interruption_frame_absorbed` 가 나오는가?
- [ ] **비정상**: `stt_path_queue_full_drop` 이 반복되지 않는가? `barge_in_suppress_interruption_passed` 가 없어야 함.

이 문서는 **테스트 후 로그만 보고** “생각한 대로 움직였는지” 점검할 수 있도록 정리한 것이다.
