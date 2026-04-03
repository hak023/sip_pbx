# STT 모델 결정: latest_long vs telephony_enhanced 비교 및 변경 결과

| 항목 | 내용 |
|------|------|
| 작성일 | 2026-04-03 09:45 |
| 상태 | 완료 — `config.yaml` 적용됨 |
| 관련 파일 | `config/config.yaml` L126, `src/ai_voicebot/factory.py` L43 |
| 이전 보고서 | `2026-04-02_1945_STT_TRANSCRIPT_SPACING_ANALYSIS.md` |

---

## 1. 변경 전 상태 확인

`config/config.yaml` 126번째 줄:
```yaml
model: "telephony"  # telephony | latest_long
```
**`latest_long`으로 변경된 적 없음** — 이전 리포트에서 권장한 변경이 미적용 상태였음.

`factory.py` 43번째 줄:
```python
model=_cfg.get("model", "telephony"),
```
`config.yaml`의 값을 그대로 읽어 사용 → **telephony 모델로 동작 중이었음**.

---

## 2. telephony_enhanced 사용 가능 여부 검토

### 결론: Pipecat 환경에서는 telephony_enhanced 사용 불가

| 항목 | 내용 |
|------|------|
| telephony_enhanced 정식 명칭 | `model="phone_call"` + `use_enhanced=True` (V1 API) |
| Pipecat GoogleSTTService API | **Speech-to-Text V2** (`cloud_speech.StreamingRecognitionConfig`) |
| V2 지원 모델 | `telephony`, `chirp_2`, `chirp_3` 만 지원 |
| `phone_call` (enhanced) | **V1 전용** — V2에서는 존재하지 않음 |
| Pipecat InputParams | `use_enhanced` 파라미터 **없음** |

Pipecat의 `GoogleSTTService._connect()`는 `cloud_speech.RecognitionConfig`(V2)를 사용하므로 `telephony_enhanced`(`phone_call`) 모델은 **적용 자체가 불가능**.

---

## 3. V2 모델 비교 (Pipecat에서 실제 선택 가능한 모델)

| 모델 | 기반 기술 | 스트리밍 | 한국어 | 레이턴시 | 비고 |
|------|----------|---------|--------|---------|------|
| `telephony` | 구형 DNN-HMM 계열, 8kHz 전화 특화 | ✅ | 형태소 분리 과다 | 낮음 | **현재 사용 중 → 문제 모델** |
| `latest_long` | **Conformer** (Google 최신 연구 기반) | ✅ | 형태소 통합 우수 | 낮음 | **Pipecat InputParams 기본값** |
| `chirp_2` | USM (Large Speech Model) | ✅ | 매우 우수 | 중간 | `us-central1` 위치 필요 |
| `chirp_3` | Chirp 3 gen, 다언어 ASR | ✅ | 최우수 | **높음(noticeable)** | `location="us"` 필요, 전화 통화에 오버스펙 |

### latest_long 선택 근거

1. **Pipecat 공식 기본값**: `GoogleSTTService.InputParams.model` 기본값이 `"latest_long"`. Google·Pipecat 양측 모두 전화 통화 포함 범용에 권장.
2. **한국어 형태소 통합 우수**: Conformer 기반으로 음소 분리 없이 자연스러운 어절 단위 출력.
3. **레이턴시 동일 수준**: telephony 대비 레이턴시 증가 없음 (chirp_3는 눈에 띄게 높음으로 확인됨).
4. **가격 동일**: `latest_long`은 Standard 요금 적용 — telephony와 동일.
5. **telephony_enhanced 대안 불가**: V2 API 환경에서 phone_call 모델 자체가 지원되지 않음.

---

## 4. 적용 내용

### config/config.yaml (L126)

변경 전:
```yaml
model: "telephony"  # telephony | latest_long
```

변경 후:
```yaml
model: "latest_long"  # telephony(한국어 형태소 분리 과다 공백) | latest_long(Conformer 기반, 한국어 형태소 통합 우수, Pipecat STT V2 기본값)
```

### factory.py (변경 없음)

```python
model=_cfg.get("model", "telephony"),   # config.yaml에서 "latest_long" 읽음
```
`config.yaml` 값을 읽으므로 `factory.py`는 수정 불필요. 서버 재시작 시 자동 반영.

---

## 5. 예상 효과

| 항목 | telephony (변경 전) | latest_long (변경 후) |
|------|-------------------|----------------------|
| 한국어 형태소 | `"딴 거 고 치 면서"` | `"딴거 고치면서"` 또는 `"딴 거 고치면서"` |
| 음소 분리 | 잦음 | 최소화 |
| transcript 가독성 | 낮음 | 높음 |
| call_summary 품질 | 저하 | 개선 |
| LLM 이해도 | 유지 (LLM이 보정) | 향상 |
| 레이턴시 | 기준 | 동등 |
| 비용 | Standard | Standard (동일) |

---

## 6. 서버 재시작 필요

`config.yaml`은 서버 시작 시 로드되므로 **서버 재시작** 후 적용됩니다.

적용 확인 방법 (로그):
```
google_stt_service_per_pipeline_created  model=latest_long
```

---

## 7. 추가 고려 사항

- 효과가 미흡할 경우: `pipeline_transcript_buffer.py`의 `record_pipeline_caller()`에 한글 자모 연속 공백 제거 정제 함수 보완 적용 가능 (이전 리포트 방안 B 참조).
- 장기적으로: `chirp_3` (위치 `"us"`, GA 완료)는 정확도 최우수이나 레이턴시 증가 확인 필요. 전화 통화 실시간 응답에는 레이턴시가 중요하므로 `latest_long`을 우선 사용하고 추후 A/B 테스트 권장.
