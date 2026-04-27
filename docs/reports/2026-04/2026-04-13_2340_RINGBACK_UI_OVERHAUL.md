## 개요

통화 연결음 설정 페이지(`ringback/page.tsx`)의 8가지 UX 문제를 점검·수정했다. 프론트엔드 전면 재작성과 백엔드 서비스 소규모 수정이 주된 변경 내용이다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|---|---|---|---|
| `frontend/app/settings/ringback/page.tsx` | 수정 (전면 재작성) | 8가지 UX 개선 사항 일괄 적용 | - |
| `src/services/ringback_service.py` | 수정 | `_fetch_persona_info()` KB 카테고리 fallback 추가 및 로그 보강 | - |

## 주요 결정 사항

### 1. KB 인사말 자동완성 (kb-greeting-fix)
- `fetchKbGreeting()`이 `greeting_phase1` 하나만 시도하다 실패 시 자동완성 안 됨 → `["greeting_phase1", "greeting", "인사말"]` 순서로 fallback
- `limit` 파라미터는 서버가 무시하므로 제거

### 2. 체크박스 즉시 저장 (checkbox-auto-save)
- 인사말 "사용" 체크박스 onChange에서 즉시 `PUT /api/ringback/settings` 호출
- 통화 연결음(enabled_ringback)은 음원 목록의 "사용"/"사용 안함" 버튼으로만 제어

### 3. Suno AI 브랜딩 제거 (remove-suno-branding)
- 섹션 2 헤더 `"통화 연결음 생성 (Suno AI)"` → `"통화 연결음 생성"`
- "음원 제목" 입력 필드 제거 (title은 기본값 `"통화 연결음"` 사용)

### 4. 성별/목표 시간 UI 제거 (remove-gender-duration)
- 스타일 태그의 "Vocal", "길이" 카테고리로 대체하여 UI 단순화
- 백엔드 `GenerateStyleRequest`/`GenerateMusicRequest`는 기본값 유지 (하위 호환)

### 5. StyleTagSelector 컴포넌트 신설 (style-tag-selector)
- 6개 카테고리(장르·분위기·Vocal·CM송·BPM·길이) 태그 클릭 선택 UI
- 단일/복수 선택 구분, 선택 태그 자동으로 `suno_style` 문자열 조합
- 페이지 초기 로드 시 `generate-style` API 호출로 기본값 자동 선택
- 저장된 스타일 문자열이 있으면 파싱하여 선택 상태 복원

### 6. 음원 목록에서 사용/비활성화 관리 (enabled-ringback-from-list)
- 섹션 2의 `enabled_ringback` 체크박스 제거
- 섹션 3 "사용" 버튼 → `apply-music` 완료 후 `enabled_ringback=true` 자동 저장
- "사용 안함" 버튼 추가 → `enabled_ringback=false` 저장

### 7. 페르소나 로그 보강 (lyrics-auto-gen-log)
- `_fetch_persona_info()`에 카테고리별 조회 결과 count 로그(`ringback_persona_kb_fetch`)와 전체 합산 로그(`ringback_persona_fetch_done`) 추가
- 카테고리 목록: `greeting_phase1`, `greeting`, `persona`, `business_info`

### 8. 음원 목록 표시 개선 (title-to-lyrics-display)
- `resolveItemLabel()` 함수 추가: title이 "통화 연결음" 등 기본값이면 `"생성 N (task_id 앞 8자)"` 형태로 표시

## 잔여 과제
- 실제 KB에 `persona`/`business_info` 카테고리 데이터가 충분히 있어야 페르소나 반영 가능. 없다면 지식관리에서 해당 카테고리 데이터 등록 필요.
- `suno_audio_path` 파일이 삭제되거나 서버 재시작 시 재다운로드 필요 (현행 유지).
