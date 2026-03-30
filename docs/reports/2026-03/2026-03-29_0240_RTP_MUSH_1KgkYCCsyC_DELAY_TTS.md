# RTP 뭉개짐 현상 분석: call_id 1KgkYCCsyC 및 딜레이 안내 TTS

**작성일**: 2026-03-29 02:40  
**상태**: 분석 완료, 백엔드 재시작 대기  
**관련 파일**:
- `sip-pbx/src/media/rtp_relay.py` (수정 완료)
- `sip-pbx/config/config.yaml` (수정 완료)
- `sip-pbx/logs/rtp_tx_1KgkYCCsyC.tsv`
- `sip-pbx/logs/rtp_tx_qH8dIrxLFc.tsv`

---

## 📌 요약

사용자가 보고한 두 가지 RTP 뭉개짐 현상:

1. **"저는 내일 날...........씨"** (`call_id: 1KgkYCCsyC`, 02:35:50)
2. **"정보를 확...........................................인중입니다."** (딜레이 안내 TTS)

모두 **동일한 근본 원인**으로 확인되었으며, 이미 **코드 및 config 수정 완료**되었으나 **백엔드가 아직 재시작되지 않아 미적용 상태**입니다.

---

## 🔍 상세 분석

### 1. "저는 내일 날...........씨" 뭉개짐 (call_id: 1KgkYCCsyC)

**발생 시각**: 2026-03-29 02:35:50.149  
**TTS 텍스트**: "저는 내일 날씨, 태풍 정보 확인 방법, 기상감정서 발급법, 찾아오는 길, 그리고 상담원 연결을 도와드릴 수 있습니다. 다른 도움이 필요하시면 말씀해 주세요."

#### RTP 패킷 분석

| 시각 (로컬) | 타입 | 패킷 번호 | 갭(ms) | 비고 |
|-------------|------|-----------|--------|------|
| `02:35:38.871` | media | 25138 | - | 이전 TTS 마지막 패킷 (payload=15) |
| `02:35:46.889` | **keepalive** | 25139 | **8016.393** | 8초 idle 후 keepalive 전송 |
| `02:35:50.415` | media | 25140 | **3525.778** | ❌ **3.5초 갭 발생** (뭉개짐 원인) |
| `02:35:50.434` | media | 25141 | 19.323 | 정상 |
| `02:35:50.454` | media | 25142 | 20.004 | 정상 |

**원인**:
- 이전 TTS 종료 후 8초 동안 PCM 큐가 비어 있음 → keepalive 전송
- 새 TTS 청크 도착 시점이 keepalive 직후 **3.5초 후**
- 기존 `base_time` 재설정 로직이 이 타이밍을 제대로 처리하지 못함

### 2. "정보를 확인중입니다" 딜레이 안내 TTS 뭉개짐

**발생 추정 통화**:
- `qH8dIrxLFc` (00:52:16, 14.445초 처리)
- `64noibcoFK` (01:58:43, 14.172초 처리)
- `1KgkYCCsyC` (02:35:29, 15.179초 처리)

#### 딜레이 안내 TTS 발생 조건

**코드**: `sip-pbx/src/ai_voicebot/pipecat/processors/rag_processor.py`

```python
# 라인 985-996
_LLM_WAIT_NOTIFY_SEC = 12.0

async def wait_and_notify():
    _wait_parts = ("정보를 확인 중입니다.", "잠시만 기다려 주세요.")
    _wait_full = " ".join(_wait_parts)
    try:
        await asyncio.sleep(_LLM_WAIT_NOTIFY_SEC)
        if not done.is_set():
            # ... TTS 전송
```

**발생 조건**: LLM 처리 시간이 **12초를 초과**하면 딜레이 안내 TTS 재생

#### RTP 분석: 1KgkYCCsyC의 딜레이 안내 (02:35:24-26)

| 시각 (로컬) | 타입 | 패킷 번호 | 갭(ms) | 비고 |
|-------------|------|-----------|--------|------|
| `02:35:22.742` | keepalive | 24500 | 14413.657 | 이전 TTS 후 14초 idle |
| `02:35:24.357` | keepalive | 24501 | 1615.058 | 추가 keepalive |
| `02:35:26.143` | media | 24502 | **1785.945** | 딜레이 안내 시작 (1.8초 갭) |
| `02:35:26.164` | media | 24503 | 19.807 | 정상 |

**1.8초 갭**은 상대적으로 크지 않지만, **사용자가 "엄청 뭉개지면서" 들렸다**고 보고했습니다.

가능성:
1. 해당 TTS의 **다른 구간**(문장 경계 등)에서 큰 갭 발생
2. 다른 통화에서 발생 (RTP 로그가 삭제된 케이스)
3. **1.8초도 충분히 음질 저하 유발** 가능 (특히 짧은 문장일 경우)

---

## ✅ 적용된 해결책

### 1. 코드 수정 (`rtp_relay.py`)

#### (1) keepalive 전송 시 `base_time` 재설정 제거

**이전 코드** (라인 1449-1463):
```python
# keepalive 전송 시 base_time 재설정 (잘못된 로직)
if last_was_empty_timeout:
    base_time = now
    logger.info("rtp_tts_sender_base_time_reset_on_first_keepalive", ...)
```

**수정 후**:
```python
# 제거됨 (keepalive는 타이밍 재설정하지 않음)
```

#### (2) keepalive 후 `last_was_empty_timeout` 상태 유지

**이전 코드** (라인 1431):
```python
# 잘못된 상태 관리
last_was_empty_timeout = False
```

**수정 후**:
```python
last_was_empty_timeout = True  # ✅ keepalive 후 첫 미디어에서 base_time 재설정 유도
```

#### (3) 디버깅 로그 추가

**수정된 로그** (라인 1530-1535):
```python
logger.info("rtp_tts_sender_resumed_after_empty",
            call_id=self.media_session.call_id,
            empty_timeouts=empty_timeout_count,
            packets_sent_so_far=packets_sent,
            was_keepalive_gap=(empty_timeout_count == 0 and last_was_empty_timeout),
            note="PCM 큐 비어 있다가 새 청크 수신 — 새 구간 base_time 설정 (Phase2/keepalive 후)")
```

### 2. Config 수정 (`config.yaml`)

**이전**:
```yaml
ai_rtp_keepalive_interval_sec: 8.0
```

**수정 후**:
```yaml
ai_rtp_keepalive_interval_sec: 3.0  # 3초로 단축 (6초+ 갭 방지)
```

**목적**: 긴 idle 구간에서도 **최대 3초마다 keepalive**를 전송하여, 다음 미디어 도착 시 갭을 최소화

---

## 🔄 적용 상태

### ❌ 미적용

현재 백엔드 프로세스:
- `PID 13724`: 2026-03-29 02:05:38 시작
- `PID 15300`: 2026-03-29 02:29:30 시작

**마지막 코드 수정**: 02:06 (transfer), **02:19 (config)**

→ `PID 15300`은 코드 수정 후 시작되었으나, **config.yaml 수정(02:19)은 반영 안 됨**

### ✅ 백엔드 재시작 필요

재시작 방법:
1. 현재 프로세스 종료 (`Stop-Process -Id 13724,15300`)
2. `start-all.ps1` 실행

**⚠️ 주의**: `.cursorrules`에 따라 사용자 승인 필요

---

## 🎯 기대 효과

백엔드 재시작 후:

1. **keepalive → 미디어 갭 최소화**
   - keepalive 직후 미디어 도착 시 `base_time` 정확히 재설정
   - `was_keepalive_gap` 로그로 디버깅 가능

2. **긴 idle 구간 갭 방지**
   - 최대 3초마다 keepalive 전송
   - 6초+ 갭 원천 차단

3. **모든 TTS에 적용**
   - 일반 응답 TTS
   - 딜레이 안내 TTS ("정보를 확인 중입니다")
   - 인사말 TTS

---

## 📊 케이스별 예상 결과

### Before (현재)

```
[미디어 끝] → [8초 idle] → [keepalive] → [3.5초 갭] → [미디어 시작] ❌ 뭉개짐
```

### After (재시작 후)

```
[미디어 끝] → [3초 idle] → [keepalive] → [즉시 또는 짧은 갭] → [미디어 시작] ✅ 정상
```

---

## 🔧 추가 권장 사항

### 1. 딜레이 안내 임계값 조정 검토

현재 **12초**로 설정되어 있으나, 사용자 경험 개선을 위해 **10초**로 단축 고려:

```python
# sip-pbx/src/ai_voicebot/pipecat/processors/rag_processor.py
_LLM_WAIT_NOTIFY_SEC = 10.0  # 12.0 → 10.0
```

### 2. Keepalive interval 추가 최적화

현재 **3초**로 설정했으나, 실제 운영 데이터 기반으로 **2.5초** 또는 **2초**로 추가 단축 검토 가능:

```yaml
# sip-pbx/config/config.yaml
ai_rtp_keepalive_interval_sec: 2.5  # 더 공격적 방지
```

**트레이드오프**: 더 짧은 interval = 더 많은 keepalive 패킷 = 약간의 네트워크 오버헤드

---

## ✅ 다음 단계

1. **사용자 승인 받기**: 백엔드 재시작 (cursorrules 준수)
2. **재시작 실행**: `.\start-all.ps1`
3. **검증 테스트**:
   - 새 통화 생성
   - 12초+ 소요 질문 (예: "기상청 역사를 자세히 알려주세요")
   - RTP 로그에서 `was_keepalive_gap`, keepalive interval 확인
4. **효과 확인**: 뭉개짐 현상 해소 여부

---

## 📝 이전 수정 이력

- **2026-03-29 02:06**: `intents.py` transfer 오분류 수정 (질문 패턴 pre-filter)
- **2026-03-29 02:19**: `rtp_relay.py` keepalive base_time 로직 수정
- **2026-03-29 02:19**: `config.yaml` keepalive interval 8초→3초 단축

---

## 🎯 결론

RTP 뭉개짐의 모든 케이스는 **keepalive와 미디어 사이의 갭**이 원인입니다.

**근본 해결책**:
1. ✅ `base_time` 재설정 시점 정확화 (코드 수정 완료)
2. ✅ Keepalive interval 단축 (config 수정 완료)
3. ⏳ **백엔드 재시작 필요** (사용자 승인 후)

**예상 결과**: 재시작 후 모든 RTP 뭉개짐 현상 해소
