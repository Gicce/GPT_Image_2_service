from typing import Optional
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.security import get_optional_user
from app.models.content import AIModel
from app.models.user import User

router = APIRouter()


@router.get("")
async def get_models(
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_optional_user),
):
    """公开模型列表：V4 起仅返回 Image2 一个模型（只读，无新增/删除）。

    保留 group/model_type 等字段形态以兼容客户端分组映射逻辑，
    但值固定为 image 单模型语义。
    """
    result = await db.execute(select(AIModel).where(AIModel.is_enabled == True))
    models = result.scalars().all()

    has_balance = False
    if user:
        has_balance = (user.balance_usd + user.trial_credit_usd) > 0

    return [
        {
            "id": m.id,
            "name": m.name,
            "display_name": m.display_name,
            "provider": m.provider,
            "billing_type": "per_call",
            "model_type": "image",
            "trial_allowed": m.trial_allowed,
            "group": "image",
            "user_has_access": has_balance,
            "price_per_call": str(m.price_per_call) if m.price_per_call is not None else None,
            "currency": m.currency,
            "supports_tools": False,
            "supports_vision": False,
            "rechargeable": True,
        }
        for m in models
        if m.name == "gpt-image-2"
    ]
