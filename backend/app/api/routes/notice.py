import json

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.redis import get_redis
from app.models.content import Notice

router = APIRouter()


@router.get("")
async def get_notice(db: AsyncSession = Depends(get_db)):
    redis = get_redis()
    cached = await redis.get("notice_content")
    if cached is not None:
        return json.loads(cached)

    result = await db.execute(select(Notice).limit(1))
    notice = result.scalar_one_or_none()
    data = {
        "content": notice.content if notice else "",
        "is_active": notice.is_active if notice else False,
    }
    await redis.setex("notice_content", 180, json.dumps(data))
    return data
