# 유용성 판단(judgment) JSON 파싱 실패 원인 정리

## 현상

- 로그: `JSON parse failed, attempting cleanup`, `Expecting value: line 3 column 16`
- 응답 예: `{"is_useful": true, "confidence":` 에서 끊김 (46자 수준)
- LLM이 **완성되지 않은 JSON**을 반환해 파싱 에러 발생

---

## 원인 1: 지식 추출 경로에서 `judgment_max_output_tokens` 미전달 (수정됨)

- **judge_usefulness**는 `config`에서 `judgment_max_output_tokens`(또는 `max_output_tokens`)를 읽어 `max_output_tokens`로 API에 전달한다.
- **config.yaml**에는 `judgment_max_output_tokens: 1024`가 있으나,
- **지식 추출(통화 종료 후)** 은 **sip_endpoint**에서 별도로 LLM을 만들어 쓰는데, 여기서 **gemini_config_dict**를 만들 때 `judgment_max_output_tokens`를 넣지 않고 있었다.
- 그 결과 이 경로의 LLMClient에는 `max_tokens`(또는 `max_output_tokens`)만 전달되고, 기본값 500 등 **작은 값**이 쓰였다.
- 500 토큰이어도 짧은 JSON에는 보통 충분하지만, **다른 원인(아래)으로 응답이 46자에서 끊긴 경우**와 맞물려, “잘린 JSON”이 그대로 나와 파싱이 실패한 것으로 보인다.

**조치:**  
`sip_endpoint.py`에서 지식 추출용 LLM 생성 시 `judgment_max_output_tokens`(및 필요 시 `max_output_tokens`)를 포함해 **전체 gemini 설정을 넘기도록** 수정함.  
→ 이제 config.yaml의 `judgment_max_output_tokens: 1024`가 해당 LLM에도 적용된다.

---

## 원인 2: Gemini API의 조기 종료 (finish_reason)

- 응답이 **중간에 끊기는** 경우(예: 46자, 156자)는 **토큰 한도**보다 **API/모델이 일찍 생성 중단**한 경우에 해당한다.
- 로그에서 **finish_reason: "2"** → Gemini 쪽 **MAX_TOKENS**(enum 2). `max_output_tokens=1024`여도 짧게 끊길 수 있음(API 동작·내부 한도).
- 가능한 이유:
  - **finish_reason = MAX_TOKENS (2)**: 내부적으로 토큰 한도로 판단해 잘라버리는 경우.
  - **finish_reason = SAFETY (3) / RECITATION (4)**: 정책으로 출력이 잘리거나 빈 응답.
  - **Unterminated string**: `extracted_info` 배열 안의 `"text": "기상청` 처럼 문자열 값 중간에서 끊기면 JSON 파싱 실패.

**조치:**  
- `llm_judgment_response` 로그에 **finish_reason**을 **문자열**로 기록 (1=STOP, 2=MAX_TOKENS, 3=SAFETY, 4=RECITATION).  
- **Unterminated string** 복구: 따옴표 홀수 개면 닫는 `"` 추가 후 `]` `}` 로 배열/객체 닫기 → 파싱 재시도.

---

## 원인 3: extracted_info 중간에서 끊김 (Unterminated string)

- 로그 예: `"Unterminated string starting at: line 7 column 15"`, 끝부분 `"text\": \"기상청"` (닫는 `"` 없음).
- LLM이 `extracted_info` 배열의 첫 항목을 쓰다가 **문자열 값 중간에서** 생성이 끊겨, JSON이 불완전해짐.

**조치:**  
- 파싱 실패 시 **"unterminated string"** 이면: (1) 따옴표 개수가 홀수이면 닫는 `"` 추가, (2) 열린 `[` `{` 개수만큼 `]` `}` 추가 후 `json.loads` 재시도.  
- 복구에 성공하면 `is_useful`, `confidence`, `reason`, `extracted_info`(일부만 있어도) 그대로 사용.

---

## 원인 4: 출력 형식 지시만으로는 “완전한 JSON” 보장이 어려움

- 프롬프트에서 “유효한 JSON만 출력하세요”라고 해도, **모델이 중간에 멈추면** 불완전한 문자열이 나올 수 있다.
- 마크다운 코드블록(```json ... ```)을 쓰면 앞부분이 코드블록으로 인식되어, **끝의 ``` 가 없으면** 일부만 추출되거나 잘릴 수 있다.

**현재 완화 조치:**  
- 이미 구현된 **JSON 복구 로직**: `"confidence":` 등 불완전한 필드 보정, 괄호/쉼표 정리, 실패 시 기본값 반환.  
- **finish_reason 로깅**으로 “잘림”이 나는 호출을 구분해, 재시도나 프롬프트/한도 조정의 근거로 사용 가능.

---

## 요약

| 원인 | 설명 | 조치 |
|------|------|------|
| 1. config 미전달 | 지식 추출용 LLM에 `judgment_max_output_tokens`가 안 넘어가 500 등 소량만 적용됨 | sip_endpoint에서 gemini 설정에 `judgment_max_output_tokens` 포함해 전달 (수정 완료) |
| 2. API 조기 종료 | Gemini가 MAX_TOKENS(2)/SAFETY(3) 등으로 생성 중단 → 불완전한 문자열 | `finish_reason`을 STOP/MAX_TOKENS 등 문자열로 로깅 (수정 완료) |
| 3. Unterminated string | `extracted_info` 안 `"text": "기상청` 처럼 문자열 값 중간에서 끊김 | 따옴표·괄호 보정 후 재파싱 (수정 완료) |
| 4. 불완전 JSON | 그 외 중간 끊김은 JSON 파싱 불가 | 기존 복구 로직 + 기본값 반환 유지 |

다음 통화부터는 `finish_reason`(MAX_TOKENS이면 한도/프롬프트 검토)과 **Unterminated string 복구**로 일부 잘린 응답도 파싱해 사용할 수 있다.
