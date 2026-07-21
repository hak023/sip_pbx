# 셀프서비스 AI 도우미 — 도움말 문서 & API 레퍼런스 통합 설계

**작성일**: 2026-07-15
**버전**: 1.0
**상태**: 구현 완료
**관련 문서**:
- [self-service-ai-assistant-architecture.md](../architecture/self-service-ai-assistant-architecture.md)
- [self-service-ai-assistant-prd.md](../product/self-service-ai-assistant-prd.md)
- [KNOWLEDGE_MANAGEMENT_DESIGN.md](KNOWLEDGE_MANAGEMENT_DESIGN.md)

---

## 1. 목표

유저(테넌트 관리자)가 프론트엔드(`settings/ai-assistant/docs`)에서:
1. 서비스 이용 매뉴얼 Q&A를 구조화된 형태로 열람할 수 있다.
2. AI 도우미가 대화로 변경 가능한 설정 목록과 필드를 확인할 수 있다.
3. 이 두 정보는 동일한 데이터 소스를 AI 도우미도 참조해 응대한다.

---

## 2. 데이터 모델

### 2-1. 서비스 이용 매뉴얼 → ChromaDB Q&A 항목

`docs/product/self-service-manual-content.md`의 Q&A 쌍이 ChromaDB knowledge 컬렉션에 색인된다.

| 필드             | 값                                                                           |
| ---------------- | ---------------------------------------------------------------------------- |
| `doc_type`       | `"self_service_manual"`                                                      |
| `category`       | `"question"`                                                                 |
| `source`         | `"seed"`                                                                     |
| `owner`          | 테넌트 owner (색인 요청 시 지정)                                             |
| `section_title`  | 소속 섹션 제목 (예: `"AI 에스컬레이션 설정 (AI가 모를 때 어떻게 처리할지)"`) |
| `related_domain` | settings_catalog 도메인명 (예: `"ai-escalation"`)                            |
| text             | `"Q: 질문\nA: 답변"` 포맷 (RAG 검색 대상)                                    |

### 2-2. settings_catalog 도메인

| 도메인          | writable        | writable_fields                                                      |
| --------------- | --------------- | -------------------------------------------------------------------- |
| `persona`       | ✅               | name, description, scope_keywords, enabled                           |
| `ai-escalation` | ✅               | escalation_mode, transfer_extension                                  |
| `call-control`  | ❌ (조회 전용)   | —                                                                    |
| `chat-relay`    | ✅               | message_ai_policy, message_ai_reply_enabled, message_ai_reply_prefix |
| `contacts`      | ❌ (조회 전용)   | —                                                                    |
| `general`       | ❌ (정적 데이터) | —                                                                    |
| `integrations`  | ❌ (OAuth 필요)  | —                                                                    |

### 2-3. 매뉴얼 섹션 → 도메인 매핑

매뉴얼의 `## N. 섹션 제목`에서 키워드 매칭으로 `related_domain`을 결정한다.

| 섹션 키워드      | related_domain  |
| ---------------- | --------------- |
| 에스컬레이션     | ai-escalation   |
| 착신 제어        | call-control    |
| 채팅, SIP 문자   | chat-relay      |
| 예약             | booking         |
| 페르소나         | persona         |
| Calendar, 캘린더 | integrations    |
| 초기 설정        | onboarding      |
| 셀프서비스       | self-service    |
| 서비스 소개      | intro           |
| 통화 이력        | call-history    |
| 운영자           | operator-status |

---

## 3. API 설계

### 3-1. `GET /api/settings/ai-assistant/docs?owner=<owner>`

**동작:**
1. ChromaDB에서 `doc_type=self_service_manual`, `owner=<owner>` 항목 조회
2. 없으면 `index_self_service_manual()` 자동 실행 후 재조회
3. Q&A 항목 + section_title + related_domain 반환

**응답:**
```json
{
  "owner": "1004",
  "total": 52,
  "indexed": true,
  "items": [
    {
      "id": "kb_...",
      "question": "AI 에스컬레이션 모드를 변경하려면?",
      "answer": "...",
      "section_title": "AI 에스컬레이션 설정 ...",
      "related_domain": "ai-escalation",
      "created_at": "2026-07-15T..."
    }
  ]
}
```

### 3-2. `POST /api/settings/ai-assistant/docs/index?owner=<owner>&force=false`

매뉴얼 Q&A를 (재)색인한다. 서버 관리용.

### 3-3. `GET /api/settings/ai-assistant/catalog`

settings_catalog 전체 도메인 목록을 반환한다.

**응답:**
```json
{
  "domains": [
    {
      "domain": "ai-escalation",
      "writable": true,
      "writable_fields": ["escalation_mode", "transfer_extension"],
      "destructive": true,
      "optional_fields": ["transfer_extension", "persona_exists"],
      "related_manual_domains": ["ai-escalation"]
    }
  ]
}
```

---

## 4. 프론트엔드 (`settings/ai-assistant/docs`)

탭 2개:
1. **이용 매뉴얼 Q&A** — 섹션별 사이드바 + Q&A 카드 (관련 도메인 배지 표시)
2. **AI 변경 가능 설정** — settings_catalog 도메인 목록 (writable 여부, 필드 목록)

---

## 5. AI 도우미와의 연계 흐름

```
유저 발화: "채팅 자동응답 꺼줘"
   │
   ▼
[classify_intent] → self_service
   │
   ▼
[self_service_agent_node]
   ├── RAG 검색 (doc_type=self_service_manual)
   │     → "채팅 자동응답" 관련 Q&A 검색
   │     → related_domain="chat-relay" 메타데이터 참조
   │
   ├── Tool: update_self_service_setting
   │     domain="chat-relay", field="message_ai_reply_enabled", value=false
   │
   └── 응답: "채팅 자동응답을 꺼드렸습니다."
```

**핵심**: 매뉴얼 Q&A에 `related_domain` 메타데이터가 있으므로,
RAG 결과를 통해 AI가 어떤 settings_catalog 도메인으로 설정을 변경해야 하는지 파악한다.

---

## 6. 색인 생명주기

| 이벤트                                                 | 동작                                    |
| ------------------------------------------------------ | --------------------------------------- |
| 프론트엔드 `GET /docs?owner=...` 최초 호출 (항목 없음) | 자동 색인 실행                          |
| 셀프서비스 AI 세션 최초 발화 (`onboarding.py`)         | `index_self_service_manual` 호출 (멱등) |
| 관리자가 수동 재색인 필요 시                           | `POST /docs/index?owner=...&force=true` |

---

## 7. 구현 파일 목록

| 파일                                               | 변경 내용                                                                                                                                |
| -------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `src/ai_voicebot/self_service/manual_indexer.py`   | `parse_manual_qa_with_meta()`, `load_manual_qa_with_meta()` 추가; `index_self_service_manual()`에 section_title/related_domain 메타 저장 |
| `src/api/routers/settings_ai_assistant.py`         | raw file serving → ChromaDB Q&A API + catalog API                                                                                        |
| `frontend/app/settings/ai-assistant/docs/page.tsx` | raw markdown viewer → Q&A 구조화 뷰어 (탭: 매뉴얼/카탈로그)                                                                              |

*최종 업데이트: 2026-07-15*
