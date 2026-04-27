## 개요

통화 연결음 설정의 잔여 과제 2건을 추가 구현했다.
1. KB에 페르소나/인사말 데이터가 없을 때 기본값으로 fallback 처리
2. 음원 local_path를 owner별 DB로 관리하여 재다운로드 방지

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|---|---|---|---|
| `src/services/ringback_service.py` | 수정 | `auto_generate_lyrics()`: KB 빈 경우 `_default_persona()` 사용, `_default_persona()` 함수 추가 | - |
| `src/api/routers/ringback.py` | 수정 | `apply_music()`: `_get_item_local_path()` 로 DB 캐시 확인 후 파일 존재하면 재다운로드 스킵. `_get_item_local_path()` 헬퍼 추가 | - |
| `frontend/app/settings/ringback/page.tsx` | 수정 | `fetchKbGreeting()`: 모든 KB 카테고리 실패 시 기본 인사말 텍스트로 채우기 | - |

## 주요 결정 사항

### 1. KB 없을 때 fallback (kb-default-fallback)

**가사 생성 (`ringback_service.py`)**:
- `_fetch_persona_info()`가 빈 문자열을 반환하면 `_default_persona(owner)` 호출
- 기본 페르소나: owner ID를 업체명으로 사용하는 간단한 설명 텍스트
- LLM은 이 기본 정보로도 일반적인 CM송 가사 생성 가능

**인사말 자동완성 (`page.tsx`)**:
- `greeting_phase1`, `greeting`, `인사말` 카테고리 모두 실패 시 하드코딩 기본 인사말 적용
- 기본값: `"안녕하세요! 전화 주셔서 감사합니다.\n잠시 후 연결해 드리겠습니다."`
- 이미 `greeting_text` 값이 있으면 덮어쓰지 않음 (기존 설정 보호)

### 2. 음원 local_path DB 관리 (audio-path-db-cache)

**`apply-music` 엔드포인트 개선**:
- `item_id`가 주어진 경우 → `_get_item_local_path(item_id, owner)`로 `ringback_music_items.local_path` 조회
- 경로가 존재하고 실제 파일이 있으면(`os.path.isfile`) 다운로드 스킵, 기존 캐시 재사용
- 파일이 없거나 경로 미저장이면 기존대로 다운로드 후 DB에 `local_path` 갱신

**`_get_item_local_path()` 헬퍼**:
- `ringback_music_items` 테이블에서 해당 `id` + `owner`의 `local_path` 반환
- 없거나 오류 시 `None` 반환 → 재다운로드로 fallback

## 잔여 과제
- 없음 (음원 캐시 파일을 운영자가 수동 삭제하면 자동 재다운로드로 복구됨)
