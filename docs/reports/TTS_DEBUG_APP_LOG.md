# TTS 제대로 나가지 않았던 문제 — 로그 기반 디버깅 리포트

**기준 로그**: `sip-pbx/logs/app.log`  
**대상 통화**: YCYrz6cVN4 (AI 터치다운)  
**분석 일자**: 2026-02-21

---

## 1. 요약

로그 상으로 **TTS가 “안 나간” 것”은 두 가지로 나뉜다.**

| 현상 | 원인 | 비고 |
|------|------|------|
| **사용자가 들은 말이 짧음** | LLM이 15자만 응답("안녕하세요. 기상청 AI 통") → TTS도 그만큼만 재생(~2.56초). 주차 문의에 대한 본문 답변이 아님. | **의도 분류 수정으로 해소** (인사+질문 → question으로 분류해 RAG 경로 타도록 이미 반영됨). |
| **Phase1 인사말이 일부만 RTP로 전송** | TTS 쪽 “재생 길이”는 8.156초인데, RTP로 실제 전송된 양은 6.68초. 약 1.5초 분량이 전화기까지 가지 않았을 가능성. | 아래 §2, §3 참고. |

그 외 **409 Stream timed out**은 통화 종료(BYE) 이후 Google 스트리밍 타임아웃으로, TTS 미재생의 직접 원인은 아님(§4).

---

## 2. 로그로 본 TTS ↔ RTP 불일치

### 2.1 Greeting Phase1

| 항목 | 값 | 출처 |
|------|-----|------|
| TTS 재생 길이 (duration_known) | **8.156초** | `tts_duration_known`, `tts_complete_notifier_signalled` |
| RTP로 실제 전송된 양 (duration_sec) | **6.68초** | `tts_rtp_sent_for_response` (bytes_sent: 213772) |

- 213772 bytes @ 16kHz 16bit → 213772/(16000×2) ≈ **6.68초** (RTP 쪽 계산과 일치).
- 8.156초 분량이라면 8.156×16000×2 ≈ **261,120 bytes** 필요.
- 즉, **약 47KB(약 1.5초) 상당 오디오가 TTS 완료 쪽에서는 잡혔는데 RTP 전송 쪽에는 반영되지 않음** → Phase1 인사말 끝 1.5초가 전화기로 안 갔을 가능성.

### 2.2 Greeting Phase2

| 항목 | 값 |
|------|-----|
| duration_known | 22.107초 |
| tts_rtp_sent_for_response duration_sec | 11.52초 |

- Phase2도 **TTS 길이 > RTP 전송 길이** 구조. (Phase1/2가 연속 재생이라 구간 구분이 RTP 로그와 1:1 대응하지 않을 수 있음.)

### 2.3 LLM 답변 TTS (짧은 응답)

| 항목 | 값 |
|------|-----|
| LLM response_len | 15자 ("안녕하세요. 기상청 AI 통") |
| tts_duration_known | **30.672초** (해당 구간 누적값으로 해석 시 이상함) |
| tts_rtp_sent_for_response | **2.56초**, 81932 bytes |

- 2.56초만 RTP로 전송된 것은 **15자 TTS와 일치** (짧은 응답이라 짧게 나가는 것이 정상).
- 30.672초는 **이전 Phase1+Phase2 누적이 리셋되지 않았거나, EndFrame 경계 처리 이슈** 가능성 있음.  
  → TTSCompleteNotifier가 `LLMFullResponseEndFrame` 수신 시에만 `_current_duration_sec`를 리셋하므로, **해당 응답 직전에 StartFrame/EndFrame이 기대대로 오지 않으면** 누적이 꼬일 수 있음.

---

## 3. 원인 가설 및 대응

### 3.1 Phase1 ~1.5초가 RTP로 안 간 경우

- **가설**:  
  - Greeting Phase1은 RAG에서 곧바로 텍스트를 넣어 주는데, 이 경로에서 **LLMFullResponseStartFrame**을 보내지 않을 수 있음.  
  - 그 경우 Output Transport는 “이전 응답”과 같은 구간으로 인식해, Phase1 초반 일부를 이전 응답의 마지막으로 묶거나, 프레임 순서/타이밍 때문에 일부가 RTP에 반영되기 전에 다음 구간으로 넘어갔을 수 있음.  
  - 또는 Notifier와 Output 사이에 **같은 프레임을 다르게 해석**(예: sample_rate, 채널)하거나, 비동기로 인한 **일부 프레임 유실** 가능성.

- **대응** (구현 반영 권장):  
  - RAG processor에서 **Greeting Phase1/Phase2를 보낼 때도** LLM 응답과 동일하게 **LLMFullResponseStartFrame**을 먼저 보내고, 해당 Phase가 끝날 때 **LLMFullResponseEndFrame**이 한 번만 나가도록 하기.  
  - `tts_rtp_sent_for_response`와 `tts_duration_known`을 같은 “응답” 단위로 맞추고, **둘의 차이가 10% 이상이면 WARNING 로그**를 남겨, 재현 시 추적하기 쉽게 하기.

### 3.2 “짧게만 들림”에 대한 정리

- **직접 원인**: LLM이 인사만 하도록 분류되어 15자만 생성 → TTS는 그만큼만 재생.  
- **조치**: 이미 **classify_intent**에서 “안녕” + 질문/요청 패턴이 있으면 **question**으로 분류하도록 수정되어, 동일 발화 시 RAG를 타고 본문 답변이 나와야 함.  
- **추가 점검**: 동일 시나리오로 다시 통화해, 주차 문의에 대한 **긴 답변 + 긴 TTS**가 나오는지, 그리고 그때 `tts_rtp_sent_for_response`와 `tts_duration_known`이 서로 비슷한지 확인.

---

## 4. 409 Stream timed out

로그 끝부분:

```text
[PIPECAT] ... WARNING ... ErrorFrame#0(error: ... 409 Stream timed out after receiving no more client requests.
```

- **의미**: 통화가 BYE로 종료된 뒤, Google TTS/STT 스트리밍이 “더 이상 클라이언트 요청이 없음”으로 타임아웃된 상황.
- **영향**: 이미 BYE 처리된 이후이므로 **TTS가 안 나간 이유는 아님**. 정리 단계에서 나는 정상적인 타임아웃에 가깝다.
- **권장**:  
  - 통화가 이미 종료된 상태에서 나는 409는 **치명적 오류로 간주하지 않기**.  
  - 가능하면 Pipecat/Google 클라이언트에서 **BYE 또는 pipeline teardown 이후 409는 로그 레벨을 낮추거나 무시**하도록 처리 (구현 가능한 경우).

---

## 5. 구현 체크리스트

- [x] **의도 분류**: 인사+질문 → question (이미 반영).
- [x] **Greeting 구간에 StartFrame/EndFrame 명시**: RAG processor에서 Phase1/Phase2 전에 StartFrame, Phase 끝에 EndFrame 한 번씩 보내기 (이미 반영).
- [x] **TTS vs RTP 불일치 경고**: `tts_rtp_sent_for_response` 로그 시, 동일 응답에 대한 `last_tts_duration_sec`와 비교해 차이 >10%면 WARNING 로그.
- [x] **Output이 TTSAudioRawFrame도 RTP 전송·집계**: Notifier는 모든 오디오 프레임을 누적하는데 Output이 `OutputAudioRawFrame`만 처리하면, TTS가 `TTSAudioRawFrame`만 내보낼 때 ~1.5초 분량이 RTP로 안 나가서 duration_known(8.156초) > tts_rtp_sent(6.68초)가 됨. → Output에서 `TTSAudioRawFrame`도 동일하게 전송·집계하도록 반영.
- [x] **Phase 간격을 RTP 전송량 기준으로**: Phase1 완료 후 대기 시간을 “TTS 합성 길이(play_sec)”가 아니라 “RTP로 실제 전송된 시간(rtp_sent_sec)” 기준으로 사용하도록 변경. `greeting_phase_gap_tts_complete_signalled`에 `phase1_rtp_sent_sec` 로그 추가.
- [ ] **409**: 통화 종료 후 409는 비치명적 처리 또는 로그 완화 (가능 시).

---

## 6. 추가 고민 사항 (로그 수치 의미·Phase 간격)

### 6.1 “전달된 text” vs duration_known vs duration_sec — 왜 다른가

| 로그/개념 | 의미 | 비고 |
|-----------|------|------|
| **전달된 text** | RAG가 TTS에 넣은 문장. `rag_llm_greeting_phase1` / `greeting_phase1_sent`의 `text` 필드. | Phase1 전체 문장("안녕하세요. 기상청 AI 통화 비서입니다. 무엇을 도와드릴까요?")이 전달됨. |
| **duration_known** (`tts_duration_known`) | **TTSCompleteNotifier**가 본 오디오 프레임의 총 길이(초). TTS가 합성한 오디오가 파이프라인을 통과한 양. | 8.156초 = Notifier를 지나간 바이트를 16kHz·16bit로 환산한 값. |
| **duration_sec** (`tts_rtp_sent_for_response`) | **SIPPBXOutputTransport**가 RTP로 실제 전송한 바이트를 초로 환산한 값. | 6.68초 = 전화기로 나간 양. Notifier와 Output이 다른 프레임 타입만 처리하면 둘이 달라짐. |

- **Phase1이 “1초만 들렸다”**면: (1) 서버→RTP는 6.68초만 보냈고(또는 수정 후 8.156초에 가깝게 보냄), (2) 그 중에서도 **네트워크/전화기** 구간에서 추가 유실이 있으면 실제 들리는 시간은 더 짧아질 수 있음. 즉 “전달된 text”는 전체 문장인데, **duration_known**은 서버 파이프라인 상 합성 길이, **duration_sec**는 RTP로 나간 길이이고, **실제 들리는 길이**는 RTP보다 짧을 수 있음.

### 6.2 Phase1–Phase2 시간 차이: 로그 8.96초 vs 체감 11초

- **로그의 gap_sec(8.96초)**  
  - **의미**: Phase1에 대한 `tts_complete_notifier_signalled`(이벤트 발생) **이후**에, Phase2를 보내기 전까지 **서버가 sleep한 시간**.  
  - 계산: `phase1_audio_sec(8.16) + PHASE_GAP_BUFFER(0.8) ≈ 8.96초`.  
  - 즉 “Phase1 재생이 끝날 때까지 기다리자”는 의도로 넣은 **대기 시간**이다.

- **사용자가 체감한 ~11초**  
  - **의미**: “Phase1이 끝나고(또는 끊기고) ~ Phase2가 들리기 시작하기까지”의 **침묵 구간**.  
  - 여기에는 (1) Phase1이 **실제로 1초만 들렸다**면, Phase1 “끝” 시점이 서버가 생각한 8초 시점보다 훨씬 앞서고, (2) 그 다음 서버가 8.96초 sleep한 뒤 Phase2를 보내므로, **체감 침묵 = (Phase1이 끊긴 시점 ~ Phase2 첫 RTP 도착 시점)** ≈ 1초 끝 + 8.96초 대기 + Phase2 첫 패킷 지연 ≈ 10~11초가 될 수 있음.

- **정리**  
  - **gap_sec**는 “서버가 잠든 시간”이지 “사용자 침묵 구간”을 직접 재는 값이 아님.  
  - RTP 전송량 기준 대기(`phase1_rtp_sent_sec` 사용)로 바꿔도, 네트워크/전화기에서 Phase1이 짧게만 들리면 체감 침묵은 그만큼 길어짐.  
  - 추가로 **wall-clock**으로 “Phase1 첫 RTP 시점”과 “Phase2 첫 RTP 시점” 차이를 로그에 남기면, 체감 11초와 직접 비교하기 쉬움 (추후 로그 확장 권장).

이 문서는 `app.log` 기준 TTS 디버깅 결과와, "TTS가 제대로 나가지 않았던" 현상에 대한 원인·대응을 정리한 것입니다.
