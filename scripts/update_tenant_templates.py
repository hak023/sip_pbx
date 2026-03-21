"""기존 ChromaDB tenant_config에 인사말·끝인사(greeting_templates, closing_templates) 반영.

시드 시 이미 tenant_config가 있으면 스킵되므로 DB에 끝인사가 비어 있을 수 있음.
이 스크립트로 seed_data.TENANT_CONFIGS 기준으로 갱신.

사용법 (sip-pbx 디렉터리에서):
  python scripts/update_tenant_templates.py
"""
import asyncio
import os
import sys

# 프로젝트 루트(sip-pbx)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
os.environ.setdefault("CHROMA_TELEMETRY", "False")


async def main():
    from src.services.knowledge_service import get_knowledge_service
    from src.services.seed_data import update_tenant_config_templates

    ks = get_knowledge_service()
    await ks.initialize()
    updated = await update_tenant_config_templates(ks)
    if updated:
        print("갱신된 tenant_config (인사말/끝인사 반영):", list(updated.keys()))
    else:
        print("갱신된 tenant_config 없음 (이미 있던 문서만 업데이트됨 또는 tenant_config 없음)")


if __name__ == "__main__":
    asyncio.run(main())
