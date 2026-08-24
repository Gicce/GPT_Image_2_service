"""统一退款服务（用户申请审核 + 管理员主动退款共用同一实现）。

资金规则：
- 退款货币永远是人民币分（fen）；USD 冲正只引用订单快照（amount_usd / amount_cny /
  exchange_rate），禁止实时汇率重算。
- 部分退款 USD = amount_usd × (refund_fen / total_fen)；全退（含剩余全退）用
  amount_usd - refunded_usd 差额收口，保证累计 refunded_usd ≤ amount_usd。
- 管理员批准不等于退款成功：APPROVED → 调微信 → PROCESSING → 微信确认 SUCCESS
  才在单一事务内冲正余额、累计订单退款额、写 RECHARGE_REFUND 流水。
- 幂等：settle 以 refund_requests.status CAS（行锁）保证重复回调/重复查询只冲正一次；
  out_refund_no 复用保证微信侧重试幂等。
- 冲正不得制造负余额（debit_balance_for_refund 扣到 0 为止）；审核界面负责向管理员
  展示余额不足风险，实际差额在流水中如实记录。
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import wechatpay
from app.core.config import settings
from app.models.token import Order, OrderStatus, RefundRequest, RefundRequestStatus
from app.models.user import User
from app.services import billing
from app.services import runtime_token as rt

logger = logging.getLogger(__name__)

TWO_PLACES = Decimal("0.01")


class RefundError(Exception):
    """退款业务错误（信息可直接展示给管理员/用户）。"""


def d(value) -> Decimal:
    return billing.d(value)


def q6(value: Decimal) -> Decimal:
    return billing.q6(value)


def cny_to_fen(cny) -> int:
    """人民币元 → 分（Decimal 精确换算，ROUND_HALF_UP）。"""
    return int((d(cny) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def fen_to_cny(fen: int) -> Decimal:
    return (Decimal(fen) / 100).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def order_total_fen(order: Order) -> int:
    return cny_to_fen(order.amount_cny)


def order_refunded_fen(order: Order) -> int:
    return cny_to_fen(order.refunded_cny)


def order_remaining_fen(order: Order) -> int:
    """剩余可退款（分）。"""
    return order_total_fen(order) - order_refunded_fen(order)


def compute_usd_reversal(order: Order, refund_fen: int) -> Decimal:
    """按订单快照把退款分换算为 USD 冲正额（全退用差额收口）。"""
    total_fen = order_total_fen(order)
    refunded_usd = d(order.refunded_usd)
    amount_usd = d(order.amount_usd)
    if refund_fen >= total_fen - order_refunded_fen(order):
        return q6(amount_usd - refunded_usd)
    if total_fen <= 0:
        return Decimal("0")
    return q6(amount_usd * Decimal(refund_fen) / Decimal(total_fen))


async def _order_total_credits(db: AsyncSession, order: Order) -> int:
    """订单到账总点数（credits_granted 快照；旧订单按 USD × legacy 率折算）。"""
    from app.services import config_service

    if order.credits_granted is not None and order.credits_granted > 0:
        return int(order.credits_granted)
    legacy_rate = await config_service.get_legacy_usd_to_credits(db)
    return int((d(order.amount_usd) * Decimal(legacy_rate)).to_integral_value(rounding=ROUND_HALF_UP))


async def compute_credits_reversal(db: AsyncSession, order: Order, refund_fen: int) -> int:
    """退款分 → 点数冲正额（比例换算；全退用差额收口，累计不超总点数）。"""
    from app.models.billing import BillingTransaction

    total_fen = order_total_fen(order)
    total_credits = await _order_total_credits(db, order)
    result = await db.execute(
        select(func.coalesce(func.sum(BillingTransaction.amount_credits), 0)).where(
            BillingTransaction.related_order_id == order.id,
            BillingTransaction.type == billing.RECHARGE_REFUND,
        )
    )
    refunded_credits = int(result.scalar() or 0)
    remaining_credits = max(0, total_credits - refunded_credits)

    if refund_fen >= total_fen - order_refunded_fen(order):
        return remaining_credits
    if total_fen <= 0:
        return 0
    proportional = int(
        (Decimal(total_credits) * Decimal(refund_fen) / Decimal(total_fen))
        .to_integral_value(rounding=ROUND_HALF_UP)
    )
    return min(proportional, remaining_credits)


async def get_open_request(db: AsyncSession, order_id: str) -> RefundRequest | None:
    result = await db.execute(
        select(RefundRequest).where(
            RefundRequest.order_id == order_id,
            RefundRequest.status.in_(RefundRequestStatus.OPEN),
        )
    )
    return result.scalar_one_or_none()


async def get_request_by_out_refund_no(db: AsyncSession, out_refund_no: str) -> RefundRequest | None:
    result = await db.execute(
        select(RefundRequest).where(RefundRequest.out_refund_no == out_refund_no)
    )
    return result.scalar_one_or_none()


# ── 用户申请 ──────────────────────────────────────────────────────

async def create_user_refund_request(
    db: AsyncSession, order: Order, user: User, reason: str | None
) -> RefundRequest:
    """用户提交退款申请（全额剩余可退），持久化并驱动订单进入 refund_requested。"""
    if order.user_id != user.id:
        raise RefundError("只能退款自己的订单")
    if await get_open_request(db, order.id) is not None:
        raise RefundError("该订单已有退款申请处理中，请等待审核结果")
    if order.status not in (OrderStatus.PAID, OrderStatus.ASSIGNED, OrderStatus.PARTIALLY_REFUNDED):
        raise RefundError("当前订单状态不支持退款申请")

    remaining_fen = order_remaining_fen(order)
    if remaining_fen <= 0:
        raise RefundError("订单已无可退款金额")

    now = datetime.now(timezone.utc)
    req = RefundRequest(
        id=str(uuid.uuid4()),
        order_id=order.id,
        user_id=order.user_id,
        source="user",
        requested_amount_fen=remaining_fen,
        requested_amount_cny=fen_to_cny(remaining_fen),
        requested_amount_usd=compute_usd_reversal(order, remaining_fen),
        reason=(reason or "").strip() or None,
        status=RefundRequestStatus.REQUESTED,
        requested_at=now,
    )
    db.add(req)

    order.status_before_refund = order.status
    order.status = OrderStatus.REFUND_REQUESTED
    order.refund_requested_at = now
    await db.flush()
    logger.info(
        "refund request created: order=%s user=%s amount_fen=%d",
        order.out_trade_no, user.id, remaining_fen,
    )
    return req


# ── 审核 ─────────────────────────────────────────────────────────

async def approve_refund_request(
    db: AsyncSession, req: RefundRequest, *, admin: str, review_note: str | None = None
) -> RefundRequest:
    """管理员批准：requested → approved，生成唯一 out_refund_no（重试复用）。"""
    if req.status != RefundRequestStatus.REQUESTED:
        raise RefundError(f"申请当前状态为 {req.status}，无法批准")

    order = await db.get(Order, req.order_id)
    if order is None:
        raise RefundError("订单不存在")
    if order_remaining_fen(order) < req.requested_amount_fen:
        raise RefundError("订单剩余可退款金额已小于申请金额，请刷新后重新处理")

    req.status = RefundRequestStatus.APPROVED
    req.reviewed_at = datetime.now(timezone.utc)
    req.reviewed_by = admin
    req.review_note = review_note or req.review_note
    if not req.out_refund_no:
        req.out_refund_no = (
            f"RF{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:8].upper()}"
        )
    await db.flush()
    return req


async def reject_refund_request(
    db: AsyncSession, req: RefundRequest, *, admin: str, review_note: str | None
) -> Order:
    """管理员拒绝：申请 → rejected，订单回到申请前状态。"""
    if req.status != RefundRequestStatus.REQUESTED:
        raise RefundError(f"申请当前状态为 {req.status}，无法拒绝")

    order = await db.get(Order, req.order_id)
    if order is None:
        raise RefundError("订单不存在")

    req.status = RefundRequestStatus.REJECTED
    req.reviewed_at = datetime.now(timezone.utc)
    req.reviewed_by = admin
    req.review_note = review_note

    order.status = order.status_before_refund or OrderStatus.PAID
    order.status_before_refund = None
    await db.flush()
    return order


# ── 微信退款执行与结算 ────────────────────────────────────────────

def _dev_simulate_enabled() -> bool:
    """开发环境未配置微信支付时模拟退款成功（生产绝不走此分支）。"""
    return settings.APP_ENV == "development" and not wechatpay.is_configured()


async def execute_refund(db: AsyncSession, req: RefundRequest) -> RefundRequest:
    """执行微信退款（approved → processing/success/failed）。

    幂等：processing/success 直接返回；failed 可重试（复用同一 out_refund_no）。
    """
    if req.status in (RefundRequestStatus.PROCESSING, RefundRequestStatus.SUCCESS):
        return req
    if req.status not in (RefundRequestStatus.APPROVED, RefundRequestStatus.FAILED):
        raise RefundError(f"申请当前状态为 {req.status}，无法执行退款")

    order = await db.get(Order, req.order_id)
    if order is None:
        raise RefundError("订单不存在")
    total_fen = order_total_fen(order)

    if _dev_simulate_enabled():
        logger.info("dev mode: simulate wechat refund success for %s", req.out_refund_no)
        req.status = RefundRequestStatus.PROCESSING
        order.status = OrderStatus.REFUNDING
        await db.flush()
        return await settle_refund_success(db, req, wechat_refund_id=f"DEV{uuid.uuid4().hex[:24].upper()}")

    refund_data = {
        "out_refund_no": req.out_refund_no,
        "out_trade_no": order.out_trade_no,
        "reason": (req.reason or "refund")[:80],
        "amount": {
            "refund": req.requested_amount_fen,
            "total": total_fen,
            "currency": "CNY",
        },
    }
    if settings.WECHAT_REFUND_NOTIFY_URL:
        refund_data["notify_url"] = settings.WECHAT_REFUND_NOTIFY_URL

    req.status = RefundRequestStatus.PROCESSING
    order.status = OrderStatus.REFUNDING
    await db.flush()

    try:
        code, wx_result = await wechatpay.wechatpay_request(
            "/v3/refund/domestic/refunds", method="POST", data=refund_data
        )
    except Exception as exc:
        await mark_refund_failed(db, req, f"wechat request error: {exc}")
        return req

    if code != 200:
        detail = wx_result[:200] if isinstance(wx_result, str) else str(wx_result)
        await mark_refund_failed(db, req, f"wechat refund rejected ({code}): {detail}")
        return req

    try:
        data = json.loads(wx_result) if isinstance(wx_result, str) else (wx_result or {})
    except (TypeError, ValueError):
        data = {}

    wx_status = data.get("status")
    req.wechat_refund_id = data.get("refund_id") or req.wechat_refund_id
    if wx_status == "SUCCESS":
        return await settle_refund_success(db, req, wechat_refund_id=data.get("refund_id"))
    if wx_status in ("ABNORMAL", "CLOSED"):
        await mark_refund_failed(db, req, f"wechat refund status {wx_status}")
    # PROCESSING / 未知：保持 processing，等回调或主动查询
    await db.flush()
    return req


async def settle_refund_success(
    db: AsyncSession, req: RefundRequest, *, wechat_refund_id: str | None = None
) -> RefundRequest:
    """微信确认退款 SUCCESS 后的资金冲正（单一事务，CAS 幂等）。

    - 现金余额冲正（不得为负，扣到 0 为止，差额如实入流水）
    - 订单 refunded_cny / refunded_usd 累计；状态 → refunded / partially_refunded
    - 全额退完且用户无其它付费资格 → 释放 paid Token（回落试用或 normal）
    """
    lock = await db.execute(
        select(RefundRequest).where(RefundRequest.id == req.id).with_for_update()
    )
    req = lock.scalar_one()
    if req.status == RefundRequestStatus.SUCCESS:
        return req  # 幂等：重复回调只结算一次
    if req.status not in (RefundRequestStatus.PROCESSING, RefundRequestStatus.APPROVED):
        raise RefundError(f"申请当前状态为 {req.status}，无法结算")

    order_lock = await db.execute(select(Order).where(Order.id == req.order_id).with_for_update())
    order = order_lock.scalar_one_or_none()
    if order is None:
        raise RefundError("订单不存在")

    refund_fen = req.requested_amount_fen
    remaining_before = order_remaining_fen(order)
    if refund_fen > remaining_before:
        refund_fen = remaining_before  # 防御：多次并发结算时以剩余额度收口
    if refund_fen <= 0:
        req.status = RefundRequestStatus.SUCCESS
        req.completed_at = datetime.now(timezone.utc)
        await db.flush()
        return req

    reversal_usd = compute_usd_reversal(order, refund_fen)
    reversal_credits = await compute_credits_reversal(db, order, refund_fen)

    user, txn, actual_credits = await billing.debit_paid_credits_for_refund(
        db, req.user_id, reversal_credits,
        related_order_id=order.id,
        remark=f"wechat refund {order.out_trade_no} ({fen_to_cny(refund_fen)} CNY, -{reversal_credits} credits)",
    )

    order.refunded_cny = fen_to_cny(order_refunded_fen(order) + refund_fen)
    order.refunded_usd = q6(d(order.refunded_usd) + reversal_usd)
    order.out_refund_no = req.out_refund_no
    order.refunded_at = datetime.now(timezone.utc)

    fully_refunded = order_refunded_fen(order) >= order_total_fen(order)
    order.status = OrderStatus.REFUNDED if fully_refunded else OrderStatus.PARTIALLY_REFUNDED
    order.status_before_refund = None

    req.status = RefundRequestStatus.SUCCESS
    req.wechat_refund_id = wechat_refund_id or req.wechat_refund_id
    req.completed_at = datetime.now(timezone.utc)

    if fully_refunded:
        await _maybe_downgrade_after_full_refund(db, req.user_id)

    await db.flush()
    logger.info(
        "refund settled: order=%s refund_fen=%d reversal_credits=%d reversal_usd=%s status=%s",
        order.out_trade_no, refund_fen, reversal_credits, reversal_usd, order.status,
    )
    return req


async def mark_refund_failed(db: AsyncSession, req: RefundRequest, reason: str) -> RefundRequest:
    """微信退款失败/异常：申请 → failed，订单回到可退款状态（可重试）。"""
    lock = await db.execute(
        select(RefundRequest).where(RefundRequest.id == req.id).with_for_update()
    )
    req = lock.scalar_one()
    if req.status == RefundRequestStatus.SUCCESS:
        return req
    req.status = RefundRequestStatus.FAILED
    req.failure_reason = (reason or "unknown")[:255]
    order = await db.get(Order, req.order_id)
    if order is not None:
        prev = order.status_before_refund
        if prev in (OrderStatus.PAID, OrderStatus.ASSIGNED, OrderStatus.PARTIALLY_REFUNDED):
            order.status = prev
        else:
            # 兜底：按累计退款额推导
            order.status = (
                OrderStatus.PARTIALLY_REFUNDED
                if order_refunded_fen(order) > 0
                else OrderStatus.ASSIGNED
            )
    await db.flush()
    logger.warning("refund failed: order_req=%s reason=%s", req.id, reason)
    return req


async def sync_refund_from_wechat(db: AsyncSession, req: RefundRequest) -> RefundRequest:
    """主动查询微信退款状态并结算（回调丢失兜底 + 客户端轮询驱动）。"""
    if req.status not in (RefundRequestStatus.PROCESSING,):
        return req
    if not req.out_refund_no:
        return req

    try:
        code, result = await wechatpay.wechatpay_request(
            f"/v3/refund/domestic/refunds/{req.out_refund_no}"
        )
    except Exception as exc:
        logger.warning("refund query error for %s: %s", req.out_refund_no, exc)
        return req
    if code != 200:
        return req
    try:
        data = json.loads(result) if isinstance(result, str) else {}
    except (TypeError, ValueError):
        return req

    wx_status = data.get("status")
    if wx_status == "SUCCESS":
        return await settle_refund_success(db, req, wechat_refund_id=data.get("refund_id"))
    if wx_status in ("ABNORMAL", "CLOSED"):
        return await mark_refund_failed(db, req, f"wechat refund status {wx_status}")
    return req


# ── 管理员主动退款 ────────────────────────────────────────────────

async def admin_direct_refund(
    db: AsyncSession,
    order: Order,
    *,
    admin: str,
    refund_amount_cny: Decimal | None = None,
    reason: str | None = None,
) -> RefundRequest:
    """管理员主动退款（不经过用户申请），同一执行/结算链路。"""
    if order.status not in (OrderStatus.PAID, OrderStatus.ASSIGNED, OrderStatus.PARTIALLY_REFUNDED):
        raise RefundError("只能退款已支付/已入账的订单")
    if await get_open_request(db, order.id) is not None:
        raise RefundError("该订单已有退款申请处理中")

    remaining_fen = order_remaining_fen(order)
    if remaining_fen <= 0:
        raise RefundError("订单已无可退款金额")

    if refund_amount_cny is not None:
        refund_fen = cny_to_fen(refund_amount_cny)
        if refund_fen <= 0 or refund_fen > remaining_fen:
            raise RefundError(
                f"退款金额需在 ¥{fen_to_cny(1)} ~ ¥{fen_to_cny(remaining_fen)} 之间"
            )
    else:
        refund_fen = remaining_fen

    now = datetime.now(timezone.utc)
    req = RefundRequest(
        id=str(uuid.uuid4()),
        order_id=order.id,
        user_id=order.user_id,
        source="admin",
        requested_amount_fen=refund_fen,
        requested_amount_cny=fen_to_cny(refund_fen),
        requested_amount_usd=compute_usd_reversal(order, refund_fen),
        reason=(reason or "admin refund").strip()[:255],
        status=RefundRequestStatus.APPROVED,
        requested_at=now,
        reviewed_at=now,
        reviewed_by=admin,
        out_refund_no=(
            f"RF{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:8].upper()}"
        ),
    )
    db.add(req)
    order.status_before_refund = order.status
    await db.flush()
    return await execute_refund(db, req)


# ── 全额退款后的 Token 降级 ──────────────────────────────────────

async def _maybe_downgrade_after_full_refund(db: AsyncSession, user_id: str) -> None:
    """全额退完且用户不再具备付费资格时：释放 paid 绑定；有试用额度则回落试用 Token。"""
    user = await db.get(User, user_id)
    if user is None:
        return
    if billing.d(user.balance_usd) > 0:
        return
    still_paid = await db.execute(
        select(Order.id).where(
            Order.user_id == user_id,
            Order.status.in_((
                OrderStatus.PAID, OrderStatus.ASSIGNED, OrderStatus.PARTIALLY_REFUNDED,
            )),
        ).limit(1)
    )
    if still_paid.scalar_one_or_none() is not None:
        return

    await rt.release_user_token(db, user_id, source="refund_downgrade")
    if billing.d(user.trial_credit_usd) > 0:
        trial_token = await rt.resolve_default_token(db, is_trial=True)
        if trial_token is not None:
            await rt.bind_token_to_user(db, user_id, trial_token, source="refund_downgrade")
            user.account_type = "trial"
        else:
            user.account_type = "normal"
    else:
        user.account_type = "normal"


def refund_request_public_dict(req: RefundRequest | None) -> dict | None:
    if req is None:
        return None
    return {
        "id": req.id,
        "source": req.source,
        "status": req.status,
        "requested_amount_cny": float(req.requested_amount_cny),
        "requested_amount_usd": float(req.requested_amount_usd),
        "reason": req.reason,
        "review_note": req.review_note,
        "out_refund_no": req.out_refund_no,
        "failure_reason": req.failure_reason,
        "requested_at": req.requested_at.isoformat() if req.requested_at else None,
        "reviewed_at": req.reviewed_at.isoformat() if req.reviewed_at else None,
        "completed_at": req.completed_at.isoformat() if req.completed_at else None,
    }
