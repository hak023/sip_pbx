# TTS 출력 및 Queueing 전송 리뷰 (app.log 기반)

**목적**: TTS가 정상적으로 나가지 않는 문제와 `tts_rtp_duration_mismatch` 경고의 근본 원인을 로그·코드 기준으로 정리하고, queueing을 통한 전송 경로를 명시한다.

---

## 1. 로그로 확인한 현상

### 1.1 TTS 관련 로그 요약 (call_id: 4udhVMNr2o)

| 시점 | 이벤트 | 의미 |
|------|--------|------|
| 15:54:16.805 | tts_first_audio_received / tts_first_audio_sent_to_rtp | 첫 TTS 오디오 수신·RTP 전송 시작 (인사 Phase1) |
| 15:54:16.899 | greeting_phase1_sent, tts_first_chunk_sent_to_engine, streaming_tts_gateway_flushed | Phase1 텍스트 TTS 엔진 전달 완료 |
| 15:54:18.018 | tts_stopped_frame_received, tts_duration_known **6.716s**, tts_rtp_sent_for_response **6.517s** | Phase1 완료 — 거의 일치 |
| 15:54:25.380 | greeting_phase2_sent (8.48s 경과) | Phase2 텍스트 전송 |
| 15:54:27.068 | **tts_rtp_duration_mismatch** — rtp_sent 13.215s vs tts_duration **20.552s** (약 35.7% 차이) | Phase2: Notifier가 셌던 음원 길이 > Output이 큐에 넣은 양 |
| 15:55:01.034 | **tts_rtp_duration_mismatch** — rtp_sent **2.059s** vs tts_duration **35.494s** (약 94.2% 차이) | "네, 오늘 날씨 예보를" 응답 — 극심한 불일치 |
| 15:55:38.922 | **tts_rtp_duration_mismatch** — rtp_sent 4.718s vs tts_duration **41.762s** (약 88.7% 차이) | "네, 내일의 날씨 예보를..." 응답 |

- **패턴**: Notifier가 누적한 “TTS 음원 길이(초)”는 항상 **Output이 “큐에 넣은 PCM 바이트”로 환산한 시간보다 크다**.  
- **결과**: 상대적으로 **실제 RTP로 나가는 오디오 양이 적다** → 전화기에서 TTS가 짧게 끊기거나 일부만 들리는 현상으로 이어질 수 있음.

### 1.2 Queue 관련 로그

- `pipecat_outgoing_queue_full_dropping` 은 **한 번도 발생하지 않음** → 발송 큐 포화로 인한 드롭은 아님.
- `streaming_tts_gateway_flushed` 는 “gateway→TTS 전달 완료”만 의미하며, **TTS 합성/재생 완료가 아님** (로그 문구 그대로).

---

## 2. TTS 출력 로직과 파이프라인 순서

### 2.1 파이프라인 구성 (pipeline_builder)

```
SIPPBXInput → SileroVAD → SmartTurn → GoogleSTT → SmartBargeIn → RAG-LLM(LangGraph)
  → StreamingTTSGateway → GoogleTTS → TTSEndFrameForwarder → TTSCompleteNotifier → SIPPBXOutput
```

- **TTS 출력 경로**: RAG가 `TextFrame` 전달 → StreamingTTSGateway(버퍼/플러시) → Google TTS(오디오 합성) → EndFrameForwarder → **Notifier(재생 길이 누적)** → **Output(RTP 큐에 PCM 투입)**.

### 2.2 TTSCompleteNotifier (음원 길이 누적)

- **역할**: `OutputAudioRawFrame` / `TTSAudioRawFrame` 등 `.audio`(bytes) 가 있는 프레임의 **재생 길이**를 누적.
- **계산**: `duration_sec = len(audio) / (sample_rate * 2 * num_channels)`  
  - `sample_rate` 는 프레임 속성 또는 기본 16000.
- **EndFrame 수신 시**: `KEY_LAST_TTS_DURATION_SEC` 에 해당 응답 구간 누적 초를 넣고, `event.set()` 으로 Phase 대기 해제.
- **중요**: Notifier는 **모든 오디오 프레임을 그대로 downstream 으로 push** 하므로, 이 단계에서 프레임을 버리지는 않음.

### 2.3 SIPPBXOutput (RTP 쪽 “큐에 넣기”)

- **역할**: 동일 오디오 프레임을 받아서  
  - `_response_bytes += len(audio_data)` 로 “이번 응답(Phase)에서 큐에 넣은 PCM 바이트” 누적  
  - `send_audio_to_caller(pcm_data, sample_rate)` 호출 → RTP 패킷으로 변환 후 **발송 큐에 put**.
- **EndFrame 수신 시**:  
  - `duration_sec = _response_bytes / (16000*2)` 로 로그에 기록하고,  
  - Notifier가 넣은 `KEY_LAST_TTS_DURATION_SEC` 와 비교해 10% 이상 차이 나면 **tts_rtp_duration_mismatch** 경고.

이론상 **동일 프레임**이 Notifier → Output 순으로만 지나가므로, “Notifier 누적 초”와 “Output 누적 바이트→초”는 일치해야 한다. 불일치가 나는 이유는 아래 두 가지가 유력하다.

---

## 3. Queueing을 통한 전송 경로 (상세)

### 3.1 전체 흐름

1. **Pipecat Output (SIPPBXOutput)**  
   - TTS에서 나온 PCM 프레임을 받을 때마다 `_rtp_worker.send_audio_to_caller(pcm_data, sample_rate)` 호출.

2. **RTP Relay Worker · send_audio_to_caller()** (`rtp_relay.py`)  
   - `RTPPacketBuilder.build_packets(pcm_data, sample_rate)`  
     - PCM을 8kHz로 리샘플링 → G.711 인코딩 → **20ms(160 samples @ 8kHz) 단위 RTP 패킷** 리스트 생성.  
   - 각 RTP 패킷을 **`_pipecat_outgoing_queue.put_nowait(packet)`** 로 넣음.  
   - **큐 풀 시**: `asyncio.QueueFull` 이면 `break` 로 **해당 PCM 청크에서 나온 나머지 패킷은 넣지 않음** (로그: `pipecat_outgoing_queue_full_dropping`).  
   - 현재 로그에는 이 경고가 없으므로, **실제 드롭은 “큐 풀”이 아니라 다른 원인**으로 보는 것이 맞음.

3. **실제 RTP 전송 (queue 소비)**  
   - `_pipecat_outgoing_sender_loop()` 가 **20ms 간격**으로 `_pipecat_outgoing_queue.get()` → `callee_audio_transport.sendto(packet, (caller_ip, caller_port))` 로 전송.  
   - 설계 의도: 한꺼번에 쏘지 않고, 20ms 패이싱으로 전화기 지터 버퍼 유실을 줄이기 위함.

정리하면:

- **“큐에 넣는” 쪽**: `SIPPBXOutput` → `send_audio_to_caller()` → `build_packets()` → `_pipecat_outgoing_queue.put_nowait(packet)` (여기서 “queueing” 발생).  
- **“큐에서 꺼내서 보내는” 쪽**: `_pipecat_outgoing_sender_loop()` 가 20ms마다 get → sendto.

따라서 **TTS가 “정상적으로 나가지 않는다”**는 현상이 있다면,  
- **원인 1**: Output까지 **오디오 프레임이 적게 도달** (Notifier는 많이 셌는데 Output은 적게 센 경우 → 아래 4절).  
- **원인 2**: 큐에는 잘 넣었지만, **sender 루프/네트워크/코덱** 문제로 실제 전송이 누락되거나 지연되는 경우.  
현재 로그만 보면 **원인 1이 압도적으로 유력** (Notifier > Output 지속).

---

## 4. 근본 원인 분석: Notifier > Output 인 이유

- Notifier와 Output은 **같은 파이프라인에서 순차적으로 같은 프레임**을 받는다.  
  그런데 “Notifier 누적 초 > Output 누적 바이트→초”가 반복되므로,  
  **Output이 받는 오디오 프레임 수(또는 바이트)가 Notifier보다 적다**는 뜻이다.

가능한 메커니즘 하나는 **프레임 도달 순서**다.

- RAG/StreamingTTSGateway는 **StartFrame, TextFrame(들), EndFrame** 을 빠르게 연속으로 보낼 수 있다.  
- Pipecat Google TTS가 **비동기**로 동작하면,  
  - **EndFrame(또는 TTSStoppedFrame 후의 synthetic EndFrame)** 이  
  - **아직 TTS가 밀어넣지 않은 오디오 프레임들보다 먼저** downstream(Notifier → Output)에 도달할 수 있다.  
- 그러면:  
  - **Output**은 “현재 응답” 구간에서 `LLMFullResponseStartFrame` 으로 `_response_bytes` 를 리셋한 뒤,  
    **EndFrame** 을 먼저 받아서 **그 시점의 _response_bytes(작은 값)** 로 `KEY_LAST_RTP_SENT_SEC` 를 찍고 로그를 남김.  
  - **그 다음에** TTS에서 나온 나머지 오디오 프레임들이 도착하면,  
    그건 이미 “다음 응답”의 StartFrame 이후로 취급되거나, 같은 응답인데 EndFrame 이후에 와서 **다음 응답의 _response_bytes**에 누적될 수 있다.  
- **Notifier**는 “해당 응답” 구간에서 **모든 오디오 프레임**을 EndFrame 전에 받았다고 가정하고 누적하므로,  
  TTS가 실제로 보낸 **전체** 오디오 길이에 가깝게 `KEY_LAST_TTS_DURATION_SEC` 를 넣을 수 있다.  
  (Notifier와 TTS가 같은 태스크/큐 안에 있어서, Notifier에는 오디오가 더 많이 도달한 경우를 상정.)

즉, **EndFrame이 “해당 응답의 모든 TTS 오디오”보다 먼저 Output에 도달**하면:

- Output: “이번 응답”에서 큐에 넣은 양 = **적게** 기록됨.  
- Notifier: “이번 응답” 재생 길이 = **많게** 기록됨.  
→ **tts_rtp_duration_mismatch** (Notifier > Output) 가 반복되고,  
→ 상대적으로 **RTP로 나가는 양이 적어져** TTS가 짧게 끊기거나 일부만 들리는 현상으로 이어질 수 있다.

추가로:

- **sample_rate 불일치**: TTS가 24kHz 등으로 내보내는데 Notifier/Output에서 16kHz로만 해석하면, “초” 계산은 달라질 수 있으나, **지금 로그는 “Notifier > Output”** 이므로 “Output에 도달하는 바이트가 적다”가 더 직접적인 설명이다.
- **큐 풀**: 로그에 `pipecat_outgoing_queue_full_dropping` 이 없으므로, **queueing 단계에서의 큐 포화 드롭은 우선 배제**해도 된다.

---

## 5. 점검·개선 제안

### 5.1 즉시 확인할 것

1. **Pipecat Google TTS 동작**  
   - EndFrame(또는 upstream EndFrame)을 **받자마자** 그대로 전달하지 말고,  
     “이번 응답에 해당하는 **모든 오디오를 먼저 push**한 뒤, 마지막에 EndFrame(또는 TTSStoppedFrame + synthetic EndFrame)을 보내는지” 확인.  
   - 즉, **TTS 완료 시그널은 “해당 응답의 마지막 오디오 프레임 다음”에만 나가야** Notifier/Output 모두 동일한 오디오 집합을 “한 응답”으로 인식한다.

2. **StreamingTTSGateway → TTS**  
   - `LLMFullResponseEndFrame` 시 `_flush_buffer()` 후 바로 EndFrame을 push하면,  
     TTS는 “텍스트는 다 받았음”을 알지만, **아직 합성 중인 오디오가 있을 수 있음**.  
   - 가능하면 “TTS가 이번 응답에 대한 오디오를 **다 push한 뒤** EndFrame이 나가도록” Pipecat TTS 구현/옵션 확인.

3. **발송 큐 모니터링**  
   - `_pipecat_outgoing_queue.qsize()` 를 주기적으로 로그에 남기거나,  
     `send_audio_to_caller` 호출 시점에 “이번에 넣은 패킷 수 / 누적 패킷 수”를 로그하면,  
     queueing 단계에서 실제로 얼마나 넣고 있는지 추적하기 쉬움.

### 5.2 설계/구현 개선

- **EndFrame 타이밍**:  
  - “RAG/Gateway가 EndFrame을 보내는 시점”과 “TTS가 해당 응답의 **모든** 오디오를 push한 시점”을 일치시키는 쪽으로 조정하는 것이 안전함.  
  - Pipecat 쪽에서 “TTS 완료 시에만 EndFrame(또는 TTSStoppedFrame) 전달” 옵션이 있다면 그에 맞추는 것을 권장.
- **Notifier vs Output duration 계산**  
  - 두 쪽 모두 **프레임의 `sample_rate`** 를 동일하게 사용하는지 확인.  
  - TTS가 24kHz를 쓴다면, Notifier/Output/빌더 모두 24k → 8k 리샘플 시 일관되게 처리하는지 점검.
- **큐 크기**  
  - 현재 `_pipecat_outgoing_queue` maxsize=5000, 20ms 패킷 기준 약 100초분.  
  - 부하가 크면 일시적으로 큐가 찰 수 있으므로, `pipecat_outgoing_queue_full_dropping` 로그가 나오기 시작하면 큐 크기 증가 또는 백프레셔 검토.

---

## 6. 요약

| 구분 | 내용 |
|------|------|
| **증상** | TTS가 정상적으로 나가지 않음; 로그에 `tts_rtp_duration_mismatch` 반복 (Notifier 누적 초 > Output “큐에 넣은” 초). |
| **Queueing 경로** | SIPPBXOutput → `send_audio_to_caller()` → `RTPPacketBuilder.build_packets()` → `_pipecat_outgoing_queue.put_nowait(packet)` → `_pipecat_outgoing_sender_loop()` 가 20ms 간격으로 get → sendto. |
| **큐 포화** | 로그상 `pipecat_outgoing_queue_full_dropping` 없음 → queueing 단계의 “큐 풀” 드롭은 아님. |
| **유력 원인** | **EndFrame이 해당 응답의 TTS 오디오 일부(또는 대부분)보다 먼저 Output에 도달**하여, Output이 “이번 응답”에서 적은 바이트만 누적하고, 나머지 오디오는 다음 응답 구간에 섞이거나 반영되지 않음. |
| **다음 단계** | Pipecat Google TTS에서 “해당 응답의 모든 오디오를 push한 뒤에만 완료 시그널(EndFrame/TTSStoppedFrame) 전달”이 되도록 확인·수정; 필요 시 발송 큐 크기/로깅 보강. |

---

## 7. 수정 사항 (EndFrame 타이밍) 및 재테스트용 로그

### 7.1 적용한 수정

- **TTSEndFrameForwarder**: Upstream에서 오는 `LLMFullResponseEndFrame`을 **절대 그대로 전달하지 않음**. TTS가 이번 응답의 모든 오디오를 내보낸 뒤 `TTSStoppedFrame`이 오면, 그때만 **synthetic** `LLMFullResponseEndFrame`을 한 번 전송. 하류(Notifier, Output)는 항상 [모든 오디오] → TTSStoppedFrame → EndFrame 순서로만 보게 되어, 문장 끝 잘림 완화 목적.

### 7.2 원인 파악용 상세 로그 (app.log)

재테스트 시 아래 이벤트로 순서/불일치 여부를 확인할 수 있음.

| 이벤트 | 위치 | 의미 |
|--------|------|------|
| `endframe_upstream_received_not_forwarded` | TTSEndFrameForwarder | Upstream EndFrame 수신 후 전달 안 함, `audio_frames_since_start` |
| `tts_stopped_frame_received` | TTSEndFrameForwarder | TTS 이번 응답 오디오 출력 완료 |
| `endframe_emitted_after_tts_stopped` | TTSEndFrameForwarder | Synthetic EndFrame 전송 (오디오 전부 지나간 뒤) |
| `notifier_endframe_processed` | TTSCompleteNotifier | Notifier가 EndFrame 수신 시점 — `duration_sec`, `audio_frame_count` |
| `output_endframe_processed` | SIPPBXOutput | Output이 EndFrame 수신 시점 — `response_bytes` |

**확인 방법**: 같은 응답에서 `notifier_endframe_processed`의 `duration_sec`와 `output_endframe_processed`의 `response_bytes`를 비교. `duration_sec * 32000`에 가깝게 `response_bytes`가 나오면 EndFrame이 오디오 전부 이후에만 전달된 것. `tts_rtp_duration_mismatch` 경고가 사라지거나 줄면 수정 효과 있음.

### 7.3 재테스트 방법

1. SIP PBX + Pipecat 기동 후 1003 → 1004 등으로 통화.
2. no_answer 후 AI 인수 → 인사말/질의응답 TTS 재생.
3. `logs/app.log`에서 위 이벤트 및 `tts_rtp_duration_mismatch` 검색.
4. 통화 종료 후 전화기에서 TTS가 문장 끝까지 자연스럽게 들리는지 확인.

이 문서는 `docs/reports/TTS_RTP_AND_HITL_DESIGN.md` 및 `docs/architecture/ai-voicebot-architecture.md` 의 TTS→RTP·HITL 설계와 함께 참고하면 된다.
