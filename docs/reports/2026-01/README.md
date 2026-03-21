# SIP PBX Logs

이 디렉토리에는 SIP PBX 서버의 로그 파일이 저장됩니다.

## 로그 파일 종류

### 1. SIP 트래픽 로그
**파일명**: `sip_traffic_YYYYMMDD.log`
- SIP 메시지 송수신 내역 (날짜별 분리)
- 포함 내용:
  - 📥 수신한 SIP 요청 (REGISTER, INVITE, OPTIONS 등)
  - 📤 전송한 SIP 응답 (200 OK, 180 Ringing 등)
  - 타임스탬프, 송/수신 IP:Port
  - 전체 SIP 메시지 내용

**예시**:
```
======================================================================
📥 SIP RECV [2025-10-28 09:30:45.123] 192.168.1.100:5060
======================================================================
REGISTER sip:127.0.0.1 SIP/2.0
Via: SIP/2.0/UDP 192.168.1.100:5060;branch=z9hG4bK...
From: <sip:user@192.168.1.100>;tag=...
...
======================================================================
```

### 2. 애플리케이션 로그 (LLM / STT / TTS 포함)
**파일명**: `app.log`  
**위치**: `logs/app.log` (프로젝트 루트 기준)

- **파일에 기록되는 조건**: `config/config.yaml`에서 `logging.output: "file"` 일 때만 파일에 기록됩니다. `"stdout"`이면 콘솔만 출력됩니다.
- **⚠️ 서버 시작 시 동작**: `app.log`는 **서버를 시작할 때마다 새로 덮어씁니다**(`w` 모드). 따라서 (1) 서버 기동 직후에는 초기화/시작 로그만 보이고, (2) **AI가 응대한 통화가 한 건이라도 있어야** STT/LLM/TTS 대화 로그가 파일에 쌓입니다. 통화 후 파일 끝부분을 보면 됩니다.
- 포함 내용:
  - 애플리케이션 전반 동작 (JSON 한 줄 단위)
  - **통화 중 LLM 질문/응답**: `event`가 `rag_llm_user_input`, `langgraph_agent_result`, `llm_response_sent`, `⏱️ [TIMING] generate_response` 등
  - **STT 실시간**: `event="rag_llm_user_input"` (사용자 발화 `text`), 후처리 STT는 `stt_post_process_*`, `stt_transcript_saved` 등
  - **TTS 실시간**: `rag_llm_greeting_phase1`, `streaming_tts_gateway_flushed`(Gateway→TTS 전달 완료), `tts_complete_notifier_signalled`(TTS 출력 완료, Phase2 동기화 기준), `llm_response_sent` 등
  - Pipecat(Google STT/TTS) 내부 로그도 동일한 `app.log`에 `[PIPECAT]` 접두어로 기록됨
- **인코딩**: JSON 로그는 `ensure_ascii=False`로 기록되어 한글이 `\uXXXX` 이스케이프 없이 UTF-8로 그대로 출력됨.

**category 필드로 보기** (권장):  
`event` 외에 **`category`** 로 구분해 필터할 수 있습니다.

| 필드 | 내용 |
|------|------|
| **call** | `true` 이면 통화 핵심 로그 (LLM 질의/응답, STT/TTS, RAG 검색, HITL). 이 필드로만 필터하면 대화 흐름만 볼 수 있음. |
| **category** | stt / llm / tts / rag 구분 |
| **stt** | 사용자 발화(STT) — 실시간 STT 입력, 후처리 STT, transcript 저장 |
| **llm** | LLM 질문/응답 — 사용자 입력, Agent 결과, 응답 텍스트, 에러 |
| **tts** | TTS 출력 — 인사말 Phase1/2, 발송 완료 |
| **rag** | RAG/DB — 벡터 검색, ChromaDB 검색/업서트/삭제, 재순위화, DB 로깅 |

**통화 핵심 로그만 보기** (`call: true` 인 로그만):
```powershell
Get-Content logs\app.log | Select-String '"call": true'
```

**기록 여부 빠른 확인** (STT/LLM/TTS가 실제로 쌓였는지):
```powershell
# 대화 관련 이벤트가 있는지 확인 (한 건이라도 나오면 기록된 것)
Get-Content logs\app.log | Select-String "rag_llm_user_input|langgraph_agent_result|llm_response_sent"
```

**TTS 음성 끊김/깨짐 점검**  
AI 응대 시 음성이 살짝 깨질 때는 TTS → PCM 큐 → RTP 송출 구간 로그를 보면 됩니다.  
→ **[TTS_RTP_QUEUE_CHECK.md](TTS_RTP_QUEUE_CHECK.md)** 에서 `rtp_tts_queue_empty_timeout`, `rtp_tts_queue_depleted`, `pipecat_pcm_queue_full_dropping`, `output_audio_frame_skipped` 등 이벤트별 의미와 필터 예시를 참고하세요.

**자주 보이는 경고**:
| event | 원인 | 조치 |
|-------|------|------|
| `org_manager_tenant_config_not_found` | VectorDB에 해당 extension(owner)의 `tenant_config` 문서가 없음. 통화가 API 시드보다 먼저 들어오거나, API 단독 실행으로 시드가 안 돌았을 때 | 서버를 `python -m src.main`으로 기동하면 main에서 시드를 먼저 실행해 두므로 통화 수락 전에 tenant_config가 채워짐. API만 단독 실행 시 로그인/테넌트 사용 전에 시드가 한 번 실행되므로, 첫 통화가 너무 빨리 오면 한 번 나올 수 있음. |

**AI 응대 관련 에러 (event: error)**  
`app.log`에서 `"level": "error"` 또는 `"event": "TTS synthesis error"` / `"STT streaming error"` 가 나오는 경우:

| event | 로그 메시지 요약 | 원인 | 조치 |
|-------|------------------|------|------|
| `TTS synthesis error` | `Requested language code 'ko' doesn't match the voice 'ko-KR-Chirp3-HD-Kore''s language code 'ko-kr'` | TTS 클라이언트에 전달하는 언어 코드가 `ko`인데, 보이스는 `ko-kr`(또는 `ko-KR`)만 허용함 | 설정 또는 TTS 클라이언트 초기화에서 **언어 코드를 `ko-kr` 또는 `ko-KR`로 변경**. (config 예: `streaming_tts.language` / `tts.language` 등) |
| `STT streaming error` | `400 Audio Timeout Error: Long duration elapsed without audio. Audio should be sent close to real time.` | Google STT 스트리밍 API에 오디오가 실시간에 가깝게 전달되지 않음(인사말 TTS 재생 중에는 발화가 없어서 지연이 길어짐) | (1) 인사말 구간처럼 오디오가 없을 때는 스트리밍 세션을 잠시 유지하거나, (2) Google Cloud STT 설정에서 스트리밍 타임아웃/인터리빙 정책 확인, (3) RTP→STT 버퍼가 너무 크지 않은지 확인 |

위 TTS 에러가 나면 **인사말/응답 말소리가 통화에 전혀 안 들리는** 상태가 됩니다. 우선 **TTS 언어 코드를 `ko-kr`로 맞추는 것**을 권장합니다. 상세 조치 절차는 **[docs/guides/TTS_NO_AUDIO_FIX.md](../docs/guides/TTS_NO_AUDIO_FIX.md)**를 참고하세요.

**app.log에서 자주 보이는 error/warning (요약)**  
| level | event | 요약 | 조치 |
|-------|--------|------|------|
| error | `pipecat_import_error` | `VoiceAIPipelineBuilder` 임포트 실패 | Pipecat 미사용 시 무시 가능(legacy 파이프라인 사용). 사용 시 `pip install pipecat-ai[google,silero]` |
| warning | `call_manager_inject_failed` | `src.api.routers.calls`에 `set_call_manager` 없음 | 대시보드 활성 통화 목록이 API만 사용. 연동하려면 calls 라우터에 `set_call_manager` 추가 |
| warning | `hitl_timeout_register_failed` | `HITLService`에 `register_on_hitl_timeout` 없음 | HITL 타임아웃 콜백 미등록. 서비스 코드에 해당 메서드 추가 시 해결 |
| warning | `jwt_invalid` / `ws_connection_rejected_jwt_error` | WebSocket 인증 시 JWT 형식 아님(tok_* 등) | 백엔드 WS(8001)에서 tok_* 토큰 허용하도록 수정 시 대시보드 "연결됨"·실시간 STT 표시 가능 |

**검색 예시** (PowerShell):
```powershell
# 1. LLM 질문·응답만
Get-Content logs\app.log | Select-String '"category": "llm"'

# 2. STT만 (사용자 발화)
Get-Content logs\app.log | Select-String '"category": "stt"'

# 3. TTS만 (AI 발화)
Get-Content logs\app.log | Select-String '"category": "tts"'

# 4. RAG/DB 조작만
Get-Content logs\app.log | Select-String '"category": "rag"'
```

### 지연 분석 (RTP→STT→TTS→RTP)

사용자 발화부터 AI 응답이 전화기로 나갈 때까지 구간별 시점을 보려면 `progress="timing"` 이벤트와 `ts_iso`를 사용합니다.

| event | 의미 |
|-------|------|
| `timing_caller_rtp_first_to_pipeline` | Caller RTP 첫 패킷이 파이프라인에 투입된 시점 (RTP→STT 구간 시작) |
| `timing_stt_final_to_rag` | STT 최종 결과가 RAG에 도달한 시점 (LLM 호출 직전) |
| `tts_first_audio_received` | TTS 엔진이 첫 오디오를 반환한 시점 |
| `tts_first_audio_sent_to_rtp` | 첫 오디오가 RTP 발송 큐에 넣어진 시점 |
| `timing_first_tts_rtp_sent_to_caller` | Caller에게 첫 TTS RTP 패킷이 실제 전송된 시점 (TTS→RTP 구간) |

**특정 통화의 지연 구간만 보기** (PowerShell, `call_id` 치환):
```powershell
Get-Content logs\app.log | Select-String "timing_caller_rtp_first|timing_stt_final_to_rag|tts_first_audio|timing_first_tts_rtp_sent"
```
각 로그의 `ts_iso` 차이로 (1) RTP→STT, (2) STT→LLM→TTS, (3) TTS→RTP 전송 지연을 계산할 수 있습니다.

## 로그 관리

### 자동 정리
- SIP 트래픽 로그는 날짜별로 자동 분리됩니다
- 오래된 로그는 수동으로 삭제하거나 로그 로테이션 설정 필요

### 로그 확인 방법

**실시간 모니터링**:
```bash
# Windows
Get-Content logs\sip_traffic_20251028.log -Wait -Tail 50

# Linux/Mac
tail -f logs/sip_traffic_20251028.log
```

**특정 메서드 검색**:
```bash
# REGISTER 메시지만 보기
Get-Content logs\sip_traffic_20251028.log | Select-String "REGISTER"

# 특정 IP에서 온 메시지
Get-Content logs\sip_traffic_20251028.log | Select-String "192.168.1.100"
```

## 주의사항

⚠️ 로그 파일은 `.gitignore`에 포함되어 있어 Git에 커밋되지 않습니다.

⚠️ SIP 트래픽 로그에는 민감한 정보(전화번호, 인증 정보 등)가 포함될 수 있으니 공유 시 주의하세요.

⚠️ 트래픽이 많을 경우 로그 파일이 빠르게 증가할 수 있습니다. 디스크 공간을 주기적으로 확인하세요.

