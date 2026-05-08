# docs/reports — 리포트·보고서

구현 완료 리포트, 분석 보고서, 점검 결과 등 **일회성/기록용 문서**를 둡니다.

**최종 정리**: 2026-05-08 — 월별 규모·주제별 대표 문서 큐레이션 추가(주요 문서 현행화 시 참고).

## 폴더 구조 (월별)

- 문서는 **생성된 날짜 기준**으로 **월별 폴더**에 둡니다.
- 폴더명 형식: `YYYY-MM` (예: `2026-01`, `2026-03`).

```
docs/reports/
├── README.md          ← 이 파일
├── 2025-10/
├── 2026-01/
├── 2026-02/
├── 2026-03/
└── 2026-04/
```

### 월별 문서 수 (참고)

| 폴더 | 대략 파일 수 | 한 줄 요약 |
|------|----------------|-------------|
| `2025-10/` | 1 | 초기 B2BUA 상태 등 |
| `2026-01/` | 44 | Phase3·VectorDB·통화이력·프론트 점검·설치 성공 등 |
| `2026-02/` | 16 | AI 응답 시간·앱 로그 분석 등 |
| `2026-03/` | 218+ | RTP/TTS 품질·HITL·대시보드·다수 통화 분석 리포트 |
| `2026-04/` | 200+ | 동월 고빈도 이슈·구현 기록(파일명 패턴 다양) |

전량 목록은 각 폴더에서 확인한다. **canonical 스펙·아키텍처**는 [`docs/INDEX.md`](../INDEX.md) 및 [`docs/architecture/`](../architecture/)을 우선한다.

## 주제별 대표 리포트 (큐레이션)

주요 문서(PRD·아키텍처) 현행화 시 “무엇이 구현·수정되었는지” 추적용이다. 같은 주제에 리포트가 많으면 **대표 1~3개만** 연결했다.

| 주제 | 대표 문서 (예시 경로) |
|------|------------------------|
| **SIP·코어·미디어 모드** | [`2025-10/B2BUA_STATUS.md`](2025-10/B2BUA_STATUS.md), [`2026-01/DIRECT_MEDIA_MODE_IMPLEMENTATION.md`](2026-01/DIRECT_MEDIA_MODE_IMPLEMENTATION.md), [`2026-01/SIP_TIMERS_IMPLEMENTATION_COMPLETE.md`](2026-01/SIP_TIMERS_IMPLEMENTATION_COMPLETE.md) |
| **AI 파이프라인·Phase** | [`2026-01/AI-DEVELOPMENT.md`](2026-01/AI-DEVELOPMENT.md), [`2026-01/PHASE3_COMPLETE.md`](2026-01/PHASE3_COMPLETE.md), [`2026-01/IMPLEMENTATION_STATUS.md`](2026-01/IMPLEMENTATION_STATUS.md) |
| **VectorDB·지식** | [`2026-01/VECTORDB_INTEGRATION_COMPLETE.md`](2026-01/VECTORDB_INTEGRATION_COMPLETE.md), [`2026-01/KNOWLEDGE_BASE_UI_COMPLETED.md`](2026-01/KNOWLEDGE_BASE_UI_COMPLETED.md), [`2026-01/KNOWLEDGE_EXTRACTION_ANALYSIS.md`](2026-01/KNOWLEDGE_EXTRACTION_ANALYSIS.md) |
| **통화이력·CDR** | [`2026-01/CALL_HISTORY_FIX_COMPLETE.md`](2026-01/CALL_HISTORY_FIX_COMPLETE.md), [`2026-01/CDR_FIELD_NAME_FIX.md`](2026-01/CDR_FIELD_NAME_FIX.md) |
| **프론트·점검** | [`2026-01/FRONTEND_IMPLEMENTATION_CHECK.md`](2026-01/FRONTEND_IMPLEMENTATION_CHECK.md) |
| **RTP·TTS·음질 (2026-03 다수)** | 예: [`2026-03/2026-03-29_1625_RTP_IMPROVEMENT_CONFIRMED_HmbeAyaBMZ.md`](2026-03/2026-03-29_1625_RTP_IMPROVEMENT_CONFIRMED_HmbeAyaBMZ.md), [`2026-03/2026-03-29_1640_RTP_ADAPTIVE_INTERVAL_IMPLEMENTATION.md`](2026-03/2026-03-29_1640_RTP_ADAPTIVE_INTERVAL_IMPLEMENTATION.md) — 동 폴더 내 `RTP_`, `TTS_` 접두 파일 검색 권장 |
| **HITL·대시보드 (2026-03)** | [`2026-03/2026-03-28_1805_HITL_KB_PIPELINE_AUDIT.md`](2026-03/2026-03-28_1805_HITL_KB_PIPELINE_AUDIT.md), [`2026-03/HITL_IMPLEMENTATION_COMPLETE.md`](2026-03/HITL_IMPLEMENTATION_COMPLETE.md), [`2026-03/2026-03-28_2010_DASHBOARD_LIVEFEED_GREETING_HITL_INVITE.md`](2026-03/2026-03-28_2010_DASHBOARD_LIVEFEED_GREETING_HITL_INVITE.md) |
| **성능·로그 분석 (2026-02)** | 폴더 내 `AI_RESPONSE`, `APP_LOG`, `LAST_CALL` 등 파일명 참고 |

`2026-04/`는 파일 수가 많으므로, 필요 시 **주제 키워드로 폴더 검색** 후 동일 표에 행을 추가하는 방식으로 확장한다.

## 새 리포트 작성 시

- **경로**: `docs/reports/YYYY-MM/제목.md`
- **YYYY-MM**: 문서를 **생성하는 당월** (예: 2026년 5월이면 `2026-05`).
- 기존 문서를 옮길 때는 원래 생성일 기준 월 폴더를 사용합니다.

## 참고

- 설계·가이드 등 **지속 참조 문서**는 `docs/design/`, `docs/guides/` 등에 두고, 여기에는 넣지 않습니다.
- **상용 배포·연동** 관점의 목표 아키텍처는 [`docs/architecture/production-deployment-architecture.md`](../architecture/production-deployment-architecture.md)를 본다(리포트와 역할이 다를 수 있음).
