# VectorDB tenant_config 경고 브리핑

## 점검 시 확인할 것

| 확인 항목 | 내용 |
|----------|------|
| **에러 여부** | **에러가 아님.** `level: warning`이며, “설정 없음 → 기본값 사용” 안내용 로그. |
| **not found 의미** | VectorDB에 **owner=1004**용 **tenant_config 문서가 없다**는 뜻. 조회 실패 시 기본 설정으로 진행. |
| **통화 영향** | 통화는 **정상 처리**됨. 인사말·capability 등이 기본값으로 동작. |
| **조치 필요 시** | 1004 전용 인사말/설정을 쓰려면 VectorDB에 1004용 tenant_config를 등록하거나 시드 실행. |

---

## 로그

```text
event: org_manager_tenant_config_not_found
message: "VectorDB에 tenant_config가 없습니다. 기본값 사용."
owner: "1004"
level: warning
```

## 원인

- **org_manager**가 통화의 **owner(테넌트)** 별 설정을 쓰기 위해 **VectorDB(또는 연동 저장소)에서 `tenant_config`를 조회**함.
- **owner=1004**에 해당하는 **tenant_config 문서가 없음** → “없습니다. **기본값 사용**.” 이라고 경고를 남김.
- 즉, **오류가 아니라 “설정 없음 → 기본값으로 진행”** 이라는 의미의 경고.

## 영향

- 해당 통화는 **기본 tenant 설정**으로 동작함 (인사말 문구, capability, RAG 컬렉션 지정 등이 기본값일 수 있음).
- 같은 맥락에서 **org_manager_capabilities_loaded count=0** 이 나오면, 1004용 capability도 VectorDB/설정에 없어서 0건 로드된 상태일 수 있음.

## 해결 방법

1. **1004용 tenant_config 등록**  
   - org_manager가 tenant_config를 **어디에 어떻게** 저장·조회하는지 백엔드 코드/설정 확인.  
   - 일반적으로는 “tenant_config” 컬렉션(또는 동일 용도의 테이블/문서)에 **owner=1004** 문서를 추가하면 됨.  
   - 내용: 인사말, capability 목록, RAG 컬렉션명, 기타 테넌트별 옵션 등(실제 스키마는 구현에 따름).

2. **시드/초기 데이터**  
   - 배포·설치 가이드에 “1004 테넌트용 tenant_config 시드” 스크립트나 수동 등록 절차가 있다면 실행.

3. **기본값 사용이면 괜찮은 경우**  
   - 1004를 “기본 설정으로만 쓸 테넌트”로 둘 거면, **경고만 인지하고 그대로 두어도 됨.**  
   - 다만 인사말/능력(capability) 등을 1004 전용으로 바꾸고 싶다면 위 1·2처럼 **tenant_config를 반드시 넣어야** 함.

## 요약

| 항목 | 내용 |
|------|------|
| **왜 뜨나** | owner=1004에 대한 tenant_config가 VectorDB(또는 연동 저장소)에 없어서. |
| **동작** | 기본값으로 진행되며, 통화는 정상 처리됨. |
| **해결** | 1004용 tenant_config를 VectorDB(해당 컬렉션/스키마)에 등록하거나, 시드 스크립트 실행. |
| **무시 가능 여부** | 기본 설정만 쓰면 경고만 인지하고 무시 가능; 1004 전용 설정을 쓰려면 반드시 등록 필요. |
