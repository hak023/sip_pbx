# Gemini 2.5 Flash-Lite · Native Audio(실시간)를 활용한 응답 속도 개선 방안

| 항목 | 내용 |
|------|------|
| 작성일 | 2026-03-26 |
| 상태 | 설계·검토용 (코드 미변경) |
| 전제 | 현재 SIP PBX AI 경로: **Google STT → 텍스트 LangGraph(Gemini `generate_content`) → Google TTS**, 런타임 로그 기준 LLM **`gemini-2.5-flash`** |
| 참고 문서 | [Gemini 2.5 Flash-Lite](https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash-lite?hl=ko), [Gemini 2.5 Flash 실시간(Native Audio) 미리보기](https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash-native-audio-preview-12-2025?hl=ko) |

---

## 1. 요약

| 모델 | 현재 아키텍처에 맞는 활용 | 속도 개선 성격 |
|------|---------------------------|----------------|
| **`gemini-2.5-flash-lite`** | **점진적** — 기존 `LLMClient`(`GenerativeModel` + `generate_content`) 경로에 **모델 문자열만 바꾸거나**, **경량 호출에만 별도 클라이언트**로 분리 | **낮은 공수**, 턴마다 반복되는 **짧은 LLM 호출**(의도 분류·질의 재작성·Step-back 등)의 **RTT·비용** 절감 기대 |
| **`gemini-2.5-flash-native-audio-preview-12-2025`** | **전면 개편** — [Live API](https://ai.google.dev/gemini-api/docs/live?hl=ko) 기반 **오디오 스트림 입·출력**; Pipecat `STT → RAG/LLM → TTS` 체인과 **동일 레이어가 아님** | **첫 토큰·발화 체감**은 크게 개선될 수 있으나 **RAG·HITL·로깅 정합** 재설계 필요, **미리보기** 리스크 |

---

## 2. 모델별 특성 (공식 문서 기준)

### 2.1 `gemini-2.5-flash-lite`

출처: [Gemini 2.5 Flash-Lite](https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash-lite?hl=ko)

- **포지션**: 비용 효율·**고빈도 경량 작업**·**매우 짧은 지연**에 적합하다고 명시.
- **입·출력**: 텍스트(및 이미지·동영상·오디오·PDF 입력), **출력은 텍스트**.
- **기능**: **구조화된 출력**, **함수 호출**, 파일 검색, 캐싱, Batch API 등 **일반 Gemini 텍스트 파이프라인과 호환되는 항목이 다수**.
- **비호환**: **Live API 지원 안 함**, **오디오 생성 안 함** → **현 TTS는 그대로** 두고 LLM 구간만 바꾸는 전략과 맞음.

### 2.2 `gemini-2.5-flash-native-audio-preview-12-2025`

출처: [Gemini 2.5 Flash 실시간 미리보기](https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash-native-audio-preview-12-2025?hl=ko)

- **포지션**: **Live API**로 **지연 시간이 짧은 실시간 음성·동영상** 상호작용; 연속 오디오/텍스트 스트림 처리.
- **입·출력**: 입력 오디오·동영상·텍스트 / **출력 오디오 및 텍스트**.
- **제약(문서 표 기준)**: **Batch API 미지원**, **캐싱 미지원**, **구조화된 출력 미지원**, 파일 검색·코드 실행 등 다수 미지원 — **현재 LangGraph의 JSON/의도 라벨·RAG 문서 주입 패턴과 그대로 대응하기 어려움**.
- **상태**: **미리보기** 모델 — SLA·장기 ID 안정성 검토 필요.

---

## 3. Flash-Lite로 속도 개선하는 구체 방안 (권장: 단계적)

### 3.1 왜 효과가 있을 수 있는가

기존 지연 분석(`CALL_LATENCY_ANALYSIS_AGOV7YRA.md`)에서 **한 턴에 LLM이 여러 번** 호출된다. Flash-Lite는 문서상 **경량·저지연**에 최적화되어 있어, **출력이 짧은 호출**에서 `gemini-2.5-flash` 대비 **왕복 시간 단축**을 기대할 수 있다(실측 필수).

### 3.2 적용 후보 호출 (우선순위)

| 호출 지점 | 출력 특성 | Flash-Lite 적합도 |
|-----------|-----------|-------------------|
| `classify_intent` (LLM 폴백) | 짧은 라벨 | **높음** |
| `rewrite_query` | 짧~중간 문장 | **높음** |
| `step_back` | 한 문장 수준 | **높음** |
| `generate_response` | 긴 상담 문장·RAG 근거 | **중간** — 품질·안전 검증 후 선택 |

### 3.3 구현 패턴 (코드 방향만)

1. **설정 분리**  
   - 예: `gemini.model_fast: gemini-2.5-flash-lite`, `gemini.model_quality: gemini-2.5-flash`  
   - `LLMClient`를 한 개만 두고 `generate_content` 호출 시 `model` 인자 오버라이드, 또는 **경량용 `LLMClient` 인스턴스 2개** (분류/rewrite용 vs 최종 응답용).

2. **토큰 상한**  
   - Flash-Lite 전환과 병행해 분류·rewrite·step_back의 **`max_output_tokens`**를 유지·축소해 **생성 구간** 자체를 짧게 유지.

3. **검증**  
   - 한국어 **의도 분류 정확도**, **기상청 도메인 용어**에서의 rewrite 품질, **오분류 증가 시** `question`/`transfer` 라우팅 오류를 모니터링.

### 3.4 리스크

- **품질 저하**: Lite는 Flash 대비 복잡 추론·긴 답에서 불리할 수 있음 → **최종 답변만 Flash 유지**가 보수적이다.
- **단일 모델 전역 교체**: 설정만 `gemini-2.5-flash-lite`로 바꾸는 것은 공수는 최소이나, **품질·지연 트레이드오프를 한 번에 받음**.

---

## 4. Native Audio(실시간) 모델로 속도 개선하는 방안 (장기·아키텍처)

### 4.1 무엇이 바뀌는가

- **목표 체감**: STT 완료 대기 → 텍스트 LLM → TTS 큐의 **단계적 파이프** 대신, **오디오-오디오**에 가까운 **저지연 대화** ([Live API 가이드](https://ai.google.dev/gemini-api/docs/live?hl=ko) 및 [해당 모델 문서](https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash-native-audio-preview-12-2025?hl=ko)).
- **필수 작업**: `google.generativeai`의 **일반 REST/생성 API**가 아니라 **Live API(WebSocket 등)** 스택 도입, Pipecat/전송 계층과의 **통합 설계**.

### 4.2 현 시스템과의 정합 이슈

| 기능 | 현재 (텍스트 그래프) | Native Audio + Live |
|------|----------------------|------------------------|
| RAG (Chroma + 문서 컨텍스트) | 텍스트로 주입 가능 | **도구/텍스트 병행 설계** 필요; 실시간 오디오만으로는 지식 주입 방식 재정의 |
| LangGraph 노드·CDR 타이밍 | 노드별 로그 명확 | 세션 기반으로 **이벤트 모델** 재정의 |
| HITL | 텍스트 트리거 | 음성 세션 중 **중단·에스컬레이션** UX 재설계 |
| 구조화된 출력 | 의도·슬롯에 유리 | 문서상 **구조화된 출력 미지원** — **별도 경량 텍스트 분류기** 또는 **하이브리드**(Live는 대화, 옆채널은 짧은 텍스트 API) 검토 |

### 4.3 권장 접근

1. **Phase A**: Flash-Lite로 **텍스트 파이프라인** 최적화(§3).  
2. **Phase B**: 별도 PoC로 Live API + Native Audio **단일 시나리오**(인사만, RAG 없음) 측정.  
3. **Phase C**: RAG를 **함수 호출/텍스트 턴**으로 붙일 수 있는지 API 제약을 확인한 뒤, 통합 범위 결정.

**미리보기 모델**이므로 **프로덕션 전면 전환은 비권장**; PoC·A/B에 한정하는 것이 안전하다.

---

## 5. 결론

- **빠른 효과·낮은 리스크**: **`gemini-2.5-flash-lite`**를 [공식 스펙](https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash-lite?hl=ko)에 맞게 **짧은 텍스트 LLM 호출**에 우선 적용하고, **최종 응답 생성**은 `gemini-2.5-flash`(또는 품질 검증된 모델) 유지하는 **이중 모델**이 현실적이다.
- **체감 지연의 패러다임 전환**: **`gemini-2.5-flash-native-audio-preview-12-2025`**는 [실시간 문서](https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash-native-audio-preview-12-2025?hl=ko)대로 **Live API 전용**에 가깝고, **단순 모델명 변경으로는 적용 불가**하며 **RAG·구조화 출력·미리보기 리스크**를 감수한 **아키텍처 프로젝트**로 계획해야 한다.

---

*월별 리포트 규칙에 따라 `sip-pbx/docs/reports/2026-03/` 에 보관한다.*
