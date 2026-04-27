---
작성일: 2026-04-23
상태: 완료
관련: `sip-pbx/frontend/app/settings/call-control/page.tsx`, `sip-pbx/src/api/routers/ringback.py`, `sip-pbx/src/services/ringback_service.py`
---

## 개요

통화 연결음(Suno) 모달에서 「자동 가사 생성」 흐름을 개편했다. 운영자가 **AI 생성 요청사항** 텍스트를 넣으면 가사 생성 시 반영하고, 스타일 태그는 같은 맥락(요청사항·가사)으로 LLM이 제안하도록 API·UI를 맞췄다. 프리셋 옆 **무작위 스타일**은 요청사항과 무관하게 서버 랜덤 태그만 받도록 프론트에서 본문을 분리했다(이전에는 요청란에 글이 있으면 무작위도 맥락 반영이 섞였음).

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `sip-pbx/src/api/routers/ringback.py` | 수정 | `generate-lyrics`에 `brief`, `generate-style`에 `brief`·`lyrics` 옵션 | 설계대로 |
| `sip-pbx/src/services/ringback_service.py` | 수정 | 가사 프롬프트에 운영자 brief 블록, 스타일은 brief·가사 기반 LLM 한 줄·폴백 | 설계대로 |
| `sip-pbx/frontend/app/settings/call-control/page.tsx` | 수정 | 요청사항 영역, 가사만·스타일만·연속 생성 버튼, `doGenStyleFromContext` / `doGenStyleRandom` 분리 | 설계대로 |

## 주요 결정 사항

- **스타일 두 경로**: (1) AI 블록의 「스타일만 제안」·「가사+스타일 연속」은 `brief`+`lyrics`를 `generate-style`에 넘김. (2) 프리셋 행의 「무작위 스타일」은 `vocal_gender`·`duration_target`만 전송해 항상 기존 랜덤 태그 동작과 일치.
- **호환**: `generate-style` 응답에 `used_llm`이 있어도 클라이언트는 `style`만 사용하면 됨.

## 잔여 과제 (선택)

- 스타일 LLM 실패 시 UI에 「폴백(랜덤) 적용」 여부를 짧게 알려주면 운영자 혼란이 줄어듦.
