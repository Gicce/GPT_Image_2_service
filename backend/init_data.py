"""
Safe seed script: creates missing tables and inserts default groups/models.
Does NOT drop or destroy any existing data.
Usage: cd backend && python init_data.py
"""
import asyncio

from app.core.database import engine, Base
from app.models.content import AIModel, Notice, Prompt, Group
from app.models.user import User, UserToken
from app.models.token import TokenInventory, Order, UsageLog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select


DEFAULT_GROUPS = [
    {"name": "sora", "description": "Sora 项目组", "sort_order": 1},
    {"name": "codex", "description": "Codex 项目组", "sort_order": 2},
    {"name": "codex-sale", "description": "Codex 优惠组", "sort_order": 3},
]


DEFAULT_MODELS = [
    {
        "name": "gpt-image-2",
        "display_name": "GPT Image 2",
        "provider": "OpenAI",
        "billing_type": "per_call",
        "model_type": "image",
        "group": "sora",
        "is_enabled": True,
        "trial_allowed": True,
        "price_per_call": "0.040",
        "sort_order": 1,
    },
    {
        "name": "gpt-5.5",
        "display_name": "GPT-5.5",
        "provider": "OpenAI",
        "billing_type": "per_token",
        "model_type": "chat",
        "group": "codex",
        "is_enabled": True,
        "trial_allowed": False,
        "price_input": "0.0025",
        "price_output": "0.0150",
        "price_cached": "0.0003",
        "sort_order": 2,
    },
    {
        "name": "gpt-5.5",
        "display_name": "GPT-5.5 (优惠)",
        "provider": "OpenAI",
        "billing_type": "per_token",
        "model_type": "chat",
        "group": "codex-sale",
        "is_enabled": True,
        "trial_allowed": False,
        "price_input": "0.0020",
        "price_output": "0.0120",
        "price_cached": "0.0002",
        "sort_order": 3,
    },
]


async def seed():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Tables ensured.")

    async with AsyncSession(engine) as session:
        for g in DEFAULT_GROUPS:
            result = await session.execute(select(Group).where(Group.name == g["name"]))
            if not result.scalar_one_or_none():
                session.add(Group(**g))
                print(f"  + group: {g['name']}")
            else:
                print(f"  = group: {g['name']} (exists)")

        for m in DEFAULT_MODELS:
            result = await session.execute(
                select(AIModel).where(AIModel.name == m["name"], AIModel.group == m["group"])
            )
            if not result.scalar_one_or_none():
                session.add(AIModel(**m))
                print(f"  + model: {m['name']} ({m['group']})")
            else:
                print(f"  = model: {m['name']} ({m['group']}) (exists)")

        await session.commit()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(seed())