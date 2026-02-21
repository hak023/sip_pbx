"""Seed Data Loader

착신번호(owner) 기반 멀티테넌트 초기 데이터 투입.
서버 시작 시 VectorDB에 테넌트별 초기 데이터가 없으면 자동으로 생성한다.

테넌트:
  - 1003: 이탈리안 비스트로 (Italian Bistro)
  - 1004: 기상청 (Korea Meteorological Administration)
"""

import json
import structlog
from typing import Dict, List, Optional
from datetime import datetime

logger = structlog.get_logger(__name__)


# ============================================================================
# 테넌트 설정 (tenant_config)
# ============================================================================

TENANT_CONFIGS = {
    "1003": {
        "tenant_name": "이탈리안 비스트로",
        "tenant_name_en": "Italian Bistro",
        "tenant_type": "restaurant",
        "description": "정통 이탈리아 요리를 선보이는 캐주얼 다이닝 레스토랑",
        "service_description": "메뉴 안내, 예약, 영업시간 문의",
        "main_phone": "02-1234-5678",
        "website": "www.italian-bistro.kr",
        "business_hours": "매일 11:30-22:00 (브레이크타임 15:00-17:00, 월요일 정기 휴무)",
        "greeting_templates": json.dumps([
            "안녕하세요! 이탈리안 비스트로입니다. 무엇을 도와드릴까요?",
            "이탈리안 비스트로에 전화 주셔서 감사합니다. AI 비서가 안내해 드리겠습니다.",
            "안녕하세요. 이탈리안 비스트로 AI 상담원입니다. 어떤 것이 궁금하신가요?",
        ], ensure_ascii=False),
        "system_prompt_template": (
            "당신은 {tenant_name}의 친절한 AI 전화 비서입니다.\n\n"
            "## 역할\n"
            "- 고객의 메뉴, 예약, 영업시간 등 문의에 친절하게 답변\n"
            "- 간결하고 명확하게 1-2문장으로 답변\n"
            "- 예약 문의 시 날짜, 시간, 인원을 확인\n\n"
            "## 제공 가능한 서비스\n{capabilities}\n\n"
            "## 대화 원칙\n"
            "1. 밝고 친근한 어투 사용\n"
            "2. 메뉴 가격은 정확하게 안내\n"
            "3. 모르는 것은 솔직히 인정하고 직원 연결 제안\n\n"
            "## 제약 사항\n"
            "- 레스토랑과 관련 없는 주제는 정중히 거절\n"
            "- 실제 결제나 주문 처리는 불가 (안내만 가능)\n"
            "- 개인 정보는 요구하지 않음"
        ),
    },
    "1004": {
        "tenant_name": "기상청",
        "tenant_name_en": "Korea Meteorological Administration",
        "tenant_type": "government_agency",
        "description": "대한민국의 기상 및 기후 정보를 제공하는 정부 기관",
        "service_description": "날씨 예보 및 기상 정보 안내",
        "main_phone": "131",
        "website": "www.kma.go.kr",
        "business_hours": "평일 09:00-18:00",
        "greeting_templates": json.dumps([
            "안녕하세요. 기상청 AI 통화 비서입니다. 무엇을 도와드릴까요?",
            "안녕하세요. 기상청 AI 상담원입니다. 어떤 도움이 필요하신가요?",
            "기상청에 전화해 주셔서 감사합니다. AI 비서가 도와드리겠습니다.",
            "안녕하세요. 기상청입니다. 날씨와 관련된 문의를 도와드리겠습니다.",
        ], ensure_ascii=False),
        "system_prompt_template": (
            "당신은 {tenant_name}의 친절하고 전문적인 AI 통화 비서입니다.\n\n"
            "## 역할과 책임\n"
            "- 발신자의 질문에 정확하고 친절하게 답변\n"
            "- {tenant_name}의 서비스와 정보를 명확하게 안내\n"
            "- 필요시 적절한 부서나 담당자에게 연결 제안\n"
            "- 통화 중 자연스럽고 인간적인 대화 유지\n\n"
            "## 제공 가능한 서비스\n{capabilities}\n\n"
            "## 대화 원칙\n"
            "1. 간결하고 명확하게 답변 (1-2문장)\n"
            "2. 전문 용어는 쉽게 풀어서 설명\n"
            "3. 질문 의도를 정확히 파악\n"
            "4. 모르는 것은 솔직히 인정하고 대안 제시\n"
            "5. 공손하고 존중하는 어투 유지\n\n"
            "## 제약 사항\n"
            "- {tenant_name}과 관련 없는 주제는 정중히 거절\n"
            "- 개인 정보는 절대 요구하지 않음\n"
            "- 실시간 날씨 정보는 기상청 웹사이트나 담당자 연결을 안내"
        ),
    },
}


# ============================================================================
# Capabilities (AI 서비스)
# ============================================================================

CAPABILITIES = {
    "1003": [
        {
            "id": "cap_1003_menu",
            "display_name": "메뉴 안내",
            "text": "파스타, 피자, 리조또, 스테이크 등 이탈리안 정통 메뉴와 가격을 안내합니다.",
            "category": "menu",
            "response_type": "info",
            "keywords": ["메뉴", "음식", "파스타", "피자", "가격", "추천"],
            "priority": 1,
        },
        {
            "id": "cap_1003_reservation",
            "display_name": "예약 안내",
            "text": "날짜, 시간, 인원수를 확인하여 예약을 도와드립니다. 전화 및 네이버 예약 가능.",
            "category": "reservation",
            "response_type": "collect",
            "keywords": ["예약", "예약하기", "자리", "테이블", "단체"],
            "priority": 2,
        },
        {
            "id": "cap_1003_hours",
            "display_name": "영업시간 안내",
            "text": "영업시간, 브레이크타임, 라스트오더, 정기 휴무일을 안내합니다.",
            "category": "hours",
            "response_type": "info",
            "keywords": ["영업시간", "오픈", "마감", "브레이크타임", "휴무"],
            "priority": 3,
        },
        {
            "id": "cap_1003_location",
            "display_name": "오시는 길 안내",
            "text": "매장 위치, 주차 정보, 대중교통 안내를 제공합니다.",
            "category": "location",
            "response_type": "info",
            "keywords": ["위치", "주소", "오시는길", "주차", "교통"],
            "priority": 4,
        },
        {
            "id": "cap_1003_transfer",
            "display_name": "직원 연결",
            "text": "더 자세한 상담이 필요한 경우 매장 직원에게 연결합니다.",
            "category": "transfer",
            "response_type": "transfer",
            "keywords": ["직원", "상담원", "연결", "사람"],
            "priority": 5,
        },
    ],
    "1004": [
        {
            "id": "cap_1004_forecast",
            "display_name": "날씨 예보 조회",
            "text": "오늘, 내일, 주간 날씨 예보 정보를 안내합니다. 실시간 정보는 기상청 웹사이트를 안내합니다.",
            "category": "weather_forecast",
            "response_type": "info",
            "keywords": ["날씨", "예보", "기온", "비", "눈", "맑음"],
            "priority": 1,
        },
        {
            "id": "cap_1004_warning",
            "display_name": "기상 특보 안내",
            "text": "현재 발효 중인 기상 특보(호우, 태풍, 폭설 등)를 안내합니다.",
            "category": "weather_warning",
            "response_type": "info",
            "keywords": ["특보", "경보", "주의보", "태풍", "호우", "폭설"],
            "priority": 2,
        },
        {
            "id": "cap_1004_historical",
            "display_name": "과거 기상 데이터 제공",
            "text": "과거 기상 관측 데이터 조회 및 자료 신청 방법을 안내합니다.",
            "category": "historical_data",
            "response_type": "info",
            "keywords": ["과거", "데이터", "관측", "통계", "자료"],
            "priority": 3,
        },
        {
            "id": "cap_1004_transfer",
            "display_name": "기상청 담당자 연결",
            "text": "전문 상담이 필요한 경우 담당 부서로 연결합니다.",
            "category": "transfer",
            "response_type": "transfer",
            "keywords": ["담당자", "상담원", "연결", "사람", "전화"],
            "priority": 4,
        },
        {
            "id": "cap_1004_knowledge",
            "display_name": "일반 기상 상식 안내",
            "text": "기상 용어, 날씨 현상, 기후 변화 등 일반적인 기상 상식을 안내합니다.",
            "category": "weather_knowledge",
            "response_type": "info",
            "keywords": ["기상", "상식", "용어", "기후", "변화"],
            "priority": 5,
        },
    ],
}


# ============================================================================
# Knowledge (지식 데이터)
# ============================================================================

KNOWLEDGE_DATA = {
    "1003": [
        {
            "text": "파스타 메뉴: 까르보나라 16,000원, 알리오올리오 14,000원, 봉골레 17,000원, 아마트리치아나 15,000원, 트러플 크림 파스타 22,000원",
            "category": "menu",
            "keywords": ["파스타", "까르보나라", "알리오올리오", "봉골레", "가격"],
        },
        {
            "text": "피자 메뉴: 마르게리타 15,000원, 페퍼로니 17,000원, 콰트로 포르마지 19,000원, 프로슈토 루콜라 21,000원",
            "category": "menu",
            "keywords": ["피자", "마르게리타", "페퍼로니", "가격"],
        },
        {
            "text": "메인 요리: 안심 스테이크 35,000원, 오소부코 28,000원, 해산물 리조또 22,000원, 밀라노식 커틀릿 24,000원",
            "category": "menu",
            "keywords": ["스테이크", "리조또", "메인", "가격"],
        },
        {
            "text": "런치 세트: 평일 11:30-14:30, 파스타 또는 피자 + 샐러드 + 음료 = 15,000원. 주말 런치 세트는 운영하지 않습니다.",
            "category": "menu",
            "keywords": ["런치", "세트", "점심", "할인"],
        },
        {
            "text": "영업시간은 매일 11:30~22:00이며, 브레이크타임은 15:00~17:00입니다. 라스트오더는 21:00입니다. 매주 월요일은 정기 휴무입니다.",
            "category": "hours",
            "keywords": ["영업시간", "브레이크타임", "라스트오더", "휴무"],
        },
        {
            "text": "서울시 강남구 테헤란로 123 비스트로빌딩 1층에 위치합니다. 지하철 2호선 강남역 3번 출구에서 도보 5분 거리입니다.",
            "category": "location",
            "keywords": ["위치", "주소", "강남역", "오시는길"],
        },
        {
            "text": "건물 지하 주차장 이용 가능합니다. 식사 고객에게 2시간 무료 주차를 제공합니다. 주차 공간이 한정되어 있어 대중교통 이용을 권장합니다.",
            "category": "parking",
            "keywords": ["주차", "주차장", "무료주차", "교통"],
        },
        {
            "text": "예약은 전화 또는 네이버 예약으로 가능합니다. 2인~8인 테이블 예약 가능하며, 10인 이상 단체 예약은 별도 문의 바랍니다. 당일 예약은 17시 이전 가능합니다.",
            "category": "reservation",
            "keywords": ["예약", "네이버", "단체", "테이블"],
        },
        {
            "text": "노쇼(No-show) 방지를 위해 예약 시간 15분 초과 시 자동 취소될 수 있습니다. 예약 변경/취소는 방문 2시간 전까지 가능합니다.",
            "category": "policy",
            "keywords": ["노쇼", "취소", "변경", "정책"],
        },
        {
            "text": "매월 첫째 주 수요일은 와인 데이로 하우스 와인 50% 할인입니다. 생일 고객에게는 디저트 서비스를 제공합니다 (사전 예약 필요).",
            "category": "event",
            "keywords": ["와인", "할인", "이벤트", "생일", "디저트"],
        },
    ],
    "1004": [
        {
            "text": "날씨 예보는 기상청 홈페이지(www.kma.go.kr), 날씨누리 앱, 또는 131번 자동응답전화에서 확인할 수 있습니다. 동네예보는 읍면동 단위로 제공됩니다.",
            "category": "weather_forecast",
            "keywords": ["날씨", "예보", "홈페이지", "앱", "131"],
        },
        {
            "text": "기상 특보는 주의보와 경보로 나뉩니다. 호우, 대설, 한파, 폭염, 태풍, 강풍, 건조 등의 특보가 있으며, 재난문자로도 안내됩니다.",
            "category": "weather_warning",
            "keywords": ["특보", "주의보", "경보", "호우", "태풍"],
        },
        {
            "text": "태풍 정보는 기상청 홈페이지 '태풍정보' 메뉴에서 실시간 확인 가능합니다. 진로 예측, 강도, 예상 영향 지역을 상세히 안내합니다.",
            "category": "weather_warning",
            "keywords": ["태풍", "진로", "강도", "영향"],
        },
        {
            "text": "과거 기상 데이터는 기상자료개방포털(data.kma.go.kr)에서 무료로 조회하실 수 있습니다. 기온, 강수량, 풍속 등 관측 자료를 제공합니다.",
            "category": "historical_data",
            "keywords": ["과거", "데이터", "기온", "강수량", "통계"],
        },
        {
            "text": "기상청 고객센터 전화번호는 131입니다. 운영시간은 평일 09:00~18:00이며, 긴급 기상 상황 시에는 24시간 운영합니다.",
            "category": "service_info",
            "keywords": ["고객센터", "131", "운영시간", "전화"],
        },
        {
            "text": "장마는 보통 6월 중순~7월 중순에 시작되며, 약 한 달간 지속됩니다. 장마 기간 중 강수량은 연간 강수량의 약 30%를 차지합니다.",
            "category": "weather_knowledge",
            "keywords": ["장마", "강수량", "여름", "비"],
        },
        {
            "text": "미세먼지 정보는 에어코리아(airkorea.or.kr)에서 실시간 확인 가능합니다. 기상청은 황사 관측 및 예보를 담당합니다.",
            "category": "weather_knowledge",
            "keywords": ["미세먼지", "황사", "에어코리아", "대기질"],
        },
        {
            "text": "기상감정서 발급은 기상청 홈페이지에서 온라인 신청 가능합니다. 신청 후 약 7~14일 소요되며, 수수료가 발생합니다.",
            "category": "application",
            "keywords": ["기상감정서", "발급", "신청", "수수료"],
        },
    ],
}


# ============================================================================
# FAQ 데이터
# ============================================================================

FAQ_DATA = {
    "1003": [
        {"question": "주차 가능한가요?", "answer": "네, 건물 지하 주차장을 이용하실 수 있으며 식사 고객에게 2시간 무료 주차를 제공합니다."},
        {"question": "예약 가능한가요?", "answer": "네, 전화 또는 네이버 예약으로 가능합니다. 2인~8인 테이블 예약 가능합니다."},
        {"question": "런치 세트 있나요?", "answer": "네, 평일 11:30~14:30에 파스타/피자 + 샐러드 + 음료 = 15,000원 런치 세트를 운영합니다."},
        {"question": "영업시간이 어떻게 되나요?", "answer": "매일 11:30~22:00이며, 브레이크타임은 15:00~17:00입니다. 매주 월요일은 정기 휴무입니다."},
        {"question": "단체 예약 가능한가요?", "answer": "10인 이상 단체 예약은 별도 문의 부탁드립니다. 전화로 연락 주시면 안내해 드리겠습니다."},
    ],
    "1004": [
        {"question": "내일 날씨 어떤가요?", "answer": "실시간 날씨 정보는 기상청 홈페이지(www.kma.go.kr)나 날씨누리 앱에서 확인하실 수 있습니다. 담당자에게 연결해 드릴까요?"},
        {"question": "태풍 정보는 어떻게 확인하나요?", "answer": "기상청 홈페이지의 '태풍정보' 메뉴에서 실시간으로 확인 가능합니다. 진로와 강도, 예상 영향 지역을 안내합니다."},
        {"question": "과거 날씨 데이터는 어떻게 받나요?", "answer": "기상자료개방포털(data.kma.go.kr)에서 무료로 조회 가능합니다. 자세한 절차는 담당자에게 연결해 드릴까요?"},
        {"question": "기상감정서 발급은 어떻게 하나요?", "answer": "기상청 홈페이지에서 온라인으로 신청 가능하며, 약 7~14일 소요됩니다."},
        {"question": "담당자와 통화하고 싶어요", "answer": "알겠습니다. 담당 부서로 연결해 드리겠습니다. 잠시만 기다려 주세요."},
    ],
}


# ============================================================================
# 시드 로더
# ============================================================================

async def seed_initial_data(knowledge_service) -> Dict[str, int]:
    """서버 시작 시 초기 데이터 투입.

    VectorDB에 tenant_config가 없는 경우에만 시드 데이터를 투입한다.
    이미 데이터가 있으면 스킵한다.

    Args:
        knowledge_service: KnowledgeService 인스턴스

    Returns:
        {"tenants": 2, "capabilities": 10, "knowledge": 18, "faq": 10} 형태의 통계
    """
    stats = {"tenants": 0, "capabilities": 0, "knowledge": 0, "faq": 0}

    try:
        if not knowledge_service._initialized:
            await knowledge_service.initialize()

        for owner, config in TENANT_CONFIGS.items():
            # tenant_config 존재 여부 확인
            existing = await _get_tenant_config(knowledge_service, owner)
            if existing:
                logger.info("seed_data_skip_existing_tenant",
                           owner=owner,
                           tenant_name=config["tenant_name"])
                continue

            logger.info("seed_data_creating_tenant",
                       owner=owner,
                       tenant_name=config["tenant_name"])

            # 1. tenant_config 생성
            await _create_tenant_config(knowledge_service, owner, config)
            stats["tenants"] += 1

            # 2. capabilities 생성
            for cap in CAPABILITIES.get(owner, []):
                await knowledge_service.add_capability(
                    doc_id=cap["id"],
                    display_name=cap["display_name"],
                    text=cap["text"],
                    category=cap["category"],
                    response_type=cap.get("response_type", "info"),
                    keywords=cap.get("keywords", []),
                    priority=cap.get("priority", 50),
                    is_active=True,
                    owner=owner,
                    source="seed",
                )
                stats["capabilities"] += 1

            # 3. knowledge 생성
            for idx, kb in enumerate(KNOWLEDGE_DATA.get(owner, []), start=1):
                doc_id = f"kb_seed_{owner}_{idx:03d}"
                embedding = await knowledge_service.embedder.embed(kb["text"])
                metadata = {
                    "category": kb["category"],
                    "keywords": ",".join(kb.get("keywords", [])),
                    "owner": owner,
                    "source": "seed",
                    "created_at": datetime.now().isoformat(),
                }
                await knowledge_service.vector_db.upsert(
                    doc_id=doc_id,
                    embedding=embedding,
                    text=kb["text"],
                    metadata=metadata,
                )
                stats["knowledge"] += 1

            # 4. FAQ 생성
            for idx, faq in enumerate(FAQ_DATA.get(owner, []), start=1):
                doc_id = f"faq_seed_{owner}_{idx:03d}"
                faq_text = f"Q: {faq['question']}\nA: {faq['answer']}"
                embedding = await knowledge_service.embedder.embed(faq_text)
                metadata = {
                    "category": "faq",
                    "doc_type": "faq",
                    "question": faq["question"],
                    "keywords": "",
                    "owner": owner,
                    "source": "seed",
                    "created_at": datetime.now().isoformat(),
                }
                await knowledge_service.vector_db.upsert(
                    doc_id=doc_id,
                    embedding=embedding,
                    text=faq_text,
                    metadata=metadata,
                )
                stats["faq"] += 1

            logger.info("seed_data_tenant_created",
                       owner=owner,
                       tenant_name=config["tenant_name"],
                       capabilities=len(CAPABILITIES.get(owner, [])),
                       knowledge=len(KNOWLEDGE_DATA.get(owner, [])),
                       faq=len(FAQ_DATA.get(owner, [])))

        if stats["tenants"] > 0:
            logger.info("seed_data_complete", **stats)
            # 레거시 데이터 정리 (owner 없는 문서 삭제)
            try:
                deleted = await cleanup_legacy_data(knowledge_service)
                if deleted > 0:
                    logger.info("legacy_data_cleaned", deleted=deleted)
            except Exception as cleanup_err:
                logger.warning("legacy_data_cleanup_failed", error=str(cleanup_err))
        else:
            logger.info("seed_data_already_exists", message="모든 테넌트 데이터가 이미 존재합니다")

        return stats

    except Exception as e:
        logger.error("seed_data_failed", error=str(e), exc_info=True)
        return stats


async def _get_tenant_config(knowledge_service, owner: str) -> Optional[Dict]:
    """VectorDB에서 tenant_config 조회"""
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            None,
            lambda: knowledge_service.vector_db.collection.get(
                where={"$and": [{"doc_type": "tenant_config"}, {"owner": owner}]},
                limit=1,
                include=["documents", "metadatas"],
            ),
        )
        if results["ids"]:
            return {
                "id": results["ids"][0],
                "text": results["documents"][0],
                "metadata": results["metadatas"][0],
            }
        return None
    except Exception:
        return None


async def _create_tenant_config(knowledge_service, owner: str, config: Dict) -> None:
    """VectorDB에 tenant_config 저장"""
    doc_id = f"tenant_config_{owner}"

    # 설명 텍스트 (임베딩용)
    text = f"{config['tenant_name']} ({config['tenant_name_en']}): {config['description']}"
    embedding = await knowledge_service.embedder.embed(text)

    metadata = {
        "doc_type": "tenant_config",
        "owner": owner,
        "source": "seed",
        "created_at": datetime.now().isoformat(),
    }
    # config의 모든 값을 metadata에 추가 (ChromaDB는 문자열만 지원)
    for key, value in config.items():
        metadata[key] = str(value) if not isinstance(value, str) else value

    await knowledge_service.vector_db.upsert(
        doc_id=doc_id,
        embedding=embedding,
        text=text,
        metadata=metadata,
    )


async def cleanup_legacy_data(knowledge_service) -> int:
    """owner가 없는 레거시 데이터 정리.

    기존에 owner 없이 저장된 문서들을 삭제한다.

    Returns:
        삭제된 문서 수
    """
    try:
        if not knowledge_service._initialized:
            await knowledge_service.initialize()

        import asyncio
        loop = asyncio.get_event_loop()

        # 전체 문서 조회
        results = await loop.run_in_executor(
            None,
            lambda: knowledge_service.vector_db.collection.get(
                limit=10000,
                include=["metadatas"],
            ),
        )

        if not results["ids"]:
            return 0

        # owner가 없거나 빈 문자열인 문서 찾기
        ids_to_delete = []
        for i, doc_id in enumerate(results["ids"]):
            meta = results["metadatas"][i] if results["metadatas"] else {}
            owner = meta.get("owner", "")
            if not owner:
                ids_to_delete.append(doc_id)

        if ids_to_delete:
            await loop.run_in_executor(
                None,
                lambda: knowledge_service.vector_db.collection.delete(ids=ids_to_delete),
            )
            logger.info("legacy_data_cleaned",
                       deleted_count=len(ids_to_delete),
                       deleted_ids=ids_to_delete[:10])  # 처음 10개만 로그

        return len(ids_to_delete)

    except Exception as e:
        logger.error("legacy_data_cleanup_failed", error=str(e))
        return 0


def get_tenant_list() -> List[Dict]:
    """등록된 테넌트 목록 반환 (정적).

    VectorDB 조회 없이 코드에 정의된 테넌트 목록을 반환한다.
    향후 VectorDB 기반 동적 조회로 전환할 수 있다.
    """
    tenants = []
    for owner, config in TENANT_CONFIGS.items():
        tenants.append({
            "owner": owner,
            "name": config["tenant_name"],
            "name_en": config["tenant_name_en"],
            "type": config["tenant_type"],
            "description": config["description"],
        })
    return tenants
