from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content import AIModel, Group
from app.models.token import TokenInventory
from app.models.user import User, UserToken

DEFAULT_GROUP_FALLBACKS = {
    "image": "Image generation credits",
    "agent": "Agent chat credits",
    "postprocess": "Image postprocess credits",
}
MODEL_TYPE_MAP = {"chat": "agent"}


def normalize_model_type(model_type: str | None) -> str:
    return MODEL_TYPE_MAP.get(model_type or "", model_type or "agent")


def infer_group_from_model(model: AIModel) -> str:
    if model.group:
        return model.group
    model_type = normalize_model_type(model.model_type)
    if model_type == "image":
        return "image"
    if model_type == "postprocess":
        return "postprocess"
    return "agent"


async def list_charge_groups(db: AsyncSession) -> list[dict]:
    group_rows = (await db.execute(select(Group).order_by(Group.sort_order, Group.name))).scalars().all()
    if group_rows:
        return [
            {"name": row.name, "description": row.description or DEFAULT_GROUP_FALLBACKS.get(row.name, "")}
            for row in group_rows
        ]

    models = (
        await db.execute(
            select(AIModel).where(AIModel.is_enabled == True).order_by(AIModel.sort_order, AIModel.name)
        )
    ).scalars().all()
    seen: set[str] = set()
    groups: list[dict] = []
    for model in models:
        group = infer_group_from_model(model)
        if group in seen:
            continue
        seen.add(group)
        groups.append({"name": group, "description": DEFAULT_GROUP_FALLBACKS.get(group, "")})
    return groups


async def allocate_token_for_group(db: AsyncSession, user: User, group: str, allow_trial: bool = False) -> str | None:
    if user.api_token_id:
        existing = await db.execute(select(TokenInventory).where(TokenInventory.id == user.api_token_id))
        token = existing.scalar_one_or_none()
        if token:
            if not token.group:
                token.group = group
            return token.id

    stmt = select(TokenInventory).where(TokenInventory.group == group, TokenInventory.is_assigned == False)
    if allow_trial:
        stmt = stmt.where(TokenInventory.is_trial == True)
    else:
        stmt = stmt.where(TokenInventory.is_trial == False)
    token = (await db.execute(stmt.limit(1))).scalar_one_or_none()

    if token is None and not allow_trial:
        token = (
            await db.execute(
                select(TokenInventory)
                .where(TokenInventory.is_trial == False, TokenInventory.is_assigned == False)
                .limit(1)
            )
        ).scalar_one_or_none()
    if token is None and allow_trial:
        token = (
            await db.execute(
                select(TokenInventory)
                .where(TokenInventory.is_trial == True, TokenInventory.is_assigned == False)
                .limit(1)
            )
        ).scalar_one_or_none()
    if token is None:
        return None

    token.is_assigned = True
    token.assigned_to = user.id
    token.assigned_at = datetime.now(timezone.utc)
    if not token.group:
        token.group = group
    if not user.api_token_id:
        user.api_token_id = token.id
    return token.id


async def get_or_create_user_token(
    db: AsyncSession,
    user: User,
    group: str,
    create: bool = False,
    allow_trial: bool = False,
) -> UserToken | None:
    result = await db.execute(select(UserToken).where(UserToken.user_id == user.id, UserToken.group == group))
    user_token = result.scalar_one_or_none()
    if user_token or not create:
        return user_token

    token_id = await allocate_token_for_group(db, user, group, allow_trial=allow_trial)
    if token_id is None:
        return None

    user_token = UserToken(
        user_id=user.id,
        token_id=token_id,
        group=group,
        balance_usd=Decimal("0"),
        is_trial=allow_trial,
    )
    db.add(user_token)
    await db.flush()
    return user_token


async def serialize_user(user: User, db: AsyncSession) -> dict:
    now = datetime.now(timezone.utc)
    trial_expired = bool(
        user.account_type == "trial"
        and user.trial_expires_at
        and user.trial_expires_at.replace(tzinfo=timezone.utc) < now
    )

    token_rows = (
        await db.execute(
            select(UserToken, TokenInventory)
            .join(TokenInventory, UserToken.token_id == TokenInventory.id)
            .where(UserToken.user_id == user.id)
        )
    ).all()
    if token_rows:
        tokens = [
            {
                "group": user_token.group,
                "balance_usd": float(user_token.balance_usd),
                "api_token": token.token_value if token else "",
                "is_trial": bool(user_token.is_trial),
            }
            for user_token, token in token_rows
        ]
    else:
        group_defs = await list_charge_groups(db)
        if user.account_type == "trial":
            group_defs = [group for group in group_defs if group["name"] == "image"] or [
                {"name": "image", "description": DEFAULT_GROUP_FALLBACKS["image"]}
            ]
        token_value = ""
        if user.api_token_id:
            token_row = (
                await db.execute(select(TokenInventory).where(TokenInventory.id == user.api_token_id))
            ).scalar_one_or_none()
            token_value = token_row.token_value if token_row else ""
        if user.balance_usd or token_value:
            tokens = [
                {
                    "group": group_def["name"],
                    "balance_usd": float(user.balance_usd),
                    "api_token": token_value,
                    "is_trial": user.account_type == "trial",
                }
                for group_def in group_defs
            ]
        else:
            tokens = []

    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "account_type": user.account_type,
        "trial_expires_at": user.trial_expires_at.isoformat() if user.trial_expires_at else None,
        "trial_expired": trial_expired,
        "tokens": tokens,
    }
