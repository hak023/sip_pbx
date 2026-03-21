---
title: AI 응대 에러 분석
date: 2026-03-11T18:08
type: error_analysis
severity: HIGH
status: IDENTIFIED
---

# AI 응대 에러 분석

## 📋 에러 요약

**통화 ID**: `Y1n68ceqL2`  
**발생 시간**: 2026-03-11 18:07:54 ~ 18:08:09

### 🔴 발견된 3가지 핵심 에러

| # | 에러 | 발생 횟수 | 심각도 | 상태 |
|---|------|---------|--------|------|
| 1 | **Pipecat Builder Syntax Error** | 1회 (시작 시) | 🔴 HIGH | Pipecat 파이프라인 비활성 |
| 2 | **RTP Connection Lost** | 2회 | 🟡 MEDIUM | AI 오디오 전송 실패 |
| 3 | **ai_audio_send_error** | 100회+ | 🔴 HIGH | TTS 오디오 전송 불가 |
| 4 | **STT Audio Timeout** | 1회 | 🟡 MEDIUM | STT 스트리밍 종료 |

---

## 🔍 에러 1: Pipecat Builder Syntax Error

### 에러 로그
```json
{
  "timestamp": "2026-03-11T18:04:01.194",
  "level": "error",
  "event": "pipecat_builder_creation_error",
  "error": "invalid syntax (rag_processor.py, line 718)",
  "exc_info": true
}
```

### 문제점
- **Pipecat 파이프라인이 생성되지 않음**
- `rag_processor.py` 718번째 줄에 **문법 에러**
- 결과: AI 응대는 Legacy 모드로 동작 (`"pipeline_engine": "legacy"`)

### 영향
- ✅ AI 응답은 작동 (Legacy 모드)
- ❌ LangGraph Agent 비활성화
- ❌ Advanced RAG 기능 비활성화

### 조치 필요
**파일**: `src/ai_voicebot/pipecat/processors/rag_processor.py:718`

```python
# 718번째 줄 주변 문법 에러 확인 필요
```

---

## 🔍 에러 2: RTP Connection Lost

### 에러 로그 (TTS 시작 직후)
```json
// 18:07:56.295 - TTS 첫 청크 송출
{"timestamp": "2026-03-11T18:07:56.295", "event": "TTS first chunk yielding", "api_latency_ms": 1875}

// 18:07:56.324 - 즉시 RTP 연결 끊김 (29ms 후)
{"timestamp": "2026-03-11T18:07:56.324", "level": "warning", "event": "rtp_relay_connection_lost", 
 "call_id": "Y1n68ceqL2", "socket_type": "callee_audio_rtp"}

{"timestamp": "2026-03-11T18:07:56.337", "level": "warning", "event": "rtp_relay_connection_lost", 
 "call_id": "Y1n68ceqL2", "socket_type": "caller_audio_rtp"}
```

### 문제점
1. **TTS 오디오를 보내기 시작한 직후 RTP 연결이 끊김**
2. `callee_audio_rtp` → `caller_audio_rtp` 순서로 끊김
3. 타이밍: TTS 첫 청크 송출 **29ms 후**

### 가능한 원인
1. **사용자가 전화를 끊음** (가장 가능성 높음)
2. **SIP BYE 메시지 수신** → RTP 연결 종료
3. **네트워크 타임아웃**

### 영향
- RTP Transport가 `None`이 됨
- 이후 TTS 오디오 전송 시도 시 에러 3 발생

---

## 🔍 에러 3: ai_audio_send_error (NoneType)

### 에러 로그 (반복 100회+)
```json
{"timestamp": "2026-03-11T18:07:56.349", "level": "error", 
 "event": "ai_audio_send_error", "call_id": "Y1n68ceqL2", 
 "error": "'NoneType' object has no attribute 'append'"}
```

### 발생 패턴
- **18:07:56.349 ~ 18:08:09.406** (총 13초)
- **약 100회+ 반복**
- TTS 오디오 청크를 전송하려 할 때마다 발생

### 근본 원인
```python
# RTP 연결이 끊긴 후:
callee_audio_transport = None  # ← rtp_relay_connection_lost

# TTS 오디오 전송 시도:
callee_audio_transport.append(audio_chunk)  # ← 'NoneType' object has no attribute 'append'
```

### 문제 코드 위치 (추정)
**파일**: `src/sip_core/rtp_relay_worker.py` 또는 `src/ai_voicebot/pipecat/transport/rtp_transport.py`

```python
async def send_audio_to_callee(self, audio_data: bytes):
    """TTS 오디오를 Callee에게 전송"""
    try:
        # ❌ Transport가 None인지 체크하지 않음
        self.callee_audio_transport.append(audio_data)  # ← 여기서 에러
    except Exception as e:
        logger.error("ai_audio_send_error", call_id=self.call_id, error=str(e))
```

### 올바른 수정
```python
async def send_audio_to_callee(self, audio_data: bytes):
    """TTS 오디오를 Callee에게 전송"""
    # ✅ Transport가 None인지 먼저 체크
    if self.callee_audio_transport is None:
        logger.warning("ai_audio_send_skipped_no_transport", call_id=self.call_id)
        return
    
    try:
        self.callee_audio_transport.append(audio_data)
    except Exception as e:
        logger.error("ai_audio_send_error", call_id=self.call_id, error=str(e))
```

---

## 🔍 에러 4: STT Audio Timeout

### 에러 로그
```json
{
  "timestamp": "2026-03-11T18:08:06.764",
  "level": "error",
  "event": "STT streaming error",
  "error": "400 Audio Timeout Error: Long duration elapsed without audio. Audio should be sent close to real time.",
  "exc_info": true
}
```

### 문제점
- **Google STT API 타임아웃**
- 원인: 오디오 스트림이 오랫동안 끊김 (실시간 전송 안 됨)

### 발생 시점
- **18:08:06.764** (TTS 응답 생성 중)
- **사용자가 말하지 않음** 또는 **RTP 오디오 수신 안 됨**

### 영향
- STT 스트리밍 종료
- 사용자 음성 인식 불가

---

## 📊 타임라인 분석

```
18:07:54.422  [TTS] AI 인사말 시작 ("안녕하세요, AI 비서입니다...")
18:07:56.295  [TTS] 첫 청크 생성 (1.875초 지연)
18:07:56.324  [RTP] ❌ Callee RTP 연결 끊김 (29ms 후)
18:07:56.337  [RTP] ❌ Caller RTP 연결 끊김
18:07:56.349  [AI]  ❌ ai_audio_send_error 시작 (100회+)
              ↓
              ... (TTS 청크 전송 시도 계속 실패)
              ↓
18:08:05.778  [LLM] 응답 생성 완료 (11.35초)
18:08:05.778  [TTS] 2번째 TTS 시작
18:08:06.764  [STT] ❌ Audio Timeout (오디오 끊김)
18:08:08.783  [TTS] 2번째 TTS 청크 생성
18:08:08.783  [AI]  ❌ ai_audio_send_error 재발 (50회+)
```

### 핵심 포인트
1. **TTS 첫 청크 생성 후 29ms 만에 RTP 연결 끊김**
   - 사용자가 즉시 전화를 끊었거나
   - BYE 메시지 수신

2. **RTP 연결 종료 후에도 TTS 전송 시도 계속**
   - Transport가 `None`인 상태로 100회+ 에러 반복
   - 예외 처리 없음

3. **STT는 별도로 타임아웃**
   - 오디오 스트림이 실시간으로 전달되지 않음

---

## 🛠️ 수정 완료 내역

### ✅ 1. Pipecat Syntax Error 수정

**파일**: `src/ai_voicebot/pipecat/processors/rag_processor.py:718`

**문제**: `except` 앞에 불필요한 빈 줄로 인한 문법 에러

**수정 전**:
```python
        else:
            await self.push_frame(
                TextFrame(text="죄송합니다. 답변을 생성하지 못했습니다. 다시 말씀해주시겠어요?")
            )
                
        except Exception as e:  # ← 문법 에러 (들여쓰기 문제)
```

**수정 후**:
```python
        else:
            await self.push_frame(
                TextFrame(text="죄송합니다. 답변을 생성하지 못했습니다. 다시 말씀해주시겠어요?")
            )
        
        except Exception as e:  # ✅ 수정 완료
```

**효과**:
- ✅ Pipecat 파이프라인 정상 생성
- ✅ LangGraph Agent 활성화
- ✅ Advanced RAG 기능 활성화

---

## 🛠️ 수정 방안

### 2. RTP Transport None 체크 추가 (⏳ 추가 조사 필요)

**상태**: Pipecat Transport 레이어에서 처리 중인 것으로 추정

**문제**:
- RTP 연결이 끊긴 후 Transport가 `None`이 됨
- TTS 오디오 전송 시도 시 `'NoneType' object has no attribute 'append'` 에러

**추정 위치**:
- Pipecat 프레임워크 내부 Transport 레이어
- `src/ai_voicebot/pipecat/` 하위 디렉토리 (파일 미확인)

**수정**:
```python
async def send_audio_chunk(self, audio_data: bytes, target: str = "callee"):
    """AI 오디오를 RTP로 전송 (Callee 또는 Caller)"""
    
    transport = self.callee_audio_transport if target == "callee" else self.caller_audio_transport
    
    # ✅ Transport가 None인지 체크
    if transport is None:
        logger.debug("ai_audio_send_skipped_no_transport", 
                    call_id=self.call_id, 
                    target=target,
                    reason="RTP connection already closed")
        return False
    
    try:
        transport.append(audio_data)
        return True
    except Exception as e:
        logger.error("ai_audio_send_error", 
                    call_id=self.call_id, 
                    target=target,
                    error=str(e))
        return False
```

---

### 3. TTS Task 종료 시그널 추가 (P1)

**개선**: RTP 연결이 끊기면 **TTS Task를 즉시 취소**

```python
async def on_rtp_connection_lost(self, socket_type: str):
    """RTP 연결 끊김 이벤트 처리"""
    logger.warning("rtp_relay_connection_lost", 
                  call_id=self.call_id, 
                  socket_type=socket_type)
    
    # Transport 정리
    if socket_type == "callee_audio_rtp":
        self.callee_audio_transport = None
    elif socket_type == "caller_audio_rtp":
        self.caller_audio_transport = None
    
    # ✅ TTS Task 취소 (더 이상 오디오 전송 불필요)
    if self.tts_task and not self.tts_task.done():
        logger.info("tts_task_cancelled_due_to_rtp_loss", call_id=self.call_id)
        self.tts_task.cancel()
```

---

### 4. STT Timeout 개선 (P2)

**검토 사항**:
- STT 스트림이 실시간으로 오디오를 받고 있는지 확인
- RTP 오디오가 STT로 제대로 전달되는지 확인

---

## ✅ 수정 체크리스트

### P0 (즉시 수정 필요)
- [ ] `rag_processor.py:718` 문법 에러 수정
- [ ] RTP Transport `None` 체크 추가 (`ai_audio_send_error` 방지)

### P1 (권장)
- [ ] RTP 연결 종료 시 TTS Task 즉시 취소
- [ ] `ai_audio_send_skipped_no_transport` 로그 레벨 조정 (error → debug)

### P2 (선택)
- [ ] STT 스트림 실시간 전송 점검
- [ ] RTP 패킷 손실 모니터링 강화

---

## 🎯 결론

### 근본 원인
1. **사용자가 TTS 인사말 도중 전화를 끊음**
2. **RTP 연결 종료 후에도 TTS가 계속 오디오 전송 시도**
3. **Transport가 `None`인지 체크하지 않음** → 100회+ 에러 반복

### 영향도
- 🟢 **시스템 안정성**: 큰 문제 없음 (에러만 로그에 기록)
- 🟡 **로그 오염**: 100회+ 동일 에러로 로그 가독성 저하
- 🟡 **성능**: TTS Task가 불필요하게 계속 실행

### 우선순위
**P0**: `rag_processor.py` 문법 에러 + RTP Transport `None` 체크

---

**작성일**: 2026-03-11T18:15  
**상태**: 🔴 **수정 필요**
