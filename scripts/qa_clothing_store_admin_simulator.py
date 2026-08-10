"""
QA 전용 시뮬레이터: 가상 의류 판매 관리자 사이트 REST API (1001 테넌트 AI 도우미 E2E QA용).

이 서버는 실제 SIP PBX 프로젝트와 완전히 무관한 "원격지의 낯선 시스템"을 흉내 내기 위한
독립 FastAPI 앱이다. AI 도우미(self_service)가 "내가 모르는 원격 사이트라도 자연어 매뉴얼과
OpenAPI 스펙만으로 안내·조회·설정변경을 할 수 있는가"를 검증하는 목적의 고정 데이터 시뮬레이터.

실행:
    cd sip-pbx
    python -m uvicorn scripts.qa_clothing_store_admin_simulator:app --port 8090 --reload

OpenAPI 스펙 확인(업로드용):
    http://127.0.0.1:8090/openapi.json

⚠️ PoC 목적 — 인증/인가는 의도적으로 생략(보안 이슈는 이번 QA 범위에서 제외, 프로덕션 사용 금지).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

app = FastAPI(
    title="의류판매 관리자 API (QA 시뮬레이터)",
    description=(
        "고객 주문관리, 판매 재고관리, 통계 조회 기능을 제공하는 의류 쇼핑몰 관리자 백엔드 API. "
        "이 문서는 AI 도우미가 REST-API를 통해 설정변경/데이터조회 안내를 할 수 있는지 검증하기 "
        "위한 QA 시뮬레이터용 OpenAPI 스펙이다."
    ),
    version="1.0.0",
    servers=[{"url": "http://127.0.0.1:8090"}],
)


# ── 데이터 모델 ──────────────────────────────────────────────────────────────


class Order(BaseModel):
    order_id: str
    customer_name: str
    product_name: str
    quantity: int
    status: str = Field(description="주문 상태: 결제완료 | 배송준비중 | 배송중 | 배송완료 | 취소")
    created_at: str


class OrderStatusUpdate(BaseModel):
    status: str = Field(description="변경할 주문 상태: 결제완료 | 배송준비중 | 배송중 | 배송완료 | 취소")


class InventoryItem(BaseModel):
    sku: str
    product_name: str
    size: str
    color: str
    stock_count: int


class InventoryUpdate(BaseModel):
    stock_count: int = Field(description="변경할 재고 수량(음수 불가)")


class SalesStats(BaseModel):
    period: str
    total_orders: int
    total_revenue: int
    best_seller: str


# ── 인메모리 시드 데이터 ──────────────────────────────────────────────────────

_now = datetime.utcnow()

_ORDERS: Dict[str, Order] = {
    "ORD-1001": Order(
        order_id="ORD-1001", customer_name="김도우미", product_name="오버핏 후드 집업",
        quantity=1, status="결제완료", created_at=(_now - timedelta(days=1)).isoformat(),
    ),
    "ORD-1002": Order(
        order_id="ORD-1002", customer_name="이지식", product_name="와이드 데님 팬츠",
        quantity=2, status="배송준비중", created_at=(_now - timedelta(days=2)).isoformat(),
    ),
    "ORD-1003": Order(
        order_id="ORD-1003", customer_name="박테넌트", product_name="크루넥 니트",
        quantity=1, status="배송중", created_at=(_now - timedelta(days=3)).isoformat(),
    ),
}

_INVENTORY: Dict[str, InventoryItem] = {
    "SKU-HOOD-BLK-M": InventoryItem(
        sku="SKU-HOOD-BLK-M", product_name="오버핏 후드 집업", size="M", color="블랙", stock_count=12,
    ),
    "SKU-DENIM-BLU-30": InventoryItem(
        sku="SKU-DENIM-BLU-30", product_name="와이드 데님 팬츠", size="30", color="블루", stock_count=3,
    ),
    "SKU-KNIT-IVY-FREE": InventoryItem(
        sku="SKU-KNIT-IVY-FREE", product_name="크루넥 니트", size="FREE", color="아이보리", stock_count=0,
    ),
}


# ── 주문관리 ──────────────────────────────────────────────────────────────


@app.get("/orders", response_model=List[Order], summary="주문 목록 조회")
def list_orders(status: Optional[str] = Query(None, description="상태로 필터링")) -> List[Order]:
    items = list(_ORDERS.values())
    if status:
        items = [o for o in items if o.status == status]
    return items


@app.get("/orders/{order_id}", response_model=Order, summary="주문 단건 조회")
def get_order(order_id: str) -> Order:
    order = _ORDERS.get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다")
    return order


@app.patch("/orders/{order_id}/status", response_model=Order, summary="주문 상태 변경(배송 처리 등)")
def update_order_status(order_id: str, body: OrderStatusUpdate) -> Order:
    order = _ORDERS.get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다")
    order.status = body.status
    return order


# ── 재고관리 ──────────────────────────────────────────────────────────────


@app.get("/inventory", response_model=List[InventoryItem], summary="재고 목록 조회")
def list_inventory(low_stock_only: bool = Query(False, description="재고 5개 이하만 조회")) -> List[InventoryItem]:
    items = list(_INVENTORY.values())
    if low_stock_only:
        items = [i for i in items if i.stock_count <= 5]
    return items


@app.get("/inventory/{sku}", response_model=InventoryItem, summary="재고 단건 조회")
def get_inventory_item(sku: str) -> InventoryItem:
    item = _INVENTORY.get(sku)
    if not item:
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")
    return item


@app.patch("/inventory/{sku}", response_model=InventoryItem, summary="재고 수량 변경(입고/조정)")
def update_inventory(sku: str, body: InventoryUpdate) -> InventoryItem:
    item = _INVENTORY.get(sku)
    if not item:
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")
    if body.stock_count < 0:
        raise HTTPException(status_code=422, detail="재고 수량은 0 이상이어야 합니다")
    item.stock_count = body.stock_count
    return item


# ── 통계 조회 ──────────────────────────────────────────────────────────────


@app.get("/stats/sales", response_model=SalesStats, summary="매출 통계 조회")
def get_sales_stats(period: str = Query("weekly", description="daily | weekly | monthly")) -> SalesStats:
    total_orders = len(_ORDERS)
    total_revenue = sum(39000 * o.quantity for o in _ORDERS.values())
    return SalesStats(
        period=period, total_orders=total_orders, total_revenue=total_revenue,
        best_seller="오버핏 후드 집업",
    )


@app.get("/health", summary="헬스체크")
def health() -> Dict[str, str]:
    return {"status": "ok"}
