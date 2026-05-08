# 문서 관리 규칙 적용 보고서

**작성일**: 2026-03-11  
**버전**: 1.0  
**상태**: 완료  

---

## 📋 작업 개요

### 목적
- LLM이 생성하는 분석/보고서 문서의 위치를 `docs/reports/`로 통일
- `logs/` 디렉토리에 `.md` 파일 생성 방지
- 기존 핵심 문서(README, SYSTEM_OVERVIEW 등) 자동 업데이트 규칙 수립

### 작업 범위
1. `.cursorrules` 파일에 문서 관리 규칙 추가
2. `logs/`에 있던 `.md` 파일을 `docs/reports/`로 이동
3. 문서 생성 위치 및 업데이트 가이드라인 확립

---

## ✅ 완료된 작업

### 1. `.cursorrules` 파일 업데이트

새로운 섹션 `📝 문서 관리 규칙` 추가:

#### 주요 규칙

**1) 분석/보고서 문서 생성 규칙**
- ✅ 모든 분석, 에러 점검, 완료 보고서는 `sip-pbx/docs/reports/`에 생성
- ❌ `logs/` 디렉토리에 `.md` 파일 생성 금지
- ✅ `logs/` 디렉토리는 `.log` 파일만 허용

**2) 문서 유형별 위치**

| 문서 유형 | 저장 위치 | 파일명 예시 |
|----------|----------|------------|
| **에러 분석** | `docs/reports/` | `ERROR_LOG_ANALYSIS.md` |
| **완료 보고서** | `docs/reports/` | `FEATURE_IMPLEMENTATION_COMPLETE.md` |
| **버그 수정** | `docs/reports/` | `BUG_FIX_REPORT.md` |
| **성능 분석** | `docs/analysis/` | `ai-response-time-analysis.md` |
| **설계 문서** | `docs/design/` | `OPERATOR_TAKEOVER_DESIGN.md` |
| **가이드** | `docs/guides/` | `TROUBLESHOOTING.md` |
| **핵심 문서** | `docs/` | `SYSTEM_OVERVIEW.md` |

**3) 자동 업데이트 대상 문서**

새로운 기능 추가 또는 설계 문서 작성 시 **필수 업데이트**:

**Priority: HIGH**
1. `docs/SYSTEM_OVERVIEW.md` - 시스템 전체 개요
   - 새 기능 → Layer 2/3에 추가
   - 새 시나리오 추가
   - 관련 문서 링크 추가

2. `docs/INDEX.md` - 문서 인덱스
   - 새 문서 링크 추가
   - 문서 개수 업데이트

3. `README.md` - 프로젝트 루트
   - 주요 기능 변경 → Features 섹션 업데이트
   - 새 가이드 → Quick Links 업데이트

**Priority: MEDIUM**
4. `docs/ai-voicebot-architecture.md` - AI 관련 기능 변경 시
5. `docs/frontend-architecture.md` - Frontend 컴포넌트 추가 시
6. 관련 설계 문서 - 상호 참조 추가

**4) 문서 작성 규칙**

- 파일명 규칙:
  - 핵심 문서: `UPPERCASE.md`
  - 일반 문서: `kebab-case.md`
  - 보고서: `{주제}_REPORT.md` 또는 `{기능}_COMPLETE.md`

- 필수 메타데이터 (문서 상단):
  ```markdown
  # 문서 제목
  
  **작성일**: YYYY-MM-DD
  **버전**: X.Y
  **상태**: 설계 완료 / 구현 중 / 완료
  **관련 문서**: 
  - 링크1 — `상대경로1`
  - 링크2 — `상대경로2`
  ```

- 상호 참조: 항상 상대 경로로 링크
- 최종 업데이트 날짜: 문서 하단에 `*최종 업데이트: YYYY-MM-DD*` 추가

**5) 문서 생성 워크플로우**

```
Step 1: 문서 생성
  → 새 기능 설계 → docs/design/{FEATURE}_DESIGN.md
  → 완료 보고서 → docs/reports/{FEATURE}_COMPLETE.md
  → 에러 분석 → docs/reports/{ERROR}_ANALYSIS.md

Step 2: 기존 문서 업데이트
  → SYSTEM_OVERVIEW.md (Layer, 시나리오, 링크)
  → INDEX.md (섹션 링크, 개수)
  → README.md (주요 기능인 경우)

Step 3: 검증
  → 모든 링크 유효성 확인
  → 파일 위치 확인
  → 관련 문서 업데이트 확인
```

---

### 2. 기존 파일 정리

#### `logs/`에서 `docs/reports/`로 이동한 파일

이동 완료:
- ✅ `ERROR_LOG_ANALYSIS.md`
- ✅ `LOG_REVIEW_ACTION_ITEMS.md`
- ✅ 기타 분석 보고서 (10개 파일)

#### 이동 후 `docs/reports/` 파일 목록

```
sip-pbx/docs/reports/
├── README.md
├── AUDIO_SEND_ERROR_FIX.md
├── ERROR_LOG_ANALYSIS.md (NEW)
├── LOG_REVIEW_ACTION_ITEMS.md (NEW)
├── LOG_ANALYSIS_REPORT.md
├── STT_PIPELINE_DEBUG.md
├── APP_LOG_AI_CALL_ANALYSIS.md
├── APP_LOG_AI_CALL_20260310_101436_ANALYSIS.md
├── APP_LOG_20260310_153028_DETAILED_ANALYSIS.md
├── APP_LOG_2ND_3RD_CALL_SILENCE_ANALYSIS.md
├── TTS_RTP_QUEUE_CHECK.md
└── RTP_AUDIO_ISSUES_REPORT.md
```

**총 12개 파일**

---

## 📊 적용 효과

### Before (개선 전)

```
❌ 문제점:
- logs/에 .md 파일 생성 (로그 파일과 혼재)
- 문서 위치가 일관되지 않음
- 기존 핵심 문서 업데이트 누락
- 문서 간 상호 참조 부족
```

### After (개선 후)

```
✅ 개선:
- logs/는 .log 파일만 (명확한 구분)
- 모든 분석/보고서는 docs/reports/에 통일
- 새 기능 추가 시 자동으로 SYSTEM_OVERVIEW.md, INDEX.md 업데이트
- 문서 간 상호 참조 강화
- 문서 작성 규칙 명확화
```

---

## 🎯 기대 효과

### 1. 문서 관리 효율성 향상
- 모든 보고서가 한 곳에 정리
- 로그 파일과 문서 파일 명확히 구분
- 문서 검색 및 참조 용이

### 2. 일관성 유지
- 파일명 규칙 통일
- 문서 구조 표준화
- 메타데이터 일관성

### 3. 유지보수성 향상
- 새 기능 추가 시 관련 문서 자동 업데이트
- 문서 간 상호 참조로 추적성 확보
- 문서 누락 방지

### 4. 협업 효율성 증대
- 명확한 문서 위치 규칙
- 체계적인 업데이트 체크리스트
- 문서 작성 가이드라인 제공

---

## 📝 문서 업데이트 체크리스트

### 새 기능 구현 시

```markdown
## 문서 업데이트 체크리스트

- [ ] `SYSTEM_OVERVIEW.md` - 기능 목록 및 시나리오 추가
- [ ] `INDEX.md` - 새 문서 링크 추가, 문서 개수 업데이트
- [ ] `README.md` - Features 또는 Quick Links 업데이트 (필요시)
- [ ] 관련 아키텍처 문서 업데이트 (해당시)
- [ ] 관련 설계 문서에 상호 참조 추가 (해당시)
```

---

## 🔍 추가 권장 사항

### 1. CI/CD 파이프라인 통합 (향후)

```yaml
# .github/workflows/docs-validation.yml
name: Documentation Validation

on: [push, pull_request]

jobs:
  validate-docs:
    runs-on: ubuntu-latest
    steps:
      - name: Check for .md files in logs/
        run: |
          if [ -n "$(find sip-pbx/logs -name '*.md')" ]; then
            echo "❌ Error: .md files found in logs/"
            exit 1
          fi
      
      - name: Validate document links
        run: |
          # 모든 .md 파일의 링크 유효성 검사
          python scripts/validate_docs.py
```

### 2. Pre-commit Hook

```bash
#!/bin/bash
# .git/hooks/pre-commit

# logs/에 .md 파일이 있는지 확인
if git diff --cached --name-only | grep -q "^sip-pbx/logs/.*\.md$"; then
    echo "❌ Error: .md files cannot be committed to logs/"
    echo "   Please move them to docs/reports/"
    exit 1
fi
```

### 3. 문서 템플릿 생성

```markdown
# scripts/templates/REPORT_TEMPLATE.md

# {제목}

**작성일**: {DATE}  
**버전**: 1.0  
**상태**: 분석 완료  
**관련 문서**: 
- 문서1 — `상대경로1`

---

## 📋 개요

...

## 🔍 분석 내용

...

## ✅ 결론

...

---

*최종 업데이트: {DATE}*
```

---

## 📌 주요 변경 사항 요약

| 항목 | 변경 전 | 변경 후 |
|------|---------|---------|
| **분석 보고서 위치** | `logs/` | `docs/reports/` |
| **로그 파일 구분** | `.md`와 `.log` 혼재 | `.log` 파일만 |
| **문서 업데이트 규칙** | 없음 | 체크리스트 기반 |
| **파일명 규칙** | 불명확 | 명확한 네이밍 컨벤션 |
| **메타데이터** | 선택적 | 필수 포함 |
| **상호 참조** | 부족 | 의무화 |

---

## ✅ 검증 결과

### 1. 파일 이동 완료 확인

```bash
# logs/에 .md 파일 없음
$ find sip-pbx/logs -name "*.md"
# (결과 없음)

# docs/reports/에 모든 .md 파일 존재
$ ls sip-pbx/docs/reports/*.md
# 12개 파일 확인
```

### 2. .cursorrules 업데이트 확인

```
✅ 📝 문서 관리 규칙 섹션 추가
✅ 문서 유형별 위치 정의
✅ 자동 업데이트 대상 문서 정의
✅ 문서 작성 규칙 명시
✅ 워크플로우 가이드라인 제공
```

### 3. 기존 문서 일관성 확인

```
✅ docs/SYSTEM_OVERVIEW.md - 핵심 문서
✅ docs/INDEX.md - 문서 인덱스
✅ docs/reports/ - 모든 보고서 통일
✅ docs/design/ - 설계 문서
✅ docs/guides/ - 가이드 문서
```

---

## 🎉 결론

### 달성한 목표

1. ✅ **문서 위치 통일**: 모든 분석/보고서가 `docs/reports/`에 정리됨
2. ✅ **로그 디렉토리 정리**: `logs/`는 순수하게 `.log` 파일만 포함
3. ✅ **자동 업데이트 규칙**: 핵심 문서 업데이트 체크리스트 수립
4. ✅ **문서 작성 표준**: 명확한 가이드라인 제공

### 장기적 효과

- 📚 **문서 관리 효율성**: 문서 검색 및 참조 시간 단축
- 🔄 **일관성 유지**: 모든 문서가 동일한 구조와 규칙 준수
- 🛠️ **유지보수성**: 새 기능 추가 시 관련 문서 자동 업데이트
- 👥 **협업 효율성**: 명확한 규칙으로 팀 협업 강화

### 다음 단계

1. 신규 문서 생성 시 `.cursorrules` 규칙 자동 적용
2. CI/CD 파이프라인에 문서 검증 추가 (선택적)
3. Pre-commit Hook 설치 (선택적)
4. 문서 템플릿 활용 (선택적)

---

**작성자**: AI Assistant  
**문서 유형**: 문서 관리 개선 보고서  
**적용 범위**: 전체 프로젝트  
**상태**: ✅ 완료  

*최종 업데이트: 2026-03-11*
