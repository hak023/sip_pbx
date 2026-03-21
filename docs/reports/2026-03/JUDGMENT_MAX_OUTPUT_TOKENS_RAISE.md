# 지식 정제(judge_usefulness) 출력 토큰 상향

## 배경

- 로그: `max_output_tokens`(대화)는 4096이나, 지식 정제는 **`judgment_max_output_tokens` 별도 키**로 2048이 적용됨 → `finish_reason: MAX_TOKENS` 시 JSON 중간 잘림·파싱 실패.
- Gemini 2.5 계열은 **thinking 토큰**과 모델이 붙이는 **코드펜스(````json`)** 가 출력 한도를 함께 소비해, 짧은 응답처럼 보여도 한도 도달할 수 있음.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `config/config.yaml` | 수정 | `judgment_max_output_tokens` 2048 → 8192, 주석 보강 | 대화 길이는 `judgment_max_input_chars`로 제한됨 |
| `src/ai_voicebot/ai_pipeline/llm_client.py` | 수정 | 프롬프트에 «코드블록 없이 JSON만» 지시 추가 | 토큰 낭비·잘림 완화 |

## 운영 메모

- **긴 통화**: 입력은 `judgment_max_input_chars`(기본 6000)가 담당. 출력 상향은 주로 **JSON 완성도·thinking 소비** 대응.
- 비용·지연이 걱정되면 4096으로만 올려도 되나, 동일 증상 재발 시 8192 유지 권장.
