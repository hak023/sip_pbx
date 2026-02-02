# Cursor AI Agent 사용 가이드

## 🎯 설정 완료!

다음 파일들이 생성/설정되었습니다:

1. **`.cursorrules`** - Agent의 기본 동작 규칙
2. **`SKILL.md`** - 프로젝트 컨텍스트 및 절차
3. **`.vscode/settings.json`** - Cursor 설정

---

## 🚀 사용 방법

### 1️⃣ Debug Mode (디버그 모드)

**자동 활성화 조건:**
다음 키워드를 포함하면 자동으로 Debug Mode가 활성화됩니다:
- "버그", "bug", "오류", "error", "에러"
- "문제", "실패", "안돼", "작동 안"
- "디버깅", "debug", "분석해줘"

**예시:**
```
❌ 잘못된 사용:
"STT가 안돼. 왜 그래?"

✅ 올바른 사용:
"STT가 작동하지 않아. Debug Mode로 원인 분석해줘."

또는 자동:
"STT 버그 있어. 확인해줘."
→ Agent가 자동으로 Debug Mode 활성화
```

**명시적 트리거:**
```
"Debug Mode로 이 문제 해결해줘"
"디버그 모드 활성화해서 로그 분석해줘"
```

**Debug Mode 실행 시 Agent가 하는 일:**
1. ✅ 관련 로그 파일 확인 (`logs/app.log`)
2. ✅ 최근 변경사항 검토
3. ✅ Config 설정 검증 (`config/config.yaml`)
4. ✅ 관련 코드 경로 추적
5. ✅ 근본 원인 파악 후 수정 제안

---

### 2️⃣ Plan Mode (계획 모드)

**자동 활성화 조건:**
다음과 같은 복잡한 작업 요청 시 자동 활성화:
- 새로운 기능 추가 (예: "voicemail 기능 추가")
- 대규모 리팩토링
- 다중 파일 수정 필요한 작업
- "계획", "plan", "설계", "어떻게" 키워드

**예시:**
```
❌ 잘못된 사용:
"voicemail 추가해줘" (바로 코딩 시작)

✅ 올바른 사용:
"voicemail 기능을 추가하고 싶은데, Plan Mode로 먼저 계획 세워줘"

또는 자동:
"SIP PBX에 콜백 기능 구현해줘"
→ Agent가 자동으로 Plan Mode 활성화
```

**명시적 트리거:**
```
"Plan Mode로 계획 먼저 세워줘"
"계획 모드로 구조 설계해줘"
```

**Plan Mode 실행 시 Agent가 하는 일:**
1. 📋 코드베이스 분석 (관련 파일 검색)
2. 📋 의존성 파악
3. 📋 단계별 TODO 생성 (파일 경로 포함)
4. 📋 불명확한 요구사항 질문
5. 📋 Mermaid 다이어그램으로 시각화

---

### 3️⃣ Subagents (하위 에이전트)

**자동 활성화 조건:**
다음과 같은 병렬 작업 요청 시 자동 활성화:
- 여러 개의 독립적인 작업
- "동시에", "병렬로", "함께", "같이" 키워드
- 서로 다른 모듈/파일의 작업

**예시:**
```
❌ 잘못된 사용:
"STT 개선하고 TTS도 업데이트해줘" (순차 처리, 느림)

✅ 올바른 사용:
"STT 개선과 TTS 업데이트를 Subagent로 병렬 처리해줘"

또는 자동:
"STT 개선하고 동시에 문서도 업데이트해줘"
→ Agent가 자동으로 Subagents 활성화
```

**명시적 트리거:**
```
"Subagent로 병렬 처리해줘"
"이 작업들을 동시에 처리해줘"
```

**Subagents 실행 시 Agent가 하는 일:**
1. 🤖 작업을 독립적인 단위로 분리
2. 🤖 각 작업에 적절한 모델 할당
3. 🤖 병렬로 동시 실행
4. 🤖 결과 통합 및 충돌 해결

---

## 💡 실전 시나리오

### 시나리오 1: 버그 수정

```
상황: STT가 작동하지 않음

사용자: "STT가 안돼. Debug Mode로 분석해줘"

Agent 동작:
1. Debug Mode 활성화
2. logs/app.log 확인
3. config.yaml의 ai_voicebot.recording.post_processing_stt 확인
4. gcp-key.json 존재 확인
5. 최근 코드 변경사항 검토
6. 근본 원인 파악: "Config 모델에 ai_voicebot 필드 없음"
7. 수정 제안 및 적용
8. 테스트 가이드 제공
```

---

### 시나리오 2: 새 기능 추가

```
상황: Voicemail 기능 추가

사용자: "SIP PBX에 voicemail 기능 추가해줘. Plan Mode로 먼저 계획 세워줘"

Agent 동작:
1. Plan Mode 활성화
2. 코드베이스 분석 (SIP 메시지 처리, 녹음 로직 검토)
3. 필요한 파일 파악:
   - src/sip_core/sip_endpoint.py (SIP 메시지 핸들러)
   - src/sip_core/voicemail_manager.py (신규)
   - src/config/models.py (VoicemailConfig 추가)
   - config/config.yaml (voicemail 설정)
4. 단계별 TODO 생성:
   - [ ] VoicemailConfig 모델 추가
   - [ ] voicemail_manager.py 생성
   - [ ] SIP MESSAGE 핸들러 추가
   - [ ] 음성 저장 로직 구현
   - [ ] 테스트 작성
5. Mermaid 다이어그램으로 구조 시각화
6. 불명확한 부분 질문:
   - "최대 녹음 시간은?"
   - "저장 포맷은 WAV?"
```

---

### 시나리오 3: 병렬 작업

```
상황: STT 개선 + 문서 업데이트

사용자: "STT 정확도 개선하고 동시에 README도 업데이트해줘"

Agent 동작:
1. Subagents 자동 활성화 (키워드: "동시에")
2. Subagent A (STT 개선):
   - config.yaml의 STT 파라미터 조정
   - telephony 모델 → latest_long 모델 테스트
   - 정확도 비교
3. Subagent B (문서 업데이트):
   - README.md 읽기
   - 최신 기능 반영
   - 스크린샷 업데이트 제안
4. 병렬 실행 → 시간 절약
5. 결과 통합
```

---

## 🎮 단축키 (설정됨)

| 기능 | 단축키 | 설명 |
|------|--------|------|
| Debug Mode | `Ctrl + Shift + D` | 디버그 모드 트리거 |
| Plan Mode | `Ctrl + Shift + P` | 계획 모드 트리거 |
| Subagent | `Ctrl + Shift + S` | 하위 에이전트 생성 |

---

## 📝 추가 팁

### 1. 명확한 요청
```
❌ "고쳐줘"
✅ "STT 정확도를 높이기 위해 모델을 telephony에서 latest_long으로 변경해줘"
```

### 2. 컨텍스트 제공
```
❌ "에러 났어"
✅ "통화 후 STT 처리 중 'KeyError: ai_voicebot' 에러가 발생했어. logs/app.log 확인해줘"
```

### 3. 모드 조합
```
"Plan Mode로 voicemail 기능 계획 세운 후, 
Subagent로 병렬 구현해줘"
```

---

## 🔧 설정 커스터마이징

### .cursorrules 수정
프로젝트 특성에 맞게 규칙 추가:
```markdown
## 커스텀 규칙
- 모든 API 호출은 3초 timeout
- 로그는 한국어로 작성
```

### SKILL.md 확장
새로운 절차 추가:
```markdown
## 배포 절차
1. 테스트 실행
2. Docker 이미지 빌드
3. 프로덕션 배포
```

### .vscode/settings.json 조정
```json
{
  "cursor.agent.planMode": {
    "minComplexity": 5  // 5단계 이상만 자동 활성화
  }
}
```

---

## 🎯 자주 사용하는 명령어

| 요청 | Agent 동작 |
|------|-----------|
| "STT 버그 수정해줘" | 🔍 Debug Mode 자동 활성화 |
| "voicemail 기능 추가해줘" | 📋 Plan Mode 자동 활성화 |
| "STT 개선하고 문서도 업데이트해줘" | 🤖 Subagents 자동 활성화 |
| "이 코드 리뷰해줘" | ✅ Code Review 실행 |
| "최근 통화 로그 확인해줘" | 📊 로그 분석 + 요약 |

---

## 📚 참고 문서

- **`.cursorrules`**: Agent 동작 규칙
- **`SKILL.md`**: 프로젝트 컨텍스트
- **`.vscode/settings.json`**: Cursor 설정
- **`STT_TEST_GUIDE.md`**: STT 테스트 가이드
- **`WAV_AUDIO_FIX.md`**: 오디오 문제 해결

---

## 🚨 문제 해결

### Agent가 모드를 자동으로 활성화하지 않을 때
1. `.cursorrules` 파일이 프로젝트 루트에 있는지 확인
2. Cursor를 재시작
3. 명시적으로 모드 이름 언급: "Debug Mode로..."

### 설정이 적용되지 않을 때
1. Cursor 재시작
2. `.vscode/settings.json` 문법 오류 확인
3. Cursor 버전 확인 (v2.4 이상 권장)

---

**설정 완료! 이제 Cursor AI Agent를 최대한 활용하세요!** 🚀

추가 질문이나 커스터마이징이 필요하면 언제든 요청하세요.
