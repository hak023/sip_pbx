# 대시보드 실시간 STT “인식 중” 누적 표시 개선

- **작성일**: 2026-03-26 (로컬)
- **상태**: 구현 완료
- **파일**: `sip-pbx/frontend/app/dashboard/page.tsx`

## 증상

중간(interim) STT가 `기. 기상. 기상감정…` 형태로 **한 줄에 마침표로 이어 붙여** 보이거나, 임시 줄 갱신이 안 되어 **덧붙인 것처럼** 보임.

## 원인

1. **백엔드/Google**가 중간 가설을 **마침표로 구분한 누적 문자열**로 한 번에 보내는 경우가 있음 → UI가 “교체”만 해도 누적 전체가 그대로 표시됨.
2. **구분자 유니코드**: 실제 문자열에 **U+FF0E(．) 전각 마침표** 등이 섞이면, 프론트가 `.` / `。` 만 split 하면 **한 덩어리로 남아** “현재. 현재 발. …” 전체가 한 줄에 붙어 보임 (2026-03 재현).
3. `appendLiveFeed`에서 임시 줄 갱신 조건이 `last.isFinal === false`만 인정 → 과거/직렬화 등으로 `undefined`이면 **새 카드가 계속 추가**될 수 있음.

## 조치

1. **`pickInterimSttDisplay(raw)`**  
   - `is_final`이 아닐 때만 적용.  
   - `U+002E .` / `U+3002 。` / **`U+FF0E ．`** / `U+FF61 ｡` / `U+FE52` 및 `,·•` 등으로 쪼개 **마지막 비어 있지 않은 조각**을 표시(마지막이 1글자면 이전 조각과 결합).  
   - 확정 STT에는 적용하지 않음.

2. **`appendLiveFeed`**  
   - `isFinal`을 명시적 boolean으로 저장 (`isFinal === true`만 확정).  
   - 확정 시·임시 갱신 시 **`row.isFinal !== true`** 로 미확정 줄 매칭.

3. **`stt_transcript` 소켓 핸들러**  
   - `!isFinal`이면 `text = pickInterimSttDisplay(text)` 후 `appendLiveFeed`.  
   - `is_final` 외 `isFinal`(camelCase)도 확정으로 인정.

## 한계

- 문장 중간에 오는 마침표(소수점·약어 등)는 STT 문맥에서 드물지만, 잘못 쪼개질 수 있음.  
- 근본적으로 **서버가 순수 “현재 가설 한 덩어리”만내면** 프론트 후처리 부담이 줄어듦.
