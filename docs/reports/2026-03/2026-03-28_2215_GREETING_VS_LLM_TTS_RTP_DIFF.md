# 인사말 vs LLM TTS — RTP/파이프라인 차이 점검

- **작성일**: 2026-03-28 (로컬)
- **상태**: 코드 리뷰 기준 정리 (현장 로그 재현 ID 없음)
- **관련**: `rag_processor.py`, `generate_response.py`, `rtp_relay.py`, `rtp_transport.py`, `pipeline_builder.py`

## 결론 요약

동일 파이프라인(`rag_llm` → `korean_tts_numbers` → `tts` → `transport.output()` → `send_audio_to_caller`)을 쓰지만, **텍스트 입력 형태·타이밍·사전 대기**가 달라 체감상 “LLM 답변 TTS만 ~3초 부근에 RTP가 뭉개진다”로 느껴질 수 있다.

## 1. 텍스트 프레이밍 차이 (가장 큼)

| 구분 | 인사 Phase1/2 | LLM 응답 |
|------|----------------|----------|
| TextFrame 수 | 보통 **1개** (`p1` 또는 `p2` 한 번에) | `response_chunks`: **문장 단위**로 여러 개 가능 |
| 전송 방식 | `Start` → `TextFrame(전체)` → `End` | `Start` → `TextFrame` × N (청크마다 `asyncio.sleep(0.05)`) → `End` |

- 인사: Google TTS에 **한 번의 합성 요청(연속 스트림)** 에 가깝게 들어감.
- LLM: 문장마다 **별도 TextFrame** → TTS 쪽은 **문장 단위로 합성이 이어짐**. 첫 문장 재생 길이가 대략 2~4초면, **그 직후 다음 문장 합성이 붙으면서** 버퍼·큐가 한꺼번에 쌓였다가 나가는 느낌(간격 불균형)이 날 수 있음.

참고: `StreamingTTSGateway`는 현재 `pipeline_builder` 체인에 **포함되어 있지 않음** (`pipeline_built`의 processor 목록 기준). 즉 LLM “스트리밍”은 **토큰 스트리밍이 아니라**, `generate_response` 완료 후 **문장 split + 짧은 간격으로 여러 TextFrame** 푸시에 가깝다.

## 2. `response_chunks` 생성 방식

`generate_response.py`의 `_split_into_chunks`는 `(?<=[.?!])\s+` 기준으로 문장 분리. 프롬프트가 “2~3문장”을 권장하므로 **보통 2~3개 청크** → LLM 턴마다 TTS 호출이 **2~3 구간**으로 나뉨.

## 3. LLM 턴 이전 대기 (무음·세그먼트)

- LLM 턴: `process_utterance` 등 **수 초** 동안 파이프라인 앞단이 바쁠 수 있음. 그동안 PCM 큐는 비고(또는 무음 킵얼라이브만).
- 그 후 첫 TTS PCM이 들어오면 `rtp_relay`의 **“큐 공백 후 재개”** 로직으로 `base_time` 등이 새 세그먼트처럼 잡힐 수 있음 → 전환 직후 **스케줄/간격 로그**(`rtp_tts_sender_resumed_after_empty`, `rtp_schedule_soft_resync`)와 청취 품질이 연관될 수 있음.

인사는 통화 초반에 **긴 LLM 대기 없이** TTS가 이어지는 경우가 많다.

## 4. RTP 송신 측 (공통)

- `send_audio_to_caller`는 TTS가 준 **PCM 청크 크기 그대로** 큐에 넣고, 송신 스레드가 `build_packets`로 20ms 단위로 쪼갬.
- **한 번에 큰 PCM**이 들어오면 내부 for 루프에서 패킷을 연속으로 밀어 넣으며, 스케줄이 밀리면 `rtp_schedule_soft_resync`로 격자를 재앵커함 → **간헐적 “뭉침”** 체감과 맞물릴 수 있음.
- **AEC** 사용 시 큰 `pcm_data`에 대해 락 구간이 길어지면(`tts_sender_aec_lock_hold_ms`) 송신 슬롯이 밀릴 여지가 있음(인사·LLM 공통이나, LLM 쪽이 청크 패턴이 더 거칠면 빈도↑).

## 5. 권장 확인 로그 (재현 시)

- `pcm_chunk_queued` / `rtp_pcm_chunk_to_packets`: LLM 턴에서 **pcm_bytes**가 인사 대비 특히 큰 덩어리로 찍히는지.
- `rtp_interval_violation`, `rtp_schedule_soft_resync`, `rtp_tts_send_window_jitter_spike`: ~3초 전후 시각과 함께.
- `tts_response_audio_chunk`, `tts_first_audio_sent_to_rtp`: 문장 경계와 맞는지.

## 6. 개선 아이디어 (참고만, 미구현)

- LLM도 인사처럼 **단일 TextFrame**으로 보내거나, 문장 사이 **의도적 짧은 무음/간격**을 TTS·RTP 측에서 맞추기.
- 또는 파이프라인에 `StreamingTTSGateway`를 재도입해 **문장 단위 게이트웨이**와의 조합을 재검토(부작용: Phase1 잘림 이슈로 과거에 단일 프레임 예외 처리 있었음).
