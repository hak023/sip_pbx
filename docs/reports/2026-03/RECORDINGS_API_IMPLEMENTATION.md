# 녹음(recordings) API 및 프론트 연동 (P5)

**작성일**: 2026-03  
**목적**: `recordings/` 세션 디렉터리 기준 오디오 조회·스트리밍·다운로드, 통화이력 UI 연동

---

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 |
|-----------|-----------|------|
| `src/api/utils/recording_paths.py` | 추가 | call_id→디렉터리 탐색, 오디오 목록, 안전 경로 해석 |
| `src/api/routers/recordings.py` | 추가 | `/api/recordings/calls/{call_id}/info|media|download` |
| `src/api/main.py` | 수정 | `recordings` 라우터 등록 |
| `src/api/utils/transcript_parser.py` | 수정 | `get_transcript_for_call`이 `find_call_directory` 사용 |
| `src/api/routers/call_history.py` | 수정 | `has_recording`을 실제 오디오 파일 존재로 설정, `RECORDINGS_DIR` 반영 |
| `frontend/lib/recordings.ts` | 추가 | info/blob fetch (Bearer), 다운로드 헬퍼 |
| `frontend/app/call-history/page.tsx` | 수정 | 녹음 재생 모달·저장 버튼 |

---

## API

| Method | 경로 | 설명 |
|--------|------|------|
| GET | `/api/recordings/calls/{call_id}/info` | `{ files: [{name, size_bytes, mime}], has_recording }` |
| GET | `/api/recordings/calls/{call_id}/media?file=` | 인라인 스트리밍(재생) |
| GET | `/api/recordings/calls/{call_id}/download?file=` | `attachment` 다운로드 |

- **보안**: `file` 파라미터는 순수 파일명만 허용, 세션 디렉터리 밖 접근 불가.
- **지원 확장자**: `.wav`, `.mp3`, `.m4a`, `.ogg`, `.webm`, `.flac`
- **환경변수**: `RECORDINGS_DIR` (기본 `recordings`, 프로세스 작업 디렉터리 기준)

---

## 저장 구조 (기존과 동일)

```
recordings/<세션폴더>/
  metadata.json   # call_id 등
  transcript.txt  # 선택
  *.wav 등        # 오디오
```

---

## 프론트

- `<audio src>`는 Bearer를 붙이기 어려워 **fetch + Blob URL**로 재생.
- 통화이력 테이블: `has_recording`일 때 **재생** / **저장** 버튼.
- 파일이 여러 개면 모달에서 선택 후 다시 로드.

---

## 참고

- 인증: 현재 엔드포인트는 토큰 없이도 호출 가능(내부망 가정). 필요 시 `HTTPBearer` 의존성 추가 권장.
