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
from app.models.token import TokenInventory, Order, OrderStatus

router = APIRouter()
MIN_PAYMENT_CNY = 0.01


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


class OrderItem(BaseModel):
    group: str
    amount_usd: float

class CreateOrderRequest(BaseModel):
    items: list[OrderItem]


@router.post("/create_order")
async def create_order(
    req: CreateOrderRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not req.items:
        raise HTTPException(status_code=400, detail="至少选择一个分组")

    for item in req.items:
        if item.amount_usd < settings.PAYMENT_MIN_PER_ITEM_USD:
            raise HTTPException(status_code=400, detail=f"分组 {item.group} 金额不能小于 ${settings.PAYMENT_MIN_PER_ITEM_USD}")

    total_usd = sum(item.amount_usd for item in req.items)
    if total_usd < settings.PAYMENT_MIN_TOTAL_USD or total_usd > settings.PAYMENT_MAX_TOTAL_USD:
        raise HTTPException(status_code=400, detail=f"总金额需在 ${settings.PAYMENT_MIN_TOTAL_USD} ~ ${settings.PAYMENT_MAX_TOTAL_USD} 之间")

    rate = await _get_exchange_rate()
    amount_cny = round(total_usd * rate, 2)
    if amount_cny < MIN_PAYMENT_CNY:
        raise HTTPException(status_code=400, detail="充值金额需不少于 ¥0.01")

    groups = ",".join(item.group for item in req.items)
    items_json = json.dumps([{"group": item.group, "amount_usd": item.amount_usd} for item in req.items])
    out_trade_no = f"CY{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:8].upper()}"

    order = Order(
        user_id=user.id,
        out_trade_no=out_trade_no,
        group=groups,
        amount_usd=total_usd,
        amount_cny=amount_cny,
        exchange_rate=rate,
        items_json=items_json,
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
                "description": f"CyImagePro recharge {groups}",
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
        "amount_usd": total_usd,
        "amount_cny": amount_cny,
        "exchange_rate": rate,
        "group": groups,
        "items": [{"group": item.group, "amount_usd": item.amount_usd} for item in req.items],
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
    if order and order.status == OrderStatus.PENDING:
        order.status = OrderStatus.PAID
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

    if order.status == OrderStatus.PENDING:
        path = f"/v3/pay/transactions/out-trade-no/{out_trade_no}?mchid={settings.WECHAT_MCHID}"
        code, wx_result = await wechatpay_request(path)
        wx_result = json.loads(wx_result) if wx_result else {}
        if code == 200 and wx_result.get("trade_state") == "SUCCESS":
            order.status = OrderStatus.PAID
            order.paid_at = datetime.now(timezone.utc)
            order.trade_no = wx_result.get("transaction_id")
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
    if order.status != OrderStatus.PENDING:
        raise HTTPException(status_code=400, detail="只能关闭待支付订单")

    path = f"/v3/pay/transactions/out-trade-no/{out_trade_no}/close"
    code, wx_result = await wechatpay_request(
        path,
        method="POST",
        data={"mchid": settings.WECHAT_MCHID},
    )
    if code not in (200, 204):
        raise HTTPException(status_code=502, detail=f"关闭订单失败: {wx_result}")

    order.status = OrderStatus.CLOSED
    return {"status": OrderStatus.CLOSED, "out_trade_no": out_trade_no}


class RefundRequest(BaseModel):
    reason: str = ""
    refund_amount_cny: float | None = None


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
    if order.status not in (OrderStatus.PAID, OrderStatus.ASSIGNED):
        raise HTTPException(status_code=400, detail="只能退款已支付或已分配的订单")

    # 冲正：对 ASSIGNED 订单扣除余额、撤销 Token
    if order.status == OrderStatus.ASSIGNED:
        items = json.loads(order.items_json) if order.items_json else [{"group": order.group, "amount_usd": float(order.amount_usd)}]
        for item in items:
            ut_result = await db.execute(
                select(UserToken).where(UserToken.user_id == order.user_id, UserToken.group == item["group"])
            )
            ut = ut_result.scalar_one_or_none()
            if ut:
                new_balance = float(ut.balance_usd) - item["amount_usd"]
                if new_balance <= 0:
                    tok_result = await db.execute(select(TokenInventory).where(TokenInventory.id == ut.token_id))
                    tok = tok_result.scalar_one_or_none()
                    if tok:
                        tok.is_assigned = False
                        tok.assigned_to = None
                        tok.assigned_at = None
                    await db.delete(ut)
                else:
                    ut.balance_usd = new_balance

    out_refund_no = f"RF{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:8].upper()}"
    total_fee = int(round(float(order.amount_cny) * 100))

    if req.refund_amount_cny is not None:
        refund_fee = int(round(req.refund_amount_cny * 100))
        if refund_fee <= 0 or refund_fee > total_fee:
            raise HTTPException(status_code=400, detail="退款金额无效，需在 ¥0.01 ~ ¥{} 之间".format(float(order.amount_cny)))
    else:
        refund_fee = total_fee

    refund_data = {
        "out_refund_no": out_refund_no,
        "out_trade_no": out_trade_no,
        "reason": req.reason or "admin refund",
        "amount": {"refund": refund_fee, "total": total_fee, "currency": "CNY"},
    }
    if settings.WECHAT_REFUND_NOTIFY_URL:
        refund_data["notify_url"] = settings.WECHAT_REFUND_NOTIFY_URL

    code, wx_result = await wechatpay_request(
        "/v3/refund/domestic/refunds",
        method="POST",
        data=refund_data,
    )
    if code != 200:
        raise HTTPException(status_code=502, detail=f"退款失败: {wx_result}")

    order.status = "refunded"
    order.out_refund_no = out_refund_no
    return {"status": "refunded", "out_refund_no": out_refund_no}


@router.get("/refund/query/{out_refund_no}")
async def query_refund(
    out_refund_no: str,
    _=Depends(get_admin_user),
):
    path = f"/v3/refund/domestic/refunds/{out_refund_no}"
    code, result = await wechatpay_request(path)
    if code != 200:
        raise HTTPException(status_code=502, detail=f"查询退款失败: {result}")
    return json.loads(result)


@router.post("/refund/notify")
async def refund_notify(request: Request, db: AsyncSession = Depends(get_db)):
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
    out_trade_no = data.get("out_trade_no")
    refund_status = data.get("refund_status")

    if out_trade_no and refund_status:
        res = await db.execute(select(Order).where(Order.out_trade_no == out_trade_no))
        order = res.scalar_one_or_none()
        if order:
            if refund_status == "SUCCESS":
                order.status = OrderStatus.REFUNDED
            elif refund_status == "CHANGE":
                order.status = OrderStatus.REFUND_CHANGE

    return Response(status_code=200)


@router.post("/refund_order/{out_trade_no}")
async def client_refund_order(
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
    if order.status not in (OrderStatus.PAID, OrderStatus.ASSIGNED):
        raise HTTPException(status_code=400, detail="只能退款已支付或已分配的订单")

    # 冲正：对 ASSIGNED 订单扣除余额、撤销 Token
    if order.status == OrderStatus.ASSIGNED:
        items = json.loads(order.items_json) if order.items_json else [{"group": order.group, "amount_usd": float(order.amount_usd)}]
        for item in items:
            ut_result = await db.execute(
                select(UserToken).where(UserToken.user_id == order.user_id, UserToken.group == item["group"])
            )
            ut = ut_result.scalar_one_or_none()
            if ut:
                new_balance = float(ut.balance_usd) - item["amount_usd"]
                if new_balance <= 0:
                    tok_result = await db.execute(select(TokenInventory).where(TokenInventory.id == ut.token_id))
                    tok = tok_result.scalar_one_or_none()
                    if tok:
                        tok.is_assigned = False
                        tok.assigned_to = None
                        tok.assigned_at = None
                    await db.delete(ut)
                else:
                    ut.balance_usd = new_balance

    # 发起微信全额退款
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

    code, wx_result = await wechatpay_request(
        "/v3/refund/domestic/refunds",
        method="POST",
        data=refund_data,
    )
    if code != 200:
        raise HTTPException(status_code=502, detail=f"退款失败: {wx_result}")

    order.out_refund_no = out_refund_no
    return {"status": "refunding", "out_refund_no": out_refund_no}


@router.get("/refund_status/{out_trade_no}")
async def client_refund_status(
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
    return {
        "status": order.status,
        "out_refund_no": order.out_refund_no,
        "amount_cny": float(order.amount_cny),
    }


@router.get("/orders")
async def list_user_orders(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Order)
        .where(Order.user_id == user.id)
        .order_by(Order.created_at.desc())
    )
    orders = result.scalars().all()
    return [
        {
            "out_trade_no": o.out_trade_no,
            "group": o.group,
            "amount_usd": float(o.amount_usd),
            "amount_cny": float(o.amount_cny),
            "exchange_rate": float(o.exchange_rate) if o.exchange_rate else None,
            "status": o.status,
            "pay_type": o.pay_type,
            "created_at": o.created_at.isoformat(),
            "paid_at": o.paid_at.isoformat() if o.paid_at else None,
        }
        for o in orders
    ]


@router.get("/packages")
async def get_packages(db: AsyncSession = Depends(get_db)):
    from app.models.content import Group
    rate = await _get_exchange_rate()
    result = await db.execute(select(Group).order_by(Group.sort_order))
    groups = result.scalars().all()
    return {
        "exchange_rate": rate,
        "groups": [{"name": g.name, "description": g.description} for g in groups],
        "limits": {
            "min_total_usd": settings.PAYMENT_MIN_TOTAL_USD,
            "max_total_usd": settings.PAYMENT_MAX_TOTAL_USD,
            "min_per_item_usd": settings.PAYMENT_MIN_PER_ITEM_USD,
        },
    }
