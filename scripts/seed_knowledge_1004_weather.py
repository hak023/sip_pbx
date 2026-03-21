"""
1004 테넌트(기상청) 지식베이스 예제 시드.
ChromaDB에 기상·날씨 관련 예제 지식을 owner=1004 로 추가합니다.

실행 (sip-pbx 디렉터리에서):
  python scripts/seed_knowledge_1004_weather.py
또는
  python -m scripts.seed_knowledge_1004_weather
"""
import sys
from pathlib import Path
from datetime import datetime

# 프로젝트 루트(sip-pbx)를 path에 추가
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

OWNER = "1004"  # 기상청 테넌트

# 기상청 예제 지식 (text, category, keywords)
EXAMPLES = [
    {
        "text": "기상청은 대한민국 기상 예보와 기후 정보를 제공하는 국가 기관입니다. 날씨 예보, 기상 특보, 기후 통계 등을 담당합니다.",
        "category": "소개",
        "keywords": ["기상청", "날씨", "예보", "기후"],
    },
    {
        "text": "오늘 날씨 예보는 전국 대체로 맑고, 낮 최고 기온은 서울 12도, 부산 14도, 대구 13도입니다. 미세먼지는 보통 수준입니다.",
        "category": "일기예보",
        "keywords": ["날씨", "예보", "기온", "미세먼지"],
    },
    {
        "text": "주말 날씨는 토요일은 맑다가 일요일 오후부터 서해안과 중부 지방에 비 또는 눈이 올 수 있습니다. 기온은 평년과 비슷합니다.",
        "category": "일기예보",
        "keywords": ["주말", "날씨", "비", "눈", "기온"],
    },
    {
        "text": "기상 특보는 호우, 강풍, 한파, 폭염, 대설 등으로 나뉩니다. 특보가 발령되면 기상청 홈페이지와 앱에서 상세 내용을 확인할 수 있습니다.",
        "category": "기상특보",
        "keywords": ["기상특보", "호우", "강풍", "한파", "폭염", "대설"],
    },
    {
        "text": "미세먼지 예보는 좋음, 보통, 나쁨, 매우 나쁨 네 단계입니다. 나쁨 이상일 때는 외출을 줄이고 창문을 닫는 것이 좋습니다.",
        "category": "미세먼지",
        "keywords": ["미세먼지", "예보", "초미세먼지", "대기질"],
    },
    {
        "text": "기상청 날씨 예보는 3시간 단위로 업데이트됩니다. 단기 예보는 3일, 중기 예보는 10일까지 제공됩니다.",
        "category": "예보안내",
        "keywords": ["예보", "단기", "중기", "업데이트"],
    },
    {
        "text": "한파 특보는 아침 최저 기온이 영하 12도 이하로 3일 이상 지속될 때, 또는 24시간 내 10도 이상 급강하할 때 발령됩니다.",
        "category": "기상특보",
        "keywords": ["한파", "특보", "기온", "최저기온"],
    },
    {
        "text": "여름철 폭염 특보는 일 최고 기온이 33도 이상일 때 주의보, 35도 이상일 때 경보가 발령됩니다. 충분한 수분 섭취와 그늘 이용을 권장합니다.",
        "category": "기상특보",
        "keywords": ["폭염", "특보", "기온", "주의보", "경보"],
    },
    {
        "text": "기상청 앱과 웹사이트(www.weather.go.kr)에서 전국 상세 예보, 레이더·위성 영상, 기상 캐스트를 무료로 볼 수 있습니다.",
        "category": "이용안내",
        "keywords": ["기상청", "앱", "웹사이트", "예보", "레이더"],
    },
    {
        "text": "강수 확률 70%는 해당 지역 전체에 비가 올 가능성이 70%라는 뜻이 아니라, 해당 지역의 어떤 지점에서 비가 올 확률이 70%라는 의미입니다.",
        "category": "예보안내",
        "keywords": ["강수확률", "비", "예보", "확률"],
    },
]


def _embed_text(embedder, text: str):
    """embedder에서 벡터 추출 (API와 동일 로직)."""
    if not text or not text.strip():
        return None
    if hasattr(embedder, "embed_text"):
        out = embedder.embed_text(text)
        if isinstance(out, list) and out and isinstance(out[0], (int, float)):
            return out
    if hasattr(embedder, "encode"):
        emb = embedder.encode(text, convert_to_numpy=True)
        return emb.tolist()
    return None


def main():
    from src.ai_voicebot.knowledge.chromadb_client import get_vector_db, KNOWLEDGE_COLLECTION
    from src.ai_voicebot.knowledge.embedder import get_text_embedder

    print("ChromaDB 및 임베더 로드 중...")
    vector_db = get_vector_db()
    embedder = get_text_embedder()
    if not vector_db:
        print("오류: ChromaDB를 초기화할 수 없습니다.")
        return 1
    if not embedder:
        print("오류: 텍스트 임베더를 로드할 수 없습니다. (sentence-transformers 등)")
        return 1

    print(f"지식 컬렉션: {KNOWLEDGE_COLLECTION}, owner: {OWNER}")
    added = 0
    for i, ex in enumerate(EXAMPLES):
        text = ex["text"]
        embedding = _embed_text(embedder, text)
        if not embedding:
            print(f"  건너뜀 [{i+1}] 임베딩 실패: {text[:40]}...")
            continue
        doc_id = f"kb_seed_1004_{datetime.now().strftime('%Y%m%d%H%M%S')}_{i}"
        metadata = {
            "owner": OWNER,
            "category": ex["category"],
            "keywords": ",".join(ex["keywords"]) if isinstance(ex["keywords"], list) else ex["keywords"],
            "confidence": 0.9,
            "call_id": "",
            "created_at": datetime.now().isoformat(),
        }
        try:
            vector_db.add(
                ids=[doc_id],
                embeddings=[embedding],
                documents=[text],
                metadatas=[metadata],
            )
            added += 1
            print(f"  추가 [{added}] {ex['category']}: {text[:50]}...")
        except Exception as e:
            print(f"  오류 [{i+1}] {e}")

    print(f"\n완료: {added}건 추가 (owner={OWNER}, 기상청 예제)")
    return 0 if added > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
