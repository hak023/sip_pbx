# WAV 파일 음성 왜곡 문제 분석 및 수정

## 문제 증상
- 녹음된 WAV 파일(`caller.wav`, `callee.wav`, `mixed.wav`)의 음성이 정상적으로 들리지 않음
- 파일 포맷 자체는 정상 (8kHz, Mono, 16-bit PCM)
- RTP 패킷은 정상적으로 수신됨 (Caller 283개, Callee 309개)

## 원인 분석

### RTP → WAV 변환 프로세스
```
1. RTP 패킷 수신 (UDP Socket)
   ↓
2. RTP 헤더 파싱 (12 bytes header + payload)
   ↓
3. RTP 페이로드 추출 (G.711 인코딩된 오디오)
   ↓
4. G.711 → PCM 디코딩
   ↓
5. PCM 버퍼에 저장
   ↓
6. WAV 파일 생성
```

### 문제 지점: RTP 헤더 파싱 실패 처리

**파일:** `sip-pbx/src/media/rtp_relay.py` (Line 338-344)

**잘못된 코드:**
```python
try:
    rtp_packet = RTPParser.parse(data)
    audio_payload = rtp_packet.payload
except:
    # 파싱 실패 시 전체 데이터 사용
    audio_payload = data  # ❌ 문제!
```

**문제점:**
- RTP 파싱이 실패하면 **RTP 헤더(12 bytes)를 포함한 전체 데이터**를 G.711 디코더에 전달
- 매 RTP 패킷마다 앞 12 bytes가 **잡음**으로 변환됨
- 실제 음성 데이터는 12 bytes씩 밀려서 처리됨
- 결과: 왜곡된 음성

### RTP 패킷 구조
```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|V=2|P|X|  CC   |M|     PT      |       sequence number         |  ← 12 bytes
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+    헤더
|                           timestamp                           |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|           synchronization source (SSRC) identifier            |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                      Payload (G.711 audio)                    |  ← 페이로드만
|                              ...                              |    디코딩해야 함!
```

**일반적인 RTP 패킷 크기:**
- 20ms 음성 @ 8kHz = 160 samples = 160 bytes (G.711)
- RTP 헤더 = 12 bytes
- **총 패킷 크기 = 172 bytes**

**잘못 처리하면:**
- 172 bytes 전체를 G.711 디코더에 전달
- 앞 12 bytes가 **무작위 바이트**로 디코딩됨 → **잡음**
- 실제 음성(160 bytes)도 12 bytes 오프셋 문제로 왜곡

## 수정 사항

**파일:** `sip-pbx/src/media/rtp_relay.py` (Line 338-357)

**수정된 코드:**
```python
try:
    rtp_packet = RTPParser.parse(data)
    audio_payload = rtp_packet.payload
except Exception as parse_error:
    # 파싱 실패 시 RTP 헤더(12 bytes) 건너뛰고 페이로드만 사용
    # RTP 헤더를 포함하면 G.711 디코딩 시 잡음 발생
    if len(data) > 12:
        audio_payload = data[12:]  # ✅ 헤더 제거
        logger.debug("rtp_parse_failed_using_raw_payload",
                   call_id=self.media_session.call_id,
                   socket_type=socket_type,
                   error=str(parse_error),
                   packet_size=len(data))
    else:
        # 너무 짧은 패킷은 스킵
        logger.warning("rtp_packet_too_short",
                     call_id=self.media_session.call_id,
                     packet_size=len(data))
        return
```

**수정 내용:**
1. RTP 파싱 실패 시 **항상 12 bytes 헤더를 건너뜀**
2. 페이로드만 G.711 디코더에 전달
3. 12 bytes 미만의 비정상 패킷은 스킵
4. 디버그 로그 추가 (파싱 실패 추적)

## 검증 방법

### 1. G.711 코덱 테스트
```bash
cd C:\work\workspace_sippbx
python test_g711.py
```
- G.711 인코딩/디코딩이 정상 동작하는지 확인
- `test_g711.wav` 파일 재생하여 1kHz 사인파 확인

### 2. RTP 패킷 구조 테스트
```bash
cd C:\work\workspace_sippbx
python test_rtp_parsing.py
```
- RTP 헤더 12 bytes 구조 검증
- 헤더/페이로드 분리 로직 확인

### 3. 실제 통화 테스트
1. SIP PBX 서버 재시작
2. 통화 진행
3. 녹음 파일 재생:
   ```
   sip-pbx/recordings/YYYYMMDD_HHMMSS_caller_to_callee/mixed.wav
   ```

### 4. WAV 파일 분석
```python
import wave
import struct

w = wave.open('mixed.wav', 'rb')
frames = w.readframes(100)
samples = struct.unpack(f'{len(frames)//2}h', frames)

print('Sample values:', samples[:20])
print('Max:', max(samples))
print('Min:', min(samples))
```

**정상 샘플 예시:**
```
Sample values: (-11592, 7720, -15388, -924, 3482, ...)
Max: 16124
Min: -20732
```

**비정상 샘플 (헤더 포함 시):**
- 매우 큰 값 또는 일정한 패턴 반복
- 과도한 0 값

## 추가 개선 사항

### 1. RTP 파서 강화
RTP 파서가 실패하는 경우를 줄이기 위해:
- Version 체크 강화
- Payload Type 검증
- 패킷 크기 검증

### 2. 로깅 개선
```python
logger.debug("rtp_packet_processing",
           call_id=call_id,
           packet_size=len(data),
           payload_size=len(audio_payload),
           codec=codec,
           parse_success=True/False)
```

### 3. RTCP 패킷 필터링
이미 구현됨:
```python
if "audio" in socket_type and "rtp" in socket_type:
    # RTP 패킷만 처리, RTCP는 제외
```

## 예상 결과

### 수정 전
- 음성이 왜곡되어 들림
- 잡음 많음
- 알아듣기 어려움

### 수정 후
- 음성이 선명하게 들림
- G.711 품질 (전화 품질)
- 약간의 손실은 있지만 정상 통화 품질

## 관련 파일
- `sip-pbx/src/media/rtp_relay.py` - RTP 릴레이 및 녹음
- `sip-pbx/src/media/rtp_packet.py` - RTP 파서
- `sip-pbx/src/sip_core/sip_call_recorder.py` - 녹음 및 WAV 생성
- `test_g711.py` - G.711 코덱 테스트
- `test_rtp_parsing.py` - RTP 파싱 테스트

## 결론

**핵심 문제:** RTP 파싱 실패 시 헤더를 포함한 전체 데이터를 G.711 디코더에 전달하여 음성 왜곡 발생

**해결 방법:** RTP 파싱 실패 시에도 항상 12 bytes 헤더를 건너뛰고 페이로드만 디코딩

**상태:** ✅ 수정 완료 (`rtp_relay.py` Line 342-357)
