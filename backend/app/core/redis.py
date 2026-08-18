import asyncio
import logging

import redis.asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None

NOTICE_CHANNEL = "notice:updated"


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


async def init_redis():
    """Initialize Redis connection"""
    get_redis()


async def publish_notice_update() -> None:
    """运营通知变更广播（SSE 通道据此通知在线客户端重新拉取）。"""
    try:
        redis = get_redis()
        await redis.publish(NOTICE_CHANNEL, "updated")
    except Exception:
        logger.exception("publish notice update failed")


async def recover_processing_refunds():
    """服务器启动时恢复微信退款处理中的申请：主动查询微信状态并结算。

    （旧版 15 分钟无人审核自动批准退款的机制已移除——用户申请必须经管理员审核。）
    """
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.token import RefundRequest, RefundRequestStatus
    from app.services import refund as refund_service

    logger.info("Recovering processing refund requests...")

    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(
                select(RefundRequest).where(RefundRequest.status == RefundRequestStatus.PROCESSING)
            )
            requests = result.scalars().all()
            for req in requests:
                try:
                    await refund_service.sync_refund_from_wechat(db, req)
                    await db.commit()
                except Exception:
                    await db.rollback()
                    logger.exception("Recovery settle error for refund %s", req.id)
            if requests:
                logger.info("Recovered %d processing refunds", len(requests))
        except Exception:
            await db.rollback()
            logger.exception("Error in recover_processing_refunds")
