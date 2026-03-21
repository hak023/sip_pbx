# AI 응대 통화 로그 점검 (2026-03-10 10:14:36 ~ 10:15:16)

인사말까지 듣고 끊은 통화(1003 → 1004, AI 터치오버) 로그 분석 요약입니다.

---

## 1. 이슈 점검 요약

### 1.1 심각 이슈 (인사말 구간 음성 깨짐과 직접 연관)

| 이슈 | 로그 시점 | 내용 |
|------|-----------|------|
| **tts_rtp_duration_mismatch** | 10:14:48.863 (Phase1) | Notifier 기준 TTS 재생 길이 **7.435초**인데, RTP로 보낸 양은 **5.601초**분만 전송됨 → **약 24.7% 부족** (약 1.8초 분량이 전화기로 안 나감) |
| **tts_rtp_duration_mismatch** | 10:14:57.225 (Phase2) | TTS **12.335초**인데 RTP 전송분 **10.641초** → **약 13.7% 부족** |
| **rtp_tts_queue_empty_timeout** | 10:14:54.421 | 인사말 Phase1 재생 중 **PCM 큐가 1초간 비어 있음** → 이 구간에서 **끊김/깨짐 발생 가능** (packets_sent: 283) |
| **rtp_tts_queue_depleted** | 10:15:05.946 | PCM 큐 소진 — 다음 TTS 청크 지연 시 끊김/깨짐 가능 (packets_sent: 800) |
| **rtp_tts_queue_empty_timeout** 반복 | 10:15:07 ~ 10:15:15 | empty_timeouts 2~10까지 누적 — Phase2 종료 후 큐가 반복해서 비어 있음 |

→ **인사말할 때 RTP가 덜 전달되어 음성이 약간 깨진 현상**은 위 두 가지가 원인으로 보는 것이 타당합니다.  
- TTS 음원 길이 대비 RTP로 나간 양이 24.7% 부족 (Phase1).  
- Phase1 재생 중 큐가 1초간 비어서 그 구간에서 끊김/깨짐.

### 1.2 기타 이슈

| 이슈 | 로그 | 비고 |
|------|------|------|
| **get_organization_manager_deprecated** | 10:08:25.051 | `create_org_manager(owner, knowledge_service)` 사용 권장 — 기능에는 영향 없음 |
| **no_answer_timeout_activating_ai** 중복 로그 | 10:14:46.288 2회 | 동일 이벤트가 두 번 기록됨 — 로그 정리 시 한 번만 남기면 됨 |

### 1.3 정상 동작으로 보이는 부분

- INVITE → 180 Ringing → 10초 후 AI 터치오버 → 200 OK → ACK → Pipecat 파이프라인 기동
- STUN Binding Request 전송, RTP 소켓 바인딩(caller 10000/10001, callee 10004/10005)
- 인사말 Phase1/Phase2 텍스트 생성 및 TTS 입력
- 통화 종료: BYE 수신 → 정리 → CDR 기록, 녹음/STT 후처리 완료
- `rtp_tts_packets_dropped`: 0, `rtp_tts_send_errors`: 0 → 패킷 드롭/전송 오류는 없음

---

## 2. 인사말 구간 RTP 부족 상세 (음성 깨짐 원인)

### 2.1 타임라인 (인사말 구간)

| 시점 | 이벤트 |
|------|--------|
| 10:14:46.904 | TTS 첫 오디오 청크 수신 (Phase1 시작) |
| 10:14:46.916 | Phase1 문장: "안녕하세요. 기상청입니다. 날씨와 관련된 문의를 도와드리겠습니다." |
| 10:14:47.749 | **첫 TTS 오디오 RTP 전송** (TTS 수신 후 약 0.85초 지연) |
| 10:14:47.757 | 첫 RTP 패킷 전송 성공 (dest 10.66.68.83:42027) |
| 10:14:48.862 | Notifier EndFrame: **TTS 재생 길이 7.435초**, audio_frame_count 104 |
| 10:14:48.862 | Output EndFrame: **response_bytes 179236** → duration_sec 계산값 **5.601초** |
| 10:14:48.863 | **tts_rtp_duration_mismatch** — 24.7% 부족 (7.435 vs 5.601초) |
| 10:14:54.421 | **rtp_tts_queue_empty_timeout** — PCM 큐 1초간 비어 있음 (packets_sent 283) |
| 10:14:55.295 | greeting_phase_gap: phase1_audio_sec=7.44, **phase1_rtp_sent_sec=5.6**, gap_sec=6.4 |
| 10:14:55.295 | Phase2 전송 시작 |

### 2.2 원인 정리

1. **Notifier(음원 길이) vs Output(큐에 넣은 PCM 바이트) 불일치**  
   - 로그 메시지: *"sample_rate 차이 또는 프레임 누락 가능"*  
   - TTS는 7.435초 분량인데, RTP 쪽으로는 5.601초분만 큐에 반영됨 → **일부 TTS 프레임이 큐에 안 들어갔거나, 샘플레이트/채널 해석이 다를 가능성**.

2. **인사말 재생 중 PCM 큐 공백**  
   - Phase1 재생 중(10:14:54.421) 큐가 1초간 비어 있음 → 그 구간에 RTP로 나갈 데이터가 없어 **실제로 끊김/깨짐**이 났을 가능성이 큼.

3. **Phase2에서도 동일 패턴**  
   - Phase2도 tts_rtp_duration_mismatch 13.7% → 전반적으로 **TTS 출력량 대비 RTP 전송량이 계속 부족**한 구조로 보임.

### 2.3 권장 조치 (적용 완료)

1. **TTS → RTP 경로의 샘플레이트/프레임 계산 일치** ✅  
   - Notifier 쪽 재생 길이(또는 frame count × frame_duration)와 Output 쪽 `response_bytes`로 계산한 `duration_sec`가 일치하도록  
   - **적용**: Output에서 프레임별 `sample_rate`로 재생 길이 누적(`_response_duration_sec`), Notifier와 동일 기준으로 `KEY_LAST_RTP_SENT_SEC` 설정. (`rtp_transport.py`)

2. **PCM 큐 비는 구간 제거** ✅  
   - **적용**: `_pipecat_pcm_queue` maxsize 90 → **150**, 백로그 경고 70 → 120. (`rtp_relay.py`, `TTS_RTP_AND_STT_QUEUE_DESIGN.md`)

3. **로그로 재검증**  
   - 수정 후 같은 시나리오(인사말만 듣고 끊기)에서:  
     - `tts_rtp_duration_mismatch` 제거 또는 diff_ratio_pct 0%에 가깝게,  
     - 인사말 구간에 `rtp_tts_queue_empty_timeout`이 없도록 확인.

**참고 코드**
- `sip-pbx/src/ai_voicebot/pipecat/rtp_transport.py`: `SIPPBXOutputTransport` — `_response_bytes` 누적, `duration_sec = bytes / (PIPECAT_SAMPLE_RATE*2)`, Notifier와 비교해 mismatch 시 `tts_rtp_duration_mismatch` 로깅.
- `sip-pbx/src/media/rtp_relay.py`: `send_audio_to_caller()` — PCM 큐에 투입, `_pipecat_tts_sender_loop`에서 20ms 간격 RTP 전송.
- `sip-pbx/docs/design/TTS_RTP_AND_STT_QUEUE_DESIGN.md`: PCM 큐 `maxsize=90` 등.

---

## 3. 통화 종료 시 RTP/녹음 요약

- **rtp_tts_packets_sent**: 817  
- **rtp_tts_packets_dropped**: 0  
- **rtp_tts_send_errors**: 0  
- **callee (AI) 녹음**: 817 frames, 259870 bytes, 약 16.24초 (STT 기준)  
- **caller 녹음**: 1368 frames, 437760 bytes  
- **mixed.wav**: 27.36초  
- **STT 전사**: callee 49 words, caller 0 words — 인사말만 듣고 끊어서 caller 발화 없음.

---

**[토큰 정보: 컨텍스트에 미제공]**
