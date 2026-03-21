"""
1004 테넌트(기상청) 지식베이스 예제 시드 — API 호출 방식.
백엔드(API 서버)가 떠 있고 ChromaDB·임베더가 준비된 상태에서 실행하면,
서버의 임베더로 지식을 추가합니다.

실행 (API 서버 기동 후, AI Voicebot 준비 완료 권장):
  python scripts/seed_knowledge_1004_via_api.py
  python scripts/seed_knowledge_1004_via_api.py http://localhost:8000

데이터: scripts/knowledge_seed_1004_weather.json (동일 디렉터리)
"""
import sys
import urllib.request
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SEED_JSON = SCRIPT_DIR / "knowledge_seed_1004_weather.json"


def load_examples():
    if SEED_JSON.exists():
        with open(SEED_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    # 인라인 폴백
    return [
        {"text": "기상청은 대한민국 기상 예보와 기후 정보를 제공하는 국가 기관입니다. 날씨 예보, 기상 특보, 기후 통계 등을 담당합니다.", "category": "소개", "keywords": ["기상청", "날씨", "예보", "기후"]},
        {"text": "오늘 날씨 예보는 전국 대체로 맑고, 낮 최고 기온은 서울 12도, 부산 14도, 대구 13도입니다. 미세먼지는 보통 수준입니다.", "category": "일기예보", "keywords": ["날씨", "예보", "기온", "미세먼지"]},
        {"text": "주말 날씨는 토요일은 맑다가 일요일 오후부터 서해안과 중부 지방에 비 또는 눈이 올 수 있습니다. 기온은 평년과 비슷합니다.", "category": "일기예보", "keywords": ["주말", "날씨", "비", "눈", "기온"]},
        {"text": "기상 특보는 호우, 강풍, 한파, 폭염, 대설 등으로 나뉩니다. 특보가 발령되면 기상청 홈페이지와 앱에서 상세 내용을 확인할 수 있습니다.", "category": "기상특보", "keywords": ["기상특보", "호우", "강풍", "한파", "폭염", "대설"]},
        {"text": "미세먼지 예보는 좋음, 보통, 나쁨, 매우 나쁨 네 단계입니다. 나쁨 이상일 때는 외출을 줄이고 창문을 닫는 것이 좋습니다.", "category": "미세먼지", "keywords": ["미세먼지", "예보", "초미세먼지", "대기질"]},
        {"text": "기상청 날씨 예보는 3시간 단위로 업데이트됩니다. 단기 예보는 3일, 중기 예보는 10일까지 제공됩니다.", "category": "예보안내", "keywords": ["예보", "단기", "중기", "업데이트"]},
        {"text": "한파 특보는 아침 최저 기온이 영하 12도 이하로 3일 이상 지속될 때, 또는 24시간 내 10도 이상 급강하할 때 발령됩니다.", "category": "기상특보", "keywords": ["한파", "특보", "기온", "최저기온"]},
        {"text": "여름철 폭염 특보는 일 최고 기온이 33도 이상일 때 주의보, 35도 이상일 때 경보가 발령됩니다. 충분한 수분 섭취와 그늘 이용을 권장합니다.", "category": "기상특보", "keywords": ["폭염", "특보", "기온", "주의보", "경보"]},
        {"text": "기상청 앱과 웹사이트(www.weather.go.kr)에서 전국 상세 예보, 레이더·위성 영상, 기상 캐스트를 무료로 볼 수 있습니다.", "category": "이용안내", "keywords": ["기상청", "앱", "웹사이트", "예보", "레이더"]},
        {"text": "강수 확률 70%는 해당 지역 전체에 비가 올 가능성이 70%라는 뜻이 아니라, 해당 지역의 어떤 지점에서 비가 올 확률이 70%라는 의미입니다.", "category": "예보안내", "keywords": ["강수확률", "비", "예보", "확률"]},
    ]


def post_knowledge(base_url: str, item: dict):
    body = {
        "tenant_id": "1004",
        "text": item["text"],
        "category": item["category"],
        "keywords": item.get("keywords", []),
        "confidence": 0.9,
        "call_id": "",
    }
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/knowledge",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status in (200, 201):
                return True, resp.read().decode("utf-8")
            return False, f"HTTP {resp.status}"
    except Exception as e:
        return False, str(e)


def main():
    base_url = (sys.argv[1] if len(sys.argv) > 1 else None) or "http://localhost:8000"
    examples = load_examples()
    print(f"API: {base_url}, tenant_id: 1004 (기상청), {len(examples)}건")
    added = 0
    for i, ex in enumerate(examples):
        ok, msg = post_knowledge(base_url, ex)
        if ok:
            added += 1
            print(f"  추가 [{added}] {ex['category']}: {ex['text'][:50]}...")
        else:
            print(f"  실패 [{i+1}] {msg}")
    print(f"\n완료: {added}건 추가 (owner=1004, 기상청 예제)")
    return 0 if added > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
