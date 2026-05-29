from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_optional_user
from app.models.content import AIModel
from app.models.user import User, UserToken
from app.services.account import infer_group_from_model, normalize_model_type

router = APIRouter()


@router.get("")
async def get_models(
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_optional_user),
):
    models = (await db.execute(select(AIModel).where(AIModel.is_enabled == True).order_by(AIModel.sort_order, AIModel.name))).scalars().all()

    user_groups: set[str] = set()
    legacy_access = False
    if user:
        rows = await db.execute(select(UserToken.group).where(UserToken.user_id == user.id))
        user_groups = {row[0] for row in rows.all()}
        if not user_groups:
            if user.account_type == "trial":
                user_groups = {"image"}
            elif bool(user.balance_usd) or bool(user.api_token_id):
                legacy_access = True

    result = []
    for model in models:
        group = infer_group_from_model(model)
        billing_type = model.billing_type
        if not billing_type:
            billing_type = "per_call" if normalize_model_type(model.model_type) in {"image", "postprocess"} else "per_token"
        result.append(
            {
                "id": model.id,
                "name": model.name,
                "display_name": model.display_name,
                "provider": model.provider or "OpenAI",
                "billing_type": billing_type,
                "model_type": normalize_model_type(model.model_type),
                "trial_allowed": bool(model.trial_allowed),
                "group": group,
                "user_has_access": True if legacy_access else (group in user_groups if user_groups else False),
                "price_input": model.price_input or model.price_input_per_m,
                "price_output": model.price_output or model.price_output_per_m,
                "price_cached": model.price_cached or model.price_cached_per_m,
                "price_per_call": model.price_per_call or model.price_per_image,
                "context_window": model.context_window or 32768,
                "supports_tools": bool(model.supports_tools),
                "supports_vision": bool(model.supports_vision),
            }
        )
    return result
