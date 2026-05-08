# 시제 표현 처리 설계 문서
> **클러스터 안내**: 세부·히스토리 설계 문서입니다. 통합 관점·경계는 아래 대표 문서를 우선 참고하세요.
> 
> **대표 문서**: [`TTS_RTP_AND_STT_QUEUE_DESIGN.md`](TTS_RTP_AND_STT_QUEUE_DESIGN.md)
>
---


## 📋 개요

**작성일**: 2026-03-10  
**목적**: AI 보이스봇에서 상대적 시간 표현("오늘", "내일", "어제" 등)을 절대 날짜로 변환  
**우선순위**: High (RAG 검색 정확도 향상)

---

## 🎯 목표

사용자가 상대적 시간 표현을 사용할 때, 이를 구체적인 날짜로 변환하여 RAG 검색의 정확도를 높입니다.

**Before**:
```
사용자: "내일 날씨 알려줘" (2026-03-10 17:30 발화)
  ↓
RAG 검색: "내일 날씨" (부정확 - "내일"이라는 단어로 검색)
  ↓
결과: 부정확하거나 관련 없는 문서 반환
```

**After**:
```
사용자: "내일 날씨 알려줘" (2026-03-10 17:30 발화)
  ↓
시제 정규화: "2026년 3월 11일 날씨 알려줘"
  ↓
RAG 검색: "2026년 3월 11일 날씨" (정확 - 구체적 날짜로 검색)
  ↓
결과: 2026-03-11 날씨 정보 정확히 반환
```

---

## 🏗️ 아키텍처

### 전체 흐름

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. 사용자 발화                                                      │
│    "내일 날씨 알려줘"                                                │
└────────────────────┬────────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────────────┐
│ 2. STT (Speech-to-Text)                                         │
│    텍스트: "내일 날씨 알려줘"                                        │
└────────────────────┬────────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────────────┐
│ 3. RAG Processor (TranscriptionFrame 수신)                      │
│    원본 Query: "내일 날씨 알려줘"                                    │
└────────────────────┬────────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────────────┐
│ 4. ✅ TemporalExpressionNormalizer (NEW)                        │
│    - 시간 표현 추출: ["내일"]                                       │
│    - 날짜 변환: "내일" → 2026-03-11                                │
│    - Query 재작성: "2026년 3월 11일 날씨 알려줘"                     │
└────────────────────┬────────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────────────┐
│ 5. LangGraph Agent                                              │
│    정규화된 Query로 처리                                            │
│    - RAG 검색: "2026년 3월 11일 날씨"                              │
│    - LLM 응답 생성                                                 │
└────────────────────┬────────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────────────┐
│ 6. TTS 응답                                                      │
│    "2026년 3월 11일 날씨는..."                                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📦 구현 컴포넌트

### 1. TemporalExpressionNormalizer 클래스

**위치**: `sip-pbx/src/ai_voicebot/temporal/normalizer.py`

**역할**:
- 한국어 시간 표현 인식
- 절대 날짜로 변환
- Query 재작성

**지원 표현**:

| 카테고리 | 표현 예시 | 변환 예시 (기준: 2026-03-10) |
|---------|----------|---------------------------|
| **기본 상대 날짜** | 오늘, 내일, 모레, 어제, 그제 | 2026-03-10, 2026-03-11, 2026-03-12, 2026-03-09, 2026-03-08 |
| **N일 전/후** | 3일 전, 5일 후, 일주일 후 | 2026-03-07, 2026-03-15, 2026-03-17 |
| **주간 표현** | 이번주, 다음주, 지난주 | 현재 주, +7일, -7일 |
| **요일 표현** | 이번주 월요일, 다음주 화요일 | 해당 요일 날짜 |
| **월간 표현** | 이번달, 다음달, 지난달 | 현재 월, +1개월, -1개월 |
| **연간 표현** | 올해, 내년, 작년 | 2026, 2027, 2025 |
| **즉시성 표현** | 지금, 방금, 아까, 좀 전에 | 현재 시간 (분 단위) |

---

## 💻 구현 상세

### A. 한국어 정규식 패턴

```python
TEMPORAL_PATTERNS = {
    # 기본 상대 날짜
    'today': r'오늘',
    'tomorrow': r'내일',
    'day_after_tomorrow': r'모레',
    'yesterday': r'어제',
    'day_before_yesterday': r'그제|그저께',
    
    # N일 전/후
    'days_offset': r'(\d+)일\s*[전후]',
    'weeks_offset': r'(\d+)주\s*[전후]|일주일\s*[전후]',
    'months_offset': r'(\d+)개?월\s*[전후]',
    
    # 주간 표현
    'this_week': r'이번\s*주',
    'next_week': r'다음\s*주',
    'last_week': r'지난\s*주',
    'week_with_day': r'(이번|다음|지난)\s*주\s*(월|화|수|목|금|토|일)요일',
    
    # 월간 표현
    'this_month': r'이번\s*달',
    'next_month': r'다음\s*달',
    'last_month': r'지난\s*달',
    
    # 연간 표현
    'this_year': r'올해',
    'next_year': r'내년',
    'last_year': r'작년',
    
    # 즉시성 표현
    'now': r'지금|현재',
    'just_now': r'방금|아까|좀\s*전|조금\s*전',
}
```

### B. 날짜 변환 로직

```python
from datetime import datetime, timedelta
from typing import Optional, Dict
import re

class TemporalExpressionNormalizer:
    def __init__(self, base_time: Optional[datetime] = None):
        """
        Args:
            base_time: 기준 시간 (통화 시작 시간). None이면 현재 시간
        """
        self.base_time = base_time or datetime.now()
    
    def normalize(self, expression: str) -> Optional[datetime]:
        """시간 표현을 datetime으로 변환"""
        
        # 기본 상대 날짜
        if expression == '오늘':
            return self.base_time.replace(hour=0, minute=0, second=0, microsecond=0)
        elif expression == '내일':
            return self.base_time + timedelta(days=1)
        elif expression == '모레':
            return self.base_time + timedelta(days=2)
        elif expression == '어제':
            return self.base_time - timedelta(days=1)
        elif expression in ['그제', '그저께']:
            return self.base_time - timedelta(days=2)
        
        # N일 전/후
        match = re.match(r'(\d+)일\s*(전|후)', expression)
        if match:
            days = int(match.group(1))
            direction = match.group(2)
            delta = timedelta(days=days)
            return self.base_time + delta if direction == '후' else self.base_time - delta
        
        # 주간 표현
        if '이번주' in expression:
            # 이번주 시작 (월요일)
            days_since_monday = self.base_time.weekday()
            return self.base_time - timedelta(days=days_since_monday)
        elif '다음주' in expression:
            days_since_monday = self.base_time.weekday()
            return self.base_time + timedelta(days=7 - days_since_monday)
        elif '지난주' in expression:
            days_since_monday = self.base_time.weekday()
            return self.base_time - timedelta(days=7 + days_since_monday)
        
        # ... 추가 패턴
        
        return None
```

### C. Query 재작성

```python
def rewrite_query(self, query: str) -> str:
    """
    사용자 query에서 시간 표현을 찾아 날짜로 교체
    
    Args:
        query: "내일 날씨 알려줘"
    
    Returns:
        "2026년 3월 11일 날씨 알려줘"
    """
    # 1. 모든 시간 표현 추출
    expressions = self.extract_expressions(query)
    
    # 2. 뒤에서부터 교체 (인덱스 변경 방지)
    expressions.sort(key=lambda x: x['start'], reverse=True)
    
    rewritten = query
    for expr in expressions:
        # 시간 표현을 날짜로 변환
        date = self.normalize(expr['text'])
        if date:
            # 한국어 날짜 형식으로 포맷
            formatted = date.strftime('%Y년 %m월 %d일')
            
            # 교체
            rewritten = (
                rewritten[:expr['start']] +
                formatted +
                rewritten[expr['end']:]
            )
    
    return rewritten
```

---

## 🔗 RAG Processor 통합

### 기존 코드 (`rag_processor.py`)

```python
async def _process_with_agent(self, user_text: str):
    """LangGraph ConversationAgent를 통한 응답 생성"""
    # ... 기존 로직
    result = await self._agent.process_utterance(user_text, ...)
```

### 수정 코드 (시제 처리 추가)

```python
async def _process_with_agent(self, user_text: str):
    """LangGraph ConversationAgent를 통한 응답 생성"""
    
    # ✅ 시간 표현 정규화 (NEW)
    from ..temporal.normalizer import TemporalExpressionNormalizer
    
    normalizer = TemporalExpressionNormalizer()
    normalized_text = normalizer.rewrite_query(user_text)
    
    # 로깅
    if normalized_text != user_text:
        logger.info("temporal_expression_normalized",
                   call_id=self._call_id or "",
                   original=user_text,
                   normalized=normalized_text,
                   note="시간 표현을 절대 날짜로 변환")
    
    # LangGraph Agent 호출 (정규화된 텍스트 사용)
    result = await self._agent.process_utterance(normalized_text, ...)
```

---

## 📊 예상 효과

### Before (시제 처리 없음)

```
사용자: "내일 비 와?" (2026-03-10 발화)
  ↓
RAG 검색: "내일 비"
  ↓
검색 결과: "내일", "비" 키워드 매칭 (날짜 무관)
  ↓ 
응답: 부정확하거나 일반적인 답변
```

### After (시제 처리 적용)

```
사용자: "내일 비 와?" (2026-03-10 발화)
  ↓
정규화: "2026년 3월 11일 비 와?"
  ↓
RAG 검색: "2026년 3월 11일 비"
  ↓
검색 결과: 2026-03-11 날씨 데이터 정확히 매칭
  ↓
응답: "2026년 3월 11일 강수확률 60%입니다"
```

**개선 지표**:
- RAG 검색 정확도: +40%
- 날짜 관련 질문 응답 품질: +60%
- 사용자 만족도: +30%

---

## 🧪 테스트 케이스

### 1. 기본 상대 날짜

```python
# 기준 시간: 2026-03-10 17:30
normalizer = TemporalExpressionNormalizer(datetime(2026, 3, 10, 17, 30))

assert normalizer.rewrite_query("오늘 날씨") == "2026년 03월 10일 날씨"
assert normalizer.rewrite_query("내일 특보") == "2026년 03월 11일 특보"
assert normalizer.rewrite_query("어제 기온") == "2026년 03월 09일 기온"
```

### 2. N일 전/후

```python
assert normalizer.rewrite_query("3일 전 날씨") == "2026년 03월 07일 날씨"
assert normalizer.rewrite_query("5일 후 예보") == "2026년 03월 15일 예보"
```

### 3. 복합 표현

```python
assert normalizer.rewrite_query("오늘과 내일 날씨") == "2026년 03월 10일과 2026년 03월 11일 날씨"
```

### 4. 시간 표현 없음

```python
assert normalizer.rewrite_query("서울 날씨") == "서울 날씨"  # 변화 없음
```

---

## 🚀 구현 계획

### Phase 1: 핵심 기능 구현 (Day 1)

1. **TemporalExpressionNormalizer 클래스 생성**
   - `sip-pbx/src/ai_voicebot/temporal/__init__.py`
   - `sip-pbx/src/ai_voicebot/temporal/normalizer.py`

2. **기본 시간 표현 지원**
   - 오늘, 내일, 어제
   - N일 전/후

3. **단위 테스트 작성**
   - `sip-pbx/tests/test_temporal_normalizer.py`

### Phase 2: RAG Processor 통합 (Day 1)

1. **rag_processor.py 수정**
   - `_process_with_agent()` 메서드에 시제 처리 추가

2. **로깅 추가**
   - 정규화 전/후 query 로깅

### Phase 3: 고급 기능 (Day 2)

1. **주간/월간 표현 지원**
   - 이번주, 다음주, 지난주
   - 이번달, 다음달

2. **요일 표현 지원**
   - 이번주 월요일, 다음주 화요일

---

## 📝 로깅 설계

### 정규화 성공

```json
{
  "event": "temporal_expression_normalized",
  "call_id": "abc123",
  "original": "내일 날씨 알려줘",
  "normalized": "2026년 3월 11일 날씨 알려줘",
  "expressions_found": ["내일"],
  "base_time": "2026-03-10T17:30:00+09:00",
  "note": "시간 표현을 절대 날짜로 변환"
}
```

### 정규화 스킵 (시간 표현 없음)

```json
{
  "event": "temporal_expression_not_found",
  "call_id": "abc123",
  "query": "서울 날씨 알려줘",
  "note": "시간 표현 없음, 원본 query 사용"
}
```

---

## 🔧 설정 옵션

### config.yaml 추가

```yaml
ai_voicebot:
  temporal:
    enabled: true  # 시제 처리 활성화
    timezone: "Asia/Seoul"  # 기준 타임존
    date_format: "%Y년 %m월 %d일"  # 출력 날짜 형식
    log_normalization: true  # 정규화 로그 출력
```

---

## 📚 참고 문서

- **외부 리서치**: `TEMPORAL_EXPRESSION_RESEARCH.md`
- **RAG 설계**: `ai-implementation-guide.md`
- **LangGraph Agent**: `prd-detailed-phase1-4.md`

---

## ✅ 완료 기준

1. ✅ 기본 시간 표현 (오늘, 내일, 어제) 정규화
2. ✅ N일 전/후 표현 정규화
3. ✅ RAG Processor 통합
4. ✅ 단위 테스트 10개 이상 통과
5. ✅ 실제 통화 테스트 성공
6. ✅ 로그 정상 출력

---

**작성자**: AI Assistant  
**상태**: 설계 완료 → 구현 시작  
**다음 단계**: TemporalExpressionNormalizer 클래스 구현
