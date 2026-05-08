# CDR(통화 상세 기록) 개선 설계
> **클러스터 안내**: 세부·히스토리 설계 문서입니다. 통합 관점·경계는 아래 대표 문서를 우선 참고하세요.
> 
> **대표 문서**: [`CALL_HISTORY_AND_CONTENT_DESIGN.md`](CALL_HISTORY_AND_CONTENT_DESIGN.md)
>
---


## 1. 목적

- **CDR만 확인하면 전화가 어떻게 처리되었는지 모두 알 수 있도록** 상세 기록을 남긴다.
- 용도: **가시적 디버깅**, 사후 분석, 품질 검증. 1통화당 1레코드이며, **내용이 길어도 무방**하다.
- 대상:
  1. **사용자 간 전화 (Human-to-Human)**: 기본 정보 + 통화 내용(STT) + Knowledge Base 처리(지식 추출, ChromaDB 저장)
  2. **AI 응대 전화 (AI Voicebot)**: 기본 정보 + **주요 액션별 누적 흐름**(각 시간 포함)

---

## 2. 현재 CDR 구조(참고)

- **저장**: `./cdr/cdr-YYYY-MM-DD.jsonl` (JSON Lines, 일자별)
- **현재 예시** (`cdr/cdr-2026-02-22.jsonl`): `call_id`, `caller`, `callee`, `start_time`, `answer_time`, `end_time`, `duration`, `termination_reason`, `has_recording`, `recording_path`, `recording_duration`, `recording_type`, `metadata` (예: `greeting_phase1`, `greeting_phase2`)
- **작성 시점**: 통화 종료 시 `sip_endpoint.py`에서 `CDRWriter.write_cdr(cdr)` 1회 호출
- **주요 필드**: `call_id`, `caller`, `callee`, `start_time`, `answer_time`, `end_time`, `duration`, `termination_reason`, `has_recording`, `recording_path`, `recording_duration`, `recording_type`, `metadata` (현재 `greeting_phase1`, `greeting_phase2` 등)

---

## 3. 개선 CDR 스키마 (제안)

### 3.1 공통: 통화 기본 정보 (유지·보강)

| 필드 | 타입 | 설명 |
|------|------|------|
| `call_id` | string | 통화 ID |
| `caller` | string | 발신 SIP URI |
| `callee` | string | 착신 SIP URI |
| `call_type` | string | **"user_to_user"** \| **"ai_attended"** (신규) |
| `start_time` | string (ISO) | 통화 시작 |
| `answer_time` | string \| null | 응답 시각 |
| `end_time` | string (ISO) | 통화 종료 |
| `duration` | float | 통화 시간(초) |
| `setup_time` | float \| null | 호 설정 시간(초) |
| `termination_reason` | string | normal / timeout / cancel / error / rejected |
| `media_mode` | string | bypass / reflecting |
| `has_recording` | bool | 녹음 여부 |
| `recording_path` | string \| null | 녹음 경로(상대) |
| `recording_duration` | float \| null | 녹음 길이(초) |
| `recording_type` | string \| null | sip_call / ai_call |

### 3.2 사용자 간 전화 전용: `detail.user_to_user`

| 필드 | 타입 | 설명 |
|------|------|------|
| `transcript` | string | 통화 전체 STT/전사 (발신자/착신자 구분 형식 유지) |
| `transcript_source` | string | "recordings/{dir}/transcript.txt" 등 출처 |
| `knowledge` | object | Knowledge Base 처리 요약 (아래) |

**knowledge** 구조:

| 필드 | 타입 | 설명 |
|------|------|------|
| `extraction_triggered` | bool | 지식 추출 실행 여부 |
| `extraction_finished_at` | string \| null | 추출 완료 시각(ISO) |
| `items_extracted` | int | 추출된 항목 수 (qa_pair, entity, knowledge 등) |
| `chromadb_upserts` | array | ChromaDB에 저장된 항목 목록 (디버그용) |

**chromadb_upserts** 각 항목:

| 필드 | 타입 | 설명 |
|------|------|------|
| `doc_id` | string | 문서 ID |
| `doc_type` | string | qa_pair / entity / knowledge |
| `category` | string | 카테고리 |
| `text_preview` | string | 내용 앞 200자 등 |
| `created_at` | string | 저장 시각(ISO) |

### 3.3 AI 응대 전화 전용: `detail.ai_attended`

목표: **주요 액션별로 시간과 함께 누적된 흐름**을 남겨, CDR만 보고도 “인사말 검색 → TTS → RTP”, “발화 구간 → STT → RAG → LLM → TTS → RTP”를 추적할 수 있게 한다.

| 필드 | 타입 | 설명 |
|------|------|------|
| `greeting` | object | 인사말 Phase1/Phase2 처리 (아래) |
| `timeline` | array | 액션별 이벤트 목록 (시간순) |

**greeting** 구조:

| 필드 | 타입 | 설명 |
|------|------|------|
| `phase1` | object | Phase1 인사말 |
| `phase2` | object \| null | Phase2 업무 안내 |

**greeting.phase1** / **phase2** 각각:

| 필드 | 타입 | 설명 |
|------|------|------|
| `source` | string | "tenant_config" (RAG 검색 아님, tenant_config에서 템플릿 선택) |
| `query_at` | string | 인사말 선택/조회 시각(ISO) |
| `text` | string | TTS에 넣은 전체 문장 |
| `tts_pushed_at` | string | TTS 파이프라인에 push한 시각 |
| `rtp_info` | object \| null | RTP 전송 요약(가능 시) |

**rtp_info** (가능한 경우만):

| 필드 | 타입 | 설명 |
|------|------|------|
| `first_packet_at` | string | 첫 RTP 패킷 전송 시각 |
| `last_packet_at` | string | 마지막 RTP 패킷 시각 |
| `payload_bytes` | int | 전송한 오디오 페이로드 총 바이트(선택) |

**timeline** 각 이벤트 요소:

| 필드 | 타입 | 설명 |
|------|------|------|
| `at` | string | 이벤트 시각(ISO) |
| `action` | string | 이벤트 종류(아래 표 참고) |
| `payload` | object | 액션별 상세(아래) |

**action** 값과 **payload** 예시:

| action | payload 예시 | 설명 |
|--------|----------------|------|
| `caller_rtp_start` | `{ "note": "caller 음성 첫 RTP 수신" }` | 발신자 RTP 구간 시작 |
| `stt_interim` | `{ "text": "내일 날씨", "is_final": false }` | STT 중간 결과 |
| `stt_final` | `{ "text": "내일 날씨 어때요?", "is_final": true }` | STT 최종 결과(질의로 사용된 텍스트) |
| `stt_filtered_out` | `{ "text": "...", "reason": "too_short" }` | STT 후처리로 LLM에 넘기지 않은 경우 |
| `rag_search` | `{ "query": "내일 날씨", "owner": "1004", "top_k": 6, "results_count": 3, "elapsed_sec": 0.12, "doc_previews": [ { "id": "...", "score": 0.89, "text_preview": "..." } ] }` | RAG 검색 실행 |
| `rag_cache_hit` | `{ "query": "...", "answer_preview": "...", "confidence": 0.95 }` | Semantic Cache 히트 |
| `llm_request` | `{ "user_text": "내일 날씨 어때요?", "system_prompt_full": "...", "rag_context": "...", "history_turns": 2 }` | LLM 호출 직전: 풀 시스템 프롬프트 + RAG 컨텍스트 + 대화 턴 수 |
| `llm_response` | `{ "response": "내일 날씨는 기상청 홈페이지에서...", "intent": "weather_forecast", "confidence": 0.92, "cache_hit": false, "elapsed_sec": 1.2 }` | LLM 응답 |
| `tts_pushed` | `{ "text": "내일 날씨는...", "chars": 45 }` | TTS에 전달한 텍스트 |
| `tts_rtp_sent` | `{ "duration_sec": 3.2, "payload_bytes": 51200 }` | TTS 오디오 RTP 전송 완료(구간) |
| `hitl_requested` | `{ "reason": "...", "user_text": "..." }` | HITL 요청 발생 |
| `farewell` | `{ "closing_template": "감사합니다. ...", "text": "..." }` | 끝인사 처리 |

- **풀 프롬프트**: `llm_request.system_prompt_full` 에 시스템 프롬프트 전체를 넣어, 디버깅 시 “무슨 지시로 LLM을 호출했는지” CDR만으로 확인 가능하게 한다.
- **ChromaDB 저장**: AI 통화 중 HITL/후처리로 FAQ·지식이 저장된 경우, `action: "chromadb_upsert"`, `payload: { "doc_id", "doc_type", "category", "text_preview" }` 형태로 timeline에 1건씩 추가할 수 있다.

---

## 4. 데이터 수집 방식

### 4.1 원칙

- CDR은 **통화 종료 시 1회** `write_cdr`로 파일에 append한다.
- 상세 내용은 **통화 중** `call_id` 단위로 메모리 버퍼(리스트/딕셔너리)에 **append**만 하고, 종료 시 이 버퍼를 `detail`에 넣어서 `CDR` 객체에 담아 기록한다.

### 4.2 수집 주체

- **CDR 상세 버퍼**를 담당할 저장소가 필요하다. 후보:
  - **A) CallManager 확장**: `call_id` → `CDRDetailBuffer` (greeting, timeline, user_to_user 필드 등)를 보관하고, SIP/AI 파이프라인에서 이 버퍼에만 push.
  - **B) 전역 CDR 컨텍스트 모듈**: `src.events.cdr_context` 같은 모듈에 `get_buffer(call_id)` 를 두고, RAG/LLM/TTS/RTP 등 각처에서 `cdr_context.append_timeline(call_id, event)` 호출.

- **권장**: **B) 전역 CDR 컨텍스트**. CallManager는 “통화 종료 시 버퍼를 꺼내 CDR에 넣고 write”만 담당하고, RAG/LLM/TTS/STT/RTP 등은 CDR 컨텍스트에만 의존하게 하면, SIP 레이어와 AI 파이프라인 결합도를 낮출 수 있다.

### 4.3 사용자 간 전화 수집 지점

| 데이터 | 수집 시점 | 방법 |
|--------|-----------|------|
| transcript | 통화 종료 후, CDR 작성 직전 | `recordings/{recording_dir_name}/transcript.txt` 읽기 (이미 sip_call_recorder 등에서 생성됨) |
| knowledge.extraction_triggered | 지식 추출 스케줄 시점 | CallManager.cleanup_terminated_call / trigger_knowledge_extraction 에서 플래그 설정 |
| knowledge.items_extracted, chromadb_upserts | 지식 추출 완료 시점 | extraction_pipeline / knowledge_extractor 에서 완료 시 콜백 또는 반환값으로 “추출 건수 + upsert 목록”을 CDR 버퍼에 전달 |

- 지식 추출이 **비동기(지연 실행)** 이므로, “추출 완료” 시점에 CDR 버퍼에 merge하거나, “추출 예약됨 + 결과 파일/큐”를 나중에 CDR과 매칭하는 방식 중 하나 선택 필요.  
  **1차 권장**: 추출 완료 시 `cdr_context.merge_user_to_user_knowledge(call_id, items_count, upserts_list)` 로 버퍼만 갱신하고, **CDR 작성은 통화 종료 시점에 이미 한 번 했으면**, “추출 완료 시 CDR 파일 같은 라인을 patch”하는 것은 복잡하므로, **추출 완료 시점에 CDR 한 줄을 추가로 쓰지 않고**, “통화 종료 시점에 추출이 이미 완료되었으면 그때 포함, 아니면 extraction_triggered=true, items_extracted=0, chromadb_upserts=[]” 로 두고, 추출 결과는 별도 로그/테이블로 보강하는 방식**을 권장.  
  또는 **CDR 작성 자체를 “지식 추출 완료 후”로 지연**시키는 방법(예: 지식 추출 태스크가 끝나면 그때 CDR write)도 가능하나, 통화 종료와 추출 완료 사이 지연이 길어질 수 있음.

### 4.4 AI 응대 수집 지점

| 액션 | 코드 위치(참고) | 수집 내용 |
|------|-----------------|-----------|
| 인사말 Phase1/Phase2 | `rag_processor.py` `_send_greeting_if_needed` | source=tenant_config, query_at, text, tts_pushed_at; TTS 완료/ RTP 전송 시점은 TTSCompleteNotifier·RTP 레이어에서 버퍼에 push |
| caller RTP 시작 | RTP relay (caller → 파이프라인) | `caller_rtp_start` |
| STT interim/final | `rag_processor.py` (TranscriptionFrame 처리) | `stt_interim` / `stt_final` (text, is_final); 필터 아웃 시 `stt_filtered_out` |
| RAG 검색 | `adaptive_rag_node` / `rag_engine.search` | query, owner, top_k, results_count, elapsed_sec, doc_previews |
| RAG 캐시 히트 | `semantic_cache` check_cache_node | query, answer_preview, confidence |
| LLM 요청 | `generate_response_node` (시스템 프롬프트 조립 직후) | user_text, system_prompt_full, rag_context, history_turns |
| LLM 응답 | `generate_response_node` (LLM 반환 직후) / agent 결과 | response, intent, confidence, cache_hit, elapsed_sec |
| TTS push | `rag_processor` TextFrame push | text, chars |
| TTS RTP 전송 | TTSCompleteNotifier / RTP 출력 측 | duration_sec, payload_bytes(가능 시) |
| HITL | hitl_alert_node / HITLManager | reason, user_text |
| Farewell | update_state_node (closing_template 선택) | closing_template, text |

- **시간(at)**: 각 이벤트 발생 시 `datetime.utcnow().isoformat()` 또는 `time.time()` 기반 ISO 문자열로 저장.

---

## 5. 파일 형식 및 크기

- **형식**: **JSON Lines** (`cdr-YYYY-MM-DD.jsonl`). 1레코드 = 1통화 1 JSON 객체.
- **원칙**: CDR은 **한 줄에 한 레코드**로 저장하는 것이 원칙(표준 JSONL). 파싱·스크립트 처리에 유리.
- **디버깅 모드(가시성)**: 현재는 디버깅 편의를 위해 **JSON을 들여쓰기(정렬)하여** 한 레코드가 여러 줄로 출력되도록 할 수 있다. 설정으로 켜고 끈다.

### 5.1 CDR 출력 형식 (Config)

| Config 키 | 타입 | 기본값 | 설명 |
|-----------|------|--------|------|
| `cdr.pretty_json` | bool | `false` | `true`이면 레코드 단위로 JSON을 들여쓰기(indent)하여 가시적으로 저장. `false`이면 한 줄 한 레코드(compact). |

- **`pretty_json: false` (기본)**  
  - 한 줄에 한 JSON 객체. `f.write(cdr.to_json() + '\n')`  
  - JSON Lines 표준. 기존 `read_cdr_files`(한 줄씩 `json.loads`) 그대로 사용 가능.
- **`pretty_json: true`**  
  - 한 레코드가 여러 줄(들여쓰기된 JSON). `json.dumps(..., indent=2, ensure_ascii=False)` 후 기록.  
  - 레코드 구분: 레코드 끝에 개행 2개(`\n\n`)를 두어 다음 레코드와 구분.  
  - **읽기**: 레코드 구분자가 `\n\n`이므로, 파일을 `\n\n`으로 split 후 각 블록을 `json.loads` 하면 됨. (문자열 값 내부에 `\n\n`이 있으면 이론상 분리 오류 가능; 디버그 모드에서만 사용하므로 허용.)  
  **구현**: `call_history.read_cdr_files`에서 compact(한 줄 파싱)를 먼저 시도하고, 파싱 실패 시 `\n\n`으로 split하여 pretty 형식으로 읽음.

- **크기**: 1통화당 레코드가 수십 KB~수백 KB가 될 수 있음. 디버그/분석용이므로 허용. 필요 시 로테이션/압축은 별도 정책으로 검토.

---

## 6. 기존 호환성

- `call_type` 없으면 기존 클라이언트는 “필드 없음”으로 처리; 있으면 `user_to_user` / `ai_attended` 로 구분.
- `detail` 없으면 “상세 없음”으로 처리.
- API/대시보드에서 CDR 읽을 때 `detail.user_to_user` / `detail.ai_attended` 는 선택적으로 파싱하면 됨.

---

## 7. 구현 순서 제안

0. **CDR 출력 형식(Config + Writer)** (선구현): `cdr.pretty_json` 설정 추가, `CDRWriter`에서 `pretty_json`이 true일 때 들여쓰기 JSON + `\n\n` 구분으로 기록. CDR 읽기 시 `pretty_json` 모드 파일은 `\n\n` split 후 `json.loads` 지원.
1. **CDR 스키마 확장**: `CDR` dataclass에 `call_type`, `detail` 필드 추가; `to_dict`/`from_dict` 반영.
2. **CDR 컨텍스트 모듈**: `get_buffer(call_id)` / `append_timeline` / `set_greeting` / `set_user_to_user` / `get_and_clear(call_id)` API 정의 및 메모리 저장소 구현.
3. **AI 타임라인 수집**: RAG 검색, LLM 요청/응답, STT final/interim, TTS push, 인사말 처리 등 위 표 기준으로 각 위치에서 `cdr_context.append_timeline(call_id, { at, action, payload })` 호출.
4. **사용자 간 전화**: 통화 종료 시 transcript 파일 읽어 `detail.user_to_user` 구성; 지식 추출은 “완료 시 버퍼 merge” 또는 “종료 시 추출 결과 대기(타임아웃)” 중 하나로 반영.
5. **통화 종료 시**: CallManager/SIP Endpoint에서 `cdr_context.get_and_clear(call_id)` 로 버퍼 획득 후 `CDR.detail` 에 넣고 `write_cdr` 호출.
6. **문서화**: 본 설계서를 기준으로 “CDR 필드 설명” 및 “디버깅 시 CDR 보는 법” 가이드 추가.

---

## 8. CDR 변수 입력 점검 (현재 구현)

CDR은 `sip_endpoint._cleanup_call()` 내에서 1회 생성·기록된다. 각 필드의 값 출처와 주의사항은 아래와 같다.

| CDR 필드 | 값 출처 | 비고 |
|----------|---------|------|
| `call_id` | `call_info['original_call_id']` (없으면 인자 `call_id`) | **항상 원본 Call-ID** 사용. 대시보드·녹음·인사말과 동일 키로 통일. |
| `caller` | `call_info['caller_username']`, `call_info['caller_addr'][0]` | SIP URI. addr 없으면 `'unknown'`. |
| `callee` | `call_info['callee_username']`, `call_info['callee_addr'][0]` | 동일. |
| `start_time` | `call_info['start_time']` | INVITE 처리 시 `datetime.now()` 저장. 문자열이면 `fromisoformat` 변환. |
| `answer_time` | `call_info['answer_time']` | 200 OK 처리 시 설정. |
| `end_time` | `datetime.now()` | CDR 작성 시점. |
| `duration` | `(end_time - start_time).total_seconds()` | 통화 전체 구간. |
| `setup_time` | `(answer_time - start_time).total_seconds()` | answer_time·start_time 둘 다 있을 때만 설정. |
| `termination_reason` | `TerminationReason.NORMAL` | 현재는 정상 종료만. |
| `caller_ip` / `callee_ip` | `call_info['caller_addr'][0]`, `call_info['callee_addr'][0]` | addr가 (ip, port) 튜플일 때 [0]. 없으면 None. |
| `has_recording` | `recording_metadata is not None` | 녹음 중지 성공 시에만 True. |
| `recording_path` | `recording_metadata['files']['mixed']` | SIP 녹음기 반환 상대 경로. |
| `recording_duration` | `recording_metadata['duration']` | 초 단위. |
| `recording_type` | `recording_metadata['type']` | 예: "sip_call". |
| `metadata.greeting_phase1/2` | `pop_greeting(original_call_id)` | **original_call_id**로 조회 (RAG/인사말 저장 키와 일치). |

- **call_info**는 `_active_calls.pop(call_id)`로 얻는다. `_cleanup_call`은 BYE/CANCEL 등에서 **original_call_id**를 넘기도록 호출하는 것이 좋고, CDR·인사말은 항상 **original_call_id** 기준으로 기록·조회한다.
- **call_info** 구조: INVITE 처리 시 `_active_calls[call_id]`에 `original_call_id`, `caller_username`, `callee_username`, `caller_addr`, `callee_addr`, `start_time`, `answer_time`(200 OK 시), `b2bua_call_id` 등 저장.

---

## 9. 요약

- **목적**: CDR만 보면 전화 처리 전 과정을 복기할 수 있도록 상세 기록.
- **사용자 간 전화**: 기본 정보 + **전체 STT(transcript)** + **Knowledge Base 처리(지식 추출·ChromaDB upsert 요약)**.
- **AI 응대**: 기본 정보 + **인사말 Phase1/Phase2(출처, 시각, TTS/RTP)** + **타임라인(발화 구간, STT, RAG 검색/캐시, LLM 풀 프롬프트·응답, TTS, RTP, HITL, farewell)**.
- **수집**: 통화 중 `call_id` 단위 버퍼에만 append, 통화 종료 시 버퍼를 `detail`에 넣어 1회 write.
- **변수 점검**: §8에서 현재 CDR 필드별 값 출처와 original_call_id 일원화를 정리함.

이 설계대로 구현하면 “CDR만 확인하면 전화가 어떻게 처리되었는지 모두 알 수 있는” 상세 CDR을 달성할 수 있다.
