"""ChromaDB 마이그레이션 결과 확인 스크립트"""

import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from src.ai_voicebot.knowledge.chromadb_client import get_vector_db

print("=" * 80)
print("ChromaDB 마이그레이션 결과 확인")
print("=" * 80)

vdb = get_vector_db()
results = vdb.get(limit=10)

print(f"\n총 {len(results['ids'])}건 조회\n")

for i, doc_id in enumerate(results['ids'], 1):
    meta = results['metadatas'][i-1]
    print(f"[{i}] ID: {doc_id}")
    print(f"    doc_type: {meta.get('doc_type', 'N/A')}")
    print(f"    source: {meta.get('source', 'N/A')}")
    print(f"    category: {meta.get('category', 'N/A')}")
    print(f"    owner: {meta.get('owner', 'N/A')}")
    print(f"    created_at: {meta.get('created_at', 'N/A')}")
    print()

# 통계
doc_types = {}
sources = {}
for meta in results['metadatas']:
    dt = meta.get('doc_type', 'N/A')
    src = meta.get('source', 'N/A')
    doc_types[dt] = doc_types.get(dt, 0) + 1
    sources[src] = sources.get(src, 0) + 1

print("=" * 80)
print("통계")
print("=" * 80)
print("\ndoc_type별 분포:")
for dt, count in sorted(doc_types.items()):
    print(f"  {dt}: {count}건")

print("\nsource별 분포:")
for src, count in sorted(sources.items()):
    print(f"  {src}: {count}건")
