# 지식 그룹(hop 클러스터) 실데이터 검증 — owner=9001

- 작성일: 2026-08-06
- 상태: 검증 완료 — 실데이터 확인 중 실제 버그 1건 발견·수정
- 관련 문서: [Story 1.49](../../stories/1.49.unified-knowledge-detail-panel.story.md),
  [2026-08-06_story_1.48_to_1.50_kb_unified_view_implementation.md](2026-08-06_story_1.48_to_1.50_kb_unified_view_implementation.md)

## 요청 배경

사용자가 "화면에서 봐도 뭐가 바뀐지 모르겠다, 일반 문서·설정·화면안내가 실제로 매칭이 안 되는
구조인 거 아니냐"고 의심해, 실제 owner=9001 API 응답을 직접 조회해 검증했다(서버는 이미
기동 중이었음, `localhost:8000`).

## 1. 실제 조회 결과 요약

`GET /api/settings/ai-assistant/docs?owner=9001` → 52건, `related_domain` 기준 분포:

| related_domain    | 건수 | section_title                                       |
| ----------------- | ---- | --------------------------------------------------- |
| `ai-escalation`   | 6    | AI 에스컬레이션 설정 (AI가 모를 때 어떻게 처리할지) |
| `intro`           | 3    | 서비스 소개                                         |
| `self-service`    | 3    | 셀프서비스 AI 도우미 자체 사용법 (메타 안내)        |
| `booking`         | 12   | 예약 관리                                           |
| `operator-status` | 5    | 운영자 부재중 모드                                  |
| `call-control`    | 16   | 착신 제어 (전화가 왔을 때 누가·어떻게 받을지)       |
| `chat-relay`      | 3    | 채팅(SIP 문자) 자동응답                             |
| `onboarding`      | 2    | 초기 설정 체크리스트                                |
| `call-history`    | 2    | 통화 이력 확인                                      |

`GET /api/settings/ai-assistant/catalog` → 7개 도메인: `persona`, `ai-escalation`,
`call-control`, `chat-relay`, `contacts`, `general`, `integrations`. 이 중 **`general`은
`related_manual_domains: ["intro"]`**로 명시(자기 자신의 domain 문자열이 아니라 다른 문자열을
가리킴).

`GET /api/settings/ai-assistant/screen-graph` → 6개 화면: `ai-escalation`, `chat-relay`,
`call-control`, `general`, `integrations`(→`/settings/general`로 리다이렉트), `contacts`.

## 2. 발견된 실제 버그 — `related_manual_domains`를 무시하고 있었음

`GET /api/settings/ai-assistant/domain-hop-path?domain=general&owner=9001` 응답을 직접
호출해보면 `general` → `intro`로 가는 간선이 **그래프 자체에 존재하지 않는다**(전용
"catalog_domain 서로 다른 문자열 간 별칭(alias)" 개념이 지식 그래프에 없음). 즉:

- qa 문서는 `related_domain: "intro"`로 색인됨
- 설정 카탈로그는 `domain: "general"`(카탈로그 API가 `related_manual_domains: ["intro"]`로
  이 둘의 연결을 **명시적으로 알려주고 있음**)
- 그러나 `KnowledgeClusterTable`의 클러스터링 로직은 **hop 그래프의 간선만** Union-Find로
  묶었고, 카탈로그 API가 이미 제공하는 `related_manual_domains` 힌트는 전혀 사용하지 않았다.

**결과**: "일반 설정(intro/general)" 그룹은 실제로는 Q&A(intro)와 설정(general)이 같은
주제인데도 **서로 다른 클러스터로 쪼개져 표시되고 있었다** — 사용자가 의심한 "매칭이 안 되는
구조"가 실제로 존재하는 버그였음을 확인.

### 수정

`buildClusters()`에 아래를 추가해, 카탈로그가 스스로 선언한 `related_manual_domains`를
hop 그래프 간선과 동일하게 Union-Find로 묶도록 했다(`KnowledgeClusterTable.tsx`):

```ts
for (const c of catalogDomains) {
  for (const manualDomain of c.related_manual_domains || []) {
    uf.union(`catalog_domain:${c.domain}`, `catalog_domain:${manualDomain}`);
  }
}
```

수정 후에는 `general`(설정)과 `intro`(매뉴얼 Q&A)가 같은 클러스터로 묶인다.

## 3. 나머지 도메인 — "매칭 안 됨"이 아니라 애초에 대응 카탈로그/화면이 없음

`booking`/`self-service`/`operator-status`/`onboarding`/`call-history`는 카탈로그 API·
화면 안내 API 어디에도 대응 항목이 없다(직접 확인: `domain-hop-path?domain=booking` 호출
결과 `intent_type` 노드로 가는 간선만 있고 `frontend_screen`/다른 `catalog_domain`으로 가는
간선은 없음). 이건 버그가 아니라 **애초에 이 도메인들이 "설정 카탈로그"로 등록되어 있지
않기 때문**(예: 예약 관리는 별도 화면·API 체계를 쓰고, 이 카탈로그는 7개 도메인만 관리).
이런 항목은 클러스터 테이블에서 Q&A만 있는 단독 그룹으로 표시되는 것이 올바른 동작이다.

## 4. 수정 후 실제 클러스터링 결과(수동 재현)

owner=9001 데이터를 코드 로직 그대로 손으로 재현한 결과:

| 클러스터(대표 도메인)             | 포함 Q&A                                    | 포함 설정                                   | 포함 화면                 |
| --------------------------------- | ------------------------------------------- | ------------------------------------------- | ------------------------- |
| `ai-escalation`                   | AI 에스컬레이션 설정 Q&A 6건                | `ai-escalation`(AI 변경 가능, 변경 시 신중) | AI 에스컬레이션 설정 화면 |
| `chat-relay`                      | 채팅 자동응답 Q&A 3건                       | `chat-relay`(AI 변경 가능)                  | 채팅 자동응답 설정 화면   |
| `call-control`                    | 착신 제어 Q&A 16건                          | `call-control`(조회 전용)                   | 착신 제어 설정 화면       |
| `general` + `intro`(수정 후 병합) | 서비스 소개 Q&A 3건                         | `general`(조회 전용)                        | 일반 설정 화면            |
| `contacts`                        | (매칭 Q&A 없음)                             | `contacts`(조회 전용)                       | 연락처 관리 화면          |
| `integrations`                    | (매칭 Q&A 없음, `general`과 같은 화면 공유) | `integrations`(조회 전용)                   | 일반 설정(연동) 화면      |
| `persona`                         | (매칭 Q&A 없음)                             | `persona`(AI 변경 가능)                     | (대응 화면 없음)          |
| `booking`(단독)                   | 예약 관리 Q&A 12건                          | —                                           | —                         |
| `self-service`(단독)              | 셀프서비스 안내 Q&A 3건                     | —                                           | —                         |
| `operator-status`(단독)           | 운영자 부재중 모드 Q&A 5건                  | —                                           | —                         |
| `onboarding`(단독)                | 초기 설정 체크리스트 Q&A 2건                | —                                           | —                         |
| `call-history`(단독)              | 통화 이력 확인 Q&A 2건                      | —                                           | —                         |

## 5. 검증

- `npx tsc --noEmit` 0에러(수정 반영 후).
- 위 클러스터링은 실제 API 응답(owner=9001)을 기준으로 손으로 재현한 것이며, 브라우저
  실행 확인(실서버 IV)은 아직 하지 않았다 — 다음 단계로 실제 화면에서 `general`/`intro`가
  하나로 묶여 보이는지 확인이 필요하다.

## 6. 2026-08-06 브라우저 실검증 — 두 번째 실제 버그 발견·수정(중대)

사용자가 "서버 재시작 안 했는데 브라우저에서 봐도 동일하다"고 재차 지적해, 통합 브라우저
도구로 `localhost:3000/settings/ai-assistant/docs`를 직접 열어(`localStorage.tenant_id=9001`
설정) 실제 렌더링 결과를 확인했다.

**발견**: 13개 도메인 전부가 **단 1개의 거대한 그룹으로 뭉쳐서** 표시되고 있었다
(`"AI 에스컬레이션 · 서비스 소개 · 셀프서비스 · 예약 관리 · 운영자 상태 · 착신 제어 · …
Q&A 9건 · 설정 7건 · 화면 6건 · hop 83단계"`). 이전 리포트(§4)의 "수동 재현" 예측과 전혀
다른, 실제로는 훨씬 심각한 버그였다.

**근본 원인**: `buildClusters()`의 Union-Find가 hop 그래프의 **모든** 간선 유형을 그대로
union했는데, `writable: catalog_domain → intent_type` 간선은 거의 모든 도메인이 공통으로
연결되는 IntelliDecision 유형(A/C/F/H/I 등)을 향한다 — 즉 `intent_type:A` 같은 노드가
"공유 허브"가 되어, 서로 전혀 무관한 도메인들이 이 허브를 통해 전이적으로(transitively)
하나의 거대 클러스터로 합쳐졌다. 실제 `GET /domain-hop-path?domain=ai-escalation`과
`?domain=general` 응답을 비교해보면 둘 다 `intent_type:A`, `intent_type:C` 등으로 가는
`writable` 간선을 공통으로 갖고 있어 Union-Find가 이 둘을 같은 뿌리로 묶어버렸다.

**수정**: 클러스터링(Union-Find)과 그룹 상세에 표시하는 hop 간선 모두 `edge_type ===
"rendered_by"`(도메인→화면 연결)인 것만 사용하도록 필터링(`KnowledgeClusterTable.tsx`).
`writable`(IntelliDecision 유형 메타데이터)은 애초에 "이 지식이 어떤 화면/설정과
연결되는지"와 무관한 정보라 클러스터링·표시 어느 쪽에도 부적절했다.

**수정 후 실제 결과**(owner=9001, 브라우저 실행 확인): 11개 그룹으로 정상 분리됨 —
`서비스 소개·일반 설정·외부 연동`(3개 도메인 병합, `related_manual_domains` 힌트로 정상
연결), `AI 에스컬레이션`, `착신 제어`, `채팅 자동응답`, `연락처`, `페르소나`(설정만) 및
대응 카탈로그·화면이 없는 `셀프서비스`/`예약 관리`/`운영자 상태`/`초기 설정`/`통화 이력`
단독 그룹(§3의 "매칭 없음이 아니라 원래 없음" 설명 그대로).

`AI 에스컬레이션` 그룹을 펼쳐 확인한 실제 렌더링 내용이 사용자가 제시한 예시 형식과
정확히 일치함을 확인:
- Q&A 6건이 카테고리 라벨 없이 이어짐
- 화면 안내: "AI 에스컬레이션 설정 `ai-escalation` /settings/ai-escalation" + 설명 +
  "radio, AI가 모를 때 처리 방식 — 운영자 알림(hitl), 상담원 직접 연결(transfer),
  에스컬레이션 안 함(none)"
- 설정: "AI 에스컬레이션 `ai-escalation` AI 변경 가능 변경 시 신중" + `escalation_mode`
  `transfer_extension` + "조회 필드: transfer_extension, persona_exists"

`npx tsc --noEmit` 재검증 0에러.

*최종 업데이트: 2026-08-06*
