# TTS→RTP 변수 정의·Phase 타이밍 & RAG 부족 시 HITL 대응 설계

## 1. TTS → RTP 전송 흐름 및 변수 정의

### 1.1 파이프라인 순서

```
TTS(Google) → TTSEndFrameForwarder → TTSCompleteNotifier → SIPPBXOutputTransport
                                                                  ↓
                                              send_audio_to_caller(pcm) → RTP Relay
                                                                  ↓
                                              _pipecat_outgoing_queue.put_nowait(패킷들)
                                                                  ↓
                                              _pipecat_outgoing_sender_loop: 20ms마다 1패킷 sendto()
```

- **Output**: 오디오 프레임마다 PCM을 RTP 패킷으로 쪼개 **발송 큐**에 넣기만 하고 반환한다. 실제 UDP 전송은 **발송 루프**가 20ms 간격으로 수행한다.
- **Notifier**: 동일 오디오 프레임의 재생 길이(바이트→초)를 누적해, EndFrame 시 `last_tts_duration_sec`와 이벤트를 설정한다.

### 1.2 변수 정의 (로그·동기화 해석용)

| 변수 | 설정 위치 | 의미 |
|------|-----------|------|
| **last_tts_duration_sec** | TTSCompleteNotifier | 해당 응답(Start~End) 구간에서 TTS가 내보낸 **모든 오디오 프레임**의 재생 길이 합(초). `sum(len(audio)/(sample_rate*2*channels))`. "이 응답 음원이 몇 초짜리인가". |
| **bytes_sent** | SIPPBXOutputTransport | 해당 응답 구간에서 `send_audio_to_caller()`로 **발송 큐에 넣은** PCM 바이트 합. 실제 UDP 전송 완료량이 아님. |
| **duration_sec** (Output 로그) | SIPPBXOutputTransport | `bytes_sent / (PIPECAT_SAMPLE_RATE * 2)` = 16kHz 16bit 기준 큐에 넣은 양을 초로 환산. Phase1→Phase2 대기 시 `KEY_LAST_RTP_SENT_SEC`로 사용. |
| **tts_rtp_duration_mismatch** | Output(EndFrame 시) | Notifier의 `last_tts_duration_sec`와 Output의 `duration_sec` 차이가 10% 이상일 때 경고. 동일 프레임을 두 프로세서가 보므로 이론상 일치; sample_rate 불일치 시 차이 가능. |

### 1.3 Phase1 → Phase2 시간 계산

- **목적**: Phase1 인사말 TTS가 전화기에서 재생될 시간만큼 기다린 뒤 Phase2를 보내기 위함.
- **흐름**:
  1. RAGLLMProcessor가 Phase1 텍스트를 보내고 `event.wait()`로 대기.
  2. Notifier가 Phase1의 EndFrame을 보면 재생 길이를 `last_tts_duration_sec`에 넣고 `event.set()`.
  3. **이때 Output은 아직 EndFrame을 처리하지 않았을 수 있음** (파이프라인 순서: Notifier → Output). 따라서 RAG에서는 `event.wait()` 직후 **0.05초 sleep** 후 `KEY_LAST_RTP_SENT_SEC`를 pop해, Output이 값을 써 넣을 시간을 준다.
  4. `rtp_sent_sec`가 있으면 `gap_sec = rtp_sent_sec + PHASE_GAP_BUFFER_SEC`로 대기(전화기 재생 시간 반영), 없으면 `play_sec + PHASE_GAP_BUFFER_SEC`(Notifier 누적값)로 대기.

### 1.4 끊김(choppy) 가능 원인 및 개선 방향

- **원인 후보**:
  - 발송 루프가 20ms마다 한 패킷만 보내므로, TTS가 청크를 늦게 주면 큐가 잠깐 비고, 그동안 전화기에는 패킷이 안 가서 끊김처럼 들릴 수 있음.
  - 큐가 가득 찬 경우 `put_nowait` 실패 시 해당 청크의 패킷이 누락됨(현재는 경고 후 break).
- **개선 방향**:
  - 큐 크기(5000) 유지, 누락 시 break 대신 재시도 또는 블로킹 옵션 검토.
  - 필요 시 "응답 시작 전에 최소 N ms 분량이 큐에 쌓일 때까지 대기" 같은 버퍼링은 지연 증가와 트레이드오프이므로, 현재 20ms 패이싱 유지하고 0.05초 Phase 동기화만 적용한 상태로 관찰 후 추가 검토.

---

## 2. RAG 부족 시 HITL 대응 설계 (요구 방향 반영)

### 2.1 목표 플로우 (사용자 요구)

1. **모르는 내용은 모른다고 답변**
2. **관련 내용 확인하겠으니 잠시만 기다려 달라** → HITL로 frontend 담당자에게 문의
3. **답변 없음(timeout)** → "확인 지연 중이니 확인되는 대로 연락 남기겠습니다" 후 종료, frontend로 피드백
4. **답변 있음(HITL)** → 해당 내용을 LLM을 거쳐 고객에게 안내

### 2.2 설계 요약

| 단계 | 조건 | 동작 |
|------|------|------|
| RAG/LLM | 검색 결과 없음 또는 confidence < 임계값 | "해당 내용은 확인이 필요합니다. 잠시만 기다려 주세요." + HITL 요청 발송(question, context, call_id, timeout) |
| HITL | 담당자 응답 수신 (timeout 내) | 응답 텍스트를 LLM에 "고객에게 전달할 문장으로 정리" 요청 후 TTS로 재생 |
| HITL | timeout | "확인이 지연되고 있습니다. 확인되는 대로 연락 드리겠습니다." TTS 재생 후 통화 종료; frontend에 timeout 피드백 |
| 사전 답변 | 지식 있음 | 기존처럼 RAG+LLM 응답만 사용 |

### 2.3 구현 시 필요한 것

- **RAG/LLM 쪽**: confidence 또는 검색 점수/결과 없음 판단 시, 기존 HITL 요청 API와 동일한 형식으로 `hitl_requested` 이벤트 발생 (이미 있을 수 있음).
- **HITL 응답 수신 시**: 해당 call_id에 대해 "담당자 답변" 텍스트를 LLM 한 번 거쳐 고객용 문장으로 정리한 뒤 TTS로 재생.
- **HITL timeout 시**: 정해진 문구 TTS 재생, 통화 종료, frontend에 `hitl_timeout` 등 피드백 (기존 이벤트 활용).
- **Frontend**: 담당자 입력 UI, timeout 표시/피드백은 기존 HITL 플로우와 통합.

### 2.4 외부 참고 (리서치 요약)

- **Confidence 기반 fallback**: 낮은 신뢰도(예: 0.7 미만)일 때 사용자에게 재질문 유도 또는 에스컬레이션 (Rasa 등).
- **Out-of-scope 명시**: "해당 요청은 처리할 수 없습니다" 등 명확한 거절 응답.
- **Human handoff**: 사용자에게 "사람에게 연결할까요?" 선택을 주거나, 시스템이 자동으로 HITL 요청 후 대기.
- **Cascaded decision**: 1차 모델 → 신뢰도 부족 시 상위 모델 또는 사람으로 넘기는 구조.

우리 플로우는 "모른다" 명시 → HITL 요청 → timeout/응답에 따라 문구 재생·종료·피드백으로, 위 패턴과 동일한 방향이다.

---

## 3. 적용한 코드 변경 (2.1·Phase)

- **rtp_transport.py**: `last_tts_duration_sec` / `last_rtp_sent_sec` / `bytes_sent` / `duration_sec` 정의 주석 추가, 로그 note를 "큐에 넣은 양" 기준으로 정리.
- **rag_processor.py**: `event.wait()` 해제 직후 `await asyncio.sleep(0.05)` 추가 후 `KEY_LAST_RTP_SENT_SEC` pop하여 Phase1→Phase2 시간 계산이 RTP 기준으로 안정적으로 동작하도록 함.
