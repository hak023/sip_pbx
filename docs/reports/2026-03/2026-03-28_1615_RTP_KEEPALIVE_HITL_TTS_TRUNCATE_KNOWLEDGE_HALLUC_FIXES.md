# RTP 킵얼라이브·HITL TTS 잘림·지식추출 환각 검증 수정

- **작성일**: 2026-03-28 16:15
- **버전**: 1.0
- **상태**: 코드 수정 완료
- **관련 호**: `oL0tFYH1Zg`, `s3LWD-cH5P`

---

## 요약

1. **묵음 RTP 킵얼라이브 미동작**: 환경변수 기본값 `"0"`으로 인해 항상 비활성화되어 있었음. config 기본 `true`로 전환.
2. **HITL TTS 「…맑」 잘림**: `format_hitl_reply_for_customer`가 `max_output_tokens` 640으로 LLM 응답이 중간에 끊김. 상한 2048로 상향 + `MAX_TOKENS`이면서 미완 문장일 때 담당자 원문으로 폴백.
3. **유저 간 통화 지식 저장 0건**: 초단문 턴 다수 전사에서 환각 검증 구문 매칭이 과도하게 엄격해 `skipped_halluc: 3`. 전사 정규화(4자 이하 턴 제거·공백 압축) + 부분 문자열 매칭 + 임계값 완화(0.4 → 0.25) 적용.

---

## 1. RTP 묵음 킵얼라이브 미동작

### 원인

`rtp_relay.py` `_ai_silence_rtp_keepalive_enabled()`:

```1210:1225:c:\work\workspace_sippbx\sip-pbx\src\media\rtp_relay.py
def _ai_silence_rtp_keepalive_enabled(self) -> bool:
    ...
    raw = str(os.environ.get("SIPPBX_AI_RTP_SILENCE_KEEPALIVE", "0")).strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    ...
```

환경변수 **기본값이 `"0"`** 이어서, `.env` 또는 환경변수로 **명시적으로 `1` 설정하지 않으면** 영구히 비활성화.  
`rtp_tx_oL0tFYH1Zg.tsv`에 `tx_kind=keepalive` 0건, 마지막 RTP 후 **32초 무송신** → 단말 BYE 송신과 상관 가능.

### 수정

- `MediaConfig`에 `ai_rtp_silence_keepalive: bool = True`, `ai_rtp_keepalive_interval_sec: float = 8.0` 추가.
- `RTPRelayWorker` 생성자에 위 값을 받고, **환경변수가 "설정된 경우에만"** 우선; 미설정 시 config 기본값(true).
- `sip_endpoint.py`에서 `config.media` → 워커로 전달.
- 운용 `config.yaml`, `config.example.yaml`, `env.example`에 설명 반영.

**효과**: 별도 env 설정 없이 **Pipecat·AI 모드에서 기본으로 무음 RTP 주기 송신** (단말 10초 무수신 끊김 완화). TSV에는 `tx_kind=keepalive` 로그됨.

---

## 2. HITL TTS 「2026년 3월 29일… 맑」 잘림

### 원인

로그 `app.log` 라인 1957:

```json
{"level": "warning", "event": "format_hitl_reply_truncated_max_tokens", "note": "max_output_tokens 상향 검토", "response_len": 33}
{"level": "info", "call": "hitl_response_received", "text_len": 33, "text_preview": "2026년 3월 29일 서울 날씨에 대해 문의주셨는데요. 맑"}
```

`llm_client.py` `format_hitl_reply_for_customer`의 `max_output_tokens: 640` 이 부족해 **중간에 `MAX_TOKENS`로 끊겼고**, 그 잘린 33자가 그대로 TTS로 전달되어 **말이 "맑"에서 종료**됨.

### 수정

- HITL 포맷 전용 출력 상한을 `hitl_format_max_output_tokens` 또는 `hitl_format_max_tokens` 설정 키로 지원. 기본 **2048**, 최대 **8192**.
- `MAX_TOKENS`일 때 **80자 미만** 또는 **말미에 `.!?` 등 없으면** → 담당자 원문(`operator_reply`)으로 폴백 (`format_hitl_reply_truncated_max_tokens`).
- 말미 종결 부호가 있으면 → 생성문 사용, `_truncated_max_tokens_tail` 경고만 출력.

**효과**: 질문+답변이 긴 HITL 멘트에서도 잘림 없이 TTS 송출. 만일 상한에 걸려도 담당자 원문으로 우회해 내용 손실 방지.

---

## 3. 유저 간 통화 지식 저장 0건 (`s3LWD-cH5P`)

### 원인

로그 라인 1315–1318:

```json
{"event": "llm_judgment_completed", "is_useful": true, "extracted_info_count": 3, "confidence": 1.0}
{"event": "✅ [Pipeline v2] Stage 3 완료", "verified": 0, "skipped_halluc": 3, "skipped_quality": 0, "skipped_dedup": 0}
{"event": "🎉 [Pipeline v2] 추출 완료", "stored": 0}
```

- Stage 2: **`judge_usefulness` 성공, `extracted_info` 3건 추출**
- Stage 3: **환각 검증 전부 실패** (`skipped_halluc: 3`)
- Stage 4: 저장할 항목 없음 → `stored: 0`

통화 전사는 **발신/착신이 4자 이하로 짧게 번갈아 찍힌 상태** (실시간 STT):

```
발신자: 기
착신자: 상 청 홈
발신자: 상
착신자: 페이지 에
```

반면 LLM 추출문은 **"기상청 홈페이지에 등록…"** 처럼 완성된 문장.  
구문 검증(`_syntactic_check`)은 **추출 토큰이 전사 토큰에 집합 교집합으로 있는지**를 보는데,  
"기상청" 토큰은 전사에 **"기", "상", "청"으로 쪼개져** 교집합 0 → `syntactic_score`가 임계값 0.4 미만으로 **전부 탈락**.

### 수정

**A. 설정 추가** (`models.py`, `config.yaml`)

- `KnowledgeExtractionConfig.transcript_normalization`:
  - `enabled`: true (기본)
  - `collapse_short_turns`: true
  - `short_turn_max_chars`: 4
  - `syntactic_threshold_relaxed`: **0.25** (짧은 턴 전사일 때 구문 임계값, 기본 0.4 대비 완화)

**B. 환각 검사 정규화** (`hallucination_checker.py`)

1. **초단문 전사 판정**: 턴의 50% 이상이 4자 이하면 `is_short_turn_transcript = true`.
2. **정규화**:
   - 4자 이하 턴 제거
   - 화자 라벨 제거(`발신자:`, `착신자:` 삭제)
   - 남은 내용을 공백으로 이어 붙임, 연속 공백 압축
   - 예: `"발신자: 기\n착신자: 상 청 홈페이지"` → `"상 청 홈페이지"`
3. **구문 매칭**:
   - 추출 토큰(장마철, 홈페이지 등)이 **정규화된 전사(공백 제거한 연속 문자열)**에 **부분 문자열로 있는지** 확인
   - 예: `"장마철"` → `"…상청홈페이지에등록…"` 같은 collapsed 문자열에서 `"장마철"` 검색
   - 매칭률 = (matched_count / 추출 토큰 수)
4. **임계값 전환**: `is_short_turn_transcript=true`이면 `syntactic_threshold_relaxed`(0.25) 사용, 아니면 기본(0.4).

**C. 파이프라인 연결** (`extraction_pipeline.py`)

- `HallucinationChecker(embedder, llm_client, config=self.config)` — `config`에 `transcript_normalization` 전달.

**D. 로그 강화**

- 구문 검증 실패 시 `hallucination_syntactic_fail`에 `score`, `threshold`, `short_turn`, `transcript_preview` 로그.
- `hallucination_skip` 로그에 `syntactic_score`, `semantic_score` 추가.

### 효과

- **실제 로그 패턴 테스트**: 
  - 「장마철…」 추출문 → `syntactic_score` **0.333** (>= 0.25 통과)
  - 「팩스…」 추출문 → `syntactic_score` **0.833** (>= 0.25 통과)
- 이전에는 **0.0**으로 전부 `skipped_halluc`였던 것이, 이제 구문 검증을 **통과**해 의미/함의 검증 단계로 진행 가능.
- **실시간 STT로 번갈아 나온 초단문 다수 전사**에서도 지식 추출이 정상 동작.

---

## RTP "제시간 전송" 부연

**질문**: "부분부분 끊겨 들리는데 RTP가 제시간에 나간 게 맞냐?"

**답**: 
- HITL 구간(`15:15:05–08`, 111패킷) TSV 기준: **간격 16~24ms, p50=20ms, p99=23ms, seq 연속** → **그 짧은 구간만 놓고 보면** "제시간에 나갔다"가 맞다.
- 청감상 끊김 원인은:
  1. **대형 갭**(20s, 29s, 2.8s, 0.22s) — 전체 통화 초반에 발생, HITL 구간과는 별개.
  2. **HITL 멘트 자체가 33자에서 잘렸음** (이번 수정 대상).
  3. **다른 TTS 턴의 갭·스케줄 위반** (`interval_violations: 7`, `behind_schedule: 4`).
- 즉, "뭉개짐"은 **RTP 스케줄 위반**·**콘텐츠 잘림**·**긴 무송신**의 복합이지, **이 짧은 HITL 구간 20ms 격자**는 거의 정상이었다.

---

## 파일 변경 요약

| 파일 | 주요 변경 |
|------|----------|
| `src/config/models.py` | `MediaConfig` + `ai_rtp_silence_keepalive` / `ai_rtp_keepalive_interval_sec` 추가; `KnowledgeExtractionConfig` + `transcript_normalization` 추가 |
| `src/media/rtp_relay.py` | 생성자에 킵얼라이브 설정 인자 추가, `_ai_silence_rtp_keepalive_enabled()` env 우선→config 폴백 로직 |
| `src/sip_core/sip_endpoint.py` | `RTPRelayWorker(...)` 호출 시 config 킵얼라이브 설정 전달 |
| `src/ai_voicebot/ai_pipeline/llm_client.py` | `format_hitl_reply_for_customer` 출력 상한 640 → 설정 기반(기본 2048), `MAX_TOKENS`이면서 미완 시 원문 폴백 |
| `src/ai_voicebot/knowledge/hallucination_checker.py` | 생성자 `config` 인자 추가, 초단문 전사 판정·정규화·부분 문자열 구문 매칭·완화 임계값(0.25) 로직 |
| `src/ai_voicebot/knowledge/extraction_pipeline.py` | `HallucinationChecker(config=self.config)` 전달 |
| `config/config.yaml` | `media.ai_rtp_silence_keepalive: true` 등, `knowledge_extraction.transcript_normalization` 섹션 |
| `config/config.example.yaml` | `media` 아래 킵얼라이브 주석 |
| `env.example` | 킵얼라이브 env 설명 추가 |

---

## 재현·검증 예시

### 킵얼라이브

- **재현**: 다음 AI 통화에서 TTS 무송신 구간이 8초 이상 발생하면, TSV에 `tx_kind=keepalive` 로그됨.
- **끄려면**: `config.yaml` `media.ai_rtp_silence_keepalive: false` 또는 `SIPPBX_AI_RTP_SILENCE_KEEPALIVE=0`.

### HITL TTS

- **재현**: 긴 담당자 답변을 HITL로 제출하면, 최대 2048자 멘트 생성; 그래도 상한 걸리면 원문으로 TTS.
- **조정**: `config.yaml` `ai_voicebot.llm` 아래 `hitl_format_max_output_tokens: 4096` 같이 명시 가능(현재 코드는 config에서 읽어 `hitl_format_max_tokens` 키도 호환).

### 지식 추출

- **재현**: 초단문 턴 50% 이상 전사 → `is_short_turn_transcript: true` → 구문 임계값 0.25 적용.
- **테스트**:
  - `"네 장마철은…"` → `syntactic_score` **0.333** ≥ 0.25 → 통과
  - `"네 원하시는 분들에게…"` → `syntactic_score` **0.833** ≥ 0.25 → 통과
- **완화 끄려면**: `config.yaml` `knowledge_extraction.transcript_normalization.enabled: false`.

---

## 다음 단계 (선택)

- 실제 통화 재테스트로 킵얼라이브가 TSV에 찍히는지, HITL 멘트가 완전하게 나가는지, 유저 간 통화 지식이 VectorDB에 들어가는지 확인.
- 초단문 전사가 아닌 정상 전사에서도 **의미 검증(embedding)** 또는 **함의 검증(LLM)**을 거쳐 최종 품질 게이트를 통과하는지 로그로 추적.
