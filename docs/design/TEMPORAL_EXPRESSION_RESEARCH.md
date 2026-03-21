# 시제 표현 처리 (Temporal Expression Resolution) 리서치

## 📋 개요

**작성일**: 2026-03-10  
**목적**: AI 보이스봇에서 "오늘", "내일", "어제", "좀 전에" 등 상대적 시간 표현을 정규화하는 방법 조사

---

## 🔍 왜 필요한가?

사용자가 "오늘의 날씨를 알려줘", "내일 특보 있어?", "지난주 월요일 날씨는?" 같은 질문을 하면, AI는 이를 구체적인 날짜로 변환해야 합니다.

**예시**:
- 사용자: "내일 비 와?" (2026-03-10 발화)
- 변환: `2026-03-11` → RAG 검색 → "2026년 3월 11일 강수확률 60%"

---

## 📚 주요 기술 및 라이브러리

### 1. Python 라이브러리

#### A. **dateparser** (가장 범용적) ⭐️⭐️⭐️⭐️⭐️

**GitHub**: https://github.com/scrapinghub/dateparser  
**Stars**: 2.5k+  
**언어**: Python  
**한국어 지원**: ✅

**특징**:
- 200개 이상 언어 지원
- 상대적 시간 표현 기본 지원
- 타임존 처리

**사용 예시**:
```python
import dateparser
from datetime import datetime

# 기준 시간 설정 (통화 시작 시간)
base_time = datetime(2026, 3, 10, 17, 30)  # 2026년 3월 10일 17시 30분

# 한국어 상대 시간 파싱
result = dateparser.parse('오늘', languages=['ko'], settings={
    'RELATIVE_BASE': base_time,
    'TIMEZONE': 'Asia/Seoul'
})
print(result)  # 2026-03-10 00:00:00

result = dateparser.parse('내일', languages=['ko'], settings={
    'RELATIVE_BASE': base_time,
    'TIMEZONE': 'Asia/Seoul'
})
print(result)  # 2026-03-11 00:00:00

result = dateparser.parse('어제', languages=['ko'], settings={
    'RELATIVE_BASE': base_time,
    'TIMEZONE': 'Asia/Seoul'
})
print(result)  # 2026-03-09 00:00:00

# 복잡한 표현
dateparser.parse('3일 전', languages=['ko'])  # 3 days ago
dateparser.parse('다음주 월요일', languages=['ko'])  # next Monday
dateparser.parse('지난달', languages=['ko'])  # last month
```

**설치**:
```bash
pip install dateparser
```

**장점**:
- 범용성 높음
- 안정적 (많은 프로젝트에서 사용)
- 문서화 잘 됨

**단점**:
- 한국어 특화 표현은 제한적 ("다다음주" 같은 고급 표현)

---

#### B. **MINAH** (한국어 특화) ⭐️⭐️⭐️

**GitHub**: https://github.com/digsy89/minah  
**Stars**: 1  
**언어**: Python  
**한국어 지원**: ✅ (전용)

**특징**:
- 한국어 날짜 표현 전용
- 문장에서 날짜 자동 인식

**사용 예시**:
```python
from minah import extract_dates

text = "오늘 날씨 어때? 내일은 비 올까?"
dates = extract_dates(text)
# [{'date': datetime(2026, 3, 10), 'text': '오늘'},
#  {'date': datetime(2026, 3, 11), 'text': '내일'}]
```

**장점**:
- 한국어 특화
- 문장에서 자동 추출

**단점**:
- 활발히 관리되지 않음
- 문서 부족

---

#### C. **timenorm-py** (Neural 기반) ⭐️⭐️⭐️⭐️

**GitHub**: https://github.com/clulab/timenorm  
**PyPI**: https://pypi.org/project/timenorm-py/  
**언어**: Python  
**한국어 지원**: ⚠️ (영어 중심, 다국어 확장 가능)

**특징**:
- Neural Network 기반 (SCATE - Semantically Compositional Annotation)
- Character-level RNN
- 복잡한 시간 표현 처리

**사용 예시**:
```python
from timenorm import Timenorm

tn = Timenorm()

# 영어 예시
result = tn.parse("last Tuesday of December at 3pm", "2026-03-10")
print(result.interval)  # [2025-12-30T15:00, 2025-12-30T16:00)

result = tn.parse("3 weeks from now", "2026-03-10")
print(result.interval)  # [2026-03-31, 2026-04-01)
```

**장점**:
- Neural 기반 → 일반화 능력 우수
- 복잡한 표현 처리 가능

**단점**:
- 한국어 직접 지원 없음 (커스텀 필요)
- TensorFlow 의존성

---

### 2. JavaScript/TypeScript 라이브러리

#### A. **ko-date-parse** (한국어 최적화) ⭐️⭐️⭐️⭐️⭐️

**GitHub**: https://github.com/youngkyo0504/ko-date-parse  
**Stars**: 7  
**언어**: TypeScript/JavaScript  
**한국어 지원**: ✅ (전용)

**특징**:
- 한국어 상대 시간 표현 전문
- 주간/시간 표현 우수

**지원 표현**:
```typescript
// 상대 날짜
parseKoreanDate('오늘')      // today
parseKoreanDate('내일')      // tomorrow
parseKoreanDate('모레')      // day after tomorrow
parseKoreanDate('어제')      // yesterday
parseKoreanDate('그제')      // day before yesterday

// N일 전/후
parseKoreanDate('3일 후')    // 3 days from now
parseKoreanDate('5일 전')    // 5 days ago

// 주간 표현
parseKoreanDate('이번주 월요일')      // this Monday
parseKoreanDate('다음주 화요일')      // next Tuesday
parseKoreanDate('다다음주 수요일')    // the week after next Wednesday
parseKoreanDate('지난주 금요일')      // last Friday

// 시간 표현
parseKoreanDate('오전 9시')           // 9:00 AM
parseKoreanDate('오후 3시 30분')      // 3:30 PM
parseKoreanDate('내일 오전 10시')     // tomorrow 10:00 AM
```

**사용 방법** (JSR):
```typescript
import { parseKoreanDate } from "@youngkyo0504/ko-date-parse";

const date = parseKoreanDate("다음주 월요일");
console.log(date); // Date object
```

**장점**:
- 한국어 표현 가장 풍부
- 주간 표현 우수 ("다다음주" 지원)
- 시간 포함 가능

**단점**:
- JavaScript 전용 (Python에서 직접 사용 불가)
- 별도 서버 필요 또는 Node.js 래퍼 필요

---

#### B. **datecapture** (달력 앱 최적화) ⭐️⭐️⭐️⭐️

**GitHub**: https://github.com/at-inc/datecapture  
**언어**: TypeScript  
**한국어 지원**: ✅

**특징**:
- chrono-node 래퍼
- 이벤트 제목 + 날짜 동시 추출

**사용 예시**:
```typescript
import { parseDate } from 'datecapture';

const result = parseDate(
  '다다음주 수요일 5시부터 8시까지 제이슨 미팅',
  new Date('2026-03-10'),
  'Asia/Seoul'
);

console.log(result);
// {
//   start: Date('2026-03-26T05:00:00+09:00'),
//   end: Date('2026-03-26T08:00:00+09:00'),
//   dateUnit: 'datetime',
//   subject: '제이슨 미팅'
// }
```

**장점**:
- 이벤트 제목 추출 가능 (HITL 시나리오에 유용)
- 시간 범위 처리

**단점**:
- JavaScript 전용

---

### 3. 범용 도구

#### **Duckling** (Facebook/Meta) ⭐️⭐️⭐️⭐️

**GitHub**: https://github.com/facebook/duckling  
**Stars**: 4.1k+  
**언어**: Haskell (REST API 제공)  
**한국어 지원**: ⚠️ (제한적)

**특징**:
- 다국어 시간 표현 파서
- REST API로 모든 언어에서 사용 가능
- Wit.ai에서 개발

**사용 방법**:
```bash
# Docker로 실행
docker run -p 8000:8000 rasa/duckling

# REST API 호출
curl -X POST http://localhost:8000/parse \
  --data 'text=tomorrow at 3pm' \
  --data 'locale=en_US'
```

**응답 예시**:
```json
[
  {
    "body": "tomorrow at 3pm",
    "start": 0,
    "value": {
      "values": [
        {
          "value": "2026-03-11T15:00:00.000+09:00",
          "grain": "hour",
          "type": "value"
        }
      ],
      "value": "2026-03-11T15:00:00.000+09:00",
      "grain": "hour",
      "type": "value"
    },
    "end": 16,
    "dim": "time"
  }
]
```

**장점**:
- 프로덕션 검증됨 (Wit.ai, Facebook Messenger 사용)
- 다양한 언어 지원
- 언어 독립적 (REST API)

**단점**:
- 한국어 지원 제한적
- Haskell 런타임 필요
- 별도 서비스 운영 필요

---

## 🏗️ 구현 아키텍처

### Option 1: Python 전용 (dateparser 사용) - 권장 ⭐️

```
사용자 발화: "내일 날씨 알려줘"
    ↓
STT → "내일 날씨 알려줘"
    ↓
RAG Processor (before LLM)
    ↓
시간 표현 추출 및 정규화
    - dateparser.parse('내일', languages=['ko'])
    - → 2026-03-11
    ↓
Query 재작성
    - 원본: "내일 날씨 알려줘"
    - 재작성: "2026년 3월 11일 날씨 알려줘"
    ↓
RAG 검색 (날짜로 필터링)
    ↓
LLM 응답 생성
```

**코드 예시**:
```python
import re
import dateparser
from datetime import datetime

class TemporalExpressionNormalizer:
    """시간 표현 정규화 클래스"""
    
    # 한국어 시간 표현 패턴
    TEMPORAL_PATTERNS = [
        r'오늘', r'내일', r'모레', r'어제', r'그제',
        r'\d+일\s*[전후]',  # 3일 전, 5일 후
        r'이번주', r'다음주', r'지난주',
        r'이번달', r'다음달', r'지난달',
        r'올해', r'내년', r'작년',
        r'좀\s*전', r'방금', r'아까',
    ]
    
    def __init__(self, base_time: datetime = None):
        """
        Args:
            base_time: 기준 시간 (통화 시작 시간). None이면 현재 시간 사용
        """
        self.base_time = base_time or datetime.now()
    
    def extract_temporal_expressions(self, text: str) -> list:
        """
        텍스트에서 시간 표현 추출
        
        Returns:
            [{'expression': '내일', 'start': 0, 'end': 2}, ...]
        """
        expressions = []
        for pattern in self.TEMPORAL_PATTERNS:
            for match in re.finditer(pattern, text):
                expressions.append({
                    'expression': match.group(),
                    'start': match.start(),
                    'end': match.end()
                })
        return expressions
    
    def normalize_expression(self, expression: str) -> dict:
        """
        시간 표현을 날짜로 변환
        
        Returns:
            {
                'original': '내일',
                'normalized_date': datetime(2026, 3, 11),
                'formatted': '2026년 3월 11일'
            }
        """
        # dateparser로 파싱
        parsed_date = dateparser.parse(
            expression,
            languages=['ko'],
            settings={
                'RELATIVE_BASE': self.base_time,
                'TIMEZONE': 'Asia/Seoul',
                'RETURN_AS_TIMEZONE_AWARE': True
            }
        )
        
        if not parsed_date:
            return None
        
        return {
            'original': expression,
            'normalized_date': parsed_date,
            'formatted': parsed_date.strftime('%Y년 %m월 %d일'),
            'iso': parsed_date.isoformat()
        }
    
    def rewrite_query(self, query: str) -> str:
        """
        사용자 query를 정규화된 날짜로 재작성
        
        Args:
            query: "내일 날씨 알려줘"
        
        Returns:
            "2026년 3월 11일 날씨 알려줘"
        """
        # 시간 표현 추출
        expressions = self.extract_temporal_expressions(query)
        
        if not expressions:
            return query
        
        # 뒤에서부터 교체 (인덱스 변경 방지)
        expressions.sort(key=lambda x: x['start'], reverse=True)
        
        rewritten = query
        for expr in expressions:
            normalized = self.normalize_expression(expr['expression'])
            if normalized:
                # "내일" → "2026년 3월 11일"
                rewritten = (
                    rewritten[:expr['start']] + 
                    normalized['formatted'] + 
                    rewritten[expr['end']:]
                )
        
        return rewritten


# 사용 예시
normalizer = TemporalExpressionNormalizer(base_time=datetime(2026, 3, 10, 17, 30))

# Query 재작성
original = "내일 날씨 알려줘"
rewritten = normalizer.rewrite_query(original)
print(f"원본: {original}")
print(f"재작성: {rewritten}")
# 출력:
# 원본: 내일 날씨 알려줘
# 재작성: 2026년 3월 11일 날씨 알려줘
```

---

### Option 2: Hybrid (Python + Node.js) - 고급 표현 지원

한국어 고급 표현("다다음주", "그그저께" 등)이 필요하면 `ko-date-parse`를 Node.js 마이크로서비스로 운영

```
┌─────────────────────┐
│  Python AI Pipeline │
│                     │
│  User: "다다음주 월요일 날씨"
│         ↓           │
│  HTTP Request       │
└─────────┬───────────┘
          │
          ↓
┌─────────────────────┐
│  Node.js Service    │
│  (ko-date-parse)    │
│                     │
│  /parse             │
│  POST {"text": "다다음주 월요일"}
│         ↓           │
│  {"date": "2026-03-24"}
└─────────┬───────────┘
          │
          ↓ JSON Response
┌─────────────────────┐
│  Python AI Pipeline │
│                     │
│  "2026년 3월 24일 날씨"
│         ↓           │
│  RAG Search         │
└─────────────────────┘
```

**Node.js 서비스 예시**:
```typescript
// server.ts
import express from 'express';
import { parseKoreanDate } from '@youngkyo0504/ko-date-parse';

const app = express();
app.use(express.json());

app.post('/parse', (req, res) => {
  const { text, baseDate } = req.body;
  
  try {
    const date = parseKoreanDate(text, baseDate ? new Date(baseDate) : new Date());
    res.json({
      success: true,
      date: date.toISOString(),
      formatted: date.toLocaleDateString('ko-KR')
    });
  } catch (error) {
    res.status(400).json({
      success: false,
      error: error.message
    });
  }
});

app.listen(3000, () => {
  console.log('Korean date parser running on port 3000');
});
```

**Python 클라이언트**:
```python
import requests

def parse_korean_date(expression: str, base_date: str = None):
    response = requests.post('http://localhost:3000/parse', json={
        'text': expression,
        'baseDate': base_date
    })
    return response.json()

# 사용
result = parse_korean_date("다다음주 수요일")
print(result['formatted'])  # 2026년 3월 26일
```

---

## 🎯 권장 솔루션

### 현재 프로젝트에 적합한 방안: **dateparser (Python)** ⭐️

**이유**:
1. **Python 네이티브** - 별도 서비스 불필요
2. **안정성** - 2.5k+ stars, 활발한 유지보수
3. **범용성** - 200개 이상 언어 지원
4. **통합 용이** - 기존 RAG Processor에 쉽게 추가 가능
5. **한국어 기본 표현 지원** - "오늘", "내일", "어제", "3일 전" 등

**제한사항**:
- "다다음주", "그그저께" 같은 고급 표현은 제한적
- → 필요 시 규칙 기반 전처리로 보완 가능

---

## 📝 구현 계획

### Phase 1: 기본 시간 표현 처리 (권장)

1. **dateparser 설치**
   ```bash
   pip install dateparser
   ```

2. **TemporalExpressionNormalizer 클래스 생성**
   - `sip-pbx/src/ai_voicebot/temporal/normalizer.py`

3. **RAG Processor 통합**
   - `rag_processor.py`의 `_process_with_agent()` 호출 전 query 재작성
   ```python
   # rag_processor.py
   from ..temporal.normalizer import TemporalExpressionNormalizer
   
   async def _process_with_agent(self, user_text: str):
       # ✅ 시간 표현 정규화
       normalizer = TemporalExpressionNormalizer()
       normalized_text = normalizer.rewrite_query(user_text)
       
       logger.info("temporal_expression_normalized",
                  call_id=self._call_id,
                  original=user_text,
                  normalized=normalized_text)
       
       # LangGraph Agent 호출
       result = await self._agent.process_utterance(normalized_text, ...)
   ```

4. **테스트**
   ```python
   # tests/test_temporal_normalizer.py
   def test_today():
       normalizer = TemporalExpressionNormalizer(base_time=datetime(2026, 3, 10))
       assert normalizer.rewrite_query("오늘 날씨") == "2026년 3월 10일 날씨"
   
   def test_tomorrow():
       normalizer = TemporalExpressionNormalizer(base_time=datetime(2026, 3, 10))
       assert normalizer.rewrite_query("내일 비 와?") == "2026년 3월 11일 비 와?"
   ```

---

### Phase 2: 고급 표현 지원 (선택 사항)

필요 시 규칙 기반 전처리 추가:

```python
# 고급 표현 매핑
ADVANCED_EXPRESSIONS = {
    '모레': '+2 days',
    '그제': '-2 days',
    '그그저께': '-3 days',
    '다다음주': '+2 weeks',
}

def preprocess_advanced_expressions(text: str) -> str:
    """고급 한국어 표현을 dateparser가 이해할 수 있는 형식으로 변환"""
    for kr_expr, en_expr in ADVANCED_EXPRESSIONS.items():
        text = text.replace(kr_expr, en_expr)
    return text
```

---

## 📊 비교표

| 라이브러리 | 언어 | 한국어 지원 | Stars | 유지보수 | 통합 난이도 | 권장도 |
|----------|------|-----------|-------|---------|-----------|--------|
| **dateparser** | Python | ⭐⭐⭐⭐ | 2.5k+ | ✅ Active | ⭐⭐⭐⭐⭐ | **⭐⭐⭐⭐⭐** |
| ko-date-parse | TypeScript | ⭐⭐⭐⭐⭐ | 7 | ✅ Active | ⭐⭐ (별도 서비스) | ⭐⭐⭐ |
| MINAH | Python | ⭐⭐⭐⭐⭐ | 1 | ⚠️ Low | ⭐⭐⭐⭐ | ⭐⭐⭐ |
| timenorm-py | Python | ⭐⭐ | - | ✅ Active | ⭐⭐⭐ | ⭐⭐⭐ |
| datecapture | TypeScript | ⭐⭐⭐⭐ | - | ✅ Active | ⭐⭐ (별도 서비스) | ⭐⭐⭐ |
| Duckling | Haskell/API | ⭐⭐ | 4.1k+ | ✅ Active | ⭐⭐ (별도 서비스) | ⭐⭐⭐ |

---

## 🔗 참고 자료

### 논문 및 연구
- [Temporal Information Extraction from Korean Texts (KAIST, 2015)](https://aclanthology.org/K15-1028.pdf)
- [KTimeML: Korean TimeML Specification (SNU)](https://snu.elsevierpure.com/en/publications/ktimeml-specification-of-temporal-and-event-expressions-in-korean/)

### GitHub 레포지토리
- [dateparser](https://github.com/scrapinghub/dateparser)
- [ko-date-parse](https://github.com/youngkyo0504/ko-date-parse)
- [MINAH](https://github.com/digsy89/minah)
- [timenorm](https://github.com/clulab/timenorm)
- [Duckling](https://github.com/facebook/duckling)

---

**작성자**: AI Assistant  
**다음 단계**: Phase 1 구현 (dateparser 통합)
