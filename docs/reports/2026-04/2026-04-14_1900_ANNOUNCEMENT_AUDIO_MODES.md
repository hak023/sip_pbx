## 개요

안내멘트 추가/수정 모달을 **TTS 음성** 및 **Suno AI 음악 생성** 두 가지 방식으로 개선.
TTS에는 배경음악 합성 체크 옵션 추가. Suno AI 음원 생성을 ringback 페이지에서 call-control 안내멘트 탭으로 통합.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|---|---|---|---|
| `src/call_control/models.py` | 수정 | `AnnouncementProfile`, `AnnouncementCreate`, `AnnouncementUpdate`에 Suno/배경음 필드 추가 | |
| `src/call_control/db.py` | 수정 | DDL에 신규 컬럼 추가, 마이그레이션 함수 확장, CRUD 함수 업데이트 | |
| `frontend/app/settings/call-control/page.tsx` | 수정 | `AnnouncementProfile` 타입 확장, `StyleTagSelector` 컴포넌트 추가, `AnnouncementFormModal` 2-모드 탭 재설계 | |
| `frontend/app/settings/ringback/page.tsx` | 수정 | Suno AI 생성 섹션 제거, 안내 카드로 대체. 관련 상태/함수/컴포넌트 정리 | |

## 상세 변경 내용

### 백엔드 모델 (`models.py`)
- `AnnouncementProfile`에 필드 추가:
  - `generation_mode: str` — `'tts'` | `'suno'`
  - `tts_background_music: bool` — TTS 배경음 합성 여부
  - `tts_background_style: Optional[str]` — 배경음 스타일 태그
  - `suno_lyrics`, `suno_style`, `suno_audio_url`, `suno_task_id`
- `AnnouncementCreate`, `AnnouncementUpdate`에 동일 필드 반영

### DB 마이그레이션 (`db.py`)
- DDL에 7개 신규 컬럼 추가
- `_migrate_announcement_profiles`에 반복 구조 마이그레이션 추가
- `_announcement_from_row`에서 `tts_background_music`, `generation_mode` 역직렬화
- `create_announcement`, `update_announcement` CRUD 함수에 신규 필드 반영

### AnnouncementFormModal 재설계 (`call-control/page.tsx`)
- 음원 생성 방식을 2개 버튼으로 선택:
  - **🔊 TTS 음성**: 텍스트 입력 + 배경음악 합성 체크박스(스타일 태그 선택)
  - **🎵 Suno AI 음악**: 가사 입력(자동 생성 버튼) + 스타일 태그 + 음원 생성 버튼 + 결과 미리듣기/선택
- Suno 음원 생성 진행 중 폴링으로 결과 감지 (4초 간격, 최대 30회)
- `StyleTagSelector`, `parseStyleToTags`, `tagsToStyle`, `TAG_CATEGORIES` 컴포넌트를 `call-control/page.tsx`에 추가

### ringback 페이지 정리 (`ringback/page.tsx`)
- 기존 Suno AI 생성 섹션 (섹션 2) 전체 제거
- 안내 카드로 대체: "착신 제어 > 안내멘트로 이동" 링크
- 저장된 음원 목록(섹션 3) → 섹션 2로 번호 변경
- 미사용 상태 변수(genLyrics, genMusic, selectedTags, musicStatus 등), `initAutoStyle`, 가사/스타일/음악 생성 함수 제거
- `StyleTagSelector`, `Badge`, `parseStyleToTags`, `tagsToStyle`, `TAG_CATEGORIES` 제거

## 주요 결정 사항

- **Suno 폴링**: WebSocket 이벤트가 모달 외부에서 발생하므로, 모달 내에서는 주기적 API 폴링으로 결과를 감지함. WebSocket 이벤트를 직접 모달에 주입하는 방식은 복잡도가 높아 제외.
- **배경음 합성 실제 구현**: 현재 DB/모델 저장만 구현. 실제 TTS+배경음 합성은 backend TTS 파이프라인에서 `tts_background_music=True`를 감지하여 처리하도록 향후 구현 필요.
- **`text` 필드 non-null**: Suno 모드에서도 DB `text` 컬럼에 빈 문자열 저장 (NOT NULL 제약 유지).

## 잔여 과제

- 백엔드 TTS 파이프라인에서 `tts_background_music=True`일 때 배경음 합성 처리 구현.
- Suno 음원이 announcement API 저장 후 `suno_audio_url`로부터 음원 파일 다운로드/캐싱 로직 필요.
- ringback 페이지에서 저장된 음원 목록은 여전히 별도 ringback DB를 참조하므로, call-control 안내멘트와 완전히 통합하려면 추가 API 연동 필요.
