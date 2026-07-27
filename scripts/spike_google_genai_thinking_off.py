"""
스파이크 검증: google-genai SDK(v1.75.0)로 thinking_budget=0이 실제로 TTFT를
줄이는지 확인한다. 프로덕션 코드는 건드리지 않는 독립 스크립트.

관련 리포트: docs/reports/2026-07/2026-07-24_root_cause_gemini_thinking_not_actually_disabled.md

사용법:
    $env:GEMINI_API_KEY = "<key>"   # 이미 설정돼 있으면 생략 가능
    python scripts/spike_google_genai_thinking_off.py
"""
import os
import time
import sys

try:
    from google import genai
    from google.genai import types
except ImportError:
    print("google-genai 패키지가 설치되어 있지 않습니다. `pip install google-genai`로 설치하세요.")
    sys.exit(1)

API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
if not API_KEY:
    print("GEMINI_API_KEY 또는 GOOGLE_API_KEY 환경변수가 설정되어 있지 않습니다.")
    sys.exit(1)

MODEL = "gemini-2.5-flash"
PROMPT = "안녕하세요! 오늘 날씨가 참 좋네요."  # chitchat 예시 (실제 QA 하네스와 유사한 짧은 발화)

client = genai.Client(api_key=API_KEY)


def run(label: str, thinking_budget: int | None):
    config_kwargs = {
        "temperature": 0.5,
        "top_p": 1.0,
        "top_k": 1,
        "max_output_tokens": 512,
    }
    if thinking_budget is not None:
        config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=thinking_budget)

    config = types.GenerateContentConfig(**config_kwargs)

    start = time.time()
    first_chunk_time = None
    text_parts = []
    for chunk in client.models.generate_content_stream(
        model=MODEL,
        contents=PROMPT,
        config=config,
    ):
        if first_chunk_time is None:
            first_chunk_time = time.time()
        if chunk.text:
            text_parts.append(chunk.text)
    end = time.time()

    ttft = (first_chunk_time - start) if first_chunk_time else None
    total = end - start
    print(f"\n=== {label} ===")
    print(f"TTFT: {ttft:.3f}s" if ttft is not None else "TTFT: N/A(첫 청크 없음)")
    print(f"전체 소요: {total:.3f}s")
    print(f"응답: {''.join(text_parts)[:200]}")


if __name__ == "__main__":
    print(f"모델: {MODEL}, google-genai 버전 확인 중...")
    try:
        import google.genai as _g
        print(f"google-genai module loaded: {_g.__file__}")
    except Exception:
        pass

    run("thinking_budget 미지정 (기존 google-generativeai와 동일 상황 = auto thinking)", None)
    run("thinking_budget=0 (신규 SDK로 명시적 비활성화)", 0)
