from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.auth import _user_info
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.token import UsageLog
from app.models.user import User

router = APIRouter()


@router.get("/me")
async def get_me(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await _user_info(user, db)


@router.get("/me/usage")
async def get_usage(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
    offset: int = 0,
):
    result = await db.execute(
        select(UsageLog)
        .where(UsageLog.user_id == user.id)
        .order_by(UsageLog.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    logs = result.scalars().all()
    return [
        {
            "id": log.id,
            "model": log.model,
            "usage_type": log.usage_type,
            "image_count": log.image_count,
            "input_tokens": log.input_tokens,
            "output_tokens": log.output_tokens,
            "cached_tokens": log.cached_tokens,
            "cost_usd": float(log.cost_usd),
            "created_at": log.created_at.isoformat(),
        }
        for log in logs
    ]
