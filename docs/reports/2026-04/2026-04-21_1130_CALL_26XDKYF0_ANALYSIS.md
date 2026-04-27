## 메타

- **작성일(로컬)**: 2026-04-21 11:30 (본문 보강: 2026-04-21 13:49)
- **상태**: 분석(로그 기반) + 후속 코드 대응 반영
- **call_id**: `26XdkYF0~t`
- **근거 로그**: `sip-pbx/logs/app.log`, `sip-pbx/logs/call_data_record_20260421.log` (발신 1004 → 착신/테넌트 1003, 비스트로 벨라)

## 개요

무응답 10초 후 AI 인수(no_answer_ai), Pipecat·예약(booking) 대화 중 **RTP 경로로 동일 안내 음성이 반복 체감**된 점, **1차 예약 생성 성공 후 동일 긍정 발화 1건에 대해 `booking_tool_start`가 여러 번** 찍힌 점, GCal 토큰 만료·Gemini FC 오류가 겹친 통화로 해석된다. **메인 이슈**는 예약 도구의 **중복 호출 + 도구 레이어 로깅 버그**로 정리한다.

## 타임라인 요약

| 시각(로컬) | 내용 |
|------------|------|
| 11:23:18 | INVITE, ringback, early STT |
| 11:23:28 | 무응답 AI 인수, Pipecat 시작 |
| 11:23:38 | `bypass_stt_stream_ended` — Google STT 400 Audio Timeout |
| 11:24:29 | STT seq=2 「예약… 오늘 7시」→ booking_agent, 슬롯 확인 후 TTS 안내 |
| 11:24:28 | `stt_transcript_watchdog_alert` — 약 32초간 TranscriptionFrame 없음(transcription_count=1) |
| 11:24:57~ | 「네 명이…」STT 오인식 → booking은 4명·성함 질문 등 진행 |
| 11:25:54 | `_create_booking` **성공** `bk_25f9dc81956f`, SIP MESSAGE 완료 안내 발송 |
| 11:25:54~ | `gcal_token_refresh_failed`, `booking_agent_llm_invoke_error`, 동일 사용자 텍스트「예 해주세요.」에 대해 **의도 분류·booking_agent 재진입** |
| 11:25:59~ | `_create_booking` **재시도** — 도구 결과에 `Logger._log() got an unexpected keyword argument 'error'` (**booking_tools가 표준 logging에 `error=` 키워드 사용**) |
| 11:26:08 | 고객 TTS: 「예약 생성 중 오류가 발생했습니다…」 |

## 사용자 질문별 정리

### 1. TTS / RTP — 동일 멘트(비스트로 벨라 등) 반복

- **핵심**: LangGraph·`llm_exchange`에 기록된 **AI 본문 응답은 정상**인데, **실제로 RTP로 나간 음성**에서 「비스트로 벨라…」「네, 고객님」「잘 들립니다」류가 **의도치 않게 반복**된 것이 문제로 정리한다.
- 로그상 `rag_streaming_tts_chunks` 직후 `korean_numbers_textframe_input`에 동일한 **짧은 안내 접두**가 **청크마다** 붙어 TTS로 들어간 상관관계가 있었다.
- **원인 가설(제품)**: 스트리밍 LLM이 **문장(청크)마다 동일 리스너/브랜드 안내 접두**를 생성하고, 파이프라인이 청크 단위로 `TextFrame`을 쪼개 전달하면서 **청크당 한 번씩** TTS·RTP로 재생된 것으로 본다. (순수 RTP 패킷 중복보다 **상위 텍스트 스트리밍 분할** 쪽이 주원인에 가깝다.)
- **코드 대응(2026-04-21)**: `rag_processor`에서 `response_chunks`가 2개 이상일 때 `dedupe_streaming_tts_chunks`로 **턴당 1회**에 가깝게 선행구를 제거한다. (`sip-pbx/src/common/tts_streaming_chunk_dedupe.py`)

### 2. 예약 — 긍정 발화 1번 vs `booking_tool_start` 다회 (메인 이슈)

- `call_data_record_20260421.log`: 동일 `user_text`「예 해주세요.」에 대해 **11:25:53**, **11:25:59**, **11:26:06** 부근 **`booking_tool_start` / `_create_booking` 반복**.
- **1차** `booking_committed` 성공(`bk_25f9dc81956f`) 후에도 **그래프가 완전히 종료되기 전** 동일 쿼리로 **의도 재분류·booking_agent 재진입**이 발생한 흔적(`intent_classify` 다회, `agent_graph_total` 지연).
- **2·3차 실패의 직접 원인**: 중복 예약 분기에서 `booking_tools`의 `logger.warning(..., error=str(e))`가 **표준 `logging`**에 전달되며 **`Logger._log() got an unexpected keyword argument 'error'`** 예외가 발생 → `booking_agent._execute_tool`이 이를 잡아 **`{"error": "..."}`** JSON으로 반환.
- **코드 대응(2026-04-21)**: `booking_tools`를 **structlog**로 통일; `create_booking`은 **dup을 슬롯 UPDATE 전에 검사**하고 동일 confirmed 예약이 있으면 **멱등 성공 반환**(INSERT·SMS·슬롯 증가 없음).

### 3. `gcal_token_refresh_failed` / Calendar refresh token

- **`gcal_token_refresh_failed`**: `invalid_grant: Token has been expired or revoked.` — 테넌트 **1003** Google Calendar OAuth **refresh token 만료·폐기**. 로컬 예약과 GCal은 경로가 분리되어 **1차 DB 예약은 성공**할 수 있음.
- **refresh token 발급·갱신 절차(공식)**  
  - [OAuth 2.0 개요](https://developers.google.com/identity/protocols/oauth2)  
  - [웹 서버 앱](https://developers.google.com/identity/protocols/oauth2/web-server) (`access_type=offline` 등으로 refresh 토큰 수령)  
  - [액세스 토큰 갱신](https://developers.google.com/identity/protocols/oauth2#5.-refresh-the-access-token-if-needed)

### 4. RTP 로그

- `rtp_health_snapshot`은 운영 **info**에서 **debug**로 낮춤 (`rtp_relay.py`). 병목 분석 시 로그 레벨을 올려 확인한다.

### 5. `booking_agent_llm_invoke_error`와 TCP

- 로그 메시지: `MapComposite … unexpected type … at Struct.extra_data` 형태 → **Gemini 네이티브 FC / protobuf Struct 직렬화**(도구 인자·`extra_data` 등) 이슈로 해석하는 것이 타당하다.
- **동일 시각대 `socket_receive_error`(10054)** 는 **원격이 HTTP/gRPC 등 제어 평면 TCP를 끊은 것**과 부합할 수 있으나, **SIP RTP UDP 세션**과 **1:1 동일 연결**이라고 단정하지는 않는다.

### 6. `stt_transcript_watchdog_alert`

- 구현상 워치독은 **StartFrame 이후 이 파이프라인에서 `TranscriptionFrame`이 `_STT_TRANSCRIPT_WATCHDOG_SEC` 동안 없을 때** 발동한다 (`rag_processor._stt_transcript_watchdog`).
- **의심(점검 필요)**: 발신↔서버 AI 구간에서는 STT가 살아 있는데, **착신↔PBX/미디어** 쪽이 별도로 남아 오디오·전사 경로가 어긋나면 **사용자 체감과 로그만 불일치**할 수 있다. 현재 코드만으로는 **착신 RTP 잔존 여부를 자동 판별하지 않으므로**, 해당 통화의 **transport/bypass 모드·STT 입력 소스**를 추가로 대조하는 것이 좋다.

### 7. 스트리밍 TTS 프리픽스

- **구현**: `dedupe_streaming_tts_chunks`로 청크 간 **최장 공통 접두** 및 **알려진 짧은 안내구**를 2번째 청크부터 제거한다.

## 변경 이력 (파일별) — 분석 문서 자체

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|------------|------|------|
| `sip-pbx/docs/reports/2026-04/2026-04-21_1130_CALL_26XDKYF0_ANALYSIS.md` | 수정 | TTS/RTP·예약 메인 이슈·워치독·토큰 링크 정리 | 로그 근거 유지 |

## 잔여 과제(권장)

1. `booking_agent` Gemini **라운드2 tool 결과 → Struct** 직렬화 경로/SDK 호환 점검.
2. 테넌트 1003 **Google Calendar OAuth 재연동**.
3. `stt_transcript_watchdog_alert`와 **미디어/착신 경로** 상관 — 재현 시 **STT 입력이 어떤 RTP 레그에서 오는지** 로그 보강.
