# KB URL 기반 실시간 정보 조회 Tool 설계

| 항목 | 내용 |
|---|---|
| 작성일 | 2026-04-09 |
| 상태 | 설계 완료 |
| 관련 리서치 | GitHub: ScrapeGraphAI/langchain-scrapegraph, mbeacom/genai-processors-url-fetch, LangChain Agentic RAG, DEV.to 웹 스크래핑 파이프라인 |
| 관련 파일 | `src/ai_voicebot/langgraph/tools/booking_tools.py` (`search_knowledge_tool`) |

---

## 1. 문제 정의 및 기획 배경

### 현재 상황

```
고객: "오늘 파스타 메뉴 있나요?"
  → classify_intent → booking_agent (search_knowledge_tool 호출)
  → ChromaDB RAG 검색 → KB에 등록된 정적 텍스트 반환
  → 응답: "봉골레 17,000원, 까르보나라 18,000원 ..."
```

**한계**: KB에 등록된 시점의 정보만 반환. 오늘의 특선 메뉴, 재고 변경, 실시간 가격 등 **동적으로 변하는 정보**를 반영하지 못함.

### 기획 아이디어

KB의 `faq` 카테고리에 다음과 같이 URL을 포함하여 등록:

```
메뉴 정보: http://www.aaa.com?menu=today
영업시간 확인: https://example.com/hours
오늘의 특선: https://restaurant.com/api/specials
```

→ **RAG 검색 시 URL이 감지되면**, 해당 URL을 실시간으로 가져와서 텍스트를 추출하고, 그 내용을 기반으로 LLM이 답변.

---

## 2. 리서치 결과

### GitHub 오픈소스

| 프로젝트 | 방식 | 특징 |
|---|---|---|
| `ScrapeGraphAI/langchain-scrapegraph` | 외부 API | `MarkdownifyTool(url)` → Markdown 텍스트 반환. API Key 필요 |
| `mbeacom/genai-processors-url-fetch` | httpx + BeautifulSoup/markitdown | 구글 Gemini 프로세서용. 보안 설정(allowed_domains, HTTPS only) 포함 |
| LangChain `WebBaseLoader` | httpx | `loader.load(url)` → Document 객체. 청킹·임베딩 가능 |
| LangChain Agentic RAG | `@tool fetch_url` | `requests.get(url)` + `markdownify()` → 20줄 구현 |
| DEV.to 파이프라인 가이드 | httpx + BeautifulSoup | `<nav><header><footer>` 제거 → 토큰 10~50배 절감 |

### 핵심 패턴 3가지

**패턴 1: 즉시 fetch (Agentic RAG)**
```
RAG 검색 → URL 포함 문서 감지 → fetch_url Tool 호출 → LLM이 실시간 내용으로 답변
```

**패턴 2: 주기적 재인덱싱 (Scheduled Re-index)**
```
스케줄러(cron) → URL 접속 → 변경 감지(해시) → 변경 시만 ChromaDB 재임베딩
```

**패턴 3: 캐시 TTL (Cache with TTL)**
```
첫 요청 → URL fetch → 내용 캐시(TTL: 5~60분) → 동일 URL 재요청 시 캐시 반환
```

### 토큰 비용 비교

| 방식 | 페이지당 토큰 | 비고 |
|---|---|---|
| 원시 HTML 전달 | ~25,000 | 사용 불가 |
| Full Markdown | ~3,000 | 보통 |
| 텍스트 추출 (노이즈 제거) | ~500~1,500 | **권장** |
| 구조화 JSON 추출 | ~200~800 | 특정 필드만 필요 시 |

---

## 3. 설계 — URL Fetch Tool 아키텍처

### 전체 흐름

```
고객 발화: "오늘 파스타 메뉴 뭐예요?"
  │
  ▼
[booking_agent_node]
  │
  ▼
LLM → search_knowledge_tool(query="오늘 메뉴", category="faq") 호출
  │
  ▼
[search_knowledge_tool — 기존 로직]
  ChromaDB 검색 → 상위 문서 반환
  문서 내용 예시: "오늘의 메뉴: http://restaurant.com?menu=today"
  │
  ▼
[URL 감지] ← ★ 신규 로직
  문서에서 http(s):// URL 추출
  │
  ├─ URL 없음 → 기존 방식 그대로 snippets 반환
  │
  └─ URL 있음 → fetch_url_content(url) 호출
                  │
                  ├─ 캐시 히트(TTL 이내) → 캐시된 내용 반환
                  │
                  └─ 캐시 미스 → httpx.get(url, timeout=5s)
                                  BeautifulSoup → 노이즈 제거 → 텍스트 추출
                                  markdownify → Markdown 변환 (선택)
                                  결과 캐시 저장 (TTL: 10분)
                                  │
                                  ▼
                  최종 반환: {
                    "found": true,
                    "source": "url_fetch",
                    "url": "http://...",
                    "content": "오늘의 특선: 봉골레 17,000원 ...",
                    "fetched_at": "2026-04-09 14:23",
                    "cache_hit": false
                  }
  │
  ▼
LLM: "오늘 메뉴는 봉골레 17,000원, 까르보나라 18,000원이 있습니다."
```

---

## 4. 세부 설계

### 4-1. KB 등록 방식 (운영자 입력 포맷)

KB에 다음 형태로 등록. **기존 text 필드 그대로 활용** — 별도 스키마 변경 불필요.

```
# 형식 1: URL만 포함 (전체 페이지 텍스트 사용)
오늘의 메뉴: http://restaurant.com/api/menu?date=today

# 형식 2: 설명 + URL (RAG 검색 정확도 향상)
매일 오전 업데이트되는 당일 메뉴 목록입니다.
최신 메뉴 정보: https://restaurant.com/today-menu

# 형식 3: 여러 URL (하나씩 시도)
점심 메뉴: https://example.com/lunch
저녁 메뉴: https://example.com/dinner
```

**Why 기존 text 필드 활용?**
- KB 스키마(ChromaDB metadata) 변경 불필요
- 기존 `add_knowledge` API 그대로 사용
- RAG 벡터 검색이 URL 포함 문서를 키워드로 찾아줌 ("메뉴", "오늘" 등)

---

### 4-2. URL 감지 로직

```python
import re

URL_PATTERN = re.compile(
    r'https?://[^\s\"\'\)\]\}]{10,}',
    re.IGNORECASE
)

def extract_urls_from_text(text: str) -> list[str]:
    """KB 문서 텍스트에서 URL 추출."""
    return URL_PATTERN.findall(text)
```

---

### 4-3. fetch_url_content 함수 (핵심 구현)

```python
# src/services/url_fetch_service.py

import hashlib
import time
import re
from typing import Optional

import httpx
import structlog

logger = structlog.get_logger(__name__)

# 메모리 캐시 {url_hash: (content, fetched_at_ts)}
_URL_CACHE: dict[str, tuple[str, float]] = {}
_CACHE_TTL_SEC = 600  # 10분 기본값 (환경변수로 조정 가능)

# 허용 스킴·보안
_ALLOWED_SCHEMES = {"http", "https"}
# 사내 IP / localhost 차단 (SSRF 방지)
_BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}

# 노이즈 제거 대상 HTML 태그
_NOISE_TAGS = ["nav", "header", "footer", "script", "style",
               "noscript", "aside", "advertisement", ".ad"]

# 콘텐츠 추출 우선순위 CSS 셀렉터
_CONTENT_SELECTORS = [
    "article", "main", "[role='main']",
    ".post-content", ".article-body", ".entry-content",
    "#content", "#main", "body",
]

def fetch_url_content(
    url: str,
    max_chars: int = 2000,
    ttl_sec: int = _CACHE_TTL_SEC,
) -> dict:
    """
    URL에서 텍스트 콘텐츠를 가져와 LLM용으로 정제 반환.

    Args:
        url: 가져올 URL (http/https만 허용)
        max_chars: 최대 반환 문자 수 (토큰 제한)
        ttl_sec: 캐시 TTL (초)

    Returns:
        {
          "success": bool,
          "content": str,
          "url": str,
          "fetched_at": str (ISO),
          "cache_hit": bool,
          "error": str (실패 시)
        }
    """
    from urllib.parse import urlparse
    parsed = urlparse(url)

    # 보안 검증
    if parsed.scheme not in _ALLOWED_SCHEMES:
        return {"success": False, "url": url, "error": f"허용되지 않은 스킴: {parsed.scheme}"}
    if parsed.hostname in _BLOCKED_HOSTS:
        return {"success": False, "url": url, "error": "내부 주소 접근 차단"}

    # 캐시 확인
    url_hash = hashlib.md5(url.encode()).hexdigest()
    now = time.time()
    if url_hash in _URL_CACHE:
        cached_content, cached_ts = _URL_CACHE[url_hash]
        if now - cached_ts < ttl_sec:
            logger.info("url_fetch_cache_hit", url=url, age_sec=int(now - cached_ts))
            return {
                "success": True,
                "content": cached_content,
                "url": url,
                "fetched_at": _ts_to_str(cached_ts),
                "cache_hit": True,
            }

    # 실제 Fetch
    try:
        with httpx.Client(timeout=5.0, follow_redirects=True) as client:
            resp = client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; SipPBX-Bot/1.0)",
                "Accept": "text/html,application/xhtml+xml,text/plain",
            })
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")

            if "text/html" in content_type or "application/xhtml" in content_type:
                text = _extract_text_from_html(resp.text)
            elif "application/json" in content_type:
                text = _extract_text_from_json(resp.text)
            else:
                # plain text, markdown 등
                text = resp.text.strip()

        # 길이 제한
        if len(text) > max_chars:
            text = text[:max_chars] + "..."

        # 캐시 저장
        _URL_CACHE[url_hash] = (text, now)

        logger.info("url_fetch_success", url=url, content_len=len(text))
        return {
            "success": True,
            "content": text,
            "url": url,
            "fetched_at": _ts_to_str(now),
            "cache_hit": False,
        }

    except httpx.TimeoutException:
        logger.warning("url_fetch_timeout", url=url)
        return {"success": False, "url": url, "error": "요청 시간 초과 (5초)"}
    except Exception as e:
        logger.error("url_fetch_error", url=url, error=str(e))
        return {"success": False, "url": url, "error": str(e)}


def _extract_text_from_html(html: str) -> str:
    """HTML에서 메인 콘텐츠 텍스트 추출 (노이즈 제거)."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")

        # 노이즈 태그 제거
        for tag in soup(_NOISE_TAGS):
            tag.decompose()

        # 메인 콘텐츠 영역 선택
        for selector in _CONTENT_SELECTORS:
            el = soup.select_one(selector)
            if el:
                return " ".join(el.get_text(separator="\n", strip=True).split())

        return " ".join(soup.get_text(separator="\n", strip=True).split())
    except ImportError:
        # bs4 미설치 시 간단 태그 제거
        return re.sub(r"<[^>]+>", " ", html).strip()


def _extract_text_from_json(json_text: str) -> str:
    """JSON 응답에서 텍스트 값들을 추출."""
    import json
    try:
        data = json.loads(json_text)
        return _flatten_json_values(data)[:2000]
    except Exception:
        return json_text[:2000]


def _flatten_json_values(obj, depth: int = 0) -> str:
    """JSON 객체에서 문자열 값을 재귀 추출."""
    if depth > 5:
        return ""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, list):
        return " | ".join(_flatten_json_values(v, depth+1) for v in obj[:20])
    if isinstance(obj, dict):
        return " ".join(
            f"{k}: {_flatten_json_values(v, depth+1)}"
            for k, v in list(obj.items())[:30]
        )
    return str(obj)


def _ts_to_str(ts: float) -> str:
    from datetime import datetime
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
```

---

### 4-4. search_knowledge_tool 수정 — URL 자동 감지 및 fetch 연계

기존 `search_knowledge_tool` 내부에 **URL 감지 → fetch 체인**을 추가합니다.

```python
# booking_tools.py의 _search_knowledge 함수 내부 수정 (snippets 구성 후)

# ── URL 포함 문서 감지 및 실시간 fetch ──
from src.services.url_fetch_service import fetch_url_content, extract_urls_from_text

url_fetched_results = []
for snippet in snippets:
    urls = extract_urls_from_text(snippet)
    for url in urls[:2]:  # 문서당 최대 2개 URL
        fetch_result = fetch_url_content(url, max_chars=1500)
        if fetch_result["success"]:
            url_fetched_results.append({
                "url": url,
                "content": fetch_result["content"],
                "fetched_at": fetch_result["fetched_at"],
                "cache_hit": fetch_result["cache_hit"],
            })
            logger.info(
                "search_knowledge_url_fetched",
                url=url,
                cache_hit=fetch_result["cache_hit"],
                content_len=len(fetch_result["content"]),
            )

# URL fetch 결과가 있으면 snippets보다 우선 반환
if url_fetched_results:
    return json.dumps({
        "found": True,
        "query": query,
        "category": category or "all",
        "source": "url_fetch",
        "url_results": url_fetched_results,
        "snippets": snippets,  # KB 원본도 함께 제공
    }, ensure_ascii=False)
```

---

## 5. 보안 설계

| 위협 | 대응 방법 |
|---|---|
| SSRF (내부 IP 접근) | `_BLOCKED_HOSTS` 차단, `allow_schemes=https only` 옵션 |
| 악의적 URL 등록 | KB 등록 시 URL 화이트리스트 도메인 검증 (선택) |
| 대용량 응답 (토큰 폭발) | `max_chars=2000` 하드 제한, `max_response_size=5MB` |
| 느린 응답 (통화 지연) | `timeout=5.0초` 하드 제한, 초과 시 KB 원본 텍스트로 폴백 |
| JS 렌더링 필요 페이지 | httpx는 정적 HTML만 처리, JS 필요 시 Playwright 추가 (향후) |

### 허용 도메인 화이트리스트 (선택 설정)

```python
# config/config.yaml 또는 booking_settings에 추가
url_fetch:
  allowed_domains:
    - "restaurant.com"
    - "example.com"
  https_only: false  # true로 설정 시 HTTPS URL만 허용
  timeout_sec: 5
  cache_ttl_sec: 600
  max_content_chars: 2000
```

---

## 6. 캐싱 전략

| 캐시 레이어 | 위치 | TTL | 목적 |
|---|---|---|---|
| URL 결과 캐시 | 프로세스 메모리 (`_URL_CACHE`) | 10분 | 동일 URL 반복 호출 차단 |
| (향후) Redis 캐시 | 외부 | 5~30분 | 멀티 프로세스 공유 |
| ChromaDB 임베딩 | 영속 | 영구 | KB 텍스트는 계속 저장 |

**TTL 권장값**:
- 실시간성 높은 메뉴·재고: **5분**
- 일반 안내·영업시간: **60분**
- 변경 빈도 낮은 정책·FAQ: **24시간**

---

## 7. 구현 범위 및 파일

| 파일 | 변경 유형 | 내용 |
|---|---|---|
| `src/services/url_fetch_service.py` | **신규** | URL fetch + 텍스트 추출 + 캐시 서비스 |
| `src/ai_voicebot/langgraph/tools/booking_tools.py` | 수정 | `_search_knowledge` 내부에 URL 감지 + fetch 연계 |
| `requirements.txt` | 수정 | `beautifulsoup4`, `lxml`, `markdownify` 추가 (httpx는 이미 설치) |

---

## 8. KB 등록 가이드 (운영자용)

```
[등록 예시 — 레스토랑 오늘의 메뉴]
카테고리: faq
텍스트:
오늘의 메뉴와 특선은 매일 업데이트됩니다.
최신 메뉴 정보: http://restaurant.com/api/today-menu

[등록 예시 — 재고 있는 상품 목록]
카테고리: faq
텍스트:
현재 재고 있는 상품 목록은 아래 링크에서 실시간 확인 가능합니다.
재고 현황: https://shop.example.com/stock?format=text

[등록 예시 — 영업시간 (API JSON)]
카테고리: faq
텍스트:
영업시간은 공휴일 등으로 변경될 수 있습니다.
최신 영업시간: https://example.com/api/hours
```

**URL 서버 권장 포맷** (최적 응답):
```
# 권장: 순수 텍스트 또는 간단한 HTML
오늘의 메뉴 (2026-04-09)
- 봉골레 파스타 17,000원
- 까르보나라 18,000원
- 오늘의 특선: 트러플 리조또 23,000원 (한정 10인분)
```

---

## 9. 대화 흐름 예시 (구현 후)

```
[시나리오 1: 오늘 메뉴 URL]
고객: "오늘 파스타 메뉴 있나요?"

search_knowledge_tool:
  → ChromaDB 검색: "오늘 메뉴 정보: http://restaurant.com?menu=today"
  → URL 감지: http://restaurant.com?menu=today
  → fetch_url_content() → "봉골레 17,000 / 까르보나라 18,000 / 트러플 리조또 23,000"
  → cache_hit: false, fetched_at: 2026-04-09 14:23

LLM 응답: "오늘 파스타 메뉴는 봉골레 17,000원, 까르보나라 18,000원, 
           그리고 오늘의 특선으로 트러플 리조또 23,000원이 있습니다."

---

[시나리오 2: URL fetch 실패 → KB 폴백]
고객: "오늘 메뉴 알려주세요"

search_knowledge_tool:
  → URL fetch 시도 → timeout (5초 초과)
  → 폴백: KB 텍스트 원본 반환 ("메뉴는 매일 변경됩니다. 자세한 내용은...")

LLM 응답: "메뉴는 매일 변경되는데, 지금 확인이 어려운 상황입니다. 
           직접 문의하시거나 잠시 후 다시 확인해주시겠어요?"

---

[시나리오 3: JSON API 응답]
URL: https://api.restaurant.com/menu → {"specials":[{"name":"트러플 리조또","price":23000}]}
fetch 결과: "specials: name: 트러플 리조또 | price: 23000"
LLM: "오늘의 특선은 트러플 리조또로 23,000원입니다."
```

---

## 10. 구현 단계 (권장 순서)

| 단계 | 작업 | 예상 시간 |
|---|---|---|
| 1 | `src/services/url_fetch_service.py` 신규 구현 (httpx + bs4) | 2시간 |
| 2 | `booking_tools.py`의 `_search_knowledge`에 URL 감지 + fetch 연계 | 1시간 |
| 3 | `requirements.txt`에 `beautifulsoup4`, `lxml` 추가 | 10분 |
| 4 | KB에 URL 포함 테스트 문서 등록 → 통화 시뮬레이션 | 30분 |
| 5 | (선택) 도메인 화이트리스트·HTTPS Only 설정 | 1시간 |
| 6 | (선택) Redis 캐시로 업그레이드 | 2시간 |

**합계: 최소 3.5시간 (핵심 기능), 전체 6~8시간**

---

## 11. 외부 라이브러리 대안 비교

| 옵션 | 장점 | 단점 | 권장 여부 |
|---|---|---|---|
| **httpx + BeautifulSoup** (권장) | 의존성 최소, 빠름, 이미 httpx 설치됨 | JS 렌더링 불가 | ✅ **권장** |
| `langchain_community.WebBaseLoader` | LangChain 생태계 통합 | 의존성 증가, 청킹 필요 | 선택적 |
| `ScrapeGraphAI/langchain-scrapegraph` | AI 기반 구조화 추출 | 외부 API Key 필요, 비용 발생 | ❌ (외부 의존) |
| `markdownify` | HTML → Markdown 고품질 변환 | 추가 설치 필요 | 선택적 추가 |
| Playwright | JS 렌더링 완벽 지원 | 무거움, 헤드리스 브라우저 | 향후 필요 시 |
