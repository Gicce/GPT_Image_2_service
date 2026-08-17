from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.models.token import TokenInventory

router = APIRouter()


@router.get("/trial-stock")
async def get_trial_stock(db: AsyncSession = Depends(get_db)):
    """公开端点：统一 Token 池中的试用名额余量（注册试用闸门）。"""
    result = await db.execute(
        select(func.count()).select_from(TokenInventory).where(
            TokenInventory.is_trial == True,
            TokenInventory.is_assigned == False,
            TokenInventory.is_disabled == False,
        )
    )
    remaining = result.scalar()
    return {"remaining": remaining, "available": remaining > 0}
