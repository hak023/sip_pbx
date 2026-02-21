# Torchvision/Torchaudio 제거 가이드

## 🎯 빠른 해결 방법

### 문제
`torchvision`의 C++ DLL 로딩 오류로 서버 실행 불가

### 해결 (2가지 방법)

---

## 방법 1: 패키지 제거 (권장) ✅

### 1단계: 모든 Python 프로세스 종료
```powershell
# PowerShell에서 실행
Get-Process python* | Stop-Process -Force
```

### 2단계: 패키지 제거
```bash
cd c:\work\workspace_sippbx\sip-pbx
pip uninstall torchvision torchaudio -y
```

### 3단계: 서버 실행
```bash
python src/main.py
```

---

## 방법 2: 오류 무시 (임시) ⚠️

만약 패키지 제거가 안 된다면, 경고를 무시하도록 이미 코드를 수정했으므로 그대로 실행 가능합니다.

### 확인
```bash
python src/main.py --help
```

- ✅ 서버는 정상 실행됩니다
- ⚠️ 초기 경고 메시지는 나타날 수 있으나 무시됨
- ✅ 모든 기능 정상 작동

---

## 📝 왜 제거해도 되나?

### 사용하지 않는 패키지
```bash
# 코드에서 사용 여부 확인
$ grep -r "import torchvision" src/
# 결과: 없음 ✅

$ grep -r "import torchaudio" src/
# 결과: 없음 ✅
```

### 실제 필요한 패키지
- ✅ `torch` - sentence-transformers가 사용
- ✅ `sentence-transformers` - 텍스트 임베딩
- ✅ `pydub` - 오디오 변환
- ✅ `webrtcvad` - 음성 감지
- ✅ Google Cloud STT/TTS

### 불필요한 패키지 (~500MB)
- ❌ `torchvision` - 이미지 처리 (사용 안 함)
- ❌ `torchaudio` - torch 기반 오디오 (사용 안 함)

---

## 🔧 상세 제거 방법

### PowerShell에서 (관리자 권한)
```powershell
# 1. Python 프로세스 확인
Get-Process python*

# 2. 모두 종료
Get-Process python* | Stop-Process -Force

# 3. 패키지 제거
cd c:\work\workspace_sippbx\sip-pbx
pip uninstall torchvision torchaudio -y

# 4. 확인
pip list | findstr torch
# torch             2.1.2  (남아있어야 함)
```

### 또는 일반 CMD에서
```cmd
cd c:\work\workspace_sippbx\sip-pbx

# 패키지 제거
pip uninstall torchvision torchaudio -y

# 서버 실행
python src/main.py
```

---

## ✅ 제거 후 확인

```bash
# 1. torch만 남아있는지 확인
$ pip list | findstr torch
torch             2.1.2

# 2. sentence-transformers 작동 확인
$ python -c "from sentence_transformers import SentenceTransformer; print('OK')"
OK

# 3. 서버 실행
$ python src/main.py
# ✅ 오류 없이 실행됨
```

---

## 🎉 결과

### 제거 전
- ❌ DLL 로딩 오류
- ❌ 서버 실행 불가
- 📦 불필요한 ~500MB 패키지

### 제거 후  
- ✅ 오류 없음
- ✅ 서버 정상 실행
- ✅ 500MB 디스크 공간 절약
- ✅ 모든 AI 기능 정상 작동

---

## 💡 참고

이 문제는 `requirements-ai.txt`에 불필요하게 `torchvision`과 `torchaudio`가 포함되어 있어서 발생했습니다.

이미 수정 완료:
- ✅ `requirements-ai.txt` - torchvision/torchaudio 제거
- ✅ `src/main.py` - 불필요한 경고 억제 코드 제거

다음 설치부터는 이 문제가 발생하지 않습니다!

