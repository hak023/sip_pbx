"""
AI 모델 사전 다운로드 스크립트

HuggingFace에서 필요한 AI 모델을 미리 다운로드하여
서버 시작 시간을 단축합니다.

사용법:
    python scripts/download_models.py
"""

import os
import sys
import time
from pathlib import Path

# 프로젝트 루트를 PYTHONPATH에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# SSL 검증 비활성화 (개발 환경용)
os.environ['CURL_CA_BUNDLE'] = ''
os.environ['REQUESTS_CA_BUNDLE'] = ''
os.environ['SSL_CERT_FILE'] = ''
os.environ['TOKENIZERS_PARALLELISM'] = 'false'
import ssl
ssl._create_default_https_context = ssl._create_unverified_context

# HuggingFace 로그 비활성화
os.environ['HF_HUB_DISABLE_PROGRESS_BARS'] = '0'  # 진행 표시줄은 보이게
os.environ['TRANSFORMERS_VERBOSITY'] = 'info'

print(f"""
{'='*70}
🤖 AI 모델 다운로드 시작
{'='*70}

이 스크립트는 다음 모델을 다운로드합니다:

1. 📚 sentence-transformers (텍스트 임베딩)
   - 모델: paraphrase-multilingual-mpnet-base-v2
   - 크기: 약 1.1GB
   - 용도: 텍스트를 벡터로 변환하여 의미 기반 검색 가능
   
⏱️  첫 다운로드는 네트워크 속도에 따라 1-5분 소요될 수 있습니다.
다운로드 후에는 서버 시작 시간이 80초 → 5초로 단축됩니다!

{'='*70}
""")

input("계속하려면 Enter를 누르세요... (Ctrl+C로 취소)")

try:
    print("\n[1/1] 📥 sentence-transformers 다운로드 중...\n")
    start_time = time.time()
    
    from sentence_transformers import SentenceTransformer
    
    model_name = "paraphrase-multilingual-mpnet-base-v2"
    print(f"모델명: {model_name}")
    
    # 모델 다운로드 및 로드
    model = SentenceTransformer(model_name)
    
    elapsed = time.time() - start_time
    
    # 간단한 테스트
    print("\n[테스트] 모델이 정상적으로 작동하는지 확인 중...")
    test_text = "안녕하세요"
    embedding = model.encode(test_text)
    
    print(f"""
{'='*70}
✅ 다운로드 완료!
{'='*70}

  ⏱️  소요 시간: {elapsed:.2f}초
  📦 모델 차원: {len(embedding)}
  ✅ 테스트: 성공
  
💾 모델 캐시 위치:
  {model.model_card_data.model_id if hasattr(model, 'model_card_data') else '~/.cache/huggingface/'}

{'='*70}

🎉 준비 완료! 이제 서버를 시작하면 빠르게 로딩됩니다.

  서버 시작 예상 시간:
  - 이전: 약 80-90초
  - 현재: 약 5-10초 (75초 단축!)

{'='*70}
""")

except KeyboardInterrupt:
    print("\n\n⚠️  다운로드가 취소되었습니다.")
    sys.exit(1)
except Exception as e:
    print(f"""
{'='*70}
❌ 오류 발생
{'='*70}

  {str(e)}
  
해결 방법:
  1. 인터넷 연결 확인
  2. 방화벽 설정 확인
  3. SSL 인증서 문제인 경우, 위 코드의 SSL 비활성화 부분 확인

{'='*70}
""")
    sys.exit(1)
