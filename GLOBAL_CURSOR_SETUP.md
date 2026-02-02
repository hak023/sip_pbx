# Cursor 전역 설정 완료 가이드

## ✅ 설정 완료 상태

Cursor AI Agent가 **모든 프로젝트**에서 동일하게 작동하도록 전역 설정이 완료되었습니다!

---

## 📁 생성된 파일

### 1. **전역 설정** (모든 프로젝트 적용)
```
C:\Users\hak23\.cursor\.cursorrules
```
- 모든 프로젝트에 적용되는 범용 규칙
- Debug Mode, Plan Mode, Subagents 자동 활성화 규칙
- 언어별 Best Practices
- 보안, 성능, 테스트 가이드

### 2. **프로젝트 설정** (SIP PBX만)
```
C:\work\workspace_sippbx\.cursorrules
```
- SIP PBX 프로젝트 특화 규칙
- SIP, RTP, STT 관련 규칙
- 전역 규칙에 추가됨

### 3. **프로젝트 컨텍스트** (SIP PBX만)
```
C:\work\workspace_sippbx\SKILL.md
```
- 프로젝트 구조, 절차, 히스토리

---

## 🎯 작동 방식

Cursor는 다음 순서로 규칙을 병합합니다:

```
1. 전역 규칙 로드
   └─ C:\Users\hak23\.cursor\.cursorrules

2. 프로젝트 규칙 로드 (있는 경우)
   └─ <프로젝트>\.cursorrules

3. 프로젝트 컨텍스트 로드 (있는 경우)
   └─ <프로젝트>\SKILL.md

4. 최종 규칙 = 전역 + 프로젝트 (중복 시 프로젝트 우선)
```

---

## 🚀 어떤 프로젝트에서든 사용 가능

### 예시 1: 새 Python 프로젝트
```
사용자: "FastAPI로 REST API 만들어줘. 데이터베이스는 PostgreSQL"

→ Agent 동작:
1. 전역 규칙 적용 (모든 프로젝트 동일)
2. "만들어줘" 키워드로 Plan Mode 자동 활성화
3. 코드베이스 분석 → TODO 생성 → 단계별 구현
4. Python Best Practices 적용
5. 테스트 코드 자동 생성 권장
```

### 예시 2: React 프론트엔드 프로젝트
```
사용자: "로그인 페이지 버그 수정해줘. 로그인 버튼이 안 눌려"

→ Agent 동작:
1. 전역 규칙 적용
2. "버그" 키워드로 Debug Mode 자동 활성화
3. 브라우저 콘솔 로그 확인 요청
4. React 컴포넌트 검토
5. 이벤트 핸들러 확인 → 수정
```

### 예시 3: Go 백엔드 프로젝트
```
사용자: "API 엔드포인트 3개 추가하고 동시에 문서도 업데이트해줘"

→ Agent 동작:
1. 전역 규칙 적용
2. "동시에" 키워드로 Subagents 자동 활성화
3. Subagent A: API 엔드포인트 구현
4. Subagent B: Swagger 문서 업데이트
5. 병렬 실행 → 결과 통합
```

---

## 🎮 사용법 (모든 프로젝트 동일)

### Debug Mode
**자동 트리거 키워드:**
- 한국어: 버그, 오류, 에러, 문제, 실패, 디버깅
- 영어: bug, error, issue, problem, debug

**예시:**
```
"로그인 기능에 버그가 있어. 확인해줘"
"API 호출이 실패해. Debug Mode로 분석해줘"
"테스트가 계속 에러나는데 원인 찾아줘"
```

---

### Plan Mode
**자동 트리거 키워드:**
- 기능 추가, 구현해줘, 만들어줘, 리팩토링
- add feature, implement, create, refactor

**예시:**
```
"사용자 인증 시스템 구현해줘"
"결제 모듈 추가하고 싶은데 Plan Mode로 계획 세워줘"
"이 코드 전체를 리팩토링해줘"
```

---

### Subagents
**자동 트리거 키워드:**
- 동시에, 함께, 같이, 병렬로
- together, parallel, simultaneously, along with

**예시:**
```
"API 구현하고 동시에 테스트도 작성해줘"
"프론트엔드 수정하고 함께 백엔드도 업데이트해줘"
"Subagent로 이 작업들을 병렬 처리해줘"
```

---

## 📋 새 프로젝트 시작 시

### 1. 프로젝트별 규칙 추가 (선택)
새 프로젝트 루트에 `.cursorrules` 파일 생성:

```markdown
# My Project - Specific Rules

## 프로젝트 특화 규칙
- 이 프로젝트는 [설명]
- 주요 기술 스택: [기술]
- 특별히 주의할 사항: [내용]

## 추가 Debug 경로
- 로그: logs/app.log
- 설정: config/settings.json

## 테스트 명령어
npm test
```

### 2. SKILL.md 파일 생성 (선택)
프로젝트 컨텍스트 문서:

```markdown
# Project Skills

## 아키텍처
[프로젝트 구조 설명]

## 핵심 절차
[중요한 절차들]

## 디버깅 체크리스트
[자주 발생하는 문제와 해결법]
```

---

## 🔧 Cursor 설정 확인

### Cursor Settings 열기
1. `Ctrl + ,` (또는 `Cmd + ,` on Mac)
2. "cursor rules" 검색
3. 다음 항목 확인:

```json
{
  "cursor.agent.enabled": true,
  "cursor.agent.useProjectRules": true,  // .cursorrules 사용
  "cursor.agent.useSkills": true,        // SKILL.md 사용
  "cursor.agent.autoMode": "smart"       // 자동 모드 선택
}
```

---

## 💡 전역 규칙 커스터마이징

### 전역 규칙 수정
```powershell
# 파일 열기
code C:\Users\hak23\.cursor\.cursorrules
```

**추가할 수 있는 것들:**
- 선호하는 코딩 스타일
- 자주 사용하는 라이브러리 규칙
- 회사 코딩 가이드
- 팀 협업 규칙

**예시:**
```markdown
## 내 코딩 스타일
- 함수명은 동사로 시작
- 클래스명은 명사
- 최대 줄 길이: 100자
- 들여쓰기: 스페이스 4칸

## 선호 라이브러리
- HTTP 클라이언트: httpx (Python), axios (JS)
- 로깅: structlog (Python), winston (JS)
- 테스트: pytest (Python), jest (JS)
```

---

## 🌍 다른 PC에서도 동일하게 사용하려면

### 1. 전역 규칙 백업
```powershell
# 백업
Copy-Item C:\Users\hak23\.cursor\.cursorrules ~\Dropbox\cursor-rules-backup.txt

# 복원 (다른 PC에서)
Copy-Item ~\Dropbox\cursor-rules-backup.txt C:\Users\<username>\.cursor\.cursorrules
```

### 2. Git으로 관리
```bash
# 전역 규칙을 Git 저장소에 추가
cd ~
git init cursor-config
cd cursor-config
cp ~/.cursor/.cursorrules .
git add .
git commit -m "Add global cursor rules"
git push

# 다른 PC에서
git clone <repo>
cp cursor-config/.cursorrules ~/.cursor/.cursorrules
```

---

## 📊 효과

### Before (전역 설정 없음)
```
프로젝트마다 매번:
- Debug Mode 수동 요청
- 코딩 규칙 반복 설명
- 테스트 방법 재지시
- 보안 규칙 누락
```

### After (전역 설정 적용)
```
모든 프로젝트에서 자동:
✅ 키워드만으로 모드 자동 활성화
✅ 일관된 코드 품질
✅ 자동 보안 체크
✅ 자동 테스트 권장
✅ 표준 로깅/에러 처리
```

---

## 🧪 테스트

### 1. SIP PBX 프로젝트에서 테스트
```
"최근 통화 STT 버그 있어. 확인해줘"
→ 전역 규칙 + 프로젝트 규칙 적용
```

### 2. 다른 프로젝트에서 테스트
```
cd C:\work\other-project
"로그인 API 구현해줘. Plan Mode로"
→ 전역 규칙만 적용 (프로젝트 규칙 없음)
```

### 3. 새 프로젝트 생성해서 테스트
```
mkdir C:\work\test-project
cd C:\work\test-project
"FastAPI 프로젝트 시작해줘"
→ 전역 규칙 자동 적용!
```

---

## 🚨 문제 해결

### Agent가 전역 규칙을 사용하지 않는 경우

1. **Cursor 재시작**
   ```
   Cursor 완전히 종료 → 재실행
   ```

2. **파일 경로 확인**
   ```powershell
   Test-Path C:\Users\hak23\.cursor\.cursorrules
   # True가 나와야 함
   ```

3. **파일 내용 확인**
   ```powershell
   Get-Content C:\Users\hak23\.cursor\.cursorrules | Select-Object -First 5
   # 파일이 비어있지 않은지 확인
   ```

4. **Cursor 버전 확인**
   ```
   Help > About
   → v2.2 이상 권장 (Subagents, Plan Mode 지원)
   ```

---

## 📚 참고 파일

| 파일 | 용도 | 적용 범위 |
|------|------|----------|
| `C:\Users\hak23\.cursor\.cursorrules` | 전역 규칙 | 모든 프로젝트 |
| `<project>\.cursorrules` | 프로젝트 규칙 | 해당 프로젝트만 |
| `<project>\SKILL.md` | 프로젝트 컨텍스트 | 해당 프로젝트만 |
| `<project>\.vscode\settings.json` | VS Code 설정 | 해당 프로젝트만 |

---

## ✨ 추가 팁

### 1. 자주 쓰는 명령어 단축키 만들기
Cursor Settings에서:
```json
{
  "cursor.agent.shortcuts": {
    "triggerDebugMode": "ctrl+shift+d",
    "triggerPlanMode": "ctrl+shift+p"
  }
}
```

### 2. 언어별 전역 규칙
`.cursorrules`에 추가:
```markdown
## Python 프로젝트 자동 감지
프로젝트에 `requirements.txt` 또는 `pyproject.toml`이 있으면:
- Type hints 필수
- Black 포매팅
- pytest 테스트

## JavaScript/TypeScript 프로젝트
프로젝트에 `package.json`이 있으면:
- ESLint 규칙 따르기
- Prettier 포매팅
- Jest 테스트
```

---

## 🎊 완료!

이제 **어떤 프로젝트를 열어도** Cursor AI Agent가 동일한 품질로 작동합니다!

- ✅ 전역 규칙: 모든 프로젝트에 자동 적용
- ✅ Debug/Plan/Subagents: 키워드로 자동 활성화
- ✅ 프로젝트별 추가 규칙: 선택적으로 커스터마이징
- ✅ 일관된 코드 품질: 모든 프로젝트 동일

**새 프로젝트 시작 시 아무 설정 없이 바로 사용 가능!** 🚀
