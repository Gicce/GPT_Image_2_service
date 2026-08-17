"""已支付订单 → 统一余额入账。

V4 起：支付成功只增加 users.balance_usd（现金余额），写入 RECHARGE 流水。
不再分配 Token、不再按分组记账。状态 ASSIGNED 语义 = 充值已入账。
"""

import logging
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.token import Order, OrderStatus
from app.models.user import User
from app.services import billing

logger = logging.getLogger(__name__)


class AssignmentError(Exception):
    pass


class InvalidOrderStatusError(AssignmentError):
    pass


async def assign_paid_order(
    db: AsyncSession,
    order: Order,
    *,
    auto: bool = False,
) -> Order:
    """将已支付订单入账到用户现金余额（幂等，不 commit，由调用方提交）。

    - ASSIGNED：幂等直接返回
    - 非 PAID：抛 InvalidOrderStatusError
    - 入账金额 = order.amount_usd（Decimal 快照）
    - 同时写 RECHARGE 流水并将 account_type 置为 paid
    """
    if order.status == OrderStatus.ASSIGNED:
        logger.info("Order %s already credited, skipping (auto=%s)", order.out_trade_no, auto)
        return order

    if order.status != OrderStatus.PAID:
        raise InvalidOrderStatusError(
            f"Order {order.out_trade_no} status is {order.status}, cannot credit. Only PAID orders can be credited."
        )

    amount = Decimal(str(order.amount_usd))
    user, txn = await billing.credit_balance(
        db,
        order.user_id,
        amount,
        billing.RECHARGE,
        related_order_id=order.id,
        remark=f"wechat recharge {order.out_trade_no}",
    )
    order.status = OrderStatus.ASSIGNED
    if user.account_type != "paid":
        user.account_type = "paid"

    logger.info(
        "Order %s credited $%s to user %s balance (txn %s, auto=%s)",
        order.out_trade_no, amount, order.user_id, txn.id, auto,
    )
    return order
