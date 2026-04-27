# 인텐트 분류 chitchat 오분류 수정 및 대시보드 통화이력 UX 개선

작성일: 2026-04-10 21:30  
상태: 구현 완료

---

## 개요

1. **대시보드 통화이력 펼치기/접기 UX**: `call-history` 페이지와 동일한 아코디언+전체행 클릭 방식을 `dashboard/page.tsx`에도 적용.
2. **예약 인텐트 오분류**: "예약하려고 합니다."가 페르소나 유사도 낮음(0.11)으로 `chitchat`에 직행하던 문제 수정. 페르소나 `is_relevant=false`라도 booking 동작 패턴이 있으면 LLM 3차 분류로 위임.
3. **인사/감사 발화 오분류**: "감사합니다." 등 사회적 발화가 페르소나 유사도 낮음(0.09)으로 `chitchat`에 직행하던 문제 수정. `_SOCIAL_PHRASE_PATTERNS` 추가로 LLM 3차로 위임.

---

## 근본 원인 분석

### 오류 발화: "예약하려고 합니다." (call_id: 1RuDscQG-W)

```
persona_query_relevance_check → similarity: 0.1112, is_relevant: false
→ classify_intent_persona_chitchat 직행
→ chitchat 응답: "죄송합니다, 저는 비스트로 벨라 관련 문의만 도와드릴 수 있어요."
```

예약은 비스트로 벨라의 핵심 기능임에도 페르소나 임베딩 유사도가 낮게 나와 `is_relevant=false` 처리. 기존 코드는 `is_relevant=false`이면 무조건 chitchat 반환하므로, booking 동작 패턴 체크 기회가 없었음.

### 오류 발화: "감사합니다." (call_id: 1RuDscQG-W)

```
persona_query_relevance_check → similarity: 0.0945, is_relevant: false
→ classify_intent_persona_chitchat 직행
→ chitchat 응답: "죄송합니다, 저는 비스트로 벨라 관련 문의만..."
```

감사 인사가 "비스트로 벨라"와 유사도가 낮아 chitchat → 부적절 응답 발생. LLM이 처리했으면 `gratitude`나 `farewell` 의도로 자연스러운 답변 생성 가능.

---

## 변경 이력

| 파일 경로 | 변경 유형 | 요약 |
|---|---|---|
| `src/ai_voicebot/langgraph/nodes/classify_intent.py` | 수정 | `_SOCIAL_PHRASE_PATTERNS` 추가, `is_relevant=false` 분기에 booking/social 패턴 체크 추가 |
| `sip-pbx/frontend/app/dashboard/page.tsx` | 수정 | `toggleHistoryRow` 아코디언 함수 추가, `<tr>` 전체 클릭, `stopPropagation` 적용 |

---

## 주요 결정 사항

### classify_intent.py

**기존 로직 (문제)**:
```
is_relevant=false → chitchat 즉시 반환 (booking/social 패턴 무시)
```

**수정 로직**:
```
is_relevant=false
  → booking 패턴? → LLM 3차로 fall-through
  → social 패턴(감사/안녕/수고 등)? → LLM 3차로 fall-through
  → 그 외 → chitchat 반환 (기존과 동일)
```

`_SOCIAL_PHRASE_PATTERNS`에 포함된 패턴:
- 감사: "감사합니다", "감사해요", "고맙습니다" 등
- 작별: "수고하세요", "안녕히", "전화 끊겠습니다" 등
- 긍정 응답: "네 알겠습니다", "네 감사" 등

### dashboard/page.tsx

- `toggleHistoryRow` 함수: 클릭 시 현재 행이 열려있으면 전체 접기(`{}`), 닫혀있으면 해당 행만 열기 (`{ [id]: true }`) — 하나만 펼치기 보장
- `<tr onClick={toggleHistoryRow}>` — 전체 행 클릭 가능
- `<td onClick={e.stopPropagation()}>` — 상세패널 내부 클릭 시 행 접힘 방지
- "펼치기" 버튼 → `<span>` "▼ 펼치기" / "▲ 접기" 텍스트로 변경

---

## 잔여 과제

- 페르소나 임베딩 유사도 임계값(0.6)이 전반적으로 높아 유사도 낮은 정상 발화(예약, 인사)가 차단됨. 장기적으로 임계값 조정 또는 별도 예약/인사 전용 1차 패턴 매칭 강화를 검토.
- `classify_intent` 5.28초 소요(1RuDscQG-W 1턴) — 첫 턴 페르소나 로딩+임베딩 추론 지연 원인 분석 필요.
