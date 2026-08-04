"""
Story 1.29 스파이크: Contextual Retrieval(Anthropic 방식) 도입 여부 실측.
프로덕션 코드는 건드리지 않는 독립 스크립트(scripts/spike_intellidecision_rationale_capture.py와 동일 관례).

관련 문서:
- docs/design/SELF_SERVICE_RAG_INTELLIDECISION_ADVANCEMENT_RESEARCH.md §3.1
- docs/stories/1.29.contextual-retrieval-adoption-spike.story.md

측정 방법(§AC1~AC3):
  1. ChromaDB `knowledge` 컬렉션에서 doc_type=self_service_manual(매뉴얼 Q&A) 청크를 owner 스코프로
     직접 조회한다(서버 프로세스 기동 없이 chromadb_client.get_vector_db()를 그대로 재사용).
  2. 각 청크에 대해 Gemini로 "맥락 요약 프리픽스"를 생성한다(Anthropic Contextual Retrieval 프롬프트
     패턴 축약판) — 토큰 수·지연을 실측한다.
  3. 청크 자신의 질문(question)을 쿼리로 사용하는 self-retrieval 벤치마크로, baseline(원문 임베딩)과
     contextual(프리픽스+원문 임베딩)의 top-1/top-3 히트율을 비교한다(로컬 SentenceTransformer 임베딩,
     비용 없음).
  4. 순수 파이썬으로 최소 구현한 BM25(외부 의존성 추가 없이, 저장소 관례상 새 패키지는 실측 후
     "채택" 결론일 때만 requirements에 추가)로 키워드 검색 히트율도 함께 비교한다.

사용법:
    $env:GEMINI_API_KEY = "<key>"   # 또는 C:\\work\\gemini-api-key.json 에서 자동 로드
    python scripts/spike_contextual_retrieval.py [--owner 9001] [--sample N]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from google import genai
except ImportError:
    print("google-genai 패키지가 설치되어 있지 않습니다. `pip install google-genai`로 설치하세요.")
    sys.exit(1)


def _load_api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if key:
        return key
    key_file = Path(r"C:\work\gemini-api-key.json")
    if key_file.exists():
        data = json.loads(key_file.read_text(encoding="utf-8"))
        key = data.get("gemini_api_key")
        if key:
            return key
    print("GEMINI_API_KEY를 환경변수 또는 C:\\work\\gemini-api-key.json에서 찾을 수 없습니다.")
    sys.exit(1)


MODEL = "gemini-2.5-flash"

_CONTEXT_PROMPT_TEMPLATE = (
    "다음은 지식베이스 문서(질문+답변) 한 조각(청크)이다. 이 청크가 검색될 때 함께 붙일, "
    "이 청크의 주제·범위를 명확히 하는 1문장짜리 한국어 맥락 요약을 생성하라. "
    "청크 내용을 반복하지 말고, 어떤 도메인·상황에 대한 내용인지만 간결히 설명하라.\n\n"
    "[섹션]: {section_title}\n[청크]:\n{chunk_text}\n\n"
    "맥락 요약(1문장, 다른 설명 없이 요약 문장만 출력):"
)


def _cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


_TOKEN_RE = re.compile(r"[\w가-힣]+")


def _tokenize(text: str) -> List[str]:
    return _TOKEN_RE.findall((text or "").lower())


class SimpleBM25:
    """외부 의존성 없는 최소 BM25(k1=1.5, b=0.75) — 스파이크 실측 전용, 프로덕션 미사용."""

    def __init__(self, corpus_tokens: List[List[str]], *, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.corpus = corpus_tokens
        self.doc_len = [len(d) for d in corpus_tokens]
        self.avgdl = sum(self.doc_len) / len(self.doc_len) if corpus_tokens else 0.0
        self.doc_freqs: List[Counter] = [Counter(d) for d in corpus_tokens]
        df: Counter = Counter()
        for d in corpus_tokens:
            for term in set(d):
                df[term] += 1
        n = len(corpus_tokens)
        self.idf: Dict[str, float] = {
            term: math.log(1 + (n - freq + 0.5) / (freq + 0.5)) for term, freq in df.items()
        }

    def scores(self, query_tokens: List[str]) -> List[float]:
        scores = [0.0] * len(self.corpus)
        for i, freqs in enumerate(self.doc_freqs):
            dl = self.doc_len[i] or 1
            for term in query_tokens:
                if term not in freqs:
                    continue
                idf = self.idf.get(term, 0.0)
                f = freqs[term]
                denom = f + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1))
                scores[i] += idf * (f * (self.k1 + 1)) / (denom or 1)
        return scores


def _fetch_manual_chunks(owner: str) -> List[Dict[str, Any]]:
    from src.ai_voicebot.knowledge.chromadb_client import get_vector_db
    from src.ai_voicebot.self_service.manual_indexer import SELF_SERVICE_MANUAL_DOC_TYPE

    vector_db = get_vector_db()
    if vector_db is None:
        print("ChromaDB에 연결할 수 없습니다(data/chroma 확인).")
        sys.exit(1)

    # 주의: 이 로컬 ChromaDB 설치본은 다중 조건 $and where에서 "row value misused" 오류를
    # 낸다(스파이크 실측 중 발견, 프로덕션 코드 `knowledge_service.list_knowledge()`와 무관한
    # 로컬 SQLite 백엔드 이슈) — doc_type 단일 조건으로만 조회한 뒤 owner는 파이썬에서 필터링한다.
    res = vector_db.get(where={"doc_type": SELF_SERVICE_MANUAL_DOC_TYPE}, limit=2000)
    ids_all = res.get("ids") or []
    docs_all = res.get("documents") or []
    metas_all = res.get("metadatas") or []
    ids, docs, metas = [], [], []
    for doc_id, text, meta in zip(ids_all, docs_all, metas_all):
        if (meta or {}).get("owner") == owner:
            ids.append(doc_id)
            docs.append(text)
            metas.append(meta)

    chunks = []
    for doc_id, text, meta in zip(ids, docs, metas):
        m = re.match(r"^Q:\s*(.*?)\s*\nA:\s*(.*)$", text or "", re.DOTALL)
        question = m.group(1).strip() if m else (text or "")[:80]
        chunks.append({
            "doc_id": doc_id, "text": text or "", "question": question,
            "section_title": (meta or {}).get("section_title", ""),
        })
    return chunks


def _generate_context(client: Any, chunk: Dict[str, Any]) -> Tuple[str, float, int]:
    prompt = _CONTEXT_PROMPT_TEMPLATE.format(
        section_title=chunk.get("section_title") or "(미분류)", chunk_text=chunk["text"],
    )
    start = time.time()
    resp = client.models.generate_content(model=MODEL, contents=prompt)
    elapsed = time.time() - start
    text = (getattr(resp, "text", None) or "").strip()
    approx_tokens = len(prompt) // 4 + len(text) // 4  # 대략치(정확한 usage_metadata는 아래서 별도 사용)
    usage = getattr(resp, "usage_metadata", None)
    if usage is not None:
        approx_tokens = int(getattr(usage, "total_token_count", approx_tokens) or approx_tokens)
    return text, elapsed, approx_tokens


def _embed_all(embedder: Any, texts: List[str]) -> List[List[float]]:
    return [embedder.embed_text(t) for t in texts]


def _hit_at_k(rank_order: List[int], target_idx: int, k: int) -> bool:
    return target_idx in rank_order[:k]


def run(owner: str, sample: Optional[int]) -> Dict[str, Any]:
    from src.ai_voicebot.knowledge.embedder import TextEmbedder

    print(f"[1/5] ChromaDB에서 owner={owner} self_service_manual 청크 조회 중...")
    chunks = _fetch_manual_chunks(owner)
    if sample:
        chunks = chunks[:sample]
    n = len(chunks)
    print(f"      -> {n}건 확보")
    if n < 3:
        print("청크가 너무 적어 유의미한 실측이 불가능합니다. 다른 owner를 지정하세요(--owner).")
        sys.exit(1)

    api_key = _load_api_key()
    client = genai.Client(api_key=api_key)

    print(f"[2/5] 청크 {n}건에 대해 Gemini로 맥락 요약 프리픽스 생성 중(비용·지연 실측)...")
    contexts: List[str] = []
    total_tokens = 0
    total_latency = 0.0
    for i, chunk in enumerate(chunks):
        ctx, elapsed, tokens = _generate_context(client, chunk)
        contexts.append(ctx)
        total_tokens += tokens
        total_latency += elapsed
        if (i + 1) % 10 == 0 or i == n - 1:
            print(f"      {i + 1}/{n} 완료 (누적 {total_latency:.1f}s, {total_tokens} tokens)")

    print("[3/5] 로컬 임베더로 baseline/contextual 임베딩 생성 중(비용 없음, SentenceTransformer)...")
    embedder = TextEmbedder()
    baseline_texts = [c["text"] for c in chunks]
    contextual_texts = [f"{ctx}\n\n{c['text']}" for ctx, c in zip(contexts, chunks)]
    baseline_emb = _embed_all(embedder, baseline_texts)
    contextual_emb = _embed_all(embedder, contextual_texts)
    query_emb = _embed_all(embedder, [c["question"] for c in chunks])

    print("[4/5] self-retrieval 벤치마크(각 청크의 question으로 자기 자신을 top-K에서 찾는지) 계산 중...")
    baseline_hit1 = baseline_hit3 = contextual_hit1 = contextual_hit3 = 0
    for i in range(n):
        q = query_emb[i]

        base_scores = [(_cosine(q, baseline_emb[j]), j) for j in range(n)]
        base_scores.sort(key=lambda x: x[0], reverse=True)
        base_rank = [j for _, j in base_scores]
        if _hit_at_k(base_rank, i, 1):
            baseline_hit1 += 1
        if _hit_at_k(base_rank, i, 3):
            baseline_hit3 += 1

        ctx_scores = [(_cosine(q, contextual_emb[j]), j) for j in range(n)]
        ctx_scores.sort(key=lambda x: x[0], reverse=True)
        ctx_rank = [j for _, j in ctx_scores]
        if _hit_at_k(ctx_rank, i, 1):
            contextual_hit1 += 1
        if _hit_at_k(ctx_rank, i, 3):
            contextual_hit3 += 1

    print("[5/5] BM25(키워드 검색) 벤치마크 계산 중...")
    corpus_tokens = [_tokenize(t) for t in baseline_texts]
    bm25 = SimpleBM25(corpus_tokens)
    bm25_hit1 = bm25_hit3 = 0
    for i in range(n):
        q_tokens = _tokenize(chunks[i]["question"])
        scores = bm25.scores(q_tokens)
        rank = sorted(range(n), key=lambda j: scores[j], reverse=True)
        if _hit_at_k(rank, i, 1):
            bm25_hit1 += 1
        if _hit_at_k(rank, i, 3):
            bm25_hit3 += 1

    result = {
        "owner": owner, "n_chunks": n,
        "cost": {
            "total_llm_calls": n, "total_tokens_approx": total_tokens,
            "total_latency_sec": round(total_latency, 2),
            "avg_latency_sec_per_chunk": round(total_latency / n, 3),
        },
        "retrieval_quality": {
            "baseline_vector": {
                "hit@1": round(baseline_hit1 / n, 4), "hit@3": round(baseline_hit3 / n, 4),
            },
            "contextual_vector": {
                "hit@1": round(contextual_hit1 / n, 4), "hit@3": round(contextual_hit3 / n, 4),
            },
            "bm25_keyword": {
                "hit@1": round(bm25_hit1 / n, 4), "hit@3": round(bm25_hit3 / n, 4),
            },
        },
        "sample_contexts": [
            {"section_title": c["section_title"], "question": c["question"][:60], "context": ctx}
            for c, ctx in list(zip(chunks, contexts))[:5]
        ],
    }
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", default="9001")
    parser.add_argument("--sample", type=int, default=None, help="처리할 청크 수 제한(비용 절감용)")
    parser.add_argument("--out", default=None, help="결과 JSON 저장 경로")
    args = parser.parse_args()

    result = run(args.owner, args.sample)
    print("\n" + "=" * 70)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    out_path = Path(args.out) if args.out else _PROJECT_ROOT / "data" / "spikes" / "contextual_retrieval_spike_result.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n결과 저장: {out_path}")
