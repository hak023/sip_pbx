"""
ChromaDB 지식 메타데이터 마이그레이션 스크립트

기존 데이터에 doc_type, source, created_at 필드를 추가하여
KNOWLEDGE_DOC_TYPE_DESIGN 스키마와 호환되도록 업데이트합니다.

실행 방법:
  python scripts/migrate_knowledge_metadata.py [--dry-run] [--force]

옵션:
  --dry-run: 실제로 업데이트하지 않고 변경 내용만 출력
  --force: 확인 없이 즉시 마이그레이션 실행
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from src.ai_voicebot.knowledge.chromadb_client import (
    get_vector_db,
    KNOWLEDGE_COLLECTION,
)


def infer_doc_type_from_metadata(metadata: Dict[str, Any]) -> str:
    """기존 메타데이터로부터 doc_type 추론"""
    # 이미 doc_type이 있으면 사용
    if metadata.get("doc_type"):
        return metadata["doc_type"]
    
    # capability인 경우
    if metadata.get("response_type") or metadata.get("display_name"):
        return "capability"
    
    # tenant_config인 경우
    if metadata.get("tenant_name") or metadata.get("tenant_type"):
        return "tenant_config"
    
    # category가 faq인 경우
    if metadata.get("category") == "faq":
        return "faq"
    
    # 기본값: knowledge
    return "knowledge"


def infer_source_from_metadata(metadata: Dict[str, Any], doc_id: str) -> str:
    """기존 메타데이터로부터 source 추론"""
    # 이미 source가 있으면 사용
    if metadata.get("source"):
        return metadata["source"]
    
    # doc_id 패턴으로 추론
    if doc_id.startswith("hitl_"):
        return "hitl"
    elif doc_id.startswith("kb_seed_") or doc_id.startswith("faq_seed_"):
        return "seed"
    elif doc_id.startswith("cap_"):
        return "seed"  # capability는 대부분 시드
    elif doc_id.startswith("tenant_config_"):
        return "seed"
    elif "call" in metadata.get("call_id", "").lower() or metadata.get("call_id"):
        return "call"
    
    # 기본값: api (수동 입력으로 간주)
    return "api"


def migrate_knowledge_metadata(dry_run: bool = False, force: bool = False) -> Dict[str, int]:
    """ChromaDB knowledge 컬렉션의 메타데이터 마이그레이션
    
    Args:
        dry_run: True이면 실제 업데이트 없이 분석만 수행
        force: True이면 확인 없이 즉시 실행
        
    Returns:
        {"total": int, "updated": int, "skipped": int, "errors": int}
    """
    print("=" * 80)
    print("ChromaDB 지식 메타데이터 마이그레이션")
    print("=" * 80)
    print(f"모드: {'DRY-RUN (실제 변경 없음)' if dry_run else 'LIVE (실제 변경)'}")
    print()
    
    # VectorDB 연결
    print("[1/5] ChromaDB 연결 중...")
    try:
        vector_db = get_vector_db()
        collection = vector_db.collection
        print(f"[OK] 컬렉션 연결 성공: {KNOWLEDGE_COLLECTION}")
    except Exception as e:
        print(f"[ERROR] ChromaDB 연결 실패: {e}")
        return {"total": 0, "updated": 0, "skipped": 0, "errors": 1}
    
    # 전체 데이터 조회
    print("\n[2/5] 기존 데이터 조회 중...")
    try:
        results = collection.get(
            limit=10000,
            include=["documents", "metadatas", "embeddings"]
        )
        total = len(results.get("ids", []))
        print(f"[OK] 총 {total}건의 문서 발견")
    except Exception as e:
        print(f"[ERROR] 데이터 조회 실패: {e}")
        return {"total": 0, "updated": 0, "skipped": 0, "errors": 1}
    
    if total == 0:
        print("[INFO] 마이그레이션할 데이터가 없습니다.")
        return {"total": 0, "updated": 0, "skipped": 0, "errors": 0}
    
    # 분석
    print("\n[3/5] 메타데이터 분석 중...")
    ids = results["ids"]
    documents = results.get("documents", [])
    metadatas = results.get("metadatas", [])
    embeddings = results.get("embeddings", [])
    
    needs_update = []
    already_complete = []
    
    for i, doc_id in enumerate(ids):
        metadata = metadatas[i] if i < len(metadatas) else {}
        
        # 이미 모든 필드가 있는지 확인
        has_doc_type = "doc_type" in metadata and metadata["doc_type"]
        has_source = "source" in metadata and metadata["source"]
        has_created_at = "created_at" in metadata and metadata["created_at"]
        
        if has_doc_type and has_source:
            already_complete.append(doc_id)
        else:
            needs_update.append({
                "id": doc_id,
                "index": i,
                "metadata": metadata,
                "inferred_doc_type": infer_doc_type_from_metadata(metadata),
                "inferred_source": infer_source_from_metadata(metadata, doc_id),
                "has_doc_type": has_doc_type,
                "has_source": has_source,
                "has_created_at": has_created_at,
            })
    
    print(f"[OK] 분석 완료:")
    print(f"  - 업데이트 필요: {len(needs_update)}건")
    print(f"  - 이미 완료: {len(already_complete)}건")
    
    if len(needs_update) == 0:
        print("\n[INFO] 모든 데이터가 이미 최신 스키마입니다.")
        return {"total": total, "updated": 0, "skipped": total, "errors": 0}
    
    # 샘플 출력
    print("\n[SAMPLE] 업데이트 예시 (최대 5개):")
    for item in needs_update[:5]:
        print(f"\n  ID: {item['id']}")
        print(f"    현재 category: {item['metadata'].get('category', 'N/A')}")
        print(f"    현재 owner: {item['metadata'].get('owner', 'N/A')}")
        if not item['has_doc_type']:
            print(f"    추가할 doc_type: {item['inferred_doc_type']}")
        if not item['has_source']:
            print(f"    추가할 source: {item['inferred_source']}")
        if not item['has_created_at']:
            print(f"    추가할 created_at: (현재 시각)")
    
    if len(needs_update) > 5:
        print(f"\n  ... 외 {len(needs_update) - 5}건")
    
    # 확인
    if not dry_run and not force:
        print("\n[4/5] 확인")
        response = input(f"\n{len(needs_update)}건의 문서를 업데이트하시겠습니까? (yes/no): ").strip().lower()
        if response not in ("yes", "y"):
            print("[CANCEL] 사용자에 의해 취소되었습니다.")
            return {"total": total, "updated": 0, "skipped": total, "errors": 0}
    else:
        print("\n[4/5] 확인 단계 건너뜀" + (" (dry-run)" if dry_run else " (force)"))
    
    # 업데이트 실행
    print("\n[5/5] 메타데이터 업데이트 중...")
    updated_count = 0
    error_count = 0
    current_time = datetime.now().isoformat()
    
    for item in needs_update:
        doc_id = item["id"]
        index = item["index"]
        old_metadata = item["metadata"]
        
        # 새 메타데이터 구성
        new_metadata = dict(old_metadata)
        
        if not item["has_doc_type"]:
            new_metadata["doc_type"] = item["inferred_doc_type"]
        
        if not item["has_source"]:
            new_metadata["source"] = item["inferred_source"]
        
        if not item["has_created_at"]:
            # 기존 created_at이 있으면 유지, 없으면 현재 시각
            new_metadata["created_at"] = old_metadata.get("created_at", current_time)
        
        if dry_run:
            print(f"  [DRY-RUN] {doc_id}: doc_type={new_metadata['doc_type']}, source={new_metadata['source']}")
            updated_count += 1
        else:
            try:
                # upsert로 메타데이터만 업데이트
                collection.upsert(
                    ids=[doc_id],
                    embeddings=[embeddings[index]],
                    documents=[documents[index]],
                    metadatas=[new_metadata],
                )
                updated_count += 1
                if updated_count % 10 == 0:
                    print(f"  진행 중... {updated_count}/{len(needs_update)}")
            except Exception as e:
                print(f"  [ERROR] ({doc_id}): {e}")
                error_count += 1
    
    # 결과 출력
    print("\n" + "=" * 80)
    print("마이그레이션 완료")
    print("=" * 80)
    print(f"총 문서: {total}건")
    print(f"업데이트{'(예정)' if dry_run else ''}: {updated_count}건")
    print(f"건너뜀: {len(already_complete)}건")
    print(f"오류: {error_count}건")
    
    if dry_run:
        print("\n[INFO] DRY-RUN 모드로 실행되었습니다. 실제 변경은 없습니다.")
        print("  실제 마이그레이션을 수행하려면: python scripts/migrate_knowledge_metadata.py")
    else:
        print("\n[OK] 마이그레이션이 성공적으로 완료되었습니다!")
    
    return {
        "total": total,
        "updated": updated_count,
        "skipped": len(already_complete),
        "errors": error_count,
    }


def main():
    parser = argparse.ArgumentParser(
        description="ChromaDB 지식 메타데이터 마이그레이션 (doc_type, source, created_at 추가)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제 변경 없이 분석만 수행"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="확인 없이 즉시 마이그레이션 실행"
    )
    
    args = parser.parse_args()
    
    try:
        result = migrate_knowledge_metadata(dry_run=args.dry_run, force=args.force)
        
        if result["errors"] > 0:
            sys.exit(1)
        else:
            sys.exit(0)
            
    except KeyboardInterrupt:
        print("\n\n[CANCEL] 사용자에 의해 중단되었습니다.")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] 예상치 못한 오류: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
