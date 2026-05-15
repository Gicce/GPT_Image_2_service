from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.token import TokenInventory

router = APIRouter()


@router.get("/stock")
async def get_stock(db: AsyncSession = Depends(get_db)):
    """Public endpoint: returns stock count per token_type + package"""
    packages = [10, 20, 50, 100]
    result = {}
    for token_type in ("image", "chat"):
        result[token_type] = {}
        for pkg in packages:
            count_result = await db.execute(
                select(func.count()).select_from(TokenInventory).where(
                    TokenInventory.package_usd == pkg,
                    TokenInventory.token_type == token_type,
                    TokenInventory.is_trial == False,
                    TokenInventory.is_assigned == False,
                )
            )
            result[token_type][str(pkg)] = count_result.scalar()
    return result


@router.get("/trial-stock")
async def get_trial_stock(db: AsyncSession = Depends(get_db)):
    """Public endpoint: returns trial token (image only) availability"""
    result = await db.execute(
        select(func.count()).select_from(TokenInventory).where(
            TokenInventory.is_trial == True,
            TokenInventory.token_type == "image",
            TokenInventory.is_assigned == False,
        )
    )
    remaining = result.scalar()
    return {"remaining": remaining, "available": remaining > 0}
