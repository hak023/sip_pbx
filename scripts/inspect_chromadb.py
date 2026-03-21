"""ChromaDB 컬렉션 내용을 읽어서 출력. (경량: chromadb만 사용)"""
import os
import sys
import json

# 프로젝트 루트
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ["ANONYMIZED_TELEMETRY"] = "False"
os.environ["CHROMA_TELEMETRY"] = "False"

def main():
    import chromadb
    from chromadb.config import Settings
    persist = os.path.join(os.path.dirname(__file__), "..", "data", "chromadb")
    persist = os.path.normpath(os.path.abspath(persist))
    if not os.path.isdir(persist):
        print("ChromaDB 디렉토리가 없습니다:", persist)
        print("시드 데이터를 한 번 실행하면 생성됩니다.")
        return
    client = chromadb.PersistentClient(path=persist, settings=Settings(anonymized_telemetry=False))
    try:
        col = client.get_collection("knowledge_base")
    except Exception as e:
        print("knowledge_base 컬렉션 없음:", e)
        return
    n = col.count()
    print("=== knowledge_base 문서 수:", n, "===\n")
    if n == 0:
        return
    res = col.get(limit=min(300, n), include=["documents", "metadatas"])
    ids = res.get("ids", [])
    docs = res.get("documents", [])
    metas = res.get("metadatas", [{}] * len(ids))
    for i, (doc_id, text, meta) in enumerate(zip(ids, docs, metas)):
        doc_type = meta.get("doc_type", "")
        owner = meta.get("owner", "")
        cat = meta.get("category", "")
        print("---")
        print("id:", doc_id)
        print("doc_type:", doc_type, "| owner:", owner, "| category:", cat)
        print("text:", text or "")
        if doc_type == "tenant_config":
            gt = meta.get("greeting_templates", "")
            ct = meta.get("closing_templates", "")
            # greeting_templates (항상 출력)
            if gt:
                try:
                    arr = json.loads(gt) if isinstance(gt, str) else gt
                    print("greeting_templates:", arr)
                except Exception:
                    print("greeting_templates: (JSON)", len(str(gt)), "chars")
            else:
                print("greeting_templates: (없음)")
            # closing_templates (항상 출력 — 없으면 (없음) 표시)
            if ct:
                try:
                    arr = json.loads(ct) if isinstance(ct, str) else ct
                    print("closing_templates:", arr)
                except Exception:
                    print("closing_templates: (JSON)", len(str(ct)), "chars")
            else:
                print("closing_templates: (없음)")
        print()
    # qa_cache if exists
    try:
        cache = client.get_collection("qa_cache")
        nc = cache.count()
        print("=== qa_cache 문서 수:", nc, "===\n")
    except Exception:
        pass

if __name__ == "__main__":
    main()
