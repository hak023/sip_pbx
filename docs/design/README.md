# 🏗️ Design - 상세 설계 문서

개발자를 위한 구현 수준의 상세 설계 문서 모음

---

## 📋 AI 구현 가이드

### [ai-implementation-guide.md](ai-implementation-guide.md)
AI 컴포넌트 구현 가이드 Part 1
- **8개 핵심 컴포넌트** 상세 설계
- Audio Buffer & Jitter
- VAD Detector
- STT/TTS/LLM Client
- RAG Engine
- Recording & Knowledge Extraction

**내용**:
- 컴포넌트 아키텍처
- 클래스 설계 및 메서드 정의
- 코드 예시 (Python)
- 테스트 케이스
- 에러 처리 전략

### [ai-implementation-guide-part2.md](ai-implementation-guide-part2.md)
AI 컴포넌트 구현 가이드 Part 2
- **7개 추가 컴포넌트** 상세 설계
- Vector DB (ChromaDB)
- Text Embedder
- Orchestrator (전체 통합)
- 데이터 모델 (Conversation, Knowledge, Recording)

**내용**:
- 고급 컴포넌트 설계
- 통합 시나리오
- 성능 최적화 팁
- 확장 가능성 고려사항

---

## 🆕 운영자 부재중 모드

### [OPERATOR-AWAY-MODE-DESIGN.md](OPERATOR-AWAY-MODE-DESIGN.md)
운영자 부재중 모드 상세 설계
- **워크플로우**: 부재중 시 HITL 처리 흐름
- **API 설계**: 운영자 상태 관리 엔드포인트
- **DB 스키마**: `unresolved_hitl_requests` 테이블
- **Frontend UI**: 상태 토글 및 이력 관리

**내용**:
- 상태 다이어그램 (Available/Away/Busy/Offline)
- RESTful API 명세
- WebSocket 이벤트 정의
- PostgreSQL 테이블 설계
- UI 컴포넌트 설계

---

## 📁 파일 목록

| 파일 | 라인 수 | 설명 |
|------|---------|------|
| `ai-implementation-guide.md` | ~1,500 | AI 구현 가이드 Part 1 (8개 컴포넌트) |
| `ai-implementation-guide-part2.md` | ~1,200 | AI 구현 가이드 Part 2 (7개 컴포넌트) |
| `OPERATOR-AWAY-MODE-DESIGN.md` | ~800 | 운영자 부재중 모드 설계 |

**총 라인 수**: ~3,500 lines

---

## 🎯 사용 대상

- **Backend 개발자**: Python/FastAPI 구현 시 참고
- **Frontend 개발자**: React/Next.js 컴포넌트 설계 참고
- **시스템 아키텍트**: 전체 시스템 통합 이해
- **QA 엔지니어**: 테스트 케이스 작성 참고

---

## 🔗 관련 문서

- **아키텍처**: [../ai-voicebot-architecture.md](../ai-voicebot-architecture.md)
- **구현 상태**: [../reports/IMPLEMENTATION_STATUS.md](../reports/IMPLEMENTATION_STATUS.md)
- **Frontend 설계**: [../frontend-architecture.md](../frontend-architecture.md)

---

**상위 문서 인덱스**: [../INDEX.md](../INDEX.md)  
**최종 업데이트**: 2026-01-06

