from typing import Optional
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.security import get_optional_user
from app.models.content import AIModel
from app.models.user import User, UserToken

router = APIRouter()


@router.get("")
async def get_models(
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_optional_user),
):
    result = await db.execute(
        select(AIModel).where(AIModel.is_enabled == True).order_by(AIModel.sort_order)
    )
    models = result.scalars().all()

    user_groups: set = set()
    if user:
        ut_result = await db.execute(
            select(UserToken.group).where(UserToken.user_id == user.id)
        )
        user_groups = {r[0] for r in ut_result.all()}

    return [
        {
            "id": m.id,
            "name": m.name,
            "display_name": m.display_name,
            "provider": m.provider,
            "billing_type": m.billing_type,
            "model_type": m.model_type,
            "trial_allowed": m.trial_allowed,
            "group": m.group,
            "user_has_access": m.group in user_groups if user_groups else False,
        }
        for m in models
    ]
