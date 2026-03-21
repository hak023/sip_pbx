# 지식베이스 API "Failed to fetch" 안내

## 현상

지식베이스 API에 접근(브라우저 또는 스크립트) 시 **Failed to fetch** 에러가 발생합니다.

## 원인

- 현재 워크스페이스에서 **`/api/knowledge` HTTP 라우트를 정의한 백엔드 코드가 없습니다.**
- `sip-pbx/scripts/seed_knowledge_1004_via_api.py`는 `POST {base_url}/api/knowledge`를 **호출하는 클라이언트**만 있으며, 이 엔드포인트를 제공하는 서버 쪽 코드는 검색 결과 없음.
- 프론트엔드 대시보드는 `NEXT_PUBLIC_API_URL`(기본 `http://localhost:8000`)로 `/api/calls/active`, `/api/metrics/dashboard` 등을 호출합니다. 지식베이스용 페이지/기능이 같은 호스트의 `/api/knowledge`를 호출한다면, 해당 라우트가 서버에 없어 **Failed to fetch**(404 또는 연결 실패)가 발생할 수 있습니다.

## 가능한 추가 원인

- **CORS**: 백엔드가 다른 포트/도메인에서 동작할 때 CORS 미설정이면 브라우저에서 "Failed to fetch"로 보일 수 있음.
- **네트워크/연결**: 서버 미기동, 방화벽, 잘못된 `API_URL` 등.

## 권장 조치

1. **백엔드에 `/api/knowledge` 구현**
   - `POST /api/knowledge`: tenant_id, text, category, keywords 등으로 지식 항목 추가(ChromaDB 등 VectorDB 저장).
   - (필요 시) `GET /api/knowledge?tenant_id=1004`: 목록/검색.
   - 실제로 app.log를 생성하는 SIP·AI 백엔드가 다른 저장소/경로에 있다면, 그 프로젝트에서 해당 라우트가 정의돼 있는지 확인하고, 없다면 동일 스펙으로 추가.

2. **API 서버 기동 여부 확인**
   - `seed_knowledge_1004_via_api.py`는 기본 `http://localhost:8000`을 사용. 8000 포트에서 해당 API를 제공하는 프로세스가 떠 있는지 확인.

3. **프론트엔드 호출 URL 확인**
   - 지식베이스 UI가 사용하는 `API_URL`(예: `NEXT_PUBLIC_API_URL`)이 실제 백엔드 주소와 일치하는지 확인.

## 참고

- 시드 스크립트: `sip-pbx/scripts/seed_knowledge_1004_via_api.py`
- 기대 스펙(스크립트 기준): `POST /api/knowledge`, JSON body `tenant_id`, `text`, `category`, `keywords`, `confidence`, `call_id`.
