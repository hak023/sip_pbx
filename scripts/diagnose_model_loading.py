"""
임베딩 모델 로딩 진단 스크립트

문제: paraphrase-multilingual-mpnet-base-v2 모델이 20분 이상 로딩 안 됨
목적: 각 단계별로 상세 로그를 남겨 어디서 멈추는지 파악
"""

import os
import sys
import time
from pathlib import Path

# 프로젝트 루트를 PYTHONPATH에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

print("=" * 70)
print("🔍 임베딩 모델 로딩 진단")
print("=" * 70)
print()

# 1단계: 환경 설정
print("[1/7] 🔧 환경 설정 중...")
os.environ['CURL_CA_BUNDLE'] = ''
os.environ['REQUESTS_CA_BUNDLE'] = ''
os.environ['SSL_CERT_FILE'] = ''
os.environ['TOKENIZERS_PARALLELISM'] = 'false'
os.environ['PYTHONHTTPSVERIFY'] = '0'
os.environ['HF_HUB_DISABLE_PROGRESS_BARS'] = '0'  # 진행 표시줄 보이게
os.environ['TRANSFORMERS_VERBOSITY'] = 'info'
print("   ✅ 환경 변수 설정 완료")

# 2단계: SSL 설정
print("\n[2/7] 🔐 SSL 검증 비활성화 중...")
import ssl
ssl._create_default_https_context = ssl._create_unverified_context
print("   ✅ SSL 컨텍스트 변경 완료")

# 3단계: urllib3 경고 비활성화
print("\n[3/7] ⚠️ urllib3 경고 비활성화 중...")
try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    print("   ✅ urllib3 경고 비활성화 완료")
except ImportError:
    print("   ⚠️ urllib3 not found (OK)")

# 4단계: requests 패치
print("\n[4/7] 🔧 requests 세션 패치 중...")
try:
    import requests
    original_request = requests.Session.request
    def patched_request(self, *args, **kwargs):
        kwargs.setdefault('verify', False)
        return original_request(self, *args, **kwargs)
    requests.Session.request = patched_request
    print("   ✅ requests 세션 패치 완료")
except ImportError:
    print("   ⚠️ requests not found (OK)")

# 5단계: 캐시 확인
print("\n[5/7] 📦 모델 캐시 확인 중...")
cache_dir = Path.home() / ".cache" / "huggingface" / "hub" / "models--sentence-transformers--paraphrase-multilingual-mpnet-base-v2"
if cache_dir.exists():
    files = list(cache_dir.rglob("*"))
    size = sum(f.stat().st_size for f in files if f.is_file()) / 1024 / 1024
    print(f"   ✅ 캐시 발견: {cache_dir}")
    print(f"   📊 파일 수: {len(files)}, 크기: {size:.2f} MB")
    
    # snapshots 확인
    snapshots_dir = cache_dir / "snapshots"
    if snapshots_dir.exists():
        snapshots = list(snapshots_dir.iterdir())
        print(f"   📸 스냅샷: {len(snapshots)}개")
        for snap in snapshots:
            if snap.is_dir():
                snap_files = list(snap.iterdir())
                print(f"      - {snap.name}: {len(snap_files)} 파일")
    
    # blobs 확인
    blobs_dir = cache_dir / "blobs"
    if blobs_dir.exists():
        blobs = list(blobs_dir.iterdir())
        print(f"   💾 Blobs: {len(blobs)}개")
else:
    print(f"   ❌ 캐시 없음: {cache_dir}")

# 6단계: GPU 확인
print("\n[6/7] 🎮 GPU 확인 중...")
try:
    import torch
    if torch.cuda.is_available():
        gpu_name = torch.cuda.get_device_name(0)
        gpu_memory = torch.cuda.get_device_properties(0).total_memory / 1024**3
        gpu_allocated = torch.cuda.memory_allocated(0) / 1024**2
        gpu_reserved = torch.cuda.memory_reserved(0) / 1024**2
        print(f"   ✅ CUDA 사용 가능")
        print(f"   🎮 GPU: {gpu_name}")
        print(f"   💾 메모리: {gpu_memory:.2f} GB (할당: {gpu_allocated:.2f} MB, 예약: {gpu_reserved:.2f} MB)")
    else:
        print("   💻 CUDA 사용 불가, CPU 사용")
except Exception as e:
    print(f"   ⚠️ GPU 확인 실패: {e}")

# 7단계: 모델 로딩 (상세 로그)
print("\n[7/7] 🤖 모델 로딩 시작...")
print("   ⏱️ 타임아웃: 5분")
print("   🔄 로딩 중... (Ctrl+C로 중단 가능)\n")

try:
    start_time = time.time()
    
    print("   [Step 1/5] Importing sentence_transformers...")
    from sentence_transformers import SentenceTransformer
    step1_time = time.time() - start_time
    print(f"   ✅ Import 완료 ({step1_time:.2f}초)")
    
    print("\n   [Step 2/5] Creating SentenceTransformer instance...")
    model_name = "paraphrase-multilingual-mpnet-base-v2"
    step2_start = time.time()
    
    # 로딩 진행 상황을 보기 위한 스레드
    import threading
    stop_progress = threading.Event()
    
    def show_progress():
        chars = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
        idx = 0
        while not stop_progress.is_set():
            elapsed = time.time() - step2_start
            print(f"\r   {chars[idx % len(chars)]} 로딩 중... ({elapsed:.1f}초 경과)", end='', flush=True)
            idx += 1
            time.sleep(0.1)
    
    progress_thread = threading.Thread(target=show_progress, daemon=True)
    progress_thread.start()
    
    # 실제 모델 로딩 (use_auth_token deprecated, 제거)
    model = SentenceTransformer(model_name, device='cuda' if torch.cuda.is_available() else 'cpu')
    
    stop_progress.set()
    progress_thread.join()
    
    step2_time = time.time() - step2_start
    print(f"\r   ✅ SentenceTransformer 생성 완료 ({step2_time:.2f}초)                ")
    
    print("\n   [Step 3/5] Testing model encoding...")
    test_start = time.time()
    test_text = "안녕하세요"
    embedding = model.encode(test_text)
    test_time = time.time() - test_start
    print(f"   ✅ 인코딩 테스트 완료 ({test_time:.2f}초)")
    print(f"   📊 임베딩 차원: {len(embedding)}")
    
    print("\n   [Step 4/5] Checking model details...")
    print(f"   📦 모델 ID: {model_name}")
    print(f"   🎯 디바이스: {model.device}")
    print(f"   🧮 Max sequence length: {model.max_seq_length}")
    
    total_time = time.time() - start_time
    print(f"\n   [Step 5/5] ✅ 모든 테스트 완료!")
    print(f"\n{'=' * 70}")
    print(f"✅ 모델 로딩 성공!")
    print(f"{'=' * 70}")
    print(f"\n   ⏱️ 총 소요 시간: {total_time:.2f}초")
    print(f"   - Import: {step1_time:.2f}초")
    print(f"   - 모델 생성: {step2_time:.2f}초")
    print(f"   - 테스트 인코딩: {test_time:.2f}초")
    print(f"\n💡 모델이 정상 작동합니다. 서버를 다시 시작해보세요.")
    
except KeyboardInterrupt:
    elapsed = time.time() - start_time
    print(f"\n\n⚠️ 사용자가 중단했습니다 (경과 시간: {elapsed:.2f}초)")
    print("\n어느 단계에서 중단되었는지 확인해주세요.")
    sys.exit(1)
    
except Exception as e:
    elapsed = time.time() - start_time
    print(f"\n\n❌ 오류 발생!")
    print(f"{'=' * 70}")
    print(f"   오류 타입: {type(e).__name__}")
    print(f"   오류 메시지: {str(e)}")
    print(f"   경과 시간: {elapsed:.2f}초")
    print(f"{'=' * 70}")
    
    import traceback
    print("\n📋 상세 스택 트레이스:")
    traceback.print_exc()
    
    print(f"\n{'=' * 70}")
    print("🔍 문제 해결 방법:")
    print("{'=' * 70}")
    print("\n1. 캐시 삭제 후 재시도:")
    print(f"   Remove-Item '{cache_dir}' -Recurse -Force")
    print(f"   python scripts/download_models.py")
    print("\n2. CPU 모드로 테스트:")
    print("   $env:CUDA_VISIBLE_DEVICES='-1'")
    print("   python scripts/diagnose_model_loading.py")
    print("\n3. 네트워크 확인:")
    print("   Test-NetConnection huggingface.co -Port 443")
    
    sys.exit(1)
