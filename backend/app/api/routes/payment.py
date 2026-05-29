import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.redis import get_redis
from app.core.security import get_current_user
from app.core.wechatpay import wechatpay_request
from app.models.token import Order, OrderStatus, TokenInventory
from app.models.user import User, UserToken
from app.services.account import get_or_create_user_token, list_charge_groups

router = APIRouter()


class OrderItem(BaseModel):
    group: str
    amount_usd: float


class CreateOrderRequest(BaseModel):
    items: list[OrderItem]
    pay_type: str = "wxpay"


async def _get_exchange_rate() -> float:
    redis = get_redis()
    cached = await redis.get("exchange_rate_usd_cny")
    if cached:
        return float(cached)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(settings.EXCHANGE_RATE_API)
            resp.raise_for_status()
            data = resp.json()
            rate = float(data["rates"]["CNY"])
            await redis.setex("exchange_rate_usd_cny", 3600, str(rate))
            return rate
    except Exception:
        return 7.25


def _round_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _serialize_items(items: list[dict]) -> str:
    return json.dumps(items, ensure_ascii=False, separators=(",", ":"))


async def _credit_paid_order(order: Order, user: User, db: AsyncSession) -> None:
    if order.status in {OrderStatus.ALLOCATED, OrderStatus.ASSIGNED}:
        return

    items = json.loads(order.items_json) if order.items_json else []
    first_token_id = None
    for item in items:
        group = item["group"]
        amount = Decimal(str(item["amount_usd"]))
        user_token = await get_or_create_user_token(db, user, group, create=True, allow_trial=False)
        if user_token is None:
            raise HTTPException(status_code=400, detail=f"No inventory available for group {group}")
        user_token.balance_usd = Decimal(str(user_token.balance_usd or 0)) + amount
        if first_token_id is None:
            first_token_id = user_token.token_id

    if items:
        user.account_type = "paid"
        user.balance_usd = Decimal(str(user.balance_usd or 0)) + Decimal(str(order.amount_usd or 0))
    if first_token_id and not user.api_token_id:
        user.api_token_id = first_token_id
    order.token_id = first_token_id or order.token_id
    order.status = OrderStatus.ALLOCATED
    order.allocated_at = datetime.now(timezone.utc)


async def _rollback_refund(order: Order, user: User, db: AsyncSession) -> None:
    items = json.loads(order.items_json) if order.items_json else []
    for item in items:
        group = item["group"]
        amount = Decimal(str(item["amount_usd"]))
        user_token = (
            await db.execute(select(UserToken).where(UserToken.user_id == user.id, UserToken.group == group))
        ).scalar_one_or_none()
        if user_token is not None:
            user_token.balance_usd = max(Decimal("0"), Decimal(str(user_token.balance_usd or 0)) - amount)
    user.balance_usd = max(Decimal("0"), Decimal(str(user.balance_usd or 0)) - Decimal(str(order.amount_usd or 0)))


async def _sync_order_status(order: Order, user: User, db: AsyncSession) -> None:
    if not settings.WECHAT_MCHID:
        return
    code, result = await wechatpay_request(f"/v3/pay/transactions/out-trade-no/{order.out_trade_no}?mchid={settings.WECHAT_MCHID}")
    if code != 200:
        return
    payload = json.loads(result)
    if payload.get("trade_state") == "SUCCESS" and order.status == OrderStatus.PENDING:
        order.trade_no = payload.get("transaction_id") or order.trade_no
        order.status = OrderStatus.PAID
        order.paid_at = datetime.now(timezone.utc)
        await _credit_paid_order(order, user, db)
        await db.commit()


@router.post("/create_order")
async def create_order(req: CreateOrderRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if req.pay_type != "wxpay":
        raise HTTPException(status_code=400, detail="Only wxpay is supported")
    if not req.items:
        raise HTTPException(status_code=400, detail="items must not be empty")
    if not settings.WECHAT_MCHID or not settings.WECHAT_APPID or not settings.WECHAT_CERT_SERIAL_NO or not settings.WECHAT_APIV3_KEY:
        raise HTTPException(status_code=503, detail="WeChat Pay is not configured")

    normalized_items = []
    total_usd = Decimal("0")
    for item in req.items:
        if not item.group:
            raise HTTPException(status_code=400, detail="group is required")
        amount = Decimal(str(item.amount_usd))
        if amount < Decimal(str(settings.PAYMENT_MIN_PER_ITEM_USD)):
            raise HTTPException(status_code=400, detail="An item amount is below the minimum")
        normalized_items.append({"group": item.group, "amount_usd": float(amount)})
        total_usd += amount

    if total_usd < Decimal(str(settings.PAYMENT_MIN_TOTAL_USD)):
        raise HTTPException(status_code=400, detail="Order total is below the minimum")
    if total_usd > Decimal(str(settings.PAYMENT_MAX_TOTAL_USD)):
        raise HTTPException(status_code=400, detail="Order total exceeds the maximum")

    exchange_rate = Decimal(str(await _get_exchange_rate()))
    amount_cny = _round_money(total_usd * exchange_rate)
    out_trade_no = f"CY{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:10].upper()}"
    description = ", ".join(f"{item['group']}:{item['amount_usd']}" for item in normalized_items)

    payload = {
        "appid": settings.WECHAT_APPID,
        "mchid": settings.WECHAT_MCHID,
        "description": f"CyImagePro recharge {description}"[:127],
        "out_trade_no": out_trade_no,
        "notify_url": settings.WECHAT_NOTIFY_URL,
        "amount": {"total": int((amount_cny * 100).to_integral_value(rounding=ROUND_HALF_UP)), "currency": "CNY"},
    }
    code, result = await wechatpay_request("/v3/pay/transactions/native", method="POST", data=payload)
    if code != 200:
        raise HTTPException(status_code=502, detail=f"Create order failed: {result}")

    wx_result = json.loads(result)
    order = Order(
        user_id=user.id,
        out_trade_no=out_trade_no,
        package_usd=int(total_usd),
        group=normalized_items[0]["group"] if len(normalized_items) == 1 else "mixed",
        amount_usd=_round_money(total_usd),
        amount_cny=amount_cny,
        exchange_rate=exchange_rate,
        items_json=_serialize_items(normalized_items),
        pay_type=req.pay_type,
        status=OrderStatus.PENDING,
    )
    db.add(order)
    await db.commit()

    return {
        "out_trade_no": out_trade_no,
        "code_url": wx_result.get("code_url"),
        "amount_cny": float(amount_cny),
        "exchange_rate": float(exchange_rate),
        "amount_usd": float(_round_money(total_usd)),
        "group": order.group,
        "items": normalized_items,
        "status": OrderStatus.PENDING,
    }


@router.post("/notify")
async def payment_notify(request: Request, db: AsyncSession = Depends(get_db)):
    body = await request.json()
    resource = body.get("resource") or {}
    out_trade_no = resource.get("out_trade_no") or body.get("out_trade_no")
    transaction_id = resource.get("transaction_id") or body.get("transaction_id")
    if not out_trade_no:
        return Response(status_code=204)

    order = (await db.execute(select(Order).where(Order.out_trade_no == out_trade_no))).scalar_one_or_none()
    if not order:
        return Response(status_code=204)

    user = (await db.execute(select(User).where(User.id == order.user_id))).scalar_one_or_none()
    if not user:
        return Response(status_code=204)

    if order.status == OrderStatus.PENDING:
        order.trade_no = transaction_id or order.trade_no
        order.status = OrderStatus.PAID
        order.paid_at = datetime.now(timezone.utc)
        await _credit_paid_order(order, user, db)
        await db.commit()
    return Response(status_code=204)


@router.get("/query/{out_trade_no}")
async def query_order(out_trade_no: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    order = (
        await db.execute(select(Order).where(Order.out_trade_no == out_trade_no, Order.user_id == user.id))
    ).scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.status == OrderStatus.PENDING:
        await _sync_order_status(order, user, db)
        await db.refresh(order)

    status_value = OrderStatus.ALLOCATED if order.status == OrderStatus.ASSIGNED else order.status
    items = json.loads(order.items_json) if order.items_json else []
    first_group = items[0]["group"] if items else order.group
    user_token = None
    if first_group:
        user_token = (
            await db.execute(select(UserToken).where(UserToken.user_id == user.id, UserToken.group == first_group))
        ).scalar_one_or_none()

    return {
        "out_trade_no": order.out_trade_no,
        "status": status_value,
        "amount_usd": float(order.amount_usd or 0),
        "amount_cny": float(order.amount_cny),
        "group": order.group,
        "items": items,
        "paid_at": order.paid_at.isoformat() if order.paid_at else None,
        "api_token": ((await db.execute(select(TokenInventory.token_value).where(TokenInventory.id == user_token.token_id))).scalar_one_or_none() if user_token else None),
    }


@router.post("/close/{out_trade_no}")
async def close_order(out_trade_no: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    order = (
        await db.execute(select(Order).where(Order.out_trade_no == out_trade_no, Order.user_id == user.id))
    ).scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status != OrderStatus.PENDING:
        raise HTTPException(status_code=400, detail="Only pending orders can be closed")

    path = f"/v3/pay/transactions/out-trade-no/{out_trade_no}/close"
    code, result = await wechatpay_request(path, method="POST", data={"mchid": settings.WECHAT_MCHID})
    if code not in (200, 204):
        raise HTTPException(status_code=502, detail=f"Close order failed: {result}")
    order.status = OrderStatus.CLOSED
    await db.commit()
    return {"status": OrderStatus.CLOSED, "out_trade_no": out_trade_no}


@router.post("/refund_order/{out_trade_no}")
async def refund_order(out_trade_no: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    order = (
        await db.execute(select(Order).where(Order.out_trade_no == out_trade_no, Order.user_id == user.id))
    ).scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status not in {OrderStatus.PAID, OrderStatus.ALLOCATED, OrderStatus.ASSIGNED}:
        raise HTTPException(status_code=400, detail="Only paid or allocated orders can be refunded")

    out_refund_no = f"RF{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:8].upper()}"
    total_fee = int(round(float(order.amount_cny) * 100))
    refund_data = {
        "out_refund_no": out_refund_no,
        "out_trade_no": out_trade_no,
        "reason": "user refund",
        "amount": {"refund": total_fee, "total": total_fee, "currency": "CNY"},
    }
    if settings.WECHAT_REFUND_NOTIFY_URL:
        refund_data["notify_url"] = settings.WECHAT_REFUND_NOTIFY_URL

    code, result = await wechatpay_request("/v3/refund/domestic/refunds", method="POST", data=refund_data)
    if code != 200:
        raise HTTPException(status_code=502, detail=f"Refund failed: {result}")

    await _rollback_refund(order, user, db)
    order.status_before_refund = order.status
    order.status = OrderStatus.REFUNDED
    order.out_refund_no = out_refund_no
    order.refunded_at = datetime.now(timezone.utc)
    await db.commit()
    return {"status": OrderStatus.REFUNDED, "out_trade_no": out_trade_no, "message": "Refund completed"}


@router.get("/refund_status/{out_trade_no}")
async def refund_status(out_trade_no: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    order = (
        await db.execute(select(Order).where(Order.out_trade_no == out_trade_no, Order.user_id == user.id))
    ).scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return {"status": order.status, "out_refund_no": order.out_refund_no, "amount_cny": float(order.amount_cny)}


@router.get("/orders")
async def list_orders(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    orders = (
        await db.execute(select(Order).where(Order.user_id == user.id).order_by(Order.created_at.desc()))
    ).scalars().all()
    result = []
    for order in orders:
        items = json.loads(order.items_json) if order.items_json else []
        status_value = OrderStatus.ALLOCATED if order.status == OrderStatus.ASSIGNED else order.status
        result.append(
            {
                "out_trade_no": order.out_trade_no,
                "total_usd": float(order.amount_usd or 0),
                "total_cny": float(order.amount_cny),
                "status": status_value,
                "items": items,
                "created_at": order.created_at.isoformat() if order.created_at else None,
                "paid_at": order.paid_at.isoformat() if order.paid_at else None,
                "allocated_at": order.allocated_at.isoformat() if order.allocated_at else None,
                "amount_cny": float(order.amount_cny),
                "amount_usd": float(order.amount_usd or 0),
            }
        )
    return result


@router.get("/packages")
async def get_packages(db: AsyncSession = Depends(get_db)):
    rate = await _get_exchange_rate()
    return {
        "exchange_rate": rate,
        "groups": await list_charge_groups(db),
        "limits": {
            "min_total_usd": settings.PAYMENT_MIN_TOTAL_USD,
            "max_total_usd": settings.PAYMENT_MAX_TOTAL_USD,
            "min_per_item_usd": settings.PAYMENT_MIN_PER_ITEM_USD,
        },
    }
