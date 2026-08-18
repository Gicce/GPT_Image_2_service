"""已支付订单 → 统一余额入账 + 自动绑定默认正式 Runtime Token。

V4.1 起：支付成功 = 现金余额入账（RECHARGE 流水）+ 检查用户正式 Token 绑定，
无 active 正式绑定时自动绑定默认正式 Token（默认 Token 后续切换不影响已绑定用户）。
状态 ASSIGNED 语义 = 充值已入账。
"""

import logging
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.token import Order, OrderStatus
from app.models.user import User
from app.services import billing
from app.services import runtime_token as rt

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
    """将已支付订单入账到用户现金余额并自动绑定 Runtime Token（幂等，不 commit）。

    - ASSIGNED：幂等直接返回
    - 非 PAID：抛 InvalidOrderStatusError
    - 入账金额 = order.amount_usd（Decimal 快照）
    - 写 RECHARGE 流水、account_type 置 paid
    - 无 active 正式 Token 绑定 → 绑定默认正式 Token（无默认可用则记日志跳过）
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

    # 支付成功自动绑定正式 Token（用户无需再手动领取）
    await rt.ensure_paid_assignment(db, order.user_id)

    logger.info(
        "Order %s credited $%s to user %s balance (txn %s, auto=%s)",
        order.out_trade_no, amount, order.user_id, txn.id, auto,
    )
    return order
