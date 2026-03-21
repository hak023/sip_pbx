# LLM 응답 잘림 원인 점검 (length / max_output_tokens)

**목적**: "LLM이 짧게 잘려서 말한다"는 현상이 **출력 길이 제한(max_output_tokens)** 때문인지 확인하고, 설정·로깅을 정리한다.

---

## 1. 설정 위치

| 위치 | 용도 | 기본/현재 값 |
|------|------|--------------|
| **config/config.yaml** | 대화 생성(통화 답변) | `google_cloud.gemini.max_output_tokens: 500` |
| **LLMClient.__init__** | 위 설정 미지정 시 | `config.get("max_output_tokens") or config.get("max_tokens", 200)` → **200** |
| judgment_usefulness | 지식 정제 JSON | `judgment_max_output_tokens: 2048` (별도) |

- **대화 응답**에 쓰이는 값은 **config.yaml의 500** (factory에서 `gemini_config`로 LLMClient에 전달).
- 500 토큰 ≈ 한글 기준 대략 250~350자 수준. 2~3문장 + URL이면 **경계선**이라, 문장이 조금만 길어져도 **MAX_TOKENS에서 잘릴 수 있음**.

---

## 2. 코드 경로

- **대화 1회 생성**: `LLMClient.generate_response()` → `self.model.generate_content(prompt, generation_config=self.generation_config)`.
- `self.generation_config`는 `__init__`에서 `max_output_tokens=max_tokens`(config 기준 500)로 생성됨.
- **캐시 히트 시**: LangGraph semantic cache에서 이전 답변을 그대로 반환하므로, **그때는 LLM 길이 제한과 무관**. 짧게 나오면 “캐시된 짧은 문장”일 수 있음.

---

## 3. 확인 방법 (재테스트 시)

다음 로그가 추가되어 있음.

- **`llm_generate_response_finish_reason`**  
  - `finish_reason`: STOP(정상), **MAX_TOKENS**(길이 제한으로 잘림), SAFETY, RECITATION 등.  
  - `response_len`, `max_output_tokens` 함께 기록.
- **`llm_response_truncated_max_tokens`** (warning)  
  - `finish_reason == MAX_TOKENS`일 때만 출력.  
  - 응답이 **max_output_tokens에서 잘렸다**는 의미.

통화 후 `logs/app.log`에서 위 이벤트를 검색하면, **length가 모자라서 잘린 경우**인지 바로 확인할 수 있다.

---

## 4. 권장 조치

1. **max_output_tokens 상향**  
   - 대화 생성용으로 **500 → 1024**(또는 2048) 권장.  
   - URL·2~3문장 안내가 끝까지 나오도록 하기 위함.  
   - 수정 위치: `config/config.yaml` → `google_cloud.gemini.max_output_tokens`.
2. **재테스트**  
   - 동일 시나리오(예: "서울 지역 날씨 알려줘")로 통화 후,  
     - `llm_generate_response_finish_reason` / `llm_response_truncated_max_tokens` 유무 확인,  
     - 응답이 문장 끝까지 나오는지 청취 확인.
3. **캐시 영향**  
   - 짧은 응답이 **semantic_cache_hit**으로 나온다면, “길이 부족”이 아니라 **캐시된 짧은 답변**이 재사용된 것.  
   - 이때는 캐시 키/스코어 또는 캐시 응답 길이 정책을 별도 검토.

---

## 5. 요약

| 질문 | 답변 |
|------|------|
| length가 모자라서 잘리는가? | **가능성 있음.** 현재 대화 생성 `max_output_tokens`는 500이며, 2~3문장+URL이면 경계선. |
| 어떻게 확인하나? | 재통화 후 `llm_generate_response_finish_reason`에서 `MAX_TOKENS` 여부 확인. |
| 권장 설정 | 대화용 `max_output_tokens`를 **1024 이상**으로 상향. |

이 문서는 [LAST_CALL_REVIEW_4udhVMNr2o.md](./LAST_CALL_REVIEW_4udhVMNr2o.md) §2.3(LLM 응답 절단)과 함께 참고하면 된다.
