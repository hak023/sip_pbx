"""
테넌트 초기 데이터 설정 스크립트

기상청(1004) 테넌트의 초기 데이터를 설정합니다:
1. 조직 정보 (tenant_config)
2. Capabilities (AI가 응답 가능한 업무)
3. 샘플 지식 (FAQ, 절차 등)
"""

import asyncio
import sys
from pathlib import Path

# 프로젝트 루트를 Python path에 추가
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from src.services.knowledge_service import get_knowledge_service


async def setup_tenant_data():
    """테넌트 초기 데이터 설정"""
    
    service = get_knowledge_service()
    owner = "1004"  # 기상청
    
    print(f"📦 테넌트 '{owner}' 초기 데이터 설정 시작...")
    
    # 1. 조직 정보 (tenant_config)
    print("\n1️⃣ 조직 정보 설정...")
    tenant_config = {
        "id": f"tenant_{owner}",
        "text": "기상청 AI 통화 비서 설정",
        "category": "tenant_config",
        "owner": owner,
        "tenant_name": "기상청",
        "tenant_type": "government_agency",
        "greeting_templates": [
            "안녕하세요. 기상청 AI 통화 비서입니다. 무엇을 도와드릴까요?",
            "반갑습니다. 기상청입니다. 궁금하신 사항을 말씀해 주세요.",
        ],
        "description": "기상청 조직 정보 및 설정"
    }
    
    try:
        config_id = await service.add_knowledge(
            text=tenant_config["text"],
            category=tenant_config["category"],
            keywords=["tenant", "config", "organization"],
            owner=owner,
            metadata={
                "tenant_name": tenant_config["tenant_name"],
                "tenant_type": tenant_config["tenant_type"],
                "greeting_templates": tenant_config["greeting_templates"],
            }
        )
        print(f"   ✅ 조직 정보 추가 완료: {config_id}")
    except Exception as e:
        print(f"   ⚠️ 조직 정보 추가 실패: {e}")
    
    # 2. Capabilities (AI 응답 가능 업무)
    print("\n2️⃣ Capabilities 설정...")
    capabilities = [
        {"text": "날씨 예보 조회", "display_name": "날씨 예보"},
        {"text": "기상 특보 안내", "display_name": "기상 특보"},
        {"text": "강수량 조회", "display_name": "강수량 정보"},
        {"text": "기온 조회", "display_name": "기온 정보"},
        {"text": "바람 정보 제공", "display_name": "바람 정보"},
        {"text": "습도 정보 제공", "display_name": "습도 정보"},
        {"text": "일기예보 안내", "display_name": "일기예보"},
    ]
    
    for cap in capabilities:
        try:
            cap_id = await service.add_knowledge(
                text=cap["text"],
                category="capability",
                keywords=["capability", "service"],
                owner=owner,
                metadata={
                    "display_name": cap["display_name"],
                    "is_active": True,
                }
            )
            print(f"   ✅ {cap['display_name']}: {cap_id}")
        except Exception as e:
            print(f"   ⚠️ {cap['display_name']} 추가 실패: {e}")
    
    # 3. 샘플 FAQ
    print("\n3️⃣ 샘플 FAQ 설정...")
    faqs = [
        {
            "question": "오늘 날씨 어때요?",
            "answer": "현재 날씨 정보를 확인해 드리겠습니다. 어느 지역의 날씨가 궁금하신가요?",
            "category": "weather_inquiry",
        },
        {
            "question": "내일 비 올까요?",
            "answer": "내일 강수 확률을 확인해 드리겠습니다. 지역을 말씀해 주시면 더 정확한 정보를 드릴 수 있습니다.",
            "category": "precipitation_forecast",
        },
        {
            "question": "기상 특보 발령됐나요?",
            "answer": "현재 발령된 기상 특보를 확인해 드리겠습니다. 특정 지역을 말씀해 주시면 해당 지역의 특보 현황을 알려드립니다.",
            "category": "weather_warning",
        },
        {
            "question": "주간 날씨 알려줘",
            "answer": "1주일간의 날씨 예보를 안내해 드리겠습니다. 어느 지역의 주간 날씨가 궁금하신가요?",
            "category": "weekly_forecast",
        },
        {
            "question": "미세먼지 농도는?",
            "answer": "현재 미세먼지 농도를 확인해 드리겠습니다. 지역을 말씀해 주시면 해당 지역의 대기질 정보를 알려드립니다.",
            "category": "air_quality",
        },
    ]
    
    for faq in faqs:
        try:
            faq_id = await service.add_knowledge(
                text=f"Q: {faq['question']}\nA: {faq['answer']}",
                category="faq",
                keywords=["faq", faq["category"], "weather"],
                owner=owner,
                metadata={
                    "question": faq["question"],
                    "answer": faq["answer"],
                    "faq_category": faq["category"],
                }
            )
            print(f"   ✅ FAQ 추가: {faq['question'][:30]}... ({faq_id})")
        except Exception as e:
            print(f"   ⚠️ FAQ 추가 실패: {e}")
    
    # 4. 샘플 절차 (Procedure)
    print("\n4️⃣ 샘플 절차 설정...")
    procedures = [
        {
            "name": "날씨 정보 제공 절차",
            "steps": "1. 사용자 위치 확인\n2. 해당 지역 기상 데이터 조회\n3. 현재 날씨 정보 제공\n4. 추가 정보 필요 여부 확인",
            "category": "weather_info_procedure",
        },
        {
            "name": "기상 특보 안내 절차",
            "steps": "1. 현재 발령된 특보 목록 조회\n2. 사용자 위치와 관련된 특보 필터링\n3. 특보 내용 및 주의사항 안내\n4. 대처 방법 안내",
            "category": "warning_procedure",
        },
    ]
    
    for proc in procedures:
        try:
            proc_id = await service.add_knowledge(
                text=f"{proc['name']}\n\n{proc['steps']}",
                category="procedure",
                keywords=["procedure", proc["category"]],
                owner=owner,
                metadata={
                    "procedure_name": proc["name"],
                    "steps": proc["steps"],
                }
            )
            print(f"   ✅ 절차 추가: {proc['name']} ({proc_id})")
        except Exception as e:
            print(f"   ⚠️ 절차 추가 실패: {e}")
    
    # 5. 통계 출력
    print("\n📊 테넌트 데이터 통계...")
    try:
        all_docs = await service.get_all_knowledge(owner=owner, limit=1000)
        print(f"   총 문서 수: {len(all_docs)}")
        
        category_counts = {}
        for doc in all_docs:
            cat = doc.get("category", "unknown")
            category_counts[cat] = category_counts.get(cat, 0) + 1
        
        print("   카테고리별:")
        for cat, count in sorted(category_counts.items()):
            print(f"     - {cat}: {count}개")
        
        capabilities_count = await service.get_all_capabilities(owner=owner, active_only=True)
        print(f"   활성 Capabilities: {len(capabilities_count)}개")
        
    except Exception as e:
        print(f"   ⚠️ 통계 조회 실패: {e}")
    
    print("\n✅ 테넌트 초기 데이터 설정 완료!")


if __name__ == "__main__":
    asyncio.run(setup_tenant_data())
