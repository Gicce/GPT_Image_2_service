import uuid
import logging
import os
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, Field

from app.core.database import get_db
from app.core.security import get_current_user, get_admin_user
from app.core.config import settings
from app.core.redis import get_redis
from app.core.wechatpay import get_wxpay, wechatpay_request
from app.models.user import User
from app.models.token import Order, OrderStatus
from app.services.order_assignment import assign_paid_order, InvalidOrderStatusError
from app.services import billing

logger = logging.getLogger(__name__)
router = APIRouter()
MIN_PAYMENT_CNY = 0.01


def _wechatpay_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=502, detail=f"WeChat Pay request failed: {exc}")


def is_wechat_pay_configured() -> bool:
    """Check if WeChat Pay is fully configured with valid credentials."""
    return bool(
        settings.WECHAT_MCHID
        and settings.WECHAT_APPID
        and settings.WECHAT_APIV3_KEY
        and settings.WECHAT_CERT_SERIAL_NO
        and settings.WECHAT_PRIVATE_KEY_PATH
        and os.path.exists(settings.WECHAT_PRIVATE_KEY_PATH)
    )


def should_use_dev_payment() -> bool:
    """Return True if we should use development mode payment (skip real WeChat Pay)."""
    return settings.APP_ENV == "development" and not is_wechat_pay_configured()


async def _get_exchange_rate() -> float:
    redis = get_redis()
    cached = await redis.get("exchange_rate_usd_cny")
    if cached:
        return float(cached)
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(settings.EXCHANGE_RATE_API)
            data = resp.json()
            rate = float(data["rates"]["CNY"])
            await redis.setex("exchange_rate_usd_cny", 3600, str(rate))
            return rate
    except Exception:
        return 7.25


async def _validate_amount(total_usd: float) -> tuple[float, float]:
    if total_usd < settings.PAYMENT_MIN_TOTAL_USD or total_usd > settings.PAYMENT_MAX_TOTAL_USD:
        raise HTTPException(
            status_code=400,
            detail=f"充值金额需在 ${settings.PAYMENT_MIN_TOTAL_USD} ~ ${settings.PAYMENT_MAX_TOTAL_USD} 之间",
        )
    rate = await _get_exchange_rate()
    amount_cny = round(total_usd * rate, 2)
    if amount_cny < MIN_PAYMENT_CNY:
        raise HTTPException(status_code=400, detail="充值金额需不少于 ¥0.01")
    return amount_cny, rate


class CreateOrderRequest(BaseModel):
    """充值下单金额。

    amount_usd：V4 标准字段（到账 USD）。
    total_usd：V3 旧版客户端字段，短期兼容（V4 客户端不再发送）。
    """
    amount_usd: Optional[float] = Field(default=None, gt=0)
    total_usd: Optional[float] = Field(default=None, gt=0)


def _resolve_amount_usd(req: CreateOrderRequest) -> float:
    amount = req.amount_usd if req.amount_usd is not None else req.total_usd
    if amount is None:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_RECHARGE_AMOUNT",
                "message": "充值金额格式无效：请求体需包含数字类型的 amount_usd（旧版本客户端为 total_usd）",
            },
        )
    return amount


@router.post("/create_order")
async def create_order(
    req: CreateOrderRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """创建余额充值订单（单一计费主体，无分组概念）。

    币种语义：amount_usd = 到账 USD 余额；amount_cny = 微信实付人民币（分）。
    兑换按下单时汇率快照，订单保存汇率，到账金额以下单快照为准。
    """
    amount_usd = _resolve_amount_usd(req)
    amount_cny, rate = await _validate_amount(amount_usd)

    # 服务端防连击：10 秒内同用户已创建同金额待支付订单则拒绝（前端 loading 防抖的兜底；
    # 不同金额视为用户主动改单，放行）
    recent = await db.execute(
        select(Order.id).where(
            Order.user_id == user.id,
            Order.status == OrderStatus.PENDING,
            Order.amount_usd == Decimal(str(amount_usd)),
            Order.created_at > datetime.now(timezone.utc) - timedelta(seconds=10),
        ).limit(1)
    )
    if recent.scalar_one_or_none():
        raise HTTPException(status_code=429, detail="请求过于频繁，请先完成或取消当前待支付订单")

    out_trade_no = f"CY{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:8].upper()}"

    order = Order(
        user_id=user.id,
        out_trade_no=out_trade_no,
        amount_usd=Decimal(str(amount_usd)),
        amount_cny=Decimal(str(amount_cny)),
        exchange_rate=Decimal(str(rate)),
        pay_type="wxpay",
        status="pending",
    )
    db.add(order)
    await db.flush()

    dev_mode = should_use_dev_payment()
    wechat_configured = is_wechat_pay_configured()
    logger.info(f"Order {out_trade_no}: APP_ENV={settings.APP_ENV}, dev_mode={dev_mode}, wechat_configured={wechat_configured}")

    code_url = None

    if dev_mode:
        logger.info(f"Development mode: skipping WeChat Pay request for order {out_trade_no}")
        code_url = f"dev://pay/{out_trade_no}"
    elif not wechat_configured:
        raise HTTPException(
            status_code=500,
            detail="微信支付配置不完整：WECHAT_PRIVATE_KEY_PATH 未配置或文件不存在"
        )
    else:
        time_expire = (datetime.now(timezone(timedelta(hours=8))) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S+08:00")
        try:
            code, result = await wechatpay_request(
                "/v3/pay/transactions/native",
                method="POST",
                data={
                    "appid": settings.WECHAT_APPID,
                    "mchid": settings.WECHAT_MCHID,
                    "description": "CyImagePro 余额充值",
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

        import json
        result = json.loads(result)
        code_url = result.get("code_url")

    response = {
        "out_trade_no": out_trade_no,
        "code_url": code_url,
        "amount_usd": amount_usd,
        "amount_cny": amount_cny,
        "exchange_rate": rate,
        "status": "pending",
    }

    if dev_mode:
        response["dev_mode"] = True
        response["message"] = "开发环境未配置微信支付，请使用 /api/pay/dev/mark_paid 模拟支付成功"

    return response


def _parse_wechat_callback(wxpay, headers: dict, body: str) -> dict | None:
    """验签并解密微信回调，返回解密后的 resource 明文（dict）。失败返回 None。

    wechatpayv3 SDK 的 callback() 返回 dict：原始 body + 'resource' 键（已解密）。
    """
    result = wxpay.callback(headers, body)
    if not result or not isinstance(result, dict):
        return None
    resource = result.get("resource")
    if isinstance(resource, str):
        import json
        try:
            resource = json.loads(resource)
        except (TypeError, ValueError):
            return None
    if not isinstance(resource, dict):
        return None
    return resource


@router.post("/notify")
async def wechat_notify(request: Request, db: AsyncSession = Depends(get_db)):
    headers = {k: v for k, v in request.headers.items()}
    body = (await request.body()).decode("utf-8")

    try:
        wxpay = get_wxpay()
        data = _parse_wechat_callback(wxpay, headers, body)
    except Exception:
        logger.exception("wechat notify decrypt failed")
        data = None

    if data is None:
        return Response(
            status_code=400,
            content='{"code": "FAIL", "message": "验签失败"}',
            media_type="application/json",
        )

    if data.get("trade_state") != "SUCCESS":
        return Response(status_code=200)

    out_trade_no = data.get("out_trade_no")
    transaction_id = data.get("transaction_id")
    if not out_trade_no:
        logger.warning("Notify: missing out_trade_no")
        return Response(status_code=200)

    # 商户号校验（防串单）
    if settings.WECHAT_MCHID and data.get("mchid") not in (None, settings.WECHAT_MCHID):
        logger.warning(f"Notify: mchid mismatch {data.get('mchid')} != {settings.WECHAT_MCHID}")
        return Response(status_code=200)

    res = await db.execute(
        select(Order).where(Order.out_trade_no == out_trade_no).with_for_update()
    )
    order = res.scalar_one_or_none()

    if not order:
        logger.warning(f"Notify: Order {out_trade_no} not found")
        return Response(status_code=200)

    if order.status == OrderStatus.ASSIGNED:
        logger.info(f"Notify: Order {out_trade_no} already credited (idempotent)")
        return Response(status_code=200)

    if order.status in (OrderStatus.CLOSED, OrderStatus.REFUNDING, OrderStatus.REFUNDED):
        logger.info(f"Notify: Order {out_trade_no} status is {order.status}, ignoring")
        return Response(status_code=200)

    # 金额校验：回调分 ≠ 订单应付分 → 记录告警并拒绝对账不符的入账
    expected_fee = int(round(float(order.amount_cny) * 100))
    paid_fee = (data.get("amount") or {}).get("total")
    if paid_fee is not None and int(paid_fee) != expected_fee:
        logger.error(
            f"Notify: Order {out_trade_no} amount mismatch: paid={paid_fee} expected={expected_fee}"
        )
        return Response(status_code=200)

    if order.status == OrderStatus.PENDING:
        order.status = OrderStatus.PAID
        order.paid_at = datetime.now(timezone.utc)
        order.trade_no = transaction_id

    if order.status == OrderStatus.PAID:
        try:
            await assign_paid_order(db, order, auto=True)
            await db.commit()
            logger.info(f"Notify: Order {out_trade_no} credited successfully")
        except InvalidOrderStatusError as e:
            logger.warning(f"Notify: Order {out_trade_no} - {e}")
            await db.commit()
        except Exception as e:
            logger.error(f"Notify: Order {out_trade_no} credit failed: {e}")
            await db.rollback()

    return Response(status_code=200)


@router.get("/query/{out_trade_no}")
async def query_order(
    out_trade_no: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Order).where(
            Order.out_trade_no == out_trade_no,
            Order.user_id == user.id
        ).with_for_update()
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")

    if order.status == OrderStatus.PENDING and is_wechat_pay_configured():
        path = f"/v3/pay/transactions/out-trade-no/{out_trade_no}?mchid={settings.WECHAT_MCHID}"
        code, wx_result = await wechatpay_request(path)
        import json
        wx_result = json.loads(wx_result) if wx_result else {}
        if code == 200 and wx_result.get("trade_state") == "SUCCESS":
            paid_fee = (wx_result.get("amount") or {}).get("total")
            if paid_fee is not None and int(paid_fee) != int(round(float(order.amount_cny) * 100)):
                logger.error(
                    f"Query: Order {out_trade_no} amount mismatch: paid={paid_fee}"
                )
            else:
                order.status = OrderStatus.PAID
                order.paid_at = datetime.now(timezone.utc)
                order.trade_no = wx_result.get("transaction_id")

    if order.status == OrderStatus.PAID:
        try:
            await assign_paid_order(db, order, auto=True)
            await db.commit()
        except InvalidOrderStatusError as e:
            logger.warning(f"Query: Order {out_trade_no} - {e}")
            await db.commit()
        except Exception as e:
            logger.error(f"Query: Order {out_trade_no} credit failed: {e}")
            await db.rollback()

    # 入账后返回最新余额
    await db.refresh(user)
    return {
        "out_trade_no": order.out_trade_no,
        "status": order.status,
        "amount_usd": float(order.amount_usd),
        "amount_cny": float(order.amount_cny),
        "paid_at": order.paid_at.isoformat() if order.paid_at else None,
        "balance_usd": str(billing.q6(billing.d(user.balance_usd))),
        "trial_credit_usd": str(billing.q6(billing.d(user.trial_credit_usd))),
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

    if is_wechat_pay_configured():
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


async def _recharge_refund_common(db: AsyncSession, order: Order) -> None:
    """退款冲正：从用户现金余额扣回充值金额（余额不足扣到 0 为止），写流水。"""
    amount = Decimal(str(order.amount_usd))
    await billing.debit_balance_for_refund(
        db, order.user_id, amount,
        related_order_id=order.id,
        remark=f"recharge refund {order.out_trade_no}",
    )


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
        raise HTTPException(status_code=400, detail="只能退款已支付或已入账的订单")

    if order.status == OrderStatus.ASSIGNED:
        await _recharge_refund_common(db, order)

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
        await db.rollback()
        raise HTTPException(status_code=502, detail=f"退款失败: {wx_result}")

    order.status = OrderStatus.REFUNDED
    order.out_refund_no = out_refund_no
    order.refunded_at = datetime.now(timezone.utc)

    redis = get_redis()
    await redis.delete(f"refund:auto:{out_trade_no}")

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
    import json
    return json.loads(result)


@router.post("/refund/notify")
async def refund_notify(request: Request, db: AsyncSession = Depends(get_db)):
    headers = {k: v for k, v in request.headers.items()}
    body = (await request.body()).decode("utf-8")

    try:
        wxpay = get_wxpay()
        data = _parse_wechat_callback(wxpay, headers, body)
    except Exception:
        logger.exception("wechat refund notify decrypt failed")
        data = None

    if data is None:
        return Response(
            status_code=400,
            content='{"code": "FAIL", "message": "验签失败"}',
            media_type="application/json",
        )

    out_trade_no = data.get("out_trade_no")
    refund_status = data.get("refund_status")

    if out_trade_no and refund_status:
        res = await db.execute(select(Order).where(Order.out_trade_no == out_trade_no))
        order = res.scalar_one_or_none()
        if order:
            if refund_status == "SUCCESS" and order.status != OrderStatus.REFUNDED:
                order.status = OrderStatus.REFUNDED
                order.refunded_at = datetime.now(timezone.utc)
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
        raise HTTPException(status_code=400, detail="只能退款已支付或已入账的订单")

    order.status_before_refund = order.status
    order.status = OrderStatus.REFUNDING
    order.refund_requested_at = datetime.now(timezone.utc)

    redis = get_redis()
    await redis.setex(f"refund:auto:{out_trade_no}", 900, "1")

    return {"status": "refunding", "out_trade_no": out_trade_no, "message": "退款申请已提交，等待确认"}


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
    """充值信息：单一余额充值 + 汇率 + 限额。"""
    rate = await _get_exchange_rate()
    cfg = await billing.get_image2_config(db)
    price = billing.q6(billing.d(cfg.price_per_call)) if cfg and cfg.price_per_call is not None else None
    return {
        "exchange_rate": rate,
        "currency": "USD",
        "model": {
            "name": "gpt-image-2",
            "display_name": "Image2",
            "price_per_call_usd": str(price) if price else None,
        },
        "limits": {
            "min_total_usd": settings.PAYMENT_MIN_TOTAL_USD,
            "max_total_usd": settings.PAYMENT_MAX_TOTAL_USD,
        },
    }


# ── Development-only: Simulate Payment Success ──────────────────────────

@router.post("/dev/mark_paid/{out_trade_no}")
async def dev_mark_paid(
    out_trade_no: str,
    _=Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """开发环境模拟支付成功（生产环境禁用）。"""
    if settings.APP_ENV != "development":
        raise HTTPException(
            status_code=403,
            detail="开发模拟接口在生产环境已禁用 (APP_ENV=production)"
        )

    result = await db.execute(
        select(Order).where(Order.out_trade_no == out_trade_no).with_for_update()
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")

    if order.status == OrderStatus.ASSIGNED:
        u = await db.get(User, order.user_id)
        return {
            "out_trade_no": order.out_trade_no,
            "status": order.status,
            "message": "订单已入账，幂等返回",
            "balance_usd": str(billing.q6(billing.d(u.balance_usd))) if u else None,
        }

    if order.status in (OrderStatus.CLOSED, OrderStatus.REFUNDING, OrderStatus.REFUNDED):
        raise HTTPException(
            status_code=400,
            detail=f"订单状态为 {order.status}，无法模拟支付"
        )

    if order.status == OrderStatus.PENDING:
        order.status = OrderStatus.PAID
        order.paid_at = datetime.now(timezone.utc)
        order.trade_no = f"DEV{uuid.uuid4().hex[:24].upper()}"

    assignment_result = None
    if order.status == OrderStatus.PAID:
        try:
            await assign_paid_order(db, order, auto=False)
            assignment_result = {"success": True, "message": "充值入账成功"}
        except Exception as e:
            logger.error(f"Dev mark_paid: Order {out_trade_no} credit failed: {e}")
            assignment_result = {"success": False, "error": str(e)}

    u = await db.get(User, order.user_id)
    await db.commit()

    response = {
        "out_trade_no": order.out_trade_no,
        "status": order.status,
        "user_id": order.user_id,
        "amount_usd": float(order.amount_usd),
        "amount_cny": float(order.amount_cny),
        "paid_at": order.paid_at.isoformat() if order.paid_at else None,
        "balance_usd": str(billing.q6(billing.d(u.balance_usd))) if u else None,
        "trial_credit_usd": str(billing.q6(billing.d(u.trial_credit_usd))) if u else None,
    }
    if assignment_result:
        response["assignment"] = assignment_result
    return response
