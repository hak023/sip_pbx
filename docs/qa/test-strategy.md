# 🧪 SIP PBX + AI Voice Assistant - 기능 테스트 전략

## 📋 문서 정보

| 항목 | 내용 |
|------|------|
| **문서 버전** | v1.1 |
| **작성일** | 2026-01-08 |
| **작성자** | Quinn (Test Architect) |
| **프로젝트** | SIP PBX B2BUA + AI Voice Assistant |
| **상태** | Active |

---

## 📌 목차

1. [테스트 범위](#1-테스트-범위)
2. [테스트 레벨](#2-테스트-레벨)
3. [테스트 시나리오](#3-테스트-시나리오)
4. [테스트 환경](#4-테스트-환경)

---

## 1. 테스트 범위

### 1.1 시스템 컴포넌트

#### SIP PBX Core
- ✅ SIP 시그널링 (INVITE, BYE, ACK, REGISTER, CANCEL, PRACK, UPDATE, OPTIONS)
- ✅ RTP Relay
- ✅ Call Manager (세션 관리, 상태 전이)
- ✅ Port Pool (동적 할당)
- ✅ SDP 협상 및 조작
- ✅ CDR 생성 및 저장

#### AI Voice Assistant
- 🧪 부재중 자동 응답
- 🧪 실시간 STT/TTS
- 🧪 LLM 대화 생성
- ✅ RAG Engine
- ✅ Knowledge Base
- 🧪 Barge-in (VAD)
- 🧪 Call Recording & Transcription
- ✅ Knowledge Extraction (VectorDB 통합)

#### Backend API Services
- 🧪 FastAPI Gateway
- 🧪 WebSocket Server
- 🧪 HITL Service
- 🧪 Operator Status Management
- 🧪 Call History API
- 🧪 Recording Playback API
- 🧪 AI Insights API

#### Frontend (Next.js)
- 🧪 Dashboard
- 🧪 Live Call Monitor
- 🧪 HITL Dialog
- 🧪 Operator Status Toggle
- 🧪 Call History
- 🧪 Recording Playback
- 🧪 Knowledge Base Management

### 1.2 테스트 제외 항목

- ❌ 외부 SIP 클라이언트 (3rd party softphone)
- ❌ Google Cloud API 내부 로직
- ❌ PostgreSQL/Redis 내부 동작
- ❌ 네트워크 인프라

---

## 2. 테스트 레벨

### 2.1 Unit Test (단위 테스트)

**목표**: 개별 컴포넌트 로직 검증

#### SIP Core

**test_call_manager.py** ✅
- Given: 새로운 INVITE 수신
- When: handle_incoming_invite() 호출
- Then: CallSession 생성, State=PROCEEDING

**test_register_handler.py** ✅
- Given: 유효한 REGISTER 메시지
- When: handle_register() 호출
- Then: 사용자 등록, 200 OK 응답

**test_prack_handler.py** ✅
- Given: 180 Ringing 후 PRACK 수신
- When: handle_prack() 호출
- Then: 200 OK 응답, Transaction 완료

**test_cancel_handler.py** ✅
- Given: INVITE 진행 중 CANCEL 수신
- When: handle_cancel() 호출
- Then: 487 Request Terminated, BYE 전송

#### Media Layer

**test_port_pool.py** ✅
- Given: Port Pool 초기화
- When: allocate_ports(4) 호출
- Then: 4개 포트 할당, 재사용 불가

**test_rtp_packet.py** ✅
- Given: 원시 RTP 바이트 데이터
- When: RTPParser.parse() 호출
- Then: version, ssrc, payload_type 파싱 성공

**test_jitter_buffer.py** ✅
- Given: 순서가 뒤바뀐 RTP 패킷들
- When: JitterBuffer에 추가
- Then: 순서대로 재정렬하여 반환

**test_g711.py** ✅
- Given: G.711 μ-law 인코딩 데이터
- When: decode_ulaw() 호출
- Then: PCM 16-bit 데이터 반환

**test_sdp_parser.py** ✅
- Given: SDP Offer 텍스트
- When: parse_sdp() 호출
- Then: media_port, codecs, connection_ip 추출

#### AI Pipeline

**test_text_embedder.py** 🧪 (신규 필요)
- Given: "안녕하세요" 텍스트
- When: embed() 호출
- Then: 벡터 반환

**test_rag_engine.py** 🧪 (신규 필요)
- Given: Vector DB에 지식 3개 저장
- When: search("예약 취소") 호출
- Then: 유사도 높은 순서로 반환

**test_llm_client.py** 🧪 (신규 필요)
- Given: 사용자 질문 + RAG 컨텍스트
- When: generate_response() 호출
- Then: Gemini API 호출, 응답 생성

**test_vad_detector.py** 🧪 (신규 필요)
- Given: 음성 오디오 프레임
- When: is_speech() 호출
- Then: True (음성 감지)

**test_knowledge_extractor.py** 🧪 (신규 필요)
- Given: 통화 transcript.txt
- When: extract_from_call() 호출
- Then: LLM 유용성 판단, VectorDB 저장

### 2.2 Integration Test (통합 테스트)

**목표**: 컴포넌트 간 연동 검증

**test_call_manager_media_integration.py** ✅
- Given: Call Manager + Media Session Manager
- When: INVITE 처리
- Then: Port 할당, RTP Relay 시작, SDP 조작

**test_rtp_relay.py** ✅
- Given: RTP Relay + 2개 Endpoint
- When: RTP 패킷 수신
- Then: 반대편 Endpoint로 relay

**test_sip_server.py** ✅
- Given: SIP Server 실행
- When: UDP 5060 포트로 INVITE 전송
- Then: 100 Trying 수신

**test_webhook.py** ✅
- Given: Webhook 설정
- When: 통화 종료
- Then: HTTP POST로 CDR 전송

**test_ai_orchestrator_integration.py** 🧪 (신규 필요)
- Given: AI Orchestrator + Google Cloud APIs
- When: 부재중 통화 시작
- Then: STT 스트림 시작, TTS 인사말 재생

**test_hitl_service_integration.py** 🧪 (신규 필요)
- Given: HITL Service + WebSocket Server
- When: AI 신뢰도 낮음
- Then: 운영자에게 WebSocket 알림 전송

**test_recording_playback_flow.py** 🧪 (신규 필요)
- Given: 통화 녹음 완료
- When: Frontend에서 재생 요청
- Then: API로 WAV 스트리밍

**test_post_stt_integration.py** 🧪 (신규 필요)
- Given: 일반 통화 녹음 완료
- When: stop_recording() 호출
- Then: Google STT API 호출, transcript.txt 생성

### 2.3 E2E Test (End-to-End)

**목표**: 전체 시스템 시나리오 검증

**test_e2e_standard_call.py** 🧪 (신규 필요)
- Given: SIP 클라이언트 A, B 등록
- When: A→B 통화 시도
- Then: B 응답, 양방향 RTP 스트림, 종료 시 CDR 생성

**test_e2e_ai_call.py** 🧪 (신규 필요)
- Given: A→B 통화, B 10초 미응답
- When: AI 자동 응답
- Then: 인사말 재생, 사용자 발화 인식, LLM 응답

**test_e2e_hitl_intervention.py** 🧪 (신규 필요)
- Given: AI 통화 중 신뢰도 낮음
- When: HITL 요청
- Then: 운영자 알림, 운영자 답변, 통화 재개

**test_e2e_vectordb_knowledge.py** ✅
- **TC-KB-001**: 통화 내용에서 지식 추출 → VectorDB 저장
  - Given: 통화 transcript 파일 (STT 완료)
  - When: KnowledgeExtractor.extract_from_call() 호출
  - Then: LLM 유용성 판단, 텍스트 청킹, 임베딩 생성, VectorDB 저장
- **TC-KB-002**: VectorDB에서 지식 조회 (RAG 검색)
  - Given: VectorDB에 통화 지식 저장됨
  - When: RAGEngine.search() 호출
  - Then: 관련 문서 반환, 유사도 점수 검증, 메타데이터 확인
- **TC-KB-003**: 소유자 필터링 테스트
  - Given: 서로 다른 소유자의 지식이 VectorDB에 저장됨
  - When: 특정 소유자로 필터링하여 검색
  - Then: 해당 소유자의 지식만 반환
- **TC-KB-004**: 유용하지 않은 내용은 저장하지 않음
  - Given: LLM이 "유용하지 않음" 판단
  - When: KnowledgeExtractor.extract_from_call() 호출
  - Then: VectorDB에 저장되지 않음
- **TC-KB-005**: 지식 추출 통계
  - Given: 여러 통화에서 지식 추출
  - When: get_stats() 호출
  - Then: 올바른 통계 반환

**test_e2e_frontend_monitoring.py** 🧪 (신규 필요)
- Given: Frontend 대시보드 접속
- When: 실시간 통화 발생
- Then: WebSocket으로 통화 상태 업데이트, 트랜스크립트 표시

---

## 3. 테스트 시나리오

### 3.1 SIP PBX Core 시나리오

#### TC-SIP-001: 표준 통화 흐름
```gherkin
Given 사용자 A와 B가 등록됨
When A가 B에게 INVITE 전송
Then PBX가 100 Trying 응답
And PBX가 B에게 INVITE 전달
And B가 180 Ringing 응답
And PBX가 A에게 180 전달
And B가 200 OK 응답
And PBX가 A에게 200 전달
And A가 ACK 전송
And 양방향 RTP 스트림 시작
And A가 BYE 전송
And PBX가 B에게 BYE 전달
And CDR 생성 및 저장
```

#### TC-SIP-002: CANCEL 처리
```gherkin
Given A→B INVITE 진행 중 (180 Ringing)
When A가 CANCEL 전송
Then PBX가 487 Request Terminated 응답
And PBX가 B에게 CANCEL 전달
And B가 487 응답
And 통화 설정 취소됨
```

#### TC-SIP-003: PRACK 신뢰성 응답
```gherkin
Given A→B INVITE 전송
When B가 183 Session Progress (Require: 100rel)
Then PBX가 A에게 183 전달
And A가 PRACK 전송
And PBX가 B에게 PRACK 전달
And B가 200 OK (PRACK) 응답
```

#### TC-SIP-004: UPDATE 세션 변경
```gherkin
Given A↔B 통화 중
When A가 UPDATE 전송 (SDP 포함)
Then PBX가 B에게 UPDATE 전달
And B가 200 OK (SDP 포함) 응답
And 미디어 스트림 재협상
```

### 3.2 AI Voice Assistant 시나리오

#### TC-AI-001: 부재중 자동 응답
```gherkin
Given A→B INVITE 전송
When B가 10초 동안 미응답
Then PBX가 직접 200 OK 응답
And AI Orchestrator가 통화 시작
And TTS 인사말 재생
And STT 스트림 시작
```

#### TC-AI-002: 실시간 대화
```gherkin
Given AI 통화 진행 중
When 사용자가 "예약 확인 부탁드립니다" 발화
Then STT가 텍스트 변환
And RAG Engine이 Vector DB 검색
And LLM이 응답 생성
And TTS가 음성 합성 및 재생
```

#### TC-AI-003: Barge-in
```gherkin
Given AI가 TTS 재생 중
When 사용자가 발화 시작 (VAD 감지)
Then TTS 즉시 중단
And STT 스트림 활성화
```

#### TC-AI-004: HITL 개입
```gherkin
Given AI 대화 중 신뢰도 낮음
When AI가 HITL 요청
Then WebSocket으로 운영자에게 알림
And 운영자가 답변 입력
And 답변이 TTS로 재생
And 지식 베이스 저장 옵션 선택
```

#### TC-AI-005: 운영자 부재중 모드
```gherkin
Given 운영자가 "부재중" 모드 설정
When HITL 요청 발생
Then AI가 대체 응답
And 통화 계속 진행
```

#### TC-AI-006: 통화 녹음
```gherkin
Given AI 통화 진행 중
When 통화 종료
Then 녹음 파일 저장 (caller.wav, ai.wav, mixed.wav)
And transcript.txt 생성
And metadata.json 생성
```

#### TC-AI-007: 지식 추출
```gherkin
Given AI 통화 종료, transcript.txt 존재
When Knowledge Extractor 실행
Then LLM이 유용성 판단
And 텍스트 청킹
And 임베딩 생성
And Vector DB에 저장
```

### 3.3 일반 통화 녹음 및 지식 추출

#### TC-REC-001: 일반 통화 녹음
```gherkin
Given A↔B 표준 SIP 통화
When 통화 진행 중
Then SIPCallRecorder가 RTP 패킷 캡처
And caller_buffer, callee_buffer에 저장
And 통화 종료 시 WAV 파일 생성
```

#### TC-REC-002: 후처리 STT
```gherkin
Given 일반 통화 녹음 완료 (mixed.wav)
When stop_recording() 호출
Then Google Speech-to-Text API 호출
And 화자 분리(diarization) 실행
And transcript.txt 생성
```

#### TC-REC-003: 일반 통화 지식 추출
```gherkin
Given 일반 통화 transcript.txt 생성
When KnowledgeExtractor.extract_from_call() 호출
Then LLM이 착신자 발화 분석
And 유용성 판단
And Vector DB에 저장
```

### 3.4 Backend API 시나리오

#### TC-API-001: 통화 이력 조회
```gherkin
Given 운영자가 로그인
When GET /api/call-history
Then 최근 50개 통화 목록 반환
And call_id, caller, callee, duration 포함
```

#### TC-API-002: 실시간 통화 모니터링
```gherkin
Given Frontend가 WebSocket 연결
When 새로운 통화 시작
Then WebSocket 이벤트 전송: call_started
And 실시간 트랜스크립트 업데이트
```

#### TC-API-003: HITL 응답 제출
```gherkin
Given HITL 요청 대기 중
When POST /api/hitl/requests/{id}/respond
Then AI Orchestrator가 응답 수신
And TTS로 재생
And HITL 요청 상태: resolved
```

#### TC-API-004: 녹음 재생
```gherkin
Given 통화 녹음 존재
When GET /api/recordings/{call_id}/mixed.wav
Then WAV 파일 스트리밍
And Range 헤더 지원
```

#### TC-API-005: AI Insights 조회
```gherkin
Given AI 통화 완료
When GET /api/ai-insights/{call_id}
Then RAG 검색 기록 반환
And LLM 처리 로그 반환
```

### 3.5 Frontend 시나리오

#### TC-FE-001: 대시보드 표시
```gherkin
Given 운영자가 로그인
When 대시보드 접속
Then 활성 통화 수 표시
And 오늘의 통화 통계 표시
And 최근 통화 목록 표시
```

#### TC-FE-002: 실시간 통화 모니터링
```gherkin
Given AI 통화 진행 중
When Live Call Monitor 열기
Then 실시간 트랜스크립트 표시
And AI 발화 상태 표시
```

#### TC-FE-003: HITL 대화 상자
```gherkin
Given HITL 요청 수신
When 운영자가 답변 입력
Then 실시간으로 AI에게 전달
And "지식 베이스 저장" 체크박스 표시
And 저장 시 Vector DB에 추가
```

#### TC-FE-004: 통화 이력 상세
```gherkin
Given 통화 이력에서 항목 선택
When 상세 페이지 접속
Then Wavesurfer.js로 녹음 재생
And 트랜스크립트 표시
And AI Insights 표시
```

#### TC-FE-005: 지식 베이스 관리
```gherkin
Given 지식 베이스 페이지 접속
When 검색어 입력 "예약"
Then Vector DB 검색 결과 표시
And 수정/삭제 버튼 제공
And 수동 추가 기능 제공
```

---

## 4. 테스트 환경

### 4.1 로컬 개발 환경

```yaml
OS: Windows 10+ / Ubuntu 20.04+
Python: 3.11+
Node.js: 18+
Database: PostgreSQL 14+ (Docker)
Redis: 7+ (Docker)
Vector DB: ChromaDB (로컬) / Pinecone (클라우드)
```

### 4.2 CI/CD 환경

```yaml
Platform: GitHub Actions / GitLab CI
Containers: Docker Compose
Test Runner: pytest
Frontend: Jest, Playwright
```

### 4.3 Staging 환경

```yaml
Cloud: AWS / GCP / Azure
SIP Server: 실제 Public IP
Database: RDS / Cloud SQL
Load Balancer: Nginx
```

---

## 부록: 테스트 케이스 템플릿

```python
# tests/template/test_example.py

import pytest
from unittest.mock import Mock

class TestExample:
    """테스트 클래스 설명"""
    
    @pytest.fixture
    def setup_data(self):
        """테스트 데이터 준비"""
        return {"key": "value"}
    
    def test_given_when_then(self, setup_data):
        """
        Given: 초기 상태 설명
        When: 실행할 동작
        Then: 예상 결과
        """
        # Given
        input_data = setup_data
        
        # When
        result = function_under_test(input_data)
        
        # Then
        assert result == expected_output
```

---

**작성자**: Quinn (Test Architect)  
**최종 업데이트**: 2026-01-08
