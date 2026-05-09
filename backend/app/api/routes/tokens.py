from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.token import TokenInventory
from sqlalchemy import select

router = APIRouter()


@router.get("/stock")
async def get_stock(db: AsyncSession = Depends(get_db)):
    """Public endpoint: returns stock count per package (no token values exposed)"""
    packages = [10, 20, 50, 100]
    result = {}
    for pkg in packages:
        count_result = await db.execute(
            select(TokenInventory).where(
                TokenInventory.package_usd == pkg,
                TokenInventory.is_trial == False,
                TokenInventory.is_assigned == False,
            )
        )
        result[str(pkg)] = len(count_result.scalars().all())
    return result
