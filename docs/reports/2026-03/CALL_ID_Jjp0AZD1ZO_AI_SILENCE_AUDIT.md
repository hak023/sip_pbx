# AI 무응답 점검: `call_id` Jjp0AZD1ZO

- **작성일**: 2026-03-25  
- **로그**: `sip-pbx/logs/app.log`  
- **현상**: AI 봇 응대가 되지 않음 (발화 없음·무음에 가까운 경험)

## 결론 요약

통화는 **AI 모드로 정상 전환**되었고 **발신 RTP → STT 입력 큐 → 파이프라인**까지는 동작했습니다.  
그러나 **TTS → RTP로 나가는 패킷이 0건**이었고, **인사(`send_greeting`) 경로는 `rag_llm` 쪽 StartFrame 60초 타임아웃**으로 실패했습니다. 사용자 입장에서는 AI가 말하지 않는 것으로 보입니다.

## 타임라인 (발췌)

| 시각 (로그) | 내용 |
|-------------|------|
| 04:19:23 | INVITE, 미디어/RTP 워커 기동 |
| 04:19:33 | 부재 타이머로 AI 인수, Pipecat 파이프라인 기동, `input_transport_startframe_received` |
| 04:19:33~04:20:03 | `caller_rtp_to_stt_input` / `input_audio_frame_to_pipeline` 지속 (수백~1500+ 패킷) |
| 04:19:36~ | `rtp_tts_queue_empty_timeout`, **`packets_sent`: 0** 반복 → **TTS RTP 미출력** |
| 04:20:04 | `bye_received` (발신 측 BYE) |
| 04:20:29 | `pipecat_pipeline_cancel_timeout` (25s) |
| 04:20:33 | **`rag_llm_pipecat_start_timeout`**, `context`: **`send_greeting`**, note: StartFrame 미도달 |
| 04:20:33 | `send_greeting_aborted_no_startframe`, `rtp_relay_stopped`에서 **`rtp_tts_packets_sent`: 0** |

## 기술적 해석

1. **Input Transport의 StartFrame은 수신됨**  
   `input_transport_first_frame` / `input_transport_startframe_received` 존재 → 입력 쪽 파이프라인 시작 신호는 도달.

2. **인사 TTS는 별도 대기 조건 실패**  
   `rag_llm_pipecat_start_timeout`은 **Rag/LLM Pipecat 경로**에서 `send_greeting` 시 **StartFrame이 일정 시간 내 도달하지 않으면** 프레임이 드롭되고 TTS/RTP가 나가지 않는다는 로그 설명과 일치합니다.

3. **통화 전체 TTS RTP 0**  
   `rtp_relay_stopped`의 `rtp_tts_packets_sent: 0`으로, 인사뿐 아니라 **해당 콜에서 TTS 기반 RTP가 한 번도 송신되지 않음**이 확인됩니다.

4. **STT 최종 → RAG 로그 부재**  
   동일 `call_id`로 `transcription_frame_received` 등이 이 구간에 없어, 사용자 발화가 STT 최종까지 가지 않았거나(무음·VAD·STT 이슈), 이 콜은 **응답 생성·TTS까지 도달하지 못한 상태**로 종료된 것으로 볼 수 있습니다.

5. **동시 AI 콜**  
   `ai_mode_activated` 시점에 `ai_enabled_calls`: **3** — 다통화 부하 시 타이밍/큐 지연과 겹치면 `send_greeting` StartFrame 대기 실패 가능성이 있습니다 (가설, 로그만으로 단정 불가).

## 권장 후속 조치 (개발)

- `send_greeting`과 일반 `rag_llm` 파이프라인의 **StartFrame 전파 순서**·**다중 콜 동시 실행** 시 블로킹 여부 코드 점검.  
- 동일 시각대 **다른 `call_id`** 로그와 CPU/이벤트 루프 지연 여부 대조.  
- 재현 시 `rag_llm_pipecat_start_timeout` 직전 **프로세서별 프레임 로그** 추가 검토.

## 사용자 관점

“갑자기 AI가 안 된다”기보다, **이 통화에서는 AI 음성이 한 번도 나가지 않은 상태**로 약 30초 후 상대가 끊은 것에 가깝습니다.
