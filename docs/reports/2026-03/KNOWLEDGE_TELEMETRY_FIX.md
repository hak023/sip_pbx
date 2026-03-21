# 지식 베이스 텔레메트리 오류 조치

## 현상

지식 베이스 API(`GET /api/knowledge` 등) 사용 시 콘솔에 다음 오류가 반복 출력됨:

```
Failed to send telemetry event ClientStartEvent: capture() takes 1 positional argument but 3 were given
Failed to send telemetry event ClientCreateCollectionEvent: capture() takes 1 positional argument but 3 were given
```

- **API 동작**: `GET /api/knowledge`는 **200 OK**로 정상 응답하며, 지식 목록/추가/검색 기능에는 영향 없음.
- **원인**: ChromaDB가 사용하는 PostHog 텔레메트리 SDK가 v6.0.0에서 API 변경(`capture()` 시그니처)을 했고, ChromaDB는 구버전 호출 방식을 사용해 호환 문제가 발생함.  
  - Chroma 이슈: [chroma-core/chroma#4966](https://github.com/chroma-core/chroma/issues/4966), [#4997](https://github.com/chroma-core/chroma/issues/4997)

## 적용한 조치

1. **텔레메트리 로그 억제** (`src/ai_voicebot/knowledge/chromadb_client.py`)
   - `chromadb.telemetry`, `chromadb.telemetry.product.posthog` 로거 레벨을 `CRITICAL`로 설정.
   - 동일 오류가 발생해도 콘솔에 "Failed to send telemetry event"가 출력되지 않도록 함.

2. **설정 유지**
   - Chroma 클라이언트 생성 시 이미 `Settings(anonymized_telemetry=False)` 사용 중.

## 권장 (오류 근본 제거)

PostHog를 6.0 미만으로 고정하면 텔레메트리 호출 자체가 정상 동작하여 오류가 사라짐:

```bash
pip install 'posthog<6.0.0'
```

의존성 파일(requirements 등)을 사용하는 경우 해당 파일에 `posthog<6.0.0`을 추가해 두는 것을 권장함.

## 점검

- 지식 베이스 화면에서 목록 조회 시 **200 OK** 유지.
- 콘솔에 **"Failed to send telemetry event"** 메시지가 더 이상 출력되지 않는지 확인.
