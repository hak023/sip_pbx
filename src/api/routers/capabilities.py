"""AI 서비스(Capability) 관리 API

VectorDB에 doc_type=capability로 저장되는 AI 서비스 항목을 관리합니다.
"""
from fastapi import APIRouter, HTTPException
from typing import Optional
from datetime import datetime
import structlog

from ..models import (
    CapabilityCreate,
    CapabilityUpdate,
    CapabilityEntry,
    CapabilityListResponse,
    CapabilityReorderRequest,
    GuideTextResponse,
)
from src.services.knowledge_service import get_knowledge_service

logger = structlog.get_logger(__name__)
router = APIRouter()

knowledge_service = get_knowledge_service()

# 가이드 멘트 캐시 (owner → {text, generated_at})
_guide_cache: dict = {}


def _to_entry(data: dict) -> CapabilityEntry:
    """dict → CapabilityEntry 변환"""
    return CapabilityEntry(
        id=data["id"],
        display_name=data.get("display_name", ""),
        text=data.get("text", ""),
        category=data.get("category", ""),
        response_type=data.get("response_type", "info"),
        keywords=data.get("keywords", []),
        priority=data.get("priority", 50),
        is_active=data.get("is_active", True),
        owner=data.get("owner"),
        api_endpoint=data.get("api_endpoint"),
        api_method=data.get("api_method"),
        api_params=data.get("api_params"),
        transfer_to=data.get("transfer_to"),
        phone_display=data.get("phone_display"),
        collect_fields=data.get("collect_fields"),
        created_at=data.get("created_at", ""),
        updated_at=data.get("updated_at"),
    )


# =========================================================================
# 시딩: 초기 Capability 데이터
# =========================================================================

SEED_CAPABILITIES = [
    {
        "id": "cap_directions",
        "display_name": "오시는길 안내",
        "text": "서울시 강남구 테헤란로 123. 지하철 2호선 강남역 3번 출구에서 도보 5분 거리입니다.",
        "category": "location",
        "response_type": "info",
        "keywords": ["오시는길", "위치", "주소", "찾아오는방법", "지도"],
        "priority": 1,
    },
    {
        "id": "cap_parking",
        "display_name": "주차 안내",
        "text": "지하 1~3층에 고객 전용 주차장이 있으며, 2시간 무료 주차가 가능합니다. 이후 30분당 1,000원이 부과됩니다. 5만원 이상 구매 시 추가 1시간 무료입니다.",
        "category": "parking",
        "response_type": "info",
        "keywords": ["주차", "주차장", "주차비", "무료주차", "발렛"],
        "priority": 2,
    },
    {
        "id": "cap_hours",
        "display_name": "영업시간 안내",
        "text": "평일 오전 10시부터 오후 9시까지, 주말은 오전 10시부터 오후 10시까지 영업합니다. 설날과 추석 당일은 휴무입니다.",
        "category": "hours",
        "response_type": "info",
        "keywords": ["영업시간", "운영시간", "몇시", "문여는시간", "휴무"],
        "priority": 3,
    },
    {
        "id": "cap_menu",
        "display_name": "메뉴 안내",
        "text": "대표 메뉴로 아메리카노(4,500원), 카페라떼(5,000원), 바닐라라떼(5,500원), 케이크 세트(12,000원)가 있습니다. 계절 한정 메뉴는 매월 변경됩니다.",
        "category": "menu",
        "response_type": "info",
        "keywords": ["메뉴", "가격", "음료", "케이크", "디저트"],
        "priority": 4,
    },
    {
        "id": "cap_transfer",
        "display_name": "상담원 연결",
        "text": "담당 상담원에게 전화를 연결해 드립니다. 잠시만 기다려 주세요.",
        "category": "transfer",
        "response_type": "transfer",
        "transfer_to": "sip:operator@pbx.local",
        "phone_display": "operator",
        "keywords": ["상담원", "담당자", "사람", "연결", "전환"],
        "priority": 98,
    },
    {
        "id": "cap_dev_transfer",
        "display_name": "개발부서 호 연결",
        "text": "개발부서, 개발팀으로 전화 연결을 해드립니다.",
        "category": "transfer",
        "response_type": "transfer",
        "transfer_to": "8001",
        "phone_display": "8001",
        "keywords": ["개발부서", "개발팀", "개발실", "개발"],
        "priority": 5,
    },
]


async def init_seed_capabilities():
    """서버 시작 시 Capability 시딩 (VectorDB가 비어있을 때만)"""
    try:
        cap_count = await knowledge_service.count_capabilities()
        if cap_count > 0:
            logger.info("capabilities_already_seeded", count=cap_count)
            return

        for cap in SEED_CAPABILITIES:
            await knowledge_service.add_capability(
                doc_id=cap["id"],
                display_name=cap["display_name"],
                text=cap["text"],
                category=cap["category"],
                response_type=cap.get("response_type", "info"),
                keywords=cap.get("keywords", []),
                priority=cap.get("priority", 50),
                is_active=True,
                transfer_to=cap.get("transfer_to"),
                phone_display=cap.get("phone_display"),
                source="seed",
            )

        logger.info("capabilities_seeded", count=len(SEED_CAPABILITIES))

    except Exception as e:
        logger.error("capability_seeding_failed", error=str(e), exc_info=True)


# =========================================================================
# REST API
# =========================================================================

@router.get("/", response_model=CapabilityListResponse)
async def list_capabilities(
    owner: Optional[str] = None,
    active_only: bool = False,
):
    """활성 서비스 목록 조회 (priority 정렬)"""
    try:
        items = await knowledge_service.get_all_capabilities(
            owner=owner,
            active_only=active_only,
        )
        entries = [_to_entry(item) for item in items]
        return CapabilityListResponse(items=entries, total=len(entries))
    except Exception as e:
        logger.error("list_capabilities_failed", error=str(e), exc_info=True)
        return CapabilityListResponse(items=[], total=0)


@router.get("/guide-text", response_model=GuideTextResponse)
async def get_guide_text(owner: Optional[str] = None):
    """가이드 멘트 텍스트 생성/조회"""
    cache_key = owner or "__default__"

    # 캐시 확인
    if cache_key in _guide_cache:
        cached = _guide_cache[cache_key]
        return GuideTextResponse(
            text=cached["text"],
            capability_count=cached["count"],
            cached=True,
            generated_at=cached["generated_at"],
        )

    # VectorDB에서 활성 capability 조회
    items = await knowledge_service.get_all_capabilities(
        owner=owner,
        active_only=True,
    )

    if not items:
        return GuideTextResponse(
            text="무엇을 도와드릴까요?",
            capability_count=0,
            cached=False,
            generated_at=datetime.now().isoformat(),
        )

    # display_name 목록으로 가이드 멘트 생성 (간단 포맷)
    names = [item["display_name"] for item in items[:7]]
    guide_text = f"저는 {', '.join(names)}을 도와드릴 수 있어요. 어떤 것이 궁금하신가요?"

    # 캐시 저장
    now = datetime.now().isoformat()
    _guide_cache[cache_key] = {"text": guide_text, "count": len(names), "generated_at": now}

    return GuideTextResponse(
        text=guide_text,
        capability_count=len(names),
        cached=False,
        generated_at=now,
    )


@router.post("/guide-text/refresh", response_model=GuideTextResponse)
async def refresh_guide_text(owner: Optional[str] = None):
    """가이드 멘트 캐시 무효화 후 재생성"""
    cache_key = owner or "__default__"
    _guide_cache.pop(cache_key, None)
    return await get_guide_text(owner)


@router.post("/", response_model=CapabilityEntry, status_code=201)
async def create_capability(body: CapabilityCreate):
    """서비스 추가"""
    try:
        doc_id = f"cap_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        result = await knowledge_service.add_capability(
            doc_id=doc_id,
            display_name=body.display_name,
            text=body.text,
            category=body.category,
            response_type=body.response_type,
            keywords=body.keywords,
            priority=body.priority,
            is_active=body.is_active,
            owner=body.owner,
            api_endpoint=body.api_endpoint,
            api_method=body.api_method,
            api_params=body.api_params,
            transfer_to=body.transfer_to,
            collect_fields=body.collect_fields,
        )
        # 캐시 무효화
        _guide_cache.clear()
        return _to_entry(result)
    except Exception as e:
        logger.error("create_capability_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="서비스 추가 실패")


@router.put("/{cap_id}", response_model=CapabilityEntry)
async def update_capability(cap_id: str, body: CapabilityUpdate):
    """서비스 수정"""
    try:
        updates = body.model_dump(exclude_none=True)
        result = await knowledge_service.update_capability(cap_id, updates)
        if not result:
            raise HTTPException(status_code=404, detail="서비스를 찾을 수 없습니다")
        _guide_cache.clear()
        return _to_entry(result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("update_capability_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="서비스 수정 실패")


@router.delete("/{cap_id}")
async def delete_capability(cap_id: str):
    """서비스 삭제"""
    try:
        success = await knowledge_service.delete_knowledge(cap_id)
        if not success:
            raise HTTPException(status_code=404, detail="서비스를 찾을 수 없습니다")
        _guide_cache.clear()
        return {"success": True, "id": cap_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("delete_capability_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="서비스 삭제 실패")


@router.patch("/{cap_id}/toggle", response_model=CapabilityEntry)
async def toggle_capability(cap_id: str):
    """서비스 활성/비활성 토글"""
    try:
        result = await knowledge_service.toggle_capability(cap_id)
        if not result:
            raise HTTPException(status_code=404, detail="서비스를 찾을 수 없습니다")
        _guide_cache.clear()
        return _to_entry(result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("toggle_capability_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="토글 실패")


@router.put("/reorder", response_model=dict)
async def reorder_capabilities(body: CapabilityReorderRequest):
    """서비스 순서 일괄 변경"""
    try:
        success = await knowledge_service.reorder_capabilities(body.ordered_ids)
        if not success:
            raise HTTPException(status_code=500, detail="순서 변경 실패")
        _guide_cache.clear()
        return {"success": True, "count": len(body.ordered_ids)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("reorder_capabilities_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="순서 변경 실패")
