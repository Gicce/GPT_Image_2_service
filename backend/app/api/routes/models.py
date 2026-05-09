from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.models.content import AIModel

router = APIRouter()


@router.get("")
async def get_models(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AIModel).where(AIModel.is_enabled == True).order_by(AIModel.sort_order)
    )
    models = result.scalars().all()
    return [
        {
            "id": m.id,
            "name": m.name,
            "display_name": m.display_name,
            "model_type": m.model_type,
            "trial_allowed": m.trial_allowed,
        }
        for m in models
    ]
