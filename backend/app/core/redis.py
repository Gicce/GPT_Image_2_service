import asyncio
import logging

import redis.asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


async def init_redis():
    """Initialize Redis connection"""
    get_redis()


async def auto_approve_refund(out_trade_no: str):
    """自动批准退款（15分钟超时后调用）"""
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.models.token import Order, OrderStatus
    from app.core.wechatpay import wechatpay_request
    from app.services import billing
    from decimal import Decimal
    from datetime import datetime, timezone
    import uuid

    logger.info(f"Auto-approving refund for order {out_trade_no}")

    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(
                select(Order).where(Order.out_trade_no == out_trade_no).with_for_update()
            )
            order = result.scalar_one_or_none()
            if not order or order.status != OrderStatus.REFUNDING:
                logger.info(f"Order {out_trade_no} not in REFUNDING state, skipping auto-approve")
                return

            # 冲正：从统一现金余额扣回充值金额（余额不足扣到 0 为止），写流水
            if order.status_before_refund == OrderStatus.ASSIGNED:
                await billing.debit_balance_for_refund(
                    db, order.user_id, Decimal(str(order.amount_usd)),
                    related_order_id=order.id,
                    remark=f"auto refund {out_trade_no}",
                )

            # 调用微信退款
            out_refund_no = f"RF{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:8].upper()}"
            total_fee = int(round(float(order.amount_cny) * 100))
            refund_data = {
                "out_refund_no": out_refund_no,
                "out_trade_no": out_trade_no,
                "reason": "auto approved (15min timeout)",
                "amount": {"refund": total_fee, "total": total_fee, "currency": "CNY"},
            }
            if settings.WECHAT_REFUND_NOTIFY_URL:
                refund_data["notify_url"] = settings.WECHAT_REFUND_NOTIFY_URL

            code, wx_result = await wechatpay_request("/v3/refund/domestic/refunds", method="POST", data=refund_data)
            if code != 200:
                await db.rollback()
                logger.error(f"Auto-approve WeChat refund failed for {out_trade_no}: {wx_result}")
                return

            order.status = OrderStatus.REFUNDED
            order.out_refund_no = out_refund_no
            order.refunded_at = datetime.now(timezone.utc)
            await db.commit()
            logger.info(f"Auto-approved refund for {out_trade_no}")
        except Exception:
            await db.rollback()
            logger.exception(f"Auto-approve refund error for {out_trade_no}")


async def start_keyspace_listener():
    """监听 Redis keyspace 过期事件，触发自动退款"""
    r = get_redis()
    try:
        await r.config_set("notify-keyspace-events", "Ex")
    except Exception as e:
        logger.warning(f"Failed to set Redis keyspace config: {e}")

    pubsub = r.pubsub()
    await pubsub.psubscribe("__keyevent@0__:expired")

    logger.info("Redis keyspace listener started for refund auto-approve")

    async for message in pubsub.listen():
        if message["type"] == "pmessage":
            key = message["data"]
            if isinstance(key, str) and key.startswith("refund:auto:"):
                out_trade_no = key[len("refund:auto:"):]
                try:
                    await auto_approve_refund(out_trade_no)
                except Exception as e:
                    logger.error(f"Auto-approve refund error for {out_trade_no}: {e}")


async def recover_pending_refunds():
    """服务器启动时恢复未处理的退款（超时的立即自动退款，未超时的重新设置过期键）"""
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.models.token import Order, OrderStatus
    from datetime import datetime, timezone

    logger.info("Recovering pending refunds...")

    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(
                select(Order).where(Order.status == OrderStatus.REFUNDING)
            )
            orders = result.scalars().all()

            now = datetime.now(timezone.utc)
            r = get_redis()

            for order in orders:
                elapsed = (now - order.refund_requested_at).total_seconds() if order.refund_requested_at else 9999
                if elapsed >= 900:
                    try:
                        await auto_approve_refund(order.out_trade_no)
                    except Exception as e:
                        logger.error(f"Recovery auto-approve error for {order.out_trade_no}: {e}")
                else:
                    remaining = int(900 - elapsed)
                    await r.setex(f"refund:auto:{order.out_trade_no}", remaining, "1")
                    logger.info(f"Recovery: set refund:auto:{order.out_trade_no} TTL={remaining}s")

            logger.info(f"Recovery complete, processed {len(orders)} pending refunds")
        except Exception:
            logger.exception("Error in recover_pending_refunds")
