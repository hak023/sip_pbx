# 프론트엔드 완전 재시작 가이드

## 문제
브라우저가 이전 JavaScript 코드를 캐시하여 코드 변경이 반영되지 않음

## 해결 방법

### 1단계: 프론트엔드 개발 서버 완전 중지

**터미널에서 실행 중인 `npm run dev` 프로세스 종료**:
- `Ctrl + C` (여러 번 눌러서 확실히 종료)
- 또는 터미널 창 닫기

### 2단계: .next 빌드 캐시 삭제

```powershell
cd c:\work\workspace_sippbx\sip-pbx\frontend
Remove-Item -Recurse -Force .next
Remove-Item -Recurse -Force node_modules\.cache -ErrorAction SilentlyContinue
```

### 3단계: 프론트엔드 재시작

```powershell
npm run dev
```

### 4단계: 브라우저 캐시 완전 삭제

**Chrome/Edge**:
1. `Ctrl + Shift + Delete` 눌러서 캐시 삭제 창 열기
2. **기간**: "전체 기간" 선택
3. **항목**: 
   - ✅ 캐시된 이미지 및 파일
   - ✅ 쿠키 및 기타 사이트 데이터 (선택 사항)
4. "데이터 삭제" 클릭

**또는 개발자도구 사용**:
1. `F12` → 개발자도구 열기
2. **Network** 탭 선택
3. ✅ **Disable cache** 체크박스 활성화
4. 개발자도구를 **열어둔 채로** 테스트

### 5단계: 페이지 Hard Refresh

- `Ctrl + Shift + R` (Windows)
- `Cmd + Shift + R` (Mac)

### 6단계: 테스트

1. 지식 베이스 페이지 접속
2. 개발자도구 Network 탭에서 **실제 요청 URL 확인**:
   ```
   정상: http://localhost:8000/api/knowledge
   비정상: http://localhost:8000/api/knowledge?tenant_id=1004
   ```
3. 지식 추가 테스트

---

## 빠른 검증 방법

**브라우저 개발자도구 Console**에서:
```javascript
// 현재 로드된 코드 확인
fetch('/api/knowledge', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    text: 'test',
    owner: '1004',
    category: 'question',
    source: 'api'
  })
}).then(r => r.json()).then(console.log).catch(console.error)
```

응답:
- **정상**: `{"ok": true, "doc_id": "..."}`
- **비정상**: 422 에러

---

## 영구 해결책

개발 중에는 **개발자도구를 항상 열어두고** "Disable cache" 활성화!
