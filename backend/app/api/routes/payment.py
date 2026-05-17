import uuid
import json
import httpx
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.core.database import get_db
from app.core.security import get_current_user, get_admin_user
from app.core.config import settings
from app.core.redis import get_redis
from app.core.wechatpay import get_wxpay, wechatpay_request
from app.models.user import User, UserToken
from app.models.token import TokenInventory, Order

router = APIRouter()
MIN_PAYMENT_CNY = 1.00
MAX_PAYMENT_USD = 1000.00


def _wechatpay_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=502, detail=f"WeChat Pay request failed: {exc}")


async def _get_exchange_rate() -> float:
    redis = get_redis()
    cached = await redis.get("exchange_rate_usd_cny")
    if cached:
        return float(cached)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(settings.EXCHANGE_RATE_API)
            data = resp.json()
            rate = float(data["rates"]["CNY"])
            await redis.setex("exchange_rate_usd_cny", 3600, str(rate))
            return rate
    except Exception:
        return 7.25


class CreateOrderRequest(BaseModel):
    group: str
    amount_usd: float


@router.post("/create_order")
async def create_order(
    req: CreateOrderRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rate = await _get_exchange_rate()
    amount_cny = round(req.amount_usd * rate, 2)
    if req.amount_usd <= 0 or req.amount_usd > MAX_PAYMENT_USD or amount_cny < MIN_PAYMENT_CNY:
        raise HTTPException(status_code=400, detail="充值金额需不少于 ¥1，且不超过 $1000")

    out_trade_no = f"CY{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:8].upper()}"

    order = Order(
        user_id=user.id,
        out_trade_no=out_trade_no,
        group=req.group,
        amount_usd=req.amount_usd,
        amount_cny=amount_cny,
        exchange_rate=rate,
        pay_type="wxpay",
        status="pending",
    )
    db.add(order)
    await db.flush()

    time_expire = (datetime.now(timezone(timedelta(hours=8))) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S+08:00")
    try:
        code, result = await wechatpay_request(
            "/v3/pay/transactions/native",
            method="POST",
            data={
                "appid": settings.WECHAT_APPID,
                "mchid": settings.WECHAT_MCHID,
                "description": f"CyImagePro recharge {req.group}",
                "out_trade_no": out_trade_no,
                "notify_url": settings.WECHAT_NOTIFY_URL,
                "amount": {"total": int(round(amount_cny * 100)), "currency": "CNY"},
                "time_expire": time_expire,
            },
        )
    except Exception as exc:
        raise _wechatpay_error(exc) from exc

    if code != 200:
        raise HTTPException(status_code=502, detail=f"WeChat Pay create order failed: {result}")

    result = json.loads(result)

    return {
        "out_trade_no": out_trade_no,
        "code_url": result.get("code_url"),
        "amount_usd": req.amount_usd,
        "amount_cny": amount_cny,
        "exchange_rate": rate,
        "group": req.group,
        "status": "pending",
    }


@router.post("/notify")
async def wechat_notify(request: Request, db: AsyncSession = Depends(get_db)):
    headers = {k: v for k, v in request.headers.items()}
    body = (await request.body()).decode("utf-8")
    wxpay = get_wxpay()
    result = wxpay.callback(headers, body)
    if not result:
        return Response(
            status_code=400,
            content=json.dumps({"code": "FAIL", "message": "验签失败"}),
            media_type="application/json",
        )

    data = json.loads(result)
    if data.get("trade_state") != "SUCCESS":
        return Response(status_code=200)

    out_trade_no = data["out_trade_no"]
    res = await db.execute(select(Order).where(Order.out_trade_no == out_trade_no))
    order = res.scalar_one_or_none()
    if order and order.status == "pending":
        order.status = "paid"
        order.paid_at = datetime.now(timezone.utc)
        order.trade_no = data.get("transaction_id")
        user_res = await db.execute(select(User).where(User.id == order.user_id))
        u = user_res.scalar_one_or_none()
        if u:
            u.account_type = "paid"

    return Response(status_code=200)


@router.get("/query/{out_trade_no}")
async def query_order(
    out_trade_no: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Order).where(Order.out_trade_no == out_trade_no, Order.user_id == user.id)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")

    if order.status == "pending":
        path = f"/v3/pay/transactions/out-trade-no/{out_trade_no}?mchid={settings.WECHAT_MCHID}"
        code, wx_result = await wechatpay_request(path)
        wx_result = json.loads(wx_result) if wx_result else {}
        if code == 200 and wx_result.get("trade_state") == "SUCCESS":
            order.status = "paid"
            order.paid_at = datetime.now(timezone.utc)
            order.transaction_id = wx_result.get("transaction_id")
            user_res = await db.execute(select(User).where(User.id == user.id))
            u = user_res.scalar_one_or_none()
            if u:
                u.account_type = "paid"

    token_value = None
    if order.token_id:
        t = await db.execute(select(TokenInventory).where(TokenInventory.id == order.token_id))
        tok = t.scalar_one_or_none()
        if tok:
            token_value = tok.token_value

    return {
        "out_trade_no": order.out_trade_no,
        "status": order.status,
        "group": order.group,
        "amount_usd": float(order.amount_usd),
        "amount_cny": float(order.amount_cny),
        "paid_at": order.paid_at.isoformat() if order.paid_at else None,
        "api_token": token_value,
    }


@router.post("/close/{out_trade_no}")
async def close_order(
    out_trade_no: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Order).where(Order.out_trade_no == out_trade_no, Order.user_id == user.id)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status != "pending":
        raise HTTPException(status_code=400, detail="只能关闭待支付订单")

    path = f"/v3/pay/transactions/out-trade-no/{out_trade_no}/close"
    code, wx_result = await wechatpay_request(
        path,
        method="POST",
        data={"mchid": settings.WECHAT_MCHID},
    )
    if code not in (200, 204):
        raise HTTPException(status_code=502, detail=f"关闭订单失败: {wx_result}")

    order.status = "closed"
    return {"status": "closed", "out_trade_no": out_trade_no}


class RefundRequest(BaseModel):
    reason: str = ""


@router.post("/refund/{out_trade_no}")
async def refund_order(
    out_trade_no: str,
    req: RefundRequest = RefundRequest(),
    _=Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Order).where(Order.out_trade_no == out_trade_no))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status != "paid":
        raise HTTPException(status_code=400, detail="只能退款已支付订单")

    out_refund_no = f"RF{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:8].upper()}"
    total_fee = int(float(order.amount_cny) * 100)

    code, wx_result = await wechatpay_request(
        "/v3/refund/domestic/refunds",
        method="POST",
        data={
            "out_refund_no": out_refund_no,
            "out_trade_no": out_trade_no,
            "reason": req.reason or "admin refund",
            "amount": {"refund": total_fee, "total": total_fee, "currency": "CNY"},
        },
    )
    if code != 200:
        raise HTTPException(status_code=502, detail=f"退款失败: {wx_result}")

    order.status = "refunded"
    return {"status": "refunded", "out_refund_no": out_refund_no}


@router.get("/packages")
async def get_packages(db: AsyncSession = Depends(get_db)):
    from app.models.content import Group
    rate = await _get_exchange_rate()
    result = await db.execute(select(Group).order_by(Group.sort_order))
    groups = result.scalars().all()
    return {
        "exchange_rate": rate,
        "groups": [{"name": g.name, "description": g.description} for g in groups],
    }
