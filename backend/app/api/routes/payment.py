import hashlib
import uuid
import httpx
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.config import settings
from app.core.redis import get_redis
from app.models.user import User
from app.models.token import TokenInventory, Order

router = APIRouter()

PACKAGES = {10: "$10 套餐", 20: "$20 套餐", 50: "$50 套餐", 100: "$100 套餐"}


def _md5_sign(params: dict, key: str) -> str:
    # Filter out sign, sign_type and empty values
    filtered = {k: v for k, v in params.items() if k not in ("sign", "sign_type") and v != "" and v is not None}
    # Sort by ASCII key order
    sorted_str = "&".join(f"{k}={filtered[k]}" for k in sorted(filtered.keys()))
    # Append key
    sign_str = sorted_str + key
    return hashlib.md5(sign_str.encode("utf-8")).hexdigest()


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
        return 7.25  # fallback rate


class CreateOrderRequest(BaseModel):
    package_usd: int
    pay_type: str  # alipay / wxpay
    client_ip: str = "127.0.0.1"


@router.post("/create_order")
async def create_order(
    req: CreateOrderRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if req.package_usd not in PACKAGES:
        raise HTTPException(status_code=400, detail="无效的套餐")
    if req.pay_type not in ("alipay", "wxpay"):
        raise HTTPException(status_code=400, detail="不支持的支付方式")

    # Check stock
    stock = await db.execute(
        select(TokenInventory).where(
            TokenInventory.package_usd == req.package_usd,
            TokenInventory.is_trial == False,
            TokenInventory.is_assigned == False,
        ).limit(1)
    )
    if not stock.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="当前套餐暂时缺货，请联系客服")

    rate = await _get_exchange_rate()
    amount_cny = round(req.package_usd * rate, 2)
    out_trade_no = f"CY{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:8].upper()}"

    # Create order in DB
    order = Order(
        user_id=user.id,
        out_trade_no=out_trade_no,
        package_usd=req.package_usd,
        amount_cny=amount_cny,
        exchange_rate=rate,
        pay_type=req.pay_type,
        status="pending",
    )
    db.add(order)
    await db.flush()

    # Call 树杰支付 unified order API
    timestamp = str(int(datetime.now(timezone.utc).timestamp()))
    params = {
        "pid": str(settings.SHUJIE_PID),
        "method": "web",
        "device": "pc",
        "type": req.pay_type,
        "out_trade_no": out_trade_no,
        "notify_url": settings.SHUJIE_NOTIFY_URL,
        "name": PACKAGES[req.package_usd],
        "money": f"{amount_cny:.2f}",
        "client_ip": req.client_ip,
        "timestamp": timestamp,
    }
    params["sign"] = _md5_sign(params, settings.SHUJIE_MD5_KEY)
    params["sign_type"] = "MD5"

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{settings.SHUJIE_API_BASE}/create", data=params)
        result = resp.json()

    if result.get("code") != 0:
        raise HTTPException(status_code=400, detail=f"创建支付订单失败: {result.get('msg', '未知错误')}")

    # Save platform trade_no
    order.trade_no = result.get("trade_no")

    return {
        "out_trade_no": out_trade_no,
        "amount_cny": amount_cny,
        "exchange_rate": rate,
        "pay_type": result.get("pay_type"),
        "pay_info": result.get("pay_info"),  # QR code URL or payment URL
        "package_usd": req.package_usd,
    }


@router.post("/notify")
async def payment_notify(request: Request, db: AsyncSession = Depends(get_db)):
    form = await request.form()
    params = dict(form)

    # Verify MD5 signature
    expected_sign = _md5_sign(params, settings.SHUJIE_MD5_KEY)
    if params.get("sign") != expected_sign:
        return "fail"

    if params.get("trade_status") != "TRADE_SUCCESS":
        return "success"

    out_trade_no = params.get("out_trade_no")
    result = await db.execute(select(Order).where(Order.out_trade_no == out_trade_no))
    order = result.scalar_one_or_none()
    if not order or order.status == "paid":
        return "success"

    # Find available token for this package
    token_result = await db.execute(
        select(TokenInventory).where(
            TokenInventory.package_usd == order.package_usd,
            TokenInventory.is_trial == False,
            TokenInventory.is_assigned == False,
        ).limit(1)
    )
    token = token_result.scalar_one_or_none()
    if not token:
        # No stock — mark order paid but no token assigned yet
        order.status = "paid"
        order.paid_at = datetime.now(timezone.utc)
        return "success"

    now = datetime.now(timezone.utc)
    token.is_assigned = True
    token.assigned_to = order.user_id
    token.assigned_at = now

    order.status = "paid"
    order.paid_at = now
    order.token_id = token.id

    # Upgrade user to paid, add balance, assign token
    user_result = await db.execute(select(User).where(User.id == order.user_id))
    user = user_result.scalar_one_or_none()
    if user:
        user.account_type = "paid"
        user.balance_usd = float(user.balance_usd) + order.package_usd
        user.api_token_id = token.id

    return "success"


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

    token_value = None
    if order.status == "paid" and order.token_id:
        t = await db.execute(select(TokenInventory).where(TokenInventory.id == order.token_id))
        tok = t.scalar_one_or_none()
        if tok:
            token_value = tok.token_value

    return {
        "out_trade_no": order.out_trade_no,
        "status": order.status,
        "package_usd": order.package_usd,
        "amount_cny": float(order.amount_cny),
        "paid_at": order.paid_at.isoformat() if order.paid_at else None,
        "api_token": token_value,
    }


@router.get("/packages")
async def get_packages():
    rate = await _get_exchange_rate()
    return [
        {
            "package_usd": usd,
            "name": name,
            "price_cny": round(usd * rate, 2),
            "exchange_rate": rate,
        }
        for usd, name in PACKAGES.items()
    ]
