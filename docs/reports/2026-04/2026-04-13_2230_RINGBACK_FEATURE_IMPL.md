## 개요

SIP PBX B2BUA에서 INVITE 수신부터 200 OK 전까지의 18x early media 구간에  
발신자에게 **인사말(Google TTS)** + **통화 연결음(Suno AI 음원)**을 RTP로 스트리밍하는  
"통화 연결음" 기능을 설계·구현했다.  
프론트엔드 설정 메뉴(`/settings/ringback`)에서 음원을 생성·관리하고,  
200 OK 또는 AI takeover 시점에 자동으로 재생을 중단한다.

---

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|---|---|---|---|
| `src/booking/database.py` | 수정 | `ringback_settings` 테이블 DDL 추가 | owner별 설정 1건 |
| `src/services/ringback_service.py` | 신규 | Suno API 연동, LLM 가사/스타일 생성, 설정 CRUD | sunoapi.org v1 |
| `src/sip_core/ringback_player.py` | 신규 | Early media RTP 플레이어 (인사말 TTS + 연결음 루프) | ffmpeg/pydub MP3→PCM |
| `src/sip_core/sip_endpoint.py` | 수정 | Early Bind 후 RingbackPlayer 시작, 200 OK/AI takeover 시 stop() | `_ringback_players` dict 추가 |
| `src/api/routers/ringback.py` | 신규 | 설정 CRUD, 가사·스타일·음원 생성, 상태 폴링, 음원 적용 API | `/api/ringback/*` |
| `src/api/main.py` | 수정 | ringback 라우터 등록 | |
| `config/config.yaml` | 수정 | `ringback` 블록 추가 (suno_api_key, model, cache_dir 등) | |
| `config/config.example.yaml` | 수정 | 동일 ringback 블록 추가 | |
| `.env` | 수정 | `SUNO_API_KEY` 추가 | 실제 키는 별도 설정 |
| `env.example` | 수정 | `SUNO_API_KEY` 예시 추가 | |
| `requirements.txt` | 수정 | `pydub>=0.25.1` 추가 | ffmpeg 백엔드 필요 |
| `frontend/app/settings/ringback/page.tsx` | 신규 | 인사말+연결음 설정 UI | Suno 음원 생성/폴링/미리듣기 |
| `frontend/app/settings/integrations/page.tsx` | 수정 | 통화 연결음 링크 카드 추가 | `/settings/ringback` 연결 |

---

## 주요 결정 사항

### 1. Early Media 전송 방식
- 별도 RTP 포트를 추가하지 않고 `_start_rtp_relay`에서 이미 할당된 포트를 재사용.
- `rtp_worker.send_ai_audio(pcm_bytes)` 를 통해 기존 TTS 전송 경로와 동일하게 처리.
- Away 모드(AI 직접 응대)에서는 RingbackPlayer를 시작하지 않는다 (즉시 200 OK 처리).

### 2. 오디오 포맷
- `send_ai_audio`는 16kHz, mono, 16-bit PCM(LINEAR16)을 입력받아 G.711 μ-law로 변환.
- Google TTS(`TTSClient.synthesize_stream`)는 이미 16kHz PCM 스트림을 출력 → 직접 연결.
- MP3(Suno 음원) → PCM 변환: ffmpeg subprocess 우선, 실패 시 pydub 폴백.

### 3. RingbackPlayer 생명주기
- `_handle_invite_b2bua`: Early Bind 성공 후 `_start_ringback_player()` 호출 (asyncio.create_task).
- `_handle_sip_response` (200 OK for INVITE): `asyncio.create_task(_stop_ringback_player())`.
- `_handle_no_answer_timeout` (AI takeover 직전): 동일하게 stop.
- `_ringback_players: Dict[str, RingbackPlayer]` 로 call_id별 인스턴스 관리.

### 4. Suno API
- sunoapi.org (3rd party wrapper) 사용: `POST /api/v1/generate`, `GET /api/v1/feed/{task_id}`.
- `customMode=True`, `instrumental=False`, 모델 `V4_5`.
- 음원 생성 완료 후 `download_and_cache_audio`로 로컬 `data/ringback/` 에 MP3 캐시.

### 5. 프론트엔드 미리 듣기
- Suno API는 생성된 MP3 URL을 반환하므로 `<audio controls src={audio_url}>` 로 직접 재생.
- 최대 2곡이 생성되므로 radio button으로 선택 후 "이 음원 사용" 적용.

### 6. 스타일 자동 생성
- 백엔드에서 `random.choice`로 장르/분위기/BPM/CM송 태그를 조합.
- 성별(`m`/`f`)과 목표 시간(30/60/90초)은 프론트엔드 라디오/셀렉트에서 선택 후 전달.

---

## 잔여 과제

- Suno API 음원 생성 완료 폴링 시간(2~3분)이 길어 WebSocket push로 알림하는 방식 검토.
- 음원 캐시 파일이 쌓이는 경우 정리 정책(TTL 또는 수동 삭제) 필요.
- B2BUA가 183 Session Progress + SDP를 보낼 때 early media SDP 협상이 올바르게 동작하는지 실제 Linphone 환경에서 테스트 필요.
- SUNO_API_KEY 실제 발급 후 `.env`에 반영 필요.
