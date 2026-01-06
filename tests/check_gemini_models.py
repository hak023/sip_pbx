"""
Gemini 사용 가능한 모델 목록 확인

현재 API 키로 사용 가능한 Gemini 모델 이름을 확인합니다.
"""

import os
import sys
import google.generativeai as genai
from pathlib import Path

# UTF-8 인코딩 설정 (Windows 호환)
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

def load_api_key():
    """config.yaml 또는 환경 변수에서 API 키 로드"""
    # 1. config.yaml에서 로드 시도
    try:
        import yaml
        config_path = Path(__file__).parent.parent / "config" / "config.yaml"
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        gemini_config = config.get("ai_voicebot", {}).get("google_cloud", {}).get("gemini", {})
        api_key = gemini_config.get("api_key")
        
        if api_key and api_key != "your-api-key-here":
            print(f"[OK] API 키 로드: config.yaml (키: {api_key[:20]}...)")
            return api_key
    except Exception as e:
        print(f"[INFO] config.yaml 로드 실패: {e}")
    
    # 2. 환경 변수에서 로드
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if api_key:
        print(f"[OK] API 키 로드: 환경 변수 (키: {api_key[:20]}...)")
        return api_key
    
    print("[ERROR] API 키를 찾을 수 없습니다!")
    return None


def main():
    print("="*80)
    print("  Gemini 사용 가능한 모델 목록 확인")
    print("="*80)
    print()
    
    # API 키 로드
    api_key = load_api_key()
    if not api_key:
        print("\n[FAIL] API 키 설정 필요")
        print("  - config.yaml의 ai_voicebot.google_cloud.gemini.api_key")
        print("  - 또는 GEMINI_API_KEY 환경 변수")
        return
    
    # Gemini API 설정
    try:
        genai.configure(api_key=api_key)
        print("[OK] Gemini API 설정 완료\n")
    except Exception as e:
        print(f"[ERROR] API 설정 실패: {e}")
        return
    
    # 사용 가능한 모델 목록 조회
    print("-"*80)
    print("  사용 가능한 Gemini 모델 목록:")
    print("-"*80)
    
    try:
        models = genai.list_models()
        
        gemini_models = []
        for model in models:
            # Gemini 모델만 필터링
            if 'gemini' in model.name.lower():
                gemini_models.append(model)
                print(f"\n모델 이름: {model.name}")
                print(f"  - 표시 이름: {model.display_name}")
                print(f"  - 설명: {model.description[:100]}..." if len(model.description) > 100 else f"  - 설명: {model.description}")
                
                # 지원 메서드 확인
                if hasattr(model, 'supported_generation_methods'):
                    methods = model.supported_generation_methods
                    print(f"  - 지원 메서드: {', '.join(methods)}")
                
                # 입력/출력 토큰 제한
                if hasattr(model, 'input_token_limit'):
                    print(f"  - 입력 토큰 제한: {model.input_token_limit:,}")
                if hasattr(model, 'output_token_limit'):
                    print(f"  - 출력 토큰 제한: {model.output_token_limit:,}")
        
        print("\n" + "="*80)
        print(f"  총 {len(gemini_models)}개의 Gemini 모델 발견")
        print("="*80)
        
        # 권장 모델
        print("\n추천 모델:")
        for model in gemini_models:
            name = model.name
            if 'flash' in name.lower() and '2.0' in name:
                print(f"  [최신] {name} <- Gemini 2.0 Flash (최고 성능)")
            elif 'flash' in name.lower() and '1.5' in name:
                print(f"  [추천] {name} <- Gemini 1.5 Flash (빠르고 저렴)")
            elif 'pro' in name.lower() and '1.5' in name:
                print(f"  [고성능] {name} <- Gemini 1.5 Pro (높은 품질)")
        
        # 테스트
        print("\n" + "="*80)
        print("  모델 테스트")
        print("="*80)
        
        test_models = [m.name for m in gemini_models if 'flash' in m.name.lower()][:2]
        
        for model_name in test_models:
            try:
                print(f"\n[테스트] {model_name}")
                model = genai.GenerativeModel(model_name)
                response = model.generate_content("안녕하세요. 1문장으로 짧게 답변해주세요.")
                print(f"  [OK] 응답: {response.text[:100]}...")
            except Exception as e:
                print(f"  [FAIL] 오류: {e}")
        
    except Exception as e:
        print(f"[ERROR] 모델 목록 조회 실패: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()

