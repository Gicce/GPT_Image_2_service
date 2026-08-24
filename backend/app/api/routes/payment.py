import uuid
import logging
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
from app.core import wechatpay as wxpay_core
from app.models.user import User
from app.models.token import Order, OrderStatus, RefundRequest
from app.services.order_assignment import assign_paid_order, InvalidOrderStatusError
from app.services import billing
from app.services import refund as refund_service

logger = logging.getLogger(__name__)
router = APIRouter()
MIN_PAYMENT_CNY = 0.01


def _wechatpay_error(exc: Exception) -> HTTPException:
    # 具体异常只进服务端日志；对外返回稳定文案，避免泄露上游/内部信息
    logger.error("wechatpay request failed: %s: %s", type(exc).__name__, exc)
    return HTTPException(status_code=502, detail="微信支付服务暂时不可用，请稍后重试")


def is_wechat_pay_configured() -> bool:
    """Check if WeChat Pay is fully configured with valid credentials."""
    return wxpay_core.is_configured()


def should_use_dev_payment() -> bool:
    """Return True if we should use development mode payment (skip real WeChat Pay)."""
    return settings.APP_ENV == "development" and not is_wechat_pay_configured()


async def _get_exchange_rate() -> float:
    rate, _source, _at = await _get_exchange_rate_meta()
    return rate


async def _get_exchange_rate_meta() -> tuple[float, str, str]:
    """汇率 + 来源语义（供 UI 按 §26 规则标注：实时 API + 1h 缓存 = 参考汇率·每小时更新）。"""
    from datetime import datetime, timezone as _tz

    redis = get_redis()
    cached = await redis.get("exchange_rate_usd_cny")
    cached_at = await redis.get("exchange_rate_usd_cny_at")
    if cached:
        return float(cached), "realtime_cached", cached_at or ""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(settings.EXCHANGE_RATE_API)
            data = resp.json()
            rate = float(data["rates"]["CNY"])
            now_iso = datetime.now(_tz.utc).isoformat()
            await redis.setex("exchange_rate_usd_cny", 3600, str(rate))
            await redis.setex("exchange_rate_usd_cny_at", 3600, now_iso)
            return rate, "realtime_fresh", now_iso
    except Exception:
        return 7.25, "fallback_fixed", ""


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
    """创建余额充值订单（USD 兼容入口，V4.2 起到账 CY 点数）。

    币种语义：amount_usd = 旧客户端提交的到账 USD 金额（兼容窗口保留）；
    实际到账点数 = round(amount_usd × legacy_usd_to_credits)，微信按实时汇率付人民币。
    V4.2+ 客户端应使用 /create_order_cny（人民币直购）。
    """
    amount_usd = _resolve_amount_usd(req)
    amount_cny, rate = await _validate_amount(amount_usd)

    from app.services import config_service
    legacy_rate = await config_service.get_legacy_usd_to_credits(db)
    credits = int(Decimal(str(amount_usd)) * Decimal(legacy_rate))

    return await _create_recharge_order(
        db, user,
        amount_cny=amount_cny,
        amount_usd=Decimal(str(amount_usd)),
        exchange_rate=rate,
        credits=credits,
    )


class CreateOrderCnyRequest(BaseModel):
    """人民币直购（V4.2 标准入口）：¥N → N × credits_per_cny 点。"""
    amount_cny: float = Field(gt=0)


@router.post("/create_order_cny")
async def create_order_cny(
    req: CreateOrderCnyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services import config_service
    credits_per_cny = await config_service.get_credits_per_cny(db)
    min_cny = await config_service.get_config_int(db, "recharge_min_cny")
    max_cny = await config_service.get_config_int(db, "recharge_max_cny")

    amount_cny = round(float(req.amount_cny), 2)
    if amount_cny < min_cny or amount_cny > max_cny:
        raise HTTPException(
            status_code=400,
            detail=f"充值金额需在 ¥{min_cny} ~ ¥{max_cny} 之间",
        )

    credits = int(Decimal(str(amount_cny)) * Decimal(max(1, credits_per_cny)))
    rate, _src, _at = await _get_exchange_rate_meta()
    legacy_rate = await config_service.get_legacy_usd_to_credits(db)
    # USD 镜像 = 点数按固定 peg 反推（订单展示/旧客户端兼容；不参与计费）
    amount_usd = (Decimal(credits) / Decimal(legacy_rate)).quantize(Decimal("0.01"))

    return await _create_recharge_order(
        db, user,
        amount_cny=amount_cny,
        amount_usd=amount_usd,
        exchange_rate=rate,
        credits=credits,
    )


async def _create_recharge_order(
    db: AsyncSession,
    user: User,
    *,
    amount_cny: float,
    amount_usd: Decimal,
    exchange_rate: float,
    credits: int,
):
    """下单公共实现：订单快照 + 微信 Native code_url。"""
    # 服务端防连击：10 秒内同用户已创建同金额待支付订单则拒绝（前端 loading 防抖的兜底；
    # 不同金额视为用户主动改单，放行）
    recent = await db.execute(
        select(Order.id).where(
            Order.user_id == user.id,
            Order.status == OrderStatus.PENDING,
            Order.amount_cny == Decimal(str(amount_cny)),
            Order.created_at > datetime.now(timezone.utc) - timedelta(seconds=10),
        ).limit(1)
    )
    if recent.scalar_one_or_none():
        raise HTTPException(status_code=429, detail="请求过于频繁，请先完成或取消当前待支付订单")

    out_trade_no = f"CY{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:8].upper()}"

    order = Order(
        user_id=user.id,
        out_trade_no=out_trade_no,
        amount_usd=amount_usd,
        amount_cny=Decimal(str(amount_cny)),
        exchange_rate=Decimal(str(exchange_rate)),
        credits_granted=credits,
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
                    "description": "CyImagePro 点数充值",
                    "out_trade_no": out_trade_no,
                    "notify_url": settings.WECHAT_NOTIFY_URL,
                    "amount": {"total": int(round(amount_cny * 100)), "currency": "CNY"},
                    "time_expire": time_expire,
                },
            )
        except Exception as exc:
            raise _wechatpay_error(exc) from exc

        if code != 200:
            logger.error("wechatpay create order failed: code=%s body=%s", code, result)
            raise HTTPException(status_code=502, detail="微信下单失败，请稍后重试")

        import json
        result = json.loads(result)
        code_url = result.get("code_url")

    response = {
        "out_trade_no": out_trade_no,
        "code_url": code_url,
        "amount_usd": float(amount_usd),
        "amount_cny": amount_cny,
        "credits_granted": credits,
        "exchange_rate": exchange_rate,
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

    if order.status in (
        OrderStatus.CLOSED, OrderStatus.REFUND_REQUESTED, OrderStatus.REFUNDING,
        OrderStatus.PARTIALLY_REFUNDED, OrderStatus.REFUNDED, OrderStatus.REFUND_CHANGE,
    ):
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


class UserRefundRequest(BaseModel):
    reason: str = ""


@router.get("/refund/query/{out_refund_no}")
async def query_refund(
    out_refund_no: str,
    _=Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """管理员查询微信退款状态：查询同时驱动结算（回调丢失兜底）。"""
    req = await refund_service.get_request_by_out_refund_no(db, out_refund_no)
    if req is not None and req.status == "processing":
        await refund_service.sync_refund_from_wechat(db, req)
        await db.commit()
        await db.refresh(req)
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

    out_refund_no = data.get("out_refund_no")
    out_trade_no = data.get("out_trade_no")
    refund_status = data.get("refund_status")

    if out_refund_no:
        req = await refund_service.get_request_by_out_refund_no(db, out_refund_no)
        if req is not None:
            try:
                if refund_status == "SUCCESS":
                    await refund_service.settle_refund_success(
                        db, req, wechat_refund_id=data.get("refund_id")
                    )
                elif refund_status in ("ABNORMAL", "CLOSED"):
                    await refund_service.mark_refund_failed(
                        db, req, f"wechat notify status {refund_status}"
                    )
                await db.commit()
            except Exception:
                await db.rollback()
                logger.exception("refund notify settle failed for %s", out_refund_no)
            return Response(status_code=200)

    # 旧数据兜底：无 refund_requests 记录的历史退款回调，仅同步订单状态
    if out_trade_no and refund_status:
        res = await db.execute(select(Order).where(Order.out_trade_no == out_trade_no))
        order = res.scalar_one_or_none()
        if order:
            if refund_status == "SUCCESS" and order.status not in (
                OrderStatus.REFUNDED, OrderStatus.PARTIALLY_REFUNDED,
            ):
                order.status = OrderStatus.REFUNDED
                order.refunded_at = datetime.now(timezone.utc)
            elif refund_status == "CHANGE":
                order.status = OrderStatus.REFUND_CHANGE
        await db.commit()

    return Response(status_code=200)


@router.post("/refund_order/{out_trade_no}")
async def client_refund_order(
    out_trade_no: str,
    req: UserRefundRequest = UserRefundRequest(),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """用户提交退款申请：持久化 refund_requests，进入后台审核流程。"""
    result = await db.execute(
        select(Order).where(Order.out_trade_no == out_trade_no, Order.user_id == user.id)
        .with_for_update()
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")

    try:
        await refund_service.create_user_refund_request(db, order, user, req.reason)
        await db.commit()
    except refund_service.RefundError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "status": order.status,
        "out_trade_no": out_trade_no,
        "message": "退款申请已提交，等待审核",
        "refund_request": refund_service.refund_request_public_dict(
            await refund_service.get_open_request(db, order.id)
        ),
    }


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

    # 处理中的退款：轮询顺带驱动微信状态同步（回调丢失兜底）
    open_req = await refund_service.get_open_request(db, order.id)
    if open_req is not None and open_req.status == "processing":
        try:
            await refund_service.sync_refund_from_wechat(db, open_req)
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("refund status sync failed for order %s", order.out_trade_no)

    latest = await db.execute(
        select(RefundRequest)
        .where(RefundRequest.order_id == order.id)
        .order_by(RefundRequest.requested_at.desc())
        .limit(1)
    )
    latest_req = latest.scalar_one_or_none()

    return {
        "status": order.status,
        "out_refund_no": order.out_refund_no,
        "amount_cny": float(order.amount_cny),
        "refunded_cny": float(order.refunded_cny),
        "refund_request": refund_service.refund_request_public_dict(latest_req),
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
    order_ids = [o.id for o in orders]
    latest_requests: dict[str, RefundRequest] = {}
    if order_ids:
        reqs = await db.execute(
            select(RefundRequest)
            .where(RefundRequest.order_id.in_(order_ids))
            .order_by(RefundRequest.requested_at.asc())
        )
        for r in reqs.scalars().all():
            latest_requests[r.order_id] = r  # asc 迭代 → 保留最新
    return [
        {
            "out_trade_no": o.out_trade_no,
            "amount_usd": float(o.amount_usd),
            "amount_cny": float(o.amount_cny),
            "credits_granted": o.credits_granted,
            "exchange_rate": float(o.exchange_rate) if o.exchange_rate else None,
            "refunded_cny": float(o.refunded_cny),
            "status": o.status,
            "pay_type": o.pay_type,
            "created_at": o.created_at.isoformat(),
            "paid_at": o.paid_at.isoformat() if o.paid_at else None,
            "refund_request": refund_service.refund_request_public_dict(latest_requests.get(o.id)),
        }
        for o in orders
    ]


@router.get("/packages")
async def get_packages(db: AsyncSession = Depends(get_db)):
    """充值信息：点数兑换 + 汇率（含来源语义）+ 限额。"""
    from app.services import config_service
    from app.services import pricing as pricing_service

    rate, rate_source, rate_updated_at = await _get_exchange_rate_meta()
    cfg = await billing.get_image2_config(db)
    price = billing.q6(billing.d(cfg.price_per_call)) if cfg and cfg.price_per_call is not None else None

    credits_per_cny = await config_service.get_credits_per_cny(db)
    min_cny = await config_service.get_config_int(db, "recharge_min_cny")
    max_cny = await config_service.get_config_int(db, "recharge_max_cny")

    unit_credits = None
    try:
        unit_credits, _rule = await pricing_service.resolve_unit_credits(db)
    except pricing_service.NoPriceError:
        pass

    # 汇率来源语义（UI 文案规则）：realtime_* → 参考汇率·每小时更新；fallback_fixed → 结算汇率
    return {
        "exchange_rate": rate,
        "exchange_rate_source": rate_source,
        "exchange_rate_updated_at": rate_updated_at or None,
        "currency": "CNY",
        "credits_per_cny": credits_per_cny,
        "unit_credits": unit_credits,
        "model": {
            "name": "gpt-image-2",
            "display_name": "Image2",
            "price_per_call_usd": str(price) if price else None,
        },
        "presets_cny": [10, 20, 50, 100],
        "limits": {
            "min_total_usd": settings.PAYMENT_MIN_TOTAL_USD,
            "max_total_usd": settings.PAYMENT_MAX_TOTAL_USD,
            "min_cny": min_cny,
            "max_cny": max_cny,
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
        "credits_granted": order.credits_granted,
        "paid_at": order.paid_at.isoformat() if order.paid_at else None,
        "balance_usd": str(billing.q6(billing.d(u.balance_usd))) if u else None,
        "trial_credit_usd": str(billing.q6(billing.d(u.trial_credit_usd))) if u else None,
        "paid_credits": u.paid_credits if u else None,
        "total_credits": (u.paid_credits + u.trial_credits + u.gift_credits) if u else None,
    }
    if assignment_result:
        response["assignment"] = assignment_result
    return response
