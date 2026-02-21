# 🔧 SIP-PBX 서버 실행 오류 수정 완료

## 📋 문제 요약

### 1. ModuleNotFoundError: No module named 'src'
**에러 메시지**:
```
ModuleNotFoundError: No module named 'src'
```

**원인**:
- `src/main.py`가 절대 import(`from src.config...`)를 사용
- Python 실행 시 프로젝트 루트가 sys.path에 없음

### 2. Pydantic V2 네임스페이스 충돌 경고
**경고 메시지**:
```
UserWarning: Field "model_name" has conflict with protected namespace "model_".
UserWarning: Field "model_size" has conflict with protected namespace "model_".
UserWarning: Field "model_korean" has conflict with protected namespace "model_".
UserWarning: Field "model_english" has conflict with protected namespace "model_".
```

**원인**:
- Pydantic V2에서 `model_` 접두사는 보호된 네임스페이스
- `BaseModel`의 내부 메서드와 충돌 가능
- 경고는 무시 가능하지만 Best Practice는 해결하는 것

---

## ✅ 해결 방법

### 1. ModuleNotFoundError 수정

**파일**: `src/main.py`

**수정 내용**:
```python
# 프로젝트 루트를 Python 경로에 추가 (추가된 코드)
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
```

**위치**: 6-15라인 (import 구문 전에 추가)

**효과**:
- ✅ `python src/main.py` 명령으로 직접 실행 가능
- ✅ 절대 import 정상 작동
- ✅ IDE 및 CLI 모두에서 작동

---

### 2. Pydantic 네임스페이스 충돌 수정

#### 2-1. STTConfig 수정
**파일**: `src/config/models.py` (79-90라인)

```python
class STTConfig(BaseModel):
    """STT (Speech-to-Text) 설정"""
    model_config = {"protected_namespaces": ()}  # 추가
    
    model_size: str = Field(...)  # model_ 접두사 사용 가능
```

#### 2-2. TextClassifierConfig 수정
**파일**: `src/config/models.py` (99-108라인)

```python
class TextClassifierConfig(BaseModel):
    """텍스트 분류 설정"""
    model_config = {"protected_namespaces": ()}  # 추가
    
    model_korean: str = Field(...)
    model_english: str = Field(...)
```

#### 2-3. LLMProcessLog 수정
**파일**: `src/api/routers/ai_insights.py` (30-42라인)

```python
class LLMProcessLog(BaseModel):
    """LLM 처리 로그"""
    model_config = {"protected_namespaces": ()}  # 추가
    
    model_name: Optional[str] = None
```

**효과**:
- ✅ Pydantic 경고 메시지 제거
- ✅ `model_` 접두사 필드명 계속 사용 가능
- ✅ 코드 변경 최소화

---

## 🧪 검증 결과

### 실행 테스트
```bash
cd c:\work\workspace_sippbx\sip-pbx
python src/main.py --help
```

**결과**:
```
UTF-8 인코딩 설정이 적용되었습니다.
usage: main.py [-h] [--config CONFIG] [--port PORT]
               [--log-level {DEBUG,INFO,WARNING,ERROR,CRITICAL}] [--version]

SIP PBX with Real-time Voice Analysis

options:
  -h, --help            show this help message and exit
  ...
```

**상태**:
- ✅ ModuleNotFoundError 해결
- ✅ Pydantic 경고 메시지 제거
- ✅ 정상 실행 확인

---

## 📊 수정 파일 요약

| 파일 | 라인 | 수정 내용 |
|------|------|-----------|
| `src/main.py` | 6-15 | 프로젝트 루트를 sys.path에 추가 |
| `src/config/models.py` | 81 | STTConfig에 `model_config` 추가 |
| `src/config/models.py` | 101 | TextClassifierConfig에 `model_config` 추가 |
| `src/api/routers/ai_insights.py` | 32 | LLMProcessLog에 `model_config` 추가 |

---

## 🎯 Pydantic V2 Best Practice

### protected_namespaces 설정
```python
class MyModel(BaseModel):
    model_config = {"protected_namespaces": ()}
    
    # 이제 model_ 접두사 사용 가능
    model_name: str
    model_size: str
```

### 대안 방법들

#### 방법 1: 빈 튜플로 설정 (채택)
```python
model_config = {"protected_namespaces": ()}  # 모든 네임스페이스 허용
```

#### 방법 2: 특정 네임스페이스만 제외
```python
model_config = {"protected_namespaces": ("settings_",)}  # model_ 허용
```

#### 방법 3: 필드명 변경 (미채택)
```python
# model_name → model_info
# model_size → size
```
- 장점: 경고 없음
- 단점: 기존 코드 대량 수정 필요

---

## 🚀 서버 실행 가이드

### 기본 실행
```bash
cd sip-pbx
python src/main.py
```

### 커스텀 설정
```bash
# 특정 설정 파일 사용
python src/main.py --config config/custom.yaml

# 특정 포트 사용
python src/main.py --port 5061

# 로그 레벨 변경
python src/main.py --log-level DEBUG
```

### Docker 실행
```bash
docker-compose up -d
```

---

## ✅ 완료 체크리스트

- [x] **ModuleNotFoundError 수정**
  - [x] `src/main.py`에 sys.path 추가
  - [x] 직접 실행 테스트 통과

- [x] **Pydantic 경고 제거**
  - [x] `STTConfig`에 `model_config` 추가
  - [x] `TextClassifierConfig`에 `model_config` 추가
  - [x] `LLMProcessLog`에 `model_config` 추가
  - [x] 경고 메시지 확인

- [x] **검증 완료**
  - [x] `--help` 명령 정상 작동
  - [x] 경고 메시지 제거 확인

---

## 📎 참고 문서

- [Pydantic V2 Configuration](https://docs.pydantic.dev/latest/api/config/)
- [Protected Namespaces](https://docs.pydantic.dev/latest/concepts/models/#model-config)
- [Python sys.path](https://docs.python.org/3/library/sys.html#sys.path)

---

**수정 일시**: 2026-01-08 10:50  
**수정자**: Quinn (Test Architect)  
**상태**: ✅ **완료**

