# 🎮 GPU 가속 설정 가이드

SIP PBX의 AI 기능(텍스트 임베딩)에서 GPU를 사용하여 **5-10배 속도 향상**을 얻을 수 있습니다.

---

## 📊 GPU vs CPU 성능 비교

| 작업 | CPU | GPU (CUDA) | 속도 향상 |
|------|-----|-----------|---------|
| 단일 텍스트 임베딩 | 50-100ms | **10-20ms** | **5배** |
| 배치 임베딩 (32개) | 800-1500ms | **150-300ms** | **5-10배** |
| 모델 로딩 | 0.5초 | 0.8초 | 약간 느림 |

**결론**: GPU는 **실시간 처리와 배치 처리에서 엄청난 성능 향상** 제공!

---

## 🔍 GPU 사용 가능 여부 확인

### 1. NVIDIA GPU 확인

**Windows**:
```powershell
# NVIDIA 제어판에서 확인
# 또는 장치 관리자 → 디스플레이 어댑터

# GPU 정보 확인
nvidia-smi
```

**Linux**:
```bash
lspci | grep -i nvidia
nvidia-smi
```

### 2. CUDA 지원 GPU 확인

**지원 GPU 목록**: https://developer.nvidia.com/cuda-gpus

**최소 요구사항**:
- NVIDIA GPU (GTX 900 시리즈 이상, RTX 시리즈, Tesla, Quadro 등)
- CUDA Compute Capability 3.5 이상

---

## 🚀 GPU 설치 방법

### Step 1: NVIDIA 드라이버 설치

**Windows**:
1. https://www.nvidia.com/drivers 방문
2. GPU 모델 선택 및 드라이버 다운로드
3. 설치 후 재부팅

**Linux (Ubuntu/Debian)**:
```bash
# 드라이버 자동 설치
sudo apt update
sudo apt install nvidia-driver-535  # 또는 최신 버전

# 재부팅
sudo reboot

# 확인
nvidia-smi
```

---

### Step 2: CUDA Toolkit 설치 (선택)

**필수 아님!** PyTorch에 CUDA가 포함되어 있습니다.

만약 수동 설치를 원한다면:
- https://developer.nvidia.com/cuda-downloads
- CUDA 11.8 또는 12.1 버전 설치

---

### Step 3: PyTorch CUDA 버전 설치

**현재 프로젝트 디렉토리로 이동**:
```powershell
cd C:\work\workspace_sippbx\sip-pbx
```

**가상 환경 활성화**:
```powershell
.\venv\Scripts\Activate.ps1  # Windows
# source venv/bin/activate    # Linux/Mac
```

**기존 PyTorch 제거 및 CUDA 버전 설치**:
```powershell
# 1. 기존 CPU 버전 제거
pip uninstall torch torchvision torchaudio -y

# 2. CUDA 버전 설치 (CUDA 11.8)
pip install torch==2.1.2 torchvision==0.16.2 torchaudio==2.1.2 --index-url https://download.pytorch.org/whl/cu118

# 또는 CUDA 12.1
# pip install torch==2.1.2 torchvision==0.16.2 torchaudio==2.1.2 --index-url https://download.pytorch.org/whl/cu121
```

---

### Step 4: GPU 동작 확인

**Python에서 확인**:
```python
import torch

print(f"CUDA available: {torch.cuda.is_available()}")
print(f"CUDA version: {torch.version.cuda}")
print(f"GPU count: {torch.cuda.device_count()}")
print(f"GPU name: {torch.cuda.get_device_name(0)}")
```

**예상 출력**:
```
CUDA available: True
CUDA version: 11.8
GPU count: 1
GPU name: NVIDIA GeForce RTX 3060
```

---

## 🎯 서버에서 GPU 사용 확인

### 1. 서버 시작

```powershell
cd C:\work\workspace_sippbx\sip-pbx
python src\main.py
```

### 2. 로그 확인

**GPU 사용 중**:
```json
{
  "event": "🎮 [GPU] CUDA available! Using GPU acceleration",
  "device": "cuda",
  "gpu_name": "NVIDIA GeForce RTX 3060",
  "gpu_memory_gb": "12.00GB",
  "level": "info"
}

{
  "event": "✅ [GPU] Model loaded on GPU",
  "model": "paraphrase-multilingual-mpnet-base-v2",
  "device": "cuda",
  "level": "info"
}
```

**CPU 사용 중** (GPU 없거나 CUDA 미설치):
```json
{
  "event": "💻 [CPU] CUDA not available, using CPU",
  "device": "cpu",
  "level": "info"
}
```

---

## 🔧 트러블슈팅

### 문제 1: "CUDA out of memory"

**원인**: GPU 메모리 부족

**해결**:
```python
# config.yaml에서 배치 크기 줄이기
google_cloud:
  embedding:
    batch_size: 16  # 기본 32 → 16으로 감소
```

---

### 문제 2: "torch.cuda.is_available() returns False"

**원인**: CUDA PyTorch가 아닌 CPU 버전 설치됨

**해결**:
```powershell
# 재설치
pip uninstall torch -y
pip install torch==2.1.2 --index-url https://download.pytorch.org/whl/cu118
```

---

### 문제 3: "nvidia-smi: command not found"

**원인**: NVIDIA 드라이버 미설치

**해결**: Step 1의 드라이버 설치 가이드 참고

---

### 문제 4: 드라이버 버전 불일치

**확인**:
```powershell
nvidia-smi
# Driver Version: 537.42   CUDA Version: 12.2
```

**CUDA 11.8 필요 시**:
- Driver Version 520 이상 필요
- 드라이버가 오래되었다면 업데이트

---

## 📈 성능 모니터링

### GPU 사용률 확인

**실시간 모니터링**:
```powershell
# 1초마다 갱신
nvidia-smi -l 1
```

### API로 통계 확인

```bash
# AI Voicebot 통계 확인
curl http://localhost:8000/api/stats/embedder

# 예상 응답
{
  "device": "cuda",
  "gpu_name": "NVIDIA GeForce RTX 3060",
  "gpu_memory_allocated_mb": 245.5,
  "gpu_memory_total_gb": 12.0,
  "total_embeddings": 1523
}
```

---

## 💡 추천 GPU

### 개발/테스트용
- **NVIDIA GTX 1660 Super** (6GB VRAM) - 약 30만원
- **NVIDIA RTX 3060** (12GB VRAM) - 약 40만원

### 프로덕션용
- **NVIDIA RTX 4060 Ti** (16GB VRAM) - 약 70만원
- **NVIDIA RTX 4090** (24GB VRAM) - 약 250만원
- **NVIDIA A100** (40GB/80GB VRAM) - 클라우드 추천

### 클라우드 옵션
- **AWS EC2 G4dn** (NVIDIA T4, 16GB VRAM)
- **Google Cloud Platform** (NVIDIA T4/V100/A100)
- **Azure NC 시리즈** (NVIDIA V100)

---

## ❓ FAQ

### Q1: GPU가 꼭 필요한가요?
**A**: 아니요. CPU만으로도 작동합니다. 하지만 **대량 처리나 실시간 응답**이 필요하면 GPU를 강력 추천합니다.

### Q2: 노트북 GPU도 가능한가요?
**A**: 네! NVIDIA GPU가 있는 노트북(GTX/RTX 시리즈)이면 모두 가능합니다.

### Q3: AMD GPU는 안되나요?
**A**: 현재는 NVIDIA CUDA만 지원합니다. AMD ROCm 지원은 향후 추가 예정입니다.

### Q4: 여러 GPU가 있으면?
**A**: 기본적으로 GPU 0번을 사용합니다. 다른 GPU를 사용하려면:
```python
# config.yaml
google_cloud:
  embedding:
    device: "cuda:1"  # GPU 1번 사용
```

---

## 📚 참고 문서

- PyTorch CUDA 설치: https://pytorch.org/get-started/locally/
- NVIDIA CUDA Toolkit: https://developer.nvidia.com/cuda-toolkit
- Sentence Transformers: https://www.sbert.net/

---

**🎉 GPU 설정 완료!** 이제 AI 기능이 **5-10배 빨라집니다!**
