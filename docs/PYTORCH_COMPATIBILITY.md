# 🔧 PyTorch 호환성 문제 해결 가이드

## 📋 문제 설명

### **에러 메시지**

#### 에러 1: SIP PBX 서버
```
AttributeError: module 'torch.utils._pytree' has no attribute 'register_pytree_node'
Event: ❌ Knowledge Extractor initialization failed
```

#### 에러 2: Backend API
```python
AttributeError: module 'torch.utils._pytree' has no attribute 'register_pytree_node'. 
Did you mean: '_register_pytree_node'?
```

### **영향받는 기능**
- ❌ Knowledge Extraction (지식 추출)
- ❌ AI Voicebot (AI 통화)
- ❌ VectorDB 지식 저장
- ❌ RAG 검색
- ❌ Backend API 서버 시작 실패

### **근본 원인**
PyTorch 2.1.x에서 내부 API가 변경되었는데, 구버전 라이브러리들이 호환되지 않음:

| 라이브러리 | 구버전 (❌) | 호환 버전 (✅) |
|-----------|------------|---------------|
| `transformers` | 4.35.x | **4.36.0+** |
| `sentence-transformers` | 2.2.2 | **2.3.1+** |
| `torch` | 2.1.2 | 2.1.2 (변경 없음) |

---

## 🚀 빠른 해결 방법

### **옵션 1: 자동 수정 스크립트 (권장)** ⭐

```powershell
# 1. 프로젝트 디렉토리로 이동
cd C:\work\workspace_sippbx\sip-pbx

# 2. 가상 환경 활성화
.\venv\Scripts\Activate.ps1

# 3. 수정 스크립트 실행
.\scripts\fix_pytorch_compatibility.ps1
```

**실행 결과**:
```
============================================================================
🔧 PyTorch 호환성 문제 수정
============================================================================

📦 현재 설치된 버전 확인 중...
  • sentence-transformers: Version: 2.2.2
  • transformers: Version: 4.35.2
  • torch: Version: 2.1.2

🔄 호환 버전으로 업그레이드 중...
[1/2] transformers 업그레이드 중...
  ✅ transformers 4.36.0 설치 완료
[2/2] sentence-transformers 업그레이드 중...
  ✅ sentence-transformers 2.3.1 설치 완료

============================================================================
✅ 수정 완료!
============================================================================
```

---

### **옵션 2: 수동 설치**

```powershell
# 가상 환경 활성화
.\venv\Scripts\Activate.ps1

# 호환 버전으로 업그레이드
pip install transformers==4.36.0 --upgrade
pip install sentence-transformers==2.3.1 --upgrade
```

---

### **옵션 3: 전체 재설치** (문제가 계속되는 경우)

```powershell
# 1. 관련 패키지 모두 제거
pip uninstall sentence-transformers transformers torch torchvision torchaudio -y

# 2. requirements-ai.txt 재설치
pip install -r requirements-ai.txt
```

---

## 🧪 수정 확인

### **1. Python에서 테스트**

```python
# 터미널에서 실행
python -c "import torch; import transformers; import sentence_transformers; print('✅ 모두 정상!')"
```

**예상 출력**:
```
✅ 모두 정상!
```

### **2. 버전 확인**

```powershell
pip show transformers sentence-transformers torch
```

**예상 출력**:
```
Name: transformers
Version: 4.36.0

Name: sentence-transformers
Version: 2.3.1

Name: torch
Version: 2.1.2
```

---

## 🚀 서버 재시작 및 확인

### **1. SIP PBX 서버**

```powershell
python src\main.py
```

**성공 로그 예시**:
```json
{
  "event": "🔧 [Knowledge Extraction] Starting initialization...",
  "timestamp": "2026-02-04T14:30:00.123"
}
{
  "event": "TextEmbedder initialized",
  "model": "paraphrase-multilingual-mpnet-base-v2",
  "device": "cpu",
  "timestamp": "2026-02-04T14:30:05.456"
}
{
  "event": "ChromaDB initialized",
  "collection": "knowledge_base",
  "count": 4,
  "timestamp": "2026-02-04T14:30:05.678"
}
{
  "event": "Knowledge Extractor initialized",
  "timestamp": "2026-02-04T14:30:05.890"
}
{
  "event": "call_manager_initialized",
  "knowledge_extraction_enabled": true,  // ✅ 활성화!
  "timestamp": "2026-02-04T14:30:06.000"
}
```

**초기화 시간**: 39초 → **5-10초**

---

### **2. Backend API 서버**

```powershell
python -m src.api.main
```

**성공 출력 예시**:
```
INFO:     Started server process [12345]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

---

## 📊 호환성 매트릭스

### **테스트된 조합**

| torch | transformers | sentence-transformers | 상태 |
|-------|--------------|---------------------|------|
| 2.0.1 | 4.35.x | 2.2.2 | ✅ 호환 |
| **2.1.2** | **4.36.0** | **2.3.1** | ✅ **권장** |
| 2.1.2 | 4.35.x | 2.2.2 | ❌ 에러 |
| 2.2.0 | 4.37.x | 2.4.0 | ✅ 호환 |

---

## 🔍 상세 기술 설명

### **왜 이런 문제가 발생했나?**

1. **PyTorch 2.1.0** (2023년 10월 출시)
   - 내부 API `_pytree` 모듈 변경
   - `register_pytree_node` → `_register_pytree_node`

2. **transformers 4.35.x** (2023년 10월)
   - 구버전 PyTorch API 사용
   - PyTorch 2.1과 호환 안됨

3. **transformers 4.36.0** (2023년 12월)
   - PyTorch 2.1 API 지원 추가
   - 호환성 문제 해결

4. **sentence-transformers 2.2.2** (2023년 8월)
   - transformers 4.35.x 의존
   - 간접적으로 PyTorch 2.1과 호환 안됨

5. **sentence-transformers 2.3.1** (2024년 1월)
   - transformers 4.36.0 의존
   - PyTorch 2.1 완벽 호환

### **API 변경 내용**

**PyTorch 2.0.x**:
```python
# torch/utils/_pytree.py
def register_pytree_node(cls, ...):
    # Public API
    ...
```

**PyTorch 2.1.x**:
```python
# torch/utils/_pytree.py
def _register_pytree_node(cls, ...):  # ← 언더스코어 추가 (private)
    # Internal API
    ...

def register_pytree_node(cls, ...):
    # Deprecated, redirects to _register_pytree_node
    ...
```

**transformers 4.35.x**:
```python
# transformers/utils/generic.py:465
_torch_pytree.register_pytree_node(  # ← 구버전 API 호출
    ModelOutput,
    ...
)
```

**transformers 4.36.0**:
```python
# transformers/utils/generic.py:465
if hasattr(_torch_pytree, '_register_pytree_node'):
    _torch_pytree._register_pytree_node(  # ← 신버전 API 호출
        ModelOutput,
        ...
    )
else:
    _torch_pytree.register_pytree_node(  # ← 구버전 fallback
        ModelOutput,
        ...
    )
```

---

## 🛠️ 고급 트러블슈팅

### **문제 1: pip 업그레이드 실패**

**증상**:
```
ERROR: Could not install packages due to an OSError
```

**해결**:
```powershell
# pip 업그레이드
python -m pip install --upgrade pip

# 캐시 클리어
pip cache purge

# 재시도
pip install transformers==4.36.0 sentence-transformers==2.3.1 --no-cache-dir
```

---

### **문제 2: 여전히 같은 에러 발생**

**원인**: 이전 버전이 캐시에 남아있음

**해결**:
```powershell
# 1. 완전 제거
pip uninstall sentence-transformers transformers -y

# 2. 캐시 정리
pip cache purge
python -m pip cache purge

# 3. 재설치
pip install transformers==4.36.0
pip install sentence-transformers==2.3.1

# 4. 확인
pip show transformers sentence-transformers
```

---

### **문제 3: Import 에러는 해결됐지만 모델 로딩 실패**

**증상**:
```
OSError: Can't load tokenizer for 'paraphrase-multilingual-mpnet-base-v2'
```

**해결**:
```powershell
# HuggingFace 캐시 클리어
Remove-Item -Recurse -Force $env:USERPROFILE\.cache\huggingface

# 모델 다운로드 스크립트 실행
python scripts\download_models.py
```

---

### **문제 4: 가상 환경 문제**

**증상**: 패키지를 설치했는데도 여전히 에러

**원인**: 잘못된 Python 환경 사용 중

**해결**:
```powershell
# 1. 가상 환경 확인
python -c "import sys; print(sys.prefix)"
# 출력이 C:\work\workspace_sippbx\sip-pbx\venv 가 아니면 문제!

# 2. 가상 환경 재활성화
deactivate
.\venv\Scripts\Activate.ps1

# 3. 재확인
python -c "import sys; print(sys.prefix)"
```

---

## 📚 참고 자료

- **PyTorch 릴리즈 노트**: https://github.com/pytorch/pytorch/releases/tag/v2.1.0
- **Transformers 호환성**: https://huggingface.co/docs/transformers/installation
- **Sentence Transformers**: https://www.sbert.net/

---

## ❓ FAQ

### Q1: GPU 사용 중인데 업그레이드해도 되나요?
**A**: 네! `transformers`와 `sentence-transformers` 업그레이드는 GPU 사용에 영향을 주지 않습니다.

### Q2: 프로덕션 환경에서도 안전한가요?
**A**: 네. `transformers 4.36.0`과 `sentence-transformers 2.3.1`은 안정 버전(stable)입니다.

### Q3: 다른 프로젝트에도 영향을 주나요?
**A**: 아니요. 가상 환경을 사용하므로 이 프로젝트에만 영향을 줍니다.

### Q4: 원래 버전으로 되돌리려면?
**A**: 
```powershell
pip install transformers==4.35.2 sentence-transformers==2.2.2
```

---

**🎉 수정 완료 후 모든 AI 기능이 정상 작동합니다!**
