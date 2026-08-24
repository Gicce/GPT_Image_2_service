"""已支付订单 → CY 点数入账 + 自动绑定默认正式 Runtime Token。

V4.2 起：支付成功 = paid_credits 入账（RECHARGE 流水，amount_credits = 订单
credits_granted 快照）+ 检查用户正式 Token 绑定，无 active 正式绑定时自动绑定
默认正式 Token（默认 Token 后续切换不影响已绑定用户）。状态 ASSIGNED = 已入账。
旧订单（credits_granted 为 NULL）按 amount_usd × legacy 兑换率折算，与旧口径一致。
"""

import logging
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.token import Order, OrderStatus
from app.models.user import User
from app.services import billing
from app.services import config_service
from app.services import runtime_token as rt

logger = logging.getLogger(__name__)


class AssignmentError(Exception):
    pass


class InvalidOrderStatusError(AssignmentError):
    pass


async def _order_credits(db: AsyncSession, order: Order) -> int:
    """订单到账点数：优先 credits_granted 快照；旧订单按 USD × legacy 率折算。"""
    if order.credits_granted is not None and order.credits_granted > 0:
        return int(order.credits_granted)
    legacy_rate = await config_service.get_legacy_usd_to_credits(db)
    return int((Decimal(str(order.amount_usd)) * Decimal(legacy_rate)).to_integral_value(rounding=ROUND_HALF_UP))


async def assign_paid_order(
    db: AsyncSession,
    order: Order,
    *,
    auto: bool = False,
) -> Order:
    """将已支付订单入账到用户正式点数并自动绑定 Runtime Token（幂等，不 commit）。"""
    if order.status == OrderStatus.ASSIGNED:
        logger.info("Order %s already credited, skipping (auto=%s)", order.out_trade_no, auto)
        return order

    if order.status != OrderStatus.PAID:
        raise InvalidOrderStatusError(
            f"Order {order.out_trade_no} status is {order.status}, cannot credit. Only PAID orders can be credited."
        )

    credits = await _order_credits(db, order)
    user, txn = await billing.credit_paid_credits(
        db,
        order.user_id,
        credits,
        billing.RECHARGE,
        related_order_id=order.id,
        remark=f"wechat recharge {order.out_trade_no} (+{credits} credits)",
    )
    order.status = OrderStatus.ASSIGNED
    if user.account_type != "paid":
        user.account_type = "paid"

    # 支付成功自动绑定正式 Token（用户无需再手动领取）
    await rt.ensure_paid_assignment(db, order.user_id)

    logger.info(
        "Order %s credited %d credits to user %s (txn %s, auto=%s)",
        order.out_trade_no, credits, order.user_id, txn.id, auto,
    )
    return order
