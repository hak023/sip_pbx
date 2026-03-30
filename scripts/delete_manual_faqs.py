"""
기존 매뉴얼 FAQ 삭제 스크립트

기상청_매뉴얼.txt에서 업로드된 6개 FAQ 문서를 삭제합니다.
doc_id:
- kb_20260329_180240_157263
- kb_20260329_180240_209573
- kb_20260329_180240_247019
- kb_20260329_180240_286334
- kb_20260329_180240_330725
- kb_20260329_180240_371803
"""

import asyncio
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.services.knowledge_service import get_knowledge_service


async def main():
    # 삭제할 doc_id 리스트 (로그에서 확인)
    doc_ids = [
        "kb_20260329_180240_157263",
        "kb_20260329_180240_209573",
        "kb_20260329_180240_247019",
        "kb_20260329_180240_286334",
        "kb_20260329_180240_330725",
        "kb_20260329_180240_371803",
    ]
    
    ks = get_knowledge_service()
    if not ks:
        print("KnowledgeService가 초기화되지 않았습니다. 백엔드를 먼저 시작하세요.")
        return
    
    deleted_count = 0
    for doc_id in doc_ids:
        try:
            success = await ks.delete_knowledge(doc_id)
            if success:
                deleted_count += 1
                print(f"✓ 삭제: {doc_id}")
            else:
                print(f"✗ 삭제 실패: {doc_id}")
        except Exception as e:
            print(f"✗ 에러 ({doc_id}): {e}")
    
    print(f"\n총 {deleted_count}/{len(doc_ids)} 문서 삭제 완료")


if __name__ == "__main__":
    asyncio.run(main())
