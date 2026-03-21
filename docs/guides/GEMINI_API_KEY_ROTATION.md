# 403 API 키 유출(Leaked) 대응 – 새 키 발급 절차

**에러 메시지**: `403 Your API key was reported as leaked. Please use another API key.`

Google에서 해당 API 키가 유출된 것으로 감지되어 차단된 상태입니다. **새 API 키를 발급**한 뒤 기존 키를 교체해야 합니다.

---

## 1. 새 API 키 발급 (Google AI Studio)

1. 브라우저에서 **https://aistudio.google.com/app/apikey** 접속
2. Google 계정으로 로그인
3. 기존에 유출된 키가 있다면 해당 키 **삭제** 권장 (선택)
4. **"Create API key"** 클릭
5. 프로젝트 선택 (기존 Google Cloud 프로젝트 또는 "Create new project")
6. 생성된 키를 **복사** (한 번만 표시되므로 안전한 곳에 붙여넣기)

---

## 2. 프로젝트에 새 키 반영

### 권장: `.env` 파일

**경로**: `sip-pbx/.env` (또는 프로젝트 루트 `.env`)

```env
# 기존 키를 새 키로 교체
GEMINI_API_KEY=새로_발급받은_API_키_문자열
```

- 저장 후 **서버 재시작** (또는 해당 프로세스 재기동)
- `.env`는 Git에 올리지 않도록 유지 (`.gitignore`에 포함)

### 대안: 환경 변수 (PowerShell)

```powershell
$env:GEMINI_API_KEY="새로_발급받은_API_키_문자열"
# 이후 start-all.ps1 또는 앱 실행
```

### config.yaml (비권장)

테스트용으로만 사용하고, Git에 커밋하지 마세요.

```yaml
# config/config.yaml
google_cloud:
  gemini:
    api_key: "새로_발급받은_API_키_문자열"
```

---

## 3. 적용 확인

- 앱 재시작 후 통화 또는 LLM 호출 테스트
- 로그에 `403` / `leaked` 가 더 이상 나오지 않는지 확인
- 상세: [HOW_TO_SET_API_KEY.md](HOW_TO_SET_API_KEY.md)

---

## 4. 재발 방지

- API 키를 **코드·문서·이미지·공개 저장소**에 올리지 않기
- **.env** 또는 비공개 설정 파일에만 보관
- 정기적으로 키 로테이션(교체) 권장
- 키가 노출되었다고 생각되면 즉시 AI Studio에서 해당 키 **삭제** 후 새 키 발급

---

**작성일**: 2026-02-21  
**관련 리포트**: `docs/reports/TEST_REPORT_20260221_Wu6Qg-XLB3.md`
