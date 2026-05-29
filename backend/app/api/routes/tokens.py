from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.token import TokenInventory

router = APIRouter()


@router.get("/stock")
async def get_stock(db: AsyncSession = Depends(get_db)):
    groups = ["image", "agent", "postprocess"]
    result = {}
    for group in groups:
        count_result = await db.execute(
            select(func.count()).select_from(TokenInventory).where(
                TokenInventory.group == group,
                TokenInventory.is_trial == False,
                TokenInventory.is_assigned == False,
            )
        )
        result[group] = count_result.scalar() or 0
    return result


@router.get("/trial-stock")
async def get_trial_stock(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(func.count()).select_from(TokenInventory).where(
            TokenInventory.is_trial == True,
            TokenInventory.group == "image",
            TokenInventory.is_assigned == False,
        )
    )
    count = result.scalar() or 0
    return {"remaining": count, "count": count, "available": count > 0}
