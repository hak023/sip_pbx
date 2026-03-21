# RTP Connection Lost 근본 원인 수정 완료

**작성일**: 2026-03-11  
**상태**: ✅ 수정 완료  
**관련 문서**: 
- [RTP_CONNECTION_LOST_ROOT_CAUSE_FINAL.md](RTP_CONNECTION_LOST_ROOT_CAUSE_FINAL.md) - 근본 원인 분석

---

## 📋 문제 요약

AI 응대 시작 직후 **29ms 만에** `rtp_relay_connection_lost` (callee_audio_rtp)가 발생하고, 수백 개의 `'NoneType' object has no attribute 'append'` 에러가 발생하여 **AI TTS 음성이 전송되지 않는 문제**.

### 근본 원인

AI Takeover 시나리오에서:
1. 원래 Callee (1004)는 CANCEL되어 응답하지 않음
2. **`callee_audio_transport`는 여전히 원래 Callee의 endpoint (`0.0.0.0:0`)를 가리킴**
3. TTS가 invalid endpoint로 전송 시도 → **Windows UDP Transport가 즉시 `connection_lost` 발생**
4. Transport가 `None`으로 설정됨 → 이후 모든 TTS 전송 실패

---

## ✅ 적용된 수정 사항

### 1. AI Takeover 시 Callee Transport Endpoint 명시적 재설정

**파일**: `sip-pbx/src/sip_core/sip_endpoint.py`

**위치**: Line 3075-3095 (AI Takeover RTP 모드 전환 로직)

**변경 내용**:
```python
# ✅ P0 FIX: AI 모드에서는 Callee Transport의 remote_endpoint를 Caller로 명시적 재설정
# AI TTS 출력이 Caller에게 가도록 보장
if "callee_audio_rtp" in rtp_worker.protocols:
    callee_protocol = rtp_worker.protocols["callee_audio_rtp"]
    callee_protocol.remote_endpoint = rtp_worker.caller_endpoint
    callee_protocol.remote_port = rtp_worker.caller_endpoint.port
    logger.info("✅ [AI Takeover] Callee Transport redirected to Caller",
               call_id=call_id,
               caller_endpoint=f"{rtp_worker.caller_endpoint.ip}:{rtp_worker.caller_endpoint.port}",
               note="TTS 오디오가 Caller로 정확히 전송되도록 설정")
```

**효과**:
- AI 모드 활성화 시 `callee_audio_rtp` 프로토콜의 `remote_endpoint`를 **Caller로 명시적 재설정**
- TTS 오디오가 올바른 목적지(Caller)로 전송되도록 보장
- Invalid endpoint로 인한 `connection_lost` 방지

---

### 2. AI 모드 Transport 선택 우선순위 변경

**파일**: `sip-pbx/src/media/rtp_relay.py`

**위치**: Line 762-778 (Pipecat TTS Sender Loop)

**변경 내용**:
```python
# ✅ AI 모드: Caller Transport 우선 (Callee Transport는 invalid일 수 있음)
# AI Takeover 후 Callee Transport가 connection_lost될 수 있으므로 Caller Transport 사용
if self.ai_mode:
    _transport = self.caller_audio_transport or self.callee_audio_transport
else:
    _transport = self.callee_audio_transport or self.caller_audio_transport

if not _transport or not self.caller_endpoint:
    logger.error("rtp_tts_no_valid_transport",
                call_id=self.media_session.call_id,
                ai_mode=self.ai_mode,
                has_caller_transport=self.caller_audio_transport is not None,
                has_callee_transport=self.callee_audio_transport is not None,
                note="TTS 전송 불가 - Transport 없음")
    continue
```

**효과**:
- AI 모드에서는 `caller_audio_transport`를 우선 사용 (더 안정적)
- Callee Transport가 끊긴 경우 자동 폴백
- 명확한 에러 로깅으로 디버깅 용이

---

### 3. Transport 유효성 체크 강화

**파일**: `sip-pbx/src/media/rtp_relay.py`

**위치**: Line 895-914 (RTP sendto 블록)

**변경 내용**:
```python
try:
    # ✅ Transport 유효성 재확인 (connection_lost 후 None일 수 있음)
    if not _transport or _transport.is_closing():
        logger.error("rtp_transport_invalid_before_send",
                    call_id=self.media_session.call_id,
                    transport_type=type(_transport).__name__ if _transport else "None",
                    is_closing=_transport.is_closing() if _transport else "N/A",
                    note="Transport 무효 - TTS 전송 중단")
        break
    
    # ✅ Windows Proactor 동시성 보호
    async with self._sendto_lock:
        _transport.sendto(packet, (caller_ip, caller_port))
    packets_sent += 1
    self.stats["rtp_tts_packets_sent"] += 1
except Exception as send_err:
    self.stats["rtp_tts_send_errors"] += 1
    logger.error("rtp_sendto_failed",
               call_id=self.media_session.call_id,
               dest_addr=f"{caller_ip}:{caller_port}",
               error=str(send_err),
               error_type=type(send_err).__name__)
    await asyncio.sleep(interval_sec)
    continue
```

**효과**:
- sendto 직전 Transport 상태 재확인 (`is_closing()` 체크)
- Race condition 방지 (connection_lost와 sendto 동시 발생)
- 상세한 에러 타입 로깅으로 향후 이슈 추적 용이

---

### 4. Connection Lost 콜백 로깅 개선

**파일**: `sip-pbx/src/media/rtp_relay.py`

**위치**: Line 1617-1640 (connection_lost 콜백)

**변경 내용**:
```python
def connection_lost(self, exc: Optional[Exception]) -> None:
    if exc:
        logger.warning("rtp_relay_connection_lost",
                      call_id=self.relay_worker.media_session.call_id,
                      socket_type=self.socket_type,
                      error=str(exc))

    if self.socket_type == "callee_audio_rtp":
        # AI 모드에서 Callee Transport가 끊긴 경우 Caller Transport로 폴백
        if self.relay_worker.ai_mode:
            logger.info("callee_transport_lost_in_ai_mode_fallback_to_caller",
                       call_id=self.relay_worker.media_session.call_id,
                       has_caller_transport=self.relay_worker.caller_audio_transport is not None,
                       note="AI 모드 - Caller Transport로 폴백 (정상 동작)")
        self.relay_worker.callee_audio_transport = None
        logger.info("callee_audio_transport_cleared",
                   call_id=self.relay_worker.media_session.call_id,
                   reason="connection_lost")
```

**효과**:
- AI 모드에서의 `connection_lost`가 **정상 동작**임을 명시적으로 로깅
- 폴백 상태를 명확히 표시하여 혼란 방지
- 디버깅 시 "AI 모드 - Caller Transport로 폴백 (정상 동작)" 메시지로 안심 가능

---

## 🧪 검증 로그 (예상)

### Before (수정 전)
```json
{"event": "call_established", "timestamp": "18:07:54.420"}
{"event": "TTS started", "timestamp": "18:07:54.422"}
{"event": "TTS first chunk yielding", "timestamp": "18:07:56.295"}
{"event": "rtp_relay_connection_lost", "socket_type": "callee_audio_rtp", "timestamp": "18:07:56.324"} ❌
{"event": "ai_audio_send_error", "error": "'NoneType' object has no attribute 'append'", ...} (수백 개)
```

### After (수정 후)
```json
{"event": "call_established", "timestamp": "18:07:54.420"}
{"event": "✅ [AI Takeover] Callee Transport redirected to Caller", "caller_endpoint": "192.168.1.100:5004"}
{"event": "TTS started", "timestamp": "18:07:54.422"}
{"event": "TTS first chunk yielding", "timestamp": "18:07:56.295"}
{"event": "rtp_first_packet_sent", "dest_ip": "192.168.1.100", "dest_port": 5004} ✅
{"event": "rtp_sender_progress", "packets_sent": 100, ...}
{"event": "TTS completed"} ✅
```

**검증 포인트**:
- ✅ `rtp_relay_connection_lost` 발생하지 않음
- ✅ `ai_audio_send_error` 발생하지 않음
- ✅ `rtp_first_packet_sent` 정상 출력
- ✅ 음성 정상 전송 및 수신

---

## 📊 기대 효과

### 1. AI 응대 음성 품질 개선
- **Before**: TTS 음성 전송 실패 → 사용자가 AI 인사말을 듣지 못함
- **After**: TTS 음성 정상 전송 → 사용자가 AI 인사말 및 응답을 정상적으로 수신

### 2. 에러 로그 감소
- **Before**: 수백 개의 `ai_audio_send_error` 발생
- **After**: 에러 없음, 정상 로그만 출력

### 3. 시스템 안정성 향상
- Transport 유효성 체크 강화로 Race condition 방지
- AI 모드 전환 시 명확한 상태 관리

### 4. 디버깅 용이성 증가
- 명확한 로그 메시지로 AI 모드 동작 이해 쉬움
- "정상 동작" 표시로 불필요한 디버깅 시간 절약

---

## 📌 추가 개선 가능 사항 (선택)

### Future Enhancement 1: Transport 재생성 로직
- Connection Lost 후 자동으로 Transport 재생성
- 현재는 폴백으로 충분하지만, 장시간 통화 시 고려 필요

### Future Enhancement 2: STUN Response 최적화
- AI 모드 초기 STUN 바인딩 타이밍 최적화
- NAT 환경에서 추가 테스트 필요

### Future Enhancement 3: Monitoring
- Prometheus 메트릭 추가: `rtp_connection_lost_count{mode="ai"}`
- Grafana 대시보드에서 실시간 모니터링

---

## 🎯 완료 체크리스트

- [x] P0: `sip_endpoint.py`에 Callee Transport 재설정 로직 추가
- [x] P1: `rtp_relay.py`에 AI 모드 Transport 우선순위 로직 추가
- [x] P1: Transport 유효성 체크 강화
- [x] 로깅 개선 (정상 동작 명시)
- [x] `INDEX.md` 문서 업데이트
- [ ] 테스트 실행 및 로그 확인 (다음 테스트 시)
- [ ] 검증 완료 후 이슈 클로즈

---

## 🚀 다음 단계

1. **테스트 실행**
   - AI 응대 시나리오 (Caller → Timeout → AI 인사말)
   - 로그에서 `✅ [AI Takeover] Callee Transport redirected to Caller` 확인
   - `rtp_first_packet_sent` 로그 확인
   - 실제 음성 수신 확인

2. **로그 검증**
   - `rtp_relay_connection_lost` 없음 확인
   - `ai_audio_send_error` 없음 확인
   - TTS 전송 완료 로그 확인

3. **완료 보고**
   - 테스트 결과 긍정적이면 이슈 완전 클로즈
   - 추가 이슈 발견 시 보고 및 재분석

---

**상태**: ✅ 코드 수정 완료, 테스트 대기 중
