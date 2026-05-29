from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.content import Prompt

router = APIRouter()


@router.get("")
async def get_prompts(db: AsyncSession = Depends(get_db)):
    prompts = (
        await db.execute(
            select(Prompt)
            .where(Prompt.is_active == True)
            .order_by(Prompt.category, Prompt.sort_order, Prompt.created_at)
        )
    ).scalars().all()
    return [
        {
            "id": prompt.id,
            "category": prompt.category,
            "title": prompt.title,
            "content": prompt.content,
        }
        for prompt in prompts
    ]
