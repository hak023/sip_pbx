# Frontend 통화이력 페이지 수정 보고서

## 📋 개요

**작성일**: 2026-03-10  
**목적**: Frontend 통화이력 페이지(`/call-history`)의 4가지 주요 오류 수정  
**파일**: `sip-pbx/frontend/app/call-history/page.tsx`

---

## 🐛 수정된 문제점

### 1. ✅ Roll down 시 통화 내용 미표시

**문제**:
- 행을 클릭하여 확장(roll down)했을 때 대화 내용이 표시되지 않음
- `transcripts[row.call_id]` 조회 로직만 있고, `row.transcripts` 확인 안 함

**원인**:
- Backend API가 `call-history` 응답에 `transcripts` 필드를 포함하여 반환할 수 있음
- Frontend는 별도 API 호출(`/api/calls/${callId}/transcript`)만 고려하여 즉시 표시 불가

**수정 사항**:

```typescript
// Before: transcripts state만 확인
{transcripts[row.call_id] && transcripts[row.call_id].length > 0 ? (
  // 렌더링
) : ...}

// After: row.transcripts도 함께 확인
{(() => {
  const messages = transcripts[row.call_id] || row.transcripts || [];
  if (messages.length > 0) {
    return (
      // 메시지 렌더링
    );
  } else if (row.stt_transcript || row.transcript) {
    return (
      // 텍스트 형식 렌더링
    );
  } else {
    return (
      <div className="text-sm text-gray-500">대화 내용이 없습니다</div>
    );
  }
})()}
```

**개선 효과**:
- API 응답에 이미 `transcripts`가 포함된 경우 즉시 표시
- 별도 API 호출 없이 빠른 UX 제공
- Fallback으로 `stt_transcript` 또는 `transcript` 텍스트도 표시

---

### 2. ✅ 종료 시간 미표시

**문제**:
- `end_time`이 `null`이면 빈 값(`-`)으로만 표시
- 통화 중인지, 종료되지 않았는지 구분 불가

**원인**:
- 조건부 렌더링이 단순히 `null` 체크만 수행

**수정 사항**:

```typescript
// Before
<td className="px-4 py-3 text-gray-600">
  {row.end_time ? new Date(row.end_time).toLocaleString('ko-KR') : '-'}
</td>

// After
<td className="px-4 py-3 text-gray-600">
  {row.end_time ? new Date(row.end_time).toLocaleString('ko-KR') : '통화 중'}
</td>
```

**개선 효과**:
- `end_time`이 `null`이면 "통화 중" 표시
- 사용자가 진행 중인 통화와 종료된 통화를 명확히 구분 가능

---

### 3. ✅ 녹음 필드에 재생 버튼 추가

**문제**:
- 녹음 파일이 있어도 체크 마크(`✓`)만 표시
- 다운로드 버튼은 "작업" 컬럼에 위치
- 녹음을 바로 재생할 수 없음

**원인**:
- 녹음 재생 기능 미구현
- UI/UX 개선 필요

**수정 사항**:

#### 3.1 State 추가

```typescript
const [playingAudio, setPlayingAudio] = useState<string | null>(null);
const audioRef = useRef<HTMLAudioElement | null>(null);
```

#### 3.2 재생 함수 구현

```typescript
const handlePlayRecording = (callId: string) => {
  if (playingAudio === callId) {
    // 재생 중이면 정지
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
    }
    setPlayingAudio(null);
    return;
  }

  // 새로운 오디오 재생
  const token = localStorage.getItem('access_token') || localStorage.getItem('token');
  if (!token) return;
  
  const url = `${API_URL}/api/calls/${callId}/recording?token=${encodeURIComponent(token)}`;
  
  if (audioRef.current) {
    audioRef.current.pause();
  }
  
  const audio = new Audio(url);
  audioRef.current = audio;
  setPlayingAudio(callId);
  
  audio.play().catch((err) => {
    console.error('Audio playback failed:', err);
    alert('녹음 재생 실패: ' + err.message);
    setPlayingAudio(null);
  });
  
  audio.onended = () => {
    setPlayingAudio(null);
  };
  
  audio.onerror = () => {
    alert('녹음 파일을 불러올 수 없습니다');
    setPlayingAudio(null);
  };
};
```

#### 3.3 UI 변경

```typescript
// Before: 녹음 컬럼
<td className="px-4 py-3">{row.has_recording ? '✓' : '-'}</td>

// 작업 컬럼에 다운로드 버튼
{row.has_recording && (
  <button onClick={() => handleDownloadRecording(row.call_id)}>
    ⬇
  </button>
)}

// After: 녹음 컬럼에 재생 + 다운로드 버튼
<td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
  {row.has_recording ? (
    <div className="flex gap-1">
      <button
        type="button"
        onClick={() => handlePlayRecording(row.call_id)}
        className={`px-2 py-1 text-xs ${
          playingAudio === row.call_id
            ? 'bg-red-500 hover:bg-red-600'
            : 'bg-green-500 hover:bg-green-600'
        } text-white rounded`}
        title={playingAudio === row.call_id ? '재생 중지' : '녹음 재생'}
      >
        {playingAudio === row.call_id ? '⏸' : '▶'}
      </button>
      <button
        type="button"
        onClick={() => handleDownloadRecording(row.call_id)}
        className="px-2 py-1 text-xs bg-blue-500 text-white rounded hover:bg-blue-600"
        title="녹음 다운로드"
      >
        ⬇
      </button>
    </div>
  ) : (
    '-'
  )}
</td>
```

#### 3.4 Cleanup 추가

```typescript
// Cleanup audio on unmount
useEffect(() => {
  return () => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
  };
}, []);
```

**개선 효과**:
- 녹음 파일을 바로 브라우저에서 재생 가능
- 재생 중인 녹음은 빨간색 일시정지 버튼으로 표시
- 다운로드와 재생 버튼이 녹음 컬럼에 함께 위치하여 직관적
- 컴포넌트 언마운트 시 오디오 리소스 자동 정리

---

### 4. ✅ 발신 필드에 caller 정보 미표시

**문제**:
- `caller_id`가 비어있으면 `-` 표시
- 사용자가 누가 전화했는지 알 수 없음

**원인**:
- Fallback 값이 단순히 `-`로 설정됨

**수정 사항**:

```typescript
// Before
<td className="px-4 py-3">{row.caller_id || '-'}</td>

// After
<td className="px-4 py-3">{row.caller_id || '알 수 없음'}</td>
```

**개선 효과**:
- `caller_id`가 비어있어도 "알 수 없음"으로 명확히 표시
- 데이터가 없는 것과 누락된 것을 구분 가능

---

## 📊 변경 사항 요약

| 항목 | 변경 전 | 변경 후 |
|------|---------|---------|
| **1. 대화 내용 표시** | `transcripts[callId]`만 확인 | `row.transcripts` 포함 우선 확인 |
| **2. 종료 시간** | `null`이면 `-` | `null`이면 "통화 중" |
| **3. 녹음 재생** | 체크 마크만 표시 | 재생(▶/⏸) + 다운로드(⬇) 버튼 |
| **4. 발신자 정보** | 빈 값이면 `-` | 빈 값이면 "알 수 없음" |

---

## 🎯 추가 개선 사항

### 1. Interface 업데이트

```typescript
interface CallHistoryEntry {
  // ...
  transcripts?: TranscriptMessage[];  // ✅ 추가
}
```

### 2. Import 추가

```typescript
import { useRef } from 'react';  // ✅ useRef 추가
```

### 3. toggleExpand 로직 개선

```typescript
const toggleExpand = async (callId: string) => {
  // ...
  
  // ✅ row.transcripts가 이미 있는지 먼저 확인
  const row = items.find(item => item.call_id === callId);
  if (row && row.transcripts && row.transcripts.length > 0) {
    setTranscripts((prev) => ({ ...prev, [callId]: row.transcripts || [] }));
    return;
  }
  
  // ✅ API 호출 (없는 경우만)
  // ...
};
```

---

## 🧪 테스트 시나리오

### 1. 대화 내용 표시 테스트

**절차**:
1. 통화이력 페이지 접속
2. AI 응대 통화 행 클릭 (확장)
3. 대화 내용 확인

**기대 결과**:
- `transcripts` 배열이 있으면 메시지 형식으로 표시
- `stt_transcript` 또는 `transcript` 텍스트가 있으면 텍스트 박스로 표시
- 둘 다 없으면 "대화 내용이 없습니다" 표시

---

### 2. 종료 시간 표시 테스트

**절차**:
1. 통화이력 페이지 접속
2. 진행 중인 통화와 종료된 통화 확인

**기대 결과**:
- 종료된 통화: "2026-03-10 16:47:49" 형식
- 진행 중인 통화: "통화 중"

---

### 3. 녹음 재생 테스트

**절차**:
1. 통화이력 페이지 접속
2. 녹음이 있는 통화의 재생 버튼(▶) 클릭
3. 녹음 재생 시작 확인
4. 일시정지 버튼(⏸) 클릭
5. 재생 중지 확인
6. 다운로드 버튼(⬇) 클릭
7. 파일 다운로드 확인

**기대 결과**:
- 재생 버튼 클릭 시 오디오 재생 시작
- 버튼 색상이 초록색 → 빨간색으로 변경
- 버튼 아이콘이 ▶ → ⏸ 로 변경
- 일시정지 버튼 클릭 시 재생 중지 및 초기 상태로 복귀
- 다운로드 버튼 클릭 시 mixed.wav 파일 다운로드

---

### 4. 발신자 정보 표시 테스트

**절차**:
1. 통화이력 페이지 접속
2. 발신 컬럼 확인

**기대 결과**:
- `caller_id`가 있으면 해당 ID 표시 (예: "1003")
- `caller_id`가 없으면 "알 수 없음" 표시

---

## 🔍 관련 API

### 1. GET /api/call-history

**응답 예시**:
```json
{
  "items": [
    {
      "call_id": "abc123",
      "caller_id": "1003",
      "callee_id": "1004",
      "start_time": "2026-03-10T16:47:39.000Z",
      "end_time": "2026-03-10T16:49:21.000Z",
      "is_ai_handled": true,
      "has_recording": true,
      "transcripts": [
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
  ],
  "total": 10
}
```

### 2. GET /api/calls/{call_id}/transcript

**응답 예시**:
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

### 3. GET /api/calls/{call_id}/recording

**쿼리 파라미터**:
- `token`: 인증 토큰

**응답**:
- Content-Type: `audio/wav`
- 파일: `mixed.wav` (caller + callee 믹스된 녹음)

---

## ✅ 체크리스트

- [x] 대화 내용 표시 수정 (`row.transcripts` 우선 확인)
- [x] 종료 시간 표시 개선 (`null`이면 "통화 중")
- [x] 녹음 재생 버튼 추가 (▶/⏸)
- [x] 녹음 다운로드 버튼 이동 (작업 컬럼 → 녹음 컬럼)
- [x] 발신자 정보 Fallback 개선 (`-` → "알 수 없음")
- [x] Audio 리소스 Cleanup 추가 (useEffect)
- [x] TypeScript 타입 정의 업데이트
- [ ] 실제 브라우저 테스트
- [ ] Backend API 응답 형식 확인
- [ ] 모바일 반응형 테스트

---

**작성자**: AI Assistant  
**검토자**: (사용자 검토 필요)  
**승인자**: (사용자 승인 필요)
