# RTP·TTS 오디오 품질 점검 리포트 (call_id: SESsPF16cQ)

| 항목 | 내용 |
|------|------|
| **작성일** | 2026-03-26 (분석 시점) |
| **상태** | `app.log` 기반 단일 통화 분석 |
| **로그 소스** | `sip-pbx/logs/app.log` |
| **call_id** | `SESsPF16cQ` |
| **통화 로그 상 시각(예)** | 2026-03-27 16:38:52 ~ 16:44:02 (로그 타임스탬프 기준) |
| **송신 구조 점검(후속)** | [RTP_SENDER_PATH_STRUCTURE_REVIEW.md](RTP_SENDER_PATH_STRUCTURE_REVIEW.md) — 망 유실 가정 제외, PBX 송신 경로·로그 해석 |

---

## 1. 사용자 증상과 코드상 문구

- 체감: 지연 구간에서 **「정보를 찾고 있습니다」** 유형 안내 시 말소리가 깨짐.
- 코드(`rag_processor.py`): LLM이 **12초** 이상 걸릴 때 1회만 재생하는 대기 안내 문구는  
  **`정보를 확인 중입니다.`** + **`잠시만 기다려 주세요.`** (문장별 `LLMFullResponseStartFrame` / `TextFrame` / `LLMFullResponseEndFrame`).

본 통화에서 해당 TTS는 로그에 다음과 같이 찍힘.

- `llm_processing_notification` — `2026-03-27T16:39:39.134`, `wait_sec`: 12.0  
- `tts_text_input` — `16:39:39.134` / `16:39:39.608` — `정보를 확인 중입니다.`  
- `tts_text_input` — `16:39:39.608` / `16:39:40.023` — `잠시만 기다려 주세요.`  
- 직후 본답변 TTS — `16:39:40.087` 부터 긴 응답 텍스트

즉, **지연 안내 구간 = LLM 장시간 처리와 겹치는 짧은 TTS 두 덩어리 + 곧바로 이어지는 본문 TTS** 로 구성됨.

---

## 2. 로그가 말하는 것: 송신 측 타이밍·파이프라인 (망 구간 제외)

### 2.1 `app.log` RTP 이벤트의 관측 범위

`app.log`의 RTP 관련 이벤트는 **PBX가 RTP를보낼 때의 스케줄·패킷 간격·PCM 송신 큐**를 기록한다. 이후 망·단말은 본 리포트에서 다루지 않는다.

### 2.2 **송신 타이밍 불균일**과 **TTS 프레임 계수 불일치**가 뚜렷함

다음 이벤트는 **20 ms 프레임 간격 이탈**, **스케줄 대비 늦은 전송**, **PCM 송신 큐 적체**를 가리킨다. 이는 단말 측 지터 버퍼에서 **끊김·왜곡·기계음**으로 체감될 수 있다.

| 시각(대략) | 이벤트 | 요약 |
|------------|--------|------|
| 전 구간 | `rtp_interval_violation` | 기대 20 ms 대비 실제 간격이 **9~33 ms** 등으로 반복 이탈 (`violation_count` 통화 중 **900대**까지 누적) |
| 전 구간 | `rtp_send_behind_schedule` | **스케줄보다 늦게** 전송 시도 (메모: 이벤트 루프 지연·PCM 버스트·CPU 경합) |
| 전 구간 | `rtp_tts_send_window_stats` | 윈도당 `interval_max_ms` **~30–44 ms**, `interval_min_ms` **~0.2–7 ms** 등 **과대/과소 간격 혼재**, `pcm_queue_size` **최대 20대**까지 관측 |
| 16:39:04.898 등 | `tts_rtp_duration_mismatch` | Notifier vs Output **오디오 프레임 수 큰 차이** (예: notifier 92 vs output 13, `diff_ratio_pct` ~20.7%) — 로그 설명: EndFrame 순서·바지인 등과 연관 가능 |

**대기 안내 직후 구간(사용자가 깨짐을 느끼기 쉬운 구간) 예시:**

- `16:39:39.134` — `llm_processing_notification`
- `16:39:39.452` — `rtp_send_behind_schedule` (9회째, `chunk_inner_idx` 0, 새 TTS 구간 시작 직후)
- `16:39:39.608` — `tts_rtp_duration_mismatch` (notifier 27 vs output 4, `diff_ratio_pct` 21.9%)
- `16:39:40.023` — 동일 유형 `tts_rtp_duration_mismatch` (두 번째 짧은 문장)
- `16:39:39.719` — `rtp_tts_send_window_stats`: `interval_max_ms` 41.77, `interval_min_ms` 0.48, `pcm_queue_size` 3, `interval_violations_cumulative` 40

정리하면, 동일 시각대 로그는 **송신 측(호스트) 지터·PCM 큐 적체·TTS/RTP 파이프라인 프레임 불일치**를 강하게 시사한다(망 구간은 본 분석 범위에서 제외).

---

## 3. 왜 대기 안내 구간이 특히 거슬릴 수 있는가

1. **LLM 장시간 처리**와 **짧은 filler TTS**가 동시에 걸리는 구간에서 CPU·async 이벤트 루프 경합이 커질 수 있음 (`rtp_send_behind_schedule` 메모와 부합).
2. Filler는 **문장을 둘로 쪼개** 파이프라인에 넣으며, 직후 **긴 본답변** TTS가 이어져 **PCM 큐에 청크가 연속 유입** → `pcm_queue_size`·간격 위반 통계가 함께 나타남.
3. `tts_rtp_duration_mismatch`는 **재생 길이/프레임 계산과 실제 RTP 전송량**의 괴리를 보여 주며, 짧은 문장·빠른 전환에서 체감 품질 저하와 상관 가능.

---

## 4. 권장 후속 조치 (우선순위)

1. **송신 측** 우선: `pipecat_pcm_queue_full_dropping`·`rtp_sendto_failed`·`rtp_tts_packets_dropped` 유무, PCM 큐 적체와 `behind_schedule` 상관 (상세: [RTP_SENDER_PATH_STRUCTURE_REVIEW.md](RTP_SENDER_PATH_STRUCTURE_REVIEW.md)).
2. **대기 안내 TTS 구간**에 한해 프로파일링: LLM 태스크와 RTP 송신 태스크의 **동시성**(동일 asyncio 루프 경합).
3. `tts_rtp_duration_mismatch` 발생 시점과 **Output 쪽 드롭/조기 종료** 여부를 코드 경로에서 추가 추적 (이미 로그에 가설이 적혀 있음).
4. Filler와 본답변 사이 **버퍼링/짧은 무음 삽입** 등으로 **RTP 송신 루프가 연속 버스트**에 덜 흔들리게 할지 검토.
5. (망 구간 검증이 필요해질 때만) PCAP 등으로 단말·게이트웨이 구간 병행.

---

## 5. 참고 코드

- 대기 안내 TTS: `sip-pbx/src/ai_voicebot/pipecat/processors/rag_processor.py` — `wait_and_notify`, `_wait_parts`, `_LLM_WAIT_NOTIFY_SEC = 12.0`

---

## 6. 한 줄 결론

**call `SESsPF16cQ`의 `app.log`에서 대기 안내(「정보를 확인 중입니다」) 시각 전후로 송신 RTP 간격 위반·스케줄 지연·PCM 큐 적체·TTS 프레임 불일치가 집중되어 있다. 망 유실을 가정하지 않을 때는 PBX 송신 경로(단일 20 ms 송신 루프·PCM 큐·이벤트 루프 경합)를 우선 의심하는 것이 타당하며, 구조·로그 해석은 [RTP_SENDER_PATH_STRUCTURE_REVIEW.md](RTP_SENDER_PATH_STRUCTURE_REVIEW.md)를 본다.**
