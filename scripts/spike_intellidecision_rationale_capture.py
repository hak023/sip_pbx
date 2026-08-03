"""
Story 1.20 스파이크: IntelliDecision 판단 근거 캡처 방식 3개 후보를 실제 Gemini API로 검증한다.
프로덕션 코드는 건드리지 않는 독립 스크립트(scripts/spike_google_genai_thinking_off.py와 동일 관례).

관련 문서:
- docs/architecture/self-service-ai-assistant-architecture.md "IntelliDecision 판단 근거 투명성 설계"
- docs/stories/1.20.intellidecision-rationale-capture-spike.story.md

사용법:
    $env:GEMINI_API_KEY = "<key>"   # 또는 C:\\work\\gemini-api-key.json 에서 자동 로드
    python scripts/spike_intellidecision_rationale_capture.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

try:
    from google import genai
    from google.genai import types
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


API_KEY = _load_api_key()
MODEL = "gemini-2.5-flash"  # config.yaml의 gemini.model과 동일
client = genai.Client(api_key=API_KEY)

# self_service_agent.py의 실제 유형 코드(A~I) 중 대표 3개만 스파이크 대상으로 사용
INTENT_TYPES = "A(탐색성)/B(실행성)/C(포괄적 도움요청)/D(정정)/E(Undo)/F(모호성해소)/G(일괄처리)/H(반복요청)/I(범위외설명)"

TEST_UTTERANCES = [
    ("탐색성(A)", "AI가 모르는 질문 받으면 나한테 전화하게 해줄 수 있어?"),
    ("실행성(B)", "채팅 자동응답 꺼줘"),
    ("도움요청(C)", "뭘 할 수 있어?"),
]

SIMPLE_TOOL = {
    "name": "update_self_service_setting",
    "description": "테넌트 설정 값을 변경한다.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "domain": {"type": "STRING"},
            "field": {"type": "STRING"},
            "value": {"type": "STRING"},
        },
        "required": ["domain", "field", "value"],
    },
}


def _now() -> float:
    return time.time()


# ---------------------------------------------------------------------------
# 후보 (a) 구조화 출력(response_schema) + Tool 동시 요청
# ---------------------------------------------------------------------------

def spike_a_structured_output_with_tools():
    print("\n" + "=" * 70)
    print("후보 (a) 구조화 출력(response_schema) + FunctionCall 동시 요청 가능 여부")
    print("=" * 70)

    rationale_schema = {
        "type": "OBJECT",
        "properties": {
            "matched_type": {"type": "STRING", "enum": list("ABCDEFGHI")},
            "reasoning_summary": {"type": "STRING"},
        },
        "required": ["matched_type", "reasoning_summary"],
    }

    for label, utterance in TEST_UTTERANCES:
        print(f"\n--- 발화: [{label}] '{utterance}' ---")
        # 1) tools + response_schema를 같은 config에 동시 지정 시도
        try:
            tool = types.Tool(function_declarations=[types.FunctionDeclaration(**{
                "name": SIMPLE_TOOL["name"],
                "description": SIMPLE_TOOL["description"],
                "parameters": SIMPLE_TOOL["parameters"],
            })])
            config = types.GenerateContentConfig(
                tools=[tool],
                response_mime_type="application/json",
                response_schema=rationale_schema,
                temperature=0.2,
            )
            start = _now()
            resp = client.models.generate_content(
                model=MODEL,
                contents=(
                    f"유형: {INTENT_TYPES}\n"
                    f"사용자 발화: '{utterance}'\n"
                    "이 발화가 어떤 유형인지 matched_type/reasoning_summary로만 답하라. "
                    "설정 변경이 필요하면 update_self_service_setting을 호출할 수도 있다."
                ),
                config=config,
            )
            elapsed = _now() - start
            print(f"[결과] 소요 {elapsed:.2f}s")
            print(f"  candidates finish_reason: {[getattr(c, 'finish_reason', None) for c in (resp.candidates or [])]}")
            print(f"  text: {getattr(resp, 'text', None)!r}")
        except Exception as e:  # noqa: BLE001 - 스파이크 스크립트는 실제 예외 메시지 자체가 결과 데이터
            print(f"[예외 발생] {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# 후보 (b) 센티널 태그 후행 파싱
# ---------------------------------------------------------------------------

SENTINEL_PROMPT_SUFFIX = (
    "\n\n답변을 마친 뒤 반드시 새 줄에 다음 형식의 센티널 태그를 정확히 한 번 추가하라: "
    "<<INTELLIDECISION:{{\"matched_type\":\"A~I 중 하나\",\"reasoning_summary\":\"10~30자 요약\"}}>>"
)


def _extract_sentinel(text: str):
    import re
    m = re.search(r"<<INTELLIDECISION:(\{.*?\})>>", text, re.DOTALL)
    if not m:
        return None, text
    raw = m.group(1)
    cleaned = text[: m.start()].rstrip()
    try:
        return json.loads(raw), cleaned
    except json.JSONDecodeError:
        return "PARSE_ERROR", cleaned


def spike_b_sentinel_tag(n_repeats: int = 5):
    print("\n" + "=" * 70)
    print(f"후보 (b) 센티널 태그 후행 파싱 — 발화당 {n_repeats}회 반복")
    print("=" * 70)

    total = 0
    success = 0
    leaked = 0
    for label, utterance in TEST_UTTERANCES:
        for i in range(n_repeats):
            total += 1
            prompt = (
                f"당신은 셀프서비스 AI 도우미다. 사용자 발화: '{utterance}'\n"
                "친절하게 한두 문장으로 답하라." + SENTINEL_PROMPT_SUFFIX
            )
            try:
                config = types.GenerateContentConfig(temperature=0.5, max_output_tokens=300)
                resp = client.models.generate_content(model=MODEL, contents=prompt, config=config)
                text = getattr(resp, "text", "") or ""
                parsed, cleaned = _extract_sentinel(text)
                ok = isinstance(parsed, dict)
                if ok:
                    success += 1
                else:
                    print(f"  [실패:{label} #{i+1}] parsed={parsed!r} raw={text[:120]!r}")
                # 사용자 노출 시나리오: 정제 실패 시 원본 태그가 그대로 노출되는지 확인
                if "<<INTELLIDECISION" in cleaned:
                    leaked += 1
                    print(f"  [태그 유출!:{label} #{i+1}] cleaned={cleaned[:150]!r}")
            except Exception as e:  # noqa: BLE001
                print(f"  [예외:{label} #{i+1}] {type(e).__name__}: {e}")

    print(f"\n[요약] 총 {total}회, 파싱 성공 {success}회({success/total:.0%}), 태그 유출 {leaked}회")


# ---------------------------------------------------------------------------
# 후보 (c) 경량 별도 분류 호출(응답 생성 이후 추가 왕복)
# ---------------------------------------------------------------------------

def spike_c_separate_call():
    print("\n" + "=" * 70)
    print("후보 (c) 경량 별도 분류 호출 — 추가 왕복 지연 실측")
    print("=" * 70)

    for label, utterance in TEST_UTTERANCES:
        # 1) 정상 응답 생성(기존 흐름 시뮬레이션)
        start = _now()
        resp1 = client.models.generate_content(
            model=MODEL,
            contents=f"사용자 발화: '{utterance}'\n한두 문장으로 답하라.",
            config=types.GenerateContentConfig(temperature=0.5, max_output_tokens=200),
        )
        t_response = _now() - start
        answer_text = getattr(resp1, "text", "") or ""

        # 2) 별도 분류 호출(추가 왕복)
        start2 = _now()
        resp2 = client.models.generate_content(
            model=MODEL,
            contents=(
                f"유형: {INTENT_TYPES}\n사용자 발화: '{utterance}'\nAI 응답: '{answer_text}'\n"
                "이 상호작용의 유형 코드 1글자만 답하라."
            ),
            config=types.GenerateContentConfig(temperature=0.0, max_output_tokens=10),
        )
        t_classify = _now() - start2

        print(f"\n--- 발화: [{label}] '{utterance}' ---")
        print(f"  1차 응답 생성: {t_response:.2f}s, 텍스트: {answer_text[:60]!r}")
        print(f"  2차 분류 호출(추가): {t_classify:.2f}s, 결과: {getattr(resp2, 'text', None)!r}")
        print(f"  => 이 방식의 순수 추가 지연: {t_classify:.2f}s (전체 대비 {t_classify/(t_response+t_classify):.0%})")


if __name__ == "__main__":
    print(f"모델: {MODEL}")
    spike_a_structured_output_with_tools()
    spike_b_sentinel_tag(n_repeats=5)
    spike_c_separate_call()
