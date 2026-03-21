# 지식베이스 화면에 아무것도 안 보일 때 점검

## 1. 실제 데이터가 없는 경우 vs 표시 오류

| 구분 | 의미 | 확인 방법 |
|------|------|-----------|
| **실제로 없음** | ChromaDB에 해당 테넌트(owner)로 저장된 지식이 0건임. API는 200 OK + `{ total: 0, items: [] }` 반환. | 빈 화면에 "API에서 총 **0**건을 반환했습니다" 문구가 보이면, 백엔드가 빈 목록을 정상 반환한 것. |
| **표시 오류** | API는 데이터를 주는데 프론트에서 안 그리거나, 요청/파싱 문제. | 브라우저 개발자 도구 → Network에서 `/api/knowledge` 응답 body에 `total > 0`, `items` 배열에 항목이 있는지 확인. |

## 2. 프론트 ↔ 백엔드 계약

- **요청**: `GET /api/knowledge?tenant_id=sip%3A1004%40unknown&page=1&limit=20`
- **응답**: `{ "total": number, "page": number, "limit": number, "items": KnowledgeItem[] }`
- 백엔드는 `tenant_id`를 `_tenant_id_to_owner()`로 정규화해 Chroma에서 `where: { owner: "1004" }` 로 조회함.

## 3. 직접 API 확인 (curl)

```bash
# 1004 테넌트 목록
curl -s "http://localhost:8000/api/knowledge?tenant_id=sip%3A1004%40unknown&page=1&limit=20"
```

- `total: 0`, `items: []` → **실제로 해당 테넌트에 지식 0건** (통화 추출 또는 POST로 추가 필요).
- `total > 0` 인데 화면에 안 보이면 → **프론트 표시/파싱** 쪽 점검.

## 4. 데이터가 비어 있는 이유

- ChromaDB 지식 컬렉션이 비어 있음.
- 해당 테넌트(owner)로 저장된 문서가 없음 (다른 owner로만 저장됨).
- 지식 추출 파이프라인 또는 `POST /api/knowledge` 로 아직 한 건도 추가하지 않음.

## 5. 적용한 UI 변경

- 빈 목록일 때 **"API에서 총 N건을 반환했습니다. (테넌트: 1004)"** 문구 표시.
- N=0이면 **"실제로 데이터 없음/해당 테넌트 지식 없음"** 안내 및 POST/통화 추출 안내 문구 추가.

이렇게 하면 200 OK인데 아무것도 안 보이는 경우가 **실제 0건**인지 **표시 문제**인지 구분할 수 있음.
