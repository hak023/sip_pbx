# RTP 음성 뭉개짐/끊김 이슈 점검 보고서

**목적**: TTS → RTP 구간에서 음이 뭉개지거나 끊기는 현상의 가능 원인을 정리하고, 로그·설정·코드 기준 점검 항목을 제시합니다.

---

## 1. 현재 구조 요약

| 구간 | 설명 |
|------|------|
| TTS 출력 | Pipecat 파이프라인에서 `TTSAudioRawFrame` / `OutputAudioRawFrame` (16kHz PCM) |
| PCM 큐 | `_pipecat_pcm_queue` (maxsize=90, 약 3~4초 분량). TTS가 청크를 `put_nowait` |
| 발송 루프 | `_pipecat_tts_sender_loop`: 큐에서 PCM 1청크 꺼냄 → 16k→8k 리샘플 + G.711 → 20ms당 1 RTP 패킷 전송 |
| 플러시 | 새 TTS 응답 시작 시(`LLMFullResponseStartFrame`) `request_tts_flush()` → 큐 비움 후 새 TTS만 전송 |

---

## 2. 뭉개짐/끊김 발생 가능 원인

### 2.1 PCM 큐 언더런 (가장 유력)

- **현상**: 발송 루프가 1초 동안 큐에서 PCM을 꺼내지 못하면 `rtp_tts_queue_empty_timeout` 로그 발생. 해당 구간에서 단말은 재생할 데이터가 없어 **침묵 또는 끊김**으로 들릴 수 있음.
- **원인**:
  - **Phase/응답 간 갭**: 새 응답 시작 시 플러시로 큐를 비운 뒤, LLM 생성 + TTS 첫 청크가 도착하기까지 지연. 이 구간만큼 큐가 비어 있음.
  - **TTS 생성 지연**: Google TTS 첫 바이트 지연 또는 파이프라인 내 버퍼링으로 PCM 투입이 일시적으로 멈춤.
  - **이벤트 루프 지연**: 동일 스레드에서 LLM/TTS 등 무거운 작업이 돌면 발송 루프의 `get(timeout=1.0)` / `sleep(0.02)` 실행이 밀려 큐 소비가 늦어짐.
- **로그로 확인**: `rtp_tts_queue_empty_timeout`, `rtp_tts_queue_depleted`, `rtp_tts_sender_resumed_after_empty` 빈도·타임스탬프.

### 2.2 플러시 직후 공백

- **현상**: 새 발화로 전환할 때 “이전 음성 끊기고 → 잠깐 침묵 → 새 음성 시작” 구간이 길게 느껴짐.
- **원인**: `LLMFullResponseStartFrame` 수신 시 `request_tts_flush()`로 큐를 비우고, 그 다음 TTS 첫 PCM이 들어오기까지 시간이 걸림.
- **로그**: 플러시 직후 `rtp_tts_queue_empty_timeout` 1~2회 연속 나오면 이 구간에 해당.

### 2.3 TTS → Output 경로 지연/버퍼

- **현상**: TTS는 이미 생성했는데 RTP로는 늦게 들어가서, 재생이 밀리거나 중간에 끊긴 것처럼 들림.
- **원인**: 파이프라인에서 TTS 프레임이 큐에 들어가기 전에 여러 단계(에코 제거, Notifier 등)를 거치는 동안 지연·버퍼링.
- **로그**: `output_endframe_processed`(큐에 넣은 바이트)와 `tts_rtp_sent_for_response` 시점, 그리고 그 구간의 `rtp_tts_queue_empty_timeout` 유무.

### 2.4 큐 백로그 및 드롭

- **현상**: TTS가 한꺼번에 많이 넣고 발송 루프가 따라가지 못하면 큐가 가득 찼을 때 **PCM 청크 드롭** 발생. 해당 구간 음성이 잘려 나가거나 끊김.
- **원인**: `send_audio_to_caller`에서 `put_nowait` 실패 시 `rtp_tts_packets_dropped` 증가. (현재 maxsize=90으로 완화되어 있으나, TTS 버스트가 크면 여전히 가능.)
- **로그**: `pipecat_pcm_queue_full_dropping`, `rtp_tts_packets_dropped`, `rtp_tts_pcm_queue_backlog_high`.

### 2.5 20ms 간격 이탈(지터)

- **현상**: RTP 패킷이 20ms 간격에서 자주 어긋나면 단말 재생 버퍼가 비거나 넘쳐 지터·깨짐으로 들릴 수 있음.
- **원인**: 이벤트 루프 지연, `asyncio.sleep(0.02)` 후 스케줄 지연으로 실제 전송 간격이 들쭉날쭉함.
- **로그**: `rtp_interval_violation` (expected_ms=20, actual_ms=…). 빈도가 높으면 지터 가능성.

### 2.6 네트워크·단말

- **패킷 손실**: UDP이므로 손실 시 해당 20ms 구간이 비거나 단말이 보간 실패 → 끊김/뭉개짐.
- **지연 변동**: 지터가 크면 단말 재생 버퍼 언더런.
- **단말 버퍼**: 버퍼가 작으면 서버에서 조금만 지연되어도 끊김으로 들림.
- **코덱 불일치**: SDP와 실제 전송 코덱(PCMU/PCMA)이 다르면 깨짐. (현재는 codec 일치 가정.)

### 2.7 샘플레이트/리샘플링

- **현재**: TTS 16kHz PCM → `build_packets`에서 8kHz로 리샘플 → G.711 20ms(160샘플) 단위 RTP. 구조상 문제 없음.
- **가능 이슈**: TTS가 16kHz가 아닌 다른 레이트로 올 경우 리샘플 품질·비율이 어긋날 수 있음. (Pipecat Google TTS는 24kHz 등일 수 있음 — 확인 필요.)

### 2.8 RTP 타임스탬프/시퀀스

- **현상**: 플러시 후에도 RTP sequence/timestamp는 리셋하지 않고 이어감. 일부 단말은 갑작스러운 공백 구간에서 재생을 멈추거나 잠깐 끊김으로 처리할 수 있음.
- **현재**: 플러시는 “큐만 비움”이며 SSRC/sequence/timestamp는 유지. 필요 시 플러시 시점에 timestamp를 “이어지는” 값으로만 조정하는 방안 검토 가능.

---

## 3. 로그로 점검할 항목

| 로그 이벤트 | 의미 | 조치 방향 |
|-------------|------|-----------|
| `rtp_tts_queue_empty_timeout` | PCM 큐 1초간 비어 있음 | 큐 크기·TTS 투입 타이밍·플러시 직후 갭 완화 |
| `rtp_tts_queue_depleted` | 한 청크 처리 후 큐가 0이 됨 | 다음 청크 지연 시 곧바로 empty_timeout 가능 → TTS 스트리밍/버퍼 확인 |
| `rtp_tts_sender_resumed_after_empty` | 비어 있다가 새 청크 수신 | 위 두 항목과 함께 “끊김 구간” 위치 파악 |
| `rtp_sender_session_end` | 발송 루프 종료 | `empty_timeout_count` 크면 통화 중 끊김 많았을 가능성 |
| `pipecat_pcm_queue_full_dropping` | PCM 큐 가득 참, 청크 드롭 | maxsize 증가 또는 TTS 버스트 완화 |
| `rtp_interval_violation` | 20ms 간격 이탈 | 이벤트 루프 부하·블로킹 점검 |
| `tts_rtp_duration_mismatch` | Notifier vs 큐 투입량 불일치 | TTS 프레임 누락·sample_rate 불일치 가능성 |

---

## 4. 권장 조치 (우선순위)

1. **로그 수집**: 한 통화 구간에서 위 이벤트의 발생 횟수·시각을 수집해, 끊김 구간과 `empty_timeout`/`depleted`/`resumed`의 대응 관계를 확인.
2. **플러시 직후 완화(옵션)**:
   - 플러시 직후 “프리버퍼” 목표 시간(예: 0.2초)만큼은 empty_timeout을 더 길게 두거나, 첫 TTS 청크가 올 때까지 로그만 남기고 empty_timeout 카운트를 올리지 않도록 예외 처리해, 정상적인 Phase 전환 구간을 “오류”로만 보지 않게 할 수 있음.
3. **큐 크기**: 현재 maxsize=90 유지. 로그에서 `pipecat_pcm_queue_full_dropping`이 나오면 120~150 수준으로 재검토.
4. **TTS 첫 바이트 지연**: Pipecat/Google TTS 설정에서 스트리밍·청크 크기 확인. 가능하면 첫 청크를 더 빨리 받을 수 있는 옵션 검토.
5. **이벤트 루프**: LLM/TTS가 동일 루프를 오래 잡지 않도록(태스크 분리, 청크 단위 yield 등) 이미 되어 있는지 확인. `rtp_interval_violation`이 많으면 여기부터 점검.
6. **네트워크/단말**: 동일 로그로 서버는 정상인데 끊김만 있다면, 패킷 손실률·지연·단말 버퍼 크기 확인.

---

## 5. 참고 코드 위치

- PCM 큐·발송 루프: `src/media/rtp_relay.py` — `enable_pipecat_mode()`, `_pipecat_tts_sender_loop()`, `send_audio_to_caller()`, `request_tts_flush()`
- TTS → 큐 투입: `src/ai_voicebot/pipecat/rtp_transport.py` — `SIPPBXOutputTransport.process_frame()` (TTSAudioRawFrame/OutputAudioRawFrame 처리, LLMFullResponseStartFrame 시 flush 호출)
- RTP 패킷 생성: `src/ai_voicebot/pipecat/audio_utils.py` — `RTPPacketBuilder.build_packets()` (16k→8k 리샘플, G.711, 20ms 단위)

---

*문서 갱신: 로그·원인·조치를 반영한 RTP 뭉개짐/끊김 점검용 요약.*
