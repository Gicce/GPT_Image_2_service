from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.models.token import TokenInventory
from app.models.content import Group

router = APIRouter()


@router.get("/stock")
async def get_stock(db: AsyncSession = Depends(get_db)):
    """Public endpoint: returns available token stock per group."""
    groups_result = await db.execute(select(Group).order_by(Group.sort_order))
    groups = groups_result.scalars().all()
    result = {}
    for group in groups:
        count_result = await db.execute(
            select(func.count()).select_from(TokenInventory).where(
                TokenInventory.group == group.name,
                TokenInventory.is_trial == False,
                TokenInventory.is_assigned == False,
            )
        )
        result[group.name] = count_result.scalar()
    return result


@router.get("/trial-stock")
async def get_trial_stock(db: AsyncSession = Depends(get_db)):
    """Public endpoint: returns trial token (image only) availability"""
    result = await db.execute(
        select(func.count()).select_from(TokenInventory).where(
            TokenInventory.is_trial == True,
            TokenInventory.group == "image",
            TokenInventory.is_assigned == False,
        )
    )
    remaining = result.scalar()
    return {"remaining": remaining, "available": remaining > 0}
