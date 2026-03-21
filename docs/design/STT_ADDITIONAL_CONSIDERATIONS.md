# STT 추가 고려 사항: 주변 소리·불완전 발화·천천히 말하기

사용자 관점에서 두 가지 이슈를 고려한 기술 리서치 및 대응 방안 정리.

---

## 1. 문제 정의

### 1.1 주변 소리/불완전 발화 인입

- **상황**: 사용자가 말하지 않았는데 주변 말소리(대화, 함성 등)가 마이크로 들어옴.
- **결과**: "여기야", "와" 등 **문장이 완전하지 않은 텍스트**가 STT 결과로 나와, 그대로 LLM 질의로 넘어감.
- **목표**: 이런 **의미 없거나 불완전한 발화**는 질의로 쓰지 않고 걸러내기.

### 1.2 천천히/생각하며 말하기

- **상황**: 사용자가 생각하면서 말을 천천히 하거나, 중간에 쉬었다가 이어서 말함.
- **결과**: **침묵(묵음) 구간**에서 곧바로 “발화 종료”로 판단되어, **문장이 완성되기 전에** 질의가 나감.
- **목표**: “아직 말을 다 안 끝냈다”는 구간에서는 질의를 보내지 않고, **진짜 턴 종료**일 때만 STT 결과를 LLM으로 넘기기.

---

## 2. 기술 리서치 요약

### 2.1 주변 소리·불완전 발화·False Trigger

| 주제 | 내용 |
|------|------|
| **Whisper 비음성 할루시네이션** | 비음성/배경 소리에서도 텍스트가 나오는 현상. 논문에서 VAD + “Bag of Hallucinations” 후처리로 약 67% 감소 보고. [arXiv:2501.11378 등] |
| **Intent / False trigger 억제** | “기기에게 말하는지 vs 다른 사람에게/생각 aloud” 구분. 스트리밍 E2E 모델로 약 8.7% EER, 1.4초 지연 내 구분 가능. |
| **짧은/의미 없는 발화 필터** | filler("um", "어") 탐지기(UM Detector), 짧은 발화·불완전 문장을 **STT 이후 텍스트**로 걸러내는 휴리스틱이 많이 사용됨. |

**정리**:  
- **음성 구간만** 쓰려면 VAD + (가능하면 Semantic VAD)로 “진짜 사용자 발화”만 잘라내고,  
- **텍스트 품질**은 STT **후처리**로 “짧은/불완전/의미 없음”을 판별해 LLM으로 넘기지 않는 방식이 현실적.

### 2.2 천천히 말하기·침묵·End-of-Turn Detection

| 주제 | 내용 |
|------|------|
| **침묵만으로 판단의 한계** | 단순 “N초 침묵 → 발화 종료”는 **생각하며 쉬는 구간**과 **진짜 턴 종료**를 구분 못 함. 사용자 스트레스·잘못 끊김 발생. |
| **Semantic VAD / End-of-Turn** | **말의 내용(억양·문법·속도)**까지 보는 “발화 완료 확률” 분류기 사용. “um…” 같은 비완결 억양이면 더 기다림. [OpenAI Realtime API semantic_vad, Pipecat Smart Turn 등] |
| **Google Cloud STT** | `enable_voice_activity_events` + `voice_activity_timeout`(speech end 500ms~60s)로 발화 종료 타임아웃 조절 가능. `latest_short`는 단일 발화용. |
| **연구** | End-of-Turn Detection(ETD) 데이터셋, Disfluency·불완전 발화 공동 탐지 등. 침묵 휴리스틱만으로는 한계, **음성+텍스트(또는 음성 의미)** 결합이 유리. |

**정리**:  
- **우리 파이프라인**: 이미 **Silero VAD → SmartTurn(LocalSmartTurnAnalyzerV3)** 로 “침묵 후에도 문법/억양 기반으로 완료 여부” 판단 중.  
- 천천히 말하기 이슈는 **Smart Turn 임계값·max_hold_secs** 조정, 또는 **Smart Turn v2**(한국어 95.5% 정확도, 14언어) 도입으로 완화 가능.

---

## 3. 참고 자료·GitHub·문서

### 3.1 GitHub / 오픈소스

| 리소스 | 설명 |
|--------|------|
| [deepgram/deepgram-eos-heuristics](https://github.com/deepgram/deepgram-eos-heuristics) | Deepgram 실시간 API + **Silero VAD** + 커스텀 휴리스틱으로 end-of-speech 감지. “음성 구간”과 “발화 종료” 조합 참고용. |
| [pipecat-ai/smart-turn](https://github.com/pipecat-ai/smart-turn) | **Smart Turn v2** 학습/추론 코드. 우리는 Pipecat 파이프라인에서 V3 사용 중. |
| [nikolawhallon/temp-utterance-end](https://github.com/nikolawhallon/temp-utterance-end) | Endpointing 한계 설명 (VAD 기반만으로는 부족). |
| [ezxzeng/um_detector](https://github.com/ezxzeng/um_detector) | Filler("um" 등) 탐지 – 짧은/의미 없는 발화 스킵 참고. |
| [latishab/turnsense](https://github.com/latishab/turnsense) | 경량 end-of-utterance 감지 모델 (SmolLM2 기반). |

### 3.2 문서·API

| 리소스 | 설명 |
|--------|------|
| [Google Cloud STT – Voice activity events and timeouts](https://cloud.google.com/speech-to-text/v2/docs/voice-activity-events) | `enable_voice_activity_events`, speech begin/end timeout(500ms~60s) 설정. |
| [Google Cloud STT – Single utterance](https://cloud.google.com/speech-to-text/v2/docs/single-utterance) | `latest_short` + single utterance로 짧은 발화만 인식 시 스트림 자동 종료. |
| [OpenAI Realtime API – VAD](https://developers.openai.com/api/docs/guides/realtime-vad/) | Server VAD(silence_duration_ms 등) vs **Semantic VAD**(“아직 말 안 끝났다” 확률) 설명. |
| [Deepgram – Utterance End](https://developers.deepgram.com/docs/utterance-end) | 침묵 간격 기반 UtteranceEnd. “finalized word 이후 침묵”만 감지해 한계 있음. |

### 3.3 논문·벤치마크

| 리소스 | 설명 |
|--------|------|
| [Improving endpoint detection in E2E streaming ASR for conversational speech](https://arxiv.org/abs/2505.17070) | 대화형 발화에서 endpoint 감지 개선. |
| [Speculative End-Turn Detector for Efficient Speech Chatbot](https://arxiv.org/abs/2503.23439) | 턴 종료 추론, “아직 말 안 끝남” 구분. |
| [Disfl-QA (Google)](https://research.google/pubs/disfl-qa-a-benchmark-dataset-for-understanding-disfluencies-in-question-answering/) | 비유창성(disfluency)·질의 응답에서의 불완전 발화 벤치마크. |
| [Joint, Incremental Disfluency Detection and Utterance Segmentation](https://aclanthology.org/E17-1031.pdf) | 비유창성 탐지와 발화 분할을 함께 처리. |

---

## 4. 현재 프로젝트 구성과의 연결

- **파이프라인**: `RTP → SileroVAD → SmartTurn(V3) → Google STT → RAG-LLM → TTS → RTP`
- **VAD**: `silero_vad.stop_secs`(침묵 N초 후 UserStoppedSpeakingFrame).
- **Smart Turn**: VAD가 “발화 종료”로 보낸 뒤, **LocalSmartTurnAnalyzerV3**가 문법/억양 등으로 “완료 vs 미완료” 판단. 미완료면 일정 시간(max_hold_secs) 더 hold.

즉,  
- **1번(주변 소리/불완전 문장)** → STT **출력 텍스트**에 대한 **후처리 필터**가 추가로 필요.  
- **2번(천천히 말하기)** → 이미 Smart Turn으로 완화 중; **설정 튜닝** 또는 **Smart Turn v2**(한국어 지원) 검토로 보강 가능.

---

## 5. 권장 방향 (요약)

### 5.1 주변 소리·불완전 발화(1번)

- **STT 후처리**에서 아래를 적용하는 레이어를 두는 것을 권장.
  - **최소 길이**: 글자 수 또는 단어 수가 일정 미만이면 “질의로 사용 안 함”(드롭 또는 재질의 유도).
  - **불완전/의미 없음 휴리스틱**:  
    - 예: 단일 단어만 있음(“여기야”, “와”), 문장 부호/종결 없음, 특정 패턴(함성·감탄만 있는 목록) 등.
  - (선택) **의도/완결성 분류기**: 짧은 문장을 “질의로 쓸 만한가” 점수로 걸러내기. (Disfl-QA·ETD 등 참고)
- **음성 구간**은 기존처럼 Silero VAD + Smart Turn으로 “진짜 발화 구간”만 잘라서 STT에 넘기는 것이 유리.

### 5.2 천천히 말하기(2번)

- **Smart Turn 유지·강화**  
  - `max_hold_secs`를 넉넉히(예: 2.0초 이상) 주어, 침묵이 길어도 “아직 완료 아님”이면 STT 결과를 바로 넘기지 않기.  
  - 필요 시 **Smart Turn v2**(한국어 95.5%, 14언어)로 교체 검토 – Pipecat 쪽 문서/코드 참고.
- **Google Cloud STT**  
  - 스트리밍 사용 시 `voice_activity_timeout`(speech end)를 **길게**(예: 1.2~2.0초) 주면, 서버 측에서도 “침묵 후 조금 더 기다린 뒤” 종료 처리 가능. (현재 파이프라인에서 Google STT 옵션 노출 여부 확인 후 적용.)

### 5.3 정리

- **1번**: GitHub/논문에서는 “VAD + 후처리(짧은/불완전/할루시네이션 필터)” 조합이 일반적. 우리는 **STT 결과 텍스트**에 대한 **최소 길이 + 불완전 휴리스틱(및 선택적 분류기)** 도입을 추천.
- **2번**: “침묵만으로 판단하지 말고 의미(문법·억양)까지 보라”는 게 연구·상용(Semantic VAD, Smart Turn) 쪽 공통 권장. 이미 Smart Turn V3를 쓰고 있으므로, **튜닝 + (필요 시) Smart Turn v2**가 다음 단계.

---

## 6. STT 후처리 필터 설계 (1번 도입)

VAD + 후처리 조합 중 **STT 결과 텍스트**에 대한 **최소 길이 + 불완전 휴리스틱**을 도입한 설계.

### 6.1 위치

- **적용 시점**: Google STT → RAG 프로세서 구간. RAG 프로세서가 `TranscriptionFrame`을 수신한 직후, **LLM/Agent 호출 전**에 한 번 검사.
- **구성 요소**: `stt_post_filter` 모듈(최소 길이 + 휴리스틱)을 두고, `RAGLLMProcessor`가 이 필터를 호출해 "질의로 쓸 만한가" 판단. 통과하지 못하면 해당 발화는 LLM으로 넘기지 않고 드롭(및 선택적으로 짧은 안내 TTS).

### 6.2 설정 (config)

`ai_voicebot.stt_post_filter` 아래에 다음 항목을 둠.

| 키 | 타입 | 기본값 | 설명 |
|----|------|--------|------|
| `enabled` | bool | true | STT 후처리 필터 사용 여부. |
| `min_chars` | int | 2 | 이 글자 수 미만이면 질의로 사용하지 않음(공백 제외). |
| `min_words` | int | 1 | 이 단어 수 미만이면 질의로 사용하지 않음(공백 기준 분리). |
| `skip_only_exclamations` | bool | true | 발화 전체가 감탄/단문 목록에만 해당하면 스킵(예: "와", "여기야"). |
| `exclamation_patterns` | list[str] | (내장 목록) | 스킵할 감탄·단문 패턴(정확 일치). 비어 있으면 내장 목록만 사용. |
| `reply_on_drop` | bool | false | 스킵 시 사용자에게 안내 TTS 재생 여부. true면 `reply_message` 재생. |
| `reply_message` | str | "다시 말씀해 주시겠어요?" | `reply_on_drop`가 true일 때 재생할 문장. |

### 6.3 규칙 (휴리스틱)

1. **최소 길이**  
   - `len(text.replace(" ", "")) < min_chars` → 스킵 (사유: `too_short`).  
   - 단어 수 `len(text.split()) < min_words` → 스킵 (사유: `too_few_words`).

2. **불완전/의미 없음**  
   - 발화가 **내장 감탄·단문 목록** 또는 `exclamation_patterns`에만 해당(공백 제거 후 일치) → 스킵 (사유: `only_exclamation`).  
   - 내장 목록 예: "와", "여기야", "응", "어", "음", "네", "아", "오", "으", "그래", "ㅋㅋ", "ㅎㅎ" 등 단독/짧은 감탄·대답.

3. **(선택) 문장 종결**  
   - 추후 필요 시 "마침표/물음표/느낌표 등으로 끝나지 않으면 불완전" 규칙 추가 가능. 현재 버전에서는 최소 길이 + 감탄 목록만 적용.

4. **통과**  
   - 위 조건에 걸리지 않으면 "질의로 사용"(`should_use=True`). RAG/LLM으로 전달.

### 6.4 로깅

- 스킵 시: `stt_post_filter_dropped` 이벤트로 `call_id`, `text_preview`, `reason`, `ts_iso` 기록.
- 통과 시: 기존 `rag_llm_user_input` 등 그대로 유지.

### 6.5 선택적 분류기 (추후)

- "질의로 쓸 만한가" 이진 분류기를 두고, 휴리스틱 통과 후 한 번 더 점수로 걸러내는 방식은 추후 도입 가능. (Disfl-QA·ETD 등 참고.)

---

이 문서는 위 리서치와 현재 파이프라인을 바탕으로 한 설계 참고용이며, 실제 구현 시 `config`(VAD stop_secs, smart_turn max_hold_secs, stt_post_filter 임계값 등)는 운영 데이터로 조정하는 것을 권장합니다.

---

**작성일**: 2026-02-22  
**관련**: `pipeline_builder.py`, `smart_turn_processor.py`, `rag_processor.py`, `stt_post_filter.py`, Silero VAD, Google Cloud STT
