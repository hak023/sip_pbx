# app.log AI 응대 내역 점검 (요약)

통화 로그 기준으로 **인사말 Phase1/Phase2만 들리고, 이후 "네, 알겠습니다" 등이 안 들렸다**는 현상과 **STT** 관련을 정리한 문서입니다.

---

## 1. 이번 통화에서 확인된 흐름

| 시점 | 이벤트 | 비고 |
|------|--------|------|
| 17:14:27 | Phase1 인사말 TTS 시작, tts_first_audio_sent_to_rtp | 정상 |
| 17:14:29 | Phase1 EndFrame, tts_rtp_sent_for_response (166436 bytes) | 정상 |
| 17:14:33~34 | rtp_tts_queue_empty_timeout 2회 | PCM 큐가 1초×2 비어 있음 (Phase1 종료 ~ Phase2 시작 구간) |
| 17:14:35 | greeting_phase2_sent, Phase2 "어떤 것이 궁금하신가요?" | 사용자가 마지막으로 들은 구간 |
| 17:14:35.409 | tts_first_audio_sent_to_rtp (Phase2) | Phase2 TTS → RTP 전송 시작 |
| 17:14:37.155 | **rag_llm_user_input** text=**"Here."** | 실시간 STT 결과 (영어 인식) |
| 17:14:43.464 | process_utterance_complete, langgraph_agent_result | 응답: "네, 알겠습니다. 더 필요하시면 말씀해 주세요." |
| 17:14:43.467 | tts_text_input "네, 알겠습니다." / "더 필요하시면 말씀해 주세요." | TTS 입력까지 정상 |
| 17:14:43.826 | **tts_first_audio_sent_to_rtp** (이 응답) | "네, 알겠습니다" 응답의 TTS → RTP 전송 시작 |
| 17:14:44.520 | output_endframe_processed, response_bytes=133144 | 해당 응답분 PCM 큐 투입 완료 |
| 통화 종료 | rtp_tts_packets_sent=**823** | RTP 패킷은 823개 전송됨 |

**정리**: 서버 로그상으로는 **"네, 알겠습니다"** 응답도 TTS 생성 후 RTP 큐에 넣었고**(tts_first_audio_sent_to_rtp, response_bytes=133144)**, 통화 종료 시 **rtp_tts_packets_sent=823**으로 패킷도 전송된 상태입니다. 즉, 인사말 이후 응답까지 **백엔드에서는 TTS→RTP 경로가 한 번 더 수행된 것으로 보입니다.**

---

## 2. 오류·이슈 정리

### 2.1 STT 인식 결과 ("Here.")

- **현상**: 실시간 STT가 사용자 발화를 **"Here."** 로만 인식함.
- **가능 원인**  
  - 한글 발화를 영어로 오인식 (ko-KR 설정이어도 짧은 발화·노이즈에서 발생 가능).  
  - 발화가 짧거나 불명확한 경우.
- **권장**  
  - STT 설정에서 `language_code` 가 **ko-KR** 인지 재확인.  
  - 동일 문장을 여러 번 말해 보며 실시간 STT 결과 로그(`rag_llm_user_input`) 확인.  
  - 필요 시 STT 후처리/필터(한글 우선, 최소 길이 등) 검토.

### 2.2 RTP/TTS 음 뭉개짐·끊김 (rtp_tts_queue_empty_timeout)

- **현상**: `rtp_tts_queue_empty_timeout`, `rtp_tts_queue_depleted` 로그 시 PCM 큐가 비어 구간에서 음성 끊김/뭉개짐 가능.
- **조치**: TTS→RTP PCM 큐 `maxsize`를 30 → 90으로 확대해 버퍼 여유 확보. 백로그 경고 임계치는 70으로 조정.
- **로그**: `rtp_tts_queue_empty_timeout`(empty_timeouts), `rtp_tts_sender_resumed_after_empty`, `rtp_tts_queue_depleted` 로 끊김 구간 확인.

### 2.3 output_audio_frame_skipped (InputAudioRawFrame) — 정상 동작

- **현상**: 로그에 `output_audio_frame_skipped`, `frame_type=InputAudioRawFrame` 다수 출력.
- **의미**: **발신자(caller) 음성**은 에코 방지를 위해 **의도적으로** RTP로 보내지 않음.  
  → TTS 음성이 빠진 것이 아니라, caller 음성을 다시 caller에게 보내지 않는 정상 동작.
- **조치**: 해당 경우에는 **경고 로그를 남기지 않도록** 수정함 (InputAudioRawFrame 스킵 시 로그 제외).

### 2.4 인사말 이후 음성이 안 들렸다면 (가능 원인)

서버 로그상으로는 "네, 알겠습니다" 구간도 TTS → 큐 → RTP 전송까지 진행된 것으로 보이므로, **전화기/단말·네트워크·코덱** 쪽을 의심할 수 있습니다.

- **RTP 수신**: 같은 구간에 **rtp_tts_queue_empty_timeout** 이 있어, 그 직전·직후에 짧게 끊김 구간이 있을 수 있음.  
  → 사용자가 “그때부터 안 들렸다”고 느낄 수 있음.
- **단말/코덱**: G.711(PCMU) 수신 지원, 버퍼/재생 지연, 음소거 등 확인.
- **네트워크**: 패킷 손실, 지연, 방화벽/NAT으로 RTP 차단 여부 확인.

추가로 **rtp_tts_sender_resumed_after_empty**, **rtp_tts_queue_depleted** 로그가 있으면, 그 시점 전후로 PCM 큐가 비는 구간이 있어 끊김이 발생했을 수 있습니다.

---

## 3. 로그로 확인하는 방법

- **STT 결과**: `rag_llm_user_input` (실시간), `stt_transcript_saved` (통화 종료 후 전사).
- **TTS → RTP**: `tts_first_audio_sent_to_rtp`, `output_endframe_processed`, `tts_rtp_sent_for_response`, `rtp_sender_session_end`(empty_timeout_count 포함).
- **끊김 가능 구간**: `rtp_tts_queue_empty_timeout`, `rtp_tts_sender_resumed_after_empty`, `rtp_tts_queue_depleted`.
- **STT 한 번만 나올 때**: `transcription_frame_received` (seq), 자세한 점검은 [STT_PIPELINE_DEBUG.md](STT_PIPELINE_DEBUG.md) 참고.

위 이벤트로 “STT는 됐는데 인식만 이상한지”, “TTS/RTP는 나갔는데 단말에서 안 들린 건지”를 구분해 볼 수 있습니다.
