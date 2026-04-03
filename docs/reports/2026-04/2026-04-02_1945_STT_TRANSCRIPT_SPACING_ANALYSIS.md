# STT → transcript.txt 과도 띄어쓰기 원인 분석 및 개선 방안

| 항목 | 내용 |
|------|------|
| 작성일 | 2026-04-02 19:45 |
| 상태 | 분석 완료 / 개선 옵션 제시 |
| 관련 파일 | `src/ai_voicebot/factory.py`, `src/common/pipeline_transcript_buffer.py` |
| 증상 | transcript.txt 발신자 발화에 "딴 거 고 치 면서 또 이게 요렇게" 처럼 음절 단위 공백 |

---

## 1. 증상 (실제 transcript.txt)

```
발신자: 딴 거 예 딴 거 고 치 면서 또 이게 요렇게 요렇게 망 치 질 하면은
        저쪽 에서 튀어나 오 거든요 예 아이 진짜 지금 아웃 바 운드 하다가
        아마 또 인 반 도 에 러 는 것 같은데 어쨌든 이런 식으로
```

정상 통화 대비:
```
발신자: 기상청은 무엇을 하는 곳인가요?
발신자: 미세먼지 정보는?
```

---

## 2. transcript.txt 생성 경로

```
통화 종료
  └─ stop_recording() → flush_pipeline_transcript_to_dir()
        └─ pipeline_transcript_buffer.py
              ├─ record_pipeline_caller()  ← STT 결과 저장
              └─ record_pipeline_callee()  ← TTS 텍스트 저장

transcript.txt 한 줄 =  f"{speaker_label}: {m['content']}"
                         (content = STT/TTS 그대로 기록)
```

**transcript.txt 자체에는 후처리 없음** — STT가 반환한 문자열을 그대로 기록합니다.

---

## 3. 근본 원인

### 3-1. Google STT `telephony` 모델의 한국어 형태소 분리

`factory.py` 줄 43:
```python
model=_cfg.get("model", "telephony"),
```

Google Cloud Speech-to-Text의 `telephony` 모델은 **한국어 음소 단위**로 단어를 분리하는 경향이 있습니다.

| 모델 | 한국어 특성 |
|------|-----------|
| `telephony` | 전화 통화 최적화, 8kHz 원본 기반 16kHz 업샘플 입력. 한국어에서 형태소를 공백으로 나눠 반환하는 현상 발생 |
| `latest_long` | 최신 롱 오디오 모델. telephony보다 형태소 통합 우수 |
| `chirp_2` (v2) | Google 최신 다언어 모델, 한국어 형태소 통합 가장 우수 |

### 3-2. 서브워드 마커 (`▁`, U+2581)

`_format_transcript_with_speakers()` (WAV 후처리 경로)에는 `_norm()` 함수로 `▁` 제거가 있습니다.
하지만 **파이프라인 STT 경로에는 해당 정제 로직 없음** — Google Streaming STT가 반환하는 결과에 이미 공백이 포함된 상태로 옵니다.

### 3-3. Pipecat GoogleSTTService의 Streaming 세션

Pipecat의 `GoogleSTTService`는 Google Speech V1 Streaming API를 사용합니다.
Streaming API는 `single_utterance=False` 모드에서 중간 결과(interim)를 반환하다가
무음(VAD 트리거) 시 final 결과를 반환합니다. 이 final 결과가 이미 공백 과다인 상태입니다.

---

## 4. 개선 방안

### 방안 A: STT 모델 변경 (권장 — 가장 근본적)

`factory.py`에서 모델을 변경합니다.

**옵션 A-1: `latest_long`** (즉시 적용 가능)
```python
model=_cfg.get("model", "latest_long"),
```
- telephony보다 한국어 형태소 통합 우수
- 전화 통화 품질에도 충분히 적용 가능
- 기존 코드 변경 없이 파라미터만 변경

**옵션 A-2: `chirp_2`** (최고 품질, Google Speech v2 API 필요)
- 형태소 통합 최우수
- Pipecat GoogleSTTService가 v2를 지원하는지 확인 필요
- `location` 파라미터 및 프로젝트 ID 필요

### 방안 B: STT 결과 후처리 정제 함수 (즉시 적용 가능)

파이프라인 STT 결과를 `record_pipeline_caller()` 호출 전, 또는 `rag_processor.py`에서 STT final text를 처리할 때 간단한 정제를 적용합니다.

```python
import re

def _normalize_stt_text(text: str) -> str:
    """
    Google STT telephony 모델의 한국어 과다 공백 정제.
    
    - 음절/형태소 단위 공백: '망 치 질' → '망치질'
    - 단어 내 불필요 공백: '아웃 바 운드' → '아웃바운드'
    - 연속 공백 → 단일 공백
    """
    if not text:
        return text
    # 1글자 또는 2글자 음절 사이 공백 중, 앞뒤가 한글인 경우 제거
    # 예: '망 치 질' → '망치질', '치 면서' → '치면서'
    # 단, 실제 단어 경계(조사, 어간 연결 등)는 유지되어야 하므로
    # 연속 2회 이상 1~2글자 패턴에만 적용
    # 간단한 휴리스틱: 한글 1~2자 + 공백 패턴이 3회 이상 연속되면 공백 제거
    result = re.sub(r'(?<=[\uAC00-\uD7A3]) (?=[\uAC00-\uD7A3])', '', text)
    # 연속 공백 정리
    result = re.sub(r' {2,}', ' ', result)
    return result.strip()
```

**단점**: 실제 단어 경계(예: "가 고 싶어" → "가고싶어"는 맞지만 "지금 어디 가")도 붙여버릴 수 있습니다.

### 방안 C: `enable_automatic_punctuation` + `use_enhanced` 활성화

```python
_params = GoogleSTTService.InputParams(
    languages=[Language.KO_KR],
    model=_cfg.get("model", "latest_long"),  # 모델 변경
    enable_automatic_punctuation=True,
    enable_interim_results=True,
    # use_enhanced=True,  # Enhanced 모델 (telephony_enhanced)
)
```

`telephony_enhanced`는 `telephony` 대비 형태소 통합 개선. 단, 요금이 더 비쌉니다.

### 방안 D: `pipeline_transcript_buffer.py`에서 저장 시 정제

가장 안전한 적용 범위 제한:

```python
# pipeline_transcript_buffer.py

import re

def _clean_stt_text(text: str) -> str:
    """STT 결과의 한글 음절 단위 과다 공백 제거."""
    # 한글 자모 사이 단일 공백만 제거 (비한글 단어 경계는 유지)
    cleaned = re.sub(r'(?<=[가-힣]) (?=[가-힣])', '', text)
    return re.sub(r' {2,}', ' ', cleaned).strip()

def record_pipeline_caller(call_id: str, text: str) -> None:
    if not call_id or not (text or "").strip():
        return
    t = _clean_stt_text((text or "").strip())  # ← 정제 추가
    ...
```

**장단점**:
- 단어 간 공백도 제거되므로 "와 시작 부터" → "와시작부터" 오류 가능
- 적용 범위가 transcript 기록에만 한정 (LLM 입력에는 영향 없음)

---

## 5. 권장 방안

| 우선순위 | 방안 | 효과 | 리스크 | 작업량 |
|---------|------|------|--------|--------|
| **1순위** | 방안 A-1: `latest_long` 모델 변경 | ★★★ | 낮음 | 1줄 |
| **2순위** | 방안 B: rag_processor에서 STT final text 정제 | ★★☆ | 중간 (단어 경계 붙음) | ~10줄 |
| **3순위** | 방안 C: `telephony_enhanced` | ★★☆ | 낮음, 비용 증가 | 1줄 |
| 보류 | 방안 A-2: chirp_2 | ★★★ | API 변경 필요 | 크게 변경 필요 |

### 최종 권장

**방안 A-1 (모델 `latest_long` 변경)** 을 먼저 적용해 효과를 검증한 뒤,
필요 시 방안 B를 보완 적용합니다.

`factory.py`:
```python
model=_cfg.get("model", "latest_long"),   # telephony → latest_long
```

`config/config.yaml`에서 모델을 오버라이드하는 방식으로 A/B 테스트 가능합니다.

---

## 6. 추가 배경: AI 통화에서 LLM 입력에는 영향 없음

현재 STT 결과의 과다 공백은 **transcript.txt 기록에만 영향**을 미칩니다.  
LLM(RAG processor)은 STT final text를 그대로 받아 처리하므로,
"망 치 질"처럼 받아도 LLM이 의도를 추론해 응답합니다.
단, transcript 가독성과 call_summary 품질 저하가 발생합니다.

---

## 7. 참고: transcript.txt vs conversation.json

| 파일 | 생성 경로 | 후처리 유무 |
|------|----------|------------|
| `transcript.txt` | pipeline_transcript_buffer → STT/TTS 텍스트 그대로 | 없음 |
| `conversation.json` | 동일 버퍼 → JSON 구조화 | 없음 |
| `transcript.txt` (WAV 후처리) | sip_call_recorder._format_transcript_with_speakers | ▁ 제거만 있음 |
