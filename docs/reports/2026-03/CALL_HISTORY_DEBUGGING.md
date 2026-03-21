# Frontend 통화이력 페이지 디버깅 및 개선

## 📋 개요

**작성일**: 2026-03-10  
**목적**: 사용자가 보고한 Frontend 통화이력 페이지 문제 재점검 및 디버깅 강화  
**파일**: `sip-pbx/frontend/app/call-history/page.tsx`

---

## 🔍 사용자가 보고한 문제 (스크린샷 기준)

이미지에서 확인된 문제점:
1. **발신 컬럼**: "알 수 없음" 표시 → 실제 caller 정보 필요
2. **대화 내용**: "대화 내용이 없습니다" → 실제로는 통화 내용이 있을 가능성
3. **종료 시간**: "-" 표시 → "통화 중" 또는 실제 종료 시간 필요
4. **녹음 재생**: 체크 마크만 → 재생 버튼 필요

---

## ✅ 이미 적용된 수정사항 (이전 작업)

### 1. 발신자 정보 표시

```typescript
// Line 276
<td className="px-4 py-3">{row.caller_id || '알 수 없음'}</td>
```

**상태**: ✅ 이미 수정됨
- `caller_id`가 있으면 표시, 없으면 "알 수 없음"

### 2. 종료 시간 표시

```typescript
// Line 290-291
<td className="px-4 py-3 text-gray-600">
  {row.end_time ? new Date(row.end_time).toLocaleString('ko-KR') : '통화 중'}
</td>
```

**상태**: ✅ 이미 수정됨
- `end_time`이 `null`이면 "통화 중" 표시

### 3. 녹음 재생 버튼

```typescript
// Line 293-320
<td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
  {row.has_recording ? (
    <div className="flex gap-1">
      <button onClick={() => handlePlayRecording(row.call_id)}>
        {playingAudio === row.call_id ? '⏸' : '▶'}
      </button>
      <button onClick={() => handleDownloadRecording(row.call_id)}>
        ⬇
      </button>
    </div>
  ) : '-'}
</td>
```

**상태**: ✅ 이미 수정됨
- 재생(▶/⏸) + 다운로드(⬇) 버튼 추가

---

## 🐛 추가 디버깅 개선사항

### 문제: 대화 내용이 표시되지 않음

**원인 분석**:
1. Backend API가 `transcripts` 배열을 반환하지 않을 수 있음
2. Frontend에서 API 호출이 실패하거나 응답이 비어있을 수 있음
3. 데이터 형식이 예상과 다를 수 있음

**적용된 디버깅 로그**:

```typescript
// toggleExpand 함수 (Line 100-148)
const toggleExpand = async (callId: string) => {
  // ...
  console.log('toggleExpand:', { 
    callId, 
    row, 
    hasTranscripts: !!row?.transcripts, 
    transcriptsLength: row?.transcripts?.length 
  });
  
  if (row && row.transcripts && row.transcripts.length > 0) {
    console.log('Using row.transcripts:', row.transcripts);
    // ...
  }
  
  if (row && (row.stt_transcript || row.transcript)) {
    console.log('Has stt_transcript or transcript:', row.stt_transcript || row.transcript);
  }
  
  // API 호출
  console.log('Fetching transcript for:', callId);
  const res = await fetch(`${API_URL}/api/calls/${callId}/transcript`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (res.ok) {
    const data = await res.json();
    console.log('Transcript API response:', data);
    // ...
  } else {
    console.error('Transcript API failed:', res.status, res.statusText);
  }
};
```

**렌더링 시 로그**:

```typescript
// Line 349-394
{(() => {
  const messages = transcripts[row.call_id] || row.transcripts || [];
  console.log('Rendering messages for', row.call_id, ':', messages);
  
  if (messages.length > 0) {
    // 메시지 렌더링
    return (/* ... */);
  } else if (row.stt_transcript || row.transcript) {
    console.log('Rendering text transcript for', row.call_id);
    return (/* ... */);
  } else {
    console.log('No transcript data for', row.call_id);
    return (
      <div className="text-sm text-gray-500">
        대화 내용이 없습니다
        <div className="text-xs mt-2 text-gray-400">
          (call_id: {row.call_id}, has_recording: {row.has_recording ? 'Yes' : 'No'})
        </div>
      </div>
    );
  }
})()}
```

---

## 🔧 디버깅 방법

### 1. 브라우저 콘솔 확인

**절차**:
1. Chrome/Edge 개발자 도구 열기 (F12)
2. Console 탭 선택
3. 통화이력 페이지 접속
4. 통화 행 클릭 (확장)
5. 콘솔 로그 확인

**예상 로그 출력**:
```
toggleExpand: { callId: "01ns16i1VK", row: {...}, hasTranscripts: false, transcriptsLength: undefined }
Fetching transcript for: 01ns16i1VK
Transcript API response: { messages: [], transcripts: [] }
Rendering messages for 01ns16i1VK : []
No transcript data for 01ns16i1VK
```

**분석 포인트**:
- `row.transcripts`: API 응답에 이미 포함되어 있는가?
- `Transcript API response`: API가 정상적으로 응답하는가?
- `messages`: 최종적으로 렌더링할 데이터가 있는가?

### 2. Network 탭 확인

**절차**:
1. 개발자 도구 → Network 탭
2. 통화 행 클릭
3. `/api/calls/{call_id}/transcript` 요청 확인

**확인 사항**:
- HTTP Status: 200 OK인가?
- Response Body: 데이터가 올바른 형식인가?
- Authorization Header: 토큰이 포함되어 있는가?

**예상 응답 형식**:
```json
{
  "messages": [
    {
      "role": "assistant",
      "content": "안녕하세요 기상청 AI 통합 비서입니다...",
      "timestamp": "2026-03-10T16:47:40.000Z"
    },
    {
      "role": "user",
      "content": "날씨 알려주세요",
      "timestamp": "2026-03-10T16:48:20.000Z"
    }
  ]
}
```

또는:

```json
{
  "transcripts": [
    // ...
  ]
}
```

---

## 🎯 문제 해결 시나리오

### 시나리오 1: Backend API가 빈 배열 반환

**증상**:
```
Transcript API response: { messages: [] }
```

**원인**: 
- 통화가 종료되지 않아 transcript가 아직 생성되지 않음
- Backend에서 transcript를 저장하지 않음
- Call history 데이터베이스에 transcript가 없음

**해결**:
1. Backend API 로그 확인 (`app.log`)
2. `stt_transcript_saved` 이벤트 확인
3. `recordings/{call_id}/transcript.txt` 파일 확인

### 시나리오 2: API 호출 실패 (401, 404, 500 등)

**증상**:
```
Transcript API failed: 401 Unauthorized
```

**원인**:
- 인증 토큰이 만료됨
- Call ID가 존재하지 않음
- Backend API 오류

**해결**:
1. 로그인 다시 수행 (토큰 갱신)
2. Backend API 로그 확인
3. Call history DB에 해당 call_id 존재 여부 확인

### 시나리오 3: row.transcripts가 이미 있는데 표시 안 됨

**증상**:
```
toggleExpand: { ..., hasTranscripts: true, transcriptsLength: 3 }
Using row.transcripts: [...]
Rendering messages for 01ns16i1VK : []
```

**원인**:
- `setTranscripts` 상태 업데이트가 반영되지 않음
- React 리렌더링 이슈

**해결**:
1. 페이지 새로고침 (Hard Reload: Ctrl+Shift+R)
2. 브라우저 캐시 삭제
3. React DevTools로 state 확인

### 시나리오 4: 데이터 형식 불일치

**증상**:
```typescript
// Backend가 다른 형식으로 반환
{
  "transcript_text": "착신자: 안녕하세요...",
  "stt_result": "..."
}
```

**원인**:
- Backend API 응답 형식이 Frontend 기대와 다름

**해결**:
1. Backend API 코드 확인
2. Response 형식 통일 (`messages` 또는 `transcripts` 배열)

---

## 📊 Backend API 확인 포인트

### 1. GET /api/call-history 응답

**기대 형식**:
```json
{
  "items": [
    {
      "call_id": "01ns16i1VK",
      "caller_id": "1003",
      "callee_id": "1004",
      "start_time": "2026-03-10T07:41:05Z",
      "end_time": null,
      "is_ai_handled": true,
      "has_recording": true,
      "transcripts": [  // ✅ 이 필드가 있으면 별도 API 호출 불필요
        {
          "role": "assistant",
          "content": "...",
          "timestamp": "..."
        }
      ]
    }
  ],
  "total": 1
}
```

### 2. GET /api/calls/{call_id}/transcript 응답

**기대 형식**:
```json
{
  "messages": [
    {
      "role": "assistant",
      "content": "안녕하세요...",
      "timestamp": "2026-03-10T16:47:40.000Z"
    }
  ]
}
```

또는:

```json
{
  "transcripts": [
    // ...
  ]
}
```

**현재 Frontend 지원**:
- `data.messages` ✅
- `data.transcripts` ✅
- `row.transcripts` (from call-history API) ✅
- `row.stt_transcript` (text fallback) ✅
- `row.transcript` (text fallback) ✅

---

## ✅ 사용자 액션 아이템

### 1. 브라우저 캐시 삭제 및 Hard Reload

```
Ctrl + Shift + R (Windows/Linux)
Cmd + Shift + R (Mac)
```

### 2. 콘솔 로그 확인

1. F12 → Console
2. 통화 행 클릭
3. 로그 캡처 후 공유

### 3. Network 탭 확인

1. F12 → Network
2. 통화 행 클릭
3. `/api/calls/.../transcript` 요청 확인
4. Response 내용 확인

### 4. Backend 로그 확인

```bash
# STT transcript 저장 확인
Select-String -Path "sip-pbx/logs/app.log" -Pattern "stt_transcript_saved"

# Call history API 호출 확인
Select-String -Path "sip-pbx/logs/app.log" -Pattern "call_history"
```

---

## 🔄 임시 해결 방법

만약 콘솔 로그에서 데이터가 있는데 표시되지 않는다면:

### 방법 1: 강제 리렌더링

```typescript
// fetchHistory 함수에 추가
const data = await res.json();
setItems(data.items ?? []);
setTotal(data.total ?? 0);
setTranscripts({});  // ✅ transcripts 초기화
setExpandedRow(null);  // ✅ 확장 상태 초기화
```

### 방법 2: 디버그 모드 활성화

코드에 이미 `console.log`가 추가되어 있으므로, 브라우저 콘솔에서 모든 로그를 확인할 수 있습니다.

---

## 📝 최종 체크리스트

- [x] 발신자 정보 표시 개선 (`caller_id || '알 수 없음'`)
- [x] 종료 시간 표시 개선 (`end_time ? ... : '통화 중'`)
- [x] 녹음 재생 버튼 추가 (▶/⏸)
- [x] 녹음 다운로드 버튼 추가 (⬇)
- [x] 대화 내용 로딩 로직 개선 (`row.transcripts` 우선 확인)
- [x] 콘솔 디버깅 로그 추가
- [x] 에러 핸들링 개선
- [ ] **사용자 액션**: 브라우저 캐시 삭제 및 새로고침
- [ ] **사용자 액션**: 콘솔 로그 확인 및 공유
- [ ] **사용자 액션**: Backend API 응답 확인

---

**다음 단계**:
1. 브라우저에서 Ctrl+Shift+R로 Hard Reload
2. 개발자 도구(F12) → Console 탭 열기
3. 통화 행 클릭하여 확장
4. 콘솔 로그 확인 및 캡처
5. 문제가 지속되면 로그 공유

**작성자**: AI Assistant  
**검토자**: (사용자 검토 필요)
