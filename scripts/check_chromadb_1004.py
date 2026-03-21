"""
ChromaDB 1004 테넌트 데이터 점검 스크립트.

지식 컬렉션 경로, 전체 문서 수, owner=1004 문서 수·샘플을 출력합니다.
API·시드와 동일한 경로(data/chroma)를 사용합니다.

실행 (sip-pbx 디렉터리에서):
  python scripts/check_chromadb_1004.py
"""
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

OWNER_1004 = "1004"


def main():
    from src.ai_voicebot.knowledge.chromadb_client import (
        get_chroma_persist_path,
        get_vector_db,
        KNOWLEDGE_COLLECTION,
    )

    path = get_chroma_persist_path()
    print(f"ChromaDB 경로: {path}")
    print(f"컬렉션: {KNOWLEDGE_COLLECTION}")
    if not Path(path).exists():
        print("경고: 해당 경로가 없습니다. 시드 또는 API로 데이터를 먼저 추가하세요.")
        return 1

    vector_db = get_vector_db()
    if not vector_db:
        print("오류: ChromaDB를 초기화할 수 없습니다. (경로·의존성 확인)")
        return 1

    # 전체 문서 수 (where 없음)
    raw_any = vector_db.get(where=None, limit=10000)
    ids_any = raw_any.get("ids", [])
    total = len(ids_any)
    print(f"\n컬렉션 전체 문서 수: {total}")

    # owner=1004 문서
    raw_1004 = vector_db.get(where={"owner": OWNER_1004}, limit=10000)
    ids_1004 = raw_1004.get("ids", [])
    docs_1004 = raw_1004.get("documents", [])
    metas_1004 = raw_1004.get("metadatas", [])
    count_1004 = len(ids_1004)
    print(f"owner={OWNER_1004} 문서 수: {count_1004}")

    if count_1004 == 0 and total > 0:
        # 다른 owner 값 샘플 확인
        sample_meta = (raw_any.get("metadatas") or [])
        owners = set()
        for m in sample_meta[:50]:
            if isinstance(m, dict) and m.get("owner"):
                owners.add(m["owner"])
        print(f"  참고: 컬렉션 내 다른 owner 샘플: {owners or '(없음)'}")

    if count_1004 > 0:
        print("\n[owner=1004 샘플 3건]")
        for i in range(min(3, count_1004)):
            doc = docs_1004[i] if i < len(docs_1004) else ""
            meta = metas_1004[i] if i < len(metas_1004) else {}
            cat = meta.get("category", "")
            print(f"  {i+1}. id={ids_1004[i]}, category={cat}, text={doc[:60]}...")

    print("\n점검 완료.")
    return 0 if vector_db else 1


if __name__ == "__main__":
    sys.exit(main())
