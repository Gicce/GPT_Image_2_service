from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services import config_service
from app.services import trial as trial_service

router = APIRouter()


@router.get("/trial-stock")
async def get_trial_stock(db: AsyncSession = Depends(get_db)):
    """公开端点：试用通道可用性与注册展示策略。

    保留 remaining/available 字段形状以兼容旧客户端：
    available=true 时 remaining=1，否则 remaining=0。
    """
    availability = await trial_service.trial_availability(db)
    available = availability["available"]
    return {
        # 兼容旧客户端；共享 Token 模式下它只代表可用/不可用，不是实际名额。
        "remaining": 1 if available else 0,
        "available": available,
        "reason": availability["reason"],
        "grant_credits": await config_service.get_config_int(db, "trial_grant_credits"),
        "valid_days": await config_service.get_config_int(db, "trial_valid_days"),
        "campaign_version": await config_service.get_config_int(db, "trial_campaign_version"),
    }
