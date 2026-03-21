# TTS → 큐 → RTP 재생 로직 구조 검토

인사말 구간 RTP 부족/끊김 이슈(APP_LOG_AI_CALL_20260310_101436_ANALYSIS.md)에 대한 권장 조치 반영 후, **TTS에서 생성한 패킷을 큐에 넣고 RTP로 재생되는 전체 구조**를 검토한 문서입니다.

---

## 1. 전체 흐름 (데이터 경로)

```
[Pipecat Pipeline]
  TTS (Google 등)
    → TTSAudioRawFrame / OutputAudioRawFrame (audio=bytes, sample_rate=16k)
    → TTSCompleteNotifier (재생 길이 누적, EndFrame 시 event.set())
    → SIPPBXOutputTransport (process_frame)
         │
         ├─ _response_bytes += len(audio_data)
         ├─ _response_duration_sec += len(audio)/(sample_rate*2)  ← Notifier와 동일 기준
         └─ send_audio_to_caller(pcm_data, sample_rate)
                │
                ▼
[RTP Relay Worker]
  _pipecat_pcm_queue.put_nowait(pcm_data)   ← PCM 청크만 적재 (16kHz 16bit 기대)
                │
                ▼
  _pipecat_tts_sender_loop (단일 태스크, 20ms 패이싱)
    │  get(timeout=1.0) → pcm_data
    │  _TTS_FLUSH 시 큐 드레인 (새 TTS만 재생)
    │  build_packets(pcm_data, 16000) → 16k→8k 리샘플, G.711 인코딩, 20ms 단위 RTP
    └  패킷마다 sendto() 후 asyncio.sleep(0.02)
                │
                ▼
  [UDP] RTP → Caller (전화기)
```

- **생산자**: Pipecat 파이프라인(Output)이 TTS 오디오 프레임을 받을 때마다 `send_audio_to_caller()`로 PCM 청크를 **한 번에 하나** `put_nowait` 한다.
- **소비자**: `_pipecat_tts_sender_loop` 하나가 `get(timeout=1.0)`으로 청크를 꺼내고, **20ms 간격**으로 RTP 패킷을 한 개씩 전송한다.
- **큐**: `asyncio.Queue(maxsize=150)`. TTS가 짧은 시간에 많은 청크를 넣어도, 발송 루프는 20ms당 1패킷만 보내므로 큐에 PCM이 쌓였다가 순차 소비된다.

---

## 2. 샘플레이트·포맷 정리

| 구간 | 포맷 | 비고 |
|------|------|------|
| TTS → Output | 16kHz 16-bit mono PCM (Pipecat 표준) | `PIPECAT_SAMPLE_RATE = 16000` |
| PCM 큐 | 동일 (bytes 그대로 적재) | 리샘플 없음 |
| build_packets 입력 | 16kHz 기대 | `build_packets(pcm_data, 16000)` 고정 |
| RTP (G.711) | 8kHz, 20ms = 160 samples = 160 bytes | 16k→8k 리샘플 후 G.711 인코딩 |

- **재생 길이(초) 계산**: `bytes / (sample_rate * 2)` (16bit = 2 bytes per sample).
- **Output**은 프레임별 `sample_rate`로 `_response_duration_sec`를 누적해, **TTSCompleteNotifier와 동일한 기준**으로 `KEY_LAST_RTP_SENT_SEC`를 넣어 mismatch 경고를 줄인다.

---

## 3. 이슈 없음으로 확인된 부분

1. **단일 발송 루프 + 20ms 패이싱**  
   - RTP 패킷을 한 스레드에서만 보내고, 패킷 간격을 20ms로 고정해 지터·버스트를 막는다.
2. **PCM 큐만 사용**  
   - TTS는 RTP 패킷이 아니라 PCM 청크만 넣고, 패킷 분할·전송은 발송 루프에서만 하므로 큐 적체 형태가 단순하다.
3. **새 TTS 시 플러시**  
   - `LLMFullResponseStartFrame` 수신 시 `request_tts_flush()`로 기존 PCM을 비우고, 이전 발화와 겹치지 않게 한다.
4. **G.711 변환**  
   - `audio_utils.resample` + `encode_g711`로 16k→8k→G.711이 한 방향으로만 이루어지며, `RTPPacketBuilder`가 20ms 단위로 잘라 RTP 헤더를 붙인다.

---

## 4. 보완한 이슈 (권장 조치 반영)

### 4.1 Notifier vs Output 재생 길이 불일치 (tts_rtp_duration_mismatch)

- **원인**: Output은 `duration_sec = bytes / (16000*2)`만 사용했고, Notifier는 프레임별 `sample_rate`로 재생 길이를 누적할 수 있어, 샘플레이트나 프레임 해석이 다르면 차이가 났음.
- **조치**: Output에서도 **프레임별 `sample_rate`**로 재생 길이를 누적(`_response_duration_sec += len(audio)/(sr*2)`). EndFrame 시 `KEY_LAST_RTP_SENT_SEC`에 이 누적값을 넣어 Notifier와 같은 기준으로 맞춤.
- **파일**: `sip-pbx/src/ai_voicebot/pipecat/rtp_transport.py`.

### 4.2 인사말 구간 PCM 큐 공백 (rtp_tts_queue_empty_timeout)

- **원인**: 인사말처럼 TTS가 짧은 시간에 많이 올 때, 큐 크기(90 청크)가 상대적으로 작아 1초 대기(empty timeout)가 발생할 수 있었음.
- **조치**: `_pipecat_pcm_queue` **maxsize 90 → 150**으로 확대. 백로그 경고 임계치는 70 → 120으로 조정.
- **파일**: `sip-pbx/src/media/rtp_relay.py`, `sip-pbx/docs/design/TTS_RTP_AND_STT_QUEUE_DESIGN.md`.

---

## 5. 잔여 리스크 및 권장 사항

1. **TTS가 16kHz가 아닌 샘플레이트로 내보낼 때**  
   - 현재 발송 루프는 `build_packets(pcm_data, 16000)`만 사용한다. 파이프라인 상류에서 16k로 정규화하지 않고 24k 등이 오면, RTP 쪽에서 잘못된 리샘플로 재생 길이/음질이 틀어질 수 있다.  
   - **권장**: 파이프라인에서 Output 직전에 16k로 통일하거나, `send_audio_to_caller`에서 샘플레이트를 전달해 발송 루프가 `build_packets(pcm_data, sr)`를 호출하도록 확장 검토.

2. **큐 가득 시 드롭**  
   - `put_nowait` 실패 시 청크 1개를 버리고 `rtp_tts_packets_dropped`를 올린다. 인사말 버스트가 매우 크면 드롭이 나올 수 있으므로, 로그로 모니터링하고 필요 시 maxsize를 더 늘리는 것을 고려.

3. **empty_timeout 로그**  
   - 1초 동안 큐가 비면 `rtp_tts_queue_empty_timeout`이 찍히고, 그 구간에는 RTP로 나갈 데이터가 없어 끊김/깨짐이 날 수 있다. maxsize 150으로 완화했으나, 여전히 발생하면 TTS 청크 크기·도착 간격을 확인하는 것이 좋다.

4. **통화 종료 시 발송 루프 정리**  
   - `stop_pipecat_mode()`에서 `_pipecat_pcm_queue.put_nowait(None)`으로 센티넬을 넣어 발송 루프를 종료한다. BYE 후에도 해당 통화의 empty_timeout 로그가 반복되면, 루프/태스크 취소가 해당 call에 대해 확실히 이뤄지는지 확인할 것.

---

## 6. 참고 코드 위치

| 역할 | 파일 | 내용 |
|------|------|------|
| Output: 바이트/재생길이 누적, 큐 투입 | `src/ai_voicebot/pipecat/rtp_transport.py` | `SIPPBXOutputTransport.process_frame`, `send_audio_to_caller` 호출 |
| PCM 큐·발송 루프·플러시 | `src/media/rtp_relay.py` | `enable_pipecat_mode`, `_pipecat_tts_sender_loop`, `send_audio_to_caller`, `request_tts_flush` |
| RTP 패킷 생성 (16k→8k, G.711) | `src/ai_voicebot/pipecat/audio_utils.py` | `RTPPacketBuilder.build_packets` |
| 설계 요약 | `docs/design/TTS_RTP_AND_STT_QUEUE_DESIGN.md` | PCM 큐 + 단일 발송 루프, 플러시, maxsize |

---

**[토큰 정보: 컨텍스트에 미제공]**
